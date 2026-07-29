# -*- coding: utf-8 -*-
"""Single source of truth for the authorization model ("角色即代码").

Supersedes ro_role_policy.py. Target model (agreed 2026-07-28):

  只读基线    one capability role, generated from Gamma via the classify()
              policy below, holding ZERO data grants. The only read-only role
              that carries permissions.
  看板·<名>   one zero-permission "audience" role per dashboard, whose only job
              is to sit in that dashboard's RBAC list. (A see-everything
              看板·全部 role existed briefly and was retired on 2026-07-29:
              per-dashboard roles are the only grant path.) Verified on 6.0.1:
              with DASHBOARD_RBAC on, a published dashboard with roles is
              listed / opened / queried (charts, native filters, drills) purely
              on role membership -- no datasource_access needed -- and once a
              dashboard has roles the dataset-based fallback is switched off
              for it (superset/dashboards/filters.py DashboardAccessFilter,
              superset/security/manager.py raise_for_access).
  组          groups hold 只读基线 + audience roles; operators only touch
              group membership day to day.

Subcommands (all support --dry-run):

  baseline    build/repair 只读基线 (rename from Gamma-Readonly, merge and
              delete Gamma-Readonly+, apply policy, strip all data grants)
  migrate     per dashboard: create 看板·<名>, attach it to the dashboard's
              RBAC list, hand the audience role to exactly the
              groups/users who can currently see the dashboard. Committed one
              dashboard at a time; per-user visibility is re-measured after
              each commit and the dashboard is reverted if anyone's list
              changed.
  revoke      strip datasource/schema/database/all_datasource grants from the
              legacy data roles (visibility must stay identical, since every
              published dashboard is RBAC-driven by then)
  retire      delete the now-empty legacy data roles

Implementation note: visibility is measured through the real API with a test
client inside a *fresh app context* per request (g is bound to the app context
and @protect reads g.user). Popping that context makes flask-sqlalchemy remove
the scoped session, detaching every ORM object loaded before -- so across
snapshots this script only carries plain ids/names and re-queries everything.

Dev & prod compatible. Idempotent. ASCII-safe output.
Usage: python authz_model.py {baseline|migrate|revoke|retire} [--dry-run]
"""
import re
import sys
import os

CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from superset.app import create_app  # noqa: E402

CMD = next((a for a in sys.argv[1:] if not a.startswith("-")), "audit")
DRY = "--dry-run" in sys.argv

BASELINE = "只读基线"
LEGACY_BASELINE = "Gamma-Readonly"      # renamed in place (keeps group links)
LEGACY_BASELINE_DUP = "Gamma-Readonly+"  # byte-identical duplicate, deleted
AUD_PREFIX = "看板·"

# legacy data roles, dev and prod names; stripped by `revoke`, deleted by
# `retire`. newapi is deliberately NOT here (integration account, undecided).
DATA_ROLES = ["卡车电池只读", "全局看板只读", "智能客服", "智能客服-监控看板",
              "Dify监控", "Dify监控看板", "VOC看板", "PV预测", "PV预测看板",
              "电池包数据", "SOH异常检测"]

DATA_PERMS = {"datasource_access", "database_access", "schema_access",
              "catalog_access", "all_datasource_access", "all_database_access"}

# --- capability policy (carried over from ro_role_policy.py) ---------------
READ_NAMES = re.compile(
    r"^(can_read|can_list|can_show|can_get|can_info|can_export|can_csv|"
    r"can_userinfo|can_profile|can_recent_activity|can_this_form_get|"
    r"can_explore|can_explore_json|can_datasources|can_dashboard|can_slice|"
    r"can_share_dashboard|can_share_chart|can_view_and_drill|can_drill|"
    r"can_view_chart_as_table|can_view_query|can_show_query|can_log|"
    r"can_time_range|can_language_pack|can_dashboard_permalink|"
    r"can_external_metadata|can_external_metadata_by_name|"
    r"can_fetch_datasource_metadata|can_get_drill_info|can_get_embedded|"
    r"can_query_form_data|can_available_domains|can_tags|menu_access)$")

