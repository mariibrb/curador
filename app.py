import streamlit as st
import pandas as pd
import io

# Configuração da página - O Curador
st.set_page_config(page_title="Curador - Auditoria Fiscal Robusta", layout="wide")

# --- FUNÇÃO DE RESET ---
def reset_auditoria():
    """Limpa os arquivos da memória para nova análise."""
    st.session_state['arquivo_entrada'] = None
    st.session_state['arquivo_saida'] = None
    st.session_state['id_auditoria'] += 1

if 'id_auditoria' not in st.session_state:
    st.session_state['id_auditoria'] = 0

# --- FUNÇÕES UTILITÁRIAS ---
def clean_numeric_col(df, col_name):
    """Garante que números brasileiros (1.000,00) sejam lidos corretamente."""
    if col_name in df.columns:
        s = df[col_name].astype(str).str.replace(r'\s+', '', regex=True)
        s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df[col_name] = pd.to_numeric(s, errors='coerce').fillna(0.0)
    return df

def clean_cfop_col(df, col_name='CFOP'):
    """Padroniza a coluna CFOP para garantir que todos apareçam no resumo."""
    if col_name in df.columns:
        df[col_name] = df[col_name].astype(str).str.replace('.', '', regex=False).str.strip()
        df[col_name] = df[col_name].replace(['nan', 'None', ''], 'SEM_CFOP')
    return df

def gerar_livro_p9(df, tipo='entrada'):
    """
    Gera o Livro Fiscal P9 COMPLETO.
    Lista TODOS os CFOPs, sem exceção (dropna=False).
    """
    dff = df.copy()
    
    if tipo == 'entrada':
        col_vc = 'VC'
        col_bc = 'BC-ICMS'
        col_icms = 'VLR-ICMS'
        col_st = 'ICMS-ST'
        col_ipi = 'VLR_IPI'
        col_cst = 'CST-ICMS'
    else:
        col_vc = 'VC_ITEM' 
        col_bc = 'BC_ICMS'
        col_icms = 'ICMS'
        col_st = 'ICMSST'
        col_ipi = 'IPI'
        col_cst = 'CST'

    def classificar_valores(row):
        cst = str(row[col_cst])[-2:]
        vc = row[col_vc]
        bc = row[col_bc]
        sobra = max(vc - bc, 0)
        isentas = 0.0
        outras = 0.0
        cst_isentas = ['30', '40', '41', '50', '60'] 
        if sobra > 0:
            if cst in cst_isentas:
                isentas = sobra
            else:
                outras = sobra 
        return pd.Series([isentas, outras])

    dff[['Isentas', 'Outras']] = dff.apply(classificar_valores, axis=1)

    resumo = dff.groupby('CFOP', dropna=False)[[col_vc, col_bc, col_icms, col_st, col_ipi, 'Isentas', 'Outras']].sum().reset_index()
    resumo.columns = ['CFOP', 'Valor Contábil', 'Base Cálculo', 'ICMS', 'ICMS ST', 'IPI', 'Isentas', 'Outras']
    resumo = resumo.sort_values('CFOP')
    return resumo

