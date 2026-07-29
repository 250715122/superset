# -*- coding: utf-8 -*-
"""Grant the per-user self-service permissions to every custom role.

Two things broke profile access for users on custom roles:

1. The instance runs AUTH_OAUTH, so /users/userinfo/ is served by
   UserOAuthModelView, but all granted perms sat on UserDBModelView (leftovers
   from the AUTH_DB era). `superset init` creates the UserOAuthModelView perms
   and grants them to the built-in roles only.
2. CurrentUserRestApi.can_read (the /api/v1/me/ endpoint the navbar calls) used
   to reach everyone through PUBLIC_ROLE_LIKE=Gamma; that shortcut is gone.

Superset itself classifies can_userinfo as ACCESSIBLE_PERMS ("accessible to all
users"), so handing these to every real role matches upstream intent.
Idempotent.
"""
import os

CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from superset.app import create_app  # noqa: E402

# Public must stay empty: granting it anything re-opens the is_item_public
# bypass that let any logged-in user act with the Public role's rights.
SKIP_ROLES = {"Public"}

WANTED = [
    # What the navbar's Settings > Info item actually hits: Superset 6 points it
    # at /user_info/ (UserInfoView.list, class_permission_name="user"), NOT the
    # FAB /users/userinfo/ page. This is the one that produced the
    # "Access is Denied" toast.
    ("can_read", "user"),
    ("can_userinfo", "UserOAuthModelView"),   # FAB profile page under OAUTH
    ("can_userinfo", "UserDBModelView"),      # kept for AUTH_DB fallback
    ("can_read", "CurrentUserRestApi"),       # /api/v1/me/ used by the navbar
    ("can_recent_activity", "Log"),
]

app = create_app()
with app.app_context():
    from superset import db, security_manager as sm

    pvms = {}
    for perm, view in WANTED:
        pvm = sm.find_permission_view_menu(perm, view)
        if not pvm:
            # Superset registers the view but the permission row only appears
            # when `superset init` runs; create it so this script stands alone.
            pvm = sm.add_permission_view_menu(perm, view)
            print("PVM|%s@%s|CREATED" % (perm, view))
        else:
            print("PVM|%s@%s|found" % (perm, view))
        pvms[(perm, view)] = pvm

    changed = 0
    for role in sorted(sm.get_all_roles(), key=lambda r: r.name):
        if role.name in SKIP_ROLES:
            print("SKIP|%s" % role.name.encode("unicode_escape").decode())
            continue
        have = {(pv.permission.name, pv.view_menu.name)
                for pv in role.permissions if pv.permission and pv.view_menu}
        added = []
        for key, pvm in pvms.items():
            if pvm and key not in have:
                role.permissions.append(pvm)
                added.append("%s@%s" % key)
        if added:
            changed += 1
            print("GRANT|%s|%s"
                  % (role.name.encode("unicode_escape").decode(), added))
        else:
            print("OK|%s|already complete"
                  % role.name.encode("unicode_escape").decode())

    if changed:
        db.session.commit()
    print("FIX_DONE|roles_changed=%d" % changed)
