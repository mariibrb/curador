import streamlit as st
import pandas as pd
import io

# Configuração da página do Streamlit
st.set_page_config(page_title="Escriba - Apuração ICMS/IPI", layout="wide")

def clean_numeric_col(df, col_name):
    """
    Função de limpeza rigorosa para o Escriba.
    Converte formatos brasileiros (1.000,00) para float (1000.00).
    """
    if col_name in df.columns:
        s = df[col_name].astype(str)
        s = s.str.replace(r'\s+', '', regex=True)
        s = s.str.replace('.', '', regex=False)
        s = s.str.replace(',', '.', regex=False)
        df[col_name] = pd.to_numeric(s, errors='coerce').fillna(0.0)
    return df

def main():
    st.title("📜 Escriba: Auditoria e Apuração")
    st.markdown("---")
    
    st.sidebar.header("📜 Menu do Escriba")
    st.sidebar.info("O Escriba processará seus arquivos gerenciais e gerará a planilha de conferência final.")

    # Upload de arquivos
    col1, col2 = st.columns(2)
    with col1:
        uploaded_entradas = st.file_uploader("📥 Entradas Gerencial (CSV)", type=["csv"])
    with col2:
        uploaded_saidas = st.file_uploader("📤 Saídas Gerencial (CSV)", type=["csv"])

    if uploaded_entradas and uploaded_saidas:
        try:
            # Definição das colunas baseada na hierarquia fiscal da sua planilha de Conferência
            cols_entradas = [
                'NUM_NF', 'DATA_EMISSAO', 'CNPJ', 'UF', 'VLR_NF', 'AC', 'CFOP', 'COD_PROD', 
                'DESCR', 'NCM', 'UNID', 'VUNIT', 'QTDE', 'VPROD', 'DESC', 'FRETE', 'SEG', 
                'DESP', 'VC', 'CST-ICMS', 'BC-ICMS', 'VLR-ICMS', 'BC-ICMS-ST', 'ICMS-ST', 
                'VLR_IPI', 'CST_PIS', 'BC_PIS', 'VLR_PIS', 'CST_COF', 'BC_COF', 'VLR_COF'
            ]
            
            cols_saidas = [
                'NF', 'DATA_EMISSAO', 'CNPJ', 'Ufp', 'VC', 'AC', 'CFOP', 'COD_ITEM', 
                'DESC_ITEM', 'NCM', 'UND', 'VUNIT', 'QTDE', 'VITEM', 'DESC', 'FRETE', 
                'SEG', 'OUTRAS', 'VC_ITEM', 'CST', 'BC_ICMS', 'ALIQ_ICMS', 'ICMS', 
                'BC_ICMSST', 'ICMSST', 'IPI', 'CST_PIS Escriturado', 'BC_PIS', 'PIS', 
                'CST_COF', 'BC_COF', 'COF'
            ]

            with st.spinner('O Escriba está analisando os pergaminhos...'):
                # Leitura dos CSVs com delimitador ';' conforme seus arquivos originais
                df_ent = pd.read_csv(uploaded_entradas, sep=';', encoding='latin-1', header=None, names=cols_entradas)
                df_sai = pd.read_csv(uploaded_saidas, sep=';', encoding='latin-1', header=None, names=cols_saidas)

                # Limpeza de colunas numéricas (essencial para cálculos fiscais)
                for col in ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'VLR_NF', 'ICMS-ST']:
                    df_ent = clean_numeric_col(df_ent, col)
                for col in ['ICMS', 'IPI', 'BC_ICMS', 'VC', 'ICMSST']:
                    df_sai = clean_numeric_col(df_sai, col)

                # --- LÓGICA DE APURAÇÃO ---
                icms_debito = df_sai['ICMS'].sum()
                icms_credito = df_ent['VLR-ICMS'].sum()
                icms_st_saida = df_sai['ICMSST'].sum()
                icms_st_entrada = df_ent['ICMS-ST'].sum()
                ipi_debito = df_sai['IPI'].sum()
                ipi_credito = df_ent['VLR_IPI'].sum()

                # Estruturação da Aba de Apuração
                apuracao_data = [
                    {'Imposto': 'ICMS PRÓPRIO', 'Natureza': 'Débitos (Saídas)', 'Valor': icms_debito},
                    {'Imposto': 'ICMS PRÓPRIO', 'Natureza': 'Créditos (Entradas)', 'Valor': -icms_credito},
                    {'Imposto': 'ICMS PRÓPRIO', 'Natureza': 'SALDO APURADO', 'Valor': icms_debito - icms_credito},
                    {'Imposto': '', 'Natureza': '', 'Valor': None},
                    {'Imposto': 'ICMS ST', 'Natureza': 'Débitos ST (Saídas)', 'Valor': icms_st_saida},
                    {'Imposto': 'ICMS ST', 'Natureza': 'Créditos ST (Entradas)', 'Valor': -icms_st_entrada},
                    {'Imposto': 'ICMS ST', 'Natureza': 'SALDO ST', 'Valor': icms_st_saida - icms_st_entrada},
                    {'Imposto': '', 'Natureza': '', 'Valor': None},
                    {'Imposto': 'IPI', 'Natureza': 'Débitos (Saídas)', 'Valor': ipi_debito},
                    {'Imposto': 'IPI', 'Natureza': 'Créditos (Entradas)', 'Valor': -ipi_credito},
                    {'Imposto': 'IPI', 'Natureza': 'SALDO IPI', 'Valor': ipi_debito - ipi_credito},
                ]
                df_apuracao = pd.DataFrame(apuracao_data)

            st.success("Escrituração concluída com sucesso!")

            # Exibição de Resumo na tela
            st.subheader("Resumo da Apuração")
            st.dataframe(df_apuracao[df_apuracao['Valor'].notnull()])

            # Geração do Excel com 3 abas
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_ent.to_excel(writer, sheet_name='Entradas Gerencial', index=False)
                df_sai.to_excel(writer, sheet_name='Saídas Gerencial', index=False)
                df_apuracao.to_excel(writer, sheet_name='Apuração', index=False)

                # Formatação visual
                workbook = writer.book
                fmt_money = workbook.add_format({'num_format': '#,##0.00'})
                fmt_header = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})

                for sheet_name in writer.sheets:
                    worksheet = writer.sheets[sheet_name]
                    worksheet.set_column('A:Z', 18, fmt_money)
                    # Escreve o cabeçalho formatado
                    current_df = df_ent if sheet_name == 'Entradas Gerencial' else df_sai if sheet_name == 'Saídas Gerencial' else df_apuracao
                    for col_num, value in enumerate(current_df.columns):
                        worksheet.write(0, col_num, value, fmt_header)

            st.download_button(
                label="📥 Baixar Planilha do Escriba (3 Abas)",
                data=output.getvalue(),
                file_name="Conferência_Escriba_ICMS_IPI.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        except Exception as e:
            st.error(f"Erro na leitura dos pergaminhos: {str(e)}")

    else:
        st.info("Aguardando os arquivos para iniciar a conferência.")

if __name__ == "__main__":
    main()
