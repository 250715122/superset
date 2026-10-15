# -*- coding: utf-8 -*-
"""Create or drop a short-lived admin used only by the HTTP verification run.

Usage: _tmp_admin.py add <password> | _tmp_admin.py drop
"""
import os
import sys

os.environ.setdefault("SUPERSET_CONFIG_PATH", "/opt/superset/superset_config.py")
from superset.app import create_app  # noqa: E402

NAME = "tabverify_admin"

app = create_app()
with app.app_context():
    from superset import db, security_manager

    user = security_manager.find_user(username=NAME)
    if sys.argv[1] == "drop":
        if user:
            db.session.delete(user)
            db.session.commit()
        print("dropped %s" % NAME)
    else:
        password = sys.argv[2]
        if user:
            security_manager.reset_password(user.id, password)
        else:
            security_manager.add_user(
                NAME, "Tab", "Verify", "tabverify@example.com",
                security_manager.find_role("Admin"), password=password)
        db.session.commit()
        print("ready %s" % NAME)
