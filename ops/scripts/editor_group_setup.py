# -*- coding: utf-8 -*-
"""One-time setup so that editing ONE dashboard becomes a UI-only grant.

Creates/updates, for dashboard <id>:
  role  编辑·<看板名>   datasource_access on every dataset its charts use
  RBAC  attach that role to the dashboard's role list (this is what the
        patched raise_for_ownership keys on, and it grants viewing too)
  group <看板名>编辑    holds Gamma + 编辑·<看板名>

Daily grant afterwards: Security > List Groups > add user to the group.
Requires patch_editor_ownership.py to be applied (checked, warns if not).

Usage: editor_group_setup.py <dashboard_id> [--dry-run]
Idempotent, dev & prod compatible, ASCII-safe output.
"""
import os
import sys

CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from superset.app import create_app  # noqa: E402

DASH_ID = int(sys.argv[1])
DRY = "--dry-run" in sys.argv
ROLE_PREFIX = "\u7f16\u8f91\u00b7"          # 编辑·
GROUP_SUFFIX = "\u7f16\u8f91"               # 编辑


def e(s):
    return (s or "").encode("unicode_escape").decode()


with open(CONF, encoding="utf-8") as f:
    if "EDITOR_ROLE_PREFIX" not in f.read():
        print("WARN|config not patched yet -- run patch_editor_ownership.py "
              "first, otherwise group members cannot SAVE changes")

app = create_app()
with app.app_context():
    from flask_appbuilder.security.sqla.models import Group

    from superset import db, security_manager as sm
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.dashboard import Dashboard

    d = db.session.get(Dashboard, DASH_ID)
    if not d:
        print("ABORT|dashboard %s not found" % DASH_ID)
        sys.exit(1)
    title = (d.dashboard_title or "").strip() or ("id%s" % DASH_ID)
    role_name = ROLE_PREFIX + title
    group_name = title + GROUP_SUFFIX
    datasets = [db.session.get(SqlaTable, i)
                for i in sorted({s.datasource_id for s in d.slices
                                 if s.datasource_id})]
    print("PLAN|dash=%s(%s)|published=%s|charts=%d|datasets=%s|role=%s|group=%s"
          % (DASH_ID, e(title), d.published, len(d.slices),
             [t.id for t in datasets], e(role_name), e(group_name)))

    role = sm.find_role(role_name)
    if not role:
        role = sm.role_model(name=role_name)
        db.session.add(role)
        print("  ROLE_NEW|%s" % e(role_name))
    for t in datasets:
        pvm = sm.find_permission_view_menu("datasource_access", t.perm) \
            or sm.add_permission_view_menu("datasource_access", t.perm)
        if pvm not in role.permissions:
            role.permissions.append(pvm)
            print("  ROLE_GRANT|%s" % e(t.perm))

    if role not in d.roles:
        d.roles.append(role)
        print("  RBAC_ATTACH|%s -> dashboard %s" % (e(role_name), DASH_ID))

    grp = db.session.query(Group).filter_by(name=group_name).one_or_none()
    if not grp:
        grp = Group(name=group_name,
                    label=group_name,
                    description="editor group for dashboard %s" % DASH_ID)
        db.session.add(grp)
        print("  GROUP_NEW|%s" % e(group_name))
    gamma = sm.find_role("Gamma")
    for r in (gamma, role):
        if r not in grp.roles:
            grp.roles.append(r)
            print("  GROUP_ROLE|%s -> %s" % (e(r.name), e(group_name)))

    if DRY:
        db.session.rollback()
        print("DRY_RUN|rolled back")
    else:
        db.session.commit()
        print("SETUP_DONE|daily grant = add user to group '%s' in UI"
              % e(group_name))
