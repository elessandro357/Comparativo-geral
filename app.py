# app.py
# -*- coding: utf-8 -*-
"""
Página Streamlit para processar "Comparativo geral.xlsx" e exibir dashboards
interativos com formatação de moeda brasileira e gráficos compactos.

Como rodar:
  pip install streamlit pandas numpy plotly openpyxl
  streamlit run app.py
"""
import io
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
from datetime import datetime

# ------------------ Config ------------------
st.set_page_config(page_title="Folha - Comparativo 2024 x 2025", layout="wide")
st.title("📊 Painel de Folha (2024 x 2025)")
st.caption("Envie o arquivo **Comparativo geral.xlsx** para processar e explorar com filtros interativos.")

# ------------------ Helpers ------------------
PT_MONTHS = {
    "Jan": 1, "Fev": 2, "Mar": 3, "Abr": 4, "Mai": 5, "Jun": 6,
    "Jul": 7, "Ago": 8, "Set": 9, "Out": 10, "Nov": 11, "Dez": 12
}
CATEGORIES = ["Agente Político", "Eletivo", "Comissionado", "Contratado", "Efetivo", "Total"]

def extract_month(m):
    try:
        token = str(m).split("/")[0].strip()
        return PT_MONTHS.get(token, None)
    except Exception:
        return None

def br_currency(x):
    """Formata número para moeda brasileira: R$ 1.234.567,89."""
    try:
        return f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return x

def br_percent(x):
    """Formata número para percentual brasileiro: 12,34%."""
    try:
        return f"{x*100:,.2f}%".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return x

@st.cache_data
def transform_excel(file_bytes: bytes):
    # Lê a primeira planilha do Excel
    df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0)

    # Validação mínima
    if "Secretaria " not in df.columns or "Mês/Ano" not in df.columns:
        raise ValueError("Planilha não possui colunas esperadas: 'Secretaria ' e 'Mês/Ano'.")

    # Prepara base
    df["Secretaria "] = df["Secretaria "].ffill()
    df = df[df["Mês/Ano"].notna()].copy()
    df["MesIndex"] = df["Mês/Ano"].apply(extract_month)

    col_map_2024 = {
        "Agente Político": "Agente Político 2024",
        "Eletivo": "Eletivo 2024",
        "Comissionado": "Comissionado 2024",
        "Contratado": "Contratado 2024",
        "Efetivo": "Efetivo 2024",
        "Total": "Total 2024",
    }
    col_map_2025 = {k: v.replace("2024", "2025") for k, v in col_map_2024.items()}

    # Normaliza para uma tabela fato
    rows = []
    for _, row in df.iterrows():
        mes = row["MesIndex"]
        if pd.isna(mes):
            continue
        for cat in CATEGORIES:
            v2024 = row.get(col_map_2024[cat], np.nan)
            v2025 = row.get(col_map_2025[cat], np.nan)
            if pd.notna(v2024):
                rows.append({
                    "secretaria": str(row["Secretaria "]).strip(),
                    "date": datetime(2024, int(mes), 1),
                    "year": 2024,
                    "category": cat,
                    "value": float(v2024),
                })
            if pd.notna(v2025):
                rows.append({
                    "secretaria": str(row["Secretaria "]).strip(),
                    "date": datetime(2025, i
