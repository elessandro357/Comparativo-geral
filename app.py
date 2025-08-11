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
                    "date": datetime(2025, int(mes), 1),
                    "year": 2025,
                    "category": cat,
                    "value": float(v2025),
                })

    fact = pd.DataFrame(rows).dropna(subset=["date"])
    fact["category"] = pd.Categorical(fact["category"], categories=CATEGORIES, ordered=True)

    # Dimensões auxiliares
    dim_date = (
        fact[["date"]].drop_duplicates().assign(
            year=lambda d: d["date"].dt.year,
            month=lambda d: d["date"].dt.month,
            month_name=lambda d: d["date"].dt.strftime("%b/%Y")
        ).sort_values("date")
    )
    dim_secretaria = fact[["secretaria"]].drop_duplicates().sort_values("secretaria")
    dim_category = pd.DataFrame({"category": pd.Categorical(CATEGORIES, categories=CATEGORIES, ordered=True)})

    # Comparativo 24 vs 25
    comp = (
        fact.pivot_table(index=["secretaria", "date", "category"], columns="year", values="value", aggfunc="sum")
        .reset_index()
        .rename_axis(None, axis=1)
        .rename(columns={2024: "value_2024", 2025: "value_2025"})
    )
    comp["var_abs"] = comp["value_2025"] - comp["value_2024"]
    comp["var_pct"] = np.where(comp["value_2024"] == 0, np.nan, comp["var_abs"] / comp["value_2024"])

    return fact, dim_date, dim_secretaria, dim_category, comp

# ------------------ Upload ------------------
uploaded = st.file_uploader("Envie o arquivo Excel (Comparativo geral.xlsx)", type=["xlsx"])

if not uploaded:
    st.info("Envie a planilha para liberar os filtros e dashboards.")
    st.stop()

# ------------------ Transform ------------------
try:
    fact, dim_date, dim_secretaria, dim_category, comp = transform_excel(uploaded.getvalue())
except Exception as e:
    st.error(f"Erro ao processar a planilha: {e}")
    st.stop()

# ------------------ Filtros ------------------
st.sidebar.header("Filtros")
sec_opts = sorted(dim_secretaria["secretaria"].unique().tolist())
cat_opts = CATEGORIES
year_opts = sorted(fact["year"].unique().tolist())
month_opts = sorted(dim_date["month"].unique().tolist())

sec_sel = st.sidebar.multiselect("Secretaria", sec_opts, default=sec_opts)
cat_sel = st.sidebar.multiselect("Categoria", cat_opts, default=cat_opts)
year_sel = st.sidebar.multiselect("Ano", year_opts, default=year_opts)

month_min, month_max = (min(month_opts) if month_opts else 1, max(month_opts) if month_opts else 12)
month_range = st.sidebar.slider("Mês (1=Jan ... 12=Dez)", 1, 12, (month_min, month_max))

mask = (
    fact["secretaria"].isin(sec_sel) &
    fact["category"].isin(cat_sel) &
    fact["year"].isin(year_sel) &
    fact["date"].dt.month.between(month_range[0], month_range[1])
)
filt = fact.loc[mask].copy()

# ------------------ KPIs ------------------
kpi_2024 = filt.loc[filt["year"] == 2024, "value"].sum()
kpi_2025 = filt.loc[filt["year"] == 2025, "value"].sum()
kpi_var_abs = kpi_2025 - kpi_2024
kpi_var_pct = (kpi_var_abs / kpi_2024) if kpi_2024 else np.nan

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total 2024", br_currency(kpi_2024))
c2.metric("Total 2025", br_currency(kpi_2025))
c3.metric("Variação (R$)", br_currency(kpi_var_abs))
c4.metric("Variação (%)", br_percent(kpi_var_pct) if pd.notna(kpi_var_pct) else "-")

st.markdown("---")

# ------------------ Gráficos ------------------
# parâmetros comuns de layout para gráficos compactos
def compact_layout(fig):
    fig.update_layout(
        height=300,
        margin=dict(l=20, r=20, t=40, b=20),
        hovermode="x unified"
    )
    return fig

