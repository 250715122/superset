# -*- coding: utf-8 -*-
"""End-to-end post-fix check: a non-admin viewer must now reach /meta-search/.

Uses Flask's test_client against the live app (real routing, real RBAC), with
the session's _user_id spoofed to a real non-admin viewer. Confirms:
  1. /meta-search/ now returns 200 (not 403)
  2. /meta-search/api/stats and /api/search answer
"""
import os
import sys

os.environ.setdefault("SUPERSET_CONFIG_PATH",
                      "/mnt/data/superset/superset_config.py")

from superset.app import create_app  # noqa: E402
app = create_app()

VIEWER = sys.argv[1] if len(sys.argv) > 1 else "郭特"

with app.app_context():
    from superset import security_manager
    user = security_manager.find_user(username=VIEWER)
    if not user:
        print("NO_SUCH_USER|%s" % VIEWER)
        sys.exit(2)
    uid = user.id
    roles = sorted(r.name for r in user.roles)
    print("VIEWER=%s id=%s roles=%s" % (VIEWER, uid, roles))

client = app.test_client()
with client.session_transaction() as sess:
    sess["_user_id"] = str(uid)

for path in ("/meta-search/", "/meta-search/api/stats",
             "/meta-search/api/search?q=test"):
    resp = client.get(path)
    print("GET %-40s -> HTTP %s (%d bytes)"
          % (path, resp.status_code, len(resp.data)))

# also exercise a real search through the API
resp = client.get("/meta-search/api/search?q=%s"
                  % "客服首次响应时长")
print("SEARCH -> HTTP %s" % resp.status_code)
body = resp.get_json() if resp.status_code == 200 else {}
rows = body.get("results") or []
print("  rows=%d first=%s" % (len(rows),
      ((rows[0].get("db_name") + "." + rows[0].get("table_name"))
       if rows else "none")))
