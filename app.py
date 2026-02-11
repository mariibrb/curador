import streamlit as st
import pandas as pd
import io

# Configuração da página - O Curador
st.set_page_config(page_title="Curador - Auditoria Total ICMS/ST/IPI", layout="wide")

def clean_numeric_col(df, col_name):
    """Limpeza técnica de colunas numéricas para precisão fiscal absoluta."""
    if col_name in df.columns:
        s = df[col_name].astype(str).str.replace(r'\s+', '', regex=True)
        s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df[col_name] = pd.to_numeric(s, errors='coerce').fillna(0.0)
    return df

def auditoria_entradas(row):
    """Diagnóstico de Malha Fiscal para Entradas e Créditos."""
    cfop = str(row['CFOP']).strip().replace('.', '')
    cst = str(row['CST-ICMS']).zfill(2)
    vlr_icms = row['VLR-ICMS']
    vlr_st = row['ICMS-ST']
    vlr_ipi = row['VLR_IPI']
    
    # Grupos de CFOP
    cfops_dev_venda = ['1201', '1202', '2201', '2202', '1410', '1411', '2410', '2411']
    cfops_industrializacao = ['1101', '2101']
    cst_com_st = ['10', '30', '70', '90']
    
    alertas = []
    
    # 1. Auditoria ICMS ST (Malha CST vs Destaque)
    if cst in cst_com_st and vlr_st == 0:
        alertas.append(f"ST OMISSO: CST {cst} exige ICMS ST, mas o valor está zerado.")
    if vlr_st > 0 and cst not in cst_com_st and cst != '60':
        alertas.append(f"ST INDEVIDO: Valor de ST escriturado, mas CST {cst} não prevê destaque.")

    # 2. Auditoria IPI
    if cfop in cfops_industrializacao and vlr_ipi == 0:
        alertas.append("IPI OMISSO: Compra para industrialização sem crédito de IPI.")

    # 3. Auditoria de Devolução e Crédito ICMS
    if cfop in cfops_dev_venda and vlr_icms == 0 and cst not in ['40', '41', '60']:
        alertas.append("DEVOLUÇÃO SEM CRÉDITO: Entrada de devolução sem anulação do ICMS.")
            
    return " | ".join(alertas) if alertas else "Escrituração Regular"

def auditoria_saidas(row):
    """Diagnóstico de Malha Fiscal para Saídas, Débitos e IPI."""
    cfop = str(row['CFOP']).strip().replace('.', '')
    cst = str(row['CST']).zfill(2)
    vlr_icms = row['ICMS']
    bc_icms = row['BC_ICMS']
    aliq = row['ALIQ_ICMS']
    uf_dest = str(row['Ufp']).strip().upper()
    vlr_st = row['ICMSST']
    vlr_ipi = row['IPI']
    
    cfops_industria = ['5101', '6101']
    cst_com_st = ['10', '30', '70', '90']
    
    alertas = []
    
    # 1. Auditoria ICMS ST (Saída)
    if cst in cst_com_st and vlr_st == 0:
        alertas.append(f"MALHA ST: CST {cst} (ST) sem destaque de ICMS ST na nota.")
    if vlr_st > 0 and cst not in cst_com_st:
        alertas.append(f"MALHA ST: Destaque de ST identificado, mas CST {cst} é incompatível.")

    # 2. Auditoria IPI (Saída Industrial)
    if cfop in cfops_industria and vlr_ipi == 0:
        alertas.append("IPI OMISSO: Venda de produção própria sem destaque de IPI.")

    # 3. Auditoria Alíquota Interestadual (Saídas de SP)
    if cfop.startswith('6'):
        uf_7 = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'RN', 'RO', 'RR', 'SE', 'TO']
        uf_12 = ['PR', 'RS', 'SC', 'MG', 'RJ']
        
        if uf_dest in uf_7 and aliq not in [7.0, 4.0]:
            alertas.append(f"ALÍQUOTA DIVERGENTE: UF {uf_dest} espera 7% (ou 4%), aplicado {aliq}%.")
        elif uf_dest in uf_12 and aliq not in [12.0, 4.0]:
            alertas.append(f"ALÍQUOTA DIVERGENTE: UF {uf_dest} espera 12% (ou 4%), aplicado {aliq}%.")

    # 4. Auditoria Matemática
    if vlr_icms > 0 and bc_icms > 0:
        vlr_calc = round(bc_icms * (aliq / 100), 2)
        if abs(vlr_calc - vlr_icms) > 0.05:
            alertas.append(f"CÁLCULO ICMS: Destacado {vlr_icms}, mas o cálculo resulta em {vlr_calc}.")
            
    return " | ".join(alertas) if alertas else "Escrituração Regular"

