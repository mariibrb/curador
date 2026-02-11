import streamlit as st
import pandas as pd
import io

# Configuração da página - O Curador
st.set_page_config(page_title="Curador - Malha Fiscal Total", layout="wide")

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
        cliente.append("Destacar ICMS Próprio na NF-e de Substituto.")
        dominio.append("Configurar Acumulador para calcular ICMS Próprio em operações de ST.")
    
    if tipo == 'saida' and vlr_icms > 0 and bc_icms > 0:
        calc = round(bc_icms * (aliq / 100), 2)
        if abs(calc - vlr_icms) > 0.05:
            erros.append(f"Cálculo ICMS divergente (Esperado: {calc}).")
            cliente.append("Revisar alíquota ou base de cálculo no faturamento.")
            dominio.append("Verificar vigência da alíquota no cadastro do produto.")

    # --- MALHA ICMS ST ---
    if cst in cst_st and vlr_st == 0:
        erros.append(f"CST {cst_full} exige ICMS ST, mas valor está zerado.")
        cliente.append("Calcular e destacar o valor do ICMS ST retido.")
        dominio.append("No acumulador, aba Estadual, marcar 'Gera guia de ST'.")
    elif vlr_st > 0 and cst not in cst_st and cst != '60':
        erros.append(f"Destaque de ST indevido para CST {cst_full}.")
        cliente.append("Corrigir CST para 10 ou remover valor de ST.")

    # --- MALHA IPI ---
    if cfop in ['5101', '6101'] and vlr_ipi == 0:
        erros.append("Venda industrial sem destaque de IPI.")
        cliente.append("Informar IPI (Saída de Produção Própria).")
        dominio.append("Vincular tabela de IPI no produto e usar Acumulador industrial.")

    # --- MALHA UF (Interestadual) ---
    if tipo == 'saida' and cfop.startswith('6'):
        regiao_7 = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'RN', 'RO', 'RR', 'SE', 'TO']
        if uf_dest in regiao_7 and aliq not in [7.0, 4.0]:
            erros.append(f"Alíquota incorreta para {uf_dest} (7%).")
            cliente.append(f"Alterar alíquota interestadual para 7% para {uf_dest}.")

    res = {
        'DIAGNOSTICO': " | ".join(erros) if erros else "Escrituração Regular",
        'ACAO_CLIENTE': " | ".join(cliente) if cliente else "-",
        'AJUSTE_DOMINIO': " | ".join(dominio) if dominio else "-"
    }
    return pd.Series(res)

def gerar_livro_p9(df, tipo='entrada'):
    """Resumo por CFOP no padrão do Livro Registro."""
    if tipo == 'entrada':
        df['Isentas'] = df.apply(lambda x: x['VC'] if str(x['CST-ICMS'])[-2:] in ['40', '41'] else 0, axis=1)
        df['Outras'] = df.apply(lambda x: x['VC'] if str(x['CST-ICMS'])[-2:] not in ['00', '10', '20', '40', '41'] else 0, axis=1)
        res = df.groupby('CFOP').agg({'VC': 'sum', 'BC-ICMS': 'sum', 'VLR-ICMS': 'sum', 'ICMS-ST': 'sum', 'VLR_IPI': 'sum', 'Isentas': 'sum', 'Outras': 'sum'}).reset_index()
    else:
        df['Isentas'] = df.apply(lambda x: x['VC_ITEM'] if str(x['CST'])[-2:] in ['40', '41'] else 0, axis=1)
        df['Outras'] = df.apply(lambda x: x['VC_ITEM'] if str(x['CST'])[-2:] not in ['00', '10', '20', '40', '41'] else 0, axis=1)
        res = df.groupby('CFOP').agg({'VC_ITEM': 'sum', 'BC_ICMS': 'sum', 'ICMS': 'sum', 'ICMSST': 'sum', 'IPI': 'sum', 'Isentas': 'sum', 'Outras': 'sum'}).reset_index()
    return res

