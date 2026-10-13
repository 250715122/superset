# -*- coding: utf-8 -*-
"""Refresh bluetti.ads_sr_global_rg_bindings from live resource group config.

`SHOW RESOURCE GROUPS ALL` cannot be joined in SQL, so the classifiers are
parsed and landed here for the 用户清单 chart to join against.

Writes a new snapshot_ts and keeps the three most recent snapshots, so readers
never observe an empty table. Run hourly from cron.
"""
import os
import re
from datetime import datetime

CONF = "/mnt/data/superset/superset_config.py"
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from sqlalchemy import text  # noqa: E402
from superset.app import create_app  # noqa: E402

app = create_app()

TABLE = "bluetti.ads_sr_global_rg_bindings"
KEEP_SNAPSHOTS = 3
CLF_KV_RE = re.compile(r"(\w+)=([^,\)]+)")

DDL = """
CREATE TABLE IF NOT EXISTS %s (
  snapshot_ts VARCHAR(32), rg_name VARCHAR(128), rg_id VARCHAR(32),
  classifier_id VARCHAR(32), weight VARCHAR(32),
  user_name VARCHAR(128), source_ip VARCHAR(128),
  query_type VARCHAR(64), db_name VARCHAR(128),
  classifier_raw VARCHAR(512)
) DISTRIBUTED BY HASH(rg_name) BUCKETS 1 PROPERTIES("replication_num"="1")
""" % TABLE


def clip(v, n):
    return None if v is None else str(v)[:n]


def parse_classifier(raw):
    """Parse classifiers like '(id=3137726, weight=1.0, user=agi)'."""
    s = str(raw or "").strip()
    kv = {m.group(1): m.group(2).strip() for m in CLF_KV_RE.finditer(s)}
    return {
        "classifier_id": kv.get("id"),
        "weight": kv.get("weight"),
        "user_name": kv.get("user"),
        "source_ip": kv.get("source_ip") or kv.get("sourceip"),
        "query_type": kv.get("query_type") or kv.get("queryType"),
        "db_name": kv.get("db") or kv.get("database"),
        "classifier_raw": clip(s, 500),
    }


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with app.app_context():
        from superset import db
        from superset.models.core import Database

        database = db.session.get(Database, 12)  # agi: reads SHOW, writes bluetti
        assert database, "database 12 missing"

        with database.get_sqla_engine() as eng, eng.connect() as conn:
            res = conn.execute(text("SHOW RESOURCE GROUPS ALL"))
            cols = list(res.keys())
            rows = [dict(zip(cols, r)) for r in res.fetchall()]
            print("READ|%s|rows=%s" % (now, len(rows)))

            conn.execute(text(DDL))
            n = 0
            for d in rows:
                clf = parse_classifier(d.get("classifiers"))
                conn.execute(text("""
                    INSERT INTO %s
                    (snapshot_ts, rg_name, rg_id, classifier_id, weight,
                     user_name, source_ip, query_type, db_name, classifier_raw)
                    VALUES (:ts,:n,:i,:cid,:w,:u,:ip,:qt,:db,:raw)
                """ % TABLE), {
                    "ts": now,
                    "n": clip(d.get("name"), 120),
                    "i": clip(d.get("id"), 32),
                    "cid": clip(clf["classifier_id"], 32),
                    "w": clip(clf["weight"], 32),
                    "u": clip(clf["user_name"], 120),
                    "ip": clip(clf["source_ip"], 120),
                    "qt": clip(clf["query_type"], 60),
                    "db": clip(clf["db_name"], 120),
                    "raw": clf["classifier_raw"],
                })
                n += 1
            print("INSERT|%s|rows=%s" % (now, n))

            keep = [r[0] for r in conn.execute(text(
                "SELECT DISTINCT snapshot_ts FROM %s "
                "ORDER BY snapshot_ts DESC LIMIT %s" % (TABLE, KEEP_SNAPSHOTS)
            )).fetchall()]
            if keep:
                conn.execute(text(
                    "DELETE FROM %s WHERE snapshot_ts < :oldest" % TABLE
                ), {"oldest": min(keep)})
            print("PRUNE|kept=%s" % keep)

            bound = conn.execute(text(
                "SELECT COUNT(DISTINCT user_name) FROM %s "
                "WHERE snapshot_ts = :ts AND user_name IS NOT NULL "
                "AND user_name != ''" % TABLE
            ), {"ts": now}).fetchall()[0][0]
            print("OK|snapshot=%s|bound_users=%s" % (now, bound))


if __name__ == "__main__":
    main()
