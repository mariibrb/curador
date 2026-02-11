import streamlit as st
import pandas as pd
import io

# Configuração da página - O Curador
st.set_page_config(page_title="Curador - Auditoria Fiscal", layout="wide")

def clean_numeric_col(df, col_name):
    """Limpeza técnica de colunas numéricas."""
    if col_name in df.columns:
        s = df[col_name].astype(str).str.replace(r'\s+', '', regex=True)
        s = s.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        df[col_name] = pd.to_numeric(s, errors='coerce').fillna(0.0)
    return df

def auditoria_icms_ipi(row, tipo='saida'):
    """
    Motor de Auditoria (ICMS, ST, IPI).
    Retorna: Erro, Ação Cliente e Ação Domínio.
    """
    # Dados Gerais
    cfop = str(row['CFOP']).strip().replace('.', '')
    # CST ICMS (2 dígitos)
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

    # ==============================================================================
    # 1. AUDITORIA ICMS PRÓPRIO
    # ==============================================================================
    
    # Regra 6403 (Saída)
    if tipo == 'saida' and cfop == '6403' and vlr_icms == 0:
        erros.append("ICMS Próprio não destacado no 6403.")
        cliente.append("Destacar ICMS Próprio (Substituto Tributário).")
        dominio.append("Habilitar ICMS Próprio em operações de ST no Acumulador.")

    # Regra Base de Cálculo (Frete compõe base?)
    # BC ICMS Teórica = Valor Item + Frete - Desconto
    if bc_icms > 0:
        base_teorica = vlr_prod + frete - desc
        if (base_teorica - bc_icms) > 1.0: # Margem de R$ 1,00
            erros.append("Base de ICMS menor que (Produto + Frete).")
            cliente.append("Verificar se Frete está somando na Base do ICMS.")
            dominio.append("Marcar 'Frete compõe base de ICMS' no acumulador.")

    # Regra Interestadual (SP)
    if tipo == 'saida' and cfop.startswith('6'):
        reg_7 = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'RN', 'RO', 'RR', 'SE', 'TO']
        if uf_dest in reg_7 and aliq_icms not in [7.0, 4.0]:
            erros.append(f"Alíquota {aliq_icms}% incorreta p/ {uf_dest} (Meta: 7%).")
            cliente.append(f"Ajustar alíquota interestadual p/ {uf_dest}.")

    # ==============================================================================
    # 2. AUDITORIA ICMS ST
    # ==============================================================================
    
    # CSTs que OBRIGAM ST (10, 30, 70)
    cst_st_mandatorio = ['10', '30', '70']
    # CSTs que ACEITAM ST (Inclui o 90)
    cst_st_permitido = ['10', '30', '70', '90']
    # CFOPs que indicam Substituição (Gerador)
    cfop_st = ['5401', '5403', '6401', '6403', '5405', '6405']

    if cst in cst_st_mandatorio and vlr_st == 0:
        erros.append(f"CST {cst} exige ST (zerado).")
        cliente.append("Informar ST.")
        dominio.append("Marcar 'Gera guia ST' no acumulador (Estadual).")
    
    # CST 90 só é erro se o CFOP for de ST e não tiver valor
    elif cst == '90' and vlr_st == 0 and cfop in cfop_st:
        erros.append(f"CST 90 em CFOP {cfop} exige ST.")
        cliente.append("Destacar ST.")
        dominio.append("Revisar configuração de ST no acumulador.")

    elif vlr_st > 0 and cst not in cst_st_permitido and cst != '60':
        erros.append(f"ST indevido p/ CST {cst}.")
        cliente.append("Zerar ST ou trocar CST.")

    # ==============================================================================
    # 3. AUDITORIA IPI
    # ==============================================================================
    
    # Venda Industrial
    if cfop in ['5101', '6101'] and vlr_ipi == 0:
        erros.append("Venda industrial sem IPI.")
        cliente.append("Destacar IPI.")
        dominio.append("Configurar IPI no produto/acumulador (Imposto 2).")
    
    # Compra Industrial (Crédito)
    if tipo == 'entrada' and cfop in ['1101', '2101'] and vlr_ipi == 0:
        erros.append("Compra industrial sem crédito IPI.")
        dominio.append("Verificar se acumulador apropria crédito IPI.")

    return pd.Series({
        'DIAGNÓSTICO': " | ".join(erros) if erros else "Regular",
        'AÇÃO_DOMINIO': " | ".join(dominio) if dominio else "-",
        'AÇÃO_CLIENTE': " | ".join(cliente) if cliente else "-"
    })

def reordenar_colunas(df, tipo='saida'):
    """Move as colunas de auditoria para o início."""
    cols = list(df.columns)
    # Ident
