# -*- coding: utf-8 -*-
"""Prove the restriction over real HTTP, as the restricted user.

Logs in through the API as both a viewer and an admin and compares what each
is served for the same dashboard: the layout, the chart list, the tab list,
and finally a chart data request for a chart that sits behind the restricted
tab, which must come back 4xx for the viewer.
"""
import sys

import requests

BASE = "http://127.0.0.1:8088"
DASHBOARD = 9
VIEWER = ("tabtest_probe", sys.argv[1])
ADMIN = ("tabaccess_verify", sys.argv[2])
HIDDEN_TAB = "TAB-7ucgZqpsDyr52wjYJltcy"

failures = []


def check(label, ok, detail=""):
    print("   %-4s %s%s" % ("OK" if ok else "FAIL", label,
                            ("  <- %s" % detail) if detail else ""))
    if not ok:
        failures.append(label)


def login(username, password):
    r = requests.post(
        "%s/api/v1/security/login" % BASE,
        json={"username": username, "password": password,
              "provider": "db", "refresh": True},
        timeout=30,
    )
    r.raise_for_status()
    return {"Authorization": "Bearer %s" % r.json()["access_token"]}


def get(path, headers):
    r = requests.get("%s%s" % (BASE, path), headers=headers, timeout=30)
    if r.status_code != 200:
        raise SystemExit(
            "GET %s -> %s %s" % (path, r.status_code, r.text[:300])
        )
    return r.json()["result"]


def look(headers):
    d = get("/api/v1/dashboard/%s" % DASHBOARD, headers)
    position = __import__("json").loads(d.get("position_json") or "{}")
    tabs = {k: (v.get("meta") or {}).get("text")
            for k, v in position.items()
            if isinstance(v, dict) and v.get("type") == "TAB"}
    charts = get("/api/v1/dashboard/%s/charts" % DASHBOARD, headers)
    tabs_api = get("/api/v1/dashboard/%s/tabs" % DASHBOARD, headers)
    return tabs, [c.get("slice_name") for c in charts], tabs_api


print("=== as admin ===")
admin_h = login(*ADMIN)
a_tabs, a_charts, a_tabs_api = look(admin_h)
print("   tabs served: %s" % list(a_tabs.values()))
print("   charts served: %s" % len(a_charts))
check("admin sees the restricted tab", HIDDEN_TAB in a_tabs)

print("\n=== as the restricted viewer ===")
view_h = login(*VIEWER)
v_tabs, v_charts, v_tabs_api = look(view_h)
print("   tabs served: %s" % list(v_tabs.values()))
print("   charts served: %s" % len(v_charts))
check("restricted tab absent from the layout", HIDDEN_TAB not in v_tabs)
check("viewer gets fewer tabs than admin", len(v_tabs) < len(a_tabs),
      "%s vs %s" % (len(v_tabs), len(a_tabs)))
check("viewer gets fewer charts than admin", len(v_charts) < len(a_charts),
      "%s vs %s" % (len(v_charts), len(a_charts)))
check("restricted tab absent from /tabs",
      HIDDEN_TAB not in (v_tabs_api.get("all_tabs") or {}),
      str(list((v_tabs_api.get("all_tabs") or {}).values())))

print("\n=== the data itself ===")
# a chart that lives only under the restricted tab
hidden_chart = 171
for label, headers, expect_ok in (("admin", admin_h, True),
                                  ("viewer", view_h, False)):
    r = requests.post(
        "%s/api/v1/chart/data" % BASE,
        headers=headers,
        json={
            "datasource": {"id": 42, "type": "table"},
            "queries": [{"columns": [], "metrics": [], "row_limit": 1}],
            "form_data": {"slice_id": hidden_chart, "dashboardId": DASHBOARD},
            "result_format": "json",
            "result_type": "results",
        },
        timeout=60,
    )
    denied = r.status_code in (401, 403)
    if expect_ok:
        check("admin not blocked on hidden chart (status %s)" % r.status_code,
              not denied)
    else:
        check("viewer BLOCKED on hidden chart (status %s)" % r.status_code,
              denied, r.text[:160])

print("\nRESULT=%s failures=%s" % ("PASS" if not failures else "FAIL", failures))
print("DONE")
