# app.py
# -*- coding: utf-8 -*-
"""
Painel Streamlit para processar "Comparativo geral.xlsx"
Comparações 2024 x 2025 por secretaria/categoria, KPIs BR, barras lado a lado,
ranking de Δ% (aumentos e reduções) com Top N e exportação A4 em HTML imprimível
(sem reportlab/kaleido).
"""
import io
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.io as pio
from datetime import datetime

# ============== Config ==============
st.set_page_config(page_title="Folha - Comparativo 2024 x 2025", layout="wide")
st.title("📊 Painel de Folha (2024 x 2025)")
st.caption("Envie **Comparativo geral.xlsx**. O painel evita dupla contagem e calcula TOTAL mesmo sem colunas 'Total'.")

# CSS: KPIs compactos
st.markdown("""
<style>
  div[data-testid="stMetric"] { padding: .25rem .5rem; }
  div[data-testid="stMetric"] [data-testid="stMetricLabel"] { font-size: .85rem; }
  div[data-testid="stMetric"] [data-testid="stMetricValue"] { font-size: 1.6rem; }
  div[data-testid="stMetric"] [data-testid="stMetricDelta"] svg { transform: scale(.85); }
</style>
""", unsafe_allow_html=True)

# ============== Helpers ==============
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

def ensure_all_secs(df, all_secs):
    present = set(df["secretaria"])
    missing = [s for s in all_secs if s not in present]
    if missing:
        add = pd.DataFrame({"secretaria": missing, "value": 0.0})
        df = pd.concat([df, add], ignore_index=True)
    return df

# ============== Transformação ==============
@st.cache_data(show_spinner=False)
def transform_excel(file_bytes: bytes):
    df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0)
    df.columns = df.columns.str.replace(r"\s+", " ", regex=True).str.strip()

    sec_col = next((c for c in df.columns if c.lower().startswith("secretaria")), None)
    mes_col = next((c for c in df.columns if c.replace(" ","") in {"Mês/Ano","Mes/Ano"}), None)
    if sec_col is None or mes_col is None:
        raise ValueError("Planilha precisa ter colunas 'Secretaria' e 'Mês/Ano'.")

    df[sec_col] = df[sec_col].ffill()
    df = df[df[mes_col].notna()].copy()
    df["MesIndex"] = df[mes_col].apply(extract_month)

    def find_col(name):
        if name in df.columns: return name
        target = name.lower().replace(" ", "")
        for c in df.columns:
            if c.lower().replace(" ", "") == target:
                return c
        return None

    cols_2024 = {cat: find_col(f"{cat} 2024") for cat in BASE_CATEGORIES}
    cols_2025 = {cat: find_col(f"{cat} 2025") for cat in BASE_CATEGORIES}
    col_total_2024 = find_col(f"{TOT_LABEL} 2024")
    col_total_2025 = find_col(f"{TOT_LABEL} 2025")
    has_total_cols = (col_total_2024 is not None and col_total_2025 is not None)

    rows = []
    for _, r in df.iterrows():
        m = r["MesIndex"]
        if pd.isna(m): 
            continue
        for cat in BASE_CATEGORIES:
            c24, c25 = cols_2024.get(cat), cols_2025.get(cat)
            if c24 and pd.notna(r.get(c24)):
                rows.append({"secretaria": str(r[sec_col]).strip(), "date": datetime(2024,int(m),1),
                             "year": 2024, "category": cat, "value": float(r[c24])})
            if c25 and pd.notna(r.get(c25)):
                rows.append({"secretaria": str(r[sec_col]).strip(), "date": datetime(2025,int(m),1),
                             "year": 2025, "category": cat, "value": float(r[c25])})
        if has_total_cols:
            if pd.notna(r.get(col_total_2024)):
                rows.append({"secretaria": str(r[sec_col]).strip(), "date": datetime(2024,int(m),1),
                             "year": 2024, "category": TOT_LABEL, "value": float(r[col_total_2024])})
            if pd.notna(r.get(col_total_2025)):
                rows.append({"secretaria": str(r[sec_col]).strip(), "date": datetime(2025,int(m),1),
                             "year": 2025, "category": TOT_LABEL, "value": float(r[col_total_2025])})

    fact = pd.DataFrame(rows)
    if fact.empty:
        raise ValueError("Após leitura, não há linhas com valores. Confirme nomes das colunas e meses.")

    # TOTAL derivado quando não existir no Excel
    if not has_total_cols:
        base_only = fact[fact["category"].isin(BASE_CATEGORIES)].copy()
        totals = (base_only.groupby(["secretaria","date","year"], as_index=False, observed=False)["value"].sum()
                            .assign(category=TOT_LABEL))
        fact = pd.concat([fact, totals], ignore_index=True)

    fact["category"] = pd.Categorical(fact["category"], categories=ALL_CATEGORIES, ordered=True)

    dim_date = (fact[["date"]].drop_duplicates()
                .assign(year=lambda d: d["date"].dt.year, month=lambda d: d["date"].dt.month)
                .sort_values("date"))
    dim_secretaria = fact[["secretaria"]].drop_duplicates().sort_values("secretaria")

    comp = (fact.pivot_table(index=["secretaria","date","category"], columns="year",
                             values="value", aggfunc="sum", observed=False)
                 .reset_index().rename_axis(None, axis=1)
                 .rename(columns={2024:"value_2024", 2025:"value_2025"}))
    comp["value_2024_f"] = comp["value_2024"].fillna(0.0)
    comp["value_2025_f"] = comp["value_2025"].fillna(0.0)
    comp["var_abs"] = comp["value_2025_f"] - comp["value_2024_f"]            # 2025 − 2024
    comp["var_pct"] = np.where(comp["value_2024_f"] == 0, np.nan, comp["var_abs"]/comp["value_2024_f"])
    comp["year"] = comp["date"].dt.year
    comp["month"] = comp["date"].dt.month

    return fact, dim_date, dim_secretaria, comp, has_total_cols

