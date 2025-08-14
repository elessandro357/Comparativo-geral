# app.py
# -*- coding: utf-8 -*-
"""
Painel Streamlit para processar "Comparativo geral.xlsx" e exibir dashboards
por secretaria (comparações, variações e detalhe), com formatação BR.
Suporta planilhas SEM as colunas 'Total 2024/2025' (gera TOTAL derivado).
"""
import io
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
from datetime import datetime

# ================== Config ==================
st.set_page_config(page_title="Folha - Comparativo 2024 x 2025", layout="wide")
st.title("📊 Painel de Folha (2024 x 2025)")
st.caption("Envie o arquivo **Comparativo geral.xlsx**. O painel evita dupla contagem e calcula TOTAL mesmo sem colunas 'Total'.")

# --- CSS: KPIs menores ---
st.markdown(
    """
    <style>
      div[data-testid="stMetric"] { padding: 0.25rem 0.5rem; }
      div[data-testid="stMetric"] [data-testid="stMetricLabel"] { font-size: 0.85rem; }
      div[data-testid="stMetric"] [data-testid="stMetricValue"] { font-size: 1.6rem; }
      div[data-testid="stMetric"] [data-testid="stMetricDelta"] svg { transform: scale(0.85); }
    </style>
    """,
    unsafe_allow_html=True,
)

# ================== Helpers ==================
PT_MONTHS = {"Jan":1,"Fev":2,"Mar":3,"Abr":4,"Mai":5,"Jun":6,"Jul":7,"Ago":8,"Set":9,"Out":10,"Nov":11,"Dez":12}
MONTH_ABBR = {v:k for k,v in PT_MONTHS.items()}
BASE_CATEGORIES = ["Agente Político","Eletivo","Comissionado","Contratado","Efetivo"]
TOT_LABEL = "Total"
ALL_CATEGORIES = BASE_CATEGORIES + [TOT_LABEL]

def extract_month(m):
    try:
        token = str(m).split("/")[0].strip()
        return PT_MONTHS.get(token, None)
    except Exception:
        return None

def br_currency(x):
    try:
        return f"R$ {float(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(x)

def br_percent(x):
    try:
        return f"{float(x)*100:,.2f}%".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(x)

def month_label(m:int) -> str:
    try:
        return MONTH_ABBR.get(int(m), str(m))
    except Exception:
        return str(m)

def safe_selectbox(label, options, key=None):
    if not options:
        st.warning(f"Não há opções para '{label}'. Verifique os filtros/dados.")
        return None
    return st.selectbox(label, options=options, index=0, key=key)

def ensure_all_secs(df, all_secs):
    present = set(df["secretaria"])
    missing = [s for s in all_secs if s not in present]
    if missing:
        add = pd.DataFrame({"secretaria": missing, "value": 0.0})
        df = pd.concat([df, add], ignore_index=True)
    return df

