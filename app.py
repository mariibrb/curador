import streamlit as st
import pandas as pd
import io

# Configuração da página
st.set_page_config(page_title="Curador - Auditoria Fiscal Completa", layout="wide")

def clean_numeric_col(df, col_name):
    """Limpa e converte colunas numéricas (formato BR)."""
    if col_name in df.columns:
        s = df[col_name].astype(str).str.replace(r'\s+', '', regex=True)
        s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df[col_name] = pd.to_numeric(s, errors='coerce').fillna(0.0)
    return df

def diagnosticar_entradas(row):
    """Diagnóstico de Entradas (Compras e Devoluções de Vendas)."""
    cfop = str(row['CFOP']).strip().replace('.', '')
    cst = str(row['CST-ICMS']).zfill(2)
    vlr_icms = row['VLR-ICMS']
    
    # CFOPs de Devolução de Venda (Entrada que gera crédito)
    cfops_dev_venda = ['1201', '1202', '2201', '2202', '1410', '1411', '2410', '2411']
    # Compras para Industrialização/Comercialização
    cfops_credito = ['1101', '1102', '2101', '2102', '1401', '1403', '2401', '2403']
    
    erros = []
    
    # Regra para Devolução de Venda
    if cfop in cfops_dev_venda:
        if vlr_icms == 0 and cst not in ['40', '41', '60']:
            erros.append("Alerta: Devolução de Venda sem estorno/crédito de ICMS.")
    
    # Regra para Compras
    elif cfop in cfops_credito:
        if cst in ['00', '10', '20'] and vlr_icms == 0:
            erros.append("Alerta: Compra/Insumo tributado sem aproveitamento de crédito.")
            
    if not erros: return "Conforme"
    return " | ".join(erros)

def diagnosticar_saidas(row):
    """Diagnóstico de Saídas (Vendas e Devoluções de Compras)."""
    cfop = str(row['CFOP']).strip().replace('.', '')
    cst = str(row['CST']).zfill(2)
    vlr_icms = row['ICMS']
    
    # CFOPs de Devolução de Compra (Saída que gera débito/estorno)
    cfops_dev_compra = ['5201', '5202', '6201', '6202', '5410', '5411', '6410', '6411']
    # Vendas Tributadas
    cfops_venda = ['5101', '5102', '6101', '6102', '5401', '5403', '6401', '6403']
    
    erros = []
    
    # Regra para Devolução de Compra
    if cfop in cfops_dev_compra:
        if vlr_icms == 0 and cst not in ['40', '41', '60']:
            erros.append("Alerta: Devolução de Compra sem estorno/débito de ICMS.")
            
    # Regra para Vendas
    elif cfop in cfops_venda:
        if cst == '00' and vlr_icms == 0:
            erros.append("Alerta: Venda tributada sem destaque de ICMS.")
            
    if not erros: return "Conforme"
    return " | ".join(erros)

