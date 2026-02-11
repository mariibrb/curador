import streamlit as st
import pandas as pd
import io

# Configuração da página - O Curador
st.set_page_config(page_title="Curador - Relatório de Auditoria Fiscal", layout="wide")

def clean_numeric_col(df, col_name):
    """Limpeza técnica de colunas numéricas para precisão fiscal absoluta."""
    if col_name in df.columns:
        s = df[col_name].astype(str).str.replace(r'\s+', '', regex=True)
        s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df[col_name] = pd.to_numeric(s, errors='coerce').fillna(0.0)
    return df

def auditoria_total(row, tipo='saida'):
    """
    Motor de Auditoria: Valida ICMS Próprio, ST e IPI.
    Gera Diagnóstico, Parâmetro Cliente e Solução Contábil.
    """
    cfop = str(row['CFOP']).strip().replace('.', '')
    # Normalização de CST (Lê os 2 últimos dígitos para ignorar origem)
    cst_full = str(row['CST-ICMS'] if tipo == 'entrada' else row['CST']).strip()
    cst = cst_full[-2:] if len(cst_full) >= 2 else cst_full.zfill(2)
    
    vlr_icms = row['VLR-ICMS'] if tipo == 'entrada' else row['ICMS']
    bc_icms = row['BC-ICMS'] if tipo == 'entrada' else row['BC_ICMS']
    aliq = 0 if tipo == 'entrada' else row['ALIQ_ICMS']
    vlr_st = row['ICMS-ST'] if tipo == 'entrada' else row['ICMSST']
    vlr_ipi = row['VLR_IPI'] if tipo == 'entrada' else row['IPI']
    uf_dest = "" if tipo == 'entrada' else str(row['Ufp']).strip().upper()
    
    erros, cliente, dominio = [], [], []
    cst_st = ['10', '30', '70', '90']

    # --- MALHA ICMS PRÓPRIO ---
    if cfop == '6403' and vlr_icms == 0:
        erros.append("ICMS Próprio não destacado no CFOP 6403.")
        cliente.append("Destacar ICMS Próprio na NF-e de Substituto Tributário.")
        dominio.append("No acumulador, habilitar cálculo de ICMS Próprio em operações de ST.")
    
    if tipo == 'saida' and vlr_icms > 0 and bc_icms > 0:
        calc = round(bc_icms * (aliq / 100), 2)
        if abs(calc - vlr_icms) > 0.05:
            erros.append(f"Cálculo ICMS divergente (Esperado: {calc}).")
            cliente.append("Corrigir cálculo de ICMS: valor destacado não condiz com Base x Alíquota.")
            dominio.append("Verificar alíquota no cadastro ou exceção fiscal.")

    # --- MALHA ICMS ST ---
    if cst in cst_st and vlr_st == 0:
        erros.append(f"CST {cst_full} exige destaque de ST, mas valor está zerado.")
        cliente.append("Informar valor do ICMS ST retido na nota.")
        dominio.append("No acumulador (Domínio), aba Estadual, marcar 'Gera guia de ST'.")
    elif vlr_st > 0 and cst not in cst_st and cst != '60':
        erros.append(f"Destaque de ST indevido para CST {cst_full}.")
        cliente.append("Remover ST ou ajustar CST para final 10, 30, 70 ou 90.")

    # --- MALHA IPI ---
    if cfop in ['5101', '6101'] and vlr_ipi == 0:
        erros.append("Venda industrial sem destaque de IPI.")
        cliente.append("Informar IPI (Saída de Produção Própria).")
        dominio.append("Vincular tabela de IPI no produto e usar Acumulador industrial.")

    # --- MALHA UF (Interestadual) ---
    if tipo == 'saida' and cfop.startswith('6'):
        reg_7 = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'RN', 'RO', 'RR', 'SE', 'TO']
        if uf_dest in reg_7 and aliq not in [7.0, 4.0]:
            erros.append(f"Alíquota UF {uf_dest} incorreta (Espera-se 7%).")
            cliente.append(f"Ajustar alíquota interestadual para 7% para {uf_dest}.")

    return pd.Series({
        'DIAGNÓSTICO_ERRO': " | ".join(erros) if erros else "Escrituração Regular",
        'PARAMETRO_CLIENTE': " | ".join(cliente) if cliente else "-",
        'SOLUÇÃO_CONTABIL': " | ".join(dominio) if dominio else "-"
    })

