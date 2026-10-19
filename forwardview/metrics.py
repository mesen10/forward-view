"""Group-level aggregates: medians plus market-cap-weighted ("index-style") figures."""

from __future__ import annotations

import pandas as pd


def aggregate_pe(df: pd.DataFrame, pe_col: str) -> float | None:
    """Index-style P/E = total market cap / total implied earnings (mcap / pe).

    Companies with negative or missing P/E are excluded, as index providers do.
    """
    d = df[(df[pe_col] > 0) & (df["market_cap"] > 0)]
    if d.empty:
        return None
    return d["market_cap"].sum() / (d["market_cap"] / d[pe_col]).sum()


def aggregate_growth(df: pd.DataFrame, cur_col: str, base_col: str | None = None, growth_col: str | None = None) -> float | None:
    """Aggregate revenue growth = sum(estimate) / sum(base) - 1.

    With growth_col, the base is backed out from estimate / (1 + growth).
    """
    if growth_col:
        d = df[df[cur_col].notna() & df[growth_col].notna() & (df[growth_col] > -1)]
        base = d[cur_col] / (1 + d[growth_col])
    else:
        d = df[df[cur_col].notna() & df[base_col].notna()]
        base = d[base_col]
    if d.empty or base.sum() <= 0:
        return None
    return d[cur_col].sum() / base.sum() - 1


def summarize(df: pd.DataFrame) -> dict:
    return {
        "companies": len(df),
        "market_cap": df["market_cap"].sum(),
        "trailing_pe_agg": aggregate_pe(df, "trailing_pe"),
        "forward_pe_agg": aggregate_pe(df, "forward_pe"),
        "pe_ny_agg": aggregate_pe(df, "pe_ny"),
        "forward_pe_median": df.loc[df["forward_pe"] > 0, "forward_pe"].median(),
        "rev_cq_growth_agg": aggregate_growth(df, "rev_cq", growth_col="rev_cq_growth"),
        "rev_cy_growth_agg": aggregate_growth(df, "rev_cy", growth_col="rev_cy_growth"),
        "rev_ny_growth_agg": aggregate_growth(df, "rev_ny", base_col="rev_cy"),
        "rev_cy_growth_median": df["rev_cy_growth"].median(),
        "rev_ny_growth_median": df["rev_ny_growth"].median(),
        "eps_ny_growth_median": df["eps_ny_growth"].median(),
    }


def by_group(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    rows = []
    for name, g in df.groupby(group_col, dropna=True):
        rows.append({group_col: name, **summarize(g)})
    out = pd.DataFrame(rows)
    return out.sort_values("market_cap", ascending=False) if not out.empty else out


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Per-company derived columns used in the UI."""
    df = df.copy()
    for p in ("cy", "ny"):
        old = df.get(f"eps_{p}_90d_ago")
        if old is not None:
            df[f"eps_{p}_rev90"] = df[f"eps_{p}"] / old.where(old > 0) - 1
    if "analyst_target" in df:
        df["upside"] = df["analyst_target"] / df["price"] - 1
    return df
