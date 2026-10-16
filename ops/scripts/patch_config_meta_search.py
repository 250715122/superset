# -*- coding: utf-8 -*-
"""Register the 数据资产检索 view from superset_config.py's FLASK_APP_MUTATOR.

Idempotent: re-running makes no change.  The import is wrapped so that a
broken search page can never stop Superset from booting.

Usage: patch_config_meta_search.py <superset_config.py> [--revert]
"""
import os
import re
import shutil
import sys
from datetime import datetime

MARK = "# --- 数据资产检索 /meta-search/"

BLOCK = '''
    {mark} (meta_search.py) ---
    # 注册成 FAB 视图而非裸 Blueprint，这样会生成 MetaSearch 权限，可在角色里勾选。
    # 任何失败都只记日志：检索页坏掉不能连累 Superset 启动。
    import sys as _sys
    if {dir!r} not in _sys.path:
        _sys.path.insert(0, {dir!r})
    try:
        import meta_search as _meta_search
        _meta_search.register(app)
    except Exception:  # noqa: BLE001
        import logging as _logging
        _logging.getLogger(__name__).exception("meta_search 注册失败，检索页不可用")
'''


def main():
    path = sys.argv[1]
    revert = "--revert" in sys.argv
    src = open(path, encoding="utf-8").read()

    if revert:
        if MARK not in src:
            print("NOCHANGE|没有找到补丁块")
            return
        out = re.sub(r"\n    %s.*?_logging\.getLogger\(__name__\)\.exception\("
                     r"\"meta_search 注册失败，检索页不可用\"\)\n" % re.escape(MARK),
                     "\n", src, flags=re.S)
    else:
        if MARK in src:
            print("NOCHANGE|补丁已存在")
            return
        marker = ('        except Exception:  # noqa: BLE001  '
                  '# 语言偏好绝不能让请求失败\n            pass\n')
        if marker not in src:
            sys.exit("ERROR|没找到 FLASK_APP_MUTATOR 的插入锚点，请人工检查")
        block = BLOCK.format(mark=MARK, dir=os.path.dirname(os.path.abspath(path)))
        out = src.replace(marker, marker + block, 1)

    backup = "%s.bak.metasearch.%s" % (path, datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(path, backup)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(out)
    print("OK|%s|backup=%s|%+d 字节"
          % ("revert" if revert else "patch", backup, len(out) - len(src)))


main()
