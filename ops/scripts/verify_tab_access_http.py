# -*- coding: utf-8 -*-
"""Prove the tab restriction over real HTTP, as a real logged-in user.

Logs in as an admin and as a restricted viewer and compares what each is
served for the same dashboard - the layout, the chart list, the tab list - and
then asks for the data of a chart that sits behind a restricted tab, which the
viewer must not get. Running it over HTTP rather than in-process is the point:
it exercises the deployed service, its session handling and its caches.

The dashboard tells the script what to probe: the restricted tabs come from
``tab_roles`` in its metadata as the admin sees it, and the chart to probe is
one that is reachable only through them. Nothing is hard-coded per dashboard.

Usage:
  verify_tab_access_http.py --dashboard 9 \
      --admin admin:<password> --viewer tabdemo:<password>
"""
import argparse
import json as json_mod
import sys

import requests


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:8088")
    p.add_argument("--dashboard", type=int, required=True)
    p.add_argument("--admin", required=True, metavar="USER:PASSWORD")
    p.add_argument("--viewer", required=True, metavar="USER:PASSWORD")
    args = p.parse_args()
    args.admin = args.admin.split(":", 1)
    args.viewer = args.viewer.split(":", 1)
    return args


ARGS = parse_args()
BASE = ARGS.base
DASHBOARD = ARGS.dashboard

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
    if r.status_code != 200:
        raise SystemExit("login as %s failed: %s %s"
                         % (username, r.status_code, r.text[:200]))
    return {"Authorization": "Bearer %s" % r.json()["access_token"]}


def get(path, headers):
    r = requests.get("%s%s" % (BASE, path), headers=headers, timeout=30)
    if r.status_code != 200:
        raise SystemExit("GET %s -> %s %s" % (path, r.status_code, r.text[:300]))
    return r.json()["result"]


def tabs_of(position):
    return {k: (v.get("meta") or {}).get("text") or k
            for k, v in position.items()
            if isinstance(v, dict) and v.get("type") == "TAB"}


def descendants(position, node_id):
    seen, stack = set(), [node_id]
    while stack:
        node = position.get(stack.pop())
        if not isinstance(node, dict):
            continue
        for child in node.get("children") or []:
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def chart_ids(position, node_ids):
    ids = set()
    for node_id in node_ids:
        node = position.get(node_id)
        if isinstance(node, dict) and node.get("type") == "CHART":
            chart_id = (node.get("meta") or {}).get("chartId")
            if isinstance(chart_id, int):
                ids.add(chart_id)
    return ids


def look(headers):
    d = get("/api/v1/dashboard/%s" % DASHBOARD, headers)
    position = json_mod.loads(d.get("position_json") or "{}")
    metadata = json_mod.loads(d.get("json_metadata") or "{}")
    charts = get("/api/v1/dashboard/%s/charts" % DASHBOARD, headers)
    tabs_api = get("/api/v1/dashboard/%s/tabs" % DASHBOARD, headers)
    return position, metadata, [c.get("slice_name") for c in charts], tabs_api


print("=== as admin ===")
admin_h = login(*ARGS.admin)
a_pos, a_meta, a_charts, a_tabs_api = look(admin_h)
a_tabs = tabs_of(a_pos)
print("   tabs served:   %s" % list(a_tabs.values()))
print("   charts served: %s" % len(a_charts))

restricted = {t: r for t, r in (a_meta.get("tab_roles") or {}).items()
              if t in a_pos}
if not restricted:
    raise SystemExit(
        "dashboard %s has no tab_roles set, so there is nothing to verify.\n"
        "Restrict a tab first (properties dialog, or setup_tab_access_demo.py)."
        % DASHBOARD)
print("   restricted tabs: %s"
      % {a_tabs.get(t, t): r for t, r in restricted.items()})

blocked_nodes = set()
for tab_id in restricted:
    blocked_nodes |= {tab_id} | descendants(a_pos, tab_id)
hidden_charts = (chart_ids(a_pos, blocked_nodes)
                 - chart_ids(a_pos, set(a_pos) - blocked_nodes))
if not hidden_charts:
    raise SystemExit("the restricted tabs hold no chart of their own, so there "
                     "is no data request to probe")
probe_chart = sorted(hidden_charts)[0]
chart_meta = get("/api/v1/chart/%s" % probe_chart, admin_h)
print("   probing chart %s (%s), reachable only behind a restricted tab"
      % (probe_chart, chart_meta.get("slice_name")))

check("admin sees every restricted tab",
      all(t in a_tabs for t in restricted))

print("\n=== as the restricted viewer ===")
view_h = login(*ARGS.viewer)
v_pos, v_meta, v_charts, v_tabs_api = look(view_h)
v_tabs = tabs_of(v_pos)
print("   tabs served:   %s" % list(v_tabs.values()))
print("   charts served: %s" % len(v_charts))

check("restricted tabs absent from the layout",
      not any(t in v_tabs for t in restricted), str(list(v_tabs.values())))
check("viewer gets fewer tabs than admin", len(v_tabs) < len(a_tabs),
      "%s vs %s" % (len(v_tabs), len(a_tabs)))
check("viewer gets fewer charts than admin", len(v_charts) < len(a_charts),
      "%s vs %s" % (len(v_charts), len(a_charts)))
check("restricted tabs absent from /tabs",
      not any(t in (v_tabs_api.get("all_tabs") or {}) for t in restricted),
      str(list((v_tabs_api.get("all_tabs") or {}).values())))
check("hidden tab's roles not disclosed to the viewer",
      not any(t in (v_meta.get("tab_roles") or {}) for t in restricted))

print("\n=== the data itself ===")
payload = {
    "datasource": {"id": chart_meta.get("datasource_id"),
                   "type": chart_meta.get("datasource_type") or "table"},
    "queries": [{"columns": [], "metrics": [], "row_limit": 1}],
    "form_data": {"slice_id": probe_chart, "dashboardId": DASHBOARD},
    "result_format": "json",
    "result_type": "results",
}
for label, headers, should_be_denied in (("admin", admin_h, False),
                                         ("viewer", view_h, True)):
    r = requests.post("%s/api/v1/chart/data" % BASE, headers=headers,
                      json=payload, timeout=60)
    denied = r.status_code in (401, 403)
    if should_be_denied:
        check("viewer BLOCKED on the hidden chart (HTTP %s)" % r.status_code,
              denied, r.text[:160])
    else:
        check("admin not blocked on it (HTTP %s)" % r.status_code, not denied)

print("\n=== export ===")
r = requests.get("%s/api/v1/dashboard/export/?q=!(%s)" % (BASE, DASHBOARD),
                 headers=view_h, timeout=60)
if r.status_code == 200:
    body = r.content.decode("utf-8", "ignore")
    leaked = [t for t in restricted if t in body]
    check("export carries no restricted tab", not leaked, str(leaked))
else:
    # Stock Superset already fails a non-owner's dashboard export, with a 500
    # rather than a clean refusal, because the chart export it delegates to
    # applies its own access filter. That happens with or without tab_roles,
    # so it is inherited, not ours - and it serves nothing either way.
    check("export served nothing to the viewer (HTTP %s)" % r.status_code,
          r.status_code >= 400)

print("\nRESULT=%s failures=%s" % ("PASS" if not failures else "FAIL", failures))
sys.exit(1 if failures else 0)
