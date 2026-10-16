# -*- coding: utf-8 -*-
"""Register meta_search inside the prod CustomFlaskAppMutator.

Prod's FLASK_APP_MUTATOR is a class instance, not a bare function as on dev,
so the hook goes inside ``__call__`` at class-method indentation. Idempotent:
running it twice leaves the file untouched the second time. Writes a
timestamped backup before changing anything.
"""
import datetime
import os
import shutil
import sys

CONF = "/mnt/data/superset/superset_config.py"
ROOT = "/mnt/data/superset"

ANCHOR = """        app.jinja_loader = jinja2.ChoiceLoader([
            jinja2.FileSystemLoader("/mnt/data/superset/custom_templates"),
            app.jinja_loader,
        ])
"""

BLOCK = """
        # --- 数据资产检索 /meta-search/ (meta_search.py) ---
        # 注册成 FAB 视图而非裸 Blueprint，这样会生成 MetaSearch 权限，可在角色里勾选。
        # 任何失败都只记日志：检索页坏掉不能连累 Superset 启动。
        import sys as _sys
        if '%s' not in _sys.path:
            _sys.path.insert(0, '%s')
        try:
            import meta_search as _meta_search
            _meta_search.register(app)
        except Exception:  # noqa: BLE001
            import logging as _logging
            _logging.getLogger(__name__).exception("meta_search 注册失败，检索页不可用")
""" % (ROOT, ROOT)

with open(CONF, "r", encoding="utf-8") as handle:
    text = handle.read()

if "meta_search" in text:
    print("ALREADY_PATCHED")
    sys.exit(0)

if ANCHOR not in text:
    sys.exit("ANCHOR_NOT_FOUND: refusing to guess where to insert")

stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
backup = "%s.bak_meta_search_%s" % (CONF, stamp)
shutil.copy2(CONF, backup)

patched = text.replace(ANCHOR, ANCHOR + BLOCK, 1)
with open(CONF, "w", encoding="utf-8") as handle:
    handle.write(patched)

os.system("%s/venv/bin/python -m py_compile %s" % (ROOT, CONF))
print("PATCHED|backup=%s|bytes %d -> %d" % (backup, len(text), len(patched)))
