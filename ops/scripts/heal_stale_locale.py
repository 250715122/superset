# -*- coding: utf-8 -*-
"""One-time migration for sessions that were stamped with the old default locale.

FAB's BabelManager.get_locale() persists BABEL_DEFAULT_LOCALE into the session:

    locale = session.get("locale")
    if locale:
        return locale
    session["locale"] = self.babel_default_locale
    return session["locale"]

So every session created while the default was 'en' carries locale='en', and the
session wins over the config — those users keep seeing English forever. Prod uses
cookie-based sessions, so they can't be cleared server-side.

This patch adds a before_request hook that stamps a policy version on the session
and, when the stamp is missing/outdated, resets the locale to the current default
once. A language the user picks afterwards is preserved, because by then the
session already carries the current stamp.

Idempotent. Usage: python heal_stale_locale.py [/path/to/superset_config.py]
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

MARKER = "_locale_policy"

ADDITION = '''
# FAB 的 get_locale() 会把 BABEL_DEFAULT_LOCALE 落盘进 session，因此在改默认
# 语言之前建立的会话里烙着旧的 'en'，而 session 优先级高于配置，用户会一直看到
# 英文。这里做一次性迁移：会话上的版本标记不是当前值时，把 locale 重置为当前
# 默认语言，然后打上标记。用户之后自己选的语言会保留——那时会话已带当前标记。
LOCALE_POLICY = "zh-default-20260728"

@app.before_request
def _heal_stale_session_locale():  # pylint: disable=unused-variable
    from flask import session
    try:
        if session.get("_locale_policy") == LOCALE_POLICY:
            return
        # 只处理已有 locale 的旧会话，避免给全新访客白建会话
        if session.get("locale"):
            session["locale"] = app.config["BABEL_DEFAULT_LOCALE"]
            session["_locale_policy"] = LOCALE_POLICY
    except Exception:  # noqa: BLE001  # 语言偏好绝不能让请求失败
        pass
'''

with open(CONF, encoding="utf-8") as f:
    src = f.read()

if MARKER in src:
    print("NOOP|locale healing hook already present in %s" % CONF)
    sys.exit(0)

# Insert inside the app mutator, right after the jinja ChoiceLoader block. Dev
# declares it as `def FLASK_APP_MUTATOR(app)`, prod as a class with __call__, so
# the indentation is taken from the closing `])` rather than hard-coded.
anchors = list(re.finditer(
    r"^[ \t]+app\.jinja_loader,\n(?P<ind>[ \t]+)\]\)\n", src, re.M))
if len(anchors) != 1:
    print("ABORT|anchor found %d times, expected 1" % len(anchors))
    sys.exit(1)

ind = anchors[0].group("ind")
block = "".join((ind + line if line.strip() else line) + "\n"
                for line in ADDITION.strip("\n").split("\n"))
pos = anchors[0].end()

bak = "%s.bak.%s" % (CONF, time.strftime("%Y%m%d%H%M%S"))
shutil.copy2(CONF, bak)
with open(CONF, "w", encoding="utf-8") as f:
    f.write(src[:pos] + "\n" + block + src[pos:])
print("PATCHED|%s|indent=%d|backup=%s" % (CONF, len(ind), bak))
