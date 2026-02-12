import streamlit as st
import pandas as pd
import io
import xml.etree.ElementTree as ET
import zipfile

# Configuração da página - O Curador
st.set_page_config(page_title="Curador - Auditoria Fiscal Robusta", layout="wide")

# --- GERENCIAMENTO DE SESSÃO ---
if 'id_auditoria' not in st.session_state:
    st.session_state['id_auditoria'] = 0

def reset_auditoria():
    """Limpa a memória e reseta os componentes."""
    st.session_state['arquivo_entrada'] = None
    st.session_state['arquivo_saida'] = None
    st.session_state['arquivos_xml'] = None 
    st.session_state['arquivo_status'] = None 
    st.session_state['id_auditoria'] += 1

# --- UTILITÁRIOS ---
def clean_numeric_col(df, col_name):
    if col_name in df.columns:
        s = df[col_name].astype(str).str.replace(r'\s+', '', regex=True)
        s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df[col_name] = pd.to_numeric(s, errors='coerce').fillna(0.0)
    return df

def clean_cfop_col(df, col_name='CFOP'):
    if col_name in df.columns:
        df[col_name] = df[col_name].astype(str).str.replace('.', '', regex=False).str.strip()
        df[col_name] = df[col_name].replace(['nan', 'None', ''], 'SEM_CFOP')
    return df

def carregar_status_cte(status_file):
    """
    Lê o relatório de status (Coluna A=Chave, Coluna E=Status).
    Retorna uma LISTA de chaves que NÃO são válidas (Canceladas/Denegadas).
    """
    try:
        if status_file.name.endswith('.csv'):
            df = pd.read_csv(status_file, header=None, dtype=str)
        else:
            df = pd.read_excel(status_file, header=None, dtype=str)
        
        # Seleciona Coluna A (0) e Coluna E (4)
        if df.shape[1] > 4:
            df_status = df.iloc[:, [0, 4]].copy()
            df_status.columns = ['Chave', 'Status']
            
            # Limpeza da Chave
            df_status['Chave'] = df_status['Chave'].astype(str).str.replace('CTe', '', regex=False).str.strip()
            
            # Filtra os ruins
            mask_cancel = df_status['Status'].astype(str).str.upper().str.contains('CANCEL|DENEG|INUTIL', na=False)
            return df_status.loc[mask_cancel, 'Chave'].tolist()
        return []
        
    except Exception:
        return []

# --- MÓDULO MATRIOSKA (XML RECURSIVO + ANTI-DUPLICIDADE) ---
def processar_arquivo_recursivo(arquivo_bytes, nome_arquivo, lista_dados, contadores, chaves_unicas):
    if zipfile.is_zipfile(io.BytesIO(arquivo_bytes)):
        try:
            with zipfile.ZipFile(io.BytesIO(arquivo_bytes)) as z:
                for nome_interno in z.namelist():
                    if nome_interno.endswith('/') or '__MACOSX' in nome_interno: continue
                    conteudo_interno = z.read(nome_interno)
                    # Passa o conjunto de chaves únicas adiante
                    processar_arquivo_recursivo(conteudo_interno, nome_interno, lista_dados, contadores, chaves_unicas)
        except Exception: pass 
    else:
        try:
            tree = ET.parse(io.BytesIO(arquivo_bytes))
            root = tree.getroot()
            ns_cte = {'cte': 'http://www.portalfiscal.inf.br/cte'}
            
            inf_cte = root.find('.//cte:infCte', ns_cte)
            if inf_cte is None:
                contadores['ignorados'] += 1
                return 
            
            chave = inf_cte.attrib.get('Id', '')[3:]
            
            # --- CHECAGEM DE DUPLICIDADE ---
            if chave in chaves_unicas:
                contadores['duplicados'] += 1
                return # Já li essa nota antes, sai fora!
            
            # Se é nova, adiciona ao conjunto
            chaves_unicas.add(chave)
            contadores['ctes'] += 1
            
            cfop_tag = inf_cte.find('.//cte:ide/cte:CFOP', ns_cte)
            cfop = cfop_tag.text if cfop_tag is not None else "SEM_CFOP"
            
            emit_tag = inf_cte.find('.//cte:emit/cte:xNome', ns_cte)
            emit = emit_tag.text if emit_tag is not None else "Desconhecido"
            
            v_prest_tag = inf_cte.find('.//cte:vPrest/cte:vTPrest', ns_cte)
            v_prest = float(v_prest_tag.text) if v_prest_tag is not None else 0.0
            
            icms_val = 0.0
            bc_val = 0.0
            imp = inf_cte.find('.//cte:imp/cte:ICMS', ns_cte)
            
            if imp is not None:
                for child in imp:
                    v_icms_tag = child.find('cte:vICMS', ns_cte)
                    v_bc_tag = child.find('cte:vBC', ns_cte)
                    if v_icms_tag is not None: icms_val = float(v_icms_tag.text)
                    if v_bc_tag is not None: bc_val = float(v_bc_tag.text)
                    if icms_val > 0: break
            
            lista_dados.append({
                'Arquivo': nome_arquivo,
                'Chave': chave,
                'CFOP': cfop,
                'Transportadora': emit,
                'Valor Contábil': v_prest,
                'Base Cálculo': bc_val,
                'Crédito ICMS': icms_val
            })
        except: pass

