import streamlit as st
import pandas as pd
import io

# Configuração da página - O Curador
st.set_page_config(page_title="Curador - Auditoria Fiscal Suprema", layout="wide")

def clean_numeric_col(df, col_name):
    """Limpeza técnica de colunas numéricas (decimais BR)."""
    if col_name in df.columns:
        s = df[col_name].astype(str).str.replace(r'\s+', '', regex=True)
        s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df[col_name] = pd.to_numeric(s, errors='coerce').fillna(0.0)
    return df

def auditoria_suprema(row, tipo='saida'):
    """
    MOTOR DE AUDITORIA TOTAL:
    1. ICMS Próprio (Alíquotas, 6403, Base de Cálculo)
    2. ICMS ST (CST vs Valor)
    3. IPI (Industrialização)
    4. PIS/COFINS (Monofásico vs Tributado)
    5. Formação de Preço/Base (Frete+Seguro)
    """
    # DADOS GERAIS
    cfop = str(row['CFOP']).strip().replace('.', '')
    # CST ICMS (2 dígitos)
    cst_icms_full = str(row['CST-ICMS'] if tipo == 'entrada' else row['CST']).strip()
    cst_icms = cst_icms_full[-2:] if len(cst_icms_full) >= 2 else cst_icms_full.zfill(2)
    
    # CST PIS/COF (2 dígitos)
    cst_pis = str(row['CST_PIS'] if tipo == 'entrada' else row['CST_PIS Escriturado']).strip().zfill(2)
    cst_cof = str(row['CST_COF'] if tipo == 'entrada' else row['CST_COF']).strip().zfill(2)
    
    # VALORES
    vlr_prod = row['VPROD'] if tipo == 'entrada' else row['VITEM']
    vlr_icms = row['VLR-ICMS'] if tipo == 'entrada' else row['ICMS']
    bc_icms = row['BC-ICMS'] if tipo == 'entrada' else row['BC_ICMS']
    aliq_icms = 0 if tipo == 'entrada' else row['ALIQ_ICMS']
    vlr_st = row['ICMS-ST'] if tipo == 'entrada' else row['ICMSST']
    vlr_ipi = row['VLR_IPI'] if tipo == 'entrada' else row['IPI']
    vlr_pis = row['VLR_PIS'] if tipo == 'entrada' else row['PIS']
    vlr_cof = row['VLR_COF'] if tipo == 'entrada' else row['COF']
    
    # ACESSÓRIOS (Para validar Base)
    frete = row['FRETE']
    seg = row['SEG']
    desp = row['DESP'] if tipo == 'entrada' else row['OUTRAS']
    desc = row['DESC']
    
    uf_dest = "" if tipo == 'entrada' else str(row['Ufp']).strip().upper()
    
    erros, cliente, dominio = [], [], []

    # ==============================================================================
    # 1. AUDITORIA DE ICMS E IPI (REGRA DE NEGÓCIO)
    # ==============================================================================
    
    # Regra 6403 (Saída)
    if tipo == 'saida' and cfop == '6403' and vlr_icms == 0:
        erros.append("ICMS Próprio não destacado no 6403.")
        cliente.append("Destacar ICMS Próprio (Substituto Tributário).")
        dominio.append("Habilitar ICMS Próprio em operações de ST no Acumulador.")

    # Regra ST (CST vs Valor)
    cst_st_list = ['10', '30', '70', '90']
    if cst_icms in cst_st_list and vlr_st == 0:
        erros.append(f"CST {cst_icms} exige ST, valor zerado.")
        cliente.append("Informar ST.")
        dominio.append("Marcar 'Gera guia ST' no acumulador.")
    elif vlr_st > 0 and cst_icms not in cst_st_list and cst_icms != '60':
        erros.append(f"ST indevido p/ CST {cst_icms}.")
        cliente.append("Corrigir CST ou zerar ST.")

    # Regra IPI Industrial
    if cfop in ['5101', '6101'] and vlr_ipi == 0:
        erros.append("Venda industrial sem IPI.")
        cliente.append("Destacar IPI.")
        dominio.append("Configurar IPI no produto/acumulador.")

    # Regra Interestadual (SP)
    if tipo == 'saida' and cfop.startswith('6'):
        reg_7 = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'RN', 'RO', 'RR', 'SE', 'TO']
        if uf_dest in reg_7 and aliq_icms not in [7.0, 4.0]:
            erros.append(f"Alíquota {aliq_icms}% incorreta p/ {uf_dest} (Meta: 7%).")
            cliente.append(f"Ajustar alíquota interestadual p/ {uf_dest}.")

    # ==============================================================================
    # 2. AUDITORIA DE PIS / COFINS (NOVIDADE)
    # ==============================================================================
    
    # CST Tributado (01, 02 na Saída / 50-56 na Entrada)
    cst_pis_trib = ['01', '02'] if tipo == 'saida' else ['50', '51', '52', '53', '54', '55', '56']
    if cst_pis in cst_pis_trib and vlr_pis == 0:
        erros.append(f"PIS zerado no CST Tributado {cst_pis}.")
        dominio.append("Verificar cadastro de impostos federais no produto.")

    # CST Monofásico/Zero (04, 06 na Saída / 70-75 na Entrada)
    cst_pis_mono = ['04', '05', '06', '07', '08', '09'] if tipo == 'saida' else ['70', '71', '72', '73', '74', '75']
    if cst_pis in cst_pis_mono and vlr_pis > 0:
        erros.append(f"Valor de PIS indevido p/ CST {cst_pis} (Monofásico/Zero).")
        cliente.append("Zerar PIS/COFINS (Produto Monofásico).")
        dominio.append("Configurar Grupo de PIS/COFINS correto no produto.")

    # ==============================================================================
    # 3. AUDITORIA DE FORMAÇÃO DA BASE DE CÁLCULO (COMPLIANCE)
    # ==============================================================================
    
    # A Base do ICMS deve ser >= (Valor Produto + Frete + Seguro + Outras - Desconto)
    # Tolerância de R$ 1,00 para arredondamentos
    soma_base = vlr_prod + frete + seg + desp - desc
    if bc_icms > 0 and (soma_base - bc_icms) > 1.0:
        # Se a base for significativamente menor que a soma dos componentes
        erros.append("BASE ICMS MENOR QUE O TOTAL DA NOTA (Frete não somado?).")
        cliente.append("Verificar se Frete/Seguro compõem a base do ICMS.")
        dominio.append("Marcar 'Frete compõe base de ICMS' no acumulador.")

    return pd.Series({
        'DIAGNÓSTICO_ERRO': " | ".join(erros) if erros else "Escrituração Regular",
        'PARAMETRO_CLIENTE': " | ".join(cliente) if cliente else "-",
        'SOLUÇÃO_CONTABIL': " | ".join(dominio) if dominio else "-"
    })

