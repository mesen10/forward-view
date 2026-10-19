"""Forward View: valuation and analyst-estimate dashboard. Run: streamlit run app.py"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from forwardview import metrics, store
from forwardview.fetch import PERIOD_LABELS
from forwardview.refresh import refresh
from forwardview.universes import UNIVERSES

st.set_page_config(page_title="Forward View", layout="wide")

pct = lambda label, **kw: st.column_config.NumberColumn(label, format="percent", **kw)
num = lambda label, fmt="%.1f", **kw: st.column_config.NumberColumn(label, format=fmt, **kw)


def fmt_pct(x):
    return "–" if x is None or pd.isna(x) else f"{x:+.1%}"


def fmt_x(x):
    return "–" if x is None or pd.isna(x) else f"{x:.1f}x"


@st.cache_data(ttl=300)
def load(universe: str, date: str) -> pd.DataFrame:
    df = store.load_snapshot(universe, date)
    return metrics.add_derived(df) if not df.empty else df


@st.cache_data(ttl=300)
def long_term(universe: str, date: str) -> pd.DataFrame:
    """FY0..FY+4 columns per company from the latest FMP estimates (empty rows if none)."""
    snap = load(universe, date)
    est = store.load_estimates(snap["ticker"].tolist())
    rows = []
    for r in snap.itertuples():
        lt = metrics.long_term(est[r.ticker], r.price, r.rev_cy) if r.ticker in est else {}
        rows.append({"ticker": r.ticker, "name": r.name, "market_cap": r.market_cap, **lt})
    return pd.DataFrame(rows)


@st.cache_data(ttl=300)
def history(universe: str) -> pd.DataFrame:
    return store.load_history(universe)


# ---------------- Sidebar ----------------
st.sidebar.title("Forward View")
universe = st.sidebar.radio("Universe", list(UNIVERSES), format_func=UNIVERSES.get)
dates = store.snapshot_dates(universe)
date = st.sidebar.selectbox("Snapshot", dates) if dates else None

if st.sidebar.button(f"Refresh {UNIVERSES[universe]}", type="primary", width="stretch"):
    bar = st.sidebar.progress(0.0, text="Loading constituents…")
    d, n, errors = refresh(universe, lambda i, total, t: bar.progress(i / total, text=f"{i}/{total} {t}"))
    st.cache_data.clear()
    st.sidebar.success(f"Saved {n} tickers for {d} ({errors} errors)")
    st.rerun()

st.sidebar.caption(
    "Data: Yahoo Finance via yfinance (unofficial, free). Estimates are analyst consensus. "
    "Current/Next FY follow each company's own fiscal calendar."
)

if not date:
    st.info(f"No data yet for {UNIVERSES[universe]}. Click **Refresh** in the sidebar (takes ~1 min per 100 tickers).")
    st.stop()

df = load(universe, date)
ok = df[df.get("error").isna()] if "error" in df else df
failed = df[df["error"].notna()]["ticker"].tolist() if "error" in df else []

st.title(UNIVERSES[universe])
st.caption(f"Snapshot {date} · {len(ok)} companies" + (f" · failed: {', '.join(failed)}" if failed else ""))

tab_overview, tab_companies, tab_longterm, tab_estimates, tab_groups, tab_history = st.tabs(
    ["Overview", "Companies", "FY+1 – FY+4", "Company estimates", "Sectors / industries", "History"]
)

# ---------------- Overview ----------------
with tab_overview:
    s = metrics.summarize(ok)
    c = st.columns(4)
    c[0].metric("Forward P/E (cap-weighted)", fmt_x(s["forward_pe_agg"]), help="Total market cap / total forward earnings")
    c[1].metric("Forward P/E (median)", fmt_x(s["forward_pe_median"]))
    c[2].metric("Trailing P/E (cap-weighted)", fmt_x(s["trailing_pe_agg"]))
    c[3].metric("Market cap", f"${s['market_cap'] / 1e12:.2f}T")
    c = st.columns(5)
    c[0].metric("Rev growth, current Q (agg)", fmt_pct(s["rev_cq_growth_agg"]))
    c[1].metric("Rev growth, current FY (agg)", fmt_pct(s["rev_cy_growth_agg"]))
    c[2].metric("Rev growth, next FY (agg)", fmt_pct(s["rev_ny_growth_agg"]))
    c[3].metric("Rev growth, next FY (median)", fmt_pct(s["rev_ny_growth_median"]))
    c[4].metric("EPS growth, next FY (median)", fmt_pct(s["eps_ny_growth_median"]))

    st.subheader("Universe comparison (latest snapshot each)")
    comp = []
    for u in UNIVERSES:
        ud = store.snapshot_dates(u)
        if ud:
            d = load(u, ud[0])
            d = d[d["error"].isna()] if "error" in d else d
            comp.append({"universe": UNIVERSES[u], "date": ud[0], **metrics.summarize(d)})
    comp = pd.DataFrame(comp)
    comp["market_cap"] = comp["market_cap"] / 1e12
    st.dataframe(
        comp[["universe", "date", "companies", "market_cap", "forward_pe_agg", "forward_pe_median",
              "rev_cy_growth_agg", "rev_ny_growth_agg", "rev_ny_growth_median"]],
        hide_index=True,
        width="stretch",
        column_config={
            "market_cap": num("Mkt cap ($T)", "%.2f"),
            "forward_pe_agg": num("Fwd P/E (agg)"),
            "forward_pe_median": num("Fwd P/E (median)"),
            "rev_cy_growth_agg": pct("Rev g. cur FY (agg)"),
            "rev_ny_growth_agg": pct("Rev g. next FY (agg)"),
            "rev_ny_growth_median": pct("Rev g. next FY (median)"),
        },
    )

    plot = ok[(ok["forward_pe"] > 0) & (ok["forward_pe"] < 100) & ok["rev_ny_growth"].notna()]
    if not plot.empty:
        st.subheader("Forward P/E vs. next-FY revenue growth")
        fig = px.scatter(
            plot, x="rev_ny_growth", y="forward_pe", size="market_cap", color="industry" if universe in ("sox", "hw", "energy") else "sector",
            hover_name="ticker", hover_data={"name": True, "market_cap": False}, size_max=50,
            labels={"rev_ny_growth": "Next FY revenue growth (consensus)", "forward_pe": "Forward P/E"},
        )
        fig.update_xaxes(tickformat=".0%")
        fig.update_layout(height=520, legend_title_text="")
        st.plotly_chart(fig, width="stretch")

# ---------------- Companies ----------------
with tab_companies:
    f = st.columns([2, 2, 1])
    groups = sorted(ok["sector"].dropna().unique())
    pick = f[0].multiselect("Sector", groups)
    query = f[1].text_input("Search ticker / name")
    min_cap = f[2].number_input("Min mkt cap ($B)", 0, 5000, 0)
    view = ok.copy()
    if pick:
        view = view[view["sector"].isin(pick)]
    if query:
        q = query.lower()
        view = view[view["ticker"].str.lower().str.contains(q) | view["name"].fillna("").str.lower().str.contains(q)]
    view = view[view["market_cap"].fillna(0) >= min_cap * 1e9]
    view["mcap_b"] = view["market_cap"] / 1e9
    # Detail columns are hidden by default; the "Detay" toggle shows them.
    detail = st.toggle("Detay", value=False, help="Sector, industry, market cap, price, P/E TTM, P/S TTM and EPS estimates")
    detail_cols = {
        "sector": st.column_config.TextColumn("Sector"),
        "industry": st.column_config.TextColumn("Industry"),
        "mcap_b": num("Mkt cap ($B)", "%.0f"),
        "price": num("Price", "%.2f"),
        "trailing_pe": num("P/E TTM"),
        "ps_ttm": num("P/S TTM"),
        "eps_ny_growth": pct("EPS g. next FY (est)"),
        "eps_ny_rev90": pct("Next FY EPS rev. 90d", help="Change in consensus next-FY EPS over the last 90 days"),
    }
    cols = {
        "ticker": st.column_config.TextColumn("Ticker"),
        "name": st.column_config.TextColumn("Name"),
        "forward_pe": num("Fwd P/E"),
        "revenue_growth_yoy": pct("Rev g. last Q (YoY)"),
        "rev_cq_growth": pct("Rev g. cur Q (est)"),
        "rev_nq_growth": pct("Rev g. next Q (est)"),
        "rev_cy_growth": pct("Rev g. cur FY (est)"),
        "rev_ny_growth": pct("Rev g. next FY (est)"),
        "gross_margin": pct("Gross margin"),
        "operating_margin": pct("Op. margin"),
        "upside": pct("Target upside"),
    }
    if detail:
        cols = {"ticker": cols.pop("ticker"), "name": cols.pop("name"), **detail_cols, **cols}
    st.dataframe(
        view.sort_values("market_cap", ascending=False)[list(cols)],
        hide_index=True, width="stretch", height=640, column_config=cols,
    )
    st.download_button("Download CSV", view.to_csv(index=False), f"forwardview_{universe}_{date}.csv")

# ---------------- FY+1 ... FY+4 (FMP) ----------------
LT_METRICS = {
    "Revenue growth": ("rev_growth", pct),
    "EPS growth": ("eps_growth", pct),
    "P/E": ("pe", num),
    "Revenue ($B)": ("rev", lambda label: num(label, "%.1f")),
    "EPS": ("eps", lambda label: num(label, "%.2f")),
    "Analysts (EPS)": ("eps_analysts", lambda label: num(label, "%d")),
}

with tab_longterm:
    lt = long_term(universe, date)
    status = store.estimate_status(lt["ticker"].tolist())
    covered = lt["fy1_end"].notna() if "fy1_end" in lt else pd.Series(False, index=lt.index)
    blocked = sum(s == "not_in_plan" for s in status.values())
    st.caption(
        f"FMP annual consensus · {covered.sum()} of {len(lt)} companies covered"
        + (f" · {blocked} not in the current FMP plan" if blocked else "")
        + (f" · {len(lt) - len(status)} not fetched yet (run `python -m forwardview.estimates`)" if len(status) < len(lt) else "")
        + ". FY0 is the current, not yet reported fiscal year; FY+1 is the year after it."
    )
    choice = st.radio("Metric", list(LT_METRICS), horizontal=True)
    suffix, col_type = LT_METRICS[choice]
    view = lt[covered].sort_values("market_cap", ascending=False)
    cols = {"ticker": st.column_config.TextColumn("Ticker"), "name": st.column_config.TextColumn("Name"),
            "fy0_end": st.column_config.TextColumn("FY0 ends")}
    for k in range(0 if suffix in ("rev", "eps", "pe", "eps_analysts") else 1, metrics.LT_YEARS + 1):
        c = f"fy{k}_{suffix}"
        if c in view:
            cols[c] = col_type("FY0" if k == 0 else f"FY+{k}")
    if view.empty:
        st.info("No FMP estimates for this universe yet.")
    else:
        st.dataframe(view[[c for c in cols if c in view]], hide_index=True, width="stretch", height=640, column_config=cols)
    st.caption("Growth is year over year versus the prior fiscal year's consensus. Far years have few analysts; check the Analysts view.")

# ---------------- Company estimates ----------------
with tab_estimates:
    tickers = ok.sort_values("market_cap", ascending=False)["ticker"].tolist()
    tk = st.selectbox("Company", tickers, format_func=lambda t: f"{t} · {ok.set_index('ticker').at[t, 'name']}")
    r = ok.set_index("ticker").loc[tk]
    c = st.columns(4)
    c[0].metric("Price", f"${r['price']:.2f}" if pd.notna(r["price"]) else "–", fmt_pct(r.get("upside")) + " to target")
    c[1].metric("Fwd P/E", fmt_x(r["forward_pe"]))
    c[2].metric("Rev growth last Q", fmt_pct(r["revenue_growth_yoy"]))
    c[3].metric("Recommendation (1=Strong Buy)", "–" if pd.isna(r["recommendation"]) else f"{r['recommendation']:.2f}")

    est = pd.DataFrame([
        {
            "Period": label,
            "Revenue est. ($B)": r[f"rev_{p}"] / 1e9 if pd.notna(r[f"rev_{p}"]) else None,
            "Low ($B)": r[f"rev_{p}_low"] / 1e9 if pd.notna(r[f"rev_{p}_low"]) else None,
            "High ($B)": r[f"rev_{p}_high"] / 1e9 if pd.notna(r[f"rev_{p}_high"]) else None,
            "Rev growth": r[f"rev_{p}_growth"],
            "Analysts": r[f"rev_{p}_analysts"],
            "EPS est.": r[f"eps_{p}"],
            "EPS growth": r[f"eps_{p}_growth"],
            "EPS 30d ago": r[f"eps_{p}_30d_ago"],
            "EPS 90d ago": r[f"eps_{p}_90d_ago"],
            "Up revisions 30d": r[f"eps_{p}_up30"],
            "Down revisions 30d": r[f"eps_{p}_down30"],
        }
        for p, label in PERIOD_LABELS.items()
    ])
    st.dataframe(
        est, hide_index=True, width="stretch",
        column_config={
            "Revenue est. ($B)": num("Revenue est. ($B)", "%.2f"),
            "Low ($B)": num("Low ($B)", "%.2f"),
            "High ($B)": num("High ($B)", "%.2f"),
            "Rev growth": pct("Rev growth"),
            "Analysts": num("Analysts", "%d"),
            "EPS est.": num("EPS est.", "%.2f"),
            "EPS growth": pct("EPS growth"),
            "EPS 30d ago": num("EPS 30d ago", "%.2f"),
            "EPS 90d ago": num("EPS 90d ago", "%.2f"),
            "Up revisions 30d": num("Up rev. 30d", "%d"),
            "Down revisions 30d": num("Down rev. 30d", "%d"),
        },
    )
    tl = long_term(universe, date).set_index("ticker").loc[tk]
    if pd.notna(tl.get("fy1_end")):
        st.subheader("Annual consensus, FY0 – FY+4 (FMP)")
        yrs = [k for k in range(metrics.LT_YEARS + 1) if pd.notna(tl.get(f"fy{k}_end"))]
        st.dataframe(
            pd.DataFrame([
                {
                    "Year": "FY0" if k == 0 else f"FY+{k}",
                    "FY ends": tl[f"fy{k}_end"],
                    "Revenue est. ($B)": tl[f"fy{k}_rev"] / 1e9 if pd.notna(tl[f"fy{k}_rev"]) else None,
                    "Rev growth": tl.get(f"fy{k}_rev_growth"),
                    "EPS est.": tl[f"fy{k}_eps"],
                    "EPS growth": tl.get(f"fy{k}_eps_growth"),
                    "P/E": tl.get(f"fy{k}_pe"),
                    "Analysts (rev / EPS)": f"{tl[f'fy{k}_rev_analysts']:.0f} / {tl[f'fy{k}_eps_analysts']:.0f}",
                }
                for k in yrs
            ]),
            hide_index=True, width="stretch",
            column_config={
                "Revenue est. ($B)": num("Revenue est. ($B)", "%.1f"),
                "Rev growth": pct("Rev growth"),
                "EPS est.": num("EPS est.", "%.2f"),
                "EPS growth": pct("EPS growth"),
                "P/E": num("P/E"),
            },
        )
    else:
        st.caption("No FY+1 – FY+4 estimates for this company (not covered by the current FMP plan, or not fetched yet).")

    h = history(universe)
    if not h.empty and (h["ticker"] == tk).sum() > 1:
        th = h[h["ticker"] == tk]
        fig = px.line(th, x="snapshot_date", y=["rev_cy", "rev_ny"], markers=True,
                      labels={"value": "Consensus revenue", "snapshot_date": "", "variable": ""})
        fig.update_layout(height=320, title="Consensus revenue estimate over time")
        st.plotly_chart(fig, width="stretch")

# ---------------- Sectors / industries ----------------
with tab_groups:
    group_col = st.radio("Group by", ["sector", "industry"], horizontal=True,
                         index=1 if universe in ("sox", "hw", "energy") else 0)
    g = metrics.by_group(ok, group_col)
    g["market_cap"] = g["market_cap"] / 1e9
    st.dataframe(
        g[[group_col, "companies", "market_cap", "forward_pe_agg", "forward_pe_median", "trailing_pe_agg",
           "rev_cq_growth_agg", "rev_cy_growth_agg", "rev_ny_growth_agg", "rev_ny_growth_median", "eps_ny_growth_median"]],
        hide_index=True, width="stretch",
        column_config={
            group_col: st.column_config.TextColumn(group_col.title()),
            "market_cap": num("Mkt cap ($B)", "%.0f"),
            "forward_pe_agg": num("Fwd P/E (agg)"),
            "forward_pe_median": num("Fwd P/E (median)"),
            "trailing_pe_agg": num("P/E TTM (agg)"),
            "rev_cq_growth_agg": pct("Rev g. cur Q (agg)"),
            "rev_cy_growth_agg": pct("Rev g. cur FY (agg)"),
            "rev_ny_growth_agg": pct("Rev g. next FY (agg)"),
            "rev_ny_growth_median": pct("Rev g. next FY (median)"),
            "eps_ny_growth_median": pct("EPS g. next FY (median)"),
        },
    )
    st.caption("agg = market-cap-weighted (index-style): total market cap / total earnings, total revenue / total base revenue.")

# ---------------- History ----------------
with tab_history:
    h = history(universe)
    if h.empty or h["snapshot_date"].nunique() < 2:
        st.info("History builds up as you refresh over time. Refresh daily or weekly to see trends here.")
    else:
        if "error" in h:
            h = h[h["error"].isna()]
        rows = [{"date": d, **metrics.summarize(g)} for d, g in h.groupby("snapshot_date")]
        hs = pd.DataFrame(rows)
        c1, c2 = st.columns(2)
        fig = px.line(hs, x="date", y=["forward_pe_agg", "forward_pe_median"], markers=True,
                      labels={"value": "P/E", "date": "", "variable": ""})
        fig.update_layout(title="Valuation", height=380)
        c1.plotly_chart(fig, width="stretch")
        fig = px.line(hs, x="date", y=["rev_cy_growth_agg", "rev_ny_growth_agg"], markers=True,
                      labels={"value": "Revenue growth", "date": "", "variable": ""})
        fig.update_yaxes(tickformat=".0%")
        fig.update_layout(title="Consensus revenue growth", height=380)
        c2.plotly_chart(fig, width="stretch")
