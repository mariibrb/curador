import streamlit as st
import pandas as pd
import io

# Configuração da página
st.set_page_config(page_title="Curador - Auditoria Fiscal Robusta", layout="wide")

def clean_numeric_col(df, col_name):
    """Limpeza técnica de colunas numéricas."""
    if col_name in df.columns:
        s = df[col_name].astype(str).str.replace(r'\s+', '', regex=True)
        s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df[col_name] = pd.to_numeric(s, errors='coerce').fillna(0.0)
    return df

def auditoria_robusta(row, tipo='saida'):
    """
    MOTOR DE DECISÃO:
    Analisa o erro e define:
    1. Diagnóstico Técnico
    2. Ação Legal (Nota Complementar vs CC-e)
    3. Ação Preventiva (Arrumar ERP)
    4. Ação Contábil (Arrumar Domínio)
    """
    # Dados Base
    cfop = str(row['CFOP']).strip().replace('.', '')
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
    
    # Outputs
    diag, acao_legal, acao_preventiva, acao_dominio = [], [], [], []

    # ==============================================================================
    # 1. ANÁLISE DE ICMS PRÓPRIO
    # ==============================================================================
    
    # CENÁRIO: CFOP 6403 sem destaque de ICMS Próprio
    if tipo == 'saida' and cfop == '6403' and vlr_icms == 0:
        diag.append("ERRO GRAVE: Omissão de ICMS Próprio em operação de Substituto (6403).")
        acao_legal.append("EMITIR NOTA FISCAL COMPLEMENTAR DE ICMS (Imposto esquecido).")
        acao_preventiva.append("Configurar ERP para destacar ICMS Próprio + ST.")
        acao_dominio.append("Acumulador: Aba Impostos > Incluir ICMS > Aba Geral > Opção 'Faturamento de Substituto'.")

    # CENÁRIO: Base de Cálculo menor que o devido (Frete não somado)
    if bc_icms > 0:
        base_teorica = vlr_prod + frete - desc
        if (base_teorica - bc_icms) > 1.0:
            diff = base_teorica - bc_icms
            diag.append(f"BASE REDUZIDA INDEVIDA: Base {bc_icms} < {base_teorica} (Frete não somado?).")
            acao_legal.append("EMITIR NOTA COMPLEMENTAR DE ICMS (Diferença de Base).")
            acao_preventiva.append("Marcar flag 'Frete compõe base ICMS' no sistema emissor.")
            acao_dominio.append("Acumulador: Aba ICMS > Opção 'Frete compõe base de cálculo'.")

    # CENÁRIO: Alíquota Interestadual Errada (Ex: Mandou 12% pro Nordeste)
    if tipo == 'saida' and cfop.startswith('6'):
        reg_7 = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'RN', 'RO', 'RR', 'SE', 'TO']
        if uf_dest in reg_7 and aliq_icms not in [7.0, 4.0] and aliq_icms > 0:
            diag.append(f"ALÍQUOTA INCORRETA: Usado {aliq_icms}% para {uf_dest} (Correto: 7%).")
            if aliq_icms < 7:
                acao_legal.append("EMITIR NOTA COMPLEMENTAR (Diferença de Alíquota).")
            else:
                acao_legal.append("ANÁLISE: Imposto pago a maior. Ver possibilidade de estorno/crédito.")
            acao_preventiva.append(f"Corrigir cadastro de alíquota interestadual para UF {uf_dest}.")
            acao_dominio.append("Cadastro de Produto > Impostos > ICMS Estadual > Definir exceção por UF.")

    # ==============================================================================
    # 2. ANÁLISE DE ICMS ST
    # ==============================================================================

    # CENÁRIO: CST exige ST, mas valor é zero
    if cst in cst_st_mandatorio and vlr_st == 0:
        diag.append(f"OMISSÃO DE ST: CST {cst} obriga destaque, valor está zerado.")
        acao_legal.append("EMITIR NOTA COMPLEMENTAR DE ICMS ST.")
        acao_preventiva.append("Revisar MVA/IVA no cadastro do produto.")
        acao_dominio.append("Acumulador: Aba Estadual > Selecionar 'Gera guia de recolhimento ST'.")

    # CENÁRIO: CST 90 sem ST em operação que deveria ter
    elif cst == '90' and vlr_st == 0 and cfop in cfop_st_gerador:
        diag.append("OMISSÃO DE ST (CST 90): Operação de substituição sem retenção.")
        acao_legal.append("EMITIR NOTA COMPLEMENTAR DE ICMS ST.")
        acao_preventiva.append("Configurar regra de ST para este CFOP/CST.")
        acao_dominio.append("Acumulador: Verificar se imposto 01-ICMS tem subtributária.")

    # CENÁRIO: Destaque indevido (CST errado)
    elif vlr_st > 0 and cst not in cst_st_permitido and cst != '60':
        diag.append(f"ERRO FORMAL/FINANCEIRO: ST destacada em CST {cst} (Não permitido).")
        acao_legal.append("Se cobrado do cliente: Devolução/Refaturamento. Se erro só de CST: CARTA DE CORREÇÃO (CC-e).")
        acao_preventiva.append("Alterar CST do produto para 10 ou 60.")
        acao_dominio.append("Utilitários > Alterar CST de ICMS em lote.")

    # ==============================================================================
    # 3. ANÁLISE DE IPI
    # ==============================================================================

    # CENÁRIO: Indústria sem destacar IPI
    if cfop in cfop_industrial and vlr_ipi == 0:
        diag.append("OMISSÃO DE IPI: Venda industrial sem imposto federal.")
        acao_legal.append("EMITIR NOTA COMPLEMENTAR DE IPI.")
        acao_preventiva.append("Cadastrar alíquota de IPI na NCM do produto.")
        acao_dominio.append("Acumulador: Incluir imposto IPI. Produto: Vincular classificação fiscal.")

    # CENÁRIO: Compra Industrial sem Crédito (Entrada)
    if tipo == 'entrada' and cfop in ['1101', '2101'] and vlr_ipi == 0:
        diag.append("PERDA DE CRÉDITO IPI: Insumo industrial sem aproveitamento.")
        acao_legal.append("Verificar XML do fornecedor. Se destacado lá, lançar crédito manualmente.")
        acao_dominio.append("Lançamento: Habilitar campo de IPI e verificar CST de entrada (50).")

    return pd.Series({
        'DIAGNÓSTICO_TÉCNICO': " | ".join(diag) if diag else "Regular",
        'AÇÃO_LEGAL_IMEDIATA': " | ".join(acao_legal) if acao_legal else "-",
        'AÇÃO_SISTEMA_CLIENTE': " | ".join(acao_preventiva) if acao_preventiva else "-",
        'AÇÃO_DOMINIO_SISTEMAS': " | ".join(acao_dominio) if dominio else "-"
    })

