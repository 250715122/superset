# -*- coding: utf-8 -*-
"""Stand up (and tear down) a tab-restriction demo for hands-on verification.

``setup`` restricts one tab of a dashboard to a throwaway role and creates a
throwaway account that can open the dashboard but does *not* hold that role,
so signing in as it shows the tab missing. Granting the role to that account
afterwards - from the UI, which is the point of the exercise - makes the tab
reappear.

``teardown`` puts the dashboard's metadata back byte for byte from the copy
setup saved, then deletes the account and the role.

Only ``tab_roles`` is touched; every other key of ``json_metadata`` is left
exactly as it was.

Usage:
  setup_tab_access_demo.py setup <dashboard id> [tab id] [--password ...]
  setup_tab_access_demo.py teardown <dashboard id>
"""
import os
import sys

os.environ.setdefault("SUPERSET_CONFIG_PATH", "/opt/superset/superset_config.py")
from superset.app import create_app  # noqa: E402

ROLE_NAME = "演示·仅运维可见"
USER_NAME = "tabdemo"
DEFAULT_PASSWORD = "TabDemo@2026"
BACKUP_DIR = os.path.expanduser("~/bi-tabaccess")


def backup_path(dashboard_id):
    return os.path.join(BACKUP_DIR, "_demo_metadata_%s.json" % dashboard_id)


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("setup", "teardown"):
        sys.exit(__doc__)
    action = sys.argv[1]
    dashboard_id = int(sys.argv[2])
    rest = sys.argv[3:]
    password = DEFAULT_PASSWORD
    if "--password" in rest:
        password = rest[rest.index("--password") + 1]
        rest = rest[: rest.index("--password")]
    tab_arg = rest[0] if rest else None

    app = create_app()
    with app.app_context():
        from superset import db, security_manager
        from superset.models.dashboard import Dashboard
        from superset.utils import json

        dash = db.session.get(Dashboard, dashboard_id)
        if not dash:
            sys.exit("dashboard %s not found" % dashboard_id)

        if action == "teardown":
            path = backup_path(dashboard_id)
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    dash.json_metadata = fh.read()
                os.remove(path)
                print("restored json_metadata of dashboard %s" % dashboard_id)
            else:
                metadata = json.loads(dash.json_metadata or "{}")
                metadata.pop("tab_roles", None)
                dash.json_metadata = json.dumps(metadata)
                print("no backup found; removed tab_roles only")

            user = security_manager.find_user(username=USER_NAME)
            if user:
                db.session.delete(user)
                print("deleted user %s" % USER_NAME)
            role = security_manager.find_role(ROLE_NAME)
            if role:
                db.session.delete(role)
                print("deleted role %s" % ROLE_NAME)
            db.session.commit()
            print("DONE")
            return

        position = json.loads(dash.position_json or "{}")
        tabs = {k: v for k, v in position.items()
                if isinstance(v, dict) and v.get("type") == "TAB"}
        if not tabs:
            sys.exit("dashboard %s has no tabs" % dashboard_id)

        if tab_arg and tab_arg not in tabs:
            sys.exit("tab %s is not on this dashboard. tabs are:\n%s" % (
                tab_arg,
                "\n".join("  %s  %s" % (k, (v.get("meta") or {}).get("text", ""))
                          for k, v in sorted(tabs.items()))))
        # default to the last tab, which is usually the detail-heavy one
        tab_id = tab_arg or sorted(tabs)[-1]
        tab_title = (tabs[tab_id].get("meta") or {}).get("text") or tab_id

        os.makedirs(BACKUP_DIR, exist_ok=True)
        path = backup_path(dashboard_id)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(dash.json_metadata or "")
            print("saved current json_metadata to %s" % path)

        role = (security_manager.find_role(ROLE_NAME)
                or security_manager.add_role(ROLE_NAME))

        viewer_roles = [r for r in (dash.roles or [])
                        if not r.name.startswith(security_manager.EDITOR_ROLE_PREFIX)]
        base = security_manager.find_role("只读基线")
        if base and base not in viewer_roles:
            viewer_roles.append(base)
        if not viewer_roles:
            sys.exit("dashboard %s grants no viewer role, so a demo account "
                     "could not open it at all" % dashboard_id)

        user = security_manager.find_user(username=USER_NAME)
        if user:
            user.roles = viewer_roles
            security_manager.reset_password(user.id, password)
        else:
            user = security_manager.add_user(
                USER_NAME, "Tab", "Demo", "tabdemo@example.com",
                viewer_roles[0], password=password)
            user.roles = viewer_roles

        metadata = json.loads(dash.json_metadata or "{}")
        metadata["tab_roles"] = {tab_id: [ROLE_NAME]}
        dash.json_metadata = json.dumps(metadata)
        db.session.commit()

        charts = []
        stack = [tab_id]
        while stack:
            node = position.get(stack.pop())
            if not isinstance(node, dict):
                continue
            if node.get("type") == "CHART":
                charts.append((node.get("meta") or {}).get("chartId"))
            stack.extend(node.get("children") or [])

        print("""
演示环境已就绪
---------------------------------------------------------------
看板            {title}  (id={did})
受限 Tab        {tab_title}   ({tab_id})
该 Tab 下图表   {charts}
限定角色        {role}

演示账号        用户名 {user}
                密码   {password}
                角色   {roles}
                —— 注意它没有「{role}」，所以看不到该 Tab

怎么验证
 1. 用演示账号登录，打开该看板：只应看到除「{tab_title}」以外的 Tab。
 2. 用管理员登录同一个看板：两个 Tab 都在。
 3. 管理员 → 设置 → 列表查看 → 用户 → 编辑 {user}，加上「{role}」角色。
    演示账号重新登录，「{tab_title}」出现。
 4. 收回该角色，Tab 再次消失。

验收完成后执行：
  python setup_tab_access_demo.py teardown {did}
---------------------------------------------------------------
""".format(title=dash.dashboard_title, did=dashboard_id, tab_title=tab_title,
           tab_id=tab_id, charts=sorted(c for c in charts if c),
           role=ROLE_NAME, user=USER_NAME, password=password,
           roles=[r.name for r in viewer_roles]))


main()
