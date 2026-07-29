# -*- coding: utf-8 -*-
"""Make Chinese the default display language.

get_locale() (FAB's BabelManager) returns session["locale"] when the user has
picked one, otherwise BABEL_DEFAULT_LOCALE. The SPA bootstrap derives its
locale from get_locale(), so flipping this one value switches the default for
everyone who hasn't chosen a language, while leaving the picker working.

Idempotent. Usage: python set_default_locale_zh.py [/path/to/superset_config.py]
"""
import os
import re
import shutil
import sys
import time

CONF = sys.argv[1] if len(sys.argv) > 1 else (
    "/opt/superset/superset_config.py"
    if os.path.exists("/opt/superset/superset_config.py")
    else "/mnt/data/superset/superset_config.py")

TARGET = "BABEL_DEFAULT_LOCALE = 'zh'  # 默认显示语言：简体中文"

with open(CONF, encoding="utf-8") as f:
    src = f.read()

pat = re.compile(r"^BABEL_DEFAULT_LOCALE\s*=.*$", re.M)
found = pat.findall(src)
print("CURRENT|%s" % (found or "ABSENT"))

if found and found[0].strip() == TARGET:
    print("NOOP|already zh")
    sys.exit(0)

bak = "%s.bak.%s" % (CONF, time.strftime("%Y%m%d%H%M%S"))
shutil.copy2(CONF, bak)

if found:
    if len(found) != 1:
        print("ABORT|%d BABEL_DEFAULT_LOCALE lines, expected 1" % len(found))
        sys.exit(1)
    out = pat.sub(TARGET, src)
else:
    out = src.rstrip("\n") + "\n\n" + TARGET + "\n"

with open(CONF, "w", encoding="utf-8") as f:
    f.write(out)
print("PATCHED|%s|backup=%s" % (CONF, bak))
print("NEW|%s" % pat.findall(out))