def auditoria_decisiva(row, tipo='saida'):
    """MOTOR DE AUDITORIA ROBUSTO"""
    cfop = str(row['CFOP'])
    cst_full = str(row['CST-ICMS'] if tipo == 'entrada' else row['CST']).strip()
    cst = cst_full[-2:] if len(cst_full) >= 2 else cst_full.zfill(2)
    
    vlr_prod = row['VPROD'] if tipo == 'entrada' else row['VITEM']
    vlr_icms = row['VLR-ICMS'] if tipo == 'entrada' else row['ICMS']
    bc_icms = row['BC-ICMS'] if tipo == 'entrada' else row['BC_ICMS']
    aliq_icms = 0 if tipo == 'entrada' else row['ALIQ_ICMS']
    vlr_st = row['ICMS-ST'] if tipo == 'entrada' else row['ICMSST']
    vlr_ipi = row['VLR_IPI'] if tipo == 'entrada' else row['IPI']
    
    frete = row['FRETE']
    desc = row['DESC']
    uf_dest = "" if tipo == 'entrada' else str(row['Ufp']).strip().upper()
    
    # Listas de Controle
    cst_st_mandatorio = ['10', '30', '70']
    cst_st_permitido = ['10', '30', '70', '90']
    cfop_st_gerador = ['5401', '5403', '6401', '6403', '5405', '6405']
    cfop_industrial = ['5101', '6101']
    cfop_uso_consumo = ['1556', '2556']
    
    diag, legal, prevent, dominio = [], [], [], []

    # --- ICMS PRÓPRIO ---
    if tipo == 'entrada' and cfop in cfop_uso_consumo and vlr_icms > 0:
        diag.append("ALERTA: Crédito em Uso/Consumo (1556/2556).")
        legal.append("VALIDAR: Permitido apenas se insumo produtivo ou ativo.")
        dominio.append("Se correto: Manter. Se indevido: Estornar e trocar CST.")

    if tipo == 'saida' and cfop == '6403' and vlr_icms == 0:
        diag.append("OMISSÃO GRAVE: 6403 s/ ICMS Próprio.")
        legal.append("Emitir Nota Complementar ICMS.")
        prevent.append("Configurar ERP para destacar ICMS Próprio.")
        dominio.append("Acumulador > Faturamento de Substituto.")

    if bc_icms > 0:
        base_esperada = vlr_prod + frete - desc
        if (base_esperada - bc_icms) > 1.0: 
            diag.append("Base Reduzida (Frete fora?).")
            legal.append("Emitir Nota Complementar ICMS (Diferença).")
            prevent.append("Marcar flag 'Frete compõe base ICMS'.")
            dominio.append("Acumulador > Frete compõe base.")

    if tipo == 'saida' and cfop.startswith('6'):
        reg_7 = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'RN', 'RO', 'RR', 'SE', 'TO']
        if uf_dest in reg_7 and aliq_icms not in [7.0, 4.0] and aliq_icms > 0:
            diag.append(f"Alíquota Errada ({aliq_icms}% p/ {uf_dest}).")
            legal.append("Nota Complementar ou Restituição.")
            prevent.append(f"Corrigir cadastro de alíquota p/ {uf_dest}.")
            dominio.append("Cadastro Produto > Exceção de Imposto por UF.")

    # --- ICMS ST ---
    if cst in cst_st_mandatorio and vlr_st == 0:
        diag.append("Falta ST (CST obriga).")
        legal.append("Emitir Nota Complementar ST.")
        prevent.append("Revisar MVA e cadastro.")
        dominio.append("Acumulador > Gera guia ST.")

    elif cst == '90' and vlr_st == 0 and cfop in cfop_st_gerador:
        diag.append("Falta ST (CST 90 em Op. ST).")
        legal.append("Emitir Nota Complementar ST.")
        prevent.append("Configurar regra de ST.")
        dominio.append("Acumulador > Verificar sub-tributária.")

    elif vlr_st > 0 and cst not in cst_st_permitido and cst != '60':
        diag.append("ST Indevida (CST errado).")
        legal.append("CC-e para ajustar CST.")
        prevent.append("Ajustar CST produto.")
        dominio.append("Alterar CST em lote.")

    # --- IPI ---
    if cfop in cfop_industrial and vlr_ipi == 0:
        diag.append("Falta IPI Industrial.")
        legal.append("Emitir Nota Complementar IPI.")
        prevent.append("Cadastrar alíquota IPI.")
        dominio.append("Acumulador > Imposto IPI.")

    if tipo == 'entrada' and cfop in ['1101', '2101'] and vlr_ipi == 0:
        diag.append("Crédito IPI não tomado.")
        legal.append("Verificar XML. Lançar manual.")
        prevent.append("-")
        dominio.append("Habilitar IPI no lançamento.")

    return pd.Series({
        'DIAGNÓSTICO': " | ".join(diag) if diag else "Regular",
        'AÇÃO_LEGAL': " | ".join(legal) if legal else "-",
        'AÇÃO_CLIENTE_ERP': " | ".join(prevent) if prevent else "-",
        'AÇÃO_DOMINIO': " | ".join(dominio) if dominio else "-"
    })

def reordenar_audit(df):
    cols = list(df.columns)
    prioridade = ['DIAGNÓSTICO', 'AÇÃO_LEGAL', 'AÇÃO_DOMINIO', 'AÇÃO_CLIENTE_ERP']
    for c in prioridade:
        if c in cols: cols.remove(c)
    idx = 1
    for c in reversed(prioridade):
        cols.insert(idx, c)
    return df[cols]

