# -*- coding: utf-8 -*-
"""Rework the 运行状态 / 性能分析 tabs on dashboard dp-sr-global.

The user split the original 运行分析 tab in two by hand, which left the five
native filters pointing at the old tab only — the charts that moved to
性能分析 silently fell out of scope. This re-scopes them and applies the
review feedback:

- 当前运行任务 -> 审计明细 (audit log rows, newest first)
- 平均耗时趋势 -> 查询平均耗时趋势, restricted to SELECT (SET/SHOW/COMMIT
  average ~0ms and were dragging the mean down)
- 总耗时趋势（按类型） -> 平均耗时趋势（按类型）, one line per task kind
- the three TOP100 tables aggregate by the first 200 chars of the statement
  so near-identical SQL collapses into one row
- 数据导入任务 also covers routine load and pipe, and leads with the load type

Idempotent.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime

CONF = "/mnt/data/superset/superset_config.py"
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from sqlalchemy import text  # noqa: E402
from superset.app import create_app  # noqa: E402

app = create_app()

SLUG = "dp-sr-global"
BACKUP_DIR = "/mnt/data/superset/backups"
TAB_RUN = "TAB-525bfeeea0"              # 运行状态
TAB_PERF = "TAB-ZMMbTdwpfKCBQBjuyrFdb"  # 性能分析

# ---------------------------------------------------------------- datasets

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
  SUBSTR(stmt, 1, 200) AS sql_200,
  SUBSTR(stmt, 1, 1000) AS stmt_head
FROM audit_db.audit
"""

# information_schema.loads already carries STREAM_LOAD / BROKER LOAD / SPARK LOAD
# alongside INSERT, so stream_loads is deliberately not unioned in (it would
# double count). Routine load and pipe live in their own tables.
LOADS_SQL = r"""
SELECT
  `TYPE` AS load_type,
  DB_NAME AS db_name,
  TABLE_NAME AS table_name,
  COUNT(*) AS job_n,
  SUM(CASE WHEN STATE = 'FINISHED' THEN 1 ELSE 0 END) AS finished_n,
  SUM(CASE WHEN STATE IN ('CANCELLED', 'FAILED', 'ERROR') THEN 1 ELSE 0 END) AS failed_n,
  SUM(CASE WHEN STATE NOT IN ('FINISHED', 'CANCELLED', 'FAILED', 'ERROR') THEN 1 ELSE 0 END) AS running_n,
  CAST(SUM(SINK_ROWS) AS BIGINT) AS sink_rows,
  CAST(SUM(FILTERED_ROWS) AS BIGINT) AS filtered_rows,
  CAST(MAX(CREATE_TIME) AS VARCHAR) AS last_create_time,
  CAST(MAX(LOAD_FINISH_TIME) AS VARCHAR) AS last_finish_time,
  CAST(MAX(ERROR_MSG) AS VARCHAR) AS last_error
FROM information_schema.loads
GROUP BY 1, 2, 3
UNION ALL
SELECT
  'ROUTINE_LOAD' AS load_type,
  DB_NAME AS db_name,
  TABLE_NAME AS table_name,
  COUNT(*) AS job_n,
  SUM(CASE WHEN STATE = 'STOPPED' THEN 1 ELSE 0 END) AS finished_n,
  SUM(CASE WHEN STATE IN ('CANCELLED', 'PAUSED') THEN 1 ELSE 0 END) AS failed_n,
  SUM(CASE WHEN STATE = 'RUNNING' THEN 1 ELSE 0 END) AS running_n,
  CAST(0 AS BIGINT) AS sink_rows,
  CAST(0 AS BIGINT) AS filtered_rows,
  CAST(MAX(CREATE_TIME) AS VARCHAR) AS last_create_time,
  CAST(MAX(END_TIME) AS VARCHAR) AS last_finish_time,
  CAST(MAX(REASONS_OF_STATE_CHANGED) AS VARCHAR) AS last_error
FROM information_schema.routine_load_jobs
GROUP BY 1, 2, 3
UNION ALL
SELECT
  'PIPE' AS load_type,
  DATABASE_NAME AS db_name,
  TABLE_NAME AS table_name,
  COUNT(*) AS job_n,
  SUM(CASE WHEN STATE = 'FINISHED' THEN 1 ELSE 0 END) AS finished_n,
  SUM(CASE WHEN STATE = 'ERROR' THEN 1 ELSE 0 END) AS failed_n,
  SUM(CASE WHEN STATE = 'RUNNING' THEN 1 ELSE 0 END) AS running_n,
  CAST(0 AS BIGINT) AS sink_rows,
  CAST(0 AS BIGINT) AS filtered_rows,
  CAST(MAX(CREATED_TIME) AS VARCHAR) AS last_create_time,
  CAST(NULL AS VARCHAR) AS last_finish_time,
  CAST(MAX(LAST_ERROR) AS VARCHAR) AS last_error
FROM information_schema.pipes
GROUP BY 1, 2, 3
"""

