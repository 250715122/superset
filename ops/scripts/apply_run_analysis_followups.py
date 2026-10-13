# -*- coding: utf-8 -*-
"""Follow-ups on the 运行分析 tab, after review:

1. 平均耗时趋势 reports milliseconds — average query time is ~100-200 ms, so
   whole seconds rounded every bucket to 0.
2. 用户清单 shows the configured resource group binding (parsed from
   SHOW RESOURCE GROUPS ALL by sync_sr_rg_bindings.py) instead of the groups
   observed in the audit log.

Idempotent.
"""
from __future__ import annotations

import json
import os

CONF = "/mnt/data/superset/superset_config.py"
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from sqlalchemy import text  # noqa: E402
from superset.app import create_app  # noqa: E402

app = create_app()

AVG_SLICE = "平均耗时趋势"
AVG_METRIC_SQL = "ROUND(AVG(query_ms))"
AVG_METRIC_LABEL = "平均耗时(毫秒)"

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


def main():
    with app.app_context():
        from superset import db
        from superset.connectors.sqla.models import SqlaTable
        from superset.models.slice import Slice

        sl = db.session.query(Slice).filter_by(slice_name=AVG_SLICE).one()
        params = json.loads(sl.params)
        metric = dict(params["metrics"][0])
        before = (metric.get("sqlExpression"), metric.get("label"))
        metric["sqlExpression"] = AVG_METRIC_SQL
        metric["label"] = AVG_METRIC_LABEL
        params["metrics"] = [metric]
        sl.params = json.dumps(params, ensure_ascii=False)
        sl.query_context = None
        print("SLICE|%s|%s|%s -> %s" % (
            sl.id, AVG_SLICE, before, (AVG_METRIC_SQL, AVG_METRIC_LABEL)))

        ds = db.session.query(SqlaTable).filter_by(
            table_name="v_show_users_rg").one()
        with ds.database.get_sqla_engine() as eng, eng.connect() as conn:
            rows = conn.execute(text(
                "SELECT * FROM (%s) x ORDER BY user_name" % USERS_SQL)).fetchall()
        print("SMOKE|v_show_users_rg|rows=%s" % len(rows))
        for r in rows:
            print("   %s" % " | ".join(str(c) for c in r))
        if len(rows) < 13:
            raise RuntimeError("user list shrank to %s rows, aborting" % len(rows))

        ds.sql = USERS_SQL
        ds.description = "用户清单 + 资源组（SHOW RESOURCE GROUPS ALL 配置绑定）"
        print("DS|%s|v_show_users_rg updated" % ds.id)

        db.session.commit()
        print("COMMIT_OK")


if __name__ == "__main__":
    main()
