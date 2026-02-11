import streamlit as st
import pandas as pd
import io

# Configuração da página - O Curador
st.set_page_config(page_title="Curador - Auditoria Total e Malha Fiscal", layout="wide")

def clean_numeric_col(df, col_name):
    """Limpeza técnica de colunas numéricas para precisão fiscal absoluta."""
    if col_name in df.columns:
        s = df[col_name].astype(str).str.replace(r'\s+', '', regex=True)
        s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df[col_name] = pd.to_numeric(s, errors='coerce').fillna(0.0)
    return df

def auditoria_entradas(row):
    """
    Diagnóstico de Malha Fiscal para Entradas (ICMS, ST e IPI).
    Valida Créditos, Devoluções de Vendas e Inconsistências de Escrituração.
    """
    cfop = str(row['CFOP']).strip().replace('.', '')
    cst = str(row['CST-ICMS']).zfill(2)
    vlr_icms = row['VLR-ICMS']
    vlr_st = row['ICMS-ST']
    vlr_ipi = row['VLR_IPI']
    
    # Grupos de Regras
    cfops_dev_venda = ['1201', '1202', '2201', '2202', '1410', '1411', '2410', '2411']
    cfops_credito_cheio = ['1101', '1102', '2101', '2102']
    cfops_industrializacao = ['1101', '2101']
    cst_exige_st = ['10', '30', '70', '90']
    
    alertas = []
    
    # 1. Malha de ICMS ST (Entrada)
    if cst in cst_exige_st and vlr_st == 0:
        alertas.append(f"ST OMISSO: CST {cst} exige ICMS ST, mas valor está zerado.")
    if vlr_st > 0 and cst not in cst_exige_st and cst != '60':
        alertas.append(f"ST INDEVIDO: Valor de ST escriturado para CST {cst}.")

    # 2. Malha de IPI (Crédito Industrial)
    if cfop in cfops_industrializacao and vlr_ipi == 0:
        alertas.append("IPI ALERTA: Compra industrial sem aproveitamento de crédito de IPI.")

    # 3. Malha de ICMS Próprio e Devoluções
    if cfop in cfops_dev_venda and vlr_icms == 0 and cst not in ['40', '41', '60']:
        alertas.append("DEVOLUÇÃO SEM CRÉDITO: Entrada de devolução sem anulação do ICMS.")
    elif cfop in cfops_credito_cheio and cst in ['00', '10', '20'] and vlr_icms == 0:
        alertas.append("CRÉDITO NÃO TOMADO: Operação tributada sem crédito de ICMS.")
            
    return " | ".join(alertas) if alertas else "Escrituração Regular"

def auditoria_saidas(row):
    """
    Diagnóstico de Malha Fiscal para Saídas (ICMS, ST e IPI).
    Valida Alíquotas UF, Destaques ST e Obrigatoriedade de IPI Industrial.
    """
    cfop = str(row['CFOP']).strip().replace('.', '')
    cst = str(row['CST']).zfill(2)
    vlr_icms = row['ICMS']
    bc_icms = row['BC_ICMS']
    aliq = row['ALIQ_ICMS']
    uf_dest = str(row['Ufp']).strip().upper()
    vlr_st = row['ICMSST']
    vlr_ipi = row['IPI']
    
    cfops_venda_industria = ['5101', '6101']
    cfops_venda_comercio = ['5102', '6102']
    cst_exige_st = ['10', '30', '70', '90']
    
    alertas = []
    
    # 1. Malha de ICMS ST (Saída)
    if cst in cst_exige_st and vlr_st == 0:
        alertas.append(f"MALHA ST: CST {cst} exige destaque de ST na nota.")
    if vlr_st > 0 and cst not in cst_exige_st:
        alertas.append(f"MALHA ST: ICMS ST destacado com CST {cst} incompatível.")

    # 2. Malha de IPI (Saída Industrial)
    if cfop in cfops_venda_industria and vlr_ipi == 0:
        alertas.append("IPI OMISSO: Venda de produção própria sem destaque de IPI.")

    # 3. Malha Interestadual e Alíquotas (Origem SP assumida)
    if cfop.startswith('6'):
        uf_7 = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'RN', 'RO', 'RR', 'SE', 'TO']
        uf_12 = ['PR', 'RS', 'SC', 'MG', 'RJ']
        
        if uf_dest in uf_7 and aliq not in [7.0, 4.0]:
            alertas.append(f"ALÍQUOTA UF: Destino {uf_dest} espera 7% (ou 4%), aplicado {aliq}%.")
        elif uf_dest in uf_12 and aliq not in [12.0, 4.0]:
            alertas.append(f"ALÍQUOTA UF: Destino {uf_dest} espera 12% (ou 4%), aplicado {aliq}%.")

    # 4. Auditoria Matemática
    if vlr_icms > 0 and bc_icms > 0:
        vlr_calc = round(bc_icms * (aliq / 100), 2)
        if abs(vlr_calc - vlr_icms) > 0.05:
            alertas.append(f"ERRO CÁLCULO: ICMS destacado {vlr_icms} != calculado {vlr_calc}.")
            
    return " | ".join(alertas) if alertas else "Escrituração Regular"

