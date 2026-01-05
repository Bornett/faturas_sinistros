import pdfplumber
import pandas as pd
import streamlit as st

st.title("📄 Leitor de Faturas Médicas")

# --------------------------
# 1. Extrair tabelas do PDF
# --------------------------
def extrair_tabelas(pdf_file):
    linhas = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    # Guardar apenas linhas com conteúdo
                    if row and any(cell is not None and cell.strip() != "" for cell in row):
                        linhas.append(row)
    return linhas

# --------------------------
# 2. Processar fatura
# --------------------------
def processar_fatura(pdf_file):
    dados = extrair_tabelas(pdf_file)

    # Filtrar apenas linhas com exatamente 9 colunas (linhas de itens reais)
    dados_validos = [row for row in dados if len(row) == 9]

    if not dados_validos:
        raise ValueError("Não foram encontradas linhas com 9 colunas no PDF. A estrutura pode ser diferente.")

    df = pd.DataFrame(dados_validos, columns=[
        "Data", "Código", "Descrição", "Qtd", "Val.Unitário",
        "Val.Total(s/IVA)", "Desconto", "IVA", "Val.Total(c/IVA)"
    ])

    # Converter números com vírgula e remover espaços
    for col in ["Qtd", "Val.Unitário", "Val.Total(s/IVA)", "Val.Total(c/IVA)"]:
        df[col] = (
            df[col]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .str.replace(" ", "", regex=False)
        )
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Identificar secções
    def identificar_secao(desc):
        if not isinstance(desc, str):
            return "Outros"
        d = desc.upper()
        if "MATERIAL DE CONSUMO" in d:
            return "Material de Consumo"
        if "EQUIPA CIRURGICA" in d:
            return "Equipa Cirúrgica"
        if "FÁRMACOS" in d or "MEDI" in d:
            return "Fármacos"
        if "MCDT" in d:
            return "MCDT"
        return "Outros"

    df["Secção"] = df["Descrição"].apply(identificar_secao)

    resumo = df.groupby("Secção")["Val.Total(c/IVA)"].sum().reset_index()

    return df, resumo

# --------------------------
# 3. Interface Streamlit
# --------------------------
uploaded_file = st.file_uploader("Carregue a fatura PDF", type="pdf")

if uploaded_file:
    try:
        df, resumo = processar_fatura(uploaded_file)

        st.subheader("📑 Conteúdo extraído")
        st.dataframe(df)

        st.subheader("📊 Totais por Secção")
        st.dataframe(resumo)

        st.bar_chart(resumo.set_index("Secção"))

    except Exception as e:
        st.error(f"⚠️ Erro ao processar a fatura: {str(e)}")



