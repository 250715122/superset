# -*- coding: utf-8 -*-
"""Repair the permalink salt rows so "copy permanent link" stops 500-ing.

The two shared salt rows in key_value hold base64-encoded JSON, left behind by
an older Superset; 6.0.1 reads them with a plain JsonKeyValueCodec and dies with
JSONDecodeError, so every permalink POST returns 500 for every user, admin
included.

Re-encodes in place (base64 -> plain JSON) rather than deleting the rows: the
salt value stays the same, so nothing else shifts. Rows that already decode are
left alone.

Dev & prod compatible. Idempotent. ASCII-safe output.
Usage: python fix_permalink_salt.py [--dry-run]
"""
import base64
import os
import sys

CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from superset.app import create_app  # noqa: E402

DRY = "--dry-run" in sys.argv

app = create_app()
app.config["WTF_CSRF_ENABLED"] = False

with app.app_context():
    from uuid import uuid3

    from superset import db, security_manager as sm
    from superset.key_value.models import KeyValueEntry
    from superset.key_value.shared_entries import get_uuid_namespace
    from superset.key_value.types import SharedKey
    from superset.models.dashboard import Dashboard
    import superset.key_value.shared_entries as se

    ns = get_uuid_namespace("")
    fixed = skipped = broken = 0

    for key in SharedKey:
        u = uuid3(ns, key)
        e = (db.session.query(KeyValueEntry)
             .filter_by(resource=se.RESOURCE.value, uuid=u).first())
        if not e or e.value is None:
            print("ABSENT|%s|will be generated on first use" % key.name)
            continue
        try:
            se.CODEC.decode(e.value)
            print("SKIP|%s|already decodes as JSON" % key.name)
            skipped += 1
            continue
        except Exception:  # noqa: BLE001
            pass
        try:
            value = se.CODEC.decode(base64.b64decode(e.value))
        except Exception as ex:  # noqa: BLE001
            print("BROKEN|%s|neither JSON nor base64+JSON: %s" % (key.name, ex))
            broken += 1
            continue
        e.value = se.CODEC.encode(value)
        fixed += 1
        print("FIX|%s|re-encoded, salt value unchanged (len=%d)"
              % (key.name, len(value) if hasattr(value, "__len__") else -1))

    if DRY:
        db.session.rollback()
        print("DRY_RUN|rolled back|fixed=%d skipped=%d broken=%d"
              % (fixed, skipped, broken))
        sys.exit(0)

    db.session.commit()

    # read back through the same helper the app uses
    for key in SharedKey:
        try:
            from superset.key_value.shared_entries import get_permalink_salt
            salt = get_permalink_salt(key)
            print("READBACK|%s|ok|len=%s" % (key.name, len(salt or "")))
        except Exception as ex:  # noqa: BLE001
            print("READBACK|%s|FAILED|%s: %s" % (key.name, type(ex).__name__, ex))

    # and prove the endpoint works end to end
    admin = sm.find_user(username="admin")
    d = db.session.query(Dashboard).filter_by(slug="pb-device-analysis").first()
    if admin and d:
        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess["_user_id"] = str(admin.id)
                sess["_fresh"] = True
            r = c.post("/api/v1/dashboard/%s/permalink" % d.id,
                       json={"dataMask": {}, "activeTabs": [], "anchor": ""})
            print("POST_dashboard_permalink|%s|%s"
                  % (r.status_code, r.get_data(as_text=True)[:120]))
            r2 = c.post("/api/v1/explore/permalink",
                        json={"formData": {"datasource": "%s__table"
                                           % d.slices[0].datasource_id,
                                           "viz_type": "table"}})
            print("POST_explore_permalink|%s|%s"
                  % (r2.status_code, r2.get_data(as_text=True)[:120]))
            ok = r.status_code in (200, 201) and r2.status_code in (200, 201)
    else:
        ok = False
        print("SKIP_HTTP_CHECK|admin or dashboard not found")

    print("SALT_%s|fixed=%d skipped=%d broken=%d"
          % ("OK" if ok else "CHECK_FAILED", fixed, skipped, broken))
