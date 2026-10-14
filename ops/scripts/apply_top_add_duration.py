# -*- coding: utf-8 -*-
"""Add a max-duration column to the CPU / memory TOP charts.

Minimal patch on purpose: the two charts carry hand-made layout and display
settings, so only the metrics list is touched and everything else in params is
left exactly as saved.

Idempotent.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime

os.environ.setdefault("SUPERSET_CONFIG_PATH", "/mnt/data/superset/superset_config.py")
from superset.app import create_app  # noqa: E402

app = create_app()

BACKUP_DIR = "/mnt/data/superset/backups"
TARGETS = (648, 649)
LABEL = "最大耗时(毫秒)"
SQL = "MAX(query_ms)"
# insert before this label so the two duration columns sit together
ANCHOR = "平均耗时(毫秒)"


def metric(sql, label):
    return {
        "expressionType": "SQL", "sqlExpression": sql, "label": label,
        "hasCustomLabel": True, "aggregate": None, "column": None,
        "datasourceWarning": False,
        "optionName": "metric_%s" % hashlib.md5(
            label.encode("utf-8")).hexdigest()[:10],
    }


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    with app.app_context():
        from superset import db
        from superset.models.slice import Slice

        slices = {sid: db.session.get(Slice, sid) for sid in TARGETS}
        bpath = os.path.join(BACKUP_DIR, "top_charts_%s.json" % ts)
        with open(bpath, "w", encoding="utf-8") as f:
            json.dump({sid: {"slice_name": sl.slice_name, "params": sl.params,
                             "description": sl.description}
                       for sid, sl in slices.items()},
                      f, ensure_ascii=False, indent=1)
        print("BACKUP|%s" % bpath)

        for sid, sl in slices.items():
            p = json.loads(sl.params)
            before = [m.get("label") for m in p["metrics"]]
            if LABEL in before:
                print("SKIP|%s|%s already present" % (sid, LABEL))
                continue
            idx = next((i for i, m in enumerate(p["metrics"])
                        if m.get("label") == ANCHOR), len(p["metrics"]))
            p["metrics"].insert(idx, metric(SQL, LABEL))
            sl.params = json.dumps(p, ensure_ascii=False)
            sl.query_context = None
            print("SLICE|%s|%s" % (sid, sl.slice_name))
            print("   before=%s" % before)
            print("   after =%s" % [m.get("label") for m in p["metrics"]])
            print("   untouched_keys=%s" % len(
                [k for k in p if k != "metrics"]))

        db.session.commit()
        print("COMMIT_OK")


if __name__ == "__main__":
    main()