# ================== Transform ==================
@st.cache_data(show_spinner=False)
def transform_excel(file_bytes: bytes):
    df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0)
    df.columns = df.columns.str.replace(r"\s+", " ", regex=True).str.strip()

    # Detecta Secretaria
    sec_col = next((c for c in df.columns if c.lower().startswith("secretaria")), None)

    # Detecta Mês/Ano
    mes_col = None
    for c in df.columns:
        if c.replace(" ", "") in {"Mês/Ano","Mes/Ano"}:
            mes_col = c; break
    if mes_col is None:
        for alt in ["Mês/Ano","Mes/Ano","Mes/Ano "]:
            if alt in df.columns: mes_col = alt; break

    if sec_col is None or mes_col is None:
        raise ValueError("Planilha precisa ter colunas 'Secretaria' e 'Mês/Ano'.")

    df[sec_col] = df[sec_col].ffill()
    df = df[df[mes_col].notna()].copy()
    df["MesIndex"] = df[mes_col].apply(extract_month)

    def find_col(name):
        if name in df.columns: 
            return name
        target = name.lower().replace(" ", "")
        for c in df.columns:
            if c.lower().replace(" ", "") == target:
                return c
        return None

    # Mapa de colunas por ano (algumas podem não existir)
    cols_2024 = {cat: find_col(f"{cat} 2024") for cat in BASE_CATEGORIES}
    cols_2025 = {cat: find_col(f"{cat} 2025") for cat in BASE_CATEGORIES}
    col_total_2024 = find_col(f"{TOT_LABEL} 2024")
    col_total_2025 = find_col(f"{TOT_LABEL} 2025")
    has_total_cols = (col_total_2024 is not None and col_total_2025 is not None)

    # Constrói fato com as categorias base (sem Total)
    rows = []
    for _, r in df.iterrows():
        m = r["MesIndex"]
        if pd.isna(m): 
            continue
        for cat in BASE_CATEGORIES:
            c24 = cols_2024.get(cat)
            c25 = cols_2025.get(cat)
            if c24 and pd.notna(r.get(c24)):
                rows.append({"secretaria": str(r[sec_col]).strip(), "date": datetime(2024,int(m),1),
                             "year": 2024, "category": cat, "value": float(r[c24])})
            if c25 and pd.notna(r.get(c25)):
                rows.append({"secretaria": str(r[sec_col]).strip(), "date": datetime(2025,int(m),1),
                             "year": 2025, "category": cat, "value": float(r[c25])})

        # Se existir coluna Total no Excel, adiciona também
        if has_total_cols:
            if pd.notna(r.get(col_total_2024)):
                rows.append({"secretaria": str(r[sec_col]).strip(), "date": datetime(2024,int(m),1),
                             "year": 2024, "category": TOT_LABEL, "value": float(r[col_total_2024])})
            if pd.notna(r.get(col_total_2025)):
                rows.append({"secretaria": str(r[sec_col]).strip(), "date": datetime(2025,int(m),1),
                             "year": 2025, "category": TOT_LABEL, "value": float(r[col_total_2025])})

    fact = pd.DataFrame(rows)
    if fact.empty:
        raise ValueError("Após leitura, não há linhas com valores. Confirme os nomes das colunas e meses.")

    # Se NÃO houver colunas 'Total', gera TOTAL derivado somando categorias base
    if not has_total_cols:
        base_only = fact[fact["category"].isin(BASE_CATEGORIES)].copy()
        totals = (base_only.groupby(["secretaria","date","year"], as_index=False)["value"].sum()
                            .assign(category=TOT_LABEL))
        fact = pd.concat([fact, totals], ignore_index=True)

    # Ordenação de categorias
    fact["category"] = pd.Categorical(fact["category"], categories=ALL_CATEGORIES, ordered=True)

    # Dimensões
    dim_date = (fact[["date"]].drop_duplicates()
                .assign(year=lambda d: d["date"].dt.year, month=lambda d: d["date"].dt.month)
                .sort_values("date"))
    dim_secretaria = fact[["secretaria"]].drop_duplicates().sort_values("secretaria")

    # Comparativo 24 x 25 (inclui TOT_LABEL, original ou derivado)
    comp = (fact.pivot_table(index=["secretaria","date","category"], columns="year", values="value", aggfunc="sum")
                 .reset_index().rename_axis(None, axis=1)
                 .rename(columns={2024:"value_2024", 2025:"value_2025"}))
    comp["value_2024_f"] = comp["value_2024"].fillna(0.0)
    comp["value_2025_f"] = comp["value_2025"].fillna(0.0)
    comp["var_abs"] = comp["value_2025_f"] - comp["value_2024_f"]
    comp["var_pct"] = np.where(comp["value_2024_f"] == 0, np.nan, comp["var_abs"]/comp["value_2024_f"])
    comp["year"] = comp["date"].dt.year
    comp["month"] = comp["date"].dt.month

    return fact, dim_date, dim_secretaria, comp, has_total_cols

# ================== Upload ==================
uploaded = st.file_uploader("Envie o arquivo Excel (Comparativo geral.xlsx)", type=["xlsx"])
if not uploaded:
    st.info("Envie a planilha para liberar filtros e gráficos.")
    st.stop()

# ================== Processa ==================
try:
    fact, dim_date, dim_secretaria, comp, has_total_cols = transform_excel(uploaded.getvalue())
except Exception as e:
    st.error(f"Erro ao processar a planilha: {e}")
    st.stop()