def main():
    st.title("⚖️ Curador: Malha Fiscal e Consultoria (ICMS / ST / IPI)")
    st.markdown("---")
    
    c1, c2 = st.columns(2)
    with c1: ent_file = st.file_uploader("📥 Entradas (CSV)", type=["csv"])
    with c2: sai_file = st.file_uploader("📤 Saídas (CSV)", type=["csv"])

    if ent_file and sai_file:
        try:
            cols_ent = ['NUM_NF', 'DATA_EMISSAO', 'CNPJ', 'UF', 'VLR_NF', 'AC', 'CFOP', 'COD_PROD', 'DESCR', 'NCM', 'UNID', 'VUNIT', 'QTDE', 'VPROD', 'DESC', 'FRETE', 'SEG', 'DESP', 'VC', 'CST-ICMS', 'BC-ICMS', 'VLR-ICMS', 'BC-ICMS-ST', 'ICMS-ST', 'VLR_IPI', 'CST_PIS', 'BC_PIS', 'VLR_PIS', 'CST_COF', 'BC_COF', 'VLR_COF']
            cols_sai = ['NF', 'DATA_EMISSAO', 'CNPJ', 'Ufp', 'VC', 'AC', 'CFOP', 'COD_ITEM', 'DESC_ITEM', 'NCM', 'UND', 'VUNIT', 'QTDE', 'VITEM', 'DESC', 'FRETE', 'SEG', 'OUTRAS', 'VC_ITEM', 'CST', 'BC_ICMS', 'ALIQ_ICMS', 'ICMS', 'BC_ICMSST', 'ICMSST', 'IPI', 'CST_PIS Escriturado', 'BC_PIS', 'PIS', 'CST_COF', 'BC_COF', 'COF']

            df_ent = pd.read_csv(ent_file, sep=';', encoding='latin-1', header=None, names=cols_ent)
            df_sai = pd.read_csv(sai_file, sep=';', encoding='latin-1', header=None, names=cols_sai)

            for c in ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'VC', 'ICMS-ST']: df_ent = clean_numeric_col(df_ent, c)
            for c in ['ICMS', 'IPI', 'BC_ICMS', 'VC_ITEM', 'ALIQ_ICMS', 'ICMSST']: df_sai = clean_numeric_col(df_sai, c)

            # Execução da Auditoria Analítica
            df_ent[['DIAGNOSTICO', 'CORRECAO_CLIENTE', 'AJUSTE_DOMINIO']] = df_ent.apply(lambda r: auditoria_total(r, 'entrada'), axis=1)
            df_sai[['DIAGNOSTICO', 'CORRECAO_CLIENTE', 'AJUSTE_DOMINIO']] = df_sai.apply(lambda r: auditoria_total(r, 'saida'), axis=1)

            # Cálculos de Saldo
            v_icms = df_sai['ICMS'].sum() - df_ent['VLR-ICMS'].sum()
            v_st = df_sai['ICMSST'].sum() - df_ent['ICMS-ST'].sum()
            v_ipi = df_sai['IPI'].sum() - df_ent['VLR_IPI'].sum()

            st.success("Análise de Malha Concluída!")
            
            # Dashboard
            m1, m2, m3 = st.columns(3)
            m1.metric("Saldo ICMS Próprio", f"R$ {v_icms:,.2f}", delta="Recolher" if v_icms > 0 else "Credor")
            m2.metric("Saldo ICMS ST", f"R$ {v_st:,.2f}", delta="Recolher" if v_st > 0 else "Credor")
            m3.metric("Saldo IPI", f"R$ {v_ipi:,.2f}", delta="Recolher" if v_ipi > 0 else "Credor")

            tabs = st.tabs(["🔎 Alertas de Malha", "📖 Livros Fiscais", "📊 Apuração Final"])
            with tabs[0]:
                erros = pd.concat([
                    df_ent[df_ent['DIAGNOSTICO'] != "Escrituração Regular"][['NUM_NF', 'CFOP', 'DIAGNOSTICO', 'CORRECAO_CLIENTE', 'AJUSTE_DOMINIO']].rename(columns={'NUM_NF': 'Doc'}),
                    df_sai[df_sai['DIAGNOSTICO'] != "Escrituração Regular"][['NF', 'CFOP', 'DIAGNOSTICO', 'CORRECAO_CLIENTE', 'AJUSTE_DOMINIO']].rename(columns={'NF': 'Doc'})
                ])
                st.dataframe(erros, use_container_width=True)
            with tabs[2]:
                st.table(pd.DataFrame([
                    {'Imposto': 'ICMS Próprio', 'Débito': df_sai['ICMS'].sum(), 'Crédito': -df_ent['VLR-ICMS'].sum(), 'Saldo': v_icms},
                    {'Imposto': 'ICMS ST', 'Débito': df_sai['ICMSST'].sum(), 'Crédito': -df_ent['ICMS-ST'].sum(), 'Saldo': v_st},
                    {'Imposto': 'IPI', 'Débito': df_sai['IPI'].sum(), 'Crédito': -df_ent['VLR_IPI'].sum(), 'Saldo': v_ipi}
                ]))

            # Exportação
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_ent.to_excel(writer, sheet_name='Entradas Analítico', index=False)
                df_sai.to_excel(writer, sheet_name='Saídas Analítico', index=False)
                df_apur = pd.DataFrame([{'ICMS': v_icms, 'ST': v_st, 'IPI': v_ipi}])
                df_apur.to_excel(writer, sheet_name='Resumo Saldos', index=False)
                
                workbook = writer.book
                fmt_red = workbook.add_format({'bg_color': '#FFC7CE'})
                for sheet in ['Entradas Analítico', 'Saídas Analítico']:
                    ws = writer.sheets[sheet]
                    ws.set_column('A:AN', 18)
                    df_ref = df_ent if 'Entradas' in sheet else df_sai
                    for i, val in enumerate(df_ref['DIAGNOSTICO']):
                        if val != "Escrituração Regular": ws.set_row(i + 1, None, fmt_red)

            st.download_button("📥 Baixar Auditoria do Curador", output.getvalue(), "Curador_Malha_Auditada.xlsx")

        except Exception as e:
            st.error(f"Erro Crítico: {e}")

if __name__ == "__main__":
    main()
