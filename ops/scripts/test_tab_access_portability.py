# -*- coding: utf-8 -*-
"""Checks that tab restrictions survive an export/import and do not leak through one.

Two separate questions, both about the export path:

1. Portability - an owner exports the dashboard and imports it elsewhere. The
   tab roles must come back, which is why they are stored by role *name*. The
   import rewrites chart ids inside ``metadata``, so this asserts the tab ids
   the roles are keyed by still match the imported layout.

2. Containment - the export is a read path like any other. A user who only
   sees some tabs must not be able to export the dashboard and read the hidden
   tabs' layout, charts or dataset definitions out of the YAML. ``can_export on
   Dashboard`` is held by Gamma in this deployment, so this is reachable.

The import half runs against this same instance under a fresh uuid and deletes
what it created. Charts and datasets are imported with overwrite disabled, so
existing ones are matched by uuid and left untouched.

Usage: test_tab_access_portability.py <dashboard id> [tab id]
"""
import os
import sys
import uuid as uuid_mod

os.environ.setdefault("SUPERSET_CONFIG_PATH", "/opt/superset/superset_config.py")
from superset.app import create_app  # noqa: E402

import yaml  # noqa: E402

DASHBOARD_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 9
RESTRICT_TAB = sys.argv[2] if len(sys.argv) > 2 else None

ROLE_NAME = "TABPORT-仅限运维"
USER_NAME = "tabport_probe"

failures = []


def check(label, ok, detail=""):
    print("   %-4s %s%s" % ("OK" if ok else "FAIL", label,
                            ("  <- %s" % detail) if detail else ""))
    if not ok:
        failures.append(label)


def export_contents(dashboard_id):
    """Run the export command and materialise it into {path: yaml string}."""
    from superset.commands.dashboard.export import ExportDashboardsCommand

    contents = {}
    for path, content in ExportDashboardsCommand([dashboard_id]).run():
        contents[path] = content() if callable(content) else content
    return contents


def dashboard_doc(contents):
    for path, body in contents.items():
        if path.startswith("dashboards/"):
            return yaml.safe_load(body)
    return None