def gerar_livro_p9(df, tipo='entrada'):
    """Agrupamento por CFOP no padrão do Livro Registro de ICMS."""
    if tipo == 'entrada':
        df['Isentas'] = df.apply(lambda x: x['VC'] if str(x['CST-ICMS']) in ['40', '41'] else 0, axis=1)
        df['Outras'] = df.apply(lambda x: x['VC'] if str(x['CST-ICMS']) not in ['00', '10', '20', '40', '41'] else 0, axis=1)
        resumo = df.groupby('CFOP').agg({'VC': 'sum', 'BC-ICMS': 'sum', 'VLR-ICMS': 'sum', 'ICMS-ST': 'sum', 'VLR_IPI': 'sum', 'Isentas': 'sum', 'Outras': 'sum'}).reset_index()
        resumo.columns = ['CFOP', 'Vlr Contábil', 'Base ICMS', 'ICMS Cred.', 'ICMS ST', 'IPI Cred.', 'Isentas', 'Outras']
    else:
        df['Isentas'] = df.apply(lambda x: x['VC_ITEM'] if str(x['CST']) in ['40', '41'] else 0, axis=1)
        df['Outras'] = df.apply(lambda x: x['VC_ITEM'] if str(x['CST']) not in ['00', '10', '20', '40', '41'] else 0, axis=1)
        resumo = df.groupby('CFOP').agg({'VC_ITEM': 'sum', 'BC_ICMS': 'sum', 'ICMS': 'sum', 'ICMSST': 'sum', 'IPI': 'sum', 'Isentas': 'sum', 'Outras': 'sum'}).reset_index()
        resumo.columns = ['CFOP', 'Vlr Contábil', 'Base ICMS', 'ICMS Deb.', 'ICMS ST', 'IPI Deb.', 'Isentas', 'Outras']
    return resumo