# ================== Filtros ==================
st.sidebar.header("Filtros")
sec_opts = sorted(dim_secretaria["secretaria"].unique().tolist())
cat_opts = ALL_CATEGORIES  # inclui 'Total' (original ou derivado)
year_opts = sorted(fact["year"].unique().tolist())
month_opts = sorted(dim_date["month"].unique().tolist())
month_min, month_max = (min(month_opts), max(month_opts))

sec_sel = st.sidebar.multiselect("Secretaria (para visões gerais)", sec_opts, default=sec_opts)
cat_sel = st.sidebar.multiselect("Categoria", cat_opts, default=cat_opts)
year_sel = st.sidebar.multiselect("Ano", year_opts, default=year_opts)
month_range = st.sidebar.slider("Mês (1=Jan ... 12=Dez)", 1, 12, (month_min, month_max))

# Modo de total: se NÃO houver colunas 'Total', força soma de categorias
if has_total_cols:
    total_mode = st.sidebar.radio(
        "Cálculo do TOTAL",
        ["Usar coluna 'Total' (recomendado)", "Somar categorias selecionadas"],
        index=0,
        help="Evita dupla contagem quando 'Total' aparece junto com categorias."
    )
else:
    total_mode = "Somar categorias selecionadas"
    st.sidebar.info("Colunas 'Total' ausentes. O total será calculado pela soma das categorias.")

# Escala
scale_name = st.sidebar.selectbox("Escala do eixo Y", ["Reais (R$)", "Mil (R$ mil)", "Milhões (R$ mi)"], index=0)
scale_map = {"Reais (R$)":(1.0,"R$"), "Mil (R$ mil)":(1e3,"R$ mil"), "Milhões (R$ mi)":(1e6,"R$ mi")}
scale_div, scale_label = scale_map[scale_name]

# Toggles
show_labels = st.sidebar.checkbox("Mostrar rótulos de valores nos gráficos", value=False)
equal_axes = st.sidebar.checkbox("Fixar eixos iguais nos painéis duplos", value=True)

# Filtro base
mask = (
    fact["secretaria"].isin(sec_sel) &
    fact["category"].isin(cat_sel) &
    fact["year"].isin(year_sel) &
    fact["date"].dt.month.between(month_range[0], month_range[1])
)
filt = fact.loc[mask].copy()

# SOMAS (Por Secretaria/Por Categoria) – respeita modo de total
def make_total_df(base_df, selected_categories, mode, has_tot):
    df = base_df.copy()
    if mode.startswith("Usar coluna 'Total'") and has_tot:
        df = df[df["category"] == TOT_LABEL].copy()
    else:
        cats = [c for c in selected_categories if c != TOT_LABEL]
        df = df[df["category"].isin(cats)].copy()
    df["value_scaled"] = df["value"] / scale_div
    return df

filt_tot = make_total_df(filt, cat_sel, total_mode, has_total_cols)

# ================== KPIs ==================
kpi_2024 = filt_tot.loc[filt_tot["year"] == 2024, "value"].sum()
kpi_2025 = filt_tot.loc[filt_tot["year"] == 2025, "value"].sum()
kpi_var_abs = kpi_2025 - kpi_2024
kpi_var_pct = (kpi_var_abs / kpi_2024) if kpi_2024 else np.nan

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total 2024", br_currency(kpi_2024))
c2.metric("Total 2025", br_currency(kpi_2025))
c3.metric("Variação (R$)", br_currency(kpi_var_abs))
c4.metric("Variação (%)", br_percent(kpi_var_pct) if pd.notna(kpi_var_pct) else "-")

st.markdown("---")

# ================== Layout base ==================
def compact_layout(fig, height=320):
    fig.update_layout(
        height=height,
        margin=dict(l=20, r=20, t=40, b=20),
        hovermode="x unified",
        separators=",.",
        yaxis_tickformat=",.2f"
    )
    return fig

def label_value():
    return f"Valor ({scale_label})" if scale_label != "R$" else "Valor (R$)"

# ====== Abas ======
tabA, tabB, tabC, tabD = st.tabs([
    "Comparação por Secretaria (Mês a mês)",
    "Por Secretaria (Soma)",
    "Por Categoria (Soma)",
    "Δ por Secretaria (Evolução %)"
])