app = create_app()
with app.app_context():
    from superset import db, security_manager
    from superset.dashboards import tab_access
    from superset.models.dashboard import Dashboard
    from superset.utils import json
    from superset.utils.core import override_user

    dash = db.session.get(Dashboard, DASHBOARD_ID)
    if not dash:
        sys.exit("dashboard %s not found" % DASHBOARD_ID)

    position = json.loads(dash.position_json or "{}")
    tabs = {k: v for k, v in position.items() if isinstance(v, dict)
            and v.get("type") == "TAB"}
    if not tabs:
        sys.exit("dashboard %s has no tabs" % DASHBOARD_ID)

    tab_id = RESTRICT_TAB or sorted(tabs)[0]
    if tab_id not in tabs:
        sys.exit("tab %s not on dashboard %s" % (tab_id, DASHBOARD_ID))

    print("dashboard %s (%s), restricting tab %s (%s)" % (
        DASHBOARD_ID, dash.dashboard_title, tab_id,
        (tabs[tab_id].get("meta") or {}).get("text", "")))

    original_metadata = dash.json_metadata

    role = security_manager.find_role(ROLE_NAME) or security_manager.add_role(ROLE_NAME)
    user = security_manager.find_user(username=USER_NAME)
    if not user:
        user = security_manager.add_user(
            USER_NAME, "Tab", "Port", "tabport@example.com",
            security_manager.find_role("Gamma"),
            password=uuid_mod.uuid4().hex,
        )
    # The probe must be able to *see* the dashboard for the export to be
    # reachable at all, so give it the dashboard's own viewer roles - but none
    # of its editor roles, since this deployment treats an editor as an owner
    # and owners are unrestricted by design.
    probe_roles = [
        r for r in (dash.roles or [])
        if not r.name.startswith(security_manager.EDITOR_ROLE_PREFIX)
    ]
    # A dashboard role alone carries no can_export, so pair it with the base
    # read-only role real viewers hold - that combination is what makes the
    # export endpoint reachable for a non-owner.
    base = security_manager.find_role("只读基线")
    if base:
        probe_roles.append(base)
    user.roles = probe_roles
    db.session.commit()
    print("probe user roles=%s" % [r.name for r in user.roles])

    admin = security_manager.find_user(username="admin")
    imported_id = None

    try:
        metadata = json.loads(original_metadata or "{}")
        metadata[tab_access.TAB_ROLES_KEY] = {tab_id: [ROLE_NAME]}
        dash.json_metadata = json.dumps(metadata)
        db.session.commit()
        dash = db.session.get(Dashboard, DASHBOARD_ID)

        hidden = tab_access.hidden_chart_ids
        with override_user(user):
            hidden_ids = hidden(dash)
        hidden_uuids = {str(s.uuid) for s in dash.slices if s.id in hidden_ids}
        print("charts hidden behind that tab: %s" % sorted(hidden_ids))

        # ---------- 1. the owner's export keeps everything ----------
        print("\n--- exported by admin ---")
        with override_user(admin):
            admin_contents = export_contents(DASHBOARD_ID)
        admin_doc = dashboard_doc(admin_contents)

        check("dashboard yaml present", admin_doc is not None)
        exported_roles = (admin_doc or {}).get("metadata", {}).get(
            tab_access.TAB_ROLES_KEY)
        check("tab_roles survives export",
              exported_roles == {tab_id: [ROLE_NAME]}, str(exported_roles))
        check("roles exported by name, not id",
              all(isinstance(n, str) and not n.isdigit()
                  for names in (exported_roles or {}).values() for n in names))
        check("restricted tab still in the exported layout",
              tab_id in (admin_doc or {}).get("position", {}))
        admin_chart_files = {p for p in admin_contents if p.startswith("charts/")}
        check("hidden charts still exported for the owner",
              all(any(u in admin_contents[p] for p in admin_chart_files)
                  for u in hidden_uuids) if hidden_uuids else True)

        # ---------- 2. the restricted user's export is trimmed ----------
        print("\n--- exported by a viewer without the role ---")
        probe_contents = None
        refusal = None
        with override_user(user):
            can_export = security_manager.can_access("can_export", "Dashboard")
            print("   probe holds can_export on Dashboard: %s" % can_export)
            try:
                probe_contents = export_contents(DASHBOARD_ID)
            except Exception as ex:  # noqa: BLE001
                refusal = "%s: %s" % (type(ex).__name__, ex)

        if probe_contents is None:
            # Refusing the export outright is at least as safe as trimming it,
            # and is what the stock access filters happen to do here. Record
            # which of the two actually fired rather than assuming.
            check("export refused outright for the restricted user",
                  refusal is not None, refusal)
            print("   (layout containment asserted on the trimmed export below"
                  " is therefore not exercised on this deployment)")
        else:
            probe_doc = dashboard_doc(probe_contents)
            probe_position = (probe_doc or {}).get("position", {})
            probe_metadata = (probe_doc or {}).get("metadata", {})

            check("restricted tab dropped from the exported layout",
                  tab_id not in probe_position, str(sorted(probe_position)[:6]))
            check("hidden tab's roles not disclosed",
                  tab_id not in (probe_metadata.get(tab_access.TAB_ROLES_KEY) or {}))

            probe_blob = "\n".join(probe_contents.values())
            leaked = sorted(u for u in hidden_uuids if u in probe_blob)
            check("hidden charts absent from the whole export bundle",
                  not leaked, "leaked %s" % leaked)

            check("hidden charts not re-appended as orphan charts",
                  not any(u in yaml.safe_dump(probe_position)
                          for u in hidden_uuids))

        # Whatever the endpoint decides, the trimming itself must be correct:
        # assert it directly on the dashboard document the command builds.
        print("\n--- the trimming itself, independent of the endpoint ---")
        from superset.commands.dashboard.export import ExportDashboardsCommand

        with override_user(user):
            trimmed = yaml.safe_load(
                ExportDashboardsCommand._file_content(dash)  # noqa: SLF001
            )
        trimmed_position = trimmed.get("position", {})
        check("restricted tab dropped from the exported layout",
              tab_id not in trimmed_position, str(sorted(trimmed_position)[:6]))
        check("hidden tab's roles not disclosed",
              tab_id not in (trimmed.get("metadata", {}).get(
                  tab_access.TAB_ROLES_KEY) or {}))
        trimmed_blob = yaml.safe_dump(trimmed, allow_unicode=True)
        leaked = sorted(u for u in hidden_uuids if u in trimmed_blob)
        check("hidden charts absent from the exported dashboard document",
              not leaked, "leaked %s" % leaked)

        # ---------- 3. import round trip ----------
        print("\n--- import round trip ---")
        new_uuid = str(uuid_mod.uuid4())
        round_trip = dict(admin_contents)
        for path in list(round_trip):
            if path.startswith("dashboards/"):
                doc = yaml.safe_load(round_trip[path])
                doc["uuid"] = new_uuid
                doc["dashboard_title"] = "TABPORT 往返测试 - 可删除"
                doc["slug"] = None
                round_trip[path] = yaml.safe_dump(doc, sort_keys=False,
                                                  allow_unicode=True)
        round_trip.setdefault("metadata.yaml", yaml.safe_dump(
            {"version": "1.0.0", "type": "Dashboard"}, sort_keys=False))

        from superset.commands.dashboard.importers.dispatcher import (
            ImportDashboardsCommand,
        )

        with override_user(admin):
            ImportDashboardsCommand(round_trip, overwrite=False).run()

        new_dash = (db.session.query(Dashboard)
                    .filter(Dashboard.uuid == new_uuid).one_or_none())
        check("dashboard imported", new_dash is not None)

        if new_dash:
            imported_id = new_dash.id
            new_meta = json.loads(new_dash.json_metadata or "{}")
            new_roles = new_meta.get(tab_access.TAB_ROLES_KEY)
            new_position = json.loads(new_dash.position_json or "{}")

            check("tab_roles survives import", new_roles == {tab_id: [ROLE_NAME]},
                  str(new_roles))
            check("the tab it names still exists in the imported layout",
                  all(t in new_position for t in (new_roles or {})),
                  str(sorted(new_position)[:6]))
            check("the named role still resolves after import",
                  all(security_manager.find_role(n) is not None
                      for names in (new_roles or {}).values() for n in names))

            with override_user(user):
                still_hidden = tab_access.hidden_chart_ids(new_dash)
            check("restriction is live on the imported dashboard",
                  bool(still_hidden), "hidden=%s" % sorted(still_hidden))

    finally:
        dash = db.session.get(Dashboard, DASHBOARD_ID)
        dash.json_metadata = original_metadata
        if imported_id:
            victim = db.session.get(Dashboard, imported_id)
            if victim:
                victim.slices = []
                db.session.delete(victim)
            print("\ncleaned up imported dashboard %s" % imported_id)
        db.session.commit()

    print("\n%s" % ("FAILURES: %s" % failures if failures
                    else "all portability checks passed"))
    sys.exit(1 if failures else 0)
