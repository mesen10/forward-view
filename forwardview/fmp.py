"""Financial Modeling Prep (FMP): multi-year annual analyst estimates (FY+1 ... FY+4).

Needs FMP_API_KEY in the environment or in .env at the project root.
The free plan only serves a small sample of symbols; others return HTTP 402.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import requests

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
BASE_URL = "https://financialmodelingprep.com/stable"


class InvalidKey(Exception):
    """FMP rejected the API key (HTTP 401)."""


class NotInPlan(Exception):
    """The current FMP subscription does not cover this symbol (HTTP 402)."""


def api_key() -> str | None:
    if os.environ.get("FMP_API_KEY"):
        return os.environ["FMP_API_KEY"]
    if ENV_PATH.exists():
        m = re.search(r"^FMP_API_KEY=(.*)$", ENV_PATH.read_text(), re.M)
        if m and m.group(1).strip():
            return m.group(1).strip().strip("'\"")
    return None


def fetch_annual_estimates(ticker: str, key: str) -> list[dict]:
    """Annual consensus rows, oldest first: fy_end, revenue/eps avg/low/high, analyst counts."""
    resp = requests.get(
        f"{BASE_URL}/analyst-estimates",
        params={"symbol": ticker, "period": "annual", "page": 0, "limit": 10, "apikey": key},
        timeout=30,
    )
    if resp.status_code == 401:
        raise InvalidKey("FMP rejected the API key (HTTP 401); check FMP_API_KEY in .env")
    if resp.status_code == 402:
        raise NotInPlan(ticker)
    if resp.status_code != 200:
        # Never echo the key back in errors.
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text.replace(key, '<key>')[:200]}")
    rows = [
        {
            "fy_end": d["date"],
            "rev": d.get("revenueAvg"),
            "rev_low": d.get("revenueLow"),
            "rev_high": d.get("revenueHigh"),
            "eps": d.get("epsAvg"),
            "eps_low": d.get("epsLow"),
            "eps_high": d.get("epsHigh"),
            "rev_analysts": d.get("numAnalystsRevenue"),
            "eps_analysts": d.get("numAnalystsEps"),
        }
        for d in resp.json()
    ]
    return sorted(rows, key=lambda r: r["fy_end"])
