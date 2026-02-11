import streamlit as st
import pandas as pd
import io

# Configuração da página - O Curador
st.set_page_config(page_title="Curador - Auditoria Fiscal Robusta", layout="wide")

# --- FUNÇÕES UTILITÁRIAS ---
def clean_numeric_col(df, col_name):
    """Garante que números brasileiros (1.000,00) sejam lidos corretamente."""
    if col_name in df.columns:
        s = df[col_name].astype(str).str.replace(r'\s+', '', regex=True)
        s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df[col_name] = pd.to_numeric(s, errors='coerce').fillna(0.0)
    return df

def auditoria_decisiva(row, tipo='saida'):
    """
    MOTOR DE AUDITORIA ROBUSTO
    Cruza CFOP, CST, Alíquotas e Valores para determinar a AÇÃO EXATA.
    """
    # 1. Extração de Dados
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
    
    # 2. Listas de Regra de Negócio
    cst_st_mandatorio = ['10', '30', '70']       # Exige valor
    cst_st_permitido = ['10', '30', '70', '90']  # Aceita valor
    cfop_st_gerador = ['5401', '5403', '6401', '6403', '5405', '6405'] # Operações de ST
    cfop_industrial = ['5101', '6101']           # Operações de IPI
    
    # 3. Listas de Saída
    diag, legal, prevent, dominio = [], [], [], []

    # -------------------------------------------------------------------------
    # ANÁLISE 1: ICMS PRÓPRIO
    # -------------------------------------------------------------------------
    
    # CASO CRÍTICO: CFOP 6403 (Substituto) sem ICMS Próprio
    if tipo == 'saida' and cfop == '6403' and vlr_icms == 0:
        diag.append("OMISSÃO GRAVE: CFOP 6403 exige destaque de ICMS Próprio + ST.")
        legal.append("EMITIR NOTA COMPLEMENTAR DE ICMS (Valor faltante).")
        prevent.append("Configurar ERP para destacar ICMS Próprio em operação de Substituto.")
        dominio.append("Acumulador > Impostos > ICMS > Aba Geral > Opção 'Faturamento de Substituto'.")

    # CASO: Base de Cálculo Incompleta (Frete não somado)
    if bc_icms > 0:
        base_esperada = vlr_prod + frete - desc
        if (base_esperada - bc_icms) > 1.0: # Tolerância de arredondamento
            diag.append(f"BASE REDUZIDA: Base {bc_icms} < {base_esperada} (Frete/Seguro fora?).")
            legal.append("EMITIR NOTA COMPLEMENTAR DE ICMS (Diferença de Base).")
            prevent.append("Marcar flag 'Frete compõe base ICMS' no emissor.")
            dominio.append("Acumulador > ICMS > Opção 'Frete compõe base de cálculo'.")

    # CASO: Alíquota Interestadual Errada
    if tipo == 'saida' and cfop.startswith('6'):
        reg_7 = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'RN', 'RO', 'RR', 'SE', 'TO']
        if uf_dest in reg_7 and aliq_icms not in [7.0, 4.0] and aliq_icms > 0:
            diag.append(f"ALÍQUOTA ERRADA: Usado {aliq_icms}% p/ {uf_dest} (Meta: 7%).")
            legal.append("EMITIR NOTA COMPLEMENTAR (se < 7%) ou PEDIDO DE RESTITUIÇÃO (se > 7%).")
            prevent.append(f"Corrigir cadastro de alíquota interestadual p/ {uf_dest}.")
            dominio.append("Cadastro Produto > Impostos > ICMS Estadual > Definir exceção por UF.")

    # -------------------------------------------------------------------------
    # ANÁLISE 2: ICMS ST (SUBSTITUIÇÃO TRIBUTÁRIA)
    # -------------------------------------------------------------------------

    # CASO: CST exige ST, valor zerado
    if cst in cst_st_mandatorio and vlr_st == 0:
        diag.append(f"FALTA DE ST: CST {cst} obriga destaque.")
        legal.append("EMITIR NOTA COMPLEMENTAR DE ICMS ST.")
        prevent.append("Revisar MVA e cadastro tributário do produto.")
        dominio.append("Acumulador > Estadual > 'Gera guia de recolhimento ST'.")

    # CASO: CST 90 em operação de ST (sem valor)
    elif cst == '90' and vlr_st == 0 and cfop in cfop_st_gerador:
        diag.append("FALTA DE ST (CST 90): Operação 5403/6403 exige retenção.")
        legal.append("EMITIR NOTA COMPLEMENTAR DE ICMS ST.")
        prevent.append("Configurar regra de ST para este cenário no ERP.")
        dominio.append("Acumulador > Verificar sub-tributária no imposto 01.")

    # CASO: Destaque Indevido (CST errado)
    elif vlr_st > 0 and cst not in cst_st_permitido and cst != '60':
        diag.append(f"ST INDEVIDA: CST {cst} não permite destaque.")
        legal.append("CARTA DE CORREÇÃO (CC-e) para ajustar CST (se valor for devido) ou Refaturamento.")
        prevent.append("Ajustar CST do produto para 10 ou 60.")
        dominio.append("Utilitários > Alterar CST de ICMS em lote.")

    # -------------------------------------------------------------------------
    # ANÁLISE 3: IPI (INDUSTRIAL)
    # -------------------------------------------------------------------------

    # CASO: Saída Industrial sem IPI
    if cfop in cfop_industrial and vlr_ipi == 0:
        diag.append("OMISSÃO DE IPI: Venda de produção própria.")
        legal.append("EMITIR NOTA COMPLEMENTAR DE IPI.")
        prevent.append("Cadastrar alíquota IPI na NCM.")
        dominio.append("Acumulador > Incluir imposto IPI. Produto > Classificação Fiscal.")

    # CASO: Entrada Industrial sem Crédito
    if tipo == 'entrada' and cfop in ['1101', '2101'] and vlr_ipi == 0:
        diag.append("CRÉDITO IPI NÃO TOMADO: Insumo industrial.")
        legal.append("Verificar XML fornecedor. Se destacado, lançar manual.")
        dominio.append("Lançamento > Habilitar campo IPI e usar CST de crédito (50).")

    # Retorno Formatado
    return pd.Series({
        'DIAGNÓSTICO': " | ".join(diag) if diag else "Regular",
        'AÇÃO_LEGAL': " | ".join(legal) if legal else "-",
        'AÇÃO_CLIENTE_ERP': " | ".join(prevent) if prevent else "-",
        'AÇÃO_DOMINIO': " | ".join(dominio) if dominio else "-"
    })

