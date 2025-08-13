# app.py
# -*- coding: utf-8 -*-
"""
Painel Streamlit para processar "Comparativo geral.xlsx" e exibir dashboards
por secretaria (evolução, variações, heatmap e detalhe), com formatação BR.

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

# ================== Config geral ==================
st.set_page_config(page_title="Folha - Comparativo 2024 x 2025", layout="wide")
st.title("📊 Painel de Folha (2024 x 2025)")
st.caption("Envie o arquivo **Comparativo geral.xlsx** para explorar por secretaria, com evolução, variações e heatmap.")

# ================== Helpers ==================
PT_MONTHS = {"Jan":1,"Fev":2,"Mar":3,"Abr":4,"Mai":5,"Jun":6,"Jul":7,"Ago":8,"Set":9,"Out":10,"Nov":11,"Dez":12}
MONTH_ABBR = {v:k for k,v in PT_MONTHS.items()}
CATEGORIES = ["Agente Político", "Eletivo", "Comissionado", "Contratado", "Efetivo", "Total"]

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
        return x

def br_percent(x):
    try:
        return f"{float(x)*100:,.2f}%".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return x

def month_label(m:int) -> str:
    return MONTH_ABBR.get(int(m), str(m))

@st.cache_data(show_spinner=False)
def transform_excel(file_bytes: bytes):
    # Lê a primeira planilha
    df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0)
    # Normaliza nomes de colunas
    df.columns = df.columns.str.strip()
    # Detecta a coluna de secretaria de forma robusta
    sec_col = next((c for c in df.columns if c.lower().startswith("secretaria")), None)
    if sec_col is None or "Mês/Ano" not in df.columns:
        raise ValueError("Planilha precisa conter as colunas 'Secretaria' e 'Mês/Ano'.")

    # Prepara base
    df[sec_col] = df[sec_col].ffill()
    df = df[df["Mês/Ano"].notna()].copy()
    df["MesIndex"] = df["Mês/Ano"].apply(extract_month)

    # Mapeia colunas 2024/2025 (robusto a espaços)
    base_2024 = {
        "Agente Político": "Agente Político 2024",
        "Eletivo": "Eletivo 2024",
        "Comissionado": "Comissionado 2024",
        "Contratado": "Contratado 2024",
        "Efetivo": "Efetivo 2024",
        "Total": "Total 2024",
    }
    base_2025 = {k: v.replace("2024", "2025") for k, v in base_2024.items()}

    # Tabela fato
    rows = []
    for _, row in df.iterrows():
        mes = row["MesIndex"]
        if pd.isna(mes): 
            continue
        for cat in CATEGORIES:
            v24 = row.get(base_2024[cat], np.nan)
            v25 = row.get(base_2025[cat], np.nan)
            if pd.notna(v24):
                rows.append({
                    "secretaria": str(row[sec_col]).strip(),
                    "date": datetime(2024, int(mes), 1),
                    "year": 2024,
                    "category": cat,
                    "value": float(v24)
                })
            if pd.notna(v25):
                rows.append({
                    "secretaria": str(row[sec_col]).strip(),
                    "date": datetime(2025, int(mes), 1),
                    "year": 2025,
                    "category": cat,
                    "value": float(v25)
                })

    fact = pd.DataFrame(rows).dropna(subset=["date"])
    fact["category"] = pd.Categorical(fact["category"], categories=CATEGORIES, ordered=True)

    # Dimensões auxiliares
    dim_date = (
        fact[["date"]].drop_duplicates().assign(
            year=lambda d: d["date"].dt.year,
            month=lambda d: d["date"].dt.month
        ).sort_values("date")
    )
    dim_secretaria = fact[["secretaria"]].drop_duplicates().sort_values("secretaria")

    # Comparativo 2024 x 2025 por (secretaria, date, category)
    comp = (
        fact.pivot_table(index=["secretaria","date","category"], columns="year", values="value", aggfunc="sum")
            .reset_index().rename_axis(None, axis=1)
            .rename(columns={2024:"value_2024", 2025:"value_2025"})
    )
    # Variações robustas (base 0 trata valores ausentes)
    comp["value_2024_f"] = comp["value_2024"].fillna(0.0)
    comp["value_2025_f"] = comp["value_2025"].fillna(0.0)
    comp["var_abs"] = comp["value_2025_f"] - comp["value_2024_f"]
    comp["var_pct"] = np.where(comp["value_2024_f"] == 0, np.nan, comp["var_abs"] / comp["value_2024_f"])
    comp["year"] = comp["date"].dt.year
    comp["month"] = comp["date"].dt.month

    return fact, dim_date, dim_secretaria, comp

# ================== Upload ==================
uploaded = st.file_uploader("Envie o arquivo Excel (Comparativo geral.xlsx)", type=["xlsx"])
if not uploaded:
    st.info("Envie a planilha para liberar filtros e dashboards.")
    st.stop()

# ================== Transform ==================
try:
    fact, dim_date, dim_secretaria, comp = transform_excel(uploaded.getvalue())
except Exception as e:
    st.error(f"Erro ao processar a planilha: {e}")
    st.stop()

# ================== Filtros ==================
st.sidebar.header("Filtros")
sec_opts = sorted(dim_secretaria["secretaria"].unique().tolist())
cat_opts = CATEGORIES
year_opts = sorted(fact["year"].unique().tolist())
month_opts = sorted(dim_date["month"].unique().tolist())
month_min, month_max = (min(month_opts) if month_opts else 1, max(month_opts) if month_opts else 12)

sec_sel = st.sidebar.multiselect("Secretaria (para soma/visões gerais)", sec_opts, default=sec_opts)
cat_sel = st.sidebar.multiselect("Categoria", cat_opts, default=cat_opts)
year_sel = st.sidebar.multiselect("Ano", year_opts, default=year_opts)
month_range = st.sidebar.slider("Mês (1=Jan ... 12=Dez)", 1, 12, (month_min, month_max))

# Escala do eixo Y
scale_name = st.sidebar.selectbox("Escala do eixo Y", ["Reais (R$)", "Mil (R$ mil)", "Milhões (R$ mi)"], index=0)
scale_map = {"Reais (R$)":(1.0,"R$"), "Mil (R$ mil)":(1e3,"R$ mil"), "Milhões (R$ mi)":(1e6,"R$ mi")}
scale_div, scale_label = scale_map[scale_name]

# Filtro base (para KPIs e visões gerais)
mask = (
    fact["secretaria"].isin(sec_sel) &
    fact["category"].isin(cat_sel) &
    fact["year"].isin(year_sel) &
    fact["date"].dt.month.between(month_range[0], month_range[1])
)
filt = fact.loc[mask].copy()
filt["value_scaled"] = filt["value"] / scale_div

# ================== KPIs gerais ==================
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

# ================== Funções de gráfico ==================
def compact_layout(fig, height=300):
    fig.update_layout(
        height=height,
        margin=dict(l=20, r=20, t=40, b=20),
        hovermode="x unified",
        separators=",.",  # decimal=',' milhares='.'
        yaxis_tickformat=",.2f",
        yaxis_tickprefix="R$ " if "mi" not in scale_label and "mil" not in scale_label else ""
    )
    return fig

def label_value():
    return f"Valor ({scale_label})" if scale_label != "R$" else "Valor (R$)"

# ================== Abas ==================
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Evolução Mensal (Geral)", 
    "Por Secretaria (Soma)", 
    "Por Categoria (Soma)", 
    "Δ por Secretaria (Evolução)", 
    "Heatmap (Δ por mês)", 
    "Detalhe da Secretaria"
])

# ---------- Tab 1: Evolução Mensal (Geral) ----------
with tab1:
    if not filt.empty:
        evo = (
            filt.assign(month=lambda d: d["date"].dt.month)
                .groupby(["year","month"], as_index=False)[["value","value_scaled"]].sum()
                .sort_values(["year","month"])
        )
        evo["valor_br"] = evo["value"].apply(br_currency)
        evo["Mês"] = evo["month"].apply(lambda m: f"{month_label(m)}")
        fig = px.line(
            evo, x="Mês", y="value_scaled", color="year", markers=True,
            labels={"value_scaled": label_value(), "Mês": "Mês", "year": "Ano"},
            title="Evolução Mensal (Soma dos filtros)"
        )
        fig.update_traces(
            customdata=np.stack([evo["valor_br"]], axis=-1),
            hovertemplate="Valor: %{customdata[0]}<extra></extra>"
        )
        st.plotly_chart(compact_layout(fig), use_container_width=True)
    else:
        st.info("Sem dados para os filtros selecionados.")

# ---------- Tab 2: Por Secretaria (Soma) ----------
with tab2:
    if not filt.empty:
        by_sec = filt.groupby(["year","secretaria"], as_index=False)[["value","value_scaled"]].sum()
        by_sec["valor_br"] = by_sec["value"].apply(br_currency)
        fig2 = px.bar(
            by_sec, x="secretaria", y="value_scaled", color="year", barmode="group",
            labels={"value_scaled": label_value(), "secretaria": "Secretaria", "year": "Ano"},
            title="Soma por Secretaria (período filtrado)"
        )
        fig2.update_traces(
            customdata=np.stack([by_sec["valor_br"]], axis=-1),
            hovertemplate="Valor: %{customdata[0]}<extra></extra>"
        )
        st.plotly_chart(compact_layout(fig2, height=380), use_container_width=True)
    else:
        st.info("Sem dados para os filtros selecionados.")

# ---------- Tab 3: Por Categoria (Soma) ----------
with tab3:
    if not filt.empty:
        by_cat = filt.groupby(["year","category"], as_index=False)[["value","value_scaled"]].sum()
        by_cat["valor_br"] = by_cat["value"].apply(br_currency)
        fig3 = px.bar(
            by_cat, x="category", y="value_scaled", color="year", barmode="group",
            labels={"value_scaled": label_value(), "category": "Categoria", "year": "Ano"},
            title="Soma por Categoria (período filtrado)"
        )
        fig3.update_traces(
            customdata=np.stack([by_cat["valor_br"]], axis=-1),
            hovertemplate="Valor: %{customdata[0]}<extra></extra>"
        )
        st.plotly_chart(compact_layout(fig3, height=380), use_container_width=True)
    else:
        st.info("Sem dados para os filtros selecionados.")

# ---------- Tab 4: Δ por Secretaria (Evolução) ----------
with tab4:
    st.subheader("Evolução mensal da variação (2025 - 2024)")
    mode = st.radio("Tipo de variação", ["Valor (Δ R$)", "Percentual (Δ %)"], horizontal=True)
    # Foco em 'Total' para leitura mais clara
    comp_total = comp[comp["category"] == "Total"].copy()
    comp_total = comp_total[
        comp_total["secretaria"].isin(sec_sel) &
        comp_total["date"].dt.month.between(month_range[0], month_range[1])
    ].copy()
    if comp_total.empty:
        st.info("Sem dados para os filtros selecionados.")
    else:
        comp_total["month_label"] = comp_total["month"].apply(month_label)
        if mode.startswith("Valor"):
            df_var = comp_total.groupby(["secretaria","date","month_label"], as_index=False)["var_abs"].sum()
            # Seleciona top 10 por amplitude de variação no período para não poluir
            rank = (df_var.groupby("secretaria")["var_abs"].sum().abs()
                        .sort_values(ascending=False).head(10).index.tolist())
            show_df = df_var[df_var["secretaria"].isin(rank)].copy()
            show_df["var_abs_scaled"] = show_df["var_abs"] / scale_div
            fig4 = px.line(
                show_df.sort_values(["secretaria","date"]),
                x="month_label", y="var_abs_scaled", color="secretaria", markers=True,
                labels={"var_abs_scaled": f"Δ ({scale_label})", "month_label": "Mês/2025 vs 2024"},
                title="Δ em Valor por Secretaria (limite 10 mais relevantes no período)"
            )
            fig4.add_hline(y=0, line_dash="dot", opacity=0.5)
            st.plotly_chart(compact_layout(fig4, height=420), use_container_width=True)
        else:
            df_var = comp_total.groupby(["secretaria","date","month_label"], as_index=False)["var_pct"].mean()
            # Top 10 por amplitude média de variação %
            rank = (df_var.groupby("secretaria")["var_pct"].mean().abs()
                        .sort_values(ascending=False).head(10).index.tolist())
            show_df = df_var[df_var["secretaria"].isin(rank)].copy()
            fig4p = px.line(
                show_df.sort_values(["secretaria","date"]),
                x="month_label", y="var_pct", color="secretaria", markers=True,
                labels={"var_pct": "Δ (%)", "month_label": "Mês/2025 vs 2024"},
                title="Δ em Percentual por Secretaria (limite 10 mais relevantes no período)"
            )
            fig4p.add_hline(y=0, line_dash="dot", opacity=0.5)
            fig4p.update_yaxes(tickformat=".2%")
            st.plotly_chart(compact_layout(fig4p, height=420), use_container_width=True)

        # Ranking de aumentos e reduções (somatório no período)
        st.markdown("### Ranking no período filtrado")
        rank_df = comp_total.groupby("secretaria", as_index=False)["var_abs"].sum().rename(columns={"var_abs":"var_total"})
        col_a, col_b = st.columns(2)
        top_down = rank_df.sort_values("var_total").head(5).copy()    # maiores reduções (negativos)
        top_up   = rank_df.sort_values("var_total", ascending=False).head(5).copy()  # maiores aumentos
        top_down["Δ (R$)"] = top_down["var_total"].apply(br_currency)
        top_up["Δ (R$)"] = top_up["var_total"].apply(br_currency)
        col_a.markdown("**Maiores Reduções (Δ R$)**")
        col_a.dataframe(top_down[["secretaria","Δ (R$)"]], use_container_width=True)
        col_b.markdown("**Maiores Aumentos (Δ R$)**")
        col_b.dataframe(top_up[["secretaria","Δ (R$)"]], use_container_width=True)

# ---------- Tab 5: Heatmap (Δ por mês) ----------
with tab5:
    st.subheader("Heatmap de variação por secretaria e mês (Total)")
    mode_hm = st.radio("Métrica do heatmap", ["Valor (Δ R$)", "Percentual (Δ %)"], horizontal=True, key="hm")
    comp_total = comp[(comp["category"] == "Total") &
                      (comp["secretaria"].isin(sec_sel)) &
                      (comp["date"].dt.month.between(month_range[0], month_range[1]))].copy()
    if comp_total.empty:
        st.info("Sem dados para os filtros selecionados.")
    else:
        comp_total["m"] = comp_total["month"]
        comp_total["m_lbl"] = comp_total["m"].apply(month_label)
        if mode_hm.startswith("Valor"):
            mat = comp_total.pivot_table(index="secretaria", columns="m_lbl", values="var_abs", aggfunc="sum").fillna(0.0)
            # Escala escolhida
            mat = mat / scale_div
            title = f"Δ em Valor ({scale_label})"
            zfmt = ",.2f"
        else:
            mat = comp_total.pivot_table(index="secretaria", columns="m_lbl", values="var_pct", aggfunc="mean")
            title = "Δ em Percentual"
            zfmt = ".2%"
        # Ordena colunas por mês
        col_order = [month_label(m) for m in range(month_range[0], month_range[1]+1)]
        mat = mat.reindex(columns=[c for c in col_order if c in mat.columns])
        fig_hm = px.imshow(
            mat,
            labels=dict(x="Mês", y="Secretaria", color=title),
            aspect="auto",
            color_continuous_midpoint=0
        )
        fig_hm.update_traces(hovertemplate="%{y} | %{x}: %{z:"+zfmt+"}<extra></extra>")
        st.plotly_chart(compact_layout(fig_hm, height=520), use_container_width=True)

# ---------- Tab 6: Detalhe da Secretaria ----------
with tab6:
    st.subheader("Análise detalhada por secretaria")
    # Se o filtro lateral tiver só 1 secretaria, usa ela. Senão permite escolher.
    default_sec = sec_sel[0] if len(sec_sel) == 1 else (sec_opts[0] if sec_opts else None)
    sec_one = st.selectbox("Secretaria", options=sec_opts, index=(sec_opts.index(default_sec) if default_sec in sec_opts else 0))
    focus_cat = st.selectbox("Categoria (para séries 2024 x 2025)", options=CATEGORIES, index=CATEGORIES.index("Total"))
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

        # KPIs da secretaria (só para o foco_cat)
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
            labels={"value_scaled": label_value(), "month_lbl":"Mês", "year":"Ano"},
            title=f"Evolução mensal - {sec_one} ({focus_cat})"
        )
        st.plotly_chart(compact_layout(fig_d1, height=380), use_container_width=True)

        # Barras do Δ mensal (Total usa comp; para categoria específica calculamos Δ direto)
        if focus_cat == "Total":
            comp_det = comp[(comp["secretaria"]==sec_one) & (comp["category"]=="Total") &
                            (comp["date"].dt.month.between(month_range[0], month_range[1]))].copy()
            dbar = comp_det[["month","date","var_abs"]].copy()
        else:
            # Calcula Δ (2025-2024) por mês para a categoria selecionada
            pvt = (det.pivot_table(index=["month","date"], columns="year", values="value", aggfunc="sum")
                     .reset_index().rename(columns={2024:"v24", 2025:"v25"}))
            pvt["var_abs"] = pvt["v25"].fillna(0.0) - pvt["v24"].fillna(0.0)
            dbar = pvt[["month","date","var_abs"]].copy()
        dbar["month_lbl"] = dbar["month"].apply(month_label)
        dbar["var_scaled"] = dbar["var_abs"] / scale_div
        dbar["Δ (R$)"] = dbar["var_abs"].apply(br_currency)

        fig_d2 = px.bar(
            dbar.sort_values("month"),
            x="month_lbl", y="var_scaled",
            labels={"var_scaled": f"Δ ({scale_label})", "month_lbl": "Mês"},
            title=f"Δ mensal (2025 - 2024) - {sec_one} ({focus_cat})"
        )
        fig_d2.add_hline(y=0, line_dash="dot", opacity=0.5)
        fig_d2.update_traces(
            customdata=np.stack([dbar["Δ (R$)"]], axis=-1),
            hovertemplate="Δ: %{customdata[0]}<extra></extra>"
        )
        st.plotly_chart(compact_layout(fig_d2, height=360), use_container_width=True)

        # Tabela comparativa detalhada (não formatada para download)
        st.markdown("**Tabela Δ mensal (detalhe)**")
        tbl = dbar[["month_lbl","var_abs"]].rename(columns={"month_lbl":"Mês","var_abs":"Δ (R$)"})
        tbl_fmt = tbl.copy()
        tbl_fmt["Δ (R$)"] = tbl_fmt["Δ (R$)"].apply(br_currency)
        st.dataframe(tbl_fmt, use_container_width=True)
        st.download_button(
            "⬇️ Baixar CSV (Δ mensal - detalhe)",
            data=tbl.to_csv(index=False).encode("utf-8"),
            file_name=f"delta_mensal_{sec_one}_{focus_cat}.csv",
            mime="text/csv"
        )

st.markdown("---")
st.caption("KPIs e hovers mostram valores reais em R$. Use a escala no menu lateral para ajustar o eixo Y. Heatmap e Δ destacam rapidamente aumento/redução por secretaria.")
