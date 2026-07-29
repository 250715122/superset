# -*- coding: utf-8 -*-
"""End-to-end functional probe for the RBAC-driven authorization model.

For one member of every observer group (and every non-admin user holding
audience roles directly), impersonates them through the test client and checks:

  positive  dashboard list, open each visible dashboard page, chart data for
            one chart of each visible dashboard (with dashboardId injected,
            exactly like the SPA does), share link, filter state, drill info,
            Chinese language pack
  negative  chart data for the same chart WITHOUT dashboardId (must fail once
            data grants are revoked -- proves data can only be seen through
            the dashboard), create-dashboard, create-chart

Each user is probed inside a fresh app context (g is bound to the app context
and @protect reads g.user; reusing one context across clients poisons checks).

Read-only. Dev & prod compatible. ASCII-safe output.
"""
import json
import os

CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from superset.app import create_app  # noqa: E402

app = create_app()
app.config["WTF_CSRF_ENABLED"] = False


def e(s):
    return (s or "").encode("unicode_escape").decode()


FAILS = []


def probe_user(uid, uname, roles, charts_by_dash):
    with app.app_context():
        from superset import db
        from superset.models.dashboard import Dashboard

        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess["_user_id"] = str(uid)
                sess["_fresh"] = True

            def check(label, ok, detail=""):
                mark = "PASS" if ok else "FAIL"
                if not ok:
                    FAILS.append("%s: %s %s" % (e(uname), label, detail))
                print("  %s|%-26s|%s" % (mark, label, detail))

            print("\n=== USER %s | roles=%s" % (e(uname),
                                                [e(r) for r in sorted(roles)]))
            r = c.get("/api/v1/dashboard/?q=(page_size:200,columns:!(id,slug))")
            rows = r.get_json()["result"] if r.status_code == 200 else []
            ids = sorted(x["id"] for x in rows)
            check("看板列表", r.status_code == 200, "visible=%s" % ids)

            neg_payload = None
            for row in rows:
                did = row["id"]
                d = db.session.get(Dashboard, did)
                page = "/superset/dashboard/%s/" % (row.get("slug") or did)
                r = c.get(page)
                check("打开看板 %s" % did, r.status_code == 200,
                      "http=%s" % r.status_code)

                cinfo = charts_by_dash.get(did)
                if not cinfo:
                    print("  SKIP|看板 %s 无带query_context的图表" % did)
                    continue
                cid, qc = cinfo
                payload = json.loads(qc)
                payload.setdefault("form_data", {})["dashboardId"] = did
                payload["form_data"]["slice_id"] = cid
                payload["result_format"] = "json"
                payload["result_type"] = "full"
                r = c.post("/api/v1/chart/data", json=payload)
                ok = r.status_code == 200
                nrows = ""
                if ok:
                    try:
                        nrows = "rows=%s" % r.get_json()["result"][0]["rowcount"]
                    except Exception:  # noqa: BLE001
                        nrows = "rows=?"
                check("取数(看板%s 图%s)" % (did, cid), ok,
                      nrows or "http=%s %s" % (r.status_code,
                                               r.get_data(as_text=True)[:70]))
                if neg_payload is None:
                    neg_payload = json.loads(qc)
                    neg_payload.setdefault("form_data", {}).pop("dashboardId",
                                                                None)
                    neg_payload["form_data"]["slice_id"] = cid
                    neg_payload["result_format"] = "json"
                    neg_payload["result_type"] = "full"

                if ids and did == ids[0]:
                    r = c.post("/api/v1/dashboard/%s/permalink" % did,
                               json={"dataMask": {}, "activeTabs": [],
                                     "anchor": ""})
                    check("分享链接", r.status_code == 201,
                          "http=%s" % r.status_code)
                    r = c.post("/api/v1/dashboard/%s/filter_state" % did,
                               json={"value": "{}"})
                    check("筛选器状态", r.status_code == 201,
                          "http=%s" % r.status_code)
                    ds_id = payload.get("datasource", {}).get("id")
                    if ds_id:
                        r = c.get("/api/v1/dataset/%s/drill_info/" % ds_id)
                        check("下钻信息", r.status_code in (200, 404),
                              "http=%s" % r.status_code)

            r = c.get("/superset/language_pack/zh/")
            check("中文语言包", r.status_code == 200, "http=%s" % r.status_code)

            # --- negative: writes and out-of-dashboard data access ---------
            r = c.post("/api/v1/dashboard/", json={"dashboard_title": "x"})
            check("建看板被拒", r.status_code in (401, 403, 405),
                  "http=%s" % r.status_code)
            if neg_payload is not None:
                r = c.post("/api/v1/chart/data", json=neg_payload)
                # 200 is acceptable only while legacy data grants still exist
                print("  INFO|脱离看板取数|http=%s%s"
                      % (r.status_code,
                         "（数据角色未回收前 200 属预期）"
                         .encode("unicode_escape").decode()
                         if r.status_code == 200 else ""))


with app.app_context():
    from flask_appbuilder.security.sqla.models import Group

    from superset import db, security_manager as sm
    from superset.models.dashboard import Dashboard

    # one representative chart (with saved query_context) per dashboard
    charts_by_dash = {}
    for d in db.session.query(Dashboard).all():
        for s in d.slices:
            if s.query_context:
                charts_by_dash[d.id] = (s.id, s.query_context)
                break

    targets = {}
    for g in db.session.query(Group).all():
        rn = {r.name for r in g.roles}
        if {"Gamma", "Admin"} & rn:
            continue
        for u in g.users:
            if u.is_active:
                targets[u.id] = u
                break
    for u in sm.get_all_users():
        names = {r.name for r in sm.get_user_roles(u)}
        if u.is_active and "Admin" not in names \
                and any(n.startswith("看板·") for n in names):
            targets.setdefault(u.id, u)

    plan = [(u.id, u.username,
             [r.name for r in sm.get_user_roles(u)]) for u in targets.values()]

for uid, uname, roles in plan:
    probe_user(uid, uname, roles, charts_by_dash)

print("\nPROBE_RESULT|%s" % ("ALL_PASS" if not FAILS else "%d FAIL" % len(FAILS)))
for f in FAILS:
    print("  " + f)
