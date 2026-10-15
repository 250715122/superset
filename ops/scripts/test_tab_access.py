# -*- coding: utf-8 -*-
"""End-to-end check of per-tab dashboard access control.

Restricts one tab of a dashboard to a role, then asserts - as a user who holds
only the dashboard's *viewer* role - that the tab, its charts and its datasets
are gone from every read path, and that the security manager refuses to serve
the data of a chart hidden behind it. Restores everything it touched.

The probe user deliberately gets no other role: the dashboard grant in
raise_for_access must then be the only possible route to the data, which is
exactly the path this feature narrows.

Note this deployment's CustomSsoSecurityManager treats a holder of an
"编辑·<dashboard>" role as an owner, and owners see every tab by design - so
the probe user must not hold one.

Usage: _test_tab_access.py <dashboard id> [tab id]
"""
import os
import secrets
import sys
from types import SimpleNamespace

os.environ.setdefault("SUPERSET_CONFIG_PATH", "/opt/superset/superset_config.py")
from superset.app import create_app  # noqa: E402

DASHBOARD_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 9
RESTRICT_TAB = sys.argv[2] if len(sys.argv) > 2 else None

ROLE_NAME = "TABTEST-仅限运维"
USER_NAME = "tabtest_probe"

failures = []


def check(label, ok, detail=""):
    print("   %-4s %s%s" % ("OK" if ok else "FAIL", label,
                            ("  <- %s" % detail) if detail else ""))
    if not ok:
        failures.append(label)


def can_read(sm, slc, dashboard):
    """Would the security manager serve this chart's data on this dashboard?"""
    from superset.exceptions import SupersetSecurityException
    try:
        sm.raise_for_access(
            query_context=SimpleNamespace(
                datasource=slc.datasource,
                form_data={"slice_id": slc.id, "dashboardId": dashboard.id},
            )
        )
        return True
    except SupersetSecurityException:
        return False


