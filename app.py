import pdfplumber
import pandas as pd
import streamlit as st
import re
from io import BytesIO

st.title("📄 Leitor de Faturas Médicas — TRON Automático")

# ---------------------------------------------------------
# 1. Extrair texto do PDF (linhas + texto completo)
# ---------------------------------------------------------
def extrair_linhas_e_texto(pdf_file):
    linhas = []
    textos_paginas = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            texto = page.extract_text()
            if texto:
                textos_paginas.append(texto)
                for linha in texto.split("\n"):
                    linhas.append(linha.strip())
    texto_completo = "\n".join(textos_paginas)
    return linhas, texto_completo

# ---------------------------------------------------------
# 2. Extrair dados do cliente
# ---------------------------------------------------------
def extrair_dados_cliente(texto):
    nome = ""
    contribuinte = ""

    m_nome = re.search(r"Nome:\s*(.+)", texto)
    if m_nome:
        nome = m_nome.group(1).strip()

    contribs = re.findall(r"Nr\. Contribuinte:\s*([\d]+)", texto)
    if contribs:
        contribuinte = contribs[-1].strip()

    return {"Nome": nome, "Contribuinte": contribuinte}

# ---------------------------------------------------------
# 3. Extrair Dados Gerais
# ---------------------------------------------------------
def extrair_dados_gerais(texto):
    dados = {
        "Apólice": "",
        "Data do Acidente": "",
        "Ramo/Motivo": "",
        "Número da Fatura": "",
        "Data da Fatura": "",
        "Número do Processo": ""
    }

    m_apolice = re.search(r"Nr\. Apólice:\s*([0-9]+)", texto)
    if m_apolice:
        dados["Apólice"] = m_apolice.group(1).strip()

    m_acidente = re.search(r"Data do Acidente:\s*([0-9/]+)", texto)
    if m_acidente:
        dados["Data do Acidente"] = m_acidente.group(1).strip()

    m_ramo = re.search(r"Ramo\s*/\s*Motivo:\s*([A-Za-zÀ-ÿ]+)", texto)
    if m_ramo:
        dados["Ramo/Motivo"] = m_ramo.group(1).strip()

    m_fatura = re.search(r"Fatura\s+FT\s+([A-Z0-9/]+)", texto)
    if m_fatura:
        dados["Número da Fatura"] = m_fatura.group(1).strip()

    m_emissao = re.search(r"Data de emissão:\s*([0-9\-]+)", texto)
    if m_emissao:
        dados["Data da Fatura"] = m_emissao.group(1).strip()

    m_processo = re.search(r"Tipo\s*/\s*Número:\s*([0-9]+)", texto)
    if m_processo:
        dados["Número do Processo"] = m_processo.group(1).strip()

    return dados

# ---------------------------------------------------------
# 4. Extrair itens (linhas completas)
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
# 5. Extrair subtotais declarados
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
# 6. Extrair bloco MCDT
# ---------------------------------------------------------
def extrair_bloco_mcdt(linhas):
    inicio = None
    fim = None

    for i, linha in enumerate(linhas):
        if "MCDT" in linha and inicio is None:
            inicio = i
        if "Contagem e valor (€) MCDT" in linha:
            fim = i
            break

    if inicio is None or fim is None:
        return []

    return linhas[inicio:fim]

# ---------------------------------------------------------
# 7. Classificação dos itens MCDT
# ---------------------------------------------------------
def classificar_item_mcdt(descricao):
    desc = descricao.upper()

    if "ECG" in desc:
        return "MEIOS AUXILIAR DIAGNOST - OUTROS"
    if "RX" in desc:
        return "MEIOS AUXILIAR DIAG RX"
    if "TC" in desc:
        return "MEIOS AUX DIAGNOST TAC"
    if "RM" in desc:
        return "MEIOS AUX DIAGNOST RMN"
    if "ECO" in desc:
        return "MEIOS AUX DIAGNOST ECOGRAFIA"
    if "EMG" in desc:
        return "MEIOS AUX DIAGNOST EMG"

    return "ENFERMAGEM CONTRATADA"

# ---------------------------------------------------------
# 8. Códigos TRON
# ---------------------------------------------------------
codigos_tron = {
    "MEIOS AUXILIAR DIAGNOST - OUTROS": "217",
    "MEIOS AUXILIAR DIAG RX": "218",
    "MEIOS AUX DIAGNOST TAC": "237",
    "MEIOS AUX DIAGNOST RMN": "238",
    "MEIOS AUX DIAGNOST ECOGRAFIA": "239",
    "MEIOS AUX DIAGNOST EMG": "240",
    "FARMACIAS/MEDICAMENTOS": "206",
    "CONSULTAS AT. PERMANENTE": "251",
    "ENFERMAGEM CONTRATADA": "204",
    "TOTAL DA FATURA": ""
}

