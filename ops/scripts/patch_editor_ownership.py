# -*- coding: utf-8 -*-
"""Patch superset_config.py: editor roles act as owners (page-only granting).

Inserts an override of raise_for_ownership() into CustomSsoSecurityManager:
when the stock ownership check fails, the user is still treated as owner if
they hold an editor role (name starts with 编辑·) that is attached to the
target dashboard's RBAC role list. Covers the dashboard itself and every
chart on it (mapping goes through dashboard.roles, so renaming a dashboard
does not break it).

With this in place the daily grant flow is UI-only: add the user to the
「<看板名>编辑」 group (Gamma + 编辑·X). No per-user owner rows, no scripts.

Idempotent; backs up the config; restart required afterwards.
"""
import os
import py_compile
import re
import shutil
import sys

CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")

BLOCK = '''
    # ---- 页面化编辑授权（2026-07-29）----------------------------------
    # 「编辑·X」角色挂在某看板的 RBAC 上时，持该角色的用户对这块看板及其
    # 全部图表视同 Owner（可保存修改）。这样日常开编辑权限只需把人加进
    # 「<看板名>编辑」组（Gamma + 编辑·X），纯页面操作。
    # 初始化每个看板的编辑角色/组用 _deploy/editor_group_setup.py。
    EDITOR_ROLE_PREFIX = "\\u7f16\\u8f91\\u00b7"  # 编辑·

    def _editor_role_covers(self, resource):
        try:
            from flask import g
            from superset.models.dashboard import Dashboard
            from superset.models.slice import Slice
            user = getattr(g, "user", None)
            if user is None or user.is_anonymous:
                return False
            held = {r.name for r in self.get_user_roles(user)
                    if r.name and r.name.startswith(self.EDITOR_ROLE_PREFIX)}
            if not held:
                return False

            def covered(dash):
                return any(r.name in held for r in dash.roles)

            if isinstance(resource, Dashboard):
                return covered(resource)
            if isinstance(resource, Slice):
                return any(covered(d) for d in resource.dashboards)
        except Exception:  # 判定失败一律回落到默认拒绝，绝不放大权限
            return False
        return False

    def raise_for_ownership(self, resource):
        from superset.exceptions import SupersetSecurityException
        try:
            return super().raise_for_ownership(resource)
        except SupersetSecurityException:
            if self._editor_role_covers(resource):
                return None
            raise

'''


def main():
    with open(CONF, encoding="utf-8") as f:
        src = f.read()
    if "EDITOR_ROLE_PREFIX" in src:
        print("SKIP|already patched")
        return
    m = re.search(r"^CUSTOM_SECURITY_MANAGER\s*=", src, re.M)
    if not m:
        print("ABORT|CUSTOM_SECURITY_MANAGER assignment not found")
        sys.exit(1)
    bak = CONF + ".bak.editorown"
    shutil.copy2(CONF, bak)
    patched = src[:m.start()] + BLOCK + "\n" + src[m.start():]
    with open(CONF, "w", encoding="utf-8") as f:
        f.write(patched)
    try:
        py_compile.compile(CONF, doraise=True)
    except py_compile.PyCompileError as exc:
        shutil.copy2(bak, CONF)
        print("ABORT|syntax error, restored backup: %s" % exc)
        sys.exit(1)
    print("PATCH_DONE|backup=%s" % bak)


if __name__ == "__main__":
    main()