def main():
    st.title("⚖️ Curador: Auditoria, Devoluções e Diagnóstico")
    st.markdown("---")
    
    uploaded_ent = st.file_uploader("📥 Entradas Gerencial (CSV)", type=["csv"])
    uploaded_sai = st.file_uploader("📤 Saídas Gerencial (CSV)", type=["csv"])

    if uploaded_ent and uploaded_sai:
        try:
            cols_ent = ['NUM_NF', 'DATA_EMISSAO', 'CNPJ', 'UF', 'VLR_NF', 'AC', 'CFOP', 'COD_PROD', 'DESCR', 'NCM', 'UNID', 'VUNIT', 'QTDE', 'VPROD', 'DESC', 'FRETE', 'SEG', 'DESP', 'VC', 'CST-ICMS', 'BC-ICMS', 'VLR-ICMS', 'BC-ICMS-ST', 'ICMS-ST', 'VLR_IPI', 'CST_PIS', 'BC_PIS', 'VLR_PIS', 'CST_COF', 'BC_COF', 'VLR_COF']
            cols_sai = ['NF', 'DATA_EMISSAO', 'CNPJ', 'Ufp', 'VC', 'AC', 'CFOP', 'COD_ITEM', 'DESC_ITEM', 'NCM', 'UND', 'VUNIT', 'QTDE', 'VITEM', 'DESC', 'FRETE', 'SEG', 'OUTRAS', 'VC_ITEM', 'CST', 'BC_ICMS', 'ALIQ_ICMS', 'ICMS', 'BC_ICMSST', 'ICMSST', 'IPI', 'CST_PIS Escriturado', 'BC_PIS', 'PIS', 'CST_COF', 'BC_COF', 'COF']

            with st.spinner('O Curador está processando o acervo...'):
                df_ent = pd.read_csv(uploaded_ent, sep=';', encoding='latin-1', header=None, names=cols_ent)
                df_sai = pd.read_csv(uploaded_sai, sep=';', encoding='latin-1', header=None, names=cols_sai)

                for c in ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'ICMS-ST']: df_ent = clean_numeric_col(df_ent, c)
                for c in ['ICMS', 'IPI', 'BC_ICMS', 'ICMSST']: df_sai = clean_numeric_col(df_sai, c)

                # Diagnósticos
                df_ent['DIAGNOSTICO_FISCAL'] = df_ent.apply(diagnosticar_entradas, axis=1)
                df_sai['DIAGNOSTICO_FISCAL'] = df_sai.apply(diagnosticar_saidas, axis=1)

                # Lógica de Apuração considerando Devoluções
                # ICMS Saídas (Vendas + Devoluções de Compras)
                total_debito_icms = df_sai['ICMS'].sum() 
                # ICMS Entradas (Compras + Devoluções de Vendas)
                total_credito_icms = df_ent['VLR-ICMS'].sum()
                
                saldo_icms = total_debito_icms - total_credito_icms

                apuracao = [
                    {'Item': 'Débitos Totais (Saídas + Dev. Compras)', 'Valor': total_debito_icms},
                    {'Item': 'Créditos Totais (Entradas + Dev. Vendas)', 'Valor': -total_credito_icms},
                    {'Item': 'SALDO ICMS APURADO', 'Valor': saldo_icms},
                    {'Item': 'Total de IPI a Recolher', 'Valor': df_sai['IPI'].sum() - df_ent['VLR_IPI'].sum()}
                ]
                df_apur = pd.DataFrame(apuracao)

            st.success("Análise finalizada!")
            
            t1, t2, t3 = st.tabs(["📊 Resumo de Apuração", "📑 Detalhe Entradas", "📑 Detalhe Saídas"])
            with t1:
                st.table(df_apur)
            with t2:
                st.dataframe(df_ent[['NUM_NF', 'CFOP', 'VLR-ICMS', 'DIAGNOSTICO_FISCAL']])
            with t3:
                st.dataframe(df_sai[['NF', 'CFOP', 'ICMS', 'DIAGNOSTICO_FISCAL']])

            # Geração Excel
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_ent.to_excel(writer, sheet_name='Entradas e Créditos', index=False)
                df_sai.to_excel(writer, sheet_name='Saídas e Débitos', index=False)
                df_apur.to_excel(writer, sheet_name='Apuração Final', index=False)
                
                workbook = writer.book
                fmt_red = workbook.add_format({'bg_color': '#FFC7CE'})
                for sheet, df in [('Entradas e Créditos', df_ent), ('Saídas e Débitos', df_sai)]:
                    ws = writer.sheets[sheet]
                    for i, val in enumerate(df['DIAGNOSTICO_FISCAL']):
                        if val != "Conforme": ws.set_row(i + 1, None, fmt_red)

            st.download_button("📥 Baixar Relatório do Curador", output.getvalue(), "Auditoria_Curador_V2.xlsx")

        except Exception as e:
            st.error(f"Erro Crítico: {e}")
    else:
        st.info("Aguardando arquivos...")

if __name__ == "__main__":
    main()