# ---------- Tab A: Comparação por Secretaria (Mês a mês) ----------
with tabA:
    st.caption("Escolha um mês e compare 2024 x 2025 lado a lado por secretaria (TOTAL) + ranking de Δ%.")
    meses_disponiveis = sorted(set(range(month_range[0], month_range[1]+1)))
    mes_sel = st.selectbox("Mês", options=meses_disponiveis, format_func=month_label, index=0)
    base_mes = filt_tot[filt_tot["date"].dt.month == mes_sel].copy()
    if base_mes.empty:
        st.info("Sem dados para o mês selecionado dentro do filtro.")
    else:
        all_secs = sorted(base_mes["secretaria"].unique().tolist())
        y24 = (base_mes[base_mes["year"]==2024].groupby("secretaria", as_index=False)["value"].sum())
        y25 = (base_mes[base_mes["year"]==2025].groupby("secretaria", as_index=False)["value"].sum())
        y24 = ensure_all_secs(y24, all_secs); y25 = ensure_all_secs(y25, all_secs)
        y24["value_scaled"] = y24["value"]/scale_div; y25["value_scaled"] = y25["value"]/scale_div
        y24["valor_br"] = y24["value"].apply(br_currency); y25["valor_br"] = y25["value"].apply(br_currency)

        col1, col2 = st.columns(2)
        with col1:
            fig_24 = px.bar(y24.sort_values("value_scaled", ascending=False),
                            x="secretaria", y="value_scaled", custom_data=["valor_br"],
                            labels={"value_scaled": label_value(), "secretaria":"Secretaria"},
                            title=f"{month_label(mes_sel)} / 2024 — Total")
            fig_24.update_traces(hovertemplate="Valor: %{customdata[0]}<extra></extra>",
                                 texttemplate="%{customdata[0]}" if show_labels else None,
                                 textposition="outside" if show_labels else "none",
                                 cliponaxis=False)
            if equal_axes:
                ymax = max(y24["value_scaled"].max(), y25["value_scaled"].max()) * 1.1
                fig_24.update_yaxes(range=[0, ymax])
            st.plotly_chart(compact_layout(fig_24, 380), use_container_width=True)

        with col2:
            fig_25 = px.bar(y25.sort_values("value_scaled", ascending=False),
                            x="secretaria", y="value_scaled", custom_data=["valor_br"],
                            labels={"value_scaled": label_value(), "secretaria":"Secretaria"},
                            title=f"{month_label(mes_sel)} / 2025 — Total")
            fig_25.update_traces(hovertemplate="Valor: %{customdata[0]}<extra></extra>",
                                 texttemplate="%{customdata[0]}" if show_labels else None,
                                 textposition="outside" if show_labels else "none",
                                 cliponaxis=False)
            if equal_axes:
                ymax = max(y24["value_scaled"].max(), y25["value_scaled"].max()) * 1.1
                fig_25.update_yaxes(range=[0, ymax])
            st.plotly_chart(compact_layout(fig_25, 380), use_container_width=True)

        # ===== Ranking Δ% no mês selecionado =====
        cmp = (y24.rename(columns={"value":"v24"})[["secretaria","v24"]]
                   .merge(y25.rename(columns={"value":"v25"})[["secretaria","v25"]], on="secretaria", how="outer")
                   .fillna(0.0))
        cmp["var_abs"] = cmp["v25"] - cmp["v24"]
        cmp["var_pct"] = np.where(cmp["v24"] == 0, np.nan, cmp["var_abs"]/cmp["v24"])

        # formatações
        cmp_fmt = cmp.copy()
        cmp_fmt["2024"] = cmp_fmt["v24"].apply(br_currency)
        cmp_fmt["2025"] = cmp_fmt["v25"].apply(br_currency)
        cmp_fmt["Δ (R$)"] = cmp_fmt["var_abs"].apply(br_currency)
        cmp_fmt["Δ (%)"] = cmp_fmt["var_pct"].apply(lambda x: br_percent(x) if pd.notna(x) else "-")

        colA, colB = st.columns(2)
        up = cmp.dropna(subset=["var_pct"]).sort_values("var_pct", ascending=False).head(5)
        down = cmp.dropna(subset=["var_pct"]).sort_values("var_pct", ascending=True).head(5)
        colA.markdown(f"**Top ↑ Aumentos (Δ%) — {month_label(mes_sel)}**")
        colA.dataframe(cmp_fmt.set_index("secretaria")
                       .loc[up["secretaria"], ["2024","2025","Δ (R$)","Δ (%)"]],
                       use_container_width=True)
        colB.markdown(f"**Top ↓ Reduções (Δ%) — {month_label(mes_sel)}**")
        colB.dataframe(cmp_fmt.set_index("secretaria")
                       .loc[down["secretaria"], ["2024","2025","Δ (R$)","Δ (%)"]],
                       use_container_width=True)