def processar_pacote_xml(uploaded_files, chaves_canceladas):
    dados_cte = []
    # Adicionado contador de duplicados e conjunto de chaves únicas
    contadores = {'ctes': 0, 'ignorados': 0, 'duplicados': 0}
    chaves_unicas = set()
    
    for file in uploaded_files:
        processar_arquivo_recursivo(file.read(), file.name, dados_cte, contadores, chaves_unicas)
            
    if not dados_cte:
        return pd.DataFrame(), pd.DataFrame(), 0.0, contadores, 0
        
    df_cte = pd.DataFrame(dados_cte)
    df_cte = clean_cfop_col(df_cte, 'CFOP')
    
    # Filtro de Cancelados
    ctes_cancelados = df_cte[df_cte['Chave'].isin(chaves_canceladas)]
    qtd_cancelados = len(ctes_cancelados)
    
    # Mantém válidos
    df_cte_validos = df_cte[~df_cte['Chave'].isin(chaves_canceladas)]
    
    # Resumo por CFOP (Apenas Válidos)
    df_resumo_cfop = df_cte_validos.groupby('CFOP')[['Valor Contábil', 'Base Cálculo', 'Crédito ICMS']].sum().reset_index()
    df_resumo_cfop = df_resumo_cfop.sort_values('CFOP')
    
    total_icms = df_cte_validos['Crédito ICMS'].sum()
    
    return df_cte_validos, df_resumo_cfop, total_icms, contadores, qtd_cancelados

# --- MÓDULO CSV ---
def gerar_livro_p9(df, tipo='entrada'):
    dff = df.copy()
    if tipo == 'entrada':
        col_vc, col_bc, col_icms, col_st, col_ipi, col_cst = 'VC', 'BC-ICMS', 'VLR-ICMS', 'ICMS-ST', 'VLR_IPI', 'CST-ICMS'
    else:
        col_vc, col_bc, col_icms, col_st, col_ipi, col_cst = 'VC_ITEM', 'BC_ICMS', 'ICMS', 'ICMSST', 'IPI', 'CST'

    def classificar_valores(row):
        cst = str(row[col_cst])[-2:]
        vc = row[col_vc]
        bc = row[col_bc]
        sobra = max(vc - bc, 0)
        isentas, outras = 0.0, 0.0
        cst_isentas = ['30', '40', '41', '50', '60'] 
        if sobra > 0:
            if cst in cst_isentas: isentas = sobra
            else: outras = sobra 
        return pd.Series([isentas, outras])

    dff[['Isentas', 'Outras']] = dff.apply(classificar_valores, axis=1)
    resumo = dff.groupby('CFOP', dropna=False)[[col_vc, col_bc, col_icms, col_st, col_ipi, 'Isentas', 'Outras']].sum().reset_index()
    resumo.columns = ['CFOP', 'Valor Contábil', 'Base Cálculo', 'ICMS', 'ICMS ST', 'IPI', 'Isentas', 'Outras']
    return resumo.sort_values('CFOP')

