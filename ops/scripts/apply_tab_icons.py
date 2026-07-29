# -*- coding: utf-8 -*-
"""Prefix dashboard TAB titles with icons. Dev & prod compatible, idempotent."""
import json
import os

CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from superset.app import create_app  # noqa: E402

ICONS = {
    # 卡车电池设备分析
    "运营总览": "📊 运营总览",
    "设备分布": "🗺️ 设备分布",
    "电池健康": "🔋 电池健康",
    "充放电分析": "⚡ 充放电分析",
    "数据详情": "📋 数据详情",
    # 全球AI客服·运营分析
    "管理摘要": "📌 管理摘要",
    "经营对比": "📈 经营对比",
    "Chat在线对话": "💬 Chat在线对话",
    "Email与VoC": "📧 Email与VoC",
    "转人工根因": "🙋 转人工根因",
    "体验与回访": "🔄 体验与回访",
    "数据明细": "📋 数据明细",
    "客服周报": "📅 客服周报",
}

app = create_app()
with app.app_context():
    from superset import db
    from superset.models.dashboard import Dashboard

    def find_dash(slug, kw):
        d = db.session.query(Dashboard).filter_by(slug=slug).first()
        if d:
            return d
        for dd in db.session.query(Dashboard).all():
            if all(k in (dd.dashboard_title or "") for k in kw):
                return dd
        return None

    for slug, kw in [("pb-device-analysis", ["卡车电池"]),
                     ("cs-ops-analysis", ["AI", "运营"])]:
        d = find_dash(slug, kw)
        if not d:
            print("DASH|%s|NOT FOUND" % slug)
            continue
        pos = json.loads(d.position_json or "{}")
        changed = 0
        for k, v in pos.items():
            if not (isinstance(v, dict) and v.get("type") == "TAB"):
                continue
            text = v.get("meta", {}).get("text", "")
            new = ICONS.get(text)
            if new:
                v["meta"]["text"] = new
                changed += 1
            elif any(text == t for t in ICONS.values()):
                pass  # already iconified
        if changed:
            d.position_json = json.dumps(pos, ensure_ascii=False)
        db.session.commit()
        print("TABS|dash_id=%s|changed=%d" % (d.id, changed))
    print("TAB_ICONS_DONE")