def main():
    st.title("⚖️ Curador: Malha Fiscal e Apuração Total")
    st.markdown("---")
    
    c1, c2 = st.columns(2)
    with c1: ent_file = st.file_uploader("📥 Entradas Gerenciais (CSV)", type=["csv"])
    with c2: sai_file = st.file_uploader("📤 Saídas Gerenciais (CSV)", type=["csv"])

    if ent_file and sai_file:
        try:
            cols_ent = ['NUM_NF', 'DATA_EMISSAO', 'CNPJ', 'UF', 'VLR_NF', 'AC', 'CFOP', 'COD_PROD', 'DESCR', 'NCM', 'UNID', 'VUNIT', 'QTDE', 'VPROD', 'DESC', 'FRETE', 'SEG', 'DESP', 'VC', 'CST-ICMS', 'BC-ICMS', 'VLR-ICMS', 'BC-ICMS-ST', 'ICMS-ST', 'VLR_IPI', 'CST_PIS', 'BC_PIS', 'VLR_PIS', 'CST_COF', 'BC_COF', 'VLR_COF']
            cols_sai = ['NF', 'DATA_EMISSAO', 'CNPJ', 'Ufp', 'VC', 'AC', 'CFOP', 'COD_ITEM', 'DESC_ITEM', 'NCM', 'UND', 'VUNIT', 'QTDE', 'VITEM', 'DESC', 'FRETE', 'SEG', 'OUTRAS', 'VC_ITEM', 'CST', 'BC_ICMS', 'ALIQ_ICMS', 'ICMS', 'BC_ICMSST', 'ICMSST', 'IPI', 'CST_PIS Escriturado', 'BC_PIS', 'PIS', 'CST_COF', 'BC_COF', 'COF']

            with st.spinner('O Curador está processando a malha fiscal completa...'):
                df_ent = pd.read_csv(ent_file, sep=';', encoding='latin-1', header=None, names=cols_ent)
                df_sai = pd.read_csv(sai_file, sep=';', encoding='latin-1', header=None, names=cols_sai)

                # Limpeza de valores
                for c in ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'VC', 'ICMS-ST']: df_ent = clean_numeric_col(df_ent, c)
                for c in ['ICMS', 'IPI', 'BC_ICMS', 'VC_ITEM', 'ALIQ_ICMS', 'ICMSST']: df_sai = clean_numeric_col(df_sai, c)

                # Diagnósticos de Malha
                df_ent['DIAGNOSTICO_CURADOR'] = df_ent.apply(auditoria_entradas, axis=1)
                df_sai['DIAGNOSTICO_CURADOR'] = df_sai.apply(auditoria_saidas, axis=1)

                livro_ent = gerar_livro_p9(df_ent, 'entrada')
                livro_sai = gerar_livro_p9(df_sai, 'saida')

                # Apuração Consolidada
                v_icms_deb = df_sai['ICMS'].sum()
                v_icms_cre = df_ent['VLR-ICMS'].sum()
                v_st_deb = df_sai['ICMSST'].sum()
                v_st_cre = df_ent['ICMS-ST'].sum()
                v_ipi_deb = df_sai['IPI'].sum()
                v_ipi_cre = df_ent['VLR_IPI'].sum()

                apuracao_final = [
                    {'Imposto': 'ICMS PRÓPRIO', 'Natureza': 'DÉBITOS', 'Valor': v_icms_deb},
                    {'Imposto': 'ICMS PRÓPRIO', 'Natureza': 'CRÉDITOS', 'Valor': -v_icms_cre},
                    {'Imposto': 'ICMS PRÓPRIO', 'Natureza': 'RESULTADO', 'Valor': v_icms_deb - v_icms_cre},
                    {'Imposto': '---', 'Natureza': '---', 'Valor': None},
                    {'Imposto': 'ICMS ST', 'Natureza': 'DÉBITOS', 'Valor': v_st_deb},
                    {'Imposto': 'ICMS ST', 'Natureza': 'CRÉDITOS (DEV)', 'Valor': -v_st_cre},
                    {'Imposto': 'ICMS ST', 'Natureza': 'RESULTADO', 'Valor': v_st_deb - v_st_cre},
                    {'Imposto': '---', 'Natureza': '---', 'Valor': None},
                    {'Imposto': 'IPI', 'Natureza': 'DÉBITOS', 'Valor': v_ipi_deb},
                    {'Imposto': 'IPI', 'Natureza': 'CRÉDITOS', 'Valor': -v_ipi_cre},
                    {'Imposto': 'IPI', 'Natureza': 'RESULTADO', 'Valor': v_ipi_deb - v_ipi_cre},
                ]
                df_apur = pd.DataFrame(apuracao_final)

            st.success("Auditoria Finalizada com Sucesso!")
            
            # Exibição do Valor Final com destaque
            res_icms = v_icms_deb - v_icms_cre
            tipo_icms = "RECOLHER" if res_icms > 0 else "CREDOR"
            st.metric(label=f"SALDO ICMS PRÓPRIO ({tipo_icms})", value=f"R$ {abs(res_icms):,.2f}")

            tabs = st.tabs(["📊 Apuração Consolidada", "📖 Resumo por CFOP", "🔎 Diagnóstico de Malha"])
            with tabs[0]: 
                st.subheader("Confronto Geral de Impostos")
                st.table(df_apur)
            with tabs[1]:
                st.subheader("Livros Registro de ICMS/IPI")
                st.write("Entradas:")
                st.dataframe(livro_ent, use_container_width=True)
                st.write("Saídas:")
                st.dataframe(livro_sai, use_container_width=True)
            with tabs[2]:
                st.subheader("Inconsistências de Malha Detectadas")
                erros = pd.concat([
                    df_ent[df_ent['DIAGNOSTICO_CURADOR'] != "Escrituração Regular"][['NUM_NF', 'CFOP', 'DIAGNOSTICO_CURADOR']].rename(columns={'NUM_NF': 'Doc'}),
                    df_sai[df_sai['DIAGNOSTICO_CURADOR'] != "Escrituração Regular"][['NF', 'CFOP', 'DIAGNOSTICO_CURADOR']].rename(columns={'NF': 'Doc'})
                ])
                if erros.empty: st.info("Escrituração está 100% Regular.")
                else: st.dataframe(erros, use_container_width=True)

            # Exportação Excel Íntegra
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

            st.download_button("📥 Baixar Auditoria Final (O Curador)", output.getvalue(), "Auditoria_Curador_Malha_Total.xlsx")

        except Exception as e:
            st.error(f"Erro Crítico na Auditoria: {e}")
    else:
        st.info("Suba os arquivos gerenciais para iniciar a auditoria de ICMS, ST e IPI.")

if __name__ == "__main__":
    main()