def auditoria_decisiva(row, tipo='saida'):
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
    
    cst_st_mandatorio = ['10', '30', '70']
    cst_st_permitido = ['10', '30', '70', '90']
    cfop_st_gerador = ['5401', '5403', '6401', '6403', '5405', '6405']
    cfop_industrial = ['5101', '6101']
    cfop_uso_consumo = ['1556', '2556']
    
    diag, legal, prevent, dominio = [], [], [], []

    if tipo == 'entrada' and cfop in cfop_uso_consumo and vlr_icms > 0:
        diag.append("ALERTA: Crédito em Uso/Consumo.")
        legal.append("VALIDAR se é insumo.")
        dominio.append("Se erro: Estornar.")
    if tipo == 'saida' and cfop == '6403' and vlr_icms == 0:
        diag.append("OMISSÃO GRAVE: 6403 s/ ICMS.")
        legal.append("Emitir Complementar.")
        prevent.append("Configurar ERP.")
        dominio.append("Acumulador > Faturamento Substituto.")
    if bc_icms > 0:
        base_esperada = vlr_prod + frete - desc
        if (base_esperada - bc_icms) > 1.0: 
            diag.append("Base Reduzida.")
            legal.append("Complementar ICMS.")
            prevent.append("Marcar 'Frete compõe base'.")
            dominio.append("Acumulador > Frete compõe base.")
    if tipo == 'saida' and cfop.startswith('6'):
        reg_7 = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'RN', 'RO', 'RR', 'SE', 'TO']
        if uf_dest in reg_7 and aliq_icms not in [7.0, 4.0] and aliq_icms > 0:
            diag.append(f"Alíquota Errada ({aliq_icms}%).")
            legal.append("Complementar/Restituir.")
            dominio.append("Produto > Exceção UF.")
    if cst in cst_st_mandatorio and vlr_st == 0:
        diag.append("Falta ST.")
        legal.append("Complementar ST.")
        dominio.append("Acumulador > Gera guia ST.")
    elif cst == '90' and vlr_st == 0 and cfop in cfop_st_gerador:
        diag.append("Falta ST (CST 90).")
        legal.append("Complementar ST.")
        dominio.append("Acumulador > Sub-tributária.")
    elif vlr_st > 0 and cst not in cst_st_permitido and cst != '60':
        diag.append("ST Indevida.")
        legal.append("CC-e/Refaturar.")
        prevent.append("Ajustar CST.")
    if cfop in cfop_industrial and vlr_ipi == 0:
        diag.append("Falta IPI.")
        legal.append("Complementar IPI.")
        dominio.append("Acumulador > IPI.")
    if tipo == 'entrada' and cfop in ['1101', '2101'] and vlr_ipi == 0:
        diag.append("Crédito IPI não tomado.")
        legal.append("Lançar manual.")
        dominio.append("Habilitar IPI.")

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

