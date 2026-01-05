import pdfplumber
import pandas as pd
import streamlit as st
import re
from io import BytesIO

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
# 2. Extrair dados do cliente e episódio
# ---------------------------------------------------------
def extrair_dados_cliente(linhas):
    nome = ""
    contribuinte = ""

    for linha in linhas:
        if linha.startswith("Nome:"):
            nome = linha.replace("Nome:", "").strip()
        if "Nr. Contribuinte:" in linha:
            contribuinte = linha.replace("Nr. Contribuinte:", "").strip()

    return {"Nome": nome, "Contribuinte": contribuinte}

def extrair_dados_episodio(linhas):
    apolice = ""
    acidente = ""
    ramo = ""

    for linha in linhas:
        if "Nr. Apólice:" in linha:
            apolice = linha.replace("Nr. Apólice:", "").strip()
        if "Data do Acidente:" in linha:
            acidente = linha.replace("Data do Acidente:", "").strip()
        if "Ramo / Motivo:" in linha:
            ramo = linha.replace("Ramo / Motivo:", "").strip()

    return {"Apólice": apolice, "Data do Acidente": acidente, "Ramo/Motivo": ramo}

# ---------------------------------------------------------
# 3. Extrair itens com regex flexível
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
# 4. Extrair subtotais declarados
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
# 5. Mapear agregadores TRON
# ---------------------------------------------------------
def mapear_agregadores(df_subtotais):
    mapa = {
        "29 - MATERIAL DE CONSUMO": "MAPFRE CONSUMO CIRURGICO",
        "23 - MATERIAL DE CONSUMO": "MAPFRE CONSUMO CIRURGICO",
        "21 - MATERIAL DE CONSUMO": "MAPFRE CONSUMO CIRURGICO",
        "22 - MATERIAL DE CONSUMO": "MAPFRE CONSUMO CIRURGICO",
        "24 - MATERIAL DE CONSUMO": "MAPFRE CONSUMO CIRURGICO",
        "19 - FÁRMACOS - OUTROS": "MAPFRE CONSUMO CIRURGICO",
        "EQUIPA CIRURGICA": "MAPFRE EQUIPA CIRURGICA",
        "MCDT": "MEIOS AUXILIARES DIAGNOSTICO",
        "11 - FÁRMACOS - MEDICAMENTOS": "FARMACIAS/MEDICAMENTOS",
        "PISO DE SALA": "MAPFRE BLOCO OPERATORIO"
    }

    df_subtotais["Agregador TRON"] = df_subtotais["Secção"].map(mapa).fillna("OUTROS")

    df_agregado = (
        df_subtotais.groupby("Agregador TRON")["Total declarado (€)"]
        .sum()
        .reset_index()
    )

    total_fatura = df_agregado["Total declarado (€)"].sum()

    df_agregado.loc[len(df_agregado.index)] = ["TOTAL DA FATURA", total_fatura]

    return df_agregado

# ---------------------------------------------------------
# 6. Exportar para Excel
# ---------------------------------------------------------
def exportar_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Agregadores TRON")
    return output.getvalue()

# ---------------------------------------------------------
# 7. Processar fatura
# ---------------------------------------------------------
def processar_fatura(pdf_file):
    linhas = extrair_linhas(pdf_file)

    dados_cliente = extrair_dados_cliente(linhas)
    dados_episodio = extrair_dados_episodio(linhas)

    itens = extrair_itens(linhas)
    subtotais = extrair_subtotais(linhas)
    agregados = mapear_agregadores(subtotais)

    df_itens = pd.DataFrame(itens, columns=[
        "Data", "Código", "Descrição", "Qtd", "Val.Unitário",
        "Val.Total(s/IVA)", "Desconto", "IVA", "Val.Total(c/IVA)"
    ])

    for col in ["Qtd", "Val.Unitário", "Val.Total(s/IVA)", "Desconto", "IVA", "Val.Total(c/IVA)"]:
        df_itens[col] = df_itens[col].str.replace(",", ".", regex=False)
        df_itens[col] = pd.to_numeric(df_itens[col], errors="coerce")

    return dados_cliente, dados_episodio, df_itens, subtotais, agregados

# ---------------------------------------------------------
# 8. Interface Streamlit
# ---------------------------------------------------------
uploaded_file = st.file_uploader("Carregue a fatura PDF", type="pdf")

if uploaded_file:
    try:
        dados_cliente, dados_episodio, df_itens, subtotais, agregados = processar_fatura(uploaded_file)

        st.subheader("👤 Dados do Cliente")
        st.table(pd.DataFrame([dados_cliente]))

        st.subheader("📘 Dados do Episódio")
        st.table(pd.DataFrame([dados_episodio]))

        st.subheader("📑 Itens extraídos")
        st.dataframe(df_itens)

        st.subheader("📋 Subtotais declarados na fatura")
        st.dataframe(subtotais)

        st.subheader("📦 Agregadores TRON")
        st.dataframe(agregados)

        excel_bytes = exportar_excel(agregados)
        st.download_button(
            label="📥 Exportar Agregadores TRON para Excel",
            data=excel_bytes,
            file_name="agregadores_tron.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        st.error(f"⚠️ Erro ao processar a fatura: {str(e)}")