def main():
    col_title, col_btn = st.columns([4, 1])
    with col_title:
        st.title("⚖️ Curador: Auditoria Fiscal Robusta")
    with col_btn:
        st.button("🔄 Nova Auditoria (Limpar)", on_click=reset_auditoria, type="primary")
    
    st.markdown("---")
    
    chave_ent = f"entrada_{st.session_state['id_auditoria']}"
    chave_sai = f"saida_{st.session_state['id_auditoria']}"
    
    c1, c2 = st.columns(2)
    with c1: 
        ent_f = st.file_uploader("📥 Entradas (CSV)", type=["csv"], key=chave_ent)
    with c2: 
        sai_f = st.file_uploader("📤 Saídas (CSV)", type=["csv"], key=chave_sai)

    if ent_f and sai_f:
        try:
            cols_ent = ['NUM_NF', 'DATA_EMISSAO', 'CNPJ', 'UF', 'VLR_NF', 'AC', 'CFOP', 'COD_PROD', 'DESCR', 'NCM', 'UNID', 'VUNIT', 'QTDE', 'VPROD', 'DESC', 'FRETE', 'SEG', 'DESP', 'VC', 'CST-ICMS', 'BC-ICMS', 'VLR-ICMS', 'BC-ICMS-ST', 'ICMS-ST', 'VLR_IPI', 'CST_PIS', 'BC_PIS', 'VLR_PIS', 'CST_COF', 'BC_COF', 'VLR_COF']
            cols_sai = ['NF', 'DATA_EMISSAO', 'CNPJ', 'Ufp', 'VC', 'AC', 'CFOP', 'COD_ITEM', 'DESC_ITEM', 'NCM', 'UND', 'VUNIT', 'QTDE', 'VITEM', 'DESC', 'FRETE', 'SEG', 'OUTRAS', 'VC_ITEM', 'CST', 'BC_ICMS', 'ALIQ_ICMS', 'ICMS', 'BC_ICMSST', 'ICMSST', 'IPI', 'CST_PIS Escriturado', 'BC_PIS', 'PIS', 'CST_COF', 'BC_COF', 'COF']

            df_ent = pd.read_csv(ent_f, sep=';', encoding='latin-1', header=None, names=cols_ent)
            df_sai = pd.read_csv(sai_f, sep=';', encoding='latin-1', header=None, names=cols_sai)

            # Limpeza Numérica e CFOP
            cols_num_ent = ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'VC', 'ICMS-ST', 'VPROD', 'FRETE', 'DESC']
            cols_num_sai = ['ICMS', 'IPI', 'BC_ICMS', 'VC_ITEM', 'ALIQ_ICMS', 'ICMSST', 'VITEM', 'FRETE', 'DESC']
            for c in cols_num_ent: df_ent = clean_numeric_col(df_ent, c)
            for c in cols_num_sai: df_sai = clean_numeric_col(df_sai, c)
            
            df_ent = clean_cfop_col(df_ent, 'CFOP')
            df_sai = clean_cfop_col(df_sai, 'CFOP')

            # Auditoria
            df_ent[['DIAGNÓSTICO', 'AÇÃO_LEGAL', 'AÇÃO_CLIENTE_ERP', 'AÇÃO_DOMINIO']] = df_ent.apply(lambda r: auditoria_decisiva(r, 'entrada'), axis=1)
            df_sai[['DIAGNÓSTICO', 'AÇÃO_LEGAL', 'AÇÃO_CLIENTE_ERP', 'AÇÃO_DOMINIO']] = df_sai.apply(lambda r: auditoria_decisiva(r, 'saida'), axis=1)
            
            df_ent = reordenar_audit(df_ent)
            df_sai = reordenar_audit(df_sai)

            # Saldos
            v_icms = df_sai['ICMS'].sum() - df_ent['VLR-ICMS'].sum()
            v_st = df_sai['ICMSST'].sum() - df_ent['ICMS-ST'].sum()
            v_ipi = df_sai['IPI'].sum() - df_ent['VLR_IPI'].sum()

            livro_ent = gerar_livro_p9(df_ent, 'entrada')
            livro_sai = gerar_livro_p9(df_sai, 'saida')

            st.success("Auditoria Concluída com Sucesso!")

            # 1. Apuração
            st.subheader("💰 Apuração Final (Confronto de Impostos)")
            resumo = pd.DataFrame([
                {'Imposto': 'ICMS PRÓPRIO', 'Débitos': df_sai['ICMS'].sum(), 'Créditos': df_ent['VLR-ICMS'].sum(), 'Saldo': v_icms, 'Status': 'A RECOLHER' if v_icms > 0 else 'CREDOR'},
                {'Imposto': 'ICMS ST', 'Débitos': df_sai['ICMSST'].sum(), 'Créditos': df_ent['ICMS-ST'].sum(), 'Saldo': v_st, 'Status': 'A RECOLHER' if v_st > 0 else 'CREDOR'},
                {'Imposto': 'IPI', 'Débitos': df_sai['IPI'].sum(), 'Créditos': df_ent['VLR_IPI'].sum(), 'Saldo': v_ipi, 'Status': 'A RECOLHER' if v_ipi > 0 else 'CREDOR'}
            ])
            st.dataframe(resumo.style.format({'Débitos': 'R$ {:,.2f}', 'Créditos': 'R$ {:,.2f}', 'Saldo': 'R$ {:,.2f}'}), use_container_width=True)

            # 2. Livro Fiscal
            st.markdown("---")
            st.subheader("📖 Livro Fiscal (Resumo por CFOP)")
            tabs_livro = st.tabs(["Livro de Entradas (P9)", "Livro de Saídas (P9)"])
            fmt_livro = {'Valor Contábil': 'R$ {:,.2f}', 'Base Cálculo': 'R$ {:,.2f}', 'ICMS': 'R$ {:,.2f}', 'ICMS ST': 'R$ {:,.2f}', 'IPI': 'R$ {:,.2f}', 'Isentas': 'R$ {:,.2f}', 'Outras': 'R$ {:,.2f}'}
            with tabs_livro[0]: st.dataframe(livro_ent.style.format(fmt_livro), use_container_width=True)
            with tabs_livro[1]: st.dataframe(livro_sai.style.format(fmt_livro), use_container_width=True)

            # 3. Auditoria Detalhada (AQUI ESTÃO SUAS COLUNAS!)
            st.markdown("---")
            st.subheader("🚨 Inconsistências (Ação Necessária)")
            c1, c2 = st.columns(2)
            
            erros_sai = df_sai[df_sai['DIAGNÓSTICO'] != "Regular"]
            erros_ent = df_ent[df_ent['DIAGNÓSTICO'] != "Regular"]

            with c1:
                st.markdown("**Saídas com Erro**")
                if erros_sai.empty: st.info("Regular.")
                else: 
                    # Mostrando TODAS as colunas de ação que você pediu
                    st.dataframe(erros_sai[['NF', 'CFOP', 'DIAGNÓSTICO', 'AÇÃO_LEGAL', 'AÇÃO_CLIENTE_ERP', 'AÇÃO_DOMINIO']], use_container_width=True)
            
            with c2:
                st.markdown("**Entradas com Erro**")
                if erros_ent.empty: st.info("Regular.")
                else: 
                    # Mostrando TODAS as colunas de ação que você pediu
                    st.dataframe(erros_ent[['NUM_NF', 'CFOP', 'DIAGNÓSTICO', 'AÇÃO_DOMINIO', 'AÇÃO_LEGAL']], use_container_width=True)

            # Exportação
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_ent.to_excel(writer, sheet_name='Entradas Auditadas', index=False)
                df_sai.to_excel(writer, sheet_name='Saídas Auditadas', index=False)
                resumo.to_excel(writer, sheet_name='Apuração Final', index=False)
                livro_ent.to_excel(writer, sheet_name='Livro Entradas P9', index=False)
                livro_sai.to_excel(writer, sheet_name='Livro Saídas P9', index=False)
                
                workbook = writer.book
                fmt_red = workbook.add_format({'bg_color': '#FFC7CE'})
                for sheet, df_ref in [('Entradas Auditadas', df_ent), ('Saídas Auditadas', df_sai)]:
                    ws = writer.sheets[sheet]
                    ws.set_column('A:Z', 22)
                    for i, val in enumerate(df_ref['DIAGNÓSTICO']):
                        if val != "Regular": ws.set_row(i + 1, None, fmt_red)

            st.download_button("📥 Baixar Livros e Auditoria (Curador)", output.getvalue(), "Curador_Livros_Auditoria.xlsx")

        except Exception as e:
            st.error(f"Erro Crítico: {e}")

if __name__ == "__main__":
    main()