app = create_app()
with app.app_context():
    from superset import db, security_manager
    from superset.daos.dashboard import DashboardDAO
    from superset.dashboards import tab_access
    from superset.models.dashboard import Dashboard
    from superset.utils import json
    from superset.utils.core import override_user

    dash = db.session.get(Dashboard, DASHBOARD_ID)
    position = json.loads(dash.position_json or "{}")
    tabs = {k: (v.get("meta") or {}).get("text")
            for k, v in position.items()
            if isinstance(v, dict) and v.get("type") == "TAB"}
    tab_id = RESTRICT_TAB or sorted(tabs)[-1]
    print("dashboard=%s %s" % (dash.id, dash.dashboard_title))
    print("restricting tab=%s (%s)" % (tab_id, tabs.get(tab_id)))

    original_metadata = dash.json_metadata

    role = security_manager.find_role(ROLE_NAME) or security_manager.add_role(ROLE_NAME)
    user = security_manager.find_user(username=USER_NAME)
    if not user:
        # the probe is exercised through override_user, never a login, so give
        # it a password nobody knows rather than a fixed one
        user = security_manager.add_user(
            USER_NAME, "Tab", "Probe", "tabtest@example.com",
            security_manager.find_role("Gamma"),
            password=secrets.token_urlsafe(32),
        )
    viewer_roles = [
        r for r in (dash.roles or [])
        if not r.name.startswith(security_manager.EDITOR_ROLE_PREFIX)
    ]
    user.roles = viewer_roles
    db.session.commit()
    print("probe user roles=%s" % [r.name for r in user.roles])

    # The write path: the properties modal puts tab_roles inside json_metadata,
    # and that payload is validated against a schema which rejects unknown
    # fields. Saving used to fail with a 400 that the UI swallowed, so assert
    # the field survives validation and a real update command.
    print("\n--- write path ---")
    from marshmallow import ValidationError

    from superset.commands.dashboard.update import UpdateDashboardCommand
    from superset.dashboards.schemas import DashboardJSONMetadataSchema

    probe_metadata = {tab_access.TAB_ROLES_KEY: {tab_id: [ROLE_NAME]}}
    try:
        DashboardJSONMetadataSchema().load(probe_metadata)
        check("json_metadata schema accepts tab_roles", True)
    except ValidationError as ex:
        check("json_metadata schema accepts tab_roles", False, str(ex.messages))

    metadata = json.loads(original_metadata or "{}")
    metadata[tab_access.TAB_ROLES_KEY] = {tab_id: [ROLE_NAME]}

    admin_user = security_manager.find_user(username="admin")
    with override_user(admin_user):
        try:
            UpdateDashboardCommand(
                DASHBOARD_ID, {"json_metadata": json.dumps(metadata)}
            ).run()
            db.session.commit()
            saved = json.loads(
                db.session.get(Dashboard, DASHBOARD_ID).json_metadata or "{}"
            )
            check("tab_roles survives a dashboard update",
                  saved.get(tab_access.TAB_ROLES_KEY) == {tab_id: [ROLE_NAME]},
                  str(saved.get(tab_access.TAB_ROLES_KEY)))
        except Exception as ex:  # noqa: BLE001
            check("tab_roles survives a dashboard update", False,
                  "%s: %s" % (type(ex).__name__, ex))

    dash = db.session.get(Dashboard, DASHBOARD_ID)

    try:
        hidden_charts = set()
        stack = [tab_id]
        while stack:
            node = position.get(stack.pop())
            if not isinstance(node, dict):
                continue
            if node.get("type") == "CHART":
                hidden_charts.add((node.get("meta") or {}).get("chartId"))
            stack.extend(node.get("children") or [])
        hidden_charts.discard(None)
        print("charts under that tab: %s" % sorted(hidden_charts))

        with override_user(user):
            print("\n--- as a viewer without the restricted role ---")
            check("not treated as owner/editor",
                  not tab_access.has_unrestricted_access(dash))

            pos = tab_access.filtered_position(dash)
            check("tab removed from layout", tab_id not in pos)
            check("tab's charts removed from layout",
                  not (hidden_charts & tab_access._chart_ids(pos)))
            check("other tabs survive",
                  len([k for k, v in pos.items()
                       if isinstance(v, dict) and v.get("type") == "TAB"])
                  == len(tabs) - 1,
                  "%s of %s tabs left" % (
                      len([k for k, v in pos.items()
                           if isinstance(v, dict) and v.get("type") == "TAB"]),
                      len(tabs)))

            visible = tab_access.visible_slice_ids(dash)
            check("hidden charts not in visible slice ids",
                  not (hidden_charts & visible))

            charts = DashboardDAO.get_charts_for_dashboard(DASHBOARD_ID)
            check("/charts excludes hidden charts",
                  not (hidden_charts & {c.id for c in charts}),
                  "returned %s of %s" % (len(charts), len(dash.slices)))

            tabs_payload = DashboardDAO.get_tabs_for_dashboard(DASHBOARD_ID)
            check("/tabs excludes hidden tab",
                  tab_id not in (tabs_payload.get("all_tabs") or {}),
                  "all_tabs=%s" % list((tabs_payload.get("all_tabs") or {}).values()))

            datasets = DashboardDAO.get_datasets_for_dashboard(DASHBOARD_ID)
            visible_ds = {d.get("id") for d in datasets}
            hidden_only_ds = set()
            for cid in hidden_charts:
                slc = next((s for s in dash.slices if s.id == cid), None)
                if slc and not any(
                    s.datasource_id == slc.datasource_id and s.id in visible
                    for s in dash.slices
                ):
                    hidden_only_ds.add(slc.datasource_id)
            check("/datasets drops datasets used only by hidden charts",
                  not (hidden_only_ds & visible_ds),
                  "hidden-only=%s served=%s"
                  % (sorted(hidden_only_ds), sorted(x for x in visible_ds if x)))

            print("\n--- raise_for_access, the check that guards the data ---")
            for cid in sorted(hidden_charts)[:3]:
                slc = next((s for s in dash.slices if s.id == cid), None)
                if slc and slc.datasource:
                    check("hidden chart %s DENIED" % cid,
                          not can_read(security_manager, slc, dash))

            for cid in sorted(visible)[:3]:
                slc = next((s for s in dash.slices if s.id == cid), None)
                if slc and slc.datasource:
                    check("visible chart %s allowed" % cid,
                          can_read(security_manager, slc, dash))

            for cid in sorted(hidden_charts)[:1]:
                slc = next((s for s in dash.slices if s.id == cid), None)
                if slc and slc.datasource:
                    check("drill-by into hidden chart %s refused" % cid,
                          not security_manager.has_drill_by_access(
                              {"slice_id": 0, "chart_id": slc.id,
                               "groupby": ["x"]},
                              dash, slc.datasource))

        admin = security_manager.find_user(username="admin")
        if admin:
            with override_user(admin):
                print("\n--- as admin ---")
                pos = tab_access.filtered_position(dash)
                check("admin still sees every tab",
                      len([k for k, v in pos.items()
                           if isinstance(v, dict) and v.get("type") == "TAB"])
                      == len(tabs))
                check("admin sees every chart",
                      tab_access.visible_slice_ids(dash)
                      == {s.id for s in dash.slices})
    finally:
        dash.json_metadata = original_metadata
        db.session.commit()
        print("\nrestored json_metadata")

print("\nRESULT=%s failures=%s" % ("PASS" if not failures else "FAIL", failures))
print("DONE")