# ============== Upload ==============
uploaded = st.file_uploader("Envie o arquivo Excel (Comparativo geral.xlsx)", type=["xlsx"])
if not uploaded:
    st.info("Envie a planilha para liberar filtros e gráficos.")
    st.stop()

# ============== Processa ==============
try:
    fact, dim_date, dim_secretaria, comp, has_total_cols = transform_excel(uploaded.getvalue())
except Exception as e:
    st.error(f"Erro ao processar a planilha: {e}")
    st.stop()

# ============== Filtros ==============
st.sidebar.header("Filtros")
sec_opts  = sorted(dim_secretaria["secretaria"].unique().tolist())
cat_opts  = ALL_CATEGORIES
year_opts = sorted(fact["year"].unique().tolist())
month_opts= sorted(dim_date["month"].unique().tolist())
month_min, month_max = (min(month_opts), max(month_opts))

sec_sel   = st.sidebar.multiselect("Secretaria (visões gerais)", sec_opts, default=sec_opts)
cat_sel   = st.sidebar.multiselect("Categoria", cat_opts, default=cat_opts)
year_sel  = st.sidebar.multiselect("Ano", year_opts, default=year_opts)
month_rng = st.sidebar.slider("Mês (1=Jan ... 12=Dez)", 1, 12, (month_min, month_max))

# Cálculo do total
if has_total_cols:
    total_mode = st.sidebar.radio(
        "Cálculo do TOTAL",
        ["Usar coluna 'Total' (recomendado)", "Somar categorias selecionadas"],
        index=0
    )
else:
    total_mode = "Somar categorias selecionadas"
    st.sidebar.info("Colunas 'Total' ausentes. O total será calculado pela soma das categorias.")