def main():
    st.title("⚖️ Curador: Auditoria Contábil Suprema (Todos os Impostos)")
    st.markdown("---")
    
    # Upload Centralizado
    c1, c2 = st.columns(2)
    with c1: ent_f = st.file_uploader("📥 Entradas Gerenciais (CSV)", type=["csv"])
    with c2: sai_f = st.file_uploader("📤 Saídas Gerenciais (CSV)", type=["csv"])

    if ent_f and sai_f:
        try:
            # Cabeçalhos originais
            cols_ent = ['NUM_NF', 'DATA_EMISSAO', 'CNPJ', 'UF', 'VLR_NF', 'AC', 'CFOP', 'COD_PROD', 'DESCR', 'NCM', 'UNID', 'VUNIT', 'QTDE', 'VPROD', 'DESC', 'FRETE', 'SEG', 'DESP', 'VC', 'CST-ICMS', 'BC-ICMS', 'VLR-ICMS', 'BC-ICMS-ST', 'ICMS-ST', 'VLR_IPI', 'CST_PIS', 'BC_PIS', 'VLR_PIS', 'CST_COF', 'BC_COF', 'VLR_COF']
            cols_sai = ['NF', 'DATA_EMISSAO', 'CNPJ', 'Ufp', 'VC', 'AC', 'CFOP', 'COD_ITEM', 'DESC_ITEM', 'NCM', 'UND', 'VUNIT', 'QTDE', 'VITEM', 'DESC', 'FRETE', 'SEG', 'OUTRAS', 'VC_ITEM', 'CST', 'BC_ICMS', 'ALIQ_ICMS', 'ICMS', 'BC_ICMSST', 'ICMSST', 'IPI', 'CST_PIS Escriturado', 'BC_PIS', 'PIS', 'CST_COF', 'BC_COF', 'COF']

            df_ent = pd.read_csv(ent_f, sep=';', encoding='latin-1', header=None, names=cols_ent)
            df_sai = pd.read_csv(sai_f, sep=';', encoding='latin-1', header=None, names=cols_sai)

            # Limpeza Numérica Total
            cols_num_ent = ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'VC', 'ICMS-ST', 'VPROD', 'FRETE', 'SEG', 'DESP', 'DESC', 'VLR_PIS', 'VLR_COF']
            cols_num_sai = ['ICMS', 'IPI', 'BC_ICMS', 'VC_ITEM', 'ALIQ_ICMS', 'ICMSST', 'VITEM', 'FRETE', 'SEG', 'OUTRAS', 'DESC', 'PIS', 'COF']
            
            for c in cols_num_ent: df_ent = clean_numeric_col(df_ent, c)
            for c in cols_num_sai: df_sai = clean_numeric_col(df_sai, c)

            # Execução da Auditoria Suprema
            df_ent[['DIAGNÓSTICO_ERRO', 'PARAMETRO_CLIENTE', 'SOLUÇÃO_CONTABIL']] = df_ent.apply(lambda r: auditoria_suprema(r, 'entrada'), axis=1)
            df_sai[['DIAGNÓSTICO_ERRO', 'PARAMETRO_CLIENTE', 'SOLUÇÃO_CONTABIL']] = df_sai.apply(lambda r: auditoria_suprema(r, 'saida'), axis=1)

            # Saldos Finais
            v_icms = df_sai['ICMS'].sum() - df_ent['VLR-ICMS'].sum()
            v_st = df_sai['ICMSST'].sum() - df_ent['ICMS-ST'].sum()
            v_ipi = df_sai['IPI'].sum() - df_ent['VLR_IPI'].sum()
            v_pis = df_sai['PIS'].sum() - df_ent['VLR_PIS'].sum()
            v_cof = df_sai['COF'].sum() - df_ent['VLR_COF'].sum()

            st.success("Auditoria Suprema Concluída!")
            
            # 1. Prévias de Inconsistências (O mais importante)
            st.subheader("🔎 Inconsistências para Ajuste")
            c_sai, c_ent = st.columns(2)
            with c_sai:
                st.markdown("#### 📤 Saídas Irregulares")
                erros_sai = df_sai[df_sai['DIAGNÓSTICO_ERRO'] != "Escrituração Regular"][['NF', 'CFOP', 'DIAGNÓSTICO_ERRO', 'PARAMETRO_CLIENTE']]
                if erros_sai.empty: st.info("Saídas OK.")
                else: st.dataframe(erros_sai, use_container_width=True)
            with c_ent:
                st.markdown("#### 📥 Entradas Irregulares")
                erros_ent = df_ent[df_ent['DIAGNÓSTICO_ERRO'] != "Escrituração Regular"][['NUM_NF', 'CFOP', 'DIAGNÓSTICO_ERRO', 'PARAMETRO_CLIENTE']]
                if erros_ent.empty: st.info("Entradas OK.")
                else: st.dataframe(erros_ent, use_container_width=True)

            # 2. Resumo Financeiro Completo
            st.markdown("---")
            st.subheader("📊 Apuração Geral de Impostos")
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("ICMS Próprio", f"R$ {v_icms:,.2f}")
            m2.metric("ICMS ST", f"R$ {v_st:,.2f}")
            m3.metric("IPI", f"R$ {v_ipi:,.2f}")
            m4.metric("PIS", f"R$ {v_pis:,.2f}")
            m5.metric("COFINS", f"R$ {v_cof:,.2f}")

            # Exportação
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_ent.to_excel(writer, sheet_name='Entradas Auditadas', index=False)
                df_sai.to_excel(writer, sheet_name='Saídas Auditadas', index=False)
                pd.DataFrame([
                    {'Imposto': 'ICMS', 'Saldo': v_icms}, {'Imposto': 'ST', 'Saldo': v_st},
                    {'Imposto': 'IPI', 'Saldo': v_ipi}, {'Imposto': 'PIS', 'Saldo': v_pis},
                    {'Imposto': 'COFINS', 'Saldo': v_cof}
                ]).to_excel(writer, sheet_name='Apuração Geral', index=False)
                
                workbook = writer.book
                fmt_red = workbook.add_format({'bg_color': '#FFC7CE'})
                for sheet, df_ref in [('Entradas Auditadas', df_ent), ('Saídas Auditadas', df_sai)]:
                    ws = writer.sheets[sheet]
                    ws.set_column('A:AN', 18)
                    for i, val in enumerate(df_ref['DIAGNÓSTICO_ERRO']):
                        if val != "Escrituração Regular": ws.set_row(i + 1, None, fmt_red)

            st.download_button("📥 Baixar Auditoria Suprema (Completa)", output.getvalue(), "Curador_Supremo.xlsx")

        except Exception as e:
            st.error(f"Erro no processamento: {e}")

if __name__ == "__main__":
    main()
