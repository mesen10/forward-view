"""Nasdaq.com (Zacks data): annual EPS consensus for FY0 ... FY+3, free, no key.

Used for tickers the FMP plan does not cover. No revenue estimates; rows carry rev=None.
"""

from __future__ import annotations

import pandas as pd
import requests

from .universes import BROWSER_UA

URL = "https://api.nasdaq.com/api/analyst/{ticker}/earnings-forecast"


def fetch_annual_estimates(ticker: str) -> list[dict]:
    """Annual EPS rows in the FMP row format, oldest first; the first row is the current FY."""
    resp = requests.get(
        URL.format(ticker=ticker.replace("-", ".")),
        headers={"User-Agent": BROWSER_UA, "Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    rows = []
    for d in (data.get("yearlyForecast") or {}).get("rows") or []:
        # "Jan 2027" -> last day of that month
        fy_end = (pd.Timestamp(d["fiscalEnd"]) + pd.offsets.MonthEnd(0)).date().isoformat()
        rows.append({
            "fy_end": fy_end,
            "rev": None, "rev_low": None, "rev_high": None,
            "eps": d.get("consensusEPSForecast"),
            "eps_low": d.get("lowEPSForecast"),
            "eps_high": d.get("highEPSForecast"),
            "rev_analysts": None,
            "eps_analysts": d.get("noOfEstimates"),
            "src": "nasdaq",
        })
    if not rows:
        raise LookupError("no yearly forecast")
    return sorted(rows, key=lambda r: r["fy_end"])
