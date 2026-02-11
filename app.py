import streamlit as st
import pandas as pd
import io

# Configuração da página - O Curador
st.set_page_config(page_title="Curador - Painel de Apuração Fiscal", layout="wide")

def clean_numeric_col(df, col_name):
    """Limpeza técnica de colunas numéricas (decimais BR)."""
    if col_name in df.columns:
        s = df[col_name].astype(str).str.replace(r'\s+', '', regex=True)
        s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df[col_name] = pd.to_numeric(s, errors='coerce').fillna(0.0)
    return df

def auditoria_icms_ipi(row, tipo='saida'):
    """
    Motor de Auditoria (ICMS, ST, IPI).
    Retorna: Diagnóstico, Ação Domínio e Ação Cliente.
    """
    cfop = str(row['CFOP']).strip().replace('.', '')
    # CST ICMS (2 dígitos, ignora origem)
    cst_full = str(row['CST-ICMS'] if tipo == 'entrada' else row['CST']).strip()
    cst = cst_full[-2:] if len(cst_full) >= 2 else cst_full.zfill(2)
    
    # Valores
    vlr_prod = row['VPROD'] if tipo == 'entrada' else row['VITEM']
    vlr_icms = row['VLR-ICMS'] if tipo == 'entrada' else row['ICMS']
    bc_icms = row['BC-ICMS'] if tipo == 'entrada' else row['BC_ICMS']
    aliq_icms = 0 if tipo == 'entrada' else row['ALIQ_ICMS']
    vlr_st = row['ICMS-ST'] if tipo == 'entrada' else row['ICMSST']
    vlr_ipi = row['VLR_IPI'] if tipo == 'entrada' else row['IPI']
    
    # Acessórios
    frete = row['FRETE']
    desc = row['DESC']
    
    uf_dest = "" if tipo == 'entrada' else str(row['Ufp']).strip().upper()
    
    erros, cliente, dominio = [], [], []

    # 1. ICMS PRÓPRIO
    if tipo == 'saida' and cfop == '6403' and vlr_icms == 0:
        erros.append("FALTA ICMS PRÓPRIO (6403).")
        cliente.append("Destacar ICMS Próprio.")
        dominio.append("Habilitar ICMS Próprio em ST no Acumulador.")

    if bc_icms > 0:
        base_teorica = vlr_prod + frete - desc
        if (base_teorica - bc_icms) > 1.0:
            erros.append("BASE ICMS MENOR QUE PRODUTO+FRETE.")
            dominio.append("Marcar 'Frete compõe base de ICMS' no acumulador.")

    if tipo == 'saida' and cfop.startswith('6'):
        reg_7 = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'RN', 'RO', 'RR', 'SE', 'TO']
        if uf_dest in reg_7 and aliq_icms not in [7.0, 4.0]:
            erros.append(f"ALÍQUOTA {aliq_icms}% ERRADA (META 7%).")
            cliente.append("Ajustar alíquota interestadual.")

    # 2. ICMS ST
    cst_st_mandatorio = ['10', '30', '70']
    cst_st_permitido = ['10', '30', '70', '90']
    cfop_st = ['5401', '5403', '6401', '6403', '5405', '6405']

    if cst in cst_st_mandatorio and vlr_st == 0:
        erros.append(f"CST {cst} EXIGE ST (ZERADO).")
        cliente.append("Informar ST.")
        dominio.append("Marcar 'Gera guia ST'.")
    
    elif cst == '90' and vlr_st == 0 and cfop in cfop_st:
        erros.append(f"CST 90 EM CFOP {cfop} EXIGE ST.")
        cliente.append("Destacar ST.")

    elif vlr_st > 0 and cst not in cst_st_permitido and cst != '60':
        erros.append(f"ST INDEVIDO P/ CST {cst}.")
        cliente.append("Zerar ST.")

    # 3. IPI
    if cfop in ['5101', '6101'] and vlr_ipi == 0:
        erros.append("VENDA INDUSTRIAL SEM IPI.")
        dominio.append("Configurar IPI (Imposto 2).")
    
    if tipo == 'entrada' and cfop in ['1101', '2101'] and vlr_ipi == 0:
        erros.append("COMPRA INDUSTRIAL SEM CRÉDITO IPI.")
        dominio.append("Verificar apropriação de IPI.")

    return pd.Series({
        'DIAGNÓSTICO': " | ".join(erros) if erros else "Regular",
        'AÇÃO_DOMINIO': " | ".join(dominio) if dominio else "-",
        'AÇÃO_CLIENTE': " | ".join(cliente) if cliente else "-"
    })

def reordenar_colunas(df, tipo='saida'):
    """Move colunas de auditoria para o início (visibilidade imediata)."""
    cols = list(df.columns)
    cols_audit = ['DIAGNÓSTICO', 'AÇÃO_DOMINIO', 'AÇÃO_CLIENTE']
    
    # Remove da posição original
    for c in cols_audit:
        if c in cols: cols.remove(c)
            
    # Insere logo após a NF (posições 1, 2, 3)
    pos = 1
    for c in cols_audit:
        cols.insert(pos, c)
        pos += 1
        
    return df[cols]