ALLOW_WRITE = {
    ("can_write", "DashboardFilterStateRestApi"):
        "原生筛选器状态，写的是本人临时 key，不改看板",
    ("can_write", "DashboardPermalinkRestApi"): "生成看板分享链接",
    ("can_write", "ExploreFormDataRestApi"): "下钻/查看时暂存表单态，本人临时 key",
    ("can_write", "ExplorePermalinkRestApi"): "生成图表分享链接",
    ("can_query", "Api"): "遗留取数接口，POST 只为携带查询载荷，语义是读",
    ("can_this_form_post", "ResetMyPasswordView"): "自助修改本人密码",
    ("resetmypassword", "UserDBModelView"): "自助改密（FAB action，无路由）",
    ("can_this_form_post", "UserInfoEditView"): "编辑本人资料（仅当前用户）",
    ("userinfoedit", "UserDBModelView"): "编辑本人资料（FAB action，无路由）",
}

DENY_EXTRA = {
    ("can_tag", "Chart"): "给图表打标签（代码内校验，无路由）",
    ("can_tag", "Dashboard"): "给看板打标签（同上）",
    ("can_delete_embedded", "Dashboard"):
        "无效条目：DELETE /embedded 实际校验 can_set_embedded",
    ("can_put_chart_customizations", "Dashboard"): "死条目：6.0.1 无实现",
    ("can_copy_clipboard", "Superset"): "死条目：6.0.1 无实现",
    ("can_file_handler", "Superset"): "死条目：6.0.1 无实现",
    ("can_export_as_example", "Dashboard"): "死条目：6.0.1 无实现",
    ("can_export_streaming_csv", "SQLLab"): "死条目：6.0.1 无实现",
    ("can_store", "KV"): "死条目：KV 视图已移除",
    ("can_get_value", "KV"): "死条目：KV 视图已移除",
    ("can_read", "security"): "安全管理面只读，观众不需要",
    ("can_read", "RowLevelSecurity"): "可读出 RLS 规则内容",
    ("can_estimate_query_cost", "SQLLab"): "SQL Lab 专属，观众不需要",
    ("can_format_sql", "SQLLab"): "SQL Lab 专属，观众不需要",
}

MUTATING_VERBS = {"POST", "PUT", "PATCH", "DELETE"}

DENY_NAMES = {
    "can_add", "can_edit", "can_delete", "can_write", "can_save", "muldelete",
    "can_import", "can_duplicate", "can_copy", "can_store", "can_invalidate",
    "can_bulk_create", "can_set_embedded", "can_cache_dashboard_screenshot",
    "can_put_chart_customizations", "can_tag", "can_grant", "can_revoke",
    "can_upload", "can_execute", "can_publish", "can_approve",
}

# self-service grants the baseline needs even if Gamma lacks them (added by
# fix_selfservice_perms.py in the past); only attached when the pvm exists
EXTRA_GRANTS = list(ALLOW_WRITE) + [
    ("can_read", "user"), ("can_userinfo", "UserDBModelView"),
    ("can_this_form_get", "ResetMyPasswordView"),
    ("can_this_form_get", "UserInfoEditView"),
]

DASH_Q = "/api/v1/dashboard/?q=(page_size:200,columns:!(id))"


def e(s):
    return (s or "").encode("unicode_escape").decode()


app = create_app()
app.config["WTF_CSRF_ENABLED"] = False

# (permission, class_permission_name) -> set of HTTP verbs it guards
VERBS = {}
for bv in app.appbuilder.baseviews:
    cpn = getattr(bv, "class_permission_name", None) or type(bv).__name__
    mpn = getattr(bv, "method_permission_name", None) or {}
    for attr in dir(bv):
        if attr.startswith("__"):
            continue
        f = getattr(bv, attr, None)
        if not callable(f):
            continue
        pname = mpn.get(attr) or getattr(f, "_permission_name", None)
        if not pname:
            continue
        for u in (getattr(f, "_urls", None) or []):
            VERBS.setdefault(("can_" + pname, cpn), set()).update(
                v.upper() for v in (u[1] or ["GET"]))


