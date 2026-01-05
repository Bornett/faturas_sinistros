import pdfplumber
import pandas as pd
import streamlit as st

def extrair_tabelas(pdf_file):
    linhas = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    linhas.append(row)
    return linhas

def processar_fatura(pdf_file):
    dados = extrair_tabelas(pdf_file)
    df = pd.DataFrame(dados, columns=[
        "Data", "Código", "Descrição", "Qtd", "Val.Unitário",
        "Val.Total(s/IVA)", "Desconto", "IVA", "Val.Total(c/IVA)"
    ])
    df = df.dropna(how="all")
    for col in ["Qtd", "Val.Unitário", "Val.Total(s/IVA)", "Val.Total(c/IVA)"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    def identificar_secao(desc):
        if desc is None:
            return "Outros"
        desc = desc.upper()
        if "MATERIAL DE CONSUMO" in desc:
            return "Material de Consumo"
        if "EQUIPA CIRURGICA" in desc:
            return "Equipa Cirúrgica"
        if "FÁRMACOS" in desc or "MEDI" in desc:
            return "Fármacos"
        if "MCDT" in desc:
            return "MCDT"
        return "Outros"

    df["Secção"] = df["Descrição"].apply(identificar_secao)
    resumo = df.groupby("Secção")["Val.Total(c/IVA)"].sum().reset_index()
    return df, resumo

st.title("📑 Leitor de Faturas Médicas")

uploaded_file = st.file_uploader("Carregue a fatura PDF", type="pdf")

if uploaded_file:
    df, resumo = processar_fatura(uploaded_file)
    st.subheader("📄 Conteúdo extraído")
    st.dataframe(df)
    st.subheader("📊 Totais por Secção")
    st.dataframe(resumo)
    st.bar_chart(resumo.set_index("Secção"))