def main():
    st.title("⚖️ Curador: Auditoria e Relatório Fiscal")
    st.markdown("---")
    
    # Upload Centralizado
    col1, col2 = st.columns(2)
    with col1: ent_f = st.file_uploader("📥 Entradas Gerenciais (CSV)", type=["csv"])
    with col2: sai_f = st.file_uploader("📤 Saídas Gerenciais (CSV)", type=["csv"])

    if ent_f and sai_f:
        try:
            # Cabeçalhos originais
            cols_ent = ['NUM_NF', 'DATA_EMISSAO', 'CNPJ', 'UF', 'VLR_NF', 'AC', 'CFOP', 'COD_PROD', 'DESCR', 'NCM', 'UNID', 'VUNIT', 'QTDE', 'VPROD', 'DESC', 'FRETE', 'SEG', 'DESP', 'VC', 'CST-ICMS', 'BC-ICMS', 'VLR-ICMS', 'BC-ICMS-ST', 'ICMS-ST', 'VLR_IPI', 'CST_PIS', 'BC_PIS', 'VLR_PIS', 'CST_COF', 'BC_COF', 'VLR_COF']
            cols_sai = ['NF', 'DATA_EMISSAO', 'CNPJ', 'Ufp', 'VC', 'AC', 'CFOP', 'COD_ITEM', 'DESC_ITEM', 'NCM', 'UND', 'VUNIT', 'QTDE', 'VITEM', 'DESC', 'FRETE', 'SEG', 'OUTRAS', 'VC_ITEM', 'CST', 'BC_ICMS', 'ALIQ_ICMS', 'ICMS', 'BC_ICMSST', 'ICMSST', 'IPI', 'CST_PIS Escriturado', 'BC_PIS', 'PIS', 'CST_COF', 'BC_COF', 'COF']

            df_ent = pd.read_csv(ent_f, sep=';', encoding='latin-1', header=None, names=cols_ent)
            df_sai = pd.read_csv(sai_f, sep=';', encoding='latin-1', header=None, names=cols_sai)

            for c in ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'VC', 'ICMS-ST']: df_ent = clean_numeric_col(df_ent, c)
            for c in ['ICMS', 'IPI', 'BC_ICMS', 'VC_ITEM', 'ALIQ_ICMS', 'ICMSST']: df_sai = clean_numeric_col(df_sai, c)

            # Processamento
            df_ent[['DIAGNÓSTICO_ERRO', 'PARAMETRO_CLIENTE', 'SOLUÇÃO_CONTABIL']] = df_ent.apply(lambda r: auditoria_total(r, 'entrada'), axis=1)
            df_sai[['DIAGNÓSTICO_ERRO', 'PARAMETRO_CLIENTE', 'SOLUÇÃO_CONTABIL']] = df_sai.apply(lambda r: auditoria_total(r, 'saida'), axis=1)

            # Apuração
            v_icms = df_sai['ICMS'].sum() - df_ent['VLR-ICMS'].sum()
            v_st = df_sai['ICMSST'].sum() - df_ent['ICMS-ST'].sum()
            v_ipi = df_sai['IPI'].sum() - df_ent['VLR_IPI'].sum()

            # PRÉVIAS NO STREAMLIT (CONFORME SOLICITADO)
            st.success("Análise de Malha Concluída!")
            
            # 1. Métricas de Saldo
            st.subheader("🏁 Saldo Final da Apuração")
            m1, m2, m3 = st.columns(3)
            m1.metric("Saldo ICMS Próprio", f"R$ {v_icms:,.2f}", delta="A Recolher" if v_icms > 0 else "Credor")
            m2.metric("Saldo ICMS ST", f"R$ {v_st:,.2f}", delta="A Recolher" if v_st > 0 else "Credor")
            m3.metric("Saldo IPI", f"R$ {v_ipi:,.2f}", delta="A Recolher" if v_ipi > 0 else "Credor")

            # 2. Quadro de Apuração Detalhado
            st.subheader("📋 Resumo do Confronto")
            df_resumo = pd.DataFrame([
                {'Imposto': 'ICMS Próprio', 'Débito (Saídas)': df_sai['ICMS'].sum(), 'Crédito (Entradas)': df_ent['VLR-ICMS'].sum(), 'Saldo': v_icms},
                {'Imposto': 'ICMS ST', 'Débito (Saídas)': df_sai['ICMSST'].sum(), 'Crédito (Entradas)': df_ent['ICMS-ST'].sum(), 'Saldo': v_st},
                {'Imposto': 'IPI', 'Débito (Saídas)': df_sai['IPI'].sum(), 'Crédito (Entradas)': df_ent['VLR_IPI'].sum(), 'Saldo': v_ipi},
            ])
            st.table(df_resumo)

            # 3. Diagnósticos com Erro (O que você quer ver de imediato)
            st.subheader("🔎 Inconsistências Detectadas (Prévias)")
            erros = pd.concat([
                df_ent[df_ent['DIAGNÓSTICO_ERRO'] != "Escrituração Regular"][['NUM_NF', 'CFOP', 'DIAGNÓSTICO_ERRO', 'PARAMETRO_CLIENTE', 'SOLUÇÃO_CONTABIL']].rename(columns={'NUM_NF': 'Doc'}),
                df_sai[df_sai['DIAGNÓSTICO_ERRO'] != "Escrituração Regular"][['NF', 'CFOP', 'DIAGNÓSTICO_ERRO', 'PARAMETRO_CLIENTE', 'SOLUÇÃO_CONTABIL']].rename(columns={'NF': 'Doc'})
            ])
            if erros.empty:
                st.info("✅ Nenhuma inconsistência detectada.")
            else:
                st.dataframe(erros, use_container_width=True)

            # Exportação
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_ent.to_excel(writer, sheet_name='Entradas Auditadas', index=False)
                df_sai.to_excel(writer, sheet_name='Saídas Auditadas', index=False)
                df_resumo.to_excel(writer, sheet_name='Apuração de Saldos', index=False)
                
                workbook = writer.book
                fmt_red = workbook.add_format({'bg_color': '#FFC7CE'})
                for sheet, df_ref in [('Entradas Auditadas', df_ent), ('Saídas Auditadas', df_sai)]:
                    ws = writer.sheets[sheet]
                    ws.set_column('A:AN', 18)
                    for i, val in enumerate(df_ref['DIAGNÓSTICO_ERRO']):
                        if val != "Escrituração Regular": ws.set_row(i + 1, None, fmt_red)

            st.download_button("📥 Baixar Planilha Completa do Curador", output.getvalue(), "Auditoria_Curador_Malha_Total.xlsx")

        except Exception as e:
            st.error(f"Erro no processamento: {e}")

if __name__ == "__main__":
    main()
