# -*- coding: utf-8 -*-
"""Grant the read-side MetaSearch permissions to dashboard 38's audience role.

The 数据资产检索 page is embedded in dashboard 38「数据资产」tab. Whoever can
open dashboard 38 (via its guard role 看板·数据中台全局速览) should also be
able to READ the search page. Right now only Admin holds those permissions, so
every non-admin viewer gets a 403 inside the iframe.

What this does (idempotent):
  - add can_index / can_search / can_columns / can_stats to
    看板·数据中台全局速览  (the same role that gates the hosting dashboard)
  - leaves can_confirm (a WRITE: it rewrites column comments) Admin-only
  - also covers 看板·数据中台全局速览-只读 if it exists, for symmetry

Usage: grant_meta_search_roles.py [--dry-run]
"""
import json
import os
import sys
import time

CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

DRY = "--dry-run" in sys.argv

READ_PERMS = ["can_index", "can_search", "can_columns", "can_stats"]
WRITE_PERMS = ["can_confirm"]          # intentionally NOT granted to viewers
TARGET_ROLES = ["看板·数据中台全局速览",
                "看板·数据中台全局速览-只读"]

from flask_appbuilder.security.sqla.models import Role, PermissionView  # noqa: E402
from superset.app import create_app  # noqa: E402

app = create_app()
with app.app_context():
    from superset import db

    # snapshot the current holders of every MetaSearch perm
    pv_rows = db.session.query(PermissionView).join(
        PermissionView.view_menu, aliased=True).filter(
        PermissionView.view_menu.has(name="MetaSearch")).all()

    def before_state():
        out = {}
        for pv in pv_rows:
            out[pv.permission.name] = sorted(r.name for r in pv.role)
        return out

    before = before_state()
    print("BEFORE|%s" % json.dumps(before, ensure_ascii=True, sort_keys=True))

    if not DRY:
        backup = os.path.join(os.path.dirname(CONF), "backups",
                              "meta_search_grant_%s.json"
                              % time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        with open(backup, "w") as fh:
            json.dump(before, fh, ensure_ascii=True, indent=1, sort_keys=True)
        print("BACKUP|%s" % backup)

    perm_by_name = {pv.permission.name: pv for pv in pv_rows}

    for role_name in TARGET_ROLES:
        role = db.session.query(Role).filter_by(name=role_name).first()
        if role is None:
            print("ROLE|%s|不存在，跳过" % role_name)
            continue
        for perm in READ_PERMS:
            pv = perm_by_name[perm]
            if role in pv.role:
                print("GRANT|%s|%s|已有，跳过" % (role_name, perm))
                continue
            print("GRANT|%s|%s|追加授权" % (role_name, perm))
            if not DRY:
                pv.role.append(role)

    if DRY:
        db.session.rollback()
        print("DRY_RUN|未提交")
    else:
        db.session.commit()
        print("COMMITTED")

    db.session.expire_all()
    after = before_state()
    print("AFTER|%s" % json.dumps(after, ensure_ascii=True, sort_keys=True))
