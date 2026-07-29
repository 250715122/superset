# -*- coding: utf-8 -*-
"""Close the Public-role write bypass.

Root cause: PUBLIC_ROLE_LIKE="Gamma" copies Gamma's perms (incl. can_write on
Chart/Dashboard) onto the Public role. FAB's @protect checks is_item_public()
BEFORE the per-role check, so those writes are granted to everyone -- any
logged-in user, whatever their role, can edit/save-as charts.

Fix = two parts, both required:
  1) config: PUBLIC_ROLE_LIKE -> None   (stop re-copying on every startup)
  2) db:     strip all perms off the Public role (config alone leaves the
             already-copied perms in place)

Safe here: embedding is off (EMBEDDED_SUPERSET unset, embedded_dashboards=0),
no user is assigned the Public role, and the dashboard UI already redirects
anonymous visitors to /login/.

Dev & prod compatible. Idempotent. ASCII-safe output.
A Superset restart is required afterwards for the config part to take effect.
"""
import os
import shutil
import time

CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

OLD_CFG = 'PUBLIC_ROLE_LIKE: Optional[str] = "Gamma"'
NEW_CFG = ('# 匿名 Public 角色不再继承 Gamma：FAB 的 @protect 会先判定 is_item_public()，\n'
           '# 一旦 Public 持有 can_write，任何登录用户都能绕过角色 RBAC 编辑图表。\n'
           'PUBLIC_ROLE_LIKE: Optional[str] = None')

with open(CONF, encoding="utf-8") as _f:
    _src = _f.read()
if OLD_CFG in _src:
    _bak = "%s.bak_%s" % (CONF, time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(CONF, _bak)
    with open(CONF, "w", encoding="utf-8") as _f:
        _f.write(_src.replace(OLD_CFG, NEW_CFG, 1))
    print("CFG_BACKUP|%s" % _bak)
    print("CFG_EDITED|PUBLIC_ROLE_LIKE -> None")
elif "PUBLIC_ROLE_LIKE: Optional[str] = None" in _src:
    print("CFG_ALREADY|PUBLIC_ROLE_LIKE already None")
else:
    print("CFG_PATTERN_NOT_FOUND|check manually")

from superset.app import create_app  # noqa: E402

app = create_app()
with app.app_context():
    from sqlalchemy import text

    from superset import db, security_manager as sm

    # guard: never strip Public if embedding/guest access is actually in use
    ff = app.config.get("FEATURE_FLAGS") or {}
    if ff.get("EMBEDDED_SUPERSET"):
        try:
            n = db.session.execute(
                text("SELECT count(*) FROM embedded_dashboards")).scalar()
        except Exception:
            db.session.rollback()
            n = -1
        if n != 0:
            print("ABORT|embedding in use (embedded_dashboards=%s)" % n)
            raise SystemExit(1)

    nu = db.session.execute(text("""
        SELECT count(*) FROM ab_user_role ur
        JOIN ab_role r ON r.id = ur.role_id WHERE r.name = 'Public'
    """)).scalar()
    if nu:
        print("ABORT|%s user(s) assigned the Public role" % nu)
        raise SystemExit(1)

    pub = sm.find_role("Public")
    if not pub:
        print("NO_PUBLIC_ROLE")
        raise SystemExit(0)

    before = len(pub.permissions)
    pub.permissions = []
    db.session.commit()
    after = len(sm.find_role("Public").permissions)
    print("PUBLIC_STRIPPED|before=%d|after=%d" % (before, after))
    print("CFG_NOW|PUBLIC_ROLE_LIKE=%s (restart needed if still Gamma)"
          % app.config.get("PUBLIC_ROLE_LIKE"))
    print("FIX_PUBLIC_DONE")
