#!/bin/zsh
# Scheduled refresh, run by launchd (see scripts/com.forwardview.refresh.plist).
cd "$(dirname "$0")/.." || exit 1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') start"
.venv/bin/python -m forwardview.refresh sox ndx spx
rc=$?
echo "=== $(date '+%Y-%m-%d %H:%M:%S') exit $rc"
exit $rc
