# -*- coding: utf-8 -*-
"""Put the data-asset search page at the top of dp-sr-global's 数据资产 tab.

Touches exactly one field, ``position_json``, and within it adds two nodes and
prepends one id to one tab's children. Everything else in the dashboard -- all
other charts, json_metadata, css, filter scopes -- is left byte-identical.

Idempotent: a second run reports ALREADY_PRESENT and writes nothing.
"""
import json
import os
import sys

os.environ.setdefault("SUPERSET_CONFIG_PATH",
                      "/mnt/data/superset/superset_config.py")

from superset.app import create_app  # noqa: E402

SLUG = "dp-sr-global"
TAB_TEXT = "数据资产"
ROW_ID = "ROW-meta-search"
MD_ID = "MARKDOWN-meta-search"
# Markdown heights are in 8px units; keep the iframe just inside the component
# so the dashboard does not grow a second scrollbar around it.
HEIGHT_UNITS = 76
IFRAME_PX = 600

CODE = (
    '<iframe src="/meta-search/" title="数据资产检索" '
    'style="width:100%%;height:%dpx;border:0;display:block"></iframe>' % IFRAME_PX
)

app = create_app()
with app.app_context():
    from superset import db
    from superset.models.dashboard import Dashboard

    dash = db.session.query(Dashboard).filter_by(slug=SLUG).first()
    if dash is None:
        sys.exit("dashboard %s not found" % SLUG)

    pos = json.loads(dash.position_json or "{}")

    tab_id = next((k for k, v in pos.items()
                   if isinstance(v, dict) and v.get("type") == "TAB"
                   and (v.get("meta") or {}).get("text") == TAB_TEXT), None)
    if tab_id is None:
        sys.exit("tab %r not found in %s" % (TAB_TEXT, SLUG))

    tab = pos[tab_id]
    children = tab.get("children") or []

    if ROW_ID in children or MD_ID in pos:
        print("ALREADY_PRESENT|tab=%s|children=%s" % (tab_id, children))
        sys.exit(0)

    if not children:
        sys.exit("tab %s has no rows to copy layout parentage from" % tab_id)

    # Reuse the parentage of the row currently on top, so the new row sits in
    # exactly the same place in the tree rather than a guessed one.
    sibling = pos[children[0]]
    row_parents = list(sibling.get("parents") or [])

    pos[MD_ID] = {
        "type": "MARKDOWN",
        "id": MD_ID,
        "children": [],
        "parents": row_parents + [ROW_ID],
        "meta": {"width": 12, "height": HEIGHT_UNITS, "code": CODE},
    }
    pos[ROW_ID] = {
        "type": "ROW",
        "id": ROW_ID,
        "children": [MD_ID],
        "parents": row_parents,
        "meta": {"background": "BACKGROUND_TRANSPARENT"},
    }
    tab["children"] = [ROW_ID] + children

    dash.position_json = json.dumps(pos, ensure_ascii=False)
    db.session.commit()
    print("PATCHED|tab=%s|children=%s" % (tab_id, tab["children"]))