def gerar_livro_p9(df, tipo='entrada'):
    """Consolidação por CFOP no formato do Livro Registro (Modelo P9)."""
    if tipo == 'entrada':
        df['Isentas'] = df.apply(lambda x: x['VC'] if str(x['CST-ICMS']) in ['40', '41'] else 0, axis=1)
        df['Outras'] = df.apply(lambda x: x['VC'] if str(x['CST-ICMS']) not in ['00', '10', '20', '40', '41'] else 0, axis=1)
        resumo = df.groupby('CFOP').agg({'VC': 'sum', 'BC-ICMS': 'sum', 'VLR-ICMS': 'sum', 'ICMS-ST': 'sum', 'VLR_IPI': 'sum', 'Isentas': 'sum', 'Outras': 'sum'}).reset_index()
        resumo.columns = ['CFOP', 'Valor Contábil', 'Base ICMS', 'ICMS Creditado', 'ICMS ST', 'IPI Creditado', 'Isentas', 'Outras']
    else:
        df['Isentas'] = df.apply(lambda x: x['VC_ITEM'] if str(x['CST']) in ['40', '41'] else 0, axis=1)
        df['Outras'] = df.apply(lambda x: x['VC_ITEM'] if str(x['CST']) not in ['00', '10', '20', '40', '41'] else 0, axis=1)
        resumo = df.groupby('CFOP').agg({'VC_ITEM': 'sum', 'BC_ICMS': 'sum', 'ICMS': 'sum', 'ICMSST': 'sum', 'IPI': 'sum', 'Isentas': 'sum', 'Outras': 'sum'}).reset_index()
        resumo.columns = ['CFOP', 'Valor Contábil', 'Base ICMS', 'ICMS Debitado', 'ICMS ST', 'IPI Debitado', 'Isentas', 'Outras']
    return resumo

