# -*- coding: utf-8 -*-
"""Unify percent display on SOC/SOH big-number cards of PB dashboard.

AVG(battery_soc|soh) is on a 0-100 scale; divide by 100 and use d3 percent
format so the card shows e.g. 87.3% like SOH覆盖率 does. Also drop the now
redundant "(%)" from titles. Dev & prod compatible, idempotent.
"""
import json
import os

CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from superset.app import create_app  # noqa: E402

# old_name -> (new_name, new_expr, new_fmt, new_desc)
CHANGES = {
    "平均SOC(%)": (
        "平均SOC",
        "AVG(battery_soc)/100.0",
        ".1%",
        "口径：AVG(battery_soc)，全部设备最新快照的剩余电量平均值，显示为百分比。",
    ),
    "平均SOH(%)": (
        "平均SOH",
        "AVG(battery_soh)/100.0",
        ".2%",
        "口径：AVG(battery_soh)，设备最新快照的健康度平均值，显示为百分比。仅统计上报了SOH的设备（未上报的不计入分母）。",
    ),
    "平均SOH": (
        "平均SOH",
        "AVG(battery_soh)/100.0",
        ".2%",
        "口径：AVG(battery_soh)，设备最新快照的健康度平均值，显示为百分比。仅统计上报了SOH的设备（未上报的不计入分母）。",
    ),
}

app = create_app()
with app.app_context():
    from superset import db
    from superset.models.dashboard import Dashboard

    d = db.session.query(Dashboard).filter_by(slug="pb-device-analysis").first()
    changed = 0
    for s in d.slices:
        if s.viz_type != "big_number_total" or s.slice_name not in CHANGES:
            continue
        new_name, expr, fmt, desc = CHANGES[s.slice_name]
        p = json.loads(s.params or "{}")
        m = p.get("metric")
        if isinstance(m, dict) and m.get("sqlExpression") == expr \
                and p.get("y_axis_format") == fmt:
            print("SKIP|%s|%s" % (s.id, s.slice_name.encode("unicode_escape").decode()))
            continue
        if isinstance(m, dict):
            m["sqlExpression"] = expr
        p["y_axis_format"] = fmt
        s.params = json.dumps(p, ensure_ascii=False)
        s.slice_name = new_name
        s.description = desc
        changed += 1
        print("FIX|%s|%s|fmt=%s" % (s.id, expr, fmt))
    db.session.commit()
    print("PCT_UNIFY_DONE|changed=%d" % changed)
