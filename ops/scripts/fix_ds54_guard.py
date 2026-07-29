# -*- coding: utf-8 -*-
"""Guard dataset 54 (公开用电池包明细) against naked full-table aggregation.

bluetti.dwd_iot_pack holds 7.1e9 rows (57M/day). The virtual dataset prunes
partitions via get_time_filter("time"), and the dashboard's time filter is
required with a "Last week" default -- so dashboard queries are always small.
But a query WITHOUT a time filter (saved query_context replayed by a bot, a
crafted /api/v1/chart/data payload, a maker exploring the dataset) skips
partition pruning entirely and aggregates the whole table until StarRocks
kills it with "Memory of process exceed limit".

Fix: append a guard to the dataset SQL -- when no time filter reaches the
query, return zero rows instead of scanning 7.1 billion.

Usage: python fix_ds54_guard.py [apply|revert] [--force]
  apply   backup SQL to backups/ds54_sql_<ts>.txt, append guard (idempotent),
          then verify: naked chart-data returns 200/0 rows fast, and a
          dashboard-style query (time + device filter) still returns data.
          Aborts if any chart on dashboard 17 is excluded from the time
          filter's scope (it would silently go empty) unless --force.
  revert  restore the newest backup file.
"""
import json
import os
import sys
import time

CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from superset.app import create_app  # noqa: E402

CMD = next((a for a in sys.argv[1:] if not a.startswith("-")), "apply")
FORCE = "--force" in sys.argv
DS_ID = 54
DASH_ID = 17
MARKER = "GUARD_NO_TIME_FILTER"
GUARD = (
    "\n    {# " + MARKER + ": dwd_iot_pack 有 71 亿行, 没有时间筛选就没有 pt 分区裁剪,"
    "\n       全表聚合必然打爆 StarRocks 内存; 裸查一律返回空. 看板的时间筛选是必填项,"
    "\n       正常使用不受影响; Explore 里请先加 time 的时间范围条件. #}"
    "\n    {% if not tf.from_expr and not tf.to_expr %}"
    "\n        AND 1 = 0"
    "\n    {% endif %}")


def e(s):
    return (s or "").encode("unicode_escape").decode()


app = create_app()
app.config["WTF_CSRF_ENABLED"] = False


def chart_data(uid, payload):
    with app.app_context():
        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess["_user_id"] = str(uid)
                sess["_fresh"] = True
            t0 = time.time()
            r = c.post("/api/v1/chart/data", json=payload)
            dt = time.time() - t0
            rows = None
            if r.status_code == 200:
                try:
                    rows = r.get_json()["result"][0]["rowcount"]
                except Exception:  # noqa: BLE001
                    rows = -1
            return r.status_code, rows, dt, r.get_data(as_text=True)[:90]


with app.app_context():
    from superset import db, security_manager as sm
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.dashboard import Dashboard
    from superset.models.slice import Slice

    t = db.session.get(SqlaTable, DS_ID)
    bdir = os.path.join(os.path.dirname(CONF), "backups")
    os.makedirs(bdir, exist_ok=True)

    if CMD == "revert":
        baks = sorted(f for f in os.listdir(bdir)
                      if f.startswith("ds54_sql_"))
        if not baks:
            print("ABORT|no backup found")
            sys.exit(1)
        with open(os.path.join(bdir, baks[-1])) as f:
            t.sql = f.read()
        db.session.commit()
        print("REVERTED|from %s|marker_present=%s"
              % (baks[-1], MARKER in (t.sql or "")))
        sys.exit(0)

    # --- scope pre-check: the time filter must reach every ds54 chart ------
    d = db.session.get(Dashboard, DASH_ID)
    meta = json.loads(d.json_metadata or "{}")
    ds54_charts = [s.id for s in d.slices if s.datasource_id == DS_ID]
    for f in meta.get("native_filter_configuration", []):
        if f.get("filterType") != "filter_time":
            continue
        excluded = f.get("scope", {}).get("excluded", [])
        bad = sorted(set(excluded) & set(ds54_charts))
        print("SCOPE|filter=%s|excluded=%s|ds54_charts=%s|conflict=%s"
              % (e(f.get("name")), excluded, ds54_charts, bad))
        if bad and not FORCE:
            print("ABORT|time filter does not reach charts %s -- they would "
                  "go empty; rerun with --force to override" % bad)
            sys.exit(1)

    if MARKER in (t.sql or ""):
        print("SKIP|guard already present")
    else:
        bak = os.path.join(bdir, "ds54_sql_%s.txt"
                           % time.strftime("%Y%m%d_%H%M%S"))
        with open(bak, "w") as f:
            f.write(t.sql or "")
        print("BACKUP|%s|%d bytes" % (bak, len(t.sql or "")))
        t.sql = (t.sql or "") + GUARD
        db.session.commit()
        print("APPLIED|guard appended")

    # --- verification as a real viewer -------------------------------------
    s = db.session.get(Slice, 200)
    viewer = next(u for u in sm.get_all_users() if u.is_active
                  and any(r.name.startswith("看板·电池包")
                          for r in sm.get_user_roles(u)))
    uid, uname = viewer.id, viewer.username

    naked = json.loads(s.query_context)
    naked.setdefault("form_data", {})["dashboardId"] = DASH_ID
    naked["form_data"]["slice_id"] = s.id
    naked["result_format"] = "json"
    naked["result_type"] = "full"

    real = json.loads(s.query_context)
    real.setdefault("form_data", {})["dashboardId"] = DASH_ID
    real["form_data"]["slice_id"] = s.id
    real["result_format"] = "json"
    real["result_type"] = "full"
    # mimic the SPA: the native time filter REPLACES the chart's own
    # "No filter" TEMPORAL_RANGE entry (appending a second entry would leave
    # get_time_filter reading the first, "No filter", one)
    for q in real["queries"]:
        flt = q.setdefault("filters", [])
        hit = False
        for f in flt:
            if f.get("op") == "TEMPORAL_RANGE" and f.get("col") == "time":
                f["val"] = "Last week"
                hit = True
        if not hit:
            flt.append({"col": "time", "op": "TEMPORAL_RANGE",
                        "val": "Last week"})
        flt.append({"col": "设备SN", "op": "IN",
                    "val": ["EBOX2510000170266_41"]})

print("VERIFY_AS|%s" % e(uname))
code, rows, dt, body = chart_data(uid, naked)
print("NAKED|http=%s|rows=%s|%.1fs|%s" % (code, rows, dt,
                                          e(body) if code != 200 else ""))
code2, rows2, dt2, body2 = chart_data(uid, real)
print("FILTERED|http=%s|rows=%s|%.1fs|%s" % (code2, rows2, dt2,
                                             e(body2) if code2 != 200 else ""))
ok = code == 200 and rows == 0 and code2 == 200 and (rows2 or 0) > 0
print("GUARD_RESULT|%s" % ("OK" if ok else "CHECK_MANUALLY"))