# ---------- Tab B: Por Secretaria (Soma) ----------
with tabB:
    st.caption("Totais do período filtrado por secretaria, com painéis independentes para 2024 e 2025.")
    if filt_tot.empty:
        st.info("Sem dados para os filtros selecionados.")
    else:
        all_secs = sorted(filt_tot["secretaria"].unique().tolist())
        sec24 = (filt_tot[filt_tot["year"]==2024].groupby("secretaria", as_index=False)["value"].sum())
        sec25 = (filt_tot[filt_tot["year"]==2025].groupby("secretaria", as_index=False)["value"].sum())
        sec24 = ensure_all_secs(sec24, all_secs); sec25 = ensure_all_secs(sec25, all_secs)
        sec24["value_scaled"] = sec24["value"]/scale_div; sec25["value_scaled"] = sec25["value"]/scale_div
        sec24["valor_br"] = sec24["value"].apply(br_currency); sec25["valor_br"] = sec25["value"].apply(br_currency)

        c1, c2 = st.columns(2)
        ymax = max(sec24["value_scaled"].max(), sec25["value_scaled"].max()) * 1.1 if equal_axes else None
        with c1:
            fig2a = px.bar(sec24.sort_values("value_scaled", ascending=False),
                           x="secretaria", y="value_scaled", custom_data=["valor_br"],
                           labels={"value_scaled": label_value(), "secretaria": "Secretaria"},
                           title="Soma por Secretaria — 2024")
            fig2a.update_traces(hovertemplate="Valor: %{customdata[0]}<extra></extra>",
                                texttemplate="%{customdata[0]}" if show_labels else None,
                                textposition="outside" if show_labels else "none",
                                cliponaxis=False)
            if ymax: fig2a.update_yaxes(range=[0, ymax])
            st.plotly_chart(compact_layout(fig2a, 380), use_container_width=True)
        with c2:
            fig2b = px.bar(sec25.sort_values("value_scaled", ascending=False),
                           x="secretaria", y="value_scaled", custom_data=["valor_br"],
                           labels={"value_scaled": label_value(), "secretaria": "Secretaria"},
                           title="Soma por Secretaria — 2025")
            fig2b.update_traces(hovertemplate="Valor: %{customdata[0]}<extra></extra>",
                                texttemplate="%{customdata[0]}" if show_labels else None,
                                textposition="outside" if show_labels else "none",
                                cliponaxis=False)
            if ymax: fig2b.update_yaxes(range=[0, ymax])
            st.plotly_chart(compact_layout(fig2b, 380), use_container_width=True)

