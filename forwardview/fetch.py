"""Pull fundamentals and analyst consensus estimates from Yahoo Finance via yfinance."""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable

import pandas as pd
import yfinance as yf

# yfinance period codes -> our column suffixes
PERIODS = {"0q": "cq", "+1q": "nq", "0y": "cy", "+1y": "ny"}
PERIOD_LABELS = {"cq": "Current Q", "nq": "Next Q", "cy": "Current FY", "ny": "Next FY"}

INFO_FIELDS = {
    "name": "shortName",
    "sector": "sector",
    "industry": "industry",
    "price": "currentPrice",
    "market_cap": "marketCap",
    "trailing_pe": "trailingPE",
    "forward_pe": "forwardPE",
    "ps_ttm": "priceToSalesTrailing12Months",
    "ev_to_revenue": "enterpriseToRevenue",
    "revenue_ttm": "totalRevenue",
    "revenue_growth_yoy": "revenueGrowth",  # latest quarter vs year-ago quarter
    "gross_margin": "grossMargins",
    "operating_margin": "operatingMargins",
    "analyst_target": "targetMeanPrice",
    "recommendation": "recommendationMean",  # 1 = strong buy, 5 = sell
}


def _num(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _cell(df: pd.DataFrame | None, row: str, col: str):
    if df is None or df.empty or row not in df.index or col not in df.columns:
        return None
    return _num(df.at[row, col])


def fetch_ticker(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    info = t.info or {}
    rec: dict = {"ticker": ticker}
    for col, key in INFO_FIELDS.items():
        val = info.get(key)
        rec[col] = val if col in ("name", "sector", "industry") else _num(val)

    rev = t.revenue_estimate
    eps = t.earnings_estimate
    trend = t.eps_trend
    revisions = t.eps_revisions

    for yp, p in PERIODS.items():
        rec[f"rev_{p}"] = _cell(rev, yp, "avg")
        rec[f"rev_{p}_low"] = _cell(rev, yp, "low")
        rec[f"rev_{p}_high"] = _cell(rev, yp, "high")
        rec[f"rev_{p}_growth"] = _cell(rev, yp, "growth")
        rec[f"rev_{p}_analysts"] = _cell(rev, yp, "numberOfAnalysts")
        rec[f"eps_{p}"] = _cell(eps, yp, "avg")
        rec[f"eps_{p}_growth"] = _cell(eps, yp, "growth")
        rec[f"eps_{p}_30d_ago"] = _cell(trend, yp, "30daysAgo")
        rec[f"eps_{p}_90d_ago"] = _cell(trend, yp, "90daysAgo")
        rec[f"eps_{p}_up30"] = _cell(revisions, yp, "upLast30days")
        rec[f"eps_{p}_down30"] = _cell(revisions, yp, "downLast30days")

    # Some Yahoo payloads lack growth; derive it from year-ago revenue when possible.
    for yp, p in PERIODS.items():
        if rec[f"rev_{p}_growth"] is None:
            base = _cell(rev, yp, "yearAgoRevenue")
            if base and rec[f"rev_{p}"]:
                rec[f"rev_{p}_growth"] = rec[f"rev_{p}"] / base - 1

    price = rec["price"]
    for p in ("cy", "ny"):
        e = rec[f"eps_{p}"]
        rec[f"pe_{p}"] = price / e if price and e and e > 0 else None
    return rec


def _fetch_with_retry(ticker: str, retries: int = 2) -> dict:
    for attempt in range(retries + 1):
        try:
            return fetch_ticker(ticker)
        except Exception as exc:
            if attempt == retries:
                return {"ticker": ticker, "error": str(exc)[:200]}
            time.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


def fetch_many(
    tickers: Iterable[str],
    workers: int = 8,
    progress: Callable[[int, int, str], None] | None = None,
) -> pd.DataFrame:
    tickers = list(dict.fromkeys(tickers))
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_with_retry, t): t for t in tickers}
        for i, fut in enumerate(as_completed(futures), 1):
            rows.append(fut.result())
            if progress:
                progress(i, len(tickers), futures[fut])
    # One slow sequential pass for tickers that failed under parallel load (timeouts).
    for i, row in enumerate(rows):
        if row.get("error"):
            rows[i] = _fetch_with_retry(row["ticker"])
    return pd.DataFrame(rows)