def main():
    st.title("⚖️ Curador: Auditoria Integral ICMS, ST e IPI")
    st.markdown("---")
    
    c1, c2 = st.columns(2)
    with c1: ent_file = st.file_uploader("📥 Entradas (CSV)", type=["csv"])
    with c2: sai_file = st.file_uploader("📤 Saídas (CSV)", type=["csv"])

    if ent_file and sai_file:
        try:
            cols_ent = ['NUM_NF', 'DATA_EMISSAO', 'CNPJ', 'UF', 'VLR_NF', 'AC', 'CFOP', 'COD_PROD', 'DESCR', 'NCM', 'UNID', 'VUNIT', 'QTDE', 'VPROD', 'DESC', 'FRETE', 'SEG', 'DESP', 'VC', 'CST-ICMS', 'BC-ICMS', 'VLR-ICMS', 'BC-ICMS-ST', 'ICMS-ST', 'VLR_IPI', 'CST_PIS', 'BC_PIS', 'VLR_PIS', 'CST_COF', 'BC_COF', 'VLR_COF']
            cols_sai = ['NF', 'DATA_EMISSAO', 'CNPJ', 'Ufp', 'VC', 'AC', 'CFOP', 'COD_ITEM', 'DESC_ITEM', 'NCM', 'UND', 'VUNIT', 'QTDE', 'VITEM', 'DESC', 'FRETE', 'SEG', 'OUTRAS', 'VC_ITEM', 'CST', 'BC_ICMS', 'ALIQ_ICMS', 'ICMS', 'BC_ICMSST', 'ICMSST', 'IPI', 'CST_PIS Escriturado', 'BC_PIS', 'PIS', 'CST_COF', 'BC_COF', 'COF']

            with st.spinner('O Curador está processando a malha fiscal...'):
                df_ent = pd.read_csv(ent_file, sep=';', encoding='latin-1', header=None, names=cols_ent)
                df_sai = pd.read_csv(sai_file, sep=';', encoding='latin-1', header=None, names=cols_sai)

                # Limpeza de valores para Auditoria
                for c in ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'VC', 'ICMS-ST']: df_ent = clean_numeric_col(df_ent, c)
                for c in ['ICMS', 'IPI', 'BC_ICMS', 'VC_ITEM', 'ALIQ_ICMS', 'ICMSST']: df_sai = clean_numeric_col(df_sai, c)

                # Execução da Auditoria Inteligente
                df_ent['DIAGNOSTICO_CURADOR'] = df_ent.apply(auditoria_entradas, axis=1)
                df_sai['DIAGNOSTICO_CURADOR'] = df_sai.apply(auditoria_saidas, axis=1)

                livro_ent = gerar_livro_p9(df_ent, 'entrada')
                livro_sai = gerar_livro_p9(df_sai, 'saida')

                # Apuração Consolidada
                df_apur = pd.DataFrame([
                    {'Descrição': 'DÉBITO ICMS PRÓPRIO', 'Valor': df_sai['ICMS'].sum()},
                    {'Descrição': 'CRÉDITO ICMS PRÓPRIO', 'Valor': -df_ent['VLR-ICMS'].sum()},
                    {'Descrição': 'SALDO ICMS PRÓPRIO', 'Valor': df_sai['ICMS'].sum() - df_ent['VLR-ICMS'].sum()},
                    {'Descrição': '-', 'Valor': None},
                    {'Descrição': 'DÉBITO ICMS ST', 'Valor': df_sai['ICMSST'].sum()},
                    {'Descrição': 'CRÉDITO ICMS ST (Devol.)', 'Valor': -df_ent['ICMS-ST'].sum()},
                    {'Descrição': 'SALDO ICMS ST A RECOLHER', 'Valor': df_sai['ICMSST'].sum() - df_ent['ICMS-ST'].sum()},
                    {'Descrição': '-', 'Valor': None},
                    {'Descrição': 'DÉBITO IPI', 'Valor': df_sai['IPI'].sum()},
                    {'Descrição': 'CRÉDITO IPI', 'Valor': -df_ent['VLR_IPI'].sum()},
                    {'Descrição': 'SALDO IPI A RECOLHER', 'Valor': df_sai['IPI'].sum() - df_ent['VLR_IPI'].sum()}
                ])

            st.success("Malha Fiscal processada!")
            
            tabs = st.tabs(["📊 Apuração Final", "📖 Livro Entradas", "📖 Livro Saídas", "🔎 Diagnóstico de Malha"])
            with tabs[0]: st.table(df_apur)
            with tabs[1]: st.dataframe(livro_ent, use_container_width=True)
            with tabs[2]: st.dataframe(livro_sai, use_container_width=True)
            with tabs[3]:
                erros = pd.concat([
                    df_ent[df_ent['DIAGNOSTICO_CURADOR'] != "Escrituração Regular"][['NUM_NF', 'CFOP', 'DIAGNOSTICO_CURADOR']].rename(columns={'NUM_NF': 'Doc'}),
                    df_sai[df_sai['DIAGNOSTICO_CURADOR'] != "Escrituração Regular"][['NF', 'CFOP', 'DIAGNOSTICO_CURADOR']].rename(columns={'NF': 'Doc'})
                ])
                st.dataframe(erros, use_container_width=True)

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_ent.to_excel(writer, sheet_name='Entradas Analítico', index=False)
                df_sai.to_excel(writer, sheet_name='Saídas Analítico', index=False)
                livro_ent.to_excel(writer, sheet_name='Resumo P9 Entradas', index=False)
                livro_sai.to_excel(writer, sheet_name='Resumo P9 Saídas', index=False)
                df_apur.to_excel(writer, sheet_name='Apuração Consolidada', index=False)
                
                workbook = writer.book
                fmt_red = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
                fmt_num = workbook.add_format({'num_format': '#,##0.00'})
                
                for sheet, df in [('Entradas Analítico', df_ent), ('Saídas Analítico', df_sai)]:
                    ws = writer.sheets[sheet]
                    ws.set_column('A:AG', 18, fmt_num)
                    for i, val in enumerate(df['DIAGNOSTICO_CURADOR']):
                        if val != "Escrituração Regular": ws.set_row(i + 1, None, fmt_red)

            st.download_button("📥 Baixar Auditoria Completa (O Curador)", output.getvalue(), "Curador_Malha_Fiscal_Total.xlsx")

        except Exception as e:
            st.error(f"Erro na auditoria: {e}")
    else:
        st.info("Suba os arquivos para que o Curador inicie a validação de ICMS, ST e IPI.")

if __name__ == "__main__":
    main()
