#!/bin/bash
# Snapshot every user's effective StarRocks privileges.
#
# sys.grants_to_roles takes ~11s to scan on this cluster, so expanding role
# membership live made the 用户权限 chart (dashboard 38, slice 557) cost 12s per
# page.  Privileges change rarely, so the expansion is materialised once a day
# instead and the chart reads the newest snapshot.
#
# Scheduled by DolphinScheduler (project 数据中台, workflow
# ads_sr_global_user_privileges) on 10.100.21.202.  Credentials come from
# /data/bi-sync/.sr_env so nothing secret lives in this file.
set -euo pipefail

BASE_DIR=${BASE_DIR:-$(cd "$(dirname "$0")" && pwd)}
# shellcheck disable=SC1091
[ -f "$BASE_DIR/.sr_env" ] && . "$BASE_DIR/.sr_env"
SR_HOST=${SR_HOST:-10.100.11.201}
SR_PORT=${SR_PORT:-9030}
SR_USER=${SR_USER:-agi}
SR_PASS=${SR_PASS:?SR_PASS not set (expected in $BASE_DIR/.sr_env)}
KEEP=${KEEP:-3}
TABLE=bluetti.ads_sr_global_user_privileges
LOCK=${LOCK:-/tmp/sync_sr_user_privileges.lock}
LOG_PREFIX="SR_USER_PRIV_SYNC"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$LOG_PREFIX|SKIP_LOCKED|another run holds $LOCK"
  exit 1
fi

MYSQL=(mysql -h"$SR_HOST" -P"$SR_PORT" -u"$SR_USER" -p"$SR_PASS")

"${MYSQL[@]}" -e "
CREATE TABLE IF NOT EXISTS $TABLE (
  snapshot_ts     DATETIME,
  user_name       VARCHAR(128),
  granted_via     VARCHAR(256),
  object_catalog  VARCHAR(128),
  object_database VARCHAR(256),
  object_name     VARCHAR(512),
  object_type     VARCHAR(64),
  privilege_type  VARCHAR(512),
  is_grantable    VARCHAR(8)
)
DUPLICATE KEY(snapshot_ts, user_name)
DISTRIBUTED BY HASH(user_name) BUCKETS 3
PROPERTIES(\"replication_num\"=\"1\")"

TS=$(date '+%F %T')

# One INSERT so every row of a snapshot shares the same snapshot_ts; readers
# take MAX(snapshot_ts) and therefore never see a half written batch.
"${MYSQL[@]}" -e "
INSERT INTO $TABLE
SELECT
  '$TS',
  regexp_replace(SUBSTRING_INDEX(GRANTEE, '@', 1), \"'\", ''),
  '直接授权',
  COALESCE(OBJECT_CATALOG, ''),
  COALESCE(OBJECT_DATABASE, ''),
  COALESCE(OBJECT_NAME, ''),
  OBJECT_TYPE,
  PRIVILEGE_TYPE,
  IS_GRANTABLE
FROM sys.grants_to_users
UNION ALL
SELECT
  '$TS',
  regexp_replace(SUBSTRING_INDEX(e.TO_USER, '@', 1), \"'\", ''),
  CONCAT('角色 ', r.GRANTEE),
  COALESCE(r.OBJECT_CATALOG, ''),
  COALESCE(r.OBJECT_DATABASE, ''),
  COALESCE(r.OBJECT_NAME, ''),
  r.OBJECT_TYPE,
  r.PRIVILEGE_TYPE,
  r.IS_GRANTABLE
FROM sys.grants_to_roles r
JOIN sys.role_edges e ON e.FROM_ROLE = r.GRANTEE
WHERE e.TO_USER IS NOT NULL AND e.TO_USER != ''"

rows=$("${MYSQL[@]}" -N -e "SELECT COUNT(*) FROM $TABLE WHERE snapshot_ts = '$TS'")
users=$("${MYSQL[@]}" -N -e "SELECT COUNT(DISTINCT user_name) FROM $TABLE WHERE snapshot_ts = '$TS'")
if [ "$rows" -eq 0 ]; then
  echo "$LOG_PREFIX|EMPTY|snapshot=$TS produced no rows, leaving older ones in place"
  exit 1
fi

# Keep the newest $KEEP snapshots. DELETE needs a literal on the key column,
# so the cutoff is resolved first rather than passed as a subquery.
cutoff=$("${MYSQL[@]}" -N -e "
  SELECT MIN(snapshot_ts) FROM (
    SELECT DISTINCT snapshot_ts FROM $TABLE ORDER BY snapshot_ts DESC LIMIT $KEEP
  ) t")
"${MYSQL[@]}" -e "DELETE FROM $TABLE WHERE snapshot_ts < '$cutoff'"
kept=$("${MYSQL[@]}" -N -e "SELECT COUNT(DISTINCT snapshot_ts) FROM $TABLE")

echo "$LOG_PREFIX|OK|snapshot=$TS|rows=$rows|users=$users|snapshots_kept=$kept"
