import pdfplumber
import pandas as pd
import re

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
# 3. Extrair dados gerais
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
# 4. Extrair itens
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
# 5. Extrair subtotais (versão 100% robusta)
# ---------------------------------------------------------
def extrair_subtotais(linhas):
    subtotais = []
    buffer = ""

    for linha in linhas:

        # Junta linhas partidas "Contagem e" + "valor (€) ..."
        if re.search(r"\bContagem\s+e\b", linha):
            buffer = linha
            continue

        if buffer and "valor (€)" in linha:
            linha = buffer + " " + linha
            buffer = ""

        # 1) Caso clássico: total no fim da linha
        m1 = re.search(
            r"Contagem\s+e\s+valor\s+\(€\)\s+(.*?)\s+(\d+,\d+)\s*$",
            linha
        )
        if m1:
            secao = normalizar_secao(m1.group(1).strip())
            total = float(m1.group(2).replace(",", "."))
            subtotais.append({"Secção": secao, "Total declarado (€)": total})
            continue

        # 2) Caso Boavista: total NÃO está no fim da linha
        # Exemplo:
        # Contagem e valor (€) 29 - MATERIAL DE CONSUMO ... 142,00 ... 50,38 ...
        m2 = re.search(
            r"Contagem\s+e\s+valor\s+\(€\)\s+(.*?)(\s+\d+,\d+)",
            linha
        )
        if m2:
            secao = normalizar_secao(m2.group(1).strip())

            # Procurar o primeiro número da linha (é o total declarado)
            numeros = re.findall(r"\d+,\d+", linha)
            if numeros:
                total = float(numeros[0].replace(",", "."))
                subtotais.append({"Secção": secao, "Total declarado (€)": total})
            continue

    return pd.DataFrame(subtotais)

# ---------------------------------------------------------
# 6. Normalização automática das secções
# ---------------------------------------------------------
def normalizar_secao(secao):

    s = secao.upper()

    # MATERIAL DE CONSUMO (21/22/23/29)
    if "29 - MATERIAL" in s:
        return "29 - MATERIAL DE CONSUMO"
    if "23 - MATERIAL" in s:
        return "23 - MATERIAL DE CONSUMO"
    if "21 - MATERIAL" in s:
        return "21 - MATERIAL DE CONSUMO"
    if "22 - MATERIAL" in s:
        return "22 - MATERIAL DE CONSUMO"

    # CONSULTAS
    if "CONSULTA URG" in s:
        return "CONSULTA URGÊNCIA"
    if "CONSULTA EXTERNA" in s:
        return "CONSULTA EXTERNA"

    # MATERIAL ORTOPÉDICO
    if "MAT.ORTOP" in s or "ORTOP" in s:
        return "28 - MATERIAL DE CONSUMO CLINICO - MAT. ORTOPEDICO"

    # EQUIPA CIRÚRGICA
    if "EQUIPA CIR" in s:
        return "EQUIPA CIRURGICA"

    # MCDT
    if "MCDT" in s:
        return "MCDT"

    return secao
# ---------------------------------------------------------
# Subtipos MCDT → Agregadores TRON
# ---------------------------------------------------------
mcdt_subtipos = {
    "RM": "MEIOS AUX DIAGNOST RMN",
    "RX": "MEIOS AUXILIAR DIAG RX",
    "EMG": "MEIOS AUX DIAGNOST EMG",
    "TC": "MEIOS AUX DIAGNOST TAC",
    "ECO": "MEIOS AUX DIAGNOST ECOGRAFIA"
}

# ---------------------------------------------------------
# Códigos TRON
# ---------------------------------------------------------
codigos_tron = {
    "ENFERMAGEM CONTRATADA": "204",
    "FARMACIAS/MEDICAMENTOS": "206",
    "MATERIAL ORTOPEDICO": "213",
    "MEIOS AUXILIAR DIAG RX": "218",
    "MEIOS AUX DIAGNOST TAC": "237",
    "MEIOS AUX DIAGNOST RMN": "238",
    "MEIOS AUX DIAGNOST ECOGRAFIA": "239",
    "MEIOS AUX DIAGNOST EMG": "240",
    "MAPFRE EQUIPA CIRURGICA": "243",
    "MAPFRE BLOCO OPERATORIO": "245",
    "MAPFRE CONSUMO CIRURGICO": "247",
    "CONSULTAS AT. PERMANENTE": "251",
    "CONSULTAS ESPECIALIDADE": "252",
    "OUTROS": "TR999",
    "TOTAL DA FATURA": ""
}

# ---------------------------------------------------------
# Detetar subtipo MCDT
# ---------------------------------------------------------
def detetar_subtipo_mcdt(descricao):
    desc = descricao.upper()

    if "EMG" in desc:
        return "EMG"
    if "ECO" in desc:
        return "ECO"
    if "TC" in desc:
        return "TC"
    if "RX" in desc:
        return "RX"
    if "RM" in desc:
        return "RM"

    return None