def reordenar_audit(df):
    """Move as colunas de inteligência para o início da visualização."""
    cols = list(df.columns)
    prioridade = ['DIAGNÓSTICO', 'AÇÃO_LEGAL', 'AÇÃO_DOMINIO', 'AÇÃO_CLIENTE_ERP']
    for c in prioridade:
        if c in cols: cols.remove(c)
    # Insere logo após a NF (índice 1)
    idx = 1
    for c in reversed(prioridade):
        cols.insert(idx, c)
    return df[cols]

def main():
    st.title("⚖️ Curador: Auditoria Fiscal Robusta (Compliance Total)")
    st.markdown("---")
    
    # 1. Upload Centralizado
    c1, c2 = st.columns(2)
    with c1: ent_f = st.file_uploader("📥 Entradas (CSV)", type=["csv"])
    with c2: sai_f = st.file_uploader("📤 Saídas (CSV)", type=["csv"])

    if ent_f and sai_f:
        try:
            # 2. Definição de Colunas (Fiel ao seu arquivo)
            cols_ent = ['NUM_NF', 'DATA_EMISSAO', 'CNPJ', 'UF', 'VLR_NF', 'AC', 'CFOP', 'COD_PROD', 'DESCR', 'NCM', 'UNID', 'VUNIT', 'QTDE', 'VPROD', 'DESC', 'FRETE', 'SEG', 'DESP', 'VC', 'CST-ICMS', 'BC-ICMS', 'VLR-ICMS', 'BC-ICMS-ST', 'ICMS-ST', 'VLR_IPI', 'CST_PIS', 'BC_PIS', 'VLR_PIS', 'CST_COF', 'BC_COF', 'VLR_COF']
            cols_sai = ['NF', 'DATA_EMISSAO', 'CNPJ', 'Ufp', 'VC', 'AC', 'CFOP', 'COD_ITEM', 'DESC_ITEM', 'NCM', 'UND', 'VUNIT', 'QTDE', 'VITEM', 'DESC', 'FRETE', 'SEG', 'OUTRAS', 'VC_ITEM', 'CST', 'BC_ICMS', 'ALIQ_ICMS', 'ICMS', 'BC_ICMSST', 'ICMSST', 'IPI', 'CST_PIS Escriturado', 'BC_PIS', 'PIS', 'CST_COF', 'BC_COF', 'COF']

            df_ent = pd.read_csv(ent_f, sep=';', encoding='latin-1', header=None, names=cols_ent)
            df_sai = pd.read_csv(sai_f, sep=';', encoding='latin-1', header=None, names=cols_sai)

            # 3. Limpeza de Dados
            cols_num_ent = ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'VC', 'ICMS-ST', 'VPROD', 'FRETE', 'DESC']
            cols_num_sai = ['ICMS', 'IPI', 'BC_ICMS', 'VC_ITEM', 'ALIQ_ICMS', 'ICMSST', 'VITEM', 'FRETE', 'DESC']
            for c in cols_num_ent: df_ent = clean_numeric_col(df_ent, c)
            for c in cols_num_sai: df_sai = clean_numeric_col(df_sai, c)

            # 4. Aplicação da Auditoria Robusta
            df_ent[['DIAGNÓSTICO', 'AÇÃO_LEGAL', 'AÇÃO_CLIENTE_ERP', 'AÇÃO_DOMINIO']] = df_ent.apply(lambda r: auditoria_decisiva(r, 'entrada'), axis=1)
            df_sai[['DIAGNÓSTICO', 'AÇÃO_LEGAL', 'AÇÃO_CLIENTE_ERP', 'AÇÃO_DOMINIO']] = df_sai.apply(lambda r: auditoria_decisiva(r, 'saida'), axis=1)

            # Reordenação para visualização
            df_ent = reordenar_audit(df_ent)
            df_sai = reordenar_audit(df_sai)

            # 5. Cálculo de Saldos
            v_icms = df_sai['ICMS'].sum() - df_ent['VLR-ICMS'].sum()
            v_st = df_sai['ICMSST'].sum() - df_ent['ICMS-ST'].sum()
            v_ipi = df_sai['IPI'].sum() - df_ent['VLR_IPI'].sum()

            st.success("Auditoria Concluída com Sucesso!")

            # 6. Painel de Apuração (O que pagar?)
            st.subheader("📊 Apuração Final (Débito vs Crédito)")
            resumo = pd.DataFrame([
                {'Imposto': 'ICMS PRÓPRIO', 'Débitos': df_sai['ICMS'].sum(), 'Créditos': df_ent['VLR-ICMS'].sum(), 'Saldo': v_icms, 'Status': 'A RECOLHER' if v_icms > 0 else 'CREDOR'},
                {'Imposto': 'ICMS ST', 'Débitos': df_sai['ICMSST'].sum(), 'Créditos': df_ent['ICMS-ST'].sum(), 'Saldo': v_st, 'Status': 'A RECOLHER' if v_st > 0 else 'CREDOR'},
                {'Imposto': 'IPI', 'Débitos': df_sai['IPI'].sum(), 'Créditos': df_ent['VLR_IPI'].sum(), 'Saldo': v_ipi, 'Status': 'A RECOLHER' if v_ipi > 0 else 'CREDOR'}
            ])
            st.dataframe(resumo.style.format({'Débitos': 'R$ {:,.2f}', 'Créditos': 'R$ {:,.2f}', 'Saldo': 'R$ {:,.2f}'}), use_container_width=True)

            # 7. Prévias de Inconsistências (O que corrigir?)
            st.markdown("---")
            st.subheader("🚨 Inconsistências Detectadas (Com Plano de Ação)")
            
            c1, c2 = st.columns(2)
            # Filtra apenas erros
            erros_sai = df_sai[df_sai['DIAGNÓSTICO'] != "Regular"]
            erros_ent = df_ent[df_ent['DIAGNÓSTICO'] != "Regular"]

            with c1:
                st.markdown("**📤 Saídas: Erros & Soluções**")
                if erros_sai.empty: st.info("Nenhuma inconsistência nas saídas.")
                else: st.dataframe(erros_sai[['NF', 'CFOP', 'DIAGNÓSTICO', 'AÇÃO_LEGAL', 'AÇÃO_DOMINIO']], use_container_width=True)
            
            with c2:
                st.markdown("**📥 Entradas: Erros & Soluções**")
                if erros_ent.empty: st.info("Nenhuma inconsistência nas entradas.")
                else: st.dataframe(erros_ent[['NUM_NF', 'CFOP', 'DIAGNÓSTICO', 'AÇÃO_DOMINIO']], use_container_width=True)

            # 8. Exportação Completa
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_ent.to_excel(writer, sheet_name='Entradas Auditadas', index=False)
                df_sai.to_excel(writer, sheet_name='Saídas Auditadas', index=False)
                resumo.to_excel(writer, sheet_name='Apuração Final', index=False)
                
                # Formatação Condicional (Vermelho para Erro)
                workbook = writer.book
                fmt_red = workbook.add_format({'bg_color': '#FFC7CE'})
                for sheet, df_ref in [('Entradas Auditadas', df_ent), ('Saídas Auditadas', df_sai)]:
                    ws = writer.sheets[sheet]
                    ws.set_column('A:Z', 22) # Largura legível
                    for i, val in enumerate(df_ref['DIAGNÓSTICO']):
                        if val != "Regular": ws.set_row(i + 1, None, fmt_red)

            st.download_button("📥 Baixar Relatório de Auditoria Robusta", output.getvalue(), "Curador_Auditoria_Completa.xlsx")

        except Exception as e:
            st.error(f"Erro Crítico no Processamento: {e}")

if __name__ == "__main__":
    main()
