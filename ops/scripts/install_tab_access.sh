#!/bin/bash
# Install the per-tab access control backend into a Superset venv.
# Usage: bash _install_tab_access.sh <venv python> <site-packages/superset dir> <staging dir>
# The staging dir mirrors the package layout, e.g. <staging>/dashboards/api.py
set -e
PY="$1"
PKG="$2"
SRC="$3"
TS=$(date +%Y%m%d%H%M%S)
BACKUP="$(dirname "$PKG")/_tab_access_backup_$TS"

EXISTING="dashboards/api.py dashboards/schemas.py daos/dashboard.py models/dashboard.py security/manager.py commands/dashboard/update.py"
NEW="dashboards/tab_access.py"

for f in $EXISTING; do
  mkdir -p "$BACKUP/$(dirname "$f")"
  cp -p "$PKG/$f" "$BACKUP/$f"
done
echo "BACKUP|$BACKUP"

for f in $EXISTING $NEW; do
  [ -f "$SRC/$f" ] || { echo "MISSING|$f"; exit 1; }
  sed -i 's/\r$//' "$SRC/$f"
  cp "$SRC/$f" "$PKG/$f"
  echo "INSTALLED|$f|$(git hash-object "$PKG/$f" 2>/dev/null || md5sum "$PKG/$f" | cut -d' ' -f1)"
done

for f in $EXISTING $NEW; do
  "$PY" -m py_compile "$PKG/$f"
done
echo "COMPILE|OK"

# the import graph must stay acyclic: tab_access is pulled in by the security
# manager, which is imported very early during app creation
"$PY" -c "import superset.dashboards.tab_access as t; print('IMPORT|OK|%s' % t.TAB_ROLES_KEY)"
echo "INSTALL_DONE|$TS"