# ---------------------------------------------------------
# 7. Mapear agregadores TRON (inclui ENFERMAGEM + MCDT)
# ---------------------------------------------------------
def mapear_agregadores(df_subtotais, df_itens):

    # Mapa base para secções normalizadas
    mapa = {
        "29 - MATERIAL DE CONSUMO": "ENFERMAGEM CONTRATADA",
        "23 - MATERIAL DE CONSUMO": "ENFERMAGEM CONTRATADA",
        "21 - MATERIAL DE CONSUMO": "ENFERMAGEM CONTRATADA",
        "22 - MATERIAL DE CONSUMO": "ENFERMAGEM CONTRATADA",

        "11 - FÁRMACOS - MEDICAMENTOS": "FARMACIAS/MEDICAMENTOS",

        "CONSULTA URGÊNCIA": "CONSULTAS AT. PERMANENTE",
        "CONSULTA EXTERNA": "CONSULTAS ESPECIALIDADE",

        "28 - MATERIAL DE CONSUMO CLINICO - MAT. ORTOPEDICO": "MATERIAL ORTOPEDICO",

        "EQUIPA CIRURGICA": "MAPFRE EQUIPA CIRURGICA",
        "PISO DE SALA": "MAPFRE BLOCO OPERATORIO",

        "MCDT": "MCDT"   # tratado separadamente
    }

    linhas_agregadas = []

    for _, row in df_subtotais.iterrows():
        secao = row["Secção"]
        total = row["Total declarado (€)"]

        # ---------------------------------------------
        # CASO ESPECIAL: MCDT
        # ---------------------------------------------
        if secao == "MCDT":

            soma_subtipos = 0.0
            subtotais_mcdt = {}

            for _, item in df_itens.iterrows():
                descricao = item["Descrição"]
                val = item["Val.Total(s/IVA)"]

                if pd.isna(val):
                    continue

                subtipo = detetar_subtipo_mcdt(descricao)

                if subtipo:
                    subtotais_mcdt.setdefault(subtipo, 0.0)
                    subtotais_mcdt[subtipo] += float(val)
                    soma_subtipos += float(val)

            # Criar linhas TRON para RM/RX/TC/EMG/ECO
            for subtipo, valor in subtotais_mcdt.items():
                agregador = mcdt_subtipos[subtipo]
                codigo = codigos_tron[agregador]

                linhas_agregadas.append({
                    "Descrição TRON": agregador,
                    "Código TRON": codigo,
                    "Total declarado (€)": round(valor, 2)
                })

            # RESTO DO MCDT → ENFERMAGEM CONTRATADA
            restante = round(total - soma_subtipos, 2)

            if restante > 0.01:
                linhas_agregadas.append({
                    "Descrição TRON": "ENFERMAGEM CONTRATADA",
                    "Código TRON": codigos_tron["ENFERMAGEM CONTRATADA"],
                    "Total declarado (€)": restante
                })

            continue

        # ---------------------------------------------
        # CASO NORMAL
        # ---------------------------------------------
        agregador = mapa.get(secao, "OUTROS")
        codigo = codigos_tron.get(agregador, "TR999")

        linhas_agregadas.append({
            "Descrição TRON": agregador,
            "Código TRON": codigo,
            "Total declarado (€)": total
        })

    # ---------------------------------------------
    # AGRUPAR E SOMAR
    # ---------------------------------------------
    df_final = pd.DataFrame(linhas_agregadas)

    df_final = (
        df_final.groupby(["Descrição TRON", "Código TRON"], as_index=False)
                .agg({"Total declarado (€)": "sum"})
    )

    # TOTAL DA FATURA
    total_fatura = df_final["Total declarado (€)"].sum()
    df_final.loc[len(df_final.index)] = ["TOTAL DA FATURA", "", total_fatura]

    return df_final
import streamlit as st
from io import BytesIO

# ---------------------------------------------------------
# 8. Processar fatura (liga BLOCO 1 + BLOCO 2)
# ---------------------------------------------------------
def processar_fatura(pdf_file):
    # Extrair texto e linhas
    linhas, texto = extrair_linhas_e_texto(pdf_file)

    # Extrair dados
    dados_cliente = extrair_dados_cliente(texto)
    dados_gerais = extrair_dados_gerais(texto)

    # Extrair itens
    itens = extrair_itens(linhas)
    df_itens = pd.DataFrame(itens, columns=[
        "Data", "Código", "Descrição", "Qtd", "Val.Unitário",
        "Val.Total(s/IVA)", "Desconto", "IVA", "Val.Total(c/IVA)"
    ])

    # Converter valores numéricos
    for col in ["Qtd", "Val.Unitário", "Val.Total(s/IVA)", "Desconto", "IVA", "Val.Total(c/IVA)"]:
        df_itens[col] = df_itens[col].str.replace(",", ".", regex=False)
        df_itens[col] = pd.to_numeric(df_itens[col], errors="coerce")

    # Extrair subtotais robustos
    subtotais = extrair_subtotais(linhas)

    # Mapear agregadores TRON
    agregados = mapear_agregadores(subtotais, df_itens)

    return dados_cliente, dados_gerais, df_itens, subtotais, agregados


# ---------------------------------------------------------
# 9. Exportar para Excel
# ---------------------------------------------------------
def exportar_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Agregadores TRON")
    return output.getvalue()


# ---------------------------------------------------------
# 10. Interface Streamlit
# ---------------------------------------------------------
st.title("📄 Leitor de Faturas Médicas — TRON Automático")

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