# --- MAIN ---
def main():
    col_title, col_btn = st.columns([4, 1])
    with col_title:
        st.title("⚖️ Curador: Auditoria Fiscal Robusta")
    with col_btn:
        st.button("🔄 Nova Auditoria", on_click=reset_auditoria, type="primary")
    
    st.markdown("---")
    
    # Chaves dinâmicas
    k_ent = f"in_{st.session_state['id_auditoria']}"
    k_sai = f"out_{st.session_state['id_auditoria']}"
    k_xml = f"xml_{st.session_state['id_auditoria']}"
    k_stat = f"stat_{st.session_state['id_auditoria']}"
    
    c1, c2 = st.columns(2)
    with c1: ent_f = st.file_uploader("📥 Entradas (CSV)", type=["csv"], key=k_ent)
    with c2: sai_f = st.file_uploader("📤 Saídas (CSV)", type=["csv"], key=k_sai)
    
    c3, c4 = st.columns(2)
    with c3: xml_f = st.file_uploader("🚚 XMLs Frete (Zip/XML)", type=["xml", "zip"], accept_multiple_files=True, key=k_xml)
    with c4: status_f = st.file_uploader("📜 Relatório Status CT-e (Excel/CSV)", type=["xlsx", "xls", "csv"], key=k_stat)

    if ent_f and sai_f:
        try:
            # 1. Leitura
            cols_ent = ['NUM_NF', 'DATA_EMISSAO', 'CNPJ', 'UF', 'VLR_NF', 'AC', 'CFOP', 'COD_PROD', 'DESCR', 'NCM', 'UNID', 'VUNIT', 'QTDE', 'VPROD', 'DESC', 'FRETE', 'SEG', 'DESP', 'VC', 'CST-ICMS', 'BC-ICMS', 'VLR-ICMS', 'BC-ICMS-ST', 'ICMS-ST', 'VLR_IPI', 'CST_PIS', 'BC_PIS', 'VLR_PIS', 'CST_COF', 'BC_COF', 'VLR_COF']
            cols_sai = ['NF', 'DATA_EMISSAO', 'CNPJ', 'Ufp', 'VC', 'AC', 'CFOP', 'COD_ITEM', 'DESC_ITEM', 'NCM', 'UND', 'VUNIT', 'QTDE', 'VITEM', 'DESC', 'FRETE', 'SEG', 'OUTRAS', 'VC_ITEM', 'CST', 'BC_ICMS', 'ALIQ_ICMS', 'ICMS', 'BC_ICMSST', 'ICMSST', 'IPI', 'CST_PIS Escriturado', 'BC_PIS', 'PIS', 'CST_COF', 'BC_COF', 'COF']

            df_ent = pd.read_csv(ent_f, sep=';', encoding='latin-1', header=None, names=cols_ent)
            df_sai = pd.read_csv(sai_f, sep=';', encoding='latin-1', header=None, names=cols_sai)

            cols_clean_ent = ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'VC', 'ICMS-ST', 'VPROD', 'FRETE', 'DESC']
            cols_clean_sai = ['ICMS', 'IPI', 'BC_ICMS', 'VC_ITEM', 'ALIQ_ICMS', 'ICMSST', 'VITEM', 'FRETE', 'DESC']
            for c in cols_clean_ent: df_ent = clean_numeric_col(df_ent, c)
            for c in cols_clean_sai: df_sai = clean_numeric_col(df_sai, c)
            
            df_ent = clean_cfop_col(df_ent, 'CFOP')
            df_sai = clean_cfop_col(df_sai, 'CFOP')

            # 2. Auditoria e Apuração 1
            df_ent[['DIAGNÓSTICO', 'AÇÃO_LEGAL', 'AÇÃO_CLIENTE_ERP', 'AÇÃO_DOMINIO']] = df_ent.apply(lambda r: auditoria_decisiva(r, 'entrada'), axis=1)
            df_sai[['DIAGNÓSTICO', 'AÇÃO_LEGAL', 'AÇÃO_CLIENTE_ERP', 'AÇÃO_DOMINIO']] = df_sai.apply(lambda r: auditoria_decisiva(r, 'saida'), axis=1)
            
            df_ent = reordenar_audit(df_ent)
            df_sai = reordenar_audit(df_sai)

            v_icms1 = df_sai['ICMS'].sum() - df_ent['VLR-ICMS'].sum()
            v_st = df_sai['ICMSST'].sum() - df_ent['ICMS-ST'].sum()
            v_ipi = df_sai['IPI'].sum() - df_ent['VLR_IPI'].sum()

            # 3. Processamento XML (Filtro Cancelados + Resumo CFOP)
            credito_cte = 0.0
            nfe_ign = 0
            n_dup = 0
            qtd_cancel = 0
            df_cte_detalhe = pd.DataFrame()
            df_cte_cfop = pd.DataFrame()
            
            if xml_f:
                chaves_ruins = []
                if status_f:
                    chaves_ruins = carregar_status_cte(status_f)
                    
                df_cte_detalhe, df_cte_cfop, credito_cte, contadores, qtd_cancel = processar_pacote_xml(xml_f, chaves_ruins)
                nfe_ign = contadores['ignorados']
                n_dup = contadores.get('duplicados', 0)

            # 4. Livros P9
            livro_ent = gerar_livro_p9(df_ent, 'entrada')
            livro_sai = gerar_livro_p9(df_sai, 'saida')

            st.success("Auditoria Concluída!")

            # --- VISUALIZAÇÃO ---
            
            # Painel 1: Apuração CSV
            st.subheader("💰 Apuração 1: Baseada nos Arquivos CSV (Domínio)")
            resumo_1 = pd.DataFrame([
                {'Imposto': 'ICMS PRÓPRIO', 'Débitos': df_sai['ICMS'].sum(), 'Créditos': df_ent['VLR-ICMS'].sum(), 'Saldo': v_icms1, 'Situação': 'A RECOLHER' if v_icms1 > 0 else 'CREDOR'},
                {'Imposto': 'ICMS ST', 'Débitos': df_sai['ICMSST'].sum(), 'Créditos': df_ent['ICMS-ST'].sum(), 'Saldo': v_st, 'Situação': 'A RECOLHER' if v_st > 0 else 'CREDOR'},
                {'Imposto': 'IPI', 'Débitos': df_sai['IPI'].sum(), 'Créditos': df_ent['VLR_IPI'].sum(), 'Saldo': v_ipi, 'Situação': 'A RECOLHER' if v_ipi > 0 else 'CREDOR'}
            ])
            st.dataframe(resumo_1.style.format({'Débitos': 'R$ {:,.2f}', 'Créditos': 'R$ {:,.2f}', 'Saldo': 'R$ {:,.2f}'}), use_container_width=True)

            # Painel 2: Apuração 2 (Com Frete/CFOP)
            if xml_f:
                st.markdown("---")
                st.subheader("🚚 Apuração 2: Considerando XML de Transporte")
                
                # Avisos de Filtro
                cols_warn = st.columns(3)
                if nfe_ign > 0: cols_warn[0].warning(f"⚠️ {nfe_ign} arquivos ignorados (não eram CT-e).")
                if qtd_cancel > 0: cols_warn[1].error(f"🚫 {qtd_cancel} CT-es CANCELADOS/DENEGADOS foram excluídos.")
                if n_dup > 0: cols_warn[2].info(f"ℹ️ {n_dup} duplicatas removidas.")
                
                v_icms2 = v_icms1 - credito_cte
                status_final = 'A RECOLHER' if v_icms2 > 0 else 'CREDOR'
                
                # Resumo Matemático e Por CFOP lado a lado
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.markdown("**Novo Saldo a Pagar**")
                    resumo_2 = pd.DataFrame([
                        {'Descrição': 'Saldo Apuração 1', 'Valor': v_icms1},
                        {'Descrição': '(-) Crédito Frete (Válidos)', 'Valor': -credito_cte},
                        {'Descrição': f'(=) SALDO FINAL ({status_final})', 'Valor': v_icms2}
                    ])
                    st.table(resumo_2.style.format({'Valor': 'R$ {:,.2f}'}))
                
                with c2:
                    st.markdown("**Resumo dos Fretes por CFOP**")
                    if not df_cte_cfop.empty:
                        st.dataframe(df_cte_cfop.style.format({'Valor Contábil': 'R$ {:,.2f}', 'Base Cálculo': 'R$ {:,.2f}', 'Crédito ICMS': 'R$ {:,.2f}'}), use_container_width=True)
                    else:
                        st.info("Nenhum CT-e válido encontrado.")

                with st.expander("Ver lista individual dos CT-e importados"):
                    st.dataframe(df_cte_detalhe)

            # Painel 3: Livros P9
            st.markdown("---")
            st.subheader("📖 Livro Fiscal (Resumo por CFOP - CSV)")
            t1, t2 = st.tabs(["Entradas P9", "Saídas P9"])
            fmt = {'Valor Contábil': 'R$ {:,.2f}', 'Base Cálculo': 'R$ {:,.2f}', 'ICMS': 'R$ {:,.2f}', 'ICMS ST': 'R$ {:,.2f}', 'IPI': 'R$ {:,.2f}', 'Isentas': 'R$ {:,.2f}', 'Outras': 'R$ {:,.2f}'}
            with t1: st.dataframe(livro_ent.style.format(fmt), use_container_width=True)
            with t2: st.dataframe(livro_sai.style.format(fmt), use_container_width=True)

            # Painel 4: Erros
            st.markdown("---")
            st.subheader("🚨 Inconsistências (Ação Necessária)")
            c1, c2 = st.columns(2)
            erros_sai = df_sai[df_sai['DIAGNÓSTICO'] != "Regular"]
            erros_ent = df_ent[df_ent['DIAGNÓSTICO'] != "Regular"]

            with c1:
                st.markdown("**Saídas**")
                if erros_sai.empty: st.info("Ok")
                else: st.dataframe(erros_sai[['NF', 'CFOP', 'DIAGNÓSTICO', 'AÇÃO_LEGAL', 'AÇÃO_CLIENTE_ERP', 'AÇÃO_DOMINIO']], use_container_width=True)
            with c2:
                st.markdown("**Entradas**")
                if erros_ent.empty: st.info("Ok")
                else: st.dataframe(erros_ent[['NUM_NF', 'CFOP', 'DIAGNÓSTICO', 'AÇÃO_DOMINIO', 'AÇÃO_LEGAL']], use_container_width=True)

            # Exportação
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_ent.to_excel(writer, sheet_name='Entradas Auditadas', index=False)
                df_sai.to_excel(writer, sheet_name='Saídas Auditadas', index=False)
                resumo_1.to_excel(writer, sheet_name='Apuração 1 (CSV)', index=False)
                if xml_f: 
                    df_cte_cfop.to_excel(writer, sheet_name='Resumo Frete CFOP', index=False)
                    df_cte_detalhe.to_excel(writer, sheet_name='Detalhe XMLs', index=False)
                livro_ent.to_excel(writer, sheet_name='Livro Entradas P9', index=False)
                livro_sai.to_excel(writer, sheet_name='Livro Saídas P9', index=False)
                
                wb = writer.book
                fmt_red = wb.add_format({'bg_color': '#FFC7CE'})
                for sheet in ['Entradas Auditadas', 'Saídas Auditadas']:
                    ws = writer.sheets[sheet]
                    ws.set_column('A:Z', 22)
                    for i, val in enumerate(df_ref['DIAGNÓSTICO']):
                        if val != "Regular": ws.set_row(i + 1, None, fmt_red)
            
            st.download_button("📥 Baixar Relatório Completo", output.getvalue(), "Curador_Completo.xlsx")

        except Exception as e:
            st.error(f"Erro Crítico: {e}")

if __name__ == "__main__":
    main()
