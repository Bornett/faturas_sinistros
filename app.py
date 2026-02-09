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
# 5. Extrair subtotais declarados
# ---------------------------------------------------------
def extrair_subtotais(linhas):
    subtotais = []

    # Padrão EXATO das linhas de subtotal
    padrao = re.compile(
        r"Contagem e\s+valor\s+\(€\)\s+(.*?)\s+(\d+,\d+)\s*$"
    )

    for linha in linhas:
        m = padrao.search(linha)
        if m:
            secao = m.group(1).strip()
            total_str = m.group(2).strip()

            total = float(total_str.replace(",", "."))

            subtotais.append({
                "Secção": secao,
                "Total declarado (€)": total
            })

    return pd.DataFrame(subtotais)



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
    "MAPFRE CONSUMO CIRURGICO": "247",
    "MAPFRE EQUIPA CIRURGICA": "243",
    "MEIOS AUXILIARES DIAGNOSTICO": "217",
    "FARMACIAS/MEDICAMENTOS": "206",
    "MAPFRE BLOCO OPERATORIO": "245",

    "CONSULTAS ESPECIALIDADE": "252",
    "CONSULTAS AT. PERMANENTE": "251",
    "MATERIAL ORTOPEDICO": "213",

    "MEIOS AUX DIAGNOST RMN": "238",
    "MEIOS AUXILIAR DIAG RX": "218",
    "MEIOS AUX DIAGNOST EMG": "240",
    "MEIOS AUX DIAGNOST TAC": "237",
    "MEIOS AUX DIAGNOST ECOGRAFIA": "239",

    "ENFERMAGEM CONTRATADA": "204",

    "OUTROS": "",
    "TOTAL DA FATURA": ""
}

# ---------------------------------------------------------
# Função para detetar subtipo MCDT
# ---------------------------------------------------------
def detetar_subtipo_mcdt(descricao):
    desc = descricao.upper()

    # Ordem importa: siglas mais longas primeiro
    if re.search(r"\bEMG\b", desc):
        return "EMG"
    if re.search(r"\bECO\b", desc):
        return "ECO"
    if re.search(r"\bTC\b", desc):
        return "TC"
    if re.search(r"\bRX\b", desc):
        return "RX"
    if re.search(r"\bRM\b", desc):
        return "RM"

    return None


