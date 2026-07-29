# -*- coding: utf-8 -*-
"""Grant (or revoke) full edit rights on ONE dashboard and all its charts.

Editing in 6.0.1 needs three things at once (all verified 2026-07-29):
  capability  Gamma (via the 看板制作者 group) -- can_write@Chart/Dashboard
  data        datasource_access on every dataset the dashboard's charts use.
              Mandatory: ChartFilter (charts REST API base filter) matches on
              dataset perms ONLY -- it ignores ownership, so without this the
              chart API returns 404 no matter who owns the chart.
  ownership   owner on the dashboard + each chart + each dataset -- non-admin
              holders of can_write may only save objects they own.

This script bundles them: a data role 编辑·<看板名> carries the dataset
grants; group membership carries the capability; owners are set per object.

Usage:
  python grant_dashboard_editor.py <dashboard_id> <user_id_or_username>
                                   [--revoke] [--dry-run]

revoke removes ownership + the data role from that user (role itself is kept
if others still hold it, deleted when orphaned). Group membership is NOT
revoked automatically (the user may edit other dashboards) -- prints a hint.
Idempotent, dev & prod compatible, ASCII-safe output.
"""
import os
import sys

CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from superset.app import create_app  # noqa: E402

ARGS = [a for a in sys.argv[1:] if not a.startswith("-")]
DASH_ID = int(ARGS[0])
WHO = ARGS[1]
REVOKE = "--revoke" in sys.argv
DRY = "--dry-run" in sys.argv
MAKER_GROUP = "看板制作者"
ROLE_PREFIX = "编辑·"


def e(s):
    return (s or "").encode("unicode_escape").decode()


app = create_app()
app.config["WTF_CSRF_ENABLED"] = False

with app.app_context():
    from flask_appbuilder.security.sqla.models import Group

    from superset import db, security_manager as sm
    from superset.connectors.sqla.models import SqlaTable
    from superset.models.dashboard import Dashboard

    user = (sm.get_user_by_id(int(WHO)) if WHO.isdigit()
            else sm.find_user(username=WHO))
    d = db.session.get(Dashboard, DASH_ID)
    if not user or not d:
        print("ABORT|user=%s dashboard=%s" % (bool(user), bool(d)))
        sys.exit(1)

    title = (d.dashboard_title or "").strip() or ("id%s" % DASH_ID)
    role_name = ROLE_PREFIX + title
    datasets = [db.session.get(SqlaTable, i)
                for i in sorted({s.datasource_id for s in d.slices
                                 if s.datasource_id})]
    targets = [(d, "dashboard")] + [(s, "chart:%s" % s.id) for s in d.slices] \
        + [(t, "dataset:%s" % t.id) for t in datasets]
    print("PLAN|%s|user=%s|dash=%s(%s)|charts=%d|datasets=%s"
          % ("REVOKE" if REVOKE else "GRANT", e(user.username), DASH_ID,
             e(title), len(d.slices), [t.id for t in datasets]))

    if not REVOKE:
        grp = (db.session.query(Group)
               .filter_by(name=MAKER_GROUP).one_or_none())
        held = {r.name for r in sm.get_user_roles(user)}
        if "Gamma" not in held and "Admin" not in held:
            if grp:
                grp.users.append(user)
                print("  CAPABILITY|joined group %s" % e(MAKER_GROUP))
            else:
                user.roles.append(sm.find_role("Gamma"))
                print("  CAPABILITY|direct Gamma (no maker group here)")

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
        if role not in user.roles:
            user.roles.append(role)
            print("  ROLE_ASSIGN|%s -> %s" % (e(role_name), e(user.username)))

        for obj, label in targets:
            if user not in obj.owners:
                obj.owners.append(user)
                print("  OWNER_ADD|%s" % label)
    else:
        for obj, label in targets:
            if user in obj.owners:
                obj.owners.remove(user)
                print("  OWNER_DEL|%s" % label)
        role = sm.find_role(role_name)
        if role and role in user.roles:
            user.roles.remove(role)
            print("  ROLE_UNASSIGN|%s" % e(role_name))
        if role and not role.user:
            role.permissions = []
            db.session.delete(role)
            print("  ROLE_DELETE|%s (orphaned)" % e(role_name))
        print("  HINT|group %s membership untouched -- remove manually if "
              "the user edits nothing else" % e(MAKER_GROUP))

    if DRY:
        db.session.rollback()
        print("DRY_RUN|rolled back")
        sys.exit(0)
    db.session.commit()
    uid = user.id
    probe = d.slices[0].id if d.slices else None

# functional check as the target user (fresh app context, see authz_model)
if probe:
    with app.app_context():
        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess["_user_id"] = str(uid)
                sess["_fresh"] = True
            g1 = c.get("/api/v1/chart/%s" % probe).status_code
            g2 = c.get("/explore/?slice_id=%s" % probe).status_code
            want = (200, 200) if not REVOKE else (404, g2)
            print("VERIFY|chart_api=%s|explore=%s|%s"
                  % (g1, g2, "OK" if (g1, g2) == want or REVOKE else "CHECK"))
print("EDITOR_%s_DONE" % ("REVOKE" if REVOKE else "GRANT"))
