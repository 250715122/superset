# -*- coding: utf-8 -*-
"""Register the password views that FAB skips under AUTH_OAUTH.

FAB only wires ResetMyPasswordView (self-service) and ResetPasswordView (admin
resets someone else) when AUTH_TYPE == AUTH_DB. Since this instance keeps local
accounts alive alongside SSO, both pages need to exist. Idempotent: run it
twice and the second run reports NOOP.

Usage: python enable_password_views.py [/path/to/superset_config.py]
"""
import os
import shutil
import sys
import time

CONF = sys.argv[1] if len(sys.argv) > 1 else (
    "/opt/superset/superset_config.py"
    if os.path.exists("/opt/superset/superset_config.py")
    else "/mnt/data/superset/superset_config.py")

ANCHOR = """        self.authoauthview = lambda: dual
        super().register_views()
"""

ADDITION = """        self.authoauthview = lambda: dual
        super().register_views()
        # FAB 只在 AUTH_DB 下注册这两个视图，OAUTH 下本地账号就没有改密码入口。
        # 双登录保留了本地账号，所以把自助改密码 / 管理员重置密码补回来。
        self.appbuilder.add_view_no_menu(self.resetmypasswordview())
        self.appbuilder.add_view_no_menu(self.resetpasswordview())
"""

with open(CONF, encoding="utf-8") as f:
    src = f.read()

if "resetmypasswordview()" in src:
    print("NOOP|password views already registered in %s" % CONF)
    sys.exit(0)

if src.count(ANCHOR) != 1:
    print("ABORT|anchor found %d times, expected 1" % src.count(ANCHOR))
    sys.exit(1)

bak = "%s.bak.%s" % (CONF, time.strftime("%Y%m%d%H%M%S"))
shutil.copy2(CONF, bak)
with open(CONF, "w", encoding="utf-8") as f:
    f.write(src.replace(ANCHOR, ADDITION))
print("PATCHED|%s|backup=%s" % (CONF, bak))