def main():
    st.title("⚖️ Curador: Painel de Apuração e Auditoria")
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

            # Limpeza
            for c in ['VLR-ICMS', 'VLR_IPI', 'BC-ICMS', 'VC', 'ICMS-ST', 'VPROD', 'FRETE', 'DESC']: df_ent = clean_numeric_col(df_ent, c)
            for c in ['ICMS', 'IPI', 'BC_ICMS', 'VC_ITEM', 'ALIQ_ICMS', 'ICMSST', 'VITEM', 'FRETE', 'DESC']: df_sai = clean_numeric_col(df_sai, c)

            # Processamento
            df_ent[['DIAGNÓSTICO', 'AÇÃO_DOMINIO', 'AÇÃO_CLIENTE']] = df_ent.apply(lambda r: auditoria_icms_ipi(r, 'entrada'), axis=1)
            df_sai[['DIAGNÓSTICO', 'AÇÃO_DOMINIO', 'AÇÃO_CLIENTE']] = df_sai.apply(lambda r: auditoria_icms_ipi(r, 'saida'), axis=1)

            # Reordenar para ver o erro primeiro
            df_ent = reordenar_colunas(df_ent, 'entrada')
            df_sai = reordenar_colunas(df_sai, 'saida')

            # --- CÁLCULO DO RESUMO (CRÉDITO vs DÉBITO) ---
            resumo_dados = []
            
            # ICMS
            cred_icms = df_ent['VLR-ICMS'].sum()
            deb_icms = df_sai['ICMS'].sum()
            saldo_icms = deb_icms - cred_icms
            resumo_dados.append({'Imposto': 'ICMS PRÓPRIO', 'Débitos (Saídas)': deb_icms, 'Créditos (Entradas)': cred_icms, 'Saldo Final': saldo_icms, 'Situação': 'A RECOLHER' if saldo_icms > 0 else 'CREDOR'})

            # ST
            cred_st = df_ent['ICMS-ST'].sum()
            deb_st = df_sai['ICMSST'].sum()
            saldo_st = deb_st - cred_st
            resumo_dados.append({'Imposto': 'ICMS ST', 'Débitos (Saídas)': deb_st, 'Créditos (Entradas)': cred_st, 'Saldo Final': saldo_st, 'Situação': 'A RECOLHER' if saldo_st > 0 else 'CREDOR'})

            # IPI
            cred_ipi = df_ent['VLR_IPI'].sum()
            deb_ipi = df_sai['IPI'].sum()
            saldo_ipi = deb_ipi - cred_ipi
            resumo_dados.append({'Imposto': 'IPI', 'Débitos (Saídas)': deb_ipi, 'Créditos (Entradas)': cred_ipi, 'Saldo Final': saldo_ipi, 'Situação': 'A RECOLHER' if saldo_ipi > 0 else 'CREDOR'})

            df_resumo = pd.DataFrame(resumo_dados)

            st.success("Processamento Concluído!")

            # --- EXIBIÇÃO DO RESUMO NA TELA ---
            st.subheader("📊 Resumo de Apuração (Débito x Crédito)")
            
            # Formatação visual do saldo
            st.dataframe(df_resumo.style.format({
                'Débitos (Saídas)': 'R$ {:,.2f}',
                'Créditos (Entradas)': 'R$ {:,.2f}',
                'Saldo Final': 'R$ {:,.2f}'
            }), use_container_width=True)

            # --- PRÉVIAS DE ERROS ---
            st.markdown("---")
            st.subheader("🔎 Inconsistências (Ação Necessária)")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Saídas com Erro**")
                erros_sai = df_sai[df_sai['DIAGNÓSTICO'] != "Regular"]
                if erros_sai.empty: st.info("Tudo certo nas saídas.")
                else: st.dataframe(erros_sai, use_container_width=True)
            with c2:
                st.markdown("**Entradas com Erro**")
                erros_ent = df_ent[df_ent['DIAGNÓSTICO'] != "Regular"]
                if erros_ent.empty: st.info("Tudo certo nas entradas.")
                else: st.dataframe(erros_ent, use_container_width=True)

            # Exportação
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_ent.to_excel(writer, sheet_name='Entradas Auditadas', index=False)
                df_sai.to_excel(writer, sheet_name='Saídas Auditadas', index=False)
                df_resumo.to_excel(writer, sheet_name='Apuração Final', index=False)
                
                workbook = writer.book
                fmt_red = workbook.add_format({'bg_color': '#FFC7CE'})
                for sheet, df_ref in [('Entradas Auditadas', df_ent), ('Saídas Auditadas', df_sai)]:
                    ws = writer.sheets[sheet]
                    ws.set_column('A:AG', 18) # Largura padrão
                    for i, val in enumerate(df_ref['DIAGNÓSTICO']):
                        if val != "Regular": ws.set_row(i + 1, None, fmt_red)

            st.download_button("📥 Baixar Planilha do Curador", output.getvalue(), "Apuração_Curador.xlsx")

        except Exception as e:
            st.error(f"Erro Crítico: {e}")

if __name__ == "__main__":
    main()
