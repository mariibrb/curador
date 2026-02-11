import streamlit as st
import pandas as pd
import io

# Configuração da página do Streamlit
st.set_page_config(page_title="Curador - Auditoria de ICMS/IPI", layout="wide")

def clean_numeric_col(df, col_name):
    """
    Função de limpeza e conversão numérica rigorosa.
    Trata formatos de exportação brasileiros (ponto como milhar e vírgula como decimal).
    """
    if col_name in df.columns:
        s = df[col_name].astype(str)
        s = s.str.replace(r'\s+', '', regex=True)
        s = s.str.replace('.', '', regex=False)
        s = s.str.replace(',', '.', regex=False)
        df[col_name] = pd.to_numeric(s, errors='coerce').fillna(0.0)
    return df

def diagnosticar_entradas(row):
    """
    Regras de auditoria para Entradas (Compras/Insumos).
    """
    cfop = str(row['CFOP']).strip().replace('.', '')
    cst = str(row['CST-ICMS']).zfill(2)
    vlr_icms = row['VLR-ICMS']
    
    # Compras para Industrialização ou Comercialização (Crédito geralmente permitido)
    cfops_credito = ['1101', '1102', '2101', '2102', '1401', '1403', '2401', '2403']
    # Uso e Consumo (Crédito vedado)
    cfops_consumo = ['1556', '2556', '1407', '2407']
    
    erros = []
    
    if cfop in cfops_credito:
        if cst in ['00', '10', '20'] and vlr_icms == 0:
            erros.append("Alerta: Operação de compra/insumo sem aproveitamento de crédito de ICMS.")
    
    if cfop in cfops_consumo:
        if vlr_icms > 0:
            erros.append("Alerta: Crédito de ICMS destacado em nota de Uso/Consumo (Vedado).")
            
    if not erros:
        return "Conforme"
    return " | ".join(erros)

def diagnosticar_saidas(row):
    """
    Regras de auditoria para Saídas (Vendas/Remessas).
    """
    cfop = str(row['CFOP']).strip().replace('.', '')
    cst = str(row['CST']).zfill(2)
    vlr_icms = row['ICMS']
    
    # Vendas Tributadas
    cfops_venda = ['5101', '5102', '6101', '6102', '5401', '5403', '6401', '6403']
    
    erros = []
    
    if cfop in cfops_venda:
        if cst == '00' and vlr_icms == 0:
            erros.append("Alerta: Venda tributada sem destaque de ICMS.")
        if cst in ['40', '41', '60'] and vlr_icms > 0:
            erros.append("Alerta: ICMS destacado em operação Isenta, Não Tributada ou com ST.")
            
    if not erros:
        return "Conforme"
    return " | ".join(erros)

