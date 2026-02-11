import streamlit as st
import pandas as pd
import io

# Configuração da página - O Curador
st.set_page_config(page_title="Curador - Auditoria e Livros Fiscais", layout="wide")

def clean_numeric_col(df, col_name):
    """
    Limpeza e conversão de colunas numéricas (Padrão Brasileiro).
    Garante a precisão para cálculos de impostos.
    """
    if col_name in df.columns:
        s = df[col_name].astype(str).str.replace(r'\s+', '', regex=True)
        s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df[col_name] = pd.to_numeric(s, errors='coerce').fillna(0.0)
    return df

def auditoria_entradas(row):
    """
    Diagnóstico Técnico de Entradas (Compras e Devoluções de Vendas).
    Cruza CFOP e CST para validar o direito ao crédito.
    """
    cfop = str(row['CFOP']).strip().replace('.', '')
    cst = str(row['CST-ICMS']).zfill(2)
    vlr_icms = row['VLR-ICMS']
    
    # CFOPs de Devolução de Venda (Entrada que gera crédito)
    cfops_dev_venda = ['1201', '1202', '2201', '2202', '1410', '1411', '2410', '2411']
    # Compras para Industrialização ou Comercialização (Crédito permitido)
    cfops_credito = ['1101', '1102', '2101', '2102', '1401', '1403', '2401', '2403']
    # Uso e Consumo (Crédito vedado)
    cfops_consumo = ['1556', '2556', '1407', '2407']
    
    alertas = []
    
    if cfop in cfops_dev_venda:
        if vlr_icms == 0 and cst not in ['40', '41', '60']:
            alertas.append("DEVOLUÇÃO DE VENDA: Ausência de aproveitamento de crédito.")
    elif cfop in cfops_credito:
        if cst in ['00', '10', '20'] and vlr_icms == 0:
            alertas.append("CRÉDITO NÃO TOMADO: Compra tributada sem escrituração do ICMS.")
    elif cfop in cfops_consumo:
        if vlr_icms > 0:
            alertas.append("CRÉDITO INDEVIDO: ICMS destacado em nota de uso/consumo.")
            
    return " | ".join(alertas) if alertas else "Escrituração Regular"

def auditoria_saidas(row):
    """
    Diagnóstico Técnico de Saídas (Vendas e Devoluções de Compras).
    Valida o destaque correto do imposto na emissão.
    """
    cfop = str(row['CFOP']).strip().replace('.', '')
    cst = str(row['CST']).zfill(2)
    vlr_icms = row['ICMS']
    
    # CFOPs de Devolução de Compra (Saída que gera débito/estorno)
    cfops_dev_compra = ['5201', '5202', '6201', '6202', '5410', '5411', '6410', '6411']
    # Vendas Tributadas
    cfops_venda = ['5101', '5102', '6101', '6102', '5401', '5403', '6401', '6403']
    
    alertas = []
    
    if cfop in cfops_dev_compra:
        if vlr_icms == 0 and cst not in ['40', '41', '60']:
            alertas.append("DEVOLUÇÃO DE COMPRA: Ausência de estorno/débito de ICMS.")
    elif cfop in cfops_venda:
        if cst == '00' and vlr_icms == 0:
            alertas.append("OMISSÃO DE DÉBITO: Venda tributada sem destaque de ICMS.")
    
    if cst in ['40', '41', '60'] and vlr_icms > 0:
        alertas.append("DESTAQUE INDEVIDO: ICMS destacado em operação Isenta/ST.")
            
    return " | ".join(alertas) if alertas else "Escrituração Regular"

