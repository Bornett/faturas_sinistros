import pdfplumber
import pandas as pd
import streamlit as st
import re
from io import BytesIO

st.title("📄 Leitor de Faturas Médicas")

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
# 2. Detetar tipologia de fatura
# ---------------------------------------------------------
def detectar_tipologia(texto):
    if "Nr. Beneficiário" in texto or "Data de vencimento" in texto:
        return "nova"
    return "antiga"

# ---------------------------------------------------------
# 3. Extrair dados do cliente - tipologia ANTIGA
# ---------------------------------------------------------
def extrair_dados_cliente_antiga(texto):
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
# 4. Extrair dados do cliente - tipologia NOVA
# ---------------------------------------------------------
def extrair_dados_cliente_nova(texto):
    nome = ""
    contribuinte = ""

    m_nome = re.search(r"Nome:\s*(.+)", texto)
    if m_nome:
        nome = m_nome.group(1).strip()

    m_contrib = re.search(r"Dados do cliente[\s\S]*?Nr\. Contribuinte:\s*([0-9]+)", texto)
    if m_contrib:
        contribuinte = m_contrib.group(1).strip()

    return {"Nome": nome, "Contribuinte": contribuinte}

# ---------------------------------------------------------
# 5. Extrair Dados Gerais - tipologia ANTIGA
# ---------------------------------------------------------
def extrair_dados_gerais_antiga(texto):
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
# 6. Extrair Dados Gerais - tipologia NOVA
# ---------------------------------------------------------
def extrair_dados_gerais_nova(texto):
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

    m_fatura = re.search(r"Fatura\s+[A-Z]{1,2}\s+([A-Z0-9/]+)", texto)
    if m_fatura:
        dados["Número da Fatura"] = m_fatura.group(1).strip()

    m_vencimento = re.search(r"Data de vencimento\s*([0-9/]+)", texto)
    if m_vencimento:
        dados["Data da Fatura"] = m_vencimento.group(1).strip()

    m_processo = re.search(r"Nr\. Beneficiário:\s*([0-9]+)", texto)
    if m_processo:
        dados["Número do Processo"] = m_processo.group(1).strip()

    return dados

# ---------------------------------------------------------
# 7. Extrair itens (comum às duas tipologias)
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
# 8. Extrair subtotais declarados - tipologia ANTIGA
# ---------------------------------------------------------
def extrair_subtotais_antiga(linhas):
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
# 9. Extrair subtotais declarados - tipologia NOVA
# ---------------------------------------------------------
def extrair_subtotais_nova(linhas):
    subtotais = []

    for linha in linhas:
        if "Sub-Total" in linha:
            numeros = re.findall(r"\d[\d\s]*,\d{2}", linha)
            if len(numeros) >= 1:
                total_str = numeros[-1].replace(" ", "")
                subtotais.append({
                    "Secção": "Sub-Total",
                    "Total declarado (€)": float(total_str.replace(",", "."))
                })

    return pd.DataFrame(subtotais)

# ---------------------------------------------------------
# 10. Mapear agregadores TRON - tipologia ANTIGA
# ---------------------------------------------------------
def mapear_agregadores_antiga(df_subtotais):
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
# 11. Mapear agregadores TRON - tipologia NOVA
# ---------------------------------------------------------
def mapear_agregadores_nova(df_subtotais):
    if df_subtotais.empty:
        return pd.DataFrame([{"Agregador TRON": "TOTAL DA FATURA", "Total declarado (€)": 0}])

    total_fatura = df_subtotais["Total declarado (€)"].sum()
    return pd.DataFrame([
        {"Agregador TRON": "TOTAL DA FATURA", "Total declarado (€)": total_fatura}
    ])

# ---------------------------------------------------------
# 12. Exportar para Excel
# ---------------------------------------------------------
def exportar_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Agregadores TRON")
    return output.getvalue()

# ---------------------------------------------------------
# 13. Processar fatura
# ---------------------------------------------------------
def processar_fatura(pdf_file):
    linhas, texto = extrair_linhas_e_texto(pdf_file)
    tipo = detectar_tipologia(texto)

    if tipo == "nova":
        dados_cliente = extrair_dados_cliente_nova(texto)
        dados_gerais = extrair_dados_gerais_nova(texto)
        subtotais = extrair_subtotais_nova(linhas)
        agregados = mapear_agregadores_nova(subtotais)
    else:
        dados_cliente = extrair_dados_cliente_antiga(texto)
        dados_gerais = extrair_dados_gerais_antiga(texto)
        subtotais = extrair_subtotais_antiga(linhas)
        agregados = mapear_agregadores_antiga(subtotais)

    itens = extrair_itens(linhas)

    df_itens = pd.DataFrame(itens, columns=[
        "Data", "Código", "Descrição", "Qtd", "Val.Unitário",
        "Val.Total(s/IVA)", "Desconto", "IVA", "Val.Total(c/IVA)"
    ])

    for col in ["Qtd", "Val.Unitário", "Val.Total(s/IVA)", "Desconto", "IVA", "Val.Total(c/IVA)"]:
        df_itens[col] = df_itens[col].str.replace(",", ".", regex=False)
        df_itens[col] = pd.to_numeric(df_itens[col], errors="coerce")

    return tipo, dados_cliente, dados_gerais, df_itens, subtotais, agregados

# ---------------------------------------------------------
# 14. Interface Streamlit
# ---------------------------------------------------------
uploaded_file = st.file_uploader("Carregue a fatura PDF", type="pdf")

if uploaded_file:
    try:
        tipo, dados_cliente, dados_gerais, df_itens, subtotais, agregados = processar_fatura(uploaded_file)

        st.subheader("👤 Dados do Cliente")
        st.table(pd.DataFrame([dados_cliente]))

        st.subheader("📘 Dados Gerais")
        st.markdown(f"**Tipologia detetada:** {tipo.upper()}")
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
