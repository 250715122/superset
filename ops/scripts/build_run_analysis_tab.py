# -*- coding: utf-8 -*-
"""Build the 运行分析 tab on dashboard dp-sr-global (数据中台速览).

All datasets query StarRocks live (audit log + information_schema + SHOW PROC);
nothing depends on the stale ads_ops_cockpit_* / ads_sr_global_* snapshots.

Also repoints the existing 用户清单 chart to a dataset that carries each
account's configured resource group, collected hourly by sync_sr_rg_bindings.py.

Idempotent: re-running replaces the tab content and updates the charts in place.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

CONF = "/mnt/data/superset/superset_config.py"
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from flask_login import login_user  # noqa: E402
from flask_appbuilder.security.sqla.models import User  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402
from superset.app import create_app  # noqa: E402

app = create_app()
app.config["WTF_CSRF_ENABLED"] = False

DB_MAIN = 12          # 数据中台 — can run SHOW PROC '/current_queries'
DB_PRIV = 18          # 数据中台-dashboard — can run SHOW USERS
SCHEMA = "bluetti"
SLUG = "dp-sr-global"
TAB_TEXT = "运行分析"
BACKUP_DIR = "/mnt/data/superset/backups"

# --------------------------------------------------------------------------
# dataset SQL
# --------------------------------------------------------------------------

AUDIT_SQL = r"""
SELECT
  `timestamp` AS ts,
  CASE UPPER(regexp_extract(TRIM(stmt), '^[A-Za-z]+', 0))
    WHEN 'SELECT' THEN 'SELECT' WHEN 'WITH' THEN 'SELECT'
    WHEN 'INSERT' THEN 'INSERT' WHEN 'UPDATE' THEN 'UPDATE'
    WHEN 'DELETE' THEN 'DELETE' WHEN 'SET' THEN 'SET'
    WHEN 'SHOW' THEN 'SHOW' WHEN 'CREATE' THEN 'CREATE'
    WHEN 'ALTER' THEN 'ALTER' WHEN 'DROP' THEN 'DROP'
    WHEN 'TRUNCATE' THEN 'TRUNCATE' WHEN 'COMMIT' THEN 'COMMIT'
    WHEN 'BEGIN' THEN 'BEGIN' WHEN 'ROLLBACK' THEN 'ROLLBACK'
    WHEN 'ADMIN' THEN 'ADMIN' WHEN 'ANALYZE' THEN 'ANALYZE'
    WHEN 'DESCRIBE' THEN 'DESCRIBE' WHEN 'USE' THEN 'USE'
    ELSE 'OTHER'
  END AS task_kind,
  `user` AS user_name,
  CASE WHEN resourceGroup IS NULL OR resourceGroup = '' THEN '-' ELSE resourceGroup END AS resource_group,
  CASE WHEN `db` IS NULL OR `db` = '' THEN '-' ELSE `db` END AS db_name,
  state AS exec_state,
  CASE WHEN errorCode IS NULL OR errorCode = '' THEN '-' ELSE errorCode END AS error_code,
  queryType AS query_type,
  queryTime AS query_ms,
  ROUND(cpuCostNs / 1000000000, 3) AS cpu_sec,
  ROUND(memCostBytes / 1048576, 2) AS mem_mb,
  scanRows AS scan_rows,
  scanBytes AS scan_bytes,
  returnRows AS return_rows,
  pendingTimeMs AS pending_ms,
  clientIp AS client_ip,
  queryId AS query_id,
  digest AS digest,
  SUBSTR(stmt, 1, 1000) AS stmt_head
