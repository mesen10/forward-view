"""Index constituent lists.

Each loader returns a DataFrame with at least: ticker, name, sector, industry.
Sector/industry may be empty here; they are filled from Yahoo during fetch.
"""

from __future__ import annotations

import datetime as dt
from io import StringIO

import pandas as pd
import requests

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
)

# Fallback if the Nasdaq index site is unreachable. Snapshot of SOX members, Oct 2026.
SOX_FALLBACK = [
    "ADI", "ALAB", "AMAT", "AMD", "ARM", "ASML", "AVGO", "COHR", "CRDO", "ENTG",
    "GFS", "INTC", "KLAC", "LRCX", "MCHP", "MPWR", "MRVL", "MU", "NVDA", "NXPI",
    "ON", "QCOM", "SWKS", "TER", "TSM", "TXN", "QRVO", "MTSI", "LSCC", "STM",
]

UNIVERSES = {
    "sox": "PHLX Semiconductor (SOX)",
    "ndx": "Nasdaq-100",
    "spx": "S&P 500",
    "hw": "S&P 500 Tech Hardware",
    "energy": "S&P 500 Energy",
}

# GICS "Technology Hardware & Equipment" industry group, by sub-industry.
HARDWARE_SUB_INDUSTRIES = {
    "Technology Hardware, Storage & Peripherals",
    "Communications Equipment",
    "Electronic Equipment & Instruments",
    "Electronic Components",
    "Electronic Manufacturing Services",
    "Technology Distributors",
}


def to_yahoo_symbol(symbol: str) -> str:
    """Yahoo uses '-' for share classes (BRK.B -> BRK-B)."""
    return symbol.strip().upper().replace(".", "-").replace("/", "-")


def _frame(tickers, names=None, sectors=None, industries=None) -> pd.DataFrame:
    n = len(tickers)
    df = pd.DataFrame({
        "ticker": [to_yahoo_symbol(t) for t in tickers],
        "name": names or [""] * n,
        "index_sector": sectors or [""] * n,
        "index_industry": industries or [""] * n,
    })
    return df.drop_duplicates("ticker").reset_index(drop=True)


def load_sox() -> pd.DataFrame:
    headers = {"User-Agent": BROWSER_UA, "X-Requested-With": "XMLHttpRequest"}
    try:
        session = requests.Session()
        session.get("https://indexes.nasdaqomx.com/Index/Weighting/SOX", headers=headers, timeout=20)
        trade_date = dt.date.today().strftime("%Y-%m-%dT00:00:00.000")
        resp = session.post(
            "https://indexes.nasdaqomx.com/Index/WeightingData",
            data={"id": "SOX", "tradeDate": trade_date, "timeOfDay": "SOD"},
            headers=headers,
            timeout=20,
        )
        resp.raise_for_status()
        rows = resp.json()["aaData"]
        if len(rows) >= 20:
            return _frame([r["Symbol"] for r in rows], [r["Name"].title() for r in rows])
    except Exception as exc:  # network or format change
        print(f"[sox] live list failed ({exc}); using fallback list")
    return _frame(SOX_FALLBACK)


def load_ndx() -> pd.DataFrame:
    resp = requests.get(
        "https://api.nasdaq.com/api/quote/list-type/nasdaq100",
        headers={"User-Agent": BROWSER_UA, "Accept": "application/json"},
        timeout=20,
    )
    resp.raise_for_status()
    rows = resp.json()["data"]["data"]["rows"]
    return _frame(
        [r["symbol"] for r in rows],
        [r["companyName"] for r in rows],
        [r.get("sector") or "" for r in rows],
    )


def load_spx() -> pd.DataFrame:
    html = requests.get(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        headers={"User-Agent": "forwardview/0.1 (personal research)"},
        timeout=20,
    ).text
    table = pd.read_html(StringIO(html))[0]
    return _frame(
        table["Symbol"].tolist(),
        table["Security"].tolist(),
        table["GICS Sector"].tolist(),
        table["GICS Sub-Industry"].tolist(),
    )


def load_hw() -> pd.DataFrame:
    spx = load_spx()
    return spx[spx["index_industry"].isin(HARDWARE_SUB_INDUSTRIES)].reset_index(drop=True)


def load_energy() -> pd.DataFrame:
    spx = load_spx()
    return spx[spx["index_sector"] == "Energy"].reset_index(drop=True)


LOADERS = {"sox": load_sox, "ndx": load_ndx, "spx": load_spx, "hw": load_hw, "energy": load_energy}


def load_universe(key: str) -> pd.DataFrame:
    return LOADERS[key]()