# ---------- Tab C: Por Categoria (Soma) ----------
with tabC:
    st.caption("Totais do período filtrado por categoria **incluindo o Total calculado**, com painéis independentes para 2024 e 2025.")
    if filt.empty:
        st.info("Sem dados para os filtros selecionados.")
    else:
        # Base sem 'Total' para calcular o TOTAL corretamente
        base_cat = filt[filt["category"] != TOT_LABEL].copy()

        # Soma por categoria e por ano
        cat_by_year = base_cat.groupby(["year","category"], as_index=False)["value"].sum()

        # TOTAL calculado (soma das categorias base) por ano
        total_by_year = base_cat.groupby("year", as_index=False)["value"].sum().assign(category=TOT_LABEL)

        cat_all = pd.concat([cat_by_year, total_by_year], ignore_index=True)

        # Garante presença de todas as categorias base + Total em ambos os anos
        for y in [2024, 2025]:
            present = set(cat_all.loc[cat_all["year"]==y, "category"])
            for c in ALL_CATEGORIES:
                if c not in present:
                    cat_all = pd.concat([cat_all, pd.DataFrame({"year":[y], "category":[c], "value":[0.0]})], ignore_index=True)

        cat_all["value_scaled"] = cat_all["value"]/scale_div
        cat_all["valor_br"] = cat_all["value"].apply(br_currency)

        c1, c2 = st.columns(2)
        ymax = max(cat_all.loc[cat_all["year"]==2024, "value_scaled"].max(),
                   cat_all.loc[cat_all["year"]==2025, "value_scaled"].max()) * 1.1 if equal_axes else None

        with c1:
            d24 = cat_all[cat_all["year"]==2024].sort_values("value_scaled", ascending=False)
            fig3a = px.bar(d24, x="category", y="value_scaled", custom_data=["valor_br"],
                           labels={"value_scaled": label_value(), "category": "Categoria"},
                           title="Soma por Categoria — 2024")
            fig3a.update_traces(hovertemplate="Valor: %{customdata[0]}<extra></extra>",
                                texttemplate="%{customdata[0]}" if show_labels else None,
                                textposition="outside" if show_labels else "none",
                                cliponaxis=False)
            if ymax: fig3a.update_yaxes(range=[0, ymax])
            st.plotly_chart(compact_layout(fig3a, 380), use_container_width=True)

        with c2:
            d25 = cat_all[cat_all["year"]==2025].sort_values("value_scaled", ascending=False)
            fig3b = px.bar(d25, x="category", y="value_scaled", custom_data=["valor_br"],
                           labels={"value_scaled": label_value(), "category": "Categoria"},
                           title="Soma por Categoria — 2025")
            fig3b.update_traces(hovertemplate="Valor: %{customdata[0]}<extra></extra>",
                                texttemplate="%{customdata[0]}" if show_labels else None,
                                textposition="outside" if show_labels else "none",
                                cliponaxis=False)
            if ymax: fig3b.update_yaxes(range=[0, ymax])
            st.plotly_chart(compact_layout(fig3b, 380), use_container_width=True)

# ---------- Tab D: Δ% por Secretaria ----------
with tabD:
    st.caption("Evolução da diferença mensal **(2025 − 2024)** em **percentual** por secretaria (Total). Top 10 por variação média absoluta.")
    st.subheader("Evolução mensal da variação percentual (Δ%) — Total")
    comp_total = comp[(comp["category"] == TOT_LABEL) &
                      (comp["secretaria"].isin(sec_sel)) &
                      (comp["date"].dt.month.between(month_range[0], month_range[1]))].copy()
    if comp_total.empty:
        st.info("Sem dados para os filtros selecionados.")
    else:
        comp_total["month_label"] = comp_total["month"].apply(month_label)
        df_var = comp_total.groupby(["secretaria","date","month_label"], as_index=False)["var_pct"].mean()
        rank = (df_var.groupby("secretaria")["var_pct"].mean().abs()
                    .sort_values(ascending=False).head(10).index.tolist())
        show_df = df_var[df_var["secretaria"].isin(rank)].copy()
        fig4p = px.line(
            show_df.sort_values(["secretaria","date"]),
            x="month_label", y="var_pct", color="secretaria", markers=True,
            labels={"var_pct": "Δ (%)", "month_label": "Mês"},
            title="Δ (%) por Secretaria (Top 10 em amplitude média)"
        )
        fig4p.add_hline(y=0, line_dash="dot", opacity=0.5)
        fig4p.update_yaxes(tickformat=".2%")
        st.plotly_chart(compact_layout(fig4p, 420), use_container_width=True)

