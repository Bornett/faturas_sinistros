import pdfplumber
import pandas as pd
import streamlit as st
import re

st.title("📄 Leitor de Faturas Médicas")

# ---------------------------------------------------------
# 1. Extrair texto do PDF página a página
# ---------------------------------------------------------
def extrair_linhas(pdf_file):
    linhas = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            texto = page.extract_text()
            if texto:
                for linha in texto.split("\n"):
                    linhas.append(linha.strip())
    return linhas

# ---------------------------------------------------------
# 2. Extrair itens com regex flexível (6 a 9 valores)
# ---------------------------------------------------------
def extrair_itens(linhas):
    itens = []

    padrao = re.compile(
        r"(\d{2}/\d{2}/\d{4})\s+([A-Z0-9]+)\s+(.*?)\s+((?:\d+,\d+\s*){1,8})"
    )

    for linha in linhas:
        m = padrao.search(linha)
        if m:
            data = m.group(1)
            codigo = m.group(2)
            descricao = m.group(3)
            numeros = m.group(4).split()

            while len(numeros) < 6:
                numeros.append("0,00")
            while len(numeros) < 9:
                numeros.append("0,00")

            qtd, val_unit, val_siva, desconto, iva, val_civa = numeros[:6]

            itens.append([
                data, codigo, descricao,
                qtd, val_unit, val_siva, desconto, iva, val_civa
            ])

    return itens

# ---------------------------------------------------------
# 3. Extrair subtotais declarados (corrigido)
# ---------------------------------------------------------
def extrair_subtotais(linhas):
    subtotais = []

    for linha in linhas:
        if "Contagem" in linha and "valor" in linha and "€" in linha:
            nome_match = re.search(r"valor.*?€\)?\s*(.*)", linha)
            if not nome_match:
                continue
            resto = nome_match.group(1)

            numeros = re.findall(r"\d+,\d+", resto)
            if len(numeros) < 2:
                continue

            qtd_str = numeros[0]
            total_str = numeros[-1]

            subtotais.append({
                "Secção": resto.split(numeros[0])[0].strip(),
                "Qtd declarada": float(qtd_str.replace(",", ".")),
                "Total declarado (€)": float(total_str.replace(",", "."))
            })

    return pd.DataFrame(subtotais)

# ---------------------------------------------------------
# 4. Processar fatura
# ---------------------------------------------------------
def processar_fatura(pdf_file):
    linhas = extrair_linhas(pdf_file)

    st.write("🔍 **Texto extraído do PDF:**")
    st.write(linhas)

    itens = extrair_itens(linhas)
    st.write("🔍 **Itens identificados (regex):**")
    st.write(itens)

    if not itens:
        raise ValueError("Nenhum item foi identificado. O layout pode ter pequenas variações.")

    df = pd.DataFrame(itens, columns=[
        "Data", "Código", "Descrição", "Qtd", "Val.Unitário",
        "Val.Total(s/IVA)", "Desconto", "IVA", "Val.Total(c/IVA)"
    ])

    for col in ["Qtd", "Val.Unitário", "Val.Total(s/IVA)", "Desconto", "IVA", "Val.Total(c/IVA)"]:
        df[col] = df[col].str.replace(",", ".", regex=False)
        df[col] = pd.to_numeric(df[col], errors="coerce")

    def identificar_secao(desc):
        d = desc.upper()
        if "MATERIAL" in d:
            return "Material"
        if "EQUIPA" in d:
            return "Equipa Cirúrgica"
        if "FÁRMACOS" in d or "MEDI" in d:
            return "Fármacos"
        if "MCDT" in d:
            return "MCDT"
        return "Outros"

    df["Secção"] = df["Descrição"].apply(identificar_secao)

    resumo = df.groupby("Secção")["Val.Total(c/IVA)"].sum().reset_index()

    subtotais = extrair_subtotais(linhas)

    return df, resumo, subtotais

# ---------------------------------------------------------
# 5. Interface Streamlit
# ---------------------------------------------------------
uploaded_file = st.file_uploader("Carregue a fatura PDF", type="pdf")

if uploaded_file:
    try:
        df, resumo, subtotais = processar_fatura(uploaded_file)

        st.subheader("📑 Itens extraídos")
        st.dataframe(df)

        st.subheader("📊 Totais calculados por Secção")
        st.dataframe(resumo)

        st.subheader("📋 Subtotais declarados na fatura")
        st.dataframe(subtotais)

        st.bar_chart(resumo.set_index("Secção"))

    except Exception as e:
        st.error(f"⚠️ Erro ao processar a fatura: {str(e)}")
