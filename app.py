import streamlit as st
import pandas as pd
import io

# Configuração da página - O Curador
st.set_page_config(page_title="Curador - Auditoria Fiscal Profissional", layout="wide")

def clean_numeric_col(df, col_name):
    """Limpeza técnica para precisão fiscal absoluta (Tratamento de decimais BR)."""
    if col_name in df.columns:
        s = df[col_name].astype(str).str.replace(r'\s+', '', regex=True)
        s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df[col_name] = pd.to_numeric(s, errors='coerce').fillna(0.0)
    return df

# --- MÓDULO DE AUDITORIA DE SAÍDAS (DÉBITOS) ---
def auditoria_saidas_detalhada(row):
    cfop = str(row['CFOP']).strip().replace('.', '')
    cst_full = str(row['CST']).strip()
    cst = cst_full[-2:] if len(cst_full) >= 2 else cst_full.zfill(2)
    
    # Valores
    vlr_icms = row['ICMS']
    bc_icms = row['BC_ICMS']
    aliq = row['ALIQ_ICMS']
    vlr_st = row['ICMSST']
    vlr_ipi = row['IPI']
    uf_dest = str(row['Ufp']).strip().upper()
    
    erros, cliente, dominio = [], [], []

    # 1. VALIDAÇÃO DE ICMS PRÓPRIO
    # Regra para CFOP 6.403 (Venda de Substituto) - Deve haver ICMS Próprio destacado
    if cfop == '6403' and vlr_icms == 0:
        erros.append("ICMS PRÓPRIO ZERADO NO 6403: Operação exige destaque do imposto próprio.")
        cliente.append("No CFOP 6403, você deve destacar o ICMS Próprio além do ICMS ST.")
        dominio.append("Verificar Acumulador: Marcar incidência de ICMS em operações de Substituto.")

    # Vendas Tributadas (CST 00, 10, 20, 70) sem valor
    if cst in ['00', '10', '20', '70'] and vlr_icms == 0:
        erros.append(f"OMISSÃO DE DÉBITO: CST {cst_full} exige destaque de ICMS.")
        cliente.append("Revisar faturamento: CST tributado mas valor de ICMS está zerado.")
        dominio.append("Validar configuração de imposto no cadastro do produto ou acumulador.")

    # Diferença de Cálculo Matemático
    if vlr_icms > 0 and bc_icms > 0:
        vlr_calc = round(bc_icms * (aliq / 100), 2)
        if abs(vlr_calc - vlr_icms) > 0.05:
            erros.append(f"ERRO DE CÁLCULO: Destacado R$ {vlr_icms} != Calculado R$ {vlr_calc}.")
            cliente.append("Corrigir o cálculo do ICMS na emissão da nota.")

    # 2. VALIDAÇÃO DE ICMS ST
    cst_st = ['10', '30', '70', '90']
    if cst in cst_st and vlr_st == 0:
        erros.append(f"ST NÃO INFORMADO: CST {cst_full} é de Substituição mas valor está zerado.")
        cliente.append("Calcular e informar o valor do ICMS ST retido.")
        dominio.append("Configurações Estaduais: Marcar 'Gera guia de ST' no acumulador.")
    
    # Devolução de Compra (5.202 / 6.202) deve estornar crédito (gerar débito)
    if cfop in ['5201', '5202', '6201', '6202'] and vlr_icms == 0 and cst not in ['40', '41', '60']:
        erros.append("DEVOLUÇÃO SEM ESTORNO: Saída por devolução de compra deve anular o crédito original.")
        cliente.append("Destacar impostos na devolução conforme a nota de compra original.")
        dominio.append("Usar acumulador de Devolução que gere débito de ICMS/IPI.")

    # 3. VALIDAÇÃO DE IPI
    # Vendas Industriais (5.101, 6.101)
    if cfop in ['5101', '6101', '5401', '6401'] and vlr_ipi == 0:
        erros.append("IPI NÃO DESTACADO: Operação industrial exige destaque de IPI.")
        cliente.append("Verificar Alíquota de IPI conforme NCM para produção própria.")
        dominio.append("Vincular Tabela de IPI no cadastro de produtos e Imposto 2 no Acumulador.")

    # 4. VALIDAÇÃO DE ALÍQUOTAS INTERESTADUAIS (Saídas de SP)
    if cfop.startswith('6'):
        uf_7 = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'RN', 'RO', 'RR', 'SE', 'TO']
        uf_12 = ['PR', 'RS', 'SC', 'MG', 'RJ']
        if uf_dest in uf_7 and aliq not in [7.0, 4.0]:
            erros.append(f"ALÍQUOTA UF {uf_dest}: Esperado 7% (ou 4%), aplicado {aliq}%.")
            cliente.append(f"Ajustar sistema para aplicar 7% nas vendas para {uf_dest}.")
        elif uf_dest in uf_12 and aliq not in [12.0, 4.0]:
            erros.append(f"ALÍQUOTA UF {uf_dest}: Esperado 12% (ou 4%), aplicado {aliq}%.")

    return pd.Series({
        'DIAGNÓSTICO_ERRO': " | ".join(erros) if erros else "Escrituração Regular",
        'PARAMETRO_CLIENTE': " | ".join(cliente) if cliente else "-",
        'SOLUÇÃO_CONTABIL': " | ".join(dominio) if dominio else "-"
    })

