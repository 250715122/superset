# -*- coding: utf-8 -*-
"""Point 用户权限 (slice 557) at the daily privilege snapshot.

It used to be a `SHOW GRANTS` command dataset, which broke two ways: Superset
cannot wrap a SHOW statement in `SELECT COUNT(*) FROM (...)`, so turning on
server pagination failed with "Command datasets only support raw table
queries. Unsupported fields: is_rowcount"; and `SHOW GRANTS` only ever
returned the privileges of the account Superset connects with (agi), 21 rows
for a single user.

Reading sys.grants_to_users / sys.grants_to_roles live fixes both but costs
~12s a page, essentially all of it inside sys.grants_to_roles.  So
sync_sr_user_privileges.sh materialises the expansion once a day and this
reads the newest snapshot.

    python fix_user_privileges_chart.py            # show the plan
    python fix_user_privileges_chart.py --apply
"""
import json
import os
import sys
from datetime import datetime

os.environ.setdefault("SUPERSET_CONFIG_PATH", "/mnt/data/superset/superset_config.py")
from superset.app import create_app  # noqa: E402

APPLY = "--apply" in sys.argv
DATASET_ID = 184
SLICE_ID = 557
NEW_TABLE_NAME = "v_user_privileges"
SRC = "bluetti.ads_sr_global_user_privileges"
BACKUP_DIR = "/mnt/data/superset/backups"

NEW_SQL = """SELECT
  user_name,
  granted_via,
  object_catalog,
  object_database,
  object_name,
  object_type,
  privilege_type,
  is_grantable,
  -- trimmed with SUBSTR rather than DATE_FORMAT: a '%' in virtual dataset SQL
  -- collides with the driver's parameter placeholders
  SUBSTR(CAST(snapshot_ts AS STRING), 1, 16) AS snapshot_ts
FROM {src}
WHERE snapshot_ts = (SELECT MAX(snapshot_ts) FROM {src})""".format(src=SRC)

COLUMNS = [
    ("user_name", "用户"),
    ("granted_via", "授权来源"),
    ("object_catalog", "Catalog"),
    ("object_database", "库"),
    ("object_name", "对象"),
    ("object_type", "对象类型"),
    ("privilege_type", "权限"),
    ("is_grantable", "可转授"),
    ("snapshot_ts", "快照时间"),
]
COL_NAMES = [c for c, _ in COLUMNS]

# the only params keys this change may touch; everything else stays as the
# user left it
PARAM_PATCH = {
    "all_columns": COL_NAMES,
    "column_config": {},          # old keys pointed at columns that are gone
    "order_by_cols": ['["user_name", true]', '["object_database", true]'],
    "row_limit": 50000,           # 15k+ rows; the old 5000 would truncate
}

app = create_app()
with app.app_context():
    from superset import db
    from superset.connectors.sqla.models import SqlaTable, TableColumn
    from superset.models.slice import Slice

    table = db.session.get(SqlaTable, DATASET_ID)
    slc = db.session.get(Slice, SLICE_ID)
    params = json.loads(slc.params or "{}")

    others = (db.session.query(Slice)
              .filter(Slice.datasource_id == DATASET_ID,
                      Slice.datasource_type == "table",
                      Slice.id != SLICE_ID).all())
    print("dataset %s: name=%s" % (table.id, table.table_name))
    print("  other charts on this dataset: %s"
          % ([(s.id, s.slice_name) for s in others] or "none"))
    print("  columns now: %s"
          % [c.column_name for c in sorted(table.columns, key=lambda c: c.id)])
    print("slice %s: %s  server_pagination=%s row_limit=%s"
          % (slc.id, slc.slice_name, params.get("server_pagination"),
             params.get("row_limit")))
    print("\nwould patch params keys: %s" % sorted(PARAM_PATCH))
    print("would leave untouched:   %s"
          % sorted(k for k in params if k not in PARAM_PATCH))

    if others:
        sys.exit("ABORT: dataset is shared with other charts, not safe to repoint")

    if not APPLY:
        print("\nDRY RUN -- rerun with --apply")
        sys.exit(0)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(BACKUP_DIR, "user_privileges_%s.json" % stamp)
    with open(backup, "w", encoding="utf-8") as fh:
        json.dump({
            "dataset": {
                "id": table.id,
                "table_name": table.table_name,
                "sql": table.sql,
                "columns": [{"column_name": c.column_name,
                             "type": c.type,
                             "verbose_name": c.verbose_name} for c in table.columns],
            },
            "slice": {"id": slc.id, "name": slc.slice_name, "params": slc.params},
        }, fh, ensure_ascii=False, indent=2)
    print("\nbackup -> %s" % backup)

    table.table_name = NEW_TABLE_NAME
    table.sql = NEW_SQL

    keep = {c for c, _ in COLUMNS}
    for col in list(table.columns):
        if col.column_name not in keep:
            db.session.delete(col)
            table.columns.remove(col)
    existing = {c.column_name: c for c in table.columns}
    for name, verbose in COLUMNS:
        col = existing.get(name)
        if col is None:
            col = TableColumn(column_name=name, table=table)
            table.columns.append(col)
        col.type = "VARCHAR"
        col.verbose_name = verbose
        col.groupby = True
        col.filterable = True
        col.is_dttm = False

    params.update(PARAM_PATCH)
    slc.params = json.dumps(params, ensure_ascii=False)
    slc.query_context = None  # stale: still describes the old columns

    db.session.commit()
    print("dataset %s -> %s reading %s, %d columns"
          % (table.id, table.table_name, SRC, len(table.columns)))
    print("slice %s params patched" % slc.id)
