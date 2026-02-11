import streamlit as st
import pandas as pd
import io

# Configuração da página - O Curador
st.set_page_config(page_title="Curador - Auditoria Fiscal e Malha Total", layout="wide")

def clean_numeric_col(df, col_name):
    """Limpeza técnica de colunas numéricas para precisão fiscal absoluta."""
    if col_name in df.columns:
        s = df[col_name].astype(str).str.replace(r'\s+', '', regex=True)
        s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df[col_name] = pd.to_numeric(s, errors='coerce').fillna(0.0)
    return df

def auditoria_total(row, tipo='saida'):
    """
    Motor de Auditoria Analítica: Cruza CFOP, CST e Valores.
    Gera diagnósticos de erro e orientações de correção (Cliente e Domínio).
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
        erros.append("ICMS Próprio zerado no CFOP 6403.")
        cliente.append("Destacar ICMS Próprio na NF-e de Substituto Tributário.")
        dominio.append("Configurar Acumulador para calcular ICMS Próprio em operações de ST (Substituto).")
    
    if tipo == 'saida' and vlr_icms > 0 and bc_icms > 0:
        calc = round(bc_icms * (aliq / 100), 2)
        if abs(calc - vlr_icms) > 0.05:
            erros.append(f"Cálculo ICMS divergente (Esperado: {calc}).")
            cliente.append("Revisar faturamento: valor destacado não condiz com Base x Alíquota.")
            dominio.append("Verificar vigência da alíquota ou exceções de imposto no cadastro.")

    # --- MALHA ICMS ST ---
    if cst in cst_st and vlr_st == 0:
        erros.append(f"CST {cst_full} exige ICMS ST, mas valor está zerado.")
        cliente.append("Calcular e informar o valor do ICMS ST retido na nota.")
        dominio.append("No acumulador, aba Estadual, marcar 'Gera guia de recolhimento de ST'.")
    elif vlr_st > 0 and cst not in cst_st and cst != '60':
        erros.append(f"Destaque de ST indevido para CST {cst_full}.")
        cliente.append("Remover ST ou ajustar CST para 10, 30, 70 ou 90.")

    # --- MALHA IPI ---
    if cfop in ['5101', '6101'] and vlr_ipi == 0:
        erros.append("Venda industrial sem destaque de IPI.")
        cliente.append("Informar IPI (Saída de Produção Própria).")
        dominio.append("Vincular tabela de IPI no produto e usar Acumulador com incidência de IPI.")

    # --- MALHA UF (Interestadual) ---
    if tipo == 'saida' and cfop.startswith('6'):
        regiao_7 = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'RN', 'RO', 'RR', 'SE', 'TO']
        if uf_dest in regiao_7 and aliq not in [7.0, 4.0]:
            erros.append(f"Alíquota incorreta para {uf_dest}: espera-se 7% (ou 4%).")
            cliente.append(f"Ajustar alíquota interestadual para 7% para destino {uf_dest}.")

    res = {
        'DIAGNOSTICO': " | ".join(erros) if erros else "Escrituração Regular",
        'CORRECAO_CLIENTE': " | ".join(cliente) if cliente else "-",
        'AJUSTE_DOMINIO': " | ".join(dominio) if dominio else "-"
    }
    return pd.Series(res)

def gerar_livro_p9(df, tipo='entrada'):
    """Agrupamento por CFOP no padrão do Livro Registro de ICMS."""
    if tipo == 'entrada':
        df['Isentas'] = df.apply(lambda x: x['VC'] if str(x['CST-ICMS'])[-2:] in ['40', '41'] else 0, axis=1)
        df['Outras'] = df.apply(lambda x: x['VC'] if str(x['CST-ICMS'])[-2:] not in ['00', '10', '20', '40', '41'] else 0, axis=1)
        res = df.groupby('CFOP').agg({'VC': 'sum', 'BC-ICMS': 'sum', 'VLR-ICMS': 'sum', 'ICMS-ST': 'sum', 'VLR_IPI': 'sum', 'Isentas': 'sum', 'Outras': 'sum'}).reset_index()
        res.columns = ['CFOP', 'Vlr Contábil', 'Base ICMS', 'ICMS Cred.', 'ICMS ST', 'IPI Cred.', 'Isentas', 'Outras']
    else:
        df['Isentas'] = df.apply(lambda x: x['VC_ITEM'] if str(x['CST'])[-2:] in ['40', '41'] else 0, axis=1)
        df['Outras'] = df.apply(lambda x: x['VC_ITEM'] if str(x['CST'])[-2:] not in ['00', '10', '20', '40', '41'] else 0, axis=1)
        res = df.groupby('CFOP').agg({'VC_ITEM': 'sum', 'BC_ICMS': 'sum', 'ICMS': 'sum', 'ICMSST': 'sum', 'IPI': 'sum', 'Isentas': 'sum', 'Outras': 'sum'}).reset_index()
        res.columns = ['CFOP', 'Vlr Contábil', 'Base ICMS', 'ICMS Deb.', 'ICMS ST', 'IPI Deb.', 'Isentas', 'Outras']
    return res

def main():
    st.title("⚖️ Curador: Acervo Fiscal, Malha e Auditoria Total")
    st.markdown("---")
    
    st.sidebar.header("⚖️ Upload dos Pergaminhos")
    template_file = st.sidebar.file_uploader("📂 Planilha de Conferência (Template)", type=["xlsx"])
    ent_file = st.sidebar.file_uploader("📥 Entradas (CSV)", type=["csv"])
    sai_file = st.sidebar.file_uploader("📤 Saídas (CSV)", type=["csv"])

    if ent_file and sai_file:
        try:
            # Definição das colunas rigorosas
            cols_ent = ['NUM_NF', 'DATA_EMISSAO', 'CNPJ', 'UF', 'VLR_NF', 'AC', 'CFOP', 'COD_PROD', 'DESCR', 'NCM', 'UNID', 'VUNIT', 'QTDE', 'VPROD', 'DESC', 'FRETE', 'SEG', 'DESP', 'VC', 'CST-ICMS', 'BC-ICMS', 'VLR-ICMS', 'BC-ICMS-ST', 'ICMS-ST', 'VLR_IPI', 'CST_PIS', 'BC_PIS', 'VLR_PIS', 'CST_COF', 'BC_COF', 'VLR_COF']
            cols_sai = ['NF', 'DATA_EMISSAO', 'CNPJ', 'Ufp', 'VC', 'AC', 'CFOP', 'COD_ITEM', 'DESC_ITEM', 'NCM', 'UND', 'VUNIT', 'QTDE', 'VITEM', 'DESC', 'FRETE', 'SEG', 'OUTRAS', 'VC_ITEM', 'CST', 'BC_ICMS', 'ALIQ_ICMS', 'ICMS', 'BC_ICMSST', 'ICMSST', 'IPI', 'CST_PIS Escriturado', 'BC_PIS', 'PIS', 'CST_COF', 'BC_COF', 'COF']

            df_ent = pd.read_csv(ent_file, sep=';', encoding='latin-1', header=None, names=cols_ent)
            df_sai = pd.read_csv(sai_file, sep=';', encoding='latin-1', header=None, names=cols_sai)

            for c in ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'VC', 'ICMS-ST']: df_ent = clean_numeric_col(df_ent, c)
            for c in ['ICMS', 'IPI', 'BC_ICMS', 'VC_ITEM', 'ALIQ_ICMS', 'ICMSST']: df_sai = clean_numeric_col(df_sai, c)

            # Processamento da Malha e Consultoria
            df_ent[['DIAGNOSTICO', 'CORRECAO_CLIENTE', 'AJUSTE_DOMINIO']] = df_ent.apply(lambda r: auditoria_total(r, 'entrada'), axis=1)
            df_sai[['DIAGNOSTICO', 'CORRECAO_CLIENTE', 'AJUSTE_DOMINIO']] = df_sai.apply(lambda r: auditoria_total(r, 'saida'), axis=1)

            livro_ent = gerar_livro_p9(df_ent, 'entrada')
            livro_sai = gerar_livro_p9(df_sai, 'saida')

            # Saldos Finais
            v_icms = df_sai['ICMS'].sum() - df_ent['VLR-ICMS'].sum()
            v_st = df_sai['ICMSST'].sum() - df_ent['ICMS-ST'].sum()
            v_ipi = df_sai['IPI'].sum() - df_ent['VLR_IPI'].sum()

            st.success("Auditoria analítica concluída! Verifique o dashboard e baixe o arquivo completo.")
            
            # Dashboard
            m1, m2, m3 = st.columns(3)
            m1.metric("Saldo ICMS Próprio", f"R$ {v_icms:,.2f}", delta="A Recolher" if v_icms > 0 else "Credor")
            m2.metric("Saldo ICMS ST", f"R$ {v_st:,.2f}", delta="A Recolher" if v_st > 0 else "Credor")
            m3.metric("Saldo IPI", f"R$ {v_ipi:,.2f}", delta="A Recolher" if v_ipi > 0 else "Credor")

            # Exportação Mantendo Abas do Excel Original
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                # Se o usuário subir o template, preservamos as abas estáticas dele
                if template_file:
                    xls = pd.ExcelFile(template_file)
                    for sheet in xls.sheet_names:
                        # Pula as abas que vamos gerar de novo
                        if sheet not in ['Entradas Gerencial', 'Saídas Gerencial', 'Apuração de ICMS e IPI']:
                            pd.read_excel(xls, sheet_name=sheet).to_excel(writer, sheet_name=sheet, index=False)
                
                # Geramos as abas de trabalho (Mantendo nomes solicitados no início)
                df_ent.to_excel(writer, sheet_name='Entradas Gerencial', index=False)
                df_sai.to_excel(writer, sheet_name='Saídas Gerencial', index=False)
                livro_ent.to_excel(writer, sheet_name='Resumo P9 Entradas', index=False)
                livro_sai.to_excel(writer, sheet_name='Resumo P9 Saídas', index=False)
                
                df_apur = pd.DataFrame([
                    {'Imposto': 'ICMS Próprio', 'Débito': df_sai['ICMS'].sum(), 'Crédito': -df_ent['VLR-ICMS'].sum(), 'Saldo': v_icms},
                    {'Imposto': 'ICMS ST', 'Débito': df_sai['ICMSST'].sum(), 'Crédito': -df_ent['ICMS-ST'].sum(), 'Saldo': v_st},
                    {'Imposto': 'IPI', 'Débito': df_sai['IPI'].sum(), 'Crédito': -df_ent['VLR_IPI'].sum(), 'Saldo': v_ipi}
                ])
                df_apur.to_excel(writer, sheet_name='Apuração de ICMS e IPI', index=False)

                # Formatação Visual de Auditoria
                workbook = writer.book
                fmt_red = workbook.add_format({'bg_color': '#FFC7CE', 'font_color': '#9C0006'})
                fmt_num = workbook.add_format({'num_format': '#,##0.00'})
                for sheet in ['Entradas Gerencial', 'Saídas Gerencial']:
                    ws = writer.sheets[sheet]
                    ws.set_column('A:AN', 18, fmt_num)
                    df_ref = df_ent if 'Entradas' in sheet else df_sai
                    for i, val in enumerate(df_ref['DIAGNOSTICO']):
                        if val != "Escrituração Regular": ws.set_row(i + 1, None, fmt_red)

            st.download_button("📥 Baixar Planilha Completa (O Curador)", output.getvalue(), "Conferência_Curador_Malha_Total.xlsx")

        except Exception as e:
            st.error(f"Erro Crítico: {e}")

if __name__ == "__main__":
    main()