# Escala + Toggles + Top N
scale_name = st.sidebar.selectbox("Escala do eixo Y", ["Reais (R$)", "Mil (R$ mil)", "Milhões (R$ mi)"], index=0)
scale_map  = {"Reais (R$)":(1.0,"R$"), "Mil (R$ mil)":(1e3,"R$ mil"), "Milhões (R$ mi)":(1e6,"R$ mi")}
scale_div, scale_label = scale_map[scale_name]
show_labels = st.sidebar.checkbox("Mostrar rótulos de valores nos gráficos", value=False)
equal_axes  = st.sidebar.checkbox("Fixar eixos iguais nos painéis duplos", value=True)
top_n_rank  = st.sidebar.number_input("Top N do ranking (mês a mês)", min_value=3, max_value=20, value=5, step=1)

# ============== Base filtrada ==============
base_mask = (
    fact["secretaria"].isin(sec_sel) &
    fact["year"].isin(year_sel) &
    fact["date"].dt.month.between(month_rng[0], month_rng[1])
)
fbase = fact.loc[base_mask].copy()   # NÃO filtra por categoria aqui

def make_total_df(df, selected_categories, mode, has_tot):
    if mode.startswith("Usar coluna 'Total'") and has_tot:
        out = df[df["category"] == TOT_LABEL].copy()
    else:
        cats = [c for c in selected_categories if c != TOT_LABEL]
        if not cats:  # se usuário não selecionou base nenhuma, usa todas
            cats = BASE_CATEGORIES
        out  = df[df["category"].isin(cats)].copy()
    out["value_scaled"] = out["value"] / scale_div
    return out

filt_tot = make_total_df(fbase, cat_sel, total_mode, has_total_cols)

# ============== KPIs ==============
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

# ============== Layout base ==============
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

# Lista de figuras para exportação A4
export_figs = []

# ============== Abas ==============
tabA, tabB, tabC = st.tabs([
    "Comparação por Secretaria (Mês a mês)",
    "Por Secretaria (Soma)",
    "Por Categoria (Soma)"
])

