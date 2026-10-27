"""CLI: python -m forwardview.estimates sox ndx hw energy

Fetches multi-year annual estimates for every member of the given universes: FMP first
(revenue + EPS), then Nasdaq.com (EPS only, free) for tickers the FMP plan does not cover.
Estimates move slowly, so tickers attempted within --max-age days are skipped; this keeps
daily runs inside FMP's free plan of 250 calls/day.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

from . import nasdaq, store
from .fmp import InvalidKey, NotInPlan, api_key, fetch_annual_estimates
from .universes import UNIVERSES


def universe_tickers(universes: list[str]) -> dict[str, float | None]:
    """ticker -> Yahoo current-FY EPS consensus (USD per traded share), from the latest snapshots."""
    tickers = {}
    for u in universes:
        dates = store.snapshot_dates(u)
        if dates:
            snap = store.load_snapshot(u, dates[0])
            eps = snap["eps_cy"] if "eps_cy" in snap else [None] * len(snap)
            tickers.update({t: (None if e != e else e) for t, e in zip(snap["ticker"], eps)})
    return tickers


def same_currency(rows: list[dict], eps_cy: float | None) -> bool:
    """False when FMP's EPS is clearly in another currency or share basis than the US listing (e.g. TSM in TWD)."""
    if not eps_cy or eps_cy <= 0:
        return True
    today = dt.date.today().isoformat()
    upcoming = [r["eps"] for r in rows if r["fy_end"] >= today and r.get("eps")]
    return not upcoming or 1 / 3 < upcoming[0] / eps_cy < 3


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fetch FY+1..FY+4 estimates from FMP, falling back to Nasdaq.")
    parser.add_argument("universes", nargs="*", default=["sox", "ndx", "hw", "energy"], choices=list(UNIVERSES))
    parser.add_argument("--max-age", type=int, default=7, help="skip tickers attempted within this many days")
    parser.add_argument("--max-calls", type=int, default=200, help="stop after this many FMP API calls")
    args = parser.parse_args(argv)

    key = api_key()
    if not key:
        print("[estimates] FMP_API_KEY not set (add it to .env); using Nasdaq only")

    cutoff = (dt.date.today() - dt.timedelta(days=args.max_age)).isoformat()
    last = store.last_estimate_attempts()
    status = store.estimate_status(list(last))
    eps_cy = universe_tickers(args.universes)
    todo = [t for t in eps_cy if last.get(t, "") <= cutoff]
    print(f"[estimates] {len(todo)} tickers to fetch (max {args.max_calls} FMP calls)")

    counts = {"ok": 0, "nasdaq": 0, "not_in_plan": 0, "error": 0}
    calls = 0
    for i, t in enumerate(todo, 1):
        try:
            # Skip FMP for tickers it already refused (or served in another currency); those go straight to Nasdaq.
            use_fmp = key and status.get(t) not in ("nasdaq", "not_in_plan")
            if use_fmp and calls >= args.max_calls:
                continue
            try:
                if not use_fmp:
                    raise NotInPlan(t)
                calls += 1
                rows = fetch_annual_estimates(t, key)
                if not same_currency(rows, eps_cy[t]):
                    raise NotInPlan(t)
                store.save_estimates(t, "ok", rows)
                counts["ok"] += 1
            except NotInPlan:
                try:
                    rows = nasdaq.fetch_annual_estimates(t)
                except LookupError:
                    store.save_estimates(t, "not_in_plan", None)
                    counts["not_in_plan"] += 1
                else:
                    store.save_estimates(t, "nasdaq", rows)
                    counts["nasdaq"] += 1
                time.sleep(0.3)
        except InvalidKey as exc:
            print(f"\n[estimates] {exc}")
            return 1
        except Exception as exc:  # network errors: retried on the next run (no row saved)
            print(f"[estimates] {t}: {exc}")
            counts["error"] += 1
        if sys.stdout.isatty():
            print(f"\r[estimates] {i}/{len(todo)} {t:<8}", end="", flush=True)
    print(
        f"\n[estimates] FMP {counts['ok']}, Nasdaq {counts['nasdaq']}, "
        f"no data {counts['not_in_plan']}, errors {counts['error']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