def main():
    st.title("⚖️ Curador: Auditoria e Diagnóstico Fiscal")
    st.markdown("---")
    
    st.sidebar.header("⚖️ Painel de Controle")
    st.sidebar.info("O Curador agora audita CFOP vs CST para detectar inconsistências na escrituração.")

    col1, col2 = st.columns(2)
    with col1:
        uploaded_ent = st.file_uploader("📥 Entradas Gerencial (CSV)", type=["csv"])
    with col2:
        uploaded_sai = st.file_uploader("📤 Saídas Gerencial (CSV)", type=["csv"])

    if uploaded_ent and uploaded_sai:
        try:
            # Estrutura de colunas rigorosa
            cols_ent = ['NUM_NF', 'DATA_EMISSAO', 'CNPJ', 'UF', 'VLR_NF', 'AC', 'CFOP', 'COD_PROD', 'DESCR', 'NCM', 'UNID', 'VUNIT', 'QTDE', 'VPROD', 'DESC', 'FRETE', 'SEG', 'DESP', 'VC', 'CST-ICMS', 'BC-ICMS', 'VLR-ICMS', 'BC-ICMS-ST', 'ICMS-ST', 'VLR_IPI', 'CST_PIS', 'BC_PIS', 'VLR_PIS', 'CST_COF', 'BC_COF', 'VLR_COF']
            cols_sai = ['NF', 'DATA_EMISSAO', 'CNPJ', 'Ufp', 'VC', 'AC', 'CFOP', 'COD_ITEM', 'DESC_ITEM', 'NCM', 'UND', 'VUNIT', 'QTDE', 'VITEM', 'DESC', 'FRETE', 'SEG', 'OUTRAS', 'VC_ITEM', 'CST', 'BC_ICMS', 'ALIQ_ICMS', 'ICMS', 'BC_ICMSST', 'ICMSST', 'IPI', 'CST_PIS Escriturado', 'BC_PIS', 'PIS', 'CST_COF', 'BC_COF', 'COF']

            with st.spinner('O Curador está realizando a auditoria profunda...'):
                df_ent = pd.read_csv(uploaded_ent, sep=';', encoding='latin-1', header=None, names=cols_ent)
                df_sai = pd.read_csv(uploaded_sai, sep=';', encoding='latin-1', header=None, names=cols_sai)

                # Limpeza numérica
                for c in ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'VLR_NF', 'ICMS-ST']: df_ent = clean_numeric_col(df_ent, c)
                for c in ['ICMS', 'IPI', 'BC_ICMS', 'VC', 'ICMSST']: df_sai = clean_numeric_col(df_sai, c)

                # Aplicação dos Diagnósticos
                df_ent['DIAGNOSTICO_ESCRITURACAO'] = df_ent.apply(diagnosticar_entradas, axis=1)
                df_sai['DIAGNOSTICO_EMISSAO'] = df_sai.apply(diagnosticar_saidas, axis=1)

                # Resumo de Erros para a tela
                erros_ent = df_ent[df_ent['DIAGNOSTICO_ESCRITURACAO'] != "Conforme"]
                erros_sai = df_sai[df_sai['DIAGNOSTICO_EMISSAO'] != "Conforme"]

                # Apuração
                apuracao = [
                    {'Métrica': 'Total Débito ICMS (Saídas)', 'Valor': df_sai['ICMS'].sum()},
                    {'Métrica': 'Total Crédito ICMS (Entradas)', 'Valor': -df_ent['VLR-ICMS'].sum()},
                    {'Métrica': 'Saldo Devedor/Credor ICMS', 'Valor': df_sai['ICMS'].sum() - df_ent['VLR-ICMS'].sum()},
                    {'Métrica': 'Divergências Encontradas nas Entradas', 'Valor': len(erros_ent)},
                    {'Métrica': 'Divergências Encontradas nas Saídas', 'Valor': len(erros_sai)}
                ]
                df_apur = pd.DataFrame(apuracao)

            st.success("Auditoria Concluída!")
            
            # Mostra alertas se houver
            if len(erros_ent) > 0 or len(erros_sai) > 0:
                st.warning(f"Foram detectadas {len(erros_ent) + len(erros_sai)} possíveis inconsistências fiscais.")
            
            tabs = st.tabs(["📊 Apuração & Resumo", "📥 Entradas (Diagnóstico)", "📤 Saídas (Diagnóstico)"])
            
            with tabs[0]:
                st.subheader("Consolidado da Auditoria")
                st.table(df_apur)
            
            with tabs[1]:
                st.subheader("Relatório de Entradas")
                st.dataframe(df_ent[['NUM_NF', 'CFOP', 'CST-ICMS', 'VLR-ICMS', 'DIAGNOSTICO_ESCRITURACAO']])
                
            with tabs[2]:
                st.subheader("Relatório de Saídas")
                st.dataframe(df_sai[['NF', 'CFOP', 'CST', 'ICMS', 'DIAGNOSTICO_EMISSAO']])

            # Exportação
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_ent.to_excel(writer, sheet_name='Entradas Gerencial', index=False)
                df_sai.to_excel(writer, sheet_name='Saídas Gerencial', index=False)
                df_apur.to_excel(writer, sheet_name='Apuração e Diagnóstico', index=False)
                
                workbook = writer.book
                fmt_error = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
                fmt_money = workbook.add_format({'num_format': '#,##0.00'})
                
                # Formatar automaticamente linhas com erro no Excel
                for sheet, df, diag_col in [('Entradas Gerencial', df_ent, 'DIAGNOSTICO_ESCRITURACAO'), 
                                            ('Saídas Gerencial', df_sai, 'DIAGNOSTICO_EMISSAO')]:
                    ws = writer.sheets[sheet]
                    ws.set_column('A:AF', 18, fmt_money)
                    # Adiciona destaque visual onde houver erro
                    for i, val in enumerate(df[diag_col]):
                        if val != "Conforme":
                            ws.set_row(i + 1, None, fmt_error)

            st.download_button(
                label="📥 Baixar Planilha de Auditoria (O Curador)",
                data=output.getvalue(),
                file_name="Auditoria_Curador_Diagnostico.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        except Exception as e:
            st.error(f"Erro na análise: {str(e)}")

    else:
        st.info("Carregue as planilhas para iniciar o diagnóstico.")

if __name__ == "__main__":
    main()