FROM audit_db.audit
"""

AUDIT_COLS = [
    ("ts", "DATETIME", True), ("task_kind", "VARCHAR", False),
    ("user_name", "VARCHAR", False), ("resource_group", "VARCHAR", False),
    ("db_name", "VARCHAR", False), ("exec_state", "VARCHAR", False),
    ("error_code", "VARCHAR", False), ("query_type", "VARCHAR", False),
    ("query_ms", "BIGINT", False), ("cpu_sec", "DOUBLE", False),
    ("mem_mb", "DOUBLE", False), ("scan_rows", "BIGINT", False),
    ("scan_bytes", "BIGINT", False), ("return_rows", "BIGINT", False),
    ("pending_ms", "BIGINT", False), ("client_ip", "VARCHAR", False),
    ("query_id", "VARCHAR", False), ("digest", "VARCHAR", False),
    ("stmt_head", "VARCHAR", False),
]

CURQ_SQL = "SHOW PROC '/current_queries'"
CURQ_COLS = [
    ("StartTime", "VARCHAR", False), ("QueryId", "VARCHAR", False),
    ("User", "VARCHAR", False), ("Database", "VARCHAR", False),
    ("ResourceGroup", "VARCHAR", False), ("ExecState", "VARCHAR", False),
    ("ExecTime", "VARCHAR", False), ("CPUTime", "VARCHAR", False),
    ("MemoryUsage", "VARCHAR", False), ("DiskSpillSize", "VARCHAR", False),
    ("ScanRows", "VARCHAR", False), ("ScanBytes", "VARCHAR", False),
    ("ExecProgress", "VARCHAR", False), ("Warehouse", "VARCHAR", False),
    ("feIp", "VARCHAR", False), ("ConnectionId", "VARCHAR", False),
    ("CustomQueryId", "VARCHAR", False),
]

# information_schema.loads keeps roughly one day of jobs and is dominated by
# per-table stream/insert loads, so roll it up instead of listing raw jobs.
LOADS_SQL = r"""
SELECT
  DB_NAME AS db_name,
  TABLE_NAME AS table_name,
  `TYPE` AS load_type,
  COUNT(*) AS job_n,
  SUM(CASE WHEN STATE = 'FINISHED' THEN 1 ELSE 0 END) AS finished_n,
  SUM(CASE WHEN STATE IN ('CANCELLED', 'FAILED', 'ERROR') THEN 1 ELSE 0 END) AS failed_n,
  SUM(CASE WHEN STATE NOT IN ('FINISHED', 'CANCELLED', 'FAILED', 'ERROR') THEN 1 ELSE 0 END) AS running_n,
  SUM(SINK_ROWS) AS sink_rows,
  SUM(FILTERED_ROWS) AS filtered_rows,
  CAST(MAX(CREATE_TIME) AS VARCHAR) AS last_create_time,
  CAST(MAX(LOAD_FINISH_TIME) AS VARCHAR) AS last_finish_time,
  MAX(ERROR_MSG) AS last_error
FROM information_schema.loads
GROUP BY 1, 2, 3
"""

LOADS_COLS = [
    ("db_name", "VARCHAR", False), ("table_name", "VARCHAR", False),
    ("load_type", "VARCHAR", False), ("job_n", "BIGINT", False),
    ("finished_n", "BIGINT", False), ("failed_n", "BIGINT", False),
    ("running_n", "BIGINT", False), ("sink_rows", "BIGINT", False),
    ("filtered_rows", "BIGINT", False),
    ("last_create_time", "VARCHAR", False),
    ("last_finish_time", "VARCHAR", False), ("last_error", "VARCHAR", False),
]

MV_SQL = r"""
SELECT
  TABLE_SCHEMA AS db_name,
  TABLE_NAME AS mv_name,
  REFRESH_TYPE AS refresh_type,
  IS_ACTIVE AS is_active,
  LAST_REFRESH_STATE AS last_refresh_state,
  CAST(LAST_REFRESH_FINISHED_TIME AS VARCHAR) AS last_refresh_time,
  LAST_REFRESH_DURATION AS last_refresh_sec,
  QUERY_REWRITE_STATUS AS rewrite_status,
  TABLE_ROWS AS row_n,
  CREATOR AS creator,
  INACTIVE_REASON AS inactive_reason,
  LAST_REFRESH_ERROR_MESSAGE AS last_error
FROM information_schema.materialized_views
"""

MV_COLS = [
    ("db_name", "VARCHAR", False), ("mv_name", "VARCHAR", False),
    ("refresh_type", "VARCHAR", False), ("is_active", "VARCHAR", False),
    ("last_refresh_state", "VARCHAR", False),
    ("last_refresh_time", "VARCHAR", False),
    ("last_refresh_sec", "DOUBLE", False), ("rewrite_status", "VARCHAR", False),
    ("row_n", "BIGINT", False), ("creator", "VARCHAR", False),
    ("inactive_reason", "VARCHAR", False), ("last_error", "VARCHAR", False),
]

TASKFAIL_SQL = r"""
SELECT
  CREATE_TIME AS create_time,
  FINISH_TIME AS finish_time,
  TASK_NAME AS task_name,
  STATE AS state,
  `DATABASE` AS db_name,
  ERROR_CODE AS error_code,
  ERROR_MESSAGE AS error_message,
  SUBSTR(DEFINITION, 1, 500) AS definition_head
