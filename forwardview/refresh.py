"""CLI: python -m forwardview.refresh sox ndx spx hw energy"""

from __future__ import annotations

import argparse
import sys

from .fetch import fetch_many
from .store import save_snapshot
from .universes import UNIVERSES, load_universe


def refresh(universe: str, progress=None, workers: int = 8) -> tuple[str, int, int]:
    members = load_universe(universe)
    rows = fetch_many(members["ticker"], workers=workers, progress=progress)
    # Fill gaps (e.g. names, sectors) from the index source.
    meta = members.set_index("ticker")
    for col, src in (("name", "name"), ("sector", "index_sector"), ("industry", "index_industry")):
        if col not in rows:
            rows[col] = None
        fallback = rows["ticker"].map(meta[src]).replace("", None)
        rows[col] = rows[col].where(rows[col].notna() & (rows[col] != ""), fallback)
    errors = int(rows["error"].notna().sum()) if "error" in rows else 0
    date = save_snapshot(universe, members["ticker"].tolist(), rows)
    return date, len(rows), errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fetch a fresh snapshot for one or more universes.")
    parser.add_argument("universes", nargs="*", default=["sox", "ndx"], choices=list(UNIVERSES))
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)

    for u in args.universes:
        def progress(i, n, ticker):
            print(f"\r[{u}] {i}/{n} {ticker:<8}", end="", flush=True)

        # Skip the progress line when output goes to a log file (scheduled runs).
        date, n, errors = refresh(u, progress if sys.stdout.isatty() else None, args.workers)
        print(f"\n[{u}] saved {n} tickers for {date} ({errors} errors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