def reordenar_colunas(df, tipo='saida'):
    """Traz as colunas de inteligência para o começo."""
    cols = list(df.columns)
    novas_cols = ['DIAGNÓSTICO_TÉCNICO', 'AÇÃO_LEGAL_IMEDIATA', 'AÇÃO_SISTEMA_CLIENTE', 'AÇÃO_DOMINIO_SISTEMAS']
    
    # Remove originais
    for c in novas_cols:
        if c in cols: cols.remove(c)
            
    # Insere na posição 1 (logo após NF)
    pos = 1
    for c in reversed(novas_cols):
        cols.insert(pos, c)
        
    return df[cols]

def main():
    st.title("⚖️ Curador: Ferramenta Robusta de Auditoria e Compliance")
    st.markdown("---")
    
    c1, c2 = st.columns(2)
    with c1: ent_f = st.file_uploader("📥 Entradas (CSV)", type=["csv"])
    with c2: sai_f = st.file_uploader("📤 Saídas (CSV)", type=["csv"])

    if ent_f and sai_f:
        try:
            # Cabeçalhos originais
            cols_ent = ['NUM_NF', 'DATA_EMISSAO', 'CNPJ', 'UF', 'VLR_NF', 'AC', 'CFOP', 'COD_PROD', 'DESCR', 'NCM', 'UNID', 'VUNIT', 'QTDE', 'VPROD', 'DESC', 'FRETE', 'SEG', 'DESP', 'VC', 'CST-ICMS', 'BC-ICMS', 'VLR-ICMS', 'BC-ICMS-ST', 'ICMS-ST', 'VLR_IPI', 'CST_PIS', 'BC_PIS', 'VLR_PIS', 'CST_COF', 'BC_COF', 'VLR_COF']
            cols_sai = ['NF', 'DATA_EMISSAO', 'CNPJ', 'Ufp', 'VC', 'AC', 'CFOP', 'COD_ITEM', 'DESC_ITEM', 'NCM', 'UND', 'VUNIT', 'QTDE', 'VITEM', 'DESC', 'FRETE', 'SEG', 'OUTRAS', 'VC_ITEM', 'CST', 'BC_ICMS', 'ALIQ_ICMS', 'ICMS', 'BC_ICMSST', 'ICMSST', 'IPI', 'CST_PIS Escriturado', 'BC_PIS', 'PIS', 'CST_COF', 'BC_COF', 'COF']

            df_ent = pd.read_csv(ent_f, sep=';', encoding='latin-1', header=None, names=cols_ent)
            df_sai = pd.read_csv(sai_f, sep=';', encoding='latin-1', header=None, names=cols_sai)

            # Limpeza Numérica
            for c in ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'VC', 'ICMS-ST', 'VPROD', 'FRETE', 'DESC']: df_ent = clean_numeric_col(df_ent, c)
            for c in ['ICMS', 'IPI', 'BC_ICMS', 'VC_ITEM', 'ALIQ_ICMS', 'ICMSST', 'VITEM', 'FRETE', 'DESC']: df_sai = clean_numeric_col(df_sai, c)

            # --- PROCESSAMENTO ROBUSTO ---
            df_ent[['DIAGNÓSTICO_TÉCNICO', 'AÇÃO_LEGAL_IMEDIATA', 'AÇÃO_SISTEMA_CLIENTE', 'AÇÃO_DOMINIO_SISTEMAS']] = df_ent.apply(lambda r: auditoria_robusta(r, 'entrada'), axis=1)
            df_sai[['DIAGNÓSTICO_TÉCNICO', 'AÇÃO_LEGAL_IMEDIATA', 'AÇÃO_SISTEMA_CLIENTE', 'AÇÃO_DOMINIO_SISTEMAS']] = df_sai.apply(lambda r: auditoria_robusta(r, 'saida'), axis=1)

            # Reordenação
            df_ent = reordenar_colunas(df_ent, 'entrada')
            df_sai = reordenar_colunas(df_sai, 'saida')

            # --- CÁLCULO DE SALDOS ---
            v_icms = df_sai['ICMS'].sum() - df_ent['VLR-ICMS'].sum()
            v_st = df_sai['ICMSST'].sum() - df_ent['ICMS-ST'].sum()
            v_ipi = df_sai['IPI'].sum() - df_ent['VLR_IPI'].sum()

            st.success("Auditoria Completa Realizada!")

            # --- PAINEL DE SALDOS ---
            st.subheader("📊 Apuração dos Impostos")
            resumo = pd.DataFrame([
                {'Imposto': 'ICMS PRÓPRIO', 'Débito': df_sai['ICMS'].sum(), 'Crédito': df_ent['VLR-ICMS'].sum(), 'Saldo': v_icms, 'Status': 'A RECOLHER' if v_icms > 0 else 'CREDOR'},
                {'Imposto': 'ICMS ST', 'Débito': df_sai['ICMSST'].sum(), 'Crédito': df_ent['ICMS-ST'].sum(), 'Saldo': v_st, 'Status': 'A RECOLHER' if v_st > 0 else 'CREDOR'},
                {'Imposto': 'IPI', 'Débito': df_sai['IPI'].sum(), 'Crédito': df_ent['VLR_IPI'].sum(), 'Saldo': v_ipi, 'Status': 'A RECOLHER' if v_ipi > 0 else 'CREDOR'}
            ])
            st.table(resumo.style.format({'Débito': 'R$ {:,.2f}', 'Crédito': 'R$ {:,.2f}', 'Saldo': 'R$ {:,.2f}'}))

            # --- PRÉVIAS DE INCONSISTÊNCIAS ---
            st.subheader("🚨 Inconsistências Críticas (Com Ação Sugerida)")
            
            # Filtro apenas erros
            erros_sai = df_sai[df_sai['DIAGNÓSTICO_TÉCNICO'] != "Regular"]
            erros_ent = df_ent[df_ent['DIAGNÓSTICO_TÉCNICO'] != "Regular"]

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Saídas: Ações Necessárias**")
                if erros_sai.empty: st.info("Nenhuma inconsistência.")
                else: st.dataframe(erros_sai[['NF', 'CFOP', 'DIAGNÓSTICO_TÉCNICO', 'AÇÃO_LEGAL_IMEDIATA']], use_container_width=True)
            
            with c2:
                st.markdown("**Entradas: Ações Necessárias**")
                if erros_ent.empty: st.info("Nenhuma inconsistência.")
                else: st.dataframe(erros_ent[['NUM_NF', 'CFOP', 'DIAGNÓSTICO_TÉCNICO', 'AÇÃO_DOMINIO_SISTEMAS']], use_container_width=True)

            # Exportação
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_ent.to_excel(writer, sheet_name='Entradas Auditadas', index=False)
                df_sai.to_excel(writer, sheet_name='Saídas Auditadas', index=False)
                resumo.to_excel(writer, sheet_name='Apuração Final', index=False)
                
                workbook = writer.book
                fmt_red = workbook.add_format({'bg_color': '#FFC7CE'})
                for sheet, df_ref in [('Entradas Auditadas', df_ent), ('Saídas Auditadas', df_sai)]:
                    ws = writer.sheets[sheet]
                    ws.set_column('A:Z', 25) # Largura para ler as ações
                    for i, val in enumerate(df_ref['DIAGNÓSTICO_TÉCNICO']):
                        if val != "Regular": ws.set_row(i + 1, None, fmt_red)

            st.download_button("📥 Baixar Relatório Robusto", output.getvalue(), "Auditoria_Completa_Curador.xlsx")

        except Exception as e:
            st.error(f"Erro Crítico: {e}")

if __name__ == "__main__":
    main()
