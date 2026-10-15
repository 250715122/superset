#!/bin/bash
# Run the HTTP verification with a short-lived admin account.
# Usage: run_tab_access_http_check.sh <dashboard id> <viewer user:password>
set -u
cd "$(dirname "$0")" || exit 1
PY=${PY:-/opt/superset/venv/bin/python}
DASH="$1"
VIEWER="$2"
PW=$(head -c 24 /dev/urandom | base64 | tr -d '/+=')

"$PY" _tmp_admin.py add "$PW" 2>/dev/null | tail -1
"$PY" verify_tab_access_http.py --dashboard "$DASH" \
  --admin "tabverify_admin:$PW" --viewer "$VIEWER" 2>&1 | grep -v 'Loaded your LOCAL'
RC=${PIPESTATUS[0]}
"$PY" _tmp_admin.py drop 2>/dev/null | tail -1
exit "$RC"
