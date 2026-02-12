import streamlit as st
import pandas as pd
import io
import xml.etree.ElementTree as ET
import zipfile

# Configuração da página - O Curador
st.set_page_config(page_title="Curador - Auditoria Fiscal & Fretes (Matrioska)", layout="wide")

# --- FUNÇÃO DE RESET ---
def reset_auditoria():
    """Limpa os arquivos da memória para nova análise."""
    st.session_state['arquivo_entrada'] = None
    st.session_state['arquivo_saida'] = None
    st.session_state['arquivos_xml'] = None 
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

# --- MÓDULO DE PROCESSAMENTO XML RECURSIVO (MATRIOSKA) ---
def processar_arquivo_recursivo(arquivo_bytes, nome_arquivo, lista_dados, contadores):
    """
    Função RECURSIVA que mergulha em ZIPs dentro de ZIPs.
    Se for ZIP: Abre e chama a si mesma para cada arquivo dentro.
    Se for XML: Processa e extrai dados se for CT-e.
    """
    # Verifica se é um arquivo ZIP válido
    if zipfile.is_zipfile(io.BytesIO(arquivo_bytes)):
        try:
            with zipfile.ZipFile(io.BytesIO(arquivo_bytes)) as z:
                for nome_interno in z.namelist():
                    # Ignora pastas ou arquivos mac/sistema
                    if nome_interno.endswith('/') or '__MACOSX' in nome_interno:
                        continue
                    
                    conteudo_interno = z.read(nome_interno)
                    # RECURSÃO: Chama a função novamente para o arquivo de dentro
                    processar_arquivo_recursivo(conteudo_interno, nome_interno, lista_dados, contadores)
        except Exception as e:
            print(f"Erro ao abrir ZIP {nome_arquivo}: {e}")
            return

    # Se não for ZIP, tenta processar como XML
    else:
        try:
            # Tenta ler como XML
            tree = ET.parse(io.BytesIO(arquivo_bytes))
            root = tree.getroot()
            
            # Namespaces
            ns_cte = {'cte': 'http://www.portalfiscal.inf.br/cte'}
            
            # FILTRO: É CT-e?
            inf_cte = root.find('.//cte:infCte', ns_cte)
            
            if inf_cte is None:
                # Não é CT-e (provavelmente NFe/DANFE). Ignora.
                contadores['ignorados'] += 1
                return
            
            # Se chegou aqui, É UM CT-E VÁLIDO. Extrai dados.
            contadores['ctes'] += 1
            chave = inf_cte.attrib.get('Id', '')[3:]
            
            emit_tag = inf_cte.find('.//cte:emit/cte:xNome', ns_cte)
            emit = emit_tag.text if emit_tag is not None else "Desconhecido"
            
            v_prest_tag = inf_cte.find('.//cte:vPrest/cte:vTPrest', ns_cte)
            v_prest = float(v_prest_tag.text) if v_prest_tag is not None else 0.0
            
            icms_val = 0.0
            imp = inf_cte.find('.//cte:imp/cte:ICMS', ns_cte)
            
            if imp is not None:
                for child in imp:
                    v_icms_tag = child.find('cte:vICMS', ns_cte)
                    if v_icms_tag is not None:
                        icms_val = float(v_icms_tag.text)
                        break
            
            lista_dados.append({
                'Origem': nome_arquivo, # Nome do arquivo (ou do arquivo dentro do zip)
                'Chave': chave,
                'Transportadora': emit,
                'Valor Frete': v_prest,
                'Crédito ICMS': icms_val
            })
            
        except ET.ParseError:
            # Não é XML (pode ser PDF, TXT dentro do zip). Ignora.
            pass
        except Exception as e:
            # Outros erros
            pass

def processar_pacote_xml(uploaded_files):
    """
    Ponto de entrada para processamento dos uploads.
    """
    dados_cte = []
    contadores = {'ctes': 0, 'ignorados': 0}
    
    for file in uploaded_files:
        # Lê o conteúdo bruto do upload
        bytes_arquivo = file.read()
        # Inicia a recursão
        processar_arquivo_recursivo(bytes_arquivo, file.name, dados_cte, contadores)
            
    if not dados_cte:
        return pd.DataFrame(), 0.0, contadores['ignorados']
        
    df_cte = pd.DataFrame(dados_cte)
    total_icms = df_cte['Crédito ICMS'].sum()
    
    return df_cte, total_icms, contadores['ignorados']

