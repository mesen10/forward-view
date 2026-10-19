"""CLI: python -m forwardview.estimates sox ndx hw energy

Fetches multi-year annual estimates from FMP for every member of the given universes.
Estimates move slowly, so tickers attempted within --max-age days are skipped; this keeps
daily runs inside the free plan's 250 calls/day.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from . import store
from .fmp import InvalidKey, NotInPlan, api_key, fetch_annual_estimates
from .universes import UNIVERSES


def universe_tickers(universes: list[str]) -> list[str]:
    tickers = []
    for u in universes:
        dates = store.snapshot_dates(u)
        if dates:
            tickers += store.load_snapshot(u, dates[0])["ticker"].tolist()
    return list(dict.fromkeys(tickers))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fetch FY+1..FY+4 estimates from FMP.")
    parser.add_argument("universes", nargs="*", default=["sox", "ndx", "hw", "energy"], choices=list(UNIVERSES))
    parser.add_argument("--max-age", type=int, default=7, help="skip tickers attempted within this many days")
    parser.add_argument("--max-calls", type=int, default=200, help="stop after this many API calls")
    args = parser.parse_args(argv)

    key = api_key()
    if not key:
        print("FMP_API_KEY not set (add it to .env)")
        return 1

    cutoff = (dt.date.today() - dt.timedelta(days=args.max_age)).isoformat()
    last = store.last_estimate_attempts()
    todo = [t for t in universe_tickers(args.universes) if last.get(t, "") < cutoff]
    print(f"[estimates] {len(todo)} tickers to fetch (max {args.max_calls} calls)")

    counts = {"ok": 0, "not_in_plan": 0, "error": 0}
    for i, t in enumerate(todo[: args.max_calls], 1):
        try:
            store.save_estimates(t, "ok", fetch_annual_estimates(t, key))
            counts["ok"] += 1
        except InvalidKey as exc:
            print(f"\n[estimates] {exc}")
            return 1
        except NotInPlan:
            store.save_estimates(t, "not_in_plan", None)
            counts["not_in_plan"] += 1
        except Exception as exc:  # network errors: retried on the next run (no row saved)
            print(f"[estimates] {t}: {exc}")
            counts["error"] += 1
        if sys.stdout.isatty():
            print(f"\r[estimates] {i}/{min(len(todo), args.max_calls)} {t:<8}", end="", flush=True)
    print(f"\n[estimates] ok {counts['ok']}, not in plan {counts['not_in_plan']}, errors {counts['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