# --- MÓDULO DE AUDITORIA DE ENTRADAS (CRÉDITOS) ---
def auditoria_entradas_detalhada(row):
    cfop = str(row['CFOP']).strip().replace('.', '')
    cst_full = str(row['CST-ICMS']).strip()
    cst = cst_full[-2:] if len(cst_full) >= 2 else cst_full.zfill(2)
    vlr_icms = row['VLR-ICMS']
    vlr_st = row['ICMS-ST']
    vlr_ipi = row['VLR_IPI']
    
    erros, cliente, dominio = [], [], []

    # 1. CRÉDITO DE ICMS
    # Devolução de Venda (1.201, 2.201, 1.202, 2.202) - OBRIGATÓRIO TOMAR CRÉDITO
    if cfop in ['1201', '1202', '2201', '2202', '1410', '1411', '2410', '2411']:
        if vlr_icms == 0 and cst not in ['40', '41', '60']:
            erros.append("DEVOLUÇÃO SEM CRÉDITO: Entrada de devolução de venda sem estorno do débito.")
            cliente.append("Escriturar o crédito de ICMS referente à mercadoria devolvida.")
            dominio.append("Configurar Acumulador de Devolução de Venda para apropriar crédito.")

    # Compras Tributadas sem crédito
    if cfop in ['1101', '1102', '2101', '2102'] and cst in ['00', '10', '20'] and vlr_icms == 0:
        erros.append("CRÉDITO NÃO TOMADO: Compra para revenda/industrialização sem aproveitamento de ICMS.")
        dominio.append("Verificar se o acumulador está configurado para 'Apropriar Crédito de ICMS'.")

    # 2. CRÉDITO DE IPI
    if cfop in ['1101', '2101'] and vlr_ipi == 0:
        erros.append("IPI NÃO APROVEITADO: Insumo industrial sem crédito de IPI.")
        cliente.append("Confirmar se o fornecedor é contribuinte de IPI e destacou o imposto.")

    # 3. ICMS ST NA ENTRADA
    if cst in ['10', '30', '70', '90'] and vlr_st == 0:
        erros.append(f"ALERTA ST: CST {cst_full} indica ST na entrada mas campo está zerado.")

    return pd.Series({
        'DIAGNÓSTICO_ERRO': " | ".join(erros) if erros else "Escrituração Regular",
        'PARAMETRO_CLIENTE': " | ".join(cliente) if cliente else "-",
        'SOLUÇÃO_CONTABIL': " | ".join(dominio) if dominio else "-"
    })