FROM information_schema.task_runs
WHERE STATE NOT IN ('SUCCESS', 'MERGED', 'SKIPPED')
   OR (ERROR_MESSAGE IS NOT NULL AND ERROR_MESSAGE != '')
"""

TASKFAIL_COLS = [
    ("create_time", "DATETIME", True), ("finish_time", "DATETIME", True),
    ("task_name", "VARCHAR", False), ("state", "VARCHAR", False),
    ("db_name", "VARCHAR", False), ("error_code", "VARCHAR", False),
    ("error_message", "VARCHAR", False), ("definition_head", "VARCHAR", False),
]

USERS_SQL = r"""
SELECT
  u.user_name AS user_name,
  COALESCE(b.rg_list, '-') AS resource_group,
  COALESCE(a.query_n, 0) AS query_n_7d
FROM (
  SELECT DISTINCT regexp_replace(SUBSTRING_INDEX(GRANTEE, '@', 1), "'", '') AS user_name
  FROM sys.grants_to_users
  UNION
  SELECT DISTINCT regexp_replace(SUBSTRING_INDEX(TO_USER, '@', 1), "'", '') AS user_name
  FROM sys.role_edges
  WHERE TO_USER IS NOT NULL AND TO_USER != ''
  UNION
  SELECT DISTINCT `user` AS user_name
  FROM audit_db.audit
  WHERE `timestamp` >= CURRENT_DATE() - INTERVAL 30 DAY
    AND `user` IS NOT NULL AND `user` != ''
) u
LEFT JOIN (
  SELECT user_name, GROUP_CONCAT(DISTINCT rg_name) AS rg_list
  FROM bluetti.ads_sr_global_rg_bindings
  WHERE snapshot_ts = (SELECT MAX(snapshot_ts) FROM bluetti.ads_sr_global_rg_bindings)
    AND user_name IS NOT NULL AND user_name != ''
  GROUP BY user_name
) b ON b.user_name = u.user_name
LEFT JOIN (
  SELECT `user` AS user_name, COUNT(*) AS query_n
  FROM audit_db.audit
  WHERE `timestamp` >= CURRENT_DATE() - INTERVAL 7 DAY
  GROUP BY `user`
) a ON a.user_name = u.user_name
"""

USERS_COLS = [
    ("user_name", "VARCHAR", False), ("resource_group", "VARCHAR", False),
    ("query_n_7d", "BIGINT", False),
]

USERS_VERBOSE = {
    "user_name": "用户",
    "resource_group": "资源组",
    "query_n_7d": "近7天查询数",
}
USERS_COLUMN_CONFIG = {
    "用户": {"column_title": "用户"},
    "资源组": {"column_title": "资源组"},
    "近7天查询数": {"column_title": "近7天查询数", "showCellBars": True},
}
USERS_DESC = ("用户清单。资源组取 SHOW RESOURCE GROUPS ALL 的 classifier 配置绑定"
              "（每小时采集），不是审计日志里实际跑过的组；无 classifier 的用户"
              "显示 -，实际落 default_wg。")


def rid(prefix):
    return "%s-%s" % (prefix, uuid.uuid4().hex[:10])


def metric(sql, label):
    return {
        "expressionType": "SQL",
        "sqlExpression": sql,
        "label": label,
        "hasCustomLabel": True,
        "optionName": "metric_%s" % uuid.uuid4().hex[:10],
        "aggregate": None,
        "column": None,
        "datasourceWarning": False,
    }


def temporal_filter(col, comparator):
    return {
        "clause": "WHERE",
        "subject": col,
        "operator": "TEMPORAL_RANGE",
        "comparator": comparator,
        "expressionType": "SIMPLE",
        "filterOptionName": "filter_%s" % uuid.uuid4().hex[:10],
    }


def trend_params(ds_id, viz, metrics, groupby, stack, y_fmt=",d"):
    return {
        "datasource": "%s__table" % ds_id,
        "viz_type": viz,
        "x_axis": "ts",
        "time_grain_sqla": "PT1H",
        "x_axis_sort_asc": True,
        "x_axis_sort_series": "name",
        "x_axis_sort_series_ascending": True,
        "metrics": metrics,
        "groupby": groupby,
        "adhoc_filters": [temporal_filter("ts", "Last day")],
        "order_desc": True,
        "row_limit": 10000,
        "truncate_metric": True,
        "show_empty_columns": True,
        "comparison_type": "values",
        "annotation_layers": [],
        "forecastPeriods": 10,
        "forecastInterval": 0.8,
        "orientation": "vertical",
        "x_axis_title_margin": 15,
        "y_axis_title_margin": 15,
        "y_axis_title_position": "Left",
        "sort_series_type": "sum",
        "color_scheme": "supersetColors",
        "stack": stack,
        "only_total": True,
        "show_legend": True,
        "legendType": "scroll",
        "legendOrientation": "top",
        "x_axis_time_format": "smart_date",
        "y_axis_format": y_fmt,
        "rich_tooltip": True,
        "tooltipTimeFormat": "smart_date",
        "markerEnabled": False,
        "seriesType": "line" if viz.endswith("_line") else "bar",
        "opacity": 0.8,
        "extra_form_data": {},
    }


def table_params(ds_id, cols, row_limit, order_by, time_col=None,
                 time_range=None, page_length=25):
    params = {
        "datasource": "%s__table" % ds_id,
        "viz_type": "table",
        "query_mode": "raw",
        "all_columns": cols,
        "percent_metrics": [],
        "adhoc_filters": [],
        "row_limit": row_limit,
        "order_by_cols": [json.dumps(o) for o in order_by],
        # command datasets reject is_rowcount; server_pagination must stay False
        "server_pagination": False,
        "server_page_length": page_length,
        "page_length": page_length,
        "show_cell_bars": False,
        "align_pn": False,
        "color_pn": False,
        "include_search": True,
        "allow_render_html": False,
        "emitCrossFilters": False,
    }
    if time_col and time_range:
        params["adhoc_filters"] = [temporal_filter(time_col, time_range)]
    return params


def main():
    with app.app_context():
      with app.test_request_context():
        from superset import db
        from superset.connectors.sqla.models import SqlaTable, TableColumn
        from superset.models.core import Database
        from superset.models.dashboard import Dashboard
        from superset.models.slice import Slice

        admin = db.session.query(User).filter_by(username="admin").first()
        if admin:
            login_user(admin)

        db_main = db.session.get(Database, DB_MAIN)
        db_priv = db.session.get(Database, DB_PRIV)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(BACKUP_DIR, exist_ok=True)

        def ensure_ds(database, name, sql, cols, desc, main_dttm=None,
                      fetch_pred=None, verbose=None):
            verbose = verbose or {}
            ds = (db.session.query(SqlaTable)
                  .filter_by(table_name=name, database_id=database.id).first())
            if ds is None:
                ds = SqlaTable(table_name=name, schema=SCHEMA, database=database,
                               sql=sql, is_sqllab_view=True, description=desc)
                db.session.add(ds)
                db.session.flush()
                print("DS_NEW|%s|%s" % (name, ds.id))
            else:
                ds.sql, ds.schema, ds.is_sqllab_view = sql, SCHEMA, True
                ds.description = desc
                print("DS_UPD|%s|%s" % (name, ds.id))
            want = {c[0] for c in cols}
            have = {c.column_name: c for c in ds.columns}
            for cname, ctype, is_dttm in cols:
                if cname in have:
                    col = have[cname]
                    col.type, col.is_dttm = ctype, is_dttm
                    col.verbose_name = verbose.get(cname)
                else:
                    ds.columns.append(TableColumn(
                        column_name=cname, type=ctype, is_dttm=is_dttm,
                        verbose_name=verbose.get(cname),
                        groupby=True, filterable=True))
            for col in list(ds.columns):
                if col.column_name not in want:
                    ds.columns.remove(col)
                    db.session.delete(col)
            ds.main_dttm_col = main_dttm
            ds.fetch_values_predicate = fetch_pred
            if admin and not ds.owners:
                ds.owners = [admin]
            db.session.flush()
            return ds

        # ---------------- datasets ----------------
        ds_audit = ensure_ds(
            db_main, "v_run_audit", AUDIT_SQL, AUDIT_COLS,
            "运行分析·审计日志（audit_db.audit 现场查询）", "ts",
            "ts >= CURRENT_DATE() - INTERVAL 7 DAY")
        ds_curq = ensure_ds(
            db_main, "v_run_current_queries", CURQ_SQL, CURQ_COLS,
            "运行分析·当前运行任务（SHOW PROC '/current_queries'）")
        ds_loads = ensure_ds(
            db_main, "v_run_loads", LOADS_SQL, LOADS_COLS,
            "运行分析·导入任务（information_schema.loads 现场查询）")
        ds_mv = ensure_ds(
            db_main, "v_run_mv_status", MV_SQL, MV_COLS,
            "运行分析·物化视图状态（information_schema.materialized_views）")
        ds_task = ensure_ds(
            db_main, "v_run_task_fail", TASKFAIL_SQL, TASKFAIL_COLS,
            "运行分析·调度任务失败（information_schema.task_runs）", "create_time")
        ds_users = ensure_ds(
            db_priv, "v_show_users_rg", USERS_SQL, USERS_COLS,
            "用户清单 + 资源组（SHOW RESOURCE GROUPS ALL 配置绑定）",
            verbose=USERS_VERBOSE)

        # ---------------- smoke tests ----------------
        checks = [
            ("audit", db_main, "SELECT COUNT(*) FROM (%s) x WHERE ts >= CURRENT_DATE() - INTERVAL 1 DAY" % AUDIT_SQL),
            ("curq", db_main, CURQ_SQL),
            ("loads", db_main, "SELECT COUNT(*) FROM (%s) x" % LOADS_SQL),
            ("mv", db_main, "SELECT COUNT(*) FROM (%s) x" % MV_SQL),
            ("taskfail", db_main, "SELECT COUNT(*) FROM (%s) x" % TASKFAIL_SQL),
            ("users", db_priv, "SELECT COUNT(*) FROM (%s) x" % USERS_SQL),
        ]
        user_n = 0
        for name, database, q in checks:
            with database.get_sqla_engine() as eng, eng.connect() as conn:
                rows = conn.execute(text(q)).fetchall()
                val = rows[0][0] if (rows and len(rows[0]) == 1) else len(rows)
                print("SMOKE|%s|%s" % (name, val))
                if name == "users":
                    user_n = val

        # ---------------- charts ----------------
        def upsert_slice(name, viz, ds, params, desc):
            sl = db.session.query(Slice).filter_by(slice_name=name).first()
            payload = json.dumps(params, ensure_ascii=False)
            if sl is None:
                sl = Slice(slice_name=name, viz_type=viz, datasource_type="table",
                           datasource_id=ds.id, params=payload, description=desc)
                if admin:
                    sl.owners = [admin]
                db.session.add(sl)
                db.session.flush()
                print("SLICE_NEW|%s|%s" % (name, sl.id))
            else:
                sl.viz_type, sl.datasource_id = viz, ds.id
                sl.params, sl.query_context = payload, None
                sl.description = desc
                print("SLICE_UPD|%s|%s" % (name, sl.id))
            return sl

        DESC = "数据中台速览 · 运行分析"

        sl_cnt = upsert_slice(
            "任务量趋势（按类型）", "echarts_timeseries_bar", ds_audit,
            trend_params(ds_audit.id, "echarts_timeseries_bar",
                         [metric("COUNT(*)", "任务数量")], ["task_kind"], "Stack"),
            DESC)
        sl_avg = upsert_slice(
            "平均耗时趋势", "echarts_timeseries_line", ds_audit,
            trend_params(ds_audit.id, "echarts_timeseries_line",
                         [metric("ROUND(AVG(query_ms))", "平均耗时(毫秒)")],
                         [], None),
            DESC)
        sl_sum = upsert_slice(
            "总耗时趋势（按类型）", "echarts_timeseries_bar", ds_audit,
            trend_params(ds_audit.id, "echarts_timeseries_bar",
                         [metric("ROUND(SUM(query_ms) / 1000)", "总耗时(秒)")],
                         ["task_kind"], "Stack"),
            DESC)

        TOP_COLS = ["ts", "task_kind", "user_name", "resource_group", "db_name",
                    "query_ms", "cpu_sec", "mem_mb", "scan_rows", "return_rows",
                    "exec_state", "stmt_head"]
        sl_top_time = upsert_slice(
            "执行耗时TOP100", "table", ds_audit,
            table_params(ds_audit.id, TOP_COLS, 100, [["query_ms", False]],
                         "ts", "Last day"),
            DESC)
        sl_top_cpu = upsert_slice(
            "CPU消耗TOP100", "table", ds_audit,
            table_params(ds_audit.id, TOP_COLS, 100, [["cpu_sec", False]],
                         "ts", "Last day"),
            DESC)
        sl_top_mem = upsert_slice(
            "内存消耗TOP100", "table", ds_audit,
            table_params(ds_audit.id, TOP_COLS, 100, [["mem_mb", False]],
                         "ts", "Last day"),
            DESC)

        sl_curq = upsert_slice(
            "当前运行任务", "table", ds_curq,
            table_params(ds_curq.id, [c[0] for c in CURQ_COLS], 200, []),
            DESC)
        sl_mv = upsert_slice(
            "物化视图刷新状态", "table", ds_mv,
            table_params(ds_mv.id, [c[0] for c in MV_COLS], 200,
                         [["is_active", True], ["last_refresh_time", False]]),
            DESC)
        sl_loads = upsert_slice(
            "数据导入任务", "table", ds_loads,
            table_params(ds_loads.id, [c[0] for c in LOADS_COLS], 500,
                         [["failed_n", False], ["job_n", False]]),
            DESC)
        sl_task = upsert_slice(
            "调度任务失败记录", "table", ds_task,
            table_params(ds_task.id, [c[0] for c in TASKFAIL_COLS], 200,
                         [["create_time", False]], "create_time", "Last week"),
            DESC)

        new_slices = [sl_cnt, sl_avg, sl_sum, sl_curq, sl_top_time, sl_top_cpu,
                      sl_top_mem, sl_mv, sl_loads, sl_task]
        audit_charts = [sl_cnt.id, sl_avg.id, sl_sum.id, sl_top_time.id,
                        sl_top_cpu.id, sl_top_mem.id]
        trend_charts = [sl_cnt.id, sl_avg.id, sl_sum.id]

        # ---------------- 用户清单: add resource group ----------------
        sl_users = db.session.query(Slice).filter_by(slice_name="用户清单").first()
        if sl_users is None:
            print("WARN|用户清单 chart not found")
        elif user_n < 13:
            print("WARN|user list only %s rows (<13), left 用户清单 untouched" % user_n)
        else:
            p = json.loads(sl_users.params or "{}")
            p["datasource"] = "%s__table" % ds_users.id
            p["all_columns"] = ["user_name", "resource_group", "query_n_7d"]
            p["order_by_cols"] = [json.dumps(["user_name", True])]
            p["row_limit"] = 500
            # column_config keys on the verbose name, so stale keys from the
            # previous dataset would leave the headers rendering raw column names
            p["column_config"] = USERS_COLUMN_CONFIG
            sl_users.datasource_id = ds_users.id
            sl_users.params = json.dumps(p, ensure_ascii=False)
            sl_users.description = USERS_DESC
            sl_users.query_context = None
            print("SLICE_UPD|用户清单|%s|ds=%s" % (sl_users.id, ds_users.id))

        # ---------------- dashboard ----------------
        dash = db.session.query(Dashboard).filter_by(slug=SLUG).one()
        backup = {
            "position_json": dash.position_json,
            "json_metadata": dash.json_metadata,
            "css": dash.css,
            "slice_ids": sorted(s.id for s in dash.slices),
        }
        bpath = os.path.join(BACKUP_DIR, "%s_%s_run_analysis.json" % (SLUG, ts))
        with open(bpath, "w", encoding="utf-8") as f:
            json.dump(backup, f, ensure_ascii=False, indent=2)
        print("BACKUP|%s" % bpath)

        pos = json.loads(dash.position_json or "{}")
        meta = json.loads(dash.json_metadata or "{}")

        tabs_id = next((k for k, v in pos.items()
                        if isinstance(v, dict) and v.get("type") == "TABS"), None)
        if not tabs_id:
            raise RuntimeError("TABS container missing")

        tab_id = next((k for k, v in pos.items()
                       if isinstance(v, dict) and v.get("type") == "TAB"
                       and (v.get("meta") or {}).get("text") == TAB_TEXT), None)
        if tab_id is None:
            tab_id = rid("TAB")
            pos[tab_id] = {
                "type": "TAB", "id": tab_id, "children": [],
                "parents": ["ROOT_ID", "GRID_ID", tabs_id],
                "meta": {"text": TAB_TEXT, "defaultText": "Tab",
                         "placeholder": "Tab name"},
            }
            pos[tabs_id].setdefault("children", []).append(tab_id)
            print("TAB_NEW|%s" % tab_id)
        else:
            drop = set()

            def walk(nid):
                drop.add(nid)
                for ch in (pos.get(nid) or {}).get("children") or []:
                    walk(ch)

            for ch in list(pos[tab_id].get("children") or []):
                walk(ch)
            for nid in drop:
                pos.pop(nid, None)
            pos[tab_id]["children"] = []
            print("TAB_REUSE|%s" % tab_id)

        def add_row(specs, height):
            row_id = rid("ROW")
            pos[tab_id]["children"].append(row_id)
            pos[row_id] = {
                "type": "ROW", "id": row_id, "children": [],
                "parents": ["ROOT_ID", "GRID_ID", tabs_id, tab_id],
                "meta": {"background": "BACKGROUND_TRANSPARENT"},
            }
            for sl, width in specs:
                ch_id = rid("CHART")
                pos[row_id]["children"].append(ch_id)
                pos[ch_id] = {
                    "type": "CHART", "id": ch_id, "children": [],
                    "parents": ["ROOT_ID", "GRID_ID", tabs_id, tab_id, row_id],
                    "meta": {"width": width, "height": height,
                             "chartId": sl.id, "sliceName": sl.slice_name,
                             "uuid": str(getattr(sl, "uuid", None) or uuid.uuid4())},
                }

        md_id, md_row = rid("MARKDOWN"), rid("ROW")
        pos[md_row] = {
            "type": "ROW", "id": md_row, "children": [md_id],
            "parents": ["ROOT_ID", "GRID_ID", tabs_id, tab_id],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        pos[md_id] = {
            "type": "MARKDOWN", "id": md_id, "children": [],
            "parents": ["ROOT_ID", "GRID_ID", tabs_id, tab_id, md_row],
            "meta": {"width": 12, "height": 7, "code": (
                "### 运行分析\n"
                "- **趋势与 TOP100** 来自审计日志 `audit_db.audit`（保留约 30 天），"
                "受上方「时间范围 / 时间粒度 / 任务类型 / 用户 / 资源组」筛选\n"
                "- **任务类型** 按 SQL 首个关键字归类；Stream Load 不写审计日志，"
                "请看下方「数据导入任务」\n"
                "- **当前运行任务 / 物化视图 / 导入任务 / 调度任务** 均为实时查询，"
                "不受时间筛选影响\n"
                "- 时间范围最长可选 7 天，避免一次扫描过多审计数据"
            )},
        }
        pos[tab_id]["children"].append(md_row)

        add_row([(sl_cnt, 6), (sl_avg, 6)], 50)
        add_row([(sl_sum, 12)], 50)
        add_row([(sl_curq, 12)], 45)
        add_row([(sl_top_time, 12)], 65)
        add_row([(sl_top_cpu, 6), (sl_top_mem, 6)], 65)
        add_row([(sl_mv, 12)], 50)
        add_row([(sl_loads, 6), (sl_task, 6)], 55)

        keep = {s.id for s in dash.slices} | {s.id for s in new_slices}
        dash.slices = db.session.query(Slice).filter(Slice.id.in_(keep)).all()
        all_ids = sorted(s.id for s in dash.slices)
        tab_ids = [s.id for s in new_slices]

        # ---------------- native filters ----------------
        def nf(fid, name, ftype, targets, default_mask, charts,
               control_values=None):
            return {
                "id": fid,
                "name": name,
                "filterType": ftype,
                "targets": targets,
                "defaultDataMask": default_mask,
                "controlValues": control_values or {"enableEmptyFilter": False},
                "cascadeParentIds": [],
                "scope": {"rootPath": [tab_id],
                          "excluded": [i for i in all_ids if i not in charts]},
                "chartsInScope": charts,
                "tabsInScope": [tab_id],
                "type": "NATIVE_FILTER",
                "description": "",
            }

        def select_cv():
            return {"enableEmptyFilter": False, "defaultToFirstItem": False,
                    "multiSelect": True, "searchAllOptions": False,
                    "inverseSelection": False}

        new_filters = [
            nf("NATIVE_FILTER-run-time", "时间范围", "filter_time", [{}],
               {"extraFormData": {"time_range": "Last day"},
                "filterState": {"value": "Last day"}, "ownState": {}},
               audit_charts,
               {"enableEmptyFilter": False, "maxTimeRangeValue": 7,
                "maxTimeRangeUnit": "day"}),
            nf("NATIVE_FILTER-run-timegrain", "时间粒度", "filter_timegrain",
               [{"datasetId": ds_audit.id, "column": {"name": "ts"}}],
               {"extraFormData": {"time_grain_sqla": "PT1H"},
                "filterState": {"value": ["PT1H"], "label": "Hour"},
                "ownState": {}},
               trend_charts,
               {"enableEmptyFilter": False, "multiSelect": False}),
            nf("NATIVE_FILTER-run-kind", "任务类型", "filter_select",
               [{"datasetId": ds_audit.id, "column": {"name": "task_kind"}}],
               {"extraFormData": {}, "filterState": {}, "ownState": {}},
               audit_charts, select_cv()),
            nf("NATIVE_FILTER-run-user", "用户", "filter_select",
               [{"datasetId": ds_audit.id, "column": {"name": "user_name"}}],
               {"extraFormData": {}, "filterState": {}, "ownState": {}},
               audit_charts, select_cv()),
            nf("NATIVE_FILTER-run-rg", "资源组", "filter_select",
               [{"datasetId": ds_audit.id, "column": {"name": "resource_group"}}],
               {"extraFormData": {}, "filterState": {}, "ownState": {}},
               audit_charts, select_cv()),
        ]
        old = [f for f in (meta.get("native_filter_configuration") or [])
               if not str(f.get("id", "")).startswith("NATIVE_FILTER-run-")]
        meta["native_filter_configuration"] = old + new_filters

        chart_cfg = dict(meta.get("chart_configuration") or {})
        for sl in new_slices:
            chart_cfg[str(sl.id)] = {
                "id": sl.id,
                "crossFilters": {
                    "scope": {"rootPath": ["ROOT_ID"], "excluded": [sl.id]},
                    "chartsInScope": [],
                },
            }
        meta["chart_configuration"] = chart_cfg

        gcfg = meta.get("global_chart_configuration") or {
            "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
            "chartsInScope": []}
        gcfg["chartsInScope"] = sorted(set((gcfg.get("chartsInScope") or []) + all_ids))
        meta["global_chart_configuration"] = gcfg

        dash.position_json = json.dumps(pos, ensure_ascii=False)
        dash.json_metadata = json.dumps(meta, ensure_ascii=False)
        flag_modified(dash, "position_json")
        flag_modified(dash, "json_metadata")
        db.session.commit()
        print("COMMIT_OK|tab=%s|charts=%s" % (tab_id, tab_ids))

        # ---------------- verify through the chart API ----------------
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(admin.id)
            sess["_fresh"] = True
        for sl in new_slices + ([sl_users] if sl_users else []):
            fd = json.loads(sl.params)
            payload = {"datasource": {"id": sl.datasource_id, "type": "table"},
                       "form_data": fd, "force": True,
                       "result_type": "full", "result_format": "json",
                       "queries": [{}]}
            try:
                resp = client.post("/api/v1/chart/data?form_data=%s"
                                   % json.dumps({"slice_id": sl.id}), json=payload)
                body = resp.get_json() or {}
                res = (body.get("result") or [{}])[0]
                n = len(res.get("data") or [])
                err = res.get("error") or body.get("message")
                print("API|%s|%s|n=%s|err=%s" % (
                    sl.slice_name, resp.status_code, n,
                    (str(err)[:160] if err else None)))
            except Exception as e:  # noqa
                print("API|%s|EXC|%s" % (sl.slice_name, str(e)[:160]))

        print("URL|/superset/dashboard/%s/" % SLUG)
        print("DONE|run_analysis_tab")


if __name__ == "__main__":
    main()