def gerar_livro_p9(df, tipo='entrada'):
    """Gera o Livro Fiscal P9 COMPLETO."""
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
    return resumo.sort_values('CFOP')

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
    
    cst_st_mandatorio = ['10', '30', '70']
    cst_st_permitido = ['10', '30', '70', '90']
    cfop_st_gerador = ['5401', '5403', '6401', '6403', '5405', '6405']
    cfop_industrial = ['5101', '6101']
    cfop_uso_consumo = ['1556', '2556']
    
    diag, legal, prevent, dominio = [], [], [], []

    # --- ICMS PRÓPRIO ---
    if tipo == 'entrada' and cfop in cfop_uso_consumo and vlr_icms > 0:
        diag.append("ALERTA: Crédito em Uso/Consumo.")
        legal.append("VALIDAR: Apenas insumo produtivo.")
        dominio.append("Se indevido: Estornar.")

    if tipo == 'saida' and cfop == '6403' and vlr_icms == 0:
        diag.append("OMISSÃO GRAVE: 6403 s/ ICMS Próprio.")
        legal.append("Emitir Nota Complementar ICMS.")
        prevent.append("Configurar ERP: ICMS Próprio.")
        dominio.append("Acumulador > Faturamento Substituto.")

    if bc_icms > 0:
        base_esperada = vlr_prod + frete - desc
        if (base_esperada - bc_icms) > 1.0: 
            diag.append("Base Reduzida (Frete fora?).")
            legal.append("Emitir Nota Complementar ICMS.")
            prevent.append("Marcar 'Frete compõe base'.")
            dominio.append("Acumulador > Frete compõe base.")

    if tipo == 'saida' and cfop.startswith('6'):
        reg_7 = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'RN', 'RO', 'RR', 'SE', 'TO']
        if uf_dest in reg_7 and aliq_icms not in [7.0, 4.0] and aliq_icms > 0:
            diag.append(f"Alíquota Errada ({aliq_icms}% p/ {uf_dest}).")
            legal.append("Nota Complementar/Restituição.")
            dominio.append("Produto > Exceção por UF.")

    # --- ICMS ST ---
    if cst in cst_st_mandatorio and vlr_st == 0:
        diag.append("Falta ST (CST obriga).")
        legal.append("Emitir Nota Complementar ST.")
        dominio.append("Acumulador > Gera guia ST.")

    elif cst == '90' and vlr_st == 0 and cfop in cfop_st_gerador:
        diag.append("Falta ST (CST 90 em ST).")
        legal.append("Emitir Nota Complementar ST.")
        dominio.append("Acumulador > Sub-tributária.")

    elif vlr_st > 0 and cst not in cst_st_permitido and cst != '60':
        diag.append("ST Indevida (CST errado).")
        legal.append("CC-e ajustar CST.")
        prevent.append("Ajustar CST produto.")

    # --- IPI ---
    if cfop in cfop_industrial and vlr_ipi == 0:
        diag.append("Falta IPI Industrial.")
        legal.append("Emitir Nota Complementar IPI.")
        dominio.append("Acumulador > Imposto IPI.")

    if tipo == 'entrada' and cfop in ['1101', '2101'] and vlr_ipi == 0:
        diag.append("Crédito IPI não tomado.")
        legal.append("Verificar XML. Lançar.")
        dominio.append("Habilitar IPI lançamento.")

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
        st.button("🔄 Nova Auditoria", on_click=reset_auditoria, type="primary")
    
    st.markdown("---")
    
    chave_ent = f"entrada_{st.session_state['id_auditoria']}"
    chave_sai = f"saida_{st.session_state['id_auditoria']}"
    chave_xml = f"xml_{st.session_state['id_auditoria']}"
    
    c1, c2, c3 = st.columns(3)
    with c1: ent_f = st.file_uploader("📥 Entradas (CSV)", type=["csv"], key=chave_ent)
    with c2: sai_f = st.file_uploader("📤 Saídas (CSV)", type=["csv"], key=chave_sai)
    # Uploader que aceita XML e ZIP (Matrioska)
    with c3: xml_f = st.file_uploader("🚚 XMLs Frete (XML ou ZIP)", type=["xml", "zip"], accept_multiple_files=True, key=chave_xml)

    if ent_f and sai_f:
        try:
            # 1. Leitura e Limpeza
            cols_ent = ['NUM_NF', 'DATA_EMISSAO', 'CNPJ', 'UF', 'VLR_NF', 'AC', 'CFOP', 'COD_PROD', 'DESCR', 'NCM', 'UNID', 'VUNIT', 'QTDE', 'VPROD', 'DESC', 'FRETE', 'SEG', 'DESP', 'VC', 'CST-ICMS', 'BC-ICMS', 'VLR-ICMS', 'BC-ICMS-ST', 'ICMS-ST', 'VLR_IPI', 'CST_PIS', 'BC_PIS', 'VLR_PIS', 'CST_COF', 'BC_COF', 'VLR_COF']
            cols_sai = ['NF', 'DATA_EMISSAO', 'CNPJ', 'Ufp', 'VC', 'AC', 'CFOP', 'COD_ITEM', 'DESC_ITEM', 'NCM', 'UND', 'VUNIT', 'QTDE', 'VITEM', 'DESC', 'FRETE', 'SEG', 'OUTRAS', 'VC_ITEM', 'CST', 'BC_ICMS', 'ALIQ_ICMS', 'ICMS', 'BC_ICMSST', 'ICMSST', 'IPI', 'CST_PIS Escriturado', 'BC_PIS', 'PIS', 'CST_COF', 'BC_COF', 'COF']

            df_ent = pd.read_csv(ent_f, sep=';', encoding='latin-1', header=None, names=cols_ent)
            df_sai = pd.read_csv(sai_f, sep=';', encoding='latin-1', header=None, names=cols_sai)

            cols_num_ent = ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'VC', 'ICMS-ST', 'VPROD', 'FRETE', 'DESC']
            cols_num_sai = ['ICMS', 'IPI', 'BC_ICMS', 'VC_ITEM', 'ALIQ_ICMS', 'ICMSST', 'VITEM', 'FRETE', 'DESC']
            for c in cols_num_ent: df_ent = clean_numeric_col(df_ent, c)
            for c in cols_num_sai: df_sai = clean_numeric_col(df_sai, c)
            
            df_ent = clean_cfop_col(df_ent, 'CFOP')
            df_sai = clean_cfop_col(df_sai, 'CFOP')

            # 2. Auditoria e Apuração 1
            df_ent[['DIAGNÓSTICO', 'AÇÃO_LEGAL', 'AÇÃO_CLIENTE_ERP', 'AÇÃO_DOMINIO']] = df_ent.apply(lambda r: auditoria_decisiva(r, 'entrada'), axis=1)
            df_sai[['DIAGNÓSTICO', 'AÇÃO_LEGAL', 'AÇÃO_CLIENTE_ERP', 'AÇÃO_DOMINIO']] = df_sai.apply(lambda r: auditoria_decisiva(r, 'saida'), axis=1)
            
            df_ent = reordenar_audit(df_ent)
            df_sai = reordenar_audit(df_sai)

            v_icms = df_sai['ICMS'].sum() - df_ent['VLR-ICMS'].sum()
            v_st = df_sai['ICMSST'].sum() - df_ent['ICMS-ST'].sum()
            v_ipi = df_sai['IPI'].sum() - df_ent['VLR_IPI'].sum()

            # 3. Processamento XML Matrioska (ZIP dentro de ZIP)
            credito_transporte = 0.0
            nfe_ignoradas = 0
            df_cte_detalhe = pd.DataFrame()
            
            if xml_f:
                df_cte_detalhe, credito_transporte, nfe_ignoradas = processar_pacote_xml(xml_f)

            # 4. Livros
            livro_ent = gerar_livro_p9(df_ent, 'entrada')
            livro_sai = gerar_livro_p9(df_sai, 'saida')

            st.success("Auditoria Completa (CSV + XML Matrioska) Concluída!")

            # --- APURAÇÃO 1 ---
            st.subheader("💰 Apuração 1: Baseada nos Arquivos CSV (Domínio)")
            resumo_1 = pd.DataFrame([
                {'Imposto': 'ICMS PRÓPRIO', 'Débitos': df_sai['ICMS'].sum(), 'Créditos': df_ent['VLR-ICMS'].sum(), 'Saldo': v_icms, 'Status': 'A RECOLHER' if v_icms > 0 else 'CREDOR'},
                {'Imposto': 'ICMS ST', 'Débitos': df_sai['ICMSST'].sum(), 'Créditos': df_ent['ICMS-ST'].sum(), 'Saldo': v_st, 'Status': 'A RECOLHER' if v_st > 0 else 'CREDOR'},
                {'Imposto': 'IPI', 'Débitos': df_sai['IPI'].sum(), 'Créditos': df_ent['VLR_IPI'].sum(), 'Saldo': v_ipi, 'Status': 'A RECOLHER' if v_ipi > 0 else 'CREDOR'}
            ])
            st.dataframe(resumo_1.style.format({'Débitos': 'R$ {:,.2f}', 'Créditos': 'R$ {:,.2f}', 'Saldo': 'R$ {:,.2f}'}), use_container_width=True)

            # --- APURAÇÃO 2 ---
            if xml_f:
                st.markdown("---")
                st.subheader("🚚 Apuração 2: Considerando Frete (XML/ZIP)")
                if nfe_ignoradas > 0:
                    st.warning(f"⚠️ {nfe_ignoradas} arquivos ignorados (NF-e, DANFE, PDF ou outros). Apenas CT-e considerados.")
                
                v_icms_final = v_icms - credito_transporte
                status_final = 'A RECOLHER' if v_icms_final > 0 else 'CREDOR'
                
                resumo_2 = pd.DataFrame([
                    {'Descrição': 'Saldo da Apuração 1 (CSV)', 'Valor': v_icms},
                    {'Descrição': '(-) Crédito de Transporte (XML/ZIP)', 'Valor': -credito_transporte},
                    {'Descrição': f'(=) NOVO SALDO ICMS ({status_final})', 'Valor': v_icms_final}
                ])
                st.table(resumo_2.style.format({'Valor': 'R$ {:,.2f}'}))
                
                with st.expander("Ver Detalhes dos CT-e Importados"):
                    st.dataframe(df_cte_detalhe)

            # --- LIVROS ---
            st.markdown("---")
            st.subheader("📖 Livro Fiscal (Resumo por CFOP)")
            tabs_livro = st.tabs(["Livro Entradas (P9)", "Livro Saídas (P9)"])
            fmt = {'Valor Contábil': 'R$ {:,.2f}', 'Base Cálculo': 'R$ {:,.2f}', 'ICMS': 'R$ {:,.2f}', 'ICMS ST': 'R$ {:,.2f}', 'IPI': 'R$ {:,.2f}', 'Isentas': 'R$ {:,.2f}', 'Outras': 'R$ {:,.2f}'}
            with tabs_livro[0]: st.dataframe(livro_ent.style.format(fmt), use_container_width=True)
            with tabs_livro[1]: st.dataframe(livro_sai.style.format(fmt), use_container_width=True)

            # --- INCONSISTÊNCIAS ---
            st.markdown("---")
            st.subheader("🚨 Inconsistências (Ação Necessária)")
            c1, c2 = st.columns(2)
            erros_sai = df_sai[df_sai['DIAGNÓSTICO'] != "Regular"]
            erros_ent = df_ent[df_ent['DIAGNÓSTICO'] != "Regular"]

            with c1:
                st.markdown("**Saídas com Erro**")
                if erros_sai.empty: st.info("Regular.")
                else: st.dataframe(erros_sai[['NF', 'CFOP', 'DIAGNÓSTICO', 'AÇÃO_LEGAL', 'AÇÃO_CLIENTE_ERP', 'AÇÃO_DOMINIO']], use_container_width=True)
            with c2:
                st.markdown("**Entradas com Erro**")
                if erros_ent.empty: st.info("Regular.")
                else: st.dataframe(erros_ent[['NUM_NF', 'CFOP', 'DIAGNÓSTICO', 'AÇÃO_DOMINIO', 'AÇÃO_LEGAL']], use_container_width=True)

            # Exportação
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_ent.to_excel(writer, sheet_name='Entradas Auditadas', index=False)
                df_sai.to_excel(writer, sheet_name='Saídas Auditadas', index=False)
                resumo_1.to_excel(writer, sheet_name='Apuração 1 (CSV)', index=False)
                if xml_f: df_cte_detalhe.to_excel(writer, sheet_name='Transporte (XML)', index=False)
                livro_ent.to_excel(writer, sheet_name='Livro Entradas P9', index=False)
                livro_sai.to_excel(writer, sheet_name='Livro Saídas P9', index=False)
                
                wb = writer.book
                fmt_red = wb.add_format({'bg_color': '#FFC7CE'})
                for sheet, df_ref in [('Entradas Auditadas', df_ent), ('Saídas Auditadas', df_sai)]:
                    ws = writer.sheets[sheet]
                    ws.set_column('A:Z', 22)
                    for i, val in enumerate(df_ref['DIAGNÓSTICO']):
                        if val != "Regular": ws.set_row(i + 1, None, fmt_red)

            st.download_button("📥 Baixar Relatório Completo (CSV+XML)", output.getvalue(), "Curador_Supremo.xlsx")

        except Exception as e:
            st.error(f"Erro Crítico: {e}")

if __name__ == "__main__":
    main()
