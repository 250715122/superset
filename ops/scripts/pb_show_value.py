# -*- coding: utf-8 -*-
"""Enable 'show value' on all bar charts of the truck-battery dashboard.

Dev & prod compatible. Idempotent. ASCII-safe output.
"""
import json
import os

CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from superset.app import create_app  # noqa: E402

app = create_app()
with app.app_context():
    from superset import db
    from superset.models.dashboard import Dashboard

    d = db.session.query(Dashboard).filter_by(slug="pb-device-analysis").first()
    if not d:
        print("DASH NOT FOUND")
        raise SystemExit(1)

    changed = 0
    for s in d.slices:
        if "bar" not in (s.viz_type or ""):
            continue
        p = json.loads(s.params or "{}")
        if p.get("show_value") is True:
            print("SKIP|%s|%s|already on" % (s.id, s.viz_type))
            continue
        p["show_value"] = True
        s.params = json.dumps(p, ensure_ascii=False)
        changed += 1
        print("ON|%s|%s" % (s.id, s.viz_type))
    db.session.commit()
    print("SHOW_VALUE_DONE|changed=%d" % changed)