def classify(perm, view):
    """-> (keep: bool, reason: str). Data grants never reach the baseline."""
    if perm in DATA_PERMS:
        return False, "数据授权不属于能力基线"
    if (perm, view) in ALLOW_WRITE:
        return True, "允许的写：" + ALLOW_WRITE[(perm, view)]
    verbs = VERBS.get((perm, view), set())
    if perm in DENY_NAMES:
        return False, "写类动作名" + ("" if verbs else "（当前无路由，仍拒绝）")
    if (perm, view) in DENY_EXTRA:
        return False, DENY_EXTRA[(perm, view)]
    if READ_NAMES.match(perm):
        return True, "read"
    hit = verbs & MUTATING_VERBS
    if hit:
        return False, "守 %s 路由" % ",".join(sorted(hit))
    return True, "GET-only" if verbs else "no route / non-web grant"


def visible(user_id):
    """Dashboard ids the user sees, measured through the real API.

    Fresh app context per call (g/@protect correctness). Side effect: popping
    the context removes the scoped session -- callers must re-query ORM
    objects afterwards.
    """
    with app.app_context():
        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess["_user_id"] = str(user_id)
                sess["_fresh"] = True
            r = c.get(DASH_Q)
            if r.status_code != 200:
                return ("http_%s" % r.status_code,)
            return tuple(sorted(x["id"] for x in r.get_json()["result"]))


def pv_name(pv):
    return (pv.permission.name if pv.permission else "",
            pv.view_menu.name if pv.view_menu else "")


