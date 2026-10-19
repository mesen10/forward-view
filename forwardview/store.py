"""SQLite snapshot storage. One row per (snapshot_date, ticker); membership per universe."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "forwardview.db"


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE IF NOT EXISTS snapshots ("
        " snapshot_date TEXT, ticker TEXT, data TEXT,"
        " PRIMARY KEY (snapshot_date, ticker))"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS membership ("
        " snapshot_date TEXT, universe TEXT, ticker TEXT,"
        " PRIMARY KEY (snapshot_date, universe, ticker))"
    )
    # Multi-year annual estimates (FMP). status: ok | not_in_plan | error; data: JSON list of FY rows.
    con.execute(
        "CREATE TABLE IF NOT EXISTS estimates ("
        " fetch_date TEXT, ticker TEXT, status TEXT, data TEXT,"
        " PRIMARY KEY (fetch_date, ticker))"
    )
    return con


def save_snapshot(universe: str, members: list[str], rows: pd.DataFrame, date: str | None = None) -> str:
    """Store fetched rows as JSON blobs so new fields never require a migration."""
    date = date or dt.date.today().isoformat()
    with connect() as con:
        con.execute("DELETE FROM membership WHERE snapshot_date = ? AND universe = ?", (date, universe))
        con.executemany(
            "INSERT OR REPLACE INTO membership VALUES (?, ?, ?)",
            [(date, universe, t) for t in members],
        )
        records = rows.astype(object).where(rows.notna(), None).to_dict("records")
        con.executemany(
            "INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?)",
            [(date, r["ticker"], json.dumps(r)) for r in records],
        )
    return date


def snapshot_dates(universe: str) -> list[str]:
    with connect() as con:
        cur = con.execute(
            "SELECT DISTINCT snapshot_date FROM membership WHERE universe = ? ORDER BY snapshot_date DESC",
            (universe,),
        )
        return [r[0] for r in cur]


def load_snapshot(universe: str, date: str) -> pd.DataFrame:
    with connect() as con:
        cur = con.execute(
            "SELECT s.data FROM membership m JOIN snapshots s"
            " ON s.snapshot_date = m.snapshot_date AND s.ticker = m.ticker"
            " WHERE m.universe = ? AND m.snapshot_date = ?",
            (universe, date),
        )
        return pd.DataFrame([json.loads(r[0]) for r in cur])


def load_history(universe: str) -> pd.DataFrame:
    """All snapshots for a universe, with a snapshot_date column."""
    with connect() as con:
        cur = con.execute(
            "SELECT m.snapshot_date, s.data FROM membership m JOIN snapshots s"
            " ON s.snapshot_date = m.snapshot_date AND s.ticker = m.ticker"
            " WHERE m.universe = ? ORDER BY m.snapshot_date",
            (universe,),
        )
        rows = [{"snapshot_date": d, **json.loads(blob)} for d, blob in cur]
    return pd.DataFrame(rows)


def save_estimates(ticker: str, status: str, rows: list[dict] | None, date: str | None = None) -> None:
    date = date or dt.date.today().isoformat()
    with connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO estimates VALUES (?, ?, ?, ?)",
            (date, ticker, status, json.dumps(rows) if rows is not None else None),
        )


def last_estimate_attempts() -> dict[str, str]:
    """ticker -> date of the most recent fetch attempt (any status)."""
    with connect() as con:
        return dict(con.execute("SELECT ticker, MAX(fetch_date) FROM estimates GROUP BY ticker"))


def load_estimates(tickers: list[str]) -> dict[str, list[dict]]:
    """ticker -> FY rows from the latest successful fetch."""
    with connect() as con:
        cur = con.execute(
            "SELECT e.ticker, e.data FROM estimates e JOIN ("
            "  SELECT ticker, MAX(fetch_date) AS d FROM estimates WHERE status = 'ok' GROUP BY ticker"
            ") latest ON e.ticker = latest.ticker AND e.fetch_date = latest.d"
        )
        wanted = set(tickers)
        return {t: json.loads(blob) for t, blob in cur if t in wanted}


def estimate_status(tickers: list[str]) -> dict[str, str]:
    """ticker -> status of the most recent attempt."""
    with connect() as con:
        cur = con.execute(
            "SELECT e.ticker, e.status FROM estimates e JOIN ("
            "  SELECT ticker, MAX(fetch_date) AS d FROM estimates GROUP BY ticker"
            ") latest ON e.ticker = latest.ticker AND e.fetch_date = latest.d"
        )
        wanted = set(tickers)
        return {t: s for t, s in cur if t in wanted}