LOADS_COLS = [
    ("load_type", "VARCHAR", False), ("db_name", "VARCHAR", False),
    ("table_name", "VARCHAR", False), ("job_n", "BIGINT", False),
    ("finished_n", "BIGINT", False), ("failed_n", "BIGINT", False),
    ("running_n", "BIGINT", False), ("sink_rows", "BIGINT", False),
    ("filtered_rows", "BIGINT", False), ("last_create_time", "VARCHAR", False),
    ("last_finish_time", "VARCHAR", False), ("last_error", "VARCHAR", False),
]

AUDIT_DETAIL_COLS = [
    "ts", "task_kind", "user_name", "resource_group", "db_name", "exec_state",
    "error_code", "query_ms", "cpu_sec", "mem_mb", "scan_rows", "return_rows",
    "client_ip", "stmt_head",
]

# ---------------------------------------------------------------- helpers


def metric(sql, label):
    """Adhoc metric with an optionName derived from the label, so re-running
    this script does not churn the saved params."""
    return {
        "expressionType": "SQL", "sqlExpression": sql, "label": label,
        "hasCustomLabel": True, "aggregate": None, "column": None,
        "datasourceWarning": False,
        "optionName": "metric_%s" % hashlib.md5(
            label.encode("utf-8")).hexdigest()[:10],
    }


def temporal_filter(col, default="Last day"):
    return {
        "clause": "WHERE", "subject": col, "operator": "TEMPORAL_RANGE",
        "comparator": default, "expressionType": "SIMPLE",
        "filterOptionName": "filter_%s" % hashlib.md5(
            ("tr_" + col).encode("utf-8")).hexdigest()[:10],
    }


def eq_filter(col, value):
    return {
        "clause": "WHERE", "subject": col, "operator": "==",
        "comparator": value, "expressionType": "SIMPLE",
        "filterOptionName": "filter_%s" % hashlib.md5(
            ("eq_%s_%s" % (col, value)).encode("utf-8")).hexdigest()[:10],
    }


TOP_METRICS = {
    "query_ms": metric("MAX(query_ms)", "最大耗时(毫秒)"),
    "cpu_sec": metric("MAX(cpu_sec)", "最大CPU(秒)"),
    "mem_mb": metric("MAX(mem_mb)", "最大内存(MB)"),
}
TOP_COMMON = [
    metric("COUNT(*)", "执行次数"),
    metric("ROUND(AVG(query_ms))", "平均耗时(毫秒)"),
    metric("CAST(MAX(ts) AS VARCHAR)", "最近执行"),
    metric("MAX(user_name)", "用户"),
    metric("MAX(db_name)", "库"),
]
TOP_DESC = ("按语句前 200 个字符聚合，近似 SQL 合并成一行；耗时/CPU/内存取该语句"
            "在所选时间范围内的最大值，「最近执行」取最后一次执行时间。"
            "受上方时间范围 / 任务类型 / 用户 / 资源组筛选。")