# ---------- TAB A: Comparação por Secretaria (mês a mês) ----------
with tabA:
    st.caption("Escolha um mês e compare 2024 x 2025 por secretaria (TOTAL). Ranking mostra ↑ aumentos e ↓ reduções (percentuais positivos).")
    meses_disponiveis = sorted(set(range(month_rng[0], month_rng[1]+1)))
    mes_sel = st.selectbox("Mês", options=meses_disponiveis, format_func=month_label, index=0)

    base_mes = filt_tot[filt_tot["date"].dt.month == mes_sel].copy()
    if base_mes.empty:
        st.info("Sem dados para o mês selecionado dentro do filtro.")
    else:
        all_secs = sorted(base_mes["secretaria"].unique().tolist())
        y24 = (base_mes[base_mes["year"]==2024].groupby("secretaria", as_index=False, observed=False)["value"].sum())
        y25 = (base_mes[base_mes["year"]==2025].groupby("secretaria", as_index=False, observed=False)["value"].sum())
        y24 = ensure_all_secs(y24, all_secs); y25 = ensure_all_secs(y25, all_secs)
        y24["value_scaled"] = y24["value"]/scale_div; y25["value_scaled"] = y25["value"]/scale_div
        y24["valor_br"] = y24["value"].apply(br_currency); y25["valor_br"] = y25["value"].apply(br_currency)

        col1, col2 = st.columns(2)
        ymax = max(y24["value_scaled"].max(), y25["value_scaled"].max()) * 1.1 if equal_axes else None
        with col1:
            fig_24 = px.bar(y24.sort_values("value_scaled", ascending=False),
                            x="secretaria", y="value_scaled",
                            labels={"value_scaled": label_value(), "secretaria":"Secretaria"},
                            title=f"{month_label(mes_sel)} / 2024 — Total",
                            text="valor_br" if show_labels else None)
            fig_24.update_traces(hovertemplate="Valor: %{text}<extra></extra>" if show_labels else None,
                                 cliponaxis=False)
            if ymax: fig_24.update_yaxes(range=[0, ymax])
            st.plotly_chart(compact_layout(fig_24, 380), use_container_width=True)
            export_figs.append((fig_24.layout.title.text, fig_24))
        with col2:
            fig_25 = px.bar(y25.sort_values("value_scaled", ascending=False),
                            x="secretaria", y="value_scaled",
                            labels={"value_scaled": label_value(), "secretaria":"Secretaria"},
                            title=f"{month_label(mes_sel)} / 2025 — Total",
                            text="valor_br" if show_labels else None)
            fig_25.update_traces(hovertemplate="Valor: %{text}<extra></extra>" if show_labels else None,
                                 cliponaxis=False)
            if ymax: fig_25.update_yaxes(range=[0, ymax])
            st.plotly_chart(compact_layout(fig_25, 380), use_container_width=True)
            export_figs.append((fig_25.layout.title.text, fig_25))

        # ===== Ranking Δ% do mês (sem negativos) =====
        cmp = (y24.rename(columns={"value":"v24"})[["secretaria","v24"]]
                   .merge(y25.rename(columns={"value":"v25"})[["secretaria","v25"]], on="secretaria", how="outer")
                   .fillna(0.0))
        cmp["aumento_pct"]  = np.where(cmp["v24"]==0, np.nan, (cmp["v25"]-cmp["v24"])/cmp["v24"])
        cmp["reducao_pct"]  = np.where(cmp["v24"]==0, np.nan, (cmp["v24"]-cmp["v25"])/cmp["v24"])
        cmp["Δ (R$)"]       = cmp["v25"] - cmp["v24"]

        colA, colB = st.columns(2)
        up = cmp[(cmp["aumento_pct"]>0)].sort_values("aumento_pct", ascending=False).head(int(top_n_rank))
        down = cmp[(cmp["reducao_pct"]>0)].sort_values("reducao_pct", ascending=False).head(int(top_n_rank))

        if up.empty:
            colA.info(f"Sem aumentos em {month_label(mes_sel)}.")
        else:
            up_fmt = up.copy()
            up_fmt["2024"] = up_fmt["v24"].apply(br_currency)
            up_fmt["2025"] = up_fmt["v25"].apply(br_currency)
            up_fmt["Δ (R$)"] = up_fmt["Δ (R$)"].apply(br_currency)
            up_fmt["Aumento (%)"] = up_fmt["aumento_pct"].apply(br_percent)
            colA.markdown(f"**Top ↑ Aumentos — {month_label(mes_sel)}**")
            colA.dataframe(up_fmt.set_index("secretaria")[["2024","2025","Δ (R$)","Aumento (%)"]],
                           use_container_width=True)

        if down.empty:
            colB.info(f"Sem reduções em {month_label(mes_sel)}.")
        else:
            down_fmt = down.copy()
            down_fmt["2024"] = down_fmt["v24"].apply(br_currency)
            down_fmt["2025"] = down_fmt["v25"].apply(br_currency)
            down_fmt["Δ (R$)"] = down_fmt["Δ (R$)"].apply(br_currency)
            down_fmt["Redução (%)"] = down_fmt["reducao_pct"].apply(br_percent)
            colB.markdown(f"**Top ↓ Reduções — {month_label(mes_sel)}**")
            colB.dataframe(down_fmt.set_index("secretaria")[["2024","2025","Δ (R$)","Redução (%)"]],
                           use_container_width=True)

