# -*- coding: utf-8 -*-
"""Give 数据中台速览观众 access to the live dashboard, and de-confuse the names.

Dashboards 37 and 38 both read as「数据中台速览」and their audience roles差两个字,
so the group was wired to 37 (an unpublished first draft) while the dashboard
everyone actually uses is 38. Members got a role that opens nothing they can
find, and 38's role ended up with zero holders.

Two changes, both idempotent:
  1. add 看板·数据中台全局速览 (dashboard 38's gate) to the group, keeping the
     existing roles so nothing currently visible is lost;
  2. rename dashboard 37 and its role so the two can't be mixed up again.

Run with --dry-run first; it prints the same plan without committing.
Usage: fix_dp_sr_audience.py [--dry-run]
"""
import json
import os
import sys
import time

CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

DRY = "--dry-run" in sys.argv

GROUP = "数据中台速览观众"
ROLE_38 = "看板·数据中台全局速览"      # gates dashboard 38 (dp-sr-global)
ROLE_37_OLD = "看板·数据中台速览"       # gates dashboard 37 (dp-sr-overview)
ROLE_37_NEW = "看板·StarRocks Cockpit旧版"
DASH_37_NEW_TITLE = "StarRocks Cockpit（旧版·草稿）"

from flask_appbuilder.security.sqla.models import Group, Role  # noqa: E402
from superset.app import create_app  # noqa: E402

app = create_app()
with app.app_context():
    from superset import db
    from superset.models.dashboard import Dashboard

    group = db.session.query(Group).filter_by(name=GROUP).one()
    role38 = db.session.query(Role).filter_by(name=ROLE_38).one()
    dash37 = db.session.get(Dashboard, 37)
    dash38 = db.session.get(Dashboard, 38)
    role37 = db.session.query(Role).filter_by(name=ROLE_37_OLD).first()

    before = {
        "group": {"name": group.name,
                  "roles": sorted(r.name for r in group.roles),
                  "users": sorted(u.username for u in group.users)},
        "dash37": {"title": dash37.dashboard_title,
                   "published": dash37.published,
                   "roles": sorted(r.name for r in dash37.roles)},
        "dash38": {"title": dash38.dashboard_title,
                   "published": dash38.published,
                   "roles": sorted(r.name for r in dash38.roles)},
        "role37_id": role37.id if role37 else None,
        "role38_id": role38.id,
    }
    print("BEFORE|%s" % json.dumps(before, ensure_ascii=True, sort_keys=True))

    if not DRY:
        path = os.path.join(os.path.dirname(CONF), "backups",
                            "dp_sr_audience_%s.json"
                            % time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(before, fh, ensure_ascii=True, indent=1, sort_keys=True)
        print("BACKUP|%s" % path)

    # 1. group gains dashboard 38's gate role
    if role38 in group.roles:
        print("STEP1|已有，跳过")
    else:
        print("STEP1|给组加角色 %s" % ROLE_38)
        if not DRY:
            group.roles.append(role38)

    # 2. rename the look-alike pair
    if role37 is None:
        print("STEP2|角色 %s 不存在（可能已改名），跳过" % ROLE_37_OLD)
    else:
        print("STEP2|角色改名 %s -> %s" % (ROLE_37_OLD, ROLE_37_NEW))
        if not DRY:
            role37.name = ROLE_37_NEW

    if dash37.dashboard_title == DASH_37_NEW_TITLE:
        print("STEP3|看板 37 标题已是目标值，跳过")
    else:
        print("STEP3|看板 37 改名 %s -> %s"
              % (dash37.dashboard_title, DASH_37_NEW_TITLE))
        if not DRY:
            dash37.dashboard_title = DASH_37_NEW_TITLE

    if DRY:
        db.session.rollback()
        print("DRY_RUN|未提交")
    else:
        db.session.commit()
        print("COMMITTED")

    db.session.expire_all()
    group = db.session.query(Group).filter_by(name=GROUP).one()
    dash37 = db.session.get(Dashboard, 37)
    dash38 = db.session.get(Dashboard, 38)
    after = {
        "group_roles": sorted(r.name for r in group.roles),
        "group_users": sorted(u.username for u in group.users),
        "dash37": {"title": dash37.dashboard_title,
                   "roles": sorted(r.name for r in dash37.roles)},
        "dash38": {"title": dash38.dashboard_title,
                   "roles": sorted(r.name for r in dash38.roles)},
    }
    print("AFTER|%s" % json.dumps(after, ensure_ascii=True, sort_keys=True))

    # the only check that matters: can 郭特 clear dashboard 38's gate now
    from flask_appbuilder.security.sqla.models import User

    from superset import security_manager
    user = db.session.query(User).filter_by(username="郭特").first()
    eff = {r.name for r in security_manager.get_user_roles(user)}
    for dash in (dash37, dash38):
        gate = {r.name for r in dash.roles}
        print("CHECK|看板 %s|要求=%s|命中=%s|结论=%s"
              % (dash.id,
                 json.dumps(sorted(gate), ensure_ascii=True),
                 json.dumps(sorted(gate & eff), ensure_ascii=True),
                 "可访问" if gate & eff else "仍不可访问"))