MARKDOWN_TEXT = """### 运行状态

- **任务量趋势**、**审计明细** 读审计日志 `audit_db.audit`（保留约 30 天），受上方「时间范围 / 时间粒度 / 任务类型 / 用户 / 资源组」筛选。
- **物化视图刷新状态**、**数据导入任务**、**调度任务失败记录** 现场查 `information_schema`，反映当前状态，不受上方时间筛选影响。
- 导入任务涵盖 `INSERT` / `STREAM_LOAD` / `BROKER LOAD` / `ROUTINE LOAD` / `PIPE`；其中 `information_schema.loads` 只保留最近一段时间的作业（受 FE 的 `label_keep_max_second` / `label_keep_max_num` 限制，当前约 12 小时）。
- 耗时 / CPU / 内存 TOP 榜和趋势图在「性能分析」Tab。
"""


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    with app.app_context():
        from superset import db
        from superset.connectors.sqla.models import SqlaTable, TableColumn
        from superset.models.dashboard import Dashboard
        from superset.models.slice import Slice

        dash = db.session.query(Dashboard).filter_by(slug=SLUG).one()
        pos = json.loads(dash.position_json or "{}")
        meta = json.loads(dash.json_metadata or "{}")

        backup = {
            "position_json": dash.position_json,
            "json_metadata": dash.json_metadata,
            "css": dash.css,
            "slices": {
                s.id: {"slice_name": s.slice_name, "params": s.params,
                       "datasource_id": s.datasource_id,
                       "description": s.description}
                for s in dash.slices
            },
        }
        bpath = os.path.join(BACKUP_DIR, "%s_%s_run_status.json" % (SLUG, ts))
        with open(bpath, "w", encoding="utf-8") as f:
            json.dump(backup, f, ensure_ascii=False, indent=1)
        print("BACKUP|%s" % bpath)

        ds_audit = db.session.query(SqlaTable).filter_by(
            table_name="v_run_audit").one()
        ds_loads = db.session.query(SqlaTable).filter_by(
            table_name="v_run_loads").one()

        # ------------------------------------------------ dataset: sql_200
        with ds_audit.database.get_sqla_engine() as eng, eng.connect() as conn:
            n = conn.execute(text(
                "SELECT COUNT(DISTINCT sql_200) FROM (%s) v "
                "WHERE ts >= NOW() - INTERVAL 1 DAY" % AUDIT_SQL
            )).fetchall()[0][0]
            print("SMOKE|audit sql_200 patterns last day=%s" % n)
        ds_audit.sql = AUDIT_SQL
        have = {c.column_name for c in ds_audit.columns}
        if "sql_200" not in have:
            ds_audit.columns.append(TableColumn(
                column_name="sql_200", type="VARCHAR", is_dttm=False,
                verbose_name="SQL(前200字符)", groupby=True, filterable=True))
            print("DS|190|+sql_200")
        else:
            print("DS|190|sql_200 already present")

        # ------------------------------------------------ dataset: loads
        with ds_loads.database.get_sqla_engine() as eng, eng.connect() as conn:
            rows = conn.execute(text(
                "SELECT load_type, COUNT(*) AS tbl_n, SUM(job_n) AS job_n "
                "FROM (%s) v GROUP BY 1 ORDER BY 3 DESC" % LOADS_SQL)).fetchall()
        print("SMOKE|v_run_loads by type=%s" % [tuple(r) for r in rows])
        if not rows:
            raise RuntimeError("loads rollup returned nothing, aborting")
        ds_loads.sql = LOADS_SQL
        ds_loads.description = ("运行状态·导入任务（information_schema.loads "
                                "+ routine_load_jobs + pipes 现场查询）")
        want = {c[0] for c in LOADS_COLS}
        have = {c.column_name: c for c in ds_loads.columns}
        for cname, ctype, is_dttm in LOADS_COLS:
            if cname in have:
                have[cname].type = ctype
            else:
                ds_loads.columns.append(TableColumn(
                    column_name=cname, type=ctype, is_dttm=is_dttm,
                    groupby=True, filterable=True))
        for col in list(ds_loads.columns):
            if col.column_name not in want:
                ds_loads.columns.remove(col)
                db.session.delete(col)
        db.session.flush()

        # ------------------------------------------------ slices
        renames = {}

        def patch(sid, name=None, desc=None, ds_id=None, **params):
            sl = db.session.get(Slice, sid)
            p = json.loads(sl.params or "{}")
            p.update(params)
            if ds_id is not None and ds_id != sl.datasource_id:
                sl.datasource_id = ds_id
                p["datasource"] = "%s__table" % ds_id
            if name and name != sl.slice_name:
                renames[sid] = (sl.slice_name, name)
                sl.slice_name = name
            if desc:
                sl.description = desc
            sl.params = json.dumps(p, ensure_ascii=False)
            sl.query_context = None
            print("SLICE|%s|%s" % (sid, sl.slice_name))

        # 650: 当前运行任务 -> 审计明细
        patch(650, name="审计明细", ds_id=ds_audit.id,
              desc="审计日志明细，按时间倒序。受上方时间范围 / 任务类型 / 用户 / 资源组筛选。",
              viz_type="table", query_mode="raw",
              all_columns=AUDIT_DETAIL_COLS,
              order_by_cols=[json.dumps(["ts", False])],
              row_limit=1000,
              adhoc_filters=[temporal_filter("ts")],
              groupby=[], metrics=[])

        # 645: query-only average
        patch(645, name="查询平均耗时趋势",
              desc="仅统计 SELECT。SET / SHOW / COMMIT 等语句平均耗时接近 0ms，"
                   "混在一起会把均值拉低，所以这张图固定只看查询，不受「任务类型」筛选影响。",
              viz_type="echarts_timeseries_line",
              metrics=[metric("ROUND(AVG(query_ms))", "平均耗时(毫秒)")],
              groupby=[],
              adhoc_filters=[temporal_filter("ts"),
                             eq_filter("task_kind", "SELECT")])

        # 646: total -> average, one line per kind
        patch(646, name="平均耗时趋势（按类型）",
              desc="每种语句类型一条线，取该时间粒度内的平均耗时。",
              viz_type="echarts_timeseries_line",
              metrics=[metric("ROUND(AVG(query_ms))", "平均耗时(毫秒)")],
              groupby=["task_kind"],
              adhoc_filters=[temporal_filter("ts")])

        # 647/648/649: aggregate by statement prefix
        for sid, sort_col in ((647, "query_ms"), (648, "cpu_sec"),
                              (649, "mem_mb")):
            lead = TOP_METRICS[sort_col]
            patch(sid, desc=TOP_DESC,
                  viz_type="table", query_mode="aggregate",
                  groupby=["sql_200"],
                  metrics=[lead] + TOP_COMMON,
                  all_columns=[], order_by_cols=[],
                  timeseries_limit_metric=lead,
                  series_limit_metric=lead,
                  order_desc=True, row_limit=100,
                  adhoc_filters=[temporal_filter("ts")])

        # 652: lead with the load type
        patch(652, desc="现场查 information_schema：loads（INSERT / STREAM LOAD / "
                        "BROKER LOAD / SPARK LOAD）+ routine_load_jobs + pipes，"
                        "按库表和导入类型汇总。",
              all_columns=[c[0] for c in LOADS_COLS],
              order_by_cols=[json.dumps(["failed_n", False]),
                             json.dumps(["last_create_time", False])])

        # ------------------------------------------------ position_json
        for node in pos.values():
            if isinstance(node, dict) and node.get("type") == "CHART":
                m = node.get("meta") or {}
                if m.get("chartId") in renames:
                    old, new = renames[m["chartId"]]
                    m["sliceName"] = new
                    print("POS|%s|%s -> %s" % (m["chartId"], old, new))
            if isinstance(node, dict) and node.get("type") == "MARKDOWN":
                code = (node.get("meta") or {}).get("code") or ""
                if code.lstrip().startswith("### 运行分析"):
                    node["meta"]["code"] = MARKDOWN_TEXT
                    print("POS|markdown updated")

        # ------------------------------------------------ filter scope
        all_charts = sorted(
            (v.get("meta") or {}).get("chartId")
            for v in pos.values()
            if isinstance(v, dict) and v.get("type") == "CHART")
        scope_map = {
            "NATIVE_FILTER-run-time": [644, 645, 646, 647, 648, 649, 650],
            "NATIVE_FILTER-run-timegrain": [644, 645, 646],
            "NATIVE_FILTER-run-kind": [644, 646, 647, 648, 649, 650],
            "NATIVE_FILTER-run-user": [644, 645, 646, 647, 648, 649, 650],
            "NATIVE_FILTER-run-rg": [644, 645, 646, 647, 648, 649, 650],
        }
        for f in meta.get("native_filter_configuration") or []:
            keep = scope_map.get(f.get("id"))
            if keep is None:
                continue
            f["scope"] = {
                "rootPath": [TAB_RUN, TAB_PERF],
                "excluded": [c for c in all_charts if c not in keep],
            }
            f["chartsInScope"] = list(keep)
            print("NF|%s|in_scope=%s" % (f.get("name"), keep))

        dash.position_json = json.dumps(pos)
        dash.json_metadata = json.dumps(meta)

        db.session.commit()
        print("COMMIT_OK")


if __name__ == "__main__":
    main()