# ---------- TAB B: Por Secretaria (Soma) ----------
with tabB:
    st.caption("Totais do período filtrado por secretaria, em painéis independentes para 2024 e 2025.")
    if filt_tot.empty:
        st.info("Sem dados para os filtros selecionados.")
    else:
        all_secs = sorted(filt_tot["secretaria"].unique().tolist())
        sec24 = (filt_tot[filt_tot["year"]==2024].groupby("secretaria", as_index=False, observed=False)["value"].sum())
        sec25 = (filt_tot[filt_tot["year"]==2025].groupby("secretaria", as_index=False, observed=False)["value"].sum())
        sec24 = ensure_all_secs(sec24, all_secs); sec25 = ensure_all_secs(sec25, all_secs)
        sec24["value_scaled"] = sec24["value"]/scale_div; sec25["value_scaled"] = sec25["value"]/scale_div
        sec24["valor_br"] = sec24["value"].apply(br_currency); sec25["valor_br"] = sec25["value"].apply(br_currency)

        c1, c2 = st.columns(2)
        ymax = max(sec24["value_scaled"].max(), sec25["value_scaled"].max()) * 1.1 if equal_axes else None
        with c1:
            fig2a = px.bar(sec24.sort_values("value_scaled", ascending=False),
                           x="secretaria", y="value_scaled",
                           labels={"value_scaled": label_value(), "secretaria":"Secretaria"},
                           title="Soma por Secretaria — 2024",
                           text="valor_br" if show_labels else None)
            fig2a.update_traces(hovertemplate="Valor: %{text}<extra></extra>" if show_labels else None,
                                cliponaxis=False)
            if ymax: fig2a.update_yaxes(range=[0, ymax])
            st.plotly_chart(compact_layout(fig2a, 380), use_container_width=True)
            export_figs.append((fig2a.layout.title.text, fig2a))
        with c2:
            fig2b = px.bar(sec25.sort_values("value_scaled", ascending=False),
                           x="secretaria", y="value_scaled",
                           labels={"value_scaled": label_value(), "secretaria":"Secretaria"},
                           title="Soma por Secretaria — 2025",
                           text="valor_br" if show_labels else None)
            fig2b.update_traces(hovertemplate="Valor: %{text}<extra></extra>" if show_labels else None,
                                cliponaxis=False)
            if ymax: fig2b.update_yaxes(range=[0, ymax])
            st.plotly_chart(compact_layout(fig2b, 380), use_container_width=True)
            export_figs.append((fig2b.layout.title.text, fig2b))

# ---------- TAB C: Por Categoria (Soma) ----------
with tabC:
    st.caption("Totais do período filtrado por categoria **incluindo o Total calculado**, com painéis independentes para 2024 e 2025.")
    base_cat_all = fbase.copy()

    if base_cat_all.empty:
        st.info("Sem dados para os filtros selecionados.")
    else:
        base_no_total = base_cat_all[base_cat_all["category"] != TOT_LABEL].copy()

        selected_base = [c for c in BASE_CATEGORIES if c in cat_sel]
        use_for_cats = base_no_total[base_no_total["category"].isin(selected_base)] if selected_base else base_no_total

        cat_by_year = use_for_cats.groupby(["year","category"], as_index=False, observed=False)["value"].sum()
        total_by_year = use_for_cats.groupby("year", as_index=False, observed=False)["value"].sum().assign(category=TOT_LABEL)

        cat_all = pd.concat([cat_by_year, total_by_year], ignore_index=True)

        for y in [2024, 2025]:
            for c in ALL_CATEGORIES:
                if not ((cat_all["year"]==y) & (cat_all["category"]==c)).any():
                    cat_all = pd.concat([cat_all, pd.DataFrame({"year":[y], "category":[c], "value":[0.0]})], ignore_index=True)

        cat_all["value_scaled"] = cat_all["value"]/scale_div
        cat_all["valor_br"] = cat_all["value"].apply(br_currency)

        c1, c2 = st.columns(2)
        ymax = max(cat_all.loc[cat_all["year"]==2024, "value_scaled"].max(),
                   cat_all.loc[cat_all["year"]==2025, "value_scaled"].max()) * 1.1 if equal_axes else None

        with c1:
            d24 = cat_all[cat_all["year"]==2024].sort_values("value_scaled", ascending=False)
            fig3a = px.bar(d24, x="category", y="value_scaled",
                           labels={"value_scaled": label_value(), "category":"Categoria"},
                           title="Soma por Categoria — 2024",
                           text="valor_br" if show_labels else None)
            fig3a.update_traces(hovertemplate="Valor: %{text}<extra></extra>" if show_labels else None,
                                cliponaxis=False)
            if ymax: fig3a.update_yaxes(range=[0, ymax])
            st.plotly_chart(compact_layout(fig3a, 380), use_container_width=True)
            export_figs.append((fig3a.layout.title.text, fig3a))

        with c2:
            d25 = cat_all[cat_all["year"]==2025].sort_values("value_scaled", ascending=False)
            fig3b = px.bar(d25, x="category", y="value_scaled",
                           labels={"value_scaled": label_value(), "category":"Categoria"},
                           title="Soma por Categoria — 2025",
                           text="valor_br" if show_labels else None)
            fig3b.update_traces(hovertemplate="Valor: %{text}<extra></extra>" if show_labels else None,
                                cliponaxis=False)
            if ymax: fig3b.update_yaxes(range=[0, ymax])
            st.plotly_chart(compact_layout(fig3b, 380), use_container_width=True)
            export_figs.append((fig3b.layout.title.text, fig3b))