# ---------------------------------------------------------
# 9. Mapear agregadores TRON
# ---------------------------------------------------------
def mapear_agregadores(df_subtotais, df_itens, linhas):

    linhas_agregadas = []

    # --- 1) Extrair bloco MCDT ---
    bloco_mcdt = extrair_bloco_mcdt(linhas)

    itens_mcdt = []
    for linha in bloco_mcdt:
        m = re.search(
            r"(\d{2}/\d{2}/\d{4})\s+([A-Z0-9]+)\s+(.*?)\s+\d+,\d+\s+(\d+,\d+)",
            linha
        )
        if m:
            descricao = m.group(3).strip()
            valor = float(m.group(4).replace(",", "."))
            itens_mcdt.append((descricao, valor))

    # Classificar cada item MCDT
    for descricao, valor in itens_mcdt:
        categoria = classificar_item_mcdt(descricao)
        codigo = codigos_tron[categoria]

        linhas_agregadas.append({
            "Descrição TRON": categoria,
            "Código TRON": codigo,
            "Total declarado (€)": valor
        })

    # --- 2) Subtotais das outras secções ---
    mapa = {
        "CONSULTA URGÊNCIA": "CONSULTAS AT. PERMANENTE",
        "11 - FÁRMACOS": "FARMACIAS/MEDICAMENTOS",

        # ✔ Como escolheste: 21/23/29 → 204
        "23 - MATERIAL": "ENFERMAGEM CONTRATADA",
        "21 - MATERIAL": "ENFERMAGEM CONTRATADA",
        "29 - MATERIAL": "ENFERMAGEM CONTRATADA",
    }

    for _, row in df_subtotais.iterrows():
        secao = row["Secção"]
        total = row["Total declarado (€)"]

        if "MCDT" in secao.upper():
            continue

        destino = "ENFERMAGEM CONTRATADA"
        for chave, val in mapa.items():
            if chave in secao.upper():
                destino = val
                break

        codigo = codigos_tron.get(destino, "")

        linhas_agregadas.append({
            "Descrição TRON": destino,
            "Código TRON": codigo,
            "Total declarado (€)": total
        })

    df_final = pd.DataFrame(linhas_agregadas)

    df_final = df_final.groupby(["Descrição TRON", "Código TRON"], as_index=False).sum()

    total_fatura = df_final["Total declarado (€)"].sum()
    df_final.loc[len(df_final.index)] = ["TOTAL DA FATURA", "", total_fatura]

    return df_final

# ---------------------------------------------------------
# 10. Exportar para Excel
# ---------------------------------------------------------
def exportar_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Agregadores TRON")
    return output.getvalue()

# ---------------------------------------------------------
# 11. Processar fatura
# ---------------------------------------------------------
def processar_fatura(pdf_file):
    linhas, texto = extrair_linhas_e_texto(pdf_file)

    dados_cliente = extrair_dados_cliente(texto)
    dados_gerais = extrair_dados_gerais(texto)

    itens = extrair_itens(linhas)
    df_itens = pd.DataFrame(itens, columns=[
        "Data", "Código", "Descrição", "Qtd", "Val.Unitário",
        "Val.Total(s/IVA)", "Desconto", "IVA", "Val.Total(c/IVA)"
    ])

    if not df_itens.empty:
        for col in ["Qtd", "Val.Unitário", "Val.Total(s/IVA)", "Desconto", "IVA", "Val.Total(c/IVA)"]:
            df_itens[col] = df_itens[col].astype(str).str.replace(",", ".", regex=False)
            df_itens[col] = pd.to_numeric(df_itens[col], errors="coerce")

    subtotais = extrair_subtotais(linhas)
    agregados = mapear_agregadores(subtotais, df_itens, linhas)

    return dados_cliente, dados_gerais, df_itens, subtotais, agregados

# ---------------------------------------------------------
# 12. Interface Streamlit
# ---------------------------------------------------------
uploaded_file = st.file_uploader("Carregue a fatura PDF", type="pdf")

if uploaded_file:
    try:
        dados_cliente, dados_gerais, df_itens, subtotais, agregados = processar_fatura(uploaded_file)

        st.subheader("👤 Dados do Cliente")
        st.table(pd.DataFrame([dados_cliente]))

        st.subheader("📘 Dados Gerais")
        for campo, valor in dados_gerais.items():
            st.markdown(f"**{campo}:** {valor}")

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