# ---------- Detalhe por Secretaria ----------
st.markdown("---")
st.subheader("🔎 Detalhe da Secretaria")
sec_one = safe_selectbox("Secretaria", options=sec_opts, key="sec_one_detail")
if sec_one:
    focus_cat = st.selectbox("Categoria (para séries 2024 x 2025)", options=ALL_CATEGORIES,
                             index=ALL_CATEGORIES.index(TOT_LABEL))
    mask_det = (
        (fact["secretaria"] == sec_one) &
        (fact["category"] == focus_cat) &
        (fact["year"].isin(year_sel)) &
        (fact["date"].dt.month.between(month_range[0], month_range[1]))
    )
    det = fact.loc[mask_det].copy()
    if det.empty:
        st.info("Sem dados para a secretaria/categoria selecionadas.")
    else:
        det["month"] = det["date"].dt.month
        det["month_lbl"] = det["month"].apply(month_label)
        det["value_scaled"] = det["value"] / scale_div

        s24 = det.loc[det["year"] == 2024, "value"].sum()
        s25 = det.loc[det["year"] == 2025, "value"].sum()
        svar = s25 - s24
        svarp = (svar / s24) if s24 else np.nan
        k1,k2,k3,k4 = st.columns(4)
        k1.metric(f"{focus_cat} 2024", br_currency(s24))
        k2.metric(f"{focus_cat} 2025", br_currency(s25))
        k3.metric("Δ (R$)", br_currency(svar))
        k4.metric("Δ (%)", br_percent(svarp) if pd.notna(svarp) else "-")

        # Linhas 2024 x 2025
        s_line = det.groupby(["year","month","month_lbl"], as_index=False)["value_scaled"].sum().sort_values(["year","month"])
        fig_d1 = px.line(
            s_line, x="month_lbl", y="value_scaled", color="year", markers=True,
            labels={"value_scaled": f"Valor ({scale_label})", "month_lbl":"Mês", "year":"Ano"},
            title=f"Evolução mensal - {sec_one} ({focus_cat})"
        )
        st.plotly_chart(compact_layout(fig_d1, 360), use_container_width=True)

        # Δ mensal (2025 - 2024)
        if focus_cat == TOT_LABEL:
            comp_det = comp[(comp["secretaria"]==sec_one) & (comp["category"]==TOT_LABEL) &
                            (comp["date"].dt.month.between(month_range[0], month_range[1]))].copy()
            dbar = comp_det[["month","date","var_abs"]].copy()
        else:
            pvt = (det.pivot_table(index=["month","date"], columns="year", values="value", aggfunc="sum")
                     .reset_index().rename(columns={2024:"v24", 2025:"v25"}))
            pvt["var_abs"] = pvt["v25"].fillna(0.0) - pvt["v24"].fillna(0.0)
            dbar = pvt[["month","date","var_abs"]].copy()
        dbar["month_lbl"] = dbar["month"].apply(month_label)
        dbar["var_scaled"] = dbar["var_abs"] / scale_div
        dbar["Δ (R$)"] = dbar["var_abs"].apply(br_currency)

        fig_d2 = px.bar(
            dbar.sort_values("month"),
            x="month_lbl", y="var_scaled", custom_data=["Δ (R$)"],
            labels={"var_scaled": f"Δ ({scale_label})", "month_lbl": "Mês"},
            title=f"Δ mensal (2025 - 2024) - {sec_one} ({focus_cat})"
        )
        fig_d2.add_hline(y=0, line_dash="dot", opacity=0.5)
        fig_d2.update_traces(hovertemplate="Δ: %{customdata[0]}<extra></extra>",
                             texttemplate="%{customdata[0]}" if show_labels else None,
                             textposition="outside" if show_labels else "none",
                             cliponaxis=False)
        st.plotly_chart(compact_layout(fig_d2, 340), use_container_width=True)

        # Tabela Δ consolidada (1 linha por mês)
        st.markdown("**Tabela Δ mensal (detalhe)**")
        tbl = (dbar.groupby("month", as_index=False)["var_abs"].sum()
                    .assign(**{"Mês": lambda x: x["month"].apply(month_label)})
                    [["Mês","var_abs"]].rename(columns={"var_abs":"Δ (R$)"}))
        tbl_fmt = tbl.copy(); tbl_fmt["Δ (R$)"] = tbl_fmt["Δ (R$)"].apply(br_currency)
        st.dataframe(tbl_fmt, use_container_width=True)
        st.download_button(
            "⬇️ Baixar CSV (Δ mensal - detalhe)",
            data=tbl.to_csv(index=False).encode("utf-8"),
            file_name=f"delta_mensal_{sec_one}_{focus_cat}.csv",
            mime="text/csv"
        )

st.markdown("---")
st.caption("Δ (delta) = variação. Painéis duplos mostram 2024 e 2025 lado a lado; habilite rótulos e eixos iguais no menu lateral.")