# ============== A4 HTML (Imprimir/Salvar) ==============
st.markdown("---")
st.subheader("🖨️ A4 – Imprimir ou Salvar")
st.caption("Gera uma página A4 com os gráficos exibidos (visuais e filtros atuais). Abra e use Ctrl/Cmd+P para salvar em PDF.")

def build_a4_html(figs, titulo, subtitulo):
    parts = []
    for i, (title, fig) in enumerate(figs):
        html_fig = pio.to_html(fig, include_plotlyjs=('inline' if i == 0 else False),
                               full_html=False, config={"displayModeBar": False})
        parts.append(f"<section class='chart'><h3>{title}</h3>{html_fig}</section>")

    css = """
    <style>
      @page { size: A4; margin: 12mm; }
      html, body { margin:0; padding:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
      header { margin: 6mm 0 4mm 0; }
      h1 { font-size: 20px; margin: 0; }
      .sub { color:#555; font-size: 12px; margin-top: 2mm; }
      .chart { page-break-inside: avoid; break-inside: avoid; margin: 6mm 0; }
      .printbar { margin: 8px 0 16px 0; }
      @media print { .no-print { display:none; } }
    </style>
    """
    btn_bar = """
    <div class="printbar no-print">
      <button onclick="window.print()" style="padding:8px 12px;font-size:14px;cursor:pointer">Imprimir / Salvar em PDF</button>
    </div>
    """
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{titulo}</title>{css}</head>
<body>
  <header>
    <h1>{titulo}</h1>
    <div class="sub">{subtitulo}</div>
  </header>
  {btn_bar}
  {''.join(parts)}
</body></html>"""
    return html.encode("utf-8")

periodo = f"{month_label(month_rng[0])}–{month_label(month_rng[1])}"
anos = " & ".join(map(str, year_sel))
subtitulo = f"Período: {periodo} | Anos: {anos} | Escala: {scale_label} | Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}"

if st.button("🖨️ Gerar página A4 (HTML)"):
    if not export_figs:
        st.warning("Sem gráficos para exportar com os filtros atuais.")
    else:
        st.session_state["a4_html"] = build_a4_html(export_figs, "Relatório Folha – A4", subtitulo)

if "a4_html" in st.session_state:
    st.download_button(
        "⬇️ Baixar HTML A4",
        data=st.session_state["a4_html"],
        file_name="relatorio_folha_A4.html",
        mime="text/html"
    )
    st.components.v1.html(st.session_state["a4_html"].decode("utf-8"), height=900, scrolling=True)

st.markdown("---")
st.caption("Δ (delta) = variação. Rankings: ↑ Aumento% e ↓ Redução% listam apenas casos positivos; se não houver, mostramos aviso.")