def gerar_resumo_livro(df, tipo='entrada'):
    """
    Agrupa valores no formato do Livro Registro de ICMS (Modelo P9).
    Separa Base, Isentas e Outras conforme o CST.
    """
    if tipo == 'entrada':
        df['Isentas'] = df.apply(lambda x: x['VC'] if str(x['CST-ICMS']) in ['40', '41'] else 0, axis=1)
        df['Outras'] = df.apply(lambda x: x['VC'] if str(x['CST-ICMS']) not in ['00', '10', '20', '40', '41'] else 0, axis=1)
        
        resumo = df.groupby('CFOP').agg({
            'VC': 'sum',
            'BC-ICMS': 'sum',
            'VLR-ICMS': 'sum',
            'Isentas': 'sum',
            'Outras': 'sum'
        }).reset_index()
        resumo.columns = ['CFOP', 'Valor Contábil', 'Base de Cálculo', 'Imposto Creditado', 'Isentas/Não Trib.', 'Outras']
    else:
        df['Isentas'] = df.apply(lambda x: x['VC_ITEM'] if str(x['CST']) in ['40', '41'] else 0, axis=1)
        df['Outras'] = df.apply(lambda x: x['VC_ITEM'] if str(x['CST']) not in ['00', '10', '20', '40', '41'] else 0, axis=1)
        
        resumo = df.groupby('CFOP').agg({
            'VC_ITEM': 'sum',
            'BC_ICMS': 'sum',
            'ICMS': 'sum',
            'Isentas': 'sum',
            'Outras': 'sum'
        }).reset_index()
        resumo.columns = ['CFOP', 'Valor Contábil', 'Base de Cálculo', 'Imposto Debitado', 'Isentas/Não Trib.', 'Outras']
    
    return resumo