# ---------------------------------------------------------
# 6. Mapear agregadores TRON (com MCDT desdobrado)
# ---------------------------------------------------------
def mapear_agregadores(df_subtotais, df_itens):
    mapa = {
        # ENFERMAGEM CONTRATADA — secções 21, 22, 29
        "21 - MATERIAL DE CONSUMO": "ENFERMAGEM CONTRATADA",
        "22 - MATERIAL DE CONSUMO": "ENFERMAGEM CONTRATADA",
        "29 - MATERIAL DE CONSUMO": "ENFERMAGEM CONTRATADA",

        # Outras regras já existentes
        "EQUIPA CIRURGICA": "MAPFRE EQUIPA CIRURGICA",
        "11 - FÁRMACOS - MEDICAMENTOS": "FARMACIAS/MEDICAMENTOS",
        "PISO DE SALA": "MAPFRE BLOCO OPERATORIO",

        "CONSULTA EXTERNA": "CONSULTAS ESPECIALIDADE",
        "CONSULTA URGÊNCIA": "CONSULTAS AT. PERMANENTE",

        # Material ortopédico
        "28 - MATERIAL DE CONSUMO CLINICO - MAT. ORTOPEDICO": "MATERIAL ORTOPEDICO",
        "CLINICO - MAT. ORTOPEDICO": "MATERIAL ORTOPEDICO",
        "MAT. ORTOPEDICO": "MATERIAL ORTOPEDICO",
        "28 - MATERIAL DE CON": "MATERIAL ORTOPEDICO",
        "28 - MATERIAL DE CONSUMO": "MATERIAL ORTOPEDICO",

        # MCDT genérico
        "MCDT": "MEIOS AUXILIARES DIAGNOSTICO"
    }

    linhas_agregadas = []

    for _, row in df_subtotais.iterrows():
        secao = row["Secção"]
        total = row["Total declarado (€)"]

        # ---------------------------------------------------------
        # 1) Secções 21, 22, 29 → ENFERMAGEM CONTRATADA
        # (regex seguro: só apanha 21, 22, 29)
        # ---------------------------------------------------------
        if re.match(r"^(21|22|29)\b", secao):
            linhas_agregadas.append({
                "Descrição TRON": "ENFERMAGEM CONTRATADA",
                "Código TRON": codigos_tron["ENFERMAGEM CONTRATADA"],
                "Total declarado (€)": total
            })
            continue

        # ---------------------------------------------------------
        # 2) Caso especial: MCDT
        # ---------------------------------------------------------
        if "MCDT" in secao.upper():

            subtotais_mcdt = {}
            total_penso = 0

            for _, item in df_itens.iterrows():
                descricao = item["Descrição"].upper()
                valor = item["Val.Total(s/IVA)"]

                # 2A) Itens MCDT com "PENSO" → ENFERMAGEM CONTRATADA
                if "PENSO" in descricao:
                    total_penso += valor
                    continue

                # 2B) Subtipos RM/RX/TC/ECO/EMG
                subtipo = detetar_subtipo_mcdt(descricao)
                if subtipo:
                    subtotais_mcdt.setdefault(subtipo, 0)
                    subtotais_mcdt[subtipo] += valor

            # 2C) Adicionar PENSO → ENFERMAGEM CONTRATADA
            if total_penso > 0:
                linhas_agregadas.append({
                    "Descrição TRON": "ENFERMAGEM CONTRATADA",
                    "Código TRON": codigos_tron["ENFERMAGEM CONTRATADA"],
                    "Total declarado (€)": total_penso
                })

            # 2D) Se não houver subtipo → vai para genérico
            if not subtotais_mcdt:
                linhas_agregadas.append({
                    "Descrição TRON": "MEIOS AUXILIARES DIAGNOSTICO",
                    "Código TRON": codigos_tron["MEIOS AUXILIARES DIAGNOSTICO"],
                    "Total declarado (€)": total - total_penso
                })
                continue

            # 2E) Criar linhas TRON por subtipo
            for subtipo, valor in subtotais_mcdt.items():
                agregador = mcdt_subtipos[subtipo]
                codigo = codigos_tron[agregador]

                linhas_agregadas.append({
                    "Descrição TRON": agregador,
                    "Código TRON": codigo,
                    "Total declarado (€)": valor
                })

            continue

        # ---------------------------------------------------------
        # 3) Caso normal
        # ---------------------------------------------------------
        agregador = mapa.get(secao, "OUTROS")
        codigo = codigos_tron.get(agregador, "TR999")

        linhas_agregadas.append({
            "Descrição TRON": agregador,
            "Código TRON": codigo,
            "Total declarado (€)": total
        })

    # ---------------------------------------------------------
    # 4) Agrupamento final por Código TRON
    # ---------------------------------------------------------
    df_final = pd.DataFrame(linhas_agregadas)

    df_final = (
        df_final.groupby(["Descrição TRON", "Código TRON"], as_index=False)
                .agg({"Total declarado (€)": "sum"})
    )

    # ---------------------------------------------------------
    # 5) Total da fatura
    # ---------------------------------------------------------
    total_fatura = df_final["Total declarado (€)"].sum()
    df_final.loc[len(df_final.index)] = ["TOTAL DA FATURA", "", total_fatura]

    return df_final




# ---------------------------------------------------------
# 7. Exportar para Excel
# ---------------------------------------------------------
def exportar_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Agregadores TRON")
    return output.getvalue()

# ---------------------------------------------------------
# 8. Processar fatura
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

    for col in ["Qtd", "Val.Unitário", "Val.Total(s/IVA)", "Desconto", "IVA", "Val.Total(c/IVA)"]:
        df_itens[col] = df_itens[col].str.replace(",", ".", regex=False)
        df_itens[col] = pd.to_numeric(df_itens[col], errors="coerce")

    subtotais = extrair_subtotais(linhas)
    agregados = mapear_agregadores(subtotais, df_itens)

    return dados_cliente, dados_gerais, df_itens, subtotais, agregados

# ---------------------------------------------------------
# 9. Interface Streamlit
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