with app.app_context():
    from flask_appbuilder.security.sqla.models import Group

    from superset import db, security_manager as sm
    from superset.models.dashboard import Dashboard

    # plain data only -- survives session teardown caused by visible()
    WATCHED = [(u.id, u.username) for u in sm.get_all_users() if u.is_active
               and "Admin" not in {r.name for r in sm.get_user_roles(u)}]

    def snapshot():
        return {uid: visible(uid) for uid, _ in WATCHED}

    def diff_snap(before, after):
        return [(uname, before.get(uid), after.get(uid))
                for uid, uname in WATCHED if before.get(uid) != after.get(uid)]

    def observer_group_names():
        return [g.name for g in db.session.query(Group).all()
                if not {"Gamma", "Admin"} & {r.name for r in g.roles}]

    def ensure_role(name):
        """find-or-create WITHOUT committing. Never use sm.add_role here:
        it commits the whole session, flushing half-done loop iterations
        (this bit us once: a migrate --dry-run leaked RBAC attachments)."""
        r = sm.find_role(name)
        if not r:
            r = sm.role_model(name=name)
            db.session.add(r)
        return r

    OBS_GROUPS = observer_group_names()

    # ------------------------------------------------------------- baseline
    if CMD == "baseline":
        snap0 = None if DRY else snapshot()

        gamma = sm.find_role("Gamma")
        role = sm.find_role(BASELINE) or sm.find_role(LEGACY_BASELINE)
        if not gamma or not role:
            print("ABORT|missing role|gamma=%s|baseline=%s" % (bool(gamma),
                                                               bool(role)))
            sys.exit(1)
        if role.name != BASELINE:
            print("RENAME|%s -> %s" % (e(role.name), e(BASELINE)))
            role.name = BASELINE

        held = {pv_name(pv) for pv in role.permissions}
        added = removed = 0
        for pv in gamma.permissions:
            perm, view = pv_name(pv)
            keep, reason = classify(perm, view)
            if keep and (perm, view) not in held:
                role.permissions.append(pv)
                added += 1
                print("  ADD|%-34s %-30s %s" % (perm, view, e(reason)))
        for pv in list(role.permissions):
            perm, view = pv_name(pv)
            keep, reason = classify(perm, view)
            if not keep:
                role.permissions.remove(pv)
                removed += 1
                print("  REMOVE|%-34s %-30s %s" % (perm, view, e(reason)))
        for perm, view in EXTRA_GRANTS:
            pvm = sm.find_permission_view_menu(perm, view)
            if pvm and pvm not in role.permissions:
                role.permissions.append(pvm)
                added += 1
                print("  ADD_EXTRA|%-30s %s" % (perm, view))

        # fold the byte-identical duplicate into the baseline
        dup = sm.find_role(LEGACY_BASELINE_DUP)
        if dup:
            for u in sm.get_all_users():
                if dup in u.roles:
                    u.roles.remove(dup)
                    if role not in u.roles:
                        u.roles.append(role)
                    print("  DUP_HOLDER|%s -> %s" % (e(u.username),
                                                     e(BASELINE)))
            for g in db.session.query(Group).all():
                if dup in g.roles:
                    g.roles.remove(dup)
                    if role not in g.roles:
                        g.roles.append(role)
            dup.permissions = []
            db.session.delete(dup)
            print("  DELETE_ROLE|%s" % e(LEGACY_BASELINE_DUP))

        residual = sorted("%s@%s" % pv_name(pv) for pv in role.permissions
                          if not classify(*pv_name(pv))[0])
        print("BASELINE|added=%d|removed=%d|total=%d|residual=%s"
              % (added, removed, len(role.permissions), residual))

        if DRY:
            db.session.rollback()
            print("DRY_RUN|rolled back")
            sys.exit(0)
        db.session.commit()
        drift = diff_snap(snap0, snapshot())
        for uname, b, a in drift:
            print("VIS_CHANGED|%s|before=%s|after=%s" % (e(uname), b, a))
        print("BASELINE_OK" if not drift
              else "BASELINE_VIS_DRIFT|%d" % len(drift))

    # -------------------------------------------------------------- migrate
    elif CMD == "migrate":
        if not sm.find_role(BASELINE):
            print("ABORT|run baseline first")
            sys.exit(1)

        before = snapshot()   # read-only; needed even in dry-run to derive audiences
        dash_ids = [d.id for d in
                    db.session.query(Dashboard).order_by(Dashboard.id).all()]

        for did in dash_ids:
            # everything re-queried: previous snapshot detached the session
            d = db.session.get(Dashboard, did)
            title = (d.dashboard_title or "").strip()
            aud_name = AUD_PREFIX + (title if title and "untitled" not in title
                                     else "id%s" % did)
            aud = ensure_role(aud_name)
            if aud.permissions:
                print("WARN|%s 不是零权限角色(%d 条)，不动它的权限"
                      % (e(aud_name), len(aud.permissions)))

            # who can see this dashboard right now
            aud_groups, covered = [], set()
            for g in db.session.query(Group).all():
                if g.name not in OBS_GROUPS:
                    continue
                members = [u for u in g.users
                           if u.is_active and u.id in before]
                if members and all(did in before[u.id] for u in members):
                    aud_groups.append(g)
                    covered |= {u.id for u in members}
            owner_ids = {u.id for u in (d.owners or [])}
            direct_users = [u for u in sm.get_all_users()
                            if u.id in before and did in before[u.id]
                            and u.id not in covered and u.id not in owner_ids]

            touched = []      # plain identifiers, survives session teardown
            if aud not in d.roles:
                d.roles.append(aud)
                touched.append(("dash", did, aud.name))
            for g in aud_groups:
                if aud not in g.roles:
                    g.roles.append(aud)
                    touched.append(("group", g.name, aud_name))
            for u in direct_users:
                if aud not in u.roles:
                    u.roles.append(aud)
                    touched.append(("user", u.id, aud_name))

            print("DASH|%-4s|%-30s|pub=%-5s|groups=%s|direct=%s"
                  % (did, e(title or "-"), d.published,
                     [e(g.name) for g in aud_groups] or "-",
                     [e(u.username) for u in direct_users] or "-"))
            if DRY:
                continue
            db.session.commit()
            after = snapshot()
            drift = diff_snap(before, after)
            if drift:
                d = db.session.get(Dashboard, did)   # revert this dashboard
                for kind, ident, rname in touched:
                    r = sm.find_role(rname)
                    if kind == "dash" and r in d.roles:
                        d.roles.remove(r)
                    elif kind == "group":
                        g = (db.session.query(Group)
                             .filter_by(name=ident).one())
                        if r in g.roles:
                            g.roles.remove(r)
                    elif kind == "user":
                        u = sm.get_user_by_id(ident)
                        if r in u.roles:
                            u.roles.remove(r)
                db.session.commit()
                for uname, b, a in drift:
                    print("  DRIFT|%s|before=%s|after=%s" % (e(uname), b, a))
                print("MIGRATE_FAILED|dash=%s reverted" % did)
                sys.exit(1)
            before = after
        if DRY:
            db.session.rollback()
            print("DRY_RUN|rolled back")
        else:
            print("MIGRATE_OK|dashboards=%d" % len(dash_ids))

    # --------------------------------------------------------------- revoke
    elif CMD == "revoke":
        naked = [d.id for d in db.session.query(Dashboard).all()
                 if d.published and not d.roles]
        if naked:
            print("ABORT|published dashboards without RBAC roles: %s" % naked)
            sys.exit(1)
        before = None if DRY else snapshot()
        stripped = []     # (role_name, perm, view) -- plain, for restore
        for name in DATA_ROLES:
            r = sm.find_role(name)
            if not r:
                continue
            for pv in list(r.permissions):
                perm, view = pv_name(pv)
                if perm in DATA_PERMS:
                    r.permissions.remove(pv)
                    stripped.append((name, perm, view))
                    print("  STRIP|%-22s|%s:%s" % (e(name), perm, e(view)))
        print("REVOKE|roles_touched=%d|grants_stripped=%d"
              % (len({n for n, _, _ in stripped}), len(stripped)))
        if DRY:
            db.session.rollback()
            print("DRY_RUN|rolled back")
            sys.exit(0)
        db.session.commit()
        drift = diff_snap(before, snapshot())
        if drift:
            for name, perm, view in stripped:
                r = sm.find_role(name)
                pvm = sm.find_permission_view_menu(perm, view)
                if pvm and pvm not in r.permissions:
                    r.permissions.append(pvm)
            db.session.commit()
            for uname, b, a in drift:
                print("  DRIFT|%s|before=%s|after=%s" % (e(uname), b, a))
            print("REVOKE_FAILED|grants restored")
            sys.exit(1)
        print("REVOKE_OK")

    # --------------------------------------------------------------- retire
    elif CMD == "retire":
        before = None if DRY else snapshot()
        base = sm.find_role(BASELINE)
        for name in DATA_ROLES:
            r = sm.find_role(name)
            if not r:
                continue
            data_left = [pv for pv in r.permissions
                         if pv_name(pv)[0] in DATA_PERMS]
            if data_left:
                print("SKIP|%s still holds %d data grants -- run revoke"
                      % (e(name), len(data_left)))
                continue
            for d in db.session.query(Dashboard).all():
                if r in d.roles:
                    d.roles.remove(r)
            # fat legacy roles double as capability baseline for their
            # holders -- swap in 只读基线 or members would lose everything
            for g in db.session.query(Group).all():
                if r in g.roles:
                    g.roles.remove(r)
                    if base not in g.roles:
                        g.roles.append(base)
                        print("  BASELINE_SWAP|group %s" % e(g.name))
            for u in sm.get_all_users():
                if r in u.roles:
                    u.roles.remove(r)
                    held = {x.name for x in sm.get_user_roles(u)}
                    if BASELINE not in held and "Admin" not in held \
                            and "Gamma" not in held:
                        u.roles.append(base)
                        print("  BASELINE_SWAP|user %s" % e(u.username))
            r.permissions = []
            db.session.delete(r)
            print("DELETE_ROLE|%s" % e(name))
        if DRY:
            db.session.rollback()
            print("DRY_RUN|rolled back")
            sys.exit(0)
        db.session.commit()
        drift = diff_snap(before, snapshot())
        for uname, b, a in drift:
            print("  DRIFT|%s|before=%s|after=%s" % (e(uname), b, a))
        print("RETIRE_OK" if not drift else "RETIRE_VIS_DRIFT|%d" % len(drift))

    else:
        print("usage: authz_model.py {baseline|migrate|revoke|retire}"
              " [--dry-run]")
print("AUTHZ_DONE|%s%s" % (CMD, "|dry" if DRY else ""))