def main():
    st.title("⚖️ Curador: Auditoria Fiscal Profissional (ICMS / ST / IPI)")
    st.markdown("---")
    
    c1, c2 = st.columns(2)
    with c1: ent_f = st.file_uploader("📥 Entradas Gerenciais (CSV)", type=["csv"])
    with c2: sai_f = st.file_uploader("📤 Saídas Gerenciais (CSV)", type=["csv"])

    if ent_f and sai_f:
        try:
            cols_ent = ['NUM_NF', 'DATA_EMISSAO', 'CNPJ', 'UF', 'VLR_NF', 'AC', 'CFOP', 'COD_PROD', 'DESCR', 'NCM', 'UNID', 'VUNIT', 'QTDE', 'VPROD', 'DESC', 'FRETE', 'SEG', 'DESP', 'VC', 'CST-ICMS', 'BC-ICMS', 'VLR-ICMS', 'BC-ICMS-ST', 'ICMS-ST', 'VLR_IPI', 'CST_PIS', 'BC_PIS', 'VLR_PIS', 'CST_COF', 'BC_COF', 'VLR_COF']
            cols_sai = ['NF', 'DATA_EMISSAO', 'CNPJ', 'Ufp', 'VC', 'AC', 'CFOP', 'COD_ITEM', 'DESC_ITEM', 'NCM', 'UND', 'VUNIT', 'QTDE', 'VITEM', 'DESC', 'FRETE', 'SEG', 'OUTRAS', 'VC_ITEM', 'CST', 'BC_ICMS', 'ALIQ_ICMS', 'ICMS', 'BC_ICMSST', 'ICMSST', 'IPI', 'CST_PIS Escriturado', 'BC_PIS', 'PIS', 'CST_COF', 'BC_COF', 'COF']

            df_ent = pd.read_csv(ent_f, sep=';', encoding='latin-1', header=None, names=cols_ent)
            df_sai = pd.read_csv(sai_f, sep=';', encoding='latin-1', header=None, names=cols_sai)

            # Limpeza
            for c in ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'VC', 'ICMS-ST']: df_ent = clean_numeric_col(df_ent, c)
            for c in ['ICMS', 'IPI', 'BC_ICMS', 'VC_ITEM', 'ALIQ_ICMS', 'ICMSST']: df_sai = clean_numeric_col(df_sai, c)

            # Processamento de Auditoria
            df_ent[['DIAGNÓSTICO_ERRO', 'PARAMETRO_CLIENTE', 'SOLUÇÃO_CONTABIL']] = df_ent.apply(auditoria_entradas_detalhada, axis=1)
            df_sai[['DIAGNÓSTICO_ERRO', 'PARAMETRO_CLIENTE', 'SOLUÇÃO_CONTABIL']] = df_sai.apply(auditoria_saidas_detalhada, axis=1)

            # Apuração
            v_icms = df_sai['ICMS'].sum() - df_ent['VLR-ICMS'].sum()
            v_st = df_sai['ICMSST'].sum() - df_ent['ICMS-ST'].sum()
            v_ipi = df_sai['IPI'].sum() - df_ent['VLR_IPI'].sum()

            st.success("Análise de Malha Profissional Concluída!")
            
            # Dashboard
            st.subheader("📊 Apuração de Saldos")
            m1, m2, m3 = st.columns(3)
            m1.metric("Saldo ICMS Próprio", f"R$ {v_icms:,.2f}", delta="Recolher" if v_icms > 0 else "Credor")
            m2.metric("Saldo ICMS ST", f"R$ {v_st:,.2f}", delta="Recolher" if v_st > 0 else "Credor")
            m3.metric("Saldo IPI", f"R$ {v_ipi:,.2f}", delta="Recolher" if v_ipi > 0 else "Credor")

            # Prévias
            st.subheader("🔎 Prévias de Inconsistências")
            c_sai, c_ent = st.columns(2)
            with c_sai:
                st.markdown("#### Saídas com Erro")
                st.dataframe(df_sai[df_sai['DIAGNÓSTICO_ERRO'] != "Escrituração Regular"][['NF', 'CFOP', 'DIAGNÓSTICO_ERRO', 'PARAMETRO_CLIENTE']], use_container_width=True)
            with c_ent:
                st.markdown("#### Entradas com Erro")
                st.dataframe(df_ent[df_ent['DIAGNÓSTICO_ERRO'] != "Escrituração Regular"][['NUM_NF', 'CFOP', 'DIAGNÓSTICO_ERRO', 'PARAMETRO_CLIENTE']], use_container_width=True)

            # Exportação
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_ent.to_excel(writer, sheet_name='Entradas Auditadas', index=False)
                df_sai.to_excel(writer, sheet_name='Saídas Auditadas', index=False)
                pd.DataFrame([{'ICMS': v_icms, 'ST': v_st, 'IPI': v_ipi}]).to_excel(writer, sheet_name='Apuração', index=False)
                
                workbook = writer.book
                fmt_red = workbook.add_format({'bg_color': '#FFC7CE'})
                for sheet, df_ref in [('Entradas Auditadas', df_ent), ('Saídas Auditadas', df_sai)]:
                    ws = writer.sheets[sheet]
                    ws.set_column('A:AN', 18)
                    for i, val in enumerate(df_ref['DIAGNÓSTICO_ERRO']):
                        if val != "Escrituração Regular": ws.set_row(i + 1, None, fmt_red)

            st.download_button("📥 Baixar Auditoria Completa", output.getvalue(), "Relatorio_Curador_Malha_Total.xlsx")

        except Exception as e:
            st.error(f"Erro no processamento: {e}")

if __name__ == "__main__":
    main()