def main():
    st.title("⚖️ Curador: Auditoria e Escrituração de Livros Fiscais")
    st.markdown("---")
    
    # Upload dos Arquivos Gerenciais
    col1, col2 = st.columns(2)
    with col1:
        uploaded_ent = st.file_uploader("📥 Entradas Gerencial (CSV)", type=["csv"])
    with col2:
        uploaded_sai = st.file_uploader("📤 Saídas Gerencial (CSV)", type=["csv"])

    if uploaded_ent and uploaded_sai:
        try:
            # Definição rigorosa das colunas baseada na sua planilha de conferência
            cols_ent = ['NUM_NF', 'DATA_EMISSAO', 'CNPJ', 'UF', 'VLR_NF', 'AC', 'CFOP', 'COD_PROD', 'DESCR', 'NCM', 'UNID', 'VUNIT', 'QTDE', 'VPROD', 'DESC', 'FRETE', 'SEG', 'DESP', 'VC', 'CST-ICMS', 'BC-ICMS', 'VLR-ICMS', 'BC-ICMS-ST', 'ICMS-ST', 'VLR_IPI', 'CST_PIS', 'BC_PIS', 'VLR_PIS', 'CST_COF', 'BC_COF', 'VLR_COF']
            cols_sai = ['NF', 'DATA_EMISSAO', 'CNPJ', 'Ufp', 'VC', 'AC', 'CFOP', 'COD_ITEM', 'DESC_ITEM', 'NCM', 'UND', 'VUNIT', 'QTDE', 'VITEM', 'DESC', 'FRETE', 'SEG', 'OUTRAS', 'VC_ITEM', 'CST', 'BC_ICMS', 'ALIQ_ICMS', 'ICMS', 'BC_ICMSST', 'ICMSST', 'IPI', 'CST_PIS Escriturado', 'BC_PIS', 'PIS', 'CST_COF', 'BC_COF', 'COF']

            with st.spinner('O Curador está processando os livros fiscais...'):
                # Leitura técnica (sep ; e latin-1)
                df_ent = pd.read_csv(uploaded_ent, sep=';', encoding='latin-1', header=None, names=cols_ent)
                df_sai = pd.read_csv(uploaded_sai, sep=';', encoding='latin-1', header=None, names=cols_sai)

                # Limpeza e Conversão de Valores
                for c in ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'VC', 'VPROD', 'ICMS-ST']: df_ent = clean_numeric_col(df_ent, c)
                for c in ['ICMS', 'IPI', 'BC_ICMS', 'VC_ITEM', 'VITEM', 'ICMSST']: df_sai = clean_numeric_col(df_sai, c)

                # Execução da Auditoria e Diagnósticos
                df_ent['DIAGNOSTICO_CURADOR'] = df_ent.apply(auditoria_entradas, axis=1)
                df_sai['DIAGNOSTICO_CURADOR'] = df_sai.apply(auditoria_saidas, axis=1)

                # Geração de Resumos (Formato PDF Livro)
                livro_entradas = gerar_resumo_livro(df_ent.copy(), 'entrada')
                livro_saidas = gerar_resumo_livro(df_sai.copy(), 'saida')

                # Apuração Final de Confronto
                total_debito = df_sai['ICMS'].sum()
                total_credito = df_ent['VLR-ICMS'].sum()
                saldo_icms = total_debito - total_credito
                
                total_ipi_deb = df_sai['IPI'].sum()
                total_ipi_cred = df_ent['VLR_IPI'].sum()
                saldo_ipi = total_ipi_deb - total_ipi_cred

                df_apuracao = pd.DataFrame([
                    {'Descrição': '001 - DÉBITO POR SAÍDAS (Vendas + Devol. Compras)', 'Valor': total_debito},
                    {'Descrição': '002 - CRÉDITO POR ENTRADAS (Compras + Devol. Vendas)', 'Valor': -total_credito},
                    {'Descrição': 'SALDO LÍQUIDO ICMS PRÓPRIO', 'Valor': saldo_icms},
                    {'Descrição': '---', 'Valor': None},
                    {'Descrição': 'TOTAL DÉBITO IPI', 'Valor': total_ipi_deb},
                    {'Descrição': 'TOTAL CRÉDITO IPI', 'Valor': -total_ipi_cred},
                    {'Descrição': 'SALDO IPI A RECOLHER', 'Valor': saldo_ipi}
                ])

            st.success("Auditoria e Livros concluídos com sucesso!")

            # Visualização em Abas no Streamlit
            tabs = st.tabs(["📊 Apuração", "📥 Resumo Entradas", "📤 Resumo Saídas", "🔎 Diagnósticos"])
            
            with tabs[0]:
                st.subheader("RAICMS / RAIPI (Confronto)")
                st.table(df_apuracao)
            with tabs[1]:
                st.subheader("Consolidado por CFOP - Entradas")
                st.dataframe(livro_entradas, use_container_width=True)
            with tabs[2]:
                st.subheader("Consolidado por CFOP - Saídas")
                st.dataframe(livro_saidas, use_container_width=True)
            with tabs[3]:
                st.subheader("Inconsistências Identificadas")
                erros = pd.concat([
                    df_ent[df_ent['DIAGNOSTICO_CURADOR'] != "Escrituração Regular"][['NUM_NF', 'CFOP', 'DIAGNOSTICO_CURADOR']].rename(columns={'NUM_NF': 'Doc'}),
                    df_sai[df_sai['DIAGNOSTICO_CURADOR'] != "Escrituração Regular"][['NF', 'CFOP', 'DIAGNOSTICO_CURADOR']].rename(columns={'NF': 'Doc'})
                ])
                if erros.empty: st.info("Escrituração 100% Regular.")
                else: st.dataframe(erros, use_container_width=True)

            # Geração do Arquivo Excel para Download
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                # 1. Analíticos com Auditoria
                df_ent.to_excel(writer, sheet_name='Entradas Analítico', index=False)
                df_sai.to_excel(writer, sheet_name='Saídas Analítico', index=False)
                # 2. Resumos de Livro
                livro_entradas.to_excel(writer, sheet_name='Livro Entradas (P9)', index=False)
                livro_saidas.to_excel(writer, sheet_name='Livro Saídas (P9)', index=False)
                # 3. Apuração Final
                df_apuracao.to_excel(writer, sheet_name='Apuração Consolidada', index=False)

                # Formatação Visual
                workbook = writer.book
                fmt_money = workbook.add_format({'num_format': '#,##0.00'})
                fmt_red = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
                fmt_header = workbook.add_format({'bold': True, 'bg_color': '#D9EAD3', 'border': 1})

                for sheet_name in writer.sheets:
                    ws = writer.sheets[sheet_name]
                    ws.set_column('A:AG', 18, fmt_money)
                    # Marcar linhas com erro nos analíticos
                    if 'Analítico' in sheet_name:
                        df_target = df_ent if 'Entradas' in sheet_name else df_sai
                        for i, val in enumerate(df_target['DIAGNOSTICO_CURADOR']):
                            if val != "Escrituração Regular": ws.set_row(i + 1, None, fmt_red)

            st.download_button(
                label="📥 Baixar Livros Fiscais e Auditoria (Curador)",
                data=output.getvalue(),
                file_name="Curador_Auditoria_Fiscal_Final.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        except Exception as e:
            st.error(f"Erro no processamento: {str(e)}")

    else:
        st.info("Suba as planilhas para que o Curador inicie a auditoria dos livros.")

if __name__ == "__main__":
    main()