tab1, tab2, tab3, tab4 = st.tabs(["Evolução Mensal", "Por Secretaria", "Por Categoria", "Tabela Comparativa"])

with tab1:
    if not filt.empty:
        evo = (
            filt.assign(month=lambda d: d["date"].dt.month)
                .groupby(["year", "month"], as_index=False)["value"].sum()
                .sort_values(["year", "month"])
        )
        # Hover em BRL
        evo["valor_br"] = evo["value"].apply(br_currency)
        fig = px.line(
            evo, x="month", y="value", color="year", markers=True,
            labels={"value": "Valor", "month": "Mês", "year": "Ano"},
            title="Evolução Mensal (Soma dos Filtros)"
        )
        # customdata para hover em BR
        fig.update_traces(
            customdata=np.stack([evo["valor_br"]], axis=-1),
            hovertemplate="Valor: %{customdata[0]}<extra></extra>"
        )
        st.plotly_chart(compact_layout(fig), use_container_width=True)
    else:
        st.info("Sem dados para os filtros selecionados.")

with tab2:
    if not filt.empty:
        by_sec = filt.groupby(["year", "secretaria"], as_index=False)["value"].sum()
        by_sec["valor_br"] = by_sec["value"].apply(br_currency)
        fig2 = px.bar(
            by_sec, x="secretaria", y="value", color="year", barmode="group",
            labels={"value": "Valor", "secretaria": "Secretaria", "year": "Ano"},
            title="Soma por Secretaria"
        )
        fig2.update_traces(
            customdata=np.stack([by_sec["valor_br"]], axis=-1),
            hovertemplate="Valor: %{customdata[0]}<extra></extra>"
        )
        st.plotly_chart(compact_layout(fig2), use_container_width=True)
    else:
        st.info("Sem dados para os filtros selecionados.")

with tab3:
    if not filt.empty:
        by_cat = filt.groupby(["year", "category"], as_index=False)["value"].sum()
        by_cat["valor_br"] = by_cat["value"].apply(br_currency)
        fig3 = px.bar(
            by_cat, x="category", y="value", color="year", barmode="group",
            labels={"value": "Valor", "category": "Categoria", "year": "Ano"},
            title="Soma por Categoria"
        )
        fig3.update_traces(
            customdata=np.stack([by_cat["valor_br"]], axis=-1),
            hovertemplate="Valor: %{customdata[0]}<extra></extra>"
        )
        st.plotly_chart(compact_layout(fig3), use_container_width=True)
    else:
        st.info("Sem dados para os filtros selecionados.")

with tab4:
    # Tabela comparativa 2024 vs 2025 (por Secretaria × Categoria × Mês)
    comp_filt = comp[
        (comp["secretaria"].isin(sec_sel)) &
        (comp["category"].isin(cat_sel)) &
        (comp["date"].dt.year.isin(year_sel)) &
        (comp["date"].dt.month.between(month_range[0], month_range[1]))
    ].copy()
    comp_filt["Mês/Ano"] = comp_filt["date"].dt.strftime("%m/%Y")
    comp_show = comp_filt[[
        "secretaria", "category", "Mês/Ano", "value_2024", "value_2025", "var_abs", "var_pct"
    ]].sort_values(["secretaria", "category", "Mês/Ano"])

    # Formatação BR
    comp_fmt = comp_show.copy()
    for c in ["value_2024", "value_2025", "var_abs"]:
        comp_fmt[c] = comp_fmt[c].apply(br_currency)
    comp_fmt["var_pct"] = comp_fmt["var_pct"].apply(lambda x: br_percent(x) if pd.notna(x) else "-")

    st.dataframe(comp_fmt, use_container_width=True)

    # Download do CSV sem formatação (para análise/BI), obedecendo filtros
    csv = comp_show.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Baixar CSV (comparativo filtrado)",
        data=csv,
        file_name="comparativo_filtrado.csv",
        mime="text/csv"
    )

st.markdown("---")
st.caption("Dica: ajuste os filtros na lateral para refinar os indicadores e gráficos. KPIs, tabela e hovers usam moeda em formato brasileiro.")
