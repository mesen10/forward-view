#!/bin/zsh
# Scheduled refresh, run by launchd (see scripts/com.forwardview.refresh.plist).
cd "$(dirname "$0")/.." || exit 1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') start"
.venv/bin/python -m forwardview.refresh sox ndx spx hw energy
rc=$?
# FY+1..FY+4 from FMP; only tickers older than 7 days are fetched, so daily runs stay in the free quota.
.venv/bin/python -m forwardview.estimates sox ndx hw energy || rc=1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') exit $rc"
exit $rc
