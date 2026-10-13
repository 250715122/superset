# -*- coding: utf-8 -*-
"""Snapshot, diff, or restore manually edited Superset dashboard metadata.

Usage:
  protect_manual_dashboard_edits.py snapshot
  protect_manual_dashboard_edits.py diff
  protect_manual_dashboard_edits.py restore --confirm

The timestamped snapshot is immutable. ``current.json`` is the protected
baseline used by ``diff``. Restore updates existing objects only; the exported
assets ZIP is retained for disaster recovery involving deleted objects.
"""
import datetime
import hashlib
import io
import json
import os
import shutil
import sys
import zipfile

CONF = (
    "/opt/superset/superset_config.py"
    if os.path.exists("/opt/superset/superset_config.py")
    else "/mnt/data/superset/superset_config.py"
)
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from superset.app import create_app  # noqa: E402

app = create_app()

COMMAND = next((arg for arg in sys.argv[1:] if not arg.startswith("-")), "snapshot")
DASH_SLUG = os.environ.get("PROTECT_DASH_SLUG", "cs-bi-overview")
ROOT = os.path.join(
    os.path.dirname(CONF),
    "backups",
    "manual_dashboard_baselines",
    DASH_SLUG,
)
BASELINE = os.path.join(ROOT, "current.json")

DASHBOARD_FIELDS = (
    "dashboard_title",
    "slug",
    "position_json",
    "json_metadata",
    "css",
    "published",
    "certified_by",
    "certification_details",
)
CHART_FIELDS = (
    "slice_name",
    "viz_type",
    "datasource_id",
    "datasource_type",
    "params",
    "query_context",
    "description",
    "cache_timeout",
    "certified_by",
    "certification_details",
)
DATASET_FIELDS = (
    "table_name",
    "schema",
    "sql",
    "extra",
    "main_dttm_col",
    "cache_timeout",
)
DATASET_COLUMN_FIELDS = (
    "type",
    "verbose_name",
    "expression",
    "groupby",
    "filterable",
    "is_dttm",
    "is_active",
    "description",
)


def scalar(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def field_values(obj, fields):
    return {
        field: scalar(getattr(obj, field, None))
        for field in fields
        if hasattr(obj, field)
    }


def owner_ids(obj):
    return sorted(owner.id for owner in (getattr(obj, "owners", None) or []))


def digest(value):
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_snapshot(dashboard):
    dashboard_data = field_values(dashboard, DASHBOARD_FIELDS)
    dashboard_data["owners"] = owner_ids(dashboard)
    charts = {}
    for chart in sorted(dashboard.slices, key=lambda item: item.id):
        chart_data = field_values(chart, CHART_FIELDS)
        chart_data["owners"] = owner_ids(chart)
        chart_data["fingerprint"] = digest(chart_data)
        charts[str(chart.id)] = chart_data
    datasets = {}
    for chart in dashboard.slices:
        ds = chart.datasource
        if ds is None or str(ds.id) in datasets:
            continue
        ds_data = field_values(ds, DATASET_FIELDS)
        ds_data["columns"] = {
            col.column_name: field_values(col, DATASET_COLUMN_FIELDS)
            for col in ds.columns
        }
        ds_data["metrics"] = {
            m.metric_name: {"expression": m.expression, "verbose_name": m.verbose_name}
            for m in ds.metrics
        }
        datasets[str(ds.id)] = ds_data
    content = {
        "format_version": 1,
        "captured_at": datetime.datetime.now().isoformat(),
        "environment": "production",
        "dashboard_id": dashboard.id,
        "dashboard": dashboard_data,
        "charts": charts,
        "datasets": datasets,
    }
    content["dashboard_fingerprint"] = digest(dashboard_data)
    content["full_fingerprint"] = digest(
        {
            "dashboard": dashboard_data,
            "charts": charts,
        }
    )
    return content


def write_json(path, value):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def changed_fields(before, after):
    keys = sorted(set(before) | set(after))
    return [key for key in keys if before.get(key) != after.get(key)]


with app.app_context():
    from flask import g

    from superset import db, security_manager
    from superset.models.dashboard import Dashboard
    from superset.models.slice import Slice

    dashboard = (
        db.session.query(Dashboard).filter_by(slug=DASH_SLUG).first()
    )
    assert dashboard, "dashboard not found: %s" % DASH_SLUG
    os.makedirs(ROOT, exist_ok=True)

    if COMMAND == "snapshot":
        snapshot = build_snapshot(dashboard)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = os.path.join(ROOT, "%s.json" % stamp)
        zip_path = os.path.join(ROOT, "%s_assets.zip" % stamp)
        write_json(json_path, snapshot)
        shutil.copyfile(json_path, BASELINE)

        admin = next(
            (
                user
                for user in security_manager.get_all_users()
                if any(role.name == "Admin" for role in user.roles)
            ),
            None,
        )
        assert admin, "Admin user not found"
        g.user = admin
        from superset.commands.dashboard.export import ExportDashboardsCommand

        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, content in ExportDashboardsCommand([dashboard.id]).run():
                archive.writestr(path, content() if callable(content) else content)
        with open(zip_path, "wb") as handle:
            handle.write(output.getvalue())

        print(
            "SNAPSHOT_DONE|dashboard=%s|charts=%s|fingerprint=%s"
            % (
                dashboard.id,
                len(snapshot["charts"]),
                snapshot["full_fingerprint"],
            )
        )
        print("BASELINE|%s" % BASELINE)
        print(
            "IMMUTABLE|json=%s|zip=%s|zip_sha256=%s"
            % (json_path, zip_path, hashlib.sha256(output.getvalue()).hexdigest())
        )
        raise SystemExit(0)

    assert os.path.isfile(BASELINE), "baseline not found; run snapshot first"
    with open(BASELINE, encoding="utf-8") as handle:
        baseline = json.load(handle)
    current = build_snapshot(dashboard)

    if COMMAND == "diff":
        dashboard_changes = changed_fields(
            baseline["dashboard"],
            current["dashboard"],
        )
        baseline_charts = baseline["charts"]
        current_charts = current["charts"]
        added = sorted(set(current_charts) - set(baseline_charts), key=int)
        removed = sorted(set(baseline_charts) - set(current_charts), key=int)
        modified = {}
        for chart_id in sorted(
            set(baseline_charts) & set(current_charts),
            key=int,
        ):
            fields = changed_fields(
                baseline_charts[chart_id],
                current_charts[chart_id],
            )
            fields = [field for field in fields if field != "fingerprint"]
            if fields:
                modified[chart_id] = fields
        print("DASHBOARD_FIELDS|%s" % ",".join(dashboard_changes))
        print("CHARTS_ADDED|%s" % ",".join(added))
        print("CHARTS_REMOVED|%s" % ",".join(removed))
        for chart_id, fields in modified.items():
            print("CHART_MODIFIED|id=%s|fields=%s" % (chart_id, ",".join(fields)))
        dataset_changes = {}
        base_ds = baseline.get("datasets", {})
        for ds_id in sorted(set(base_ds) | set(current["datasets"]), key=int):
            before = base_ds.get(ds_id, {})
            after = current["datasets"].get(ds_id, {})
            fields = [f for f in changed_fields(before, after)
                      if f not in ("columns", "metrics")]
            for kind in ("columns", "metrics"):
                b, a = before.get(kind, {}), after.get(kind, {})
                fields += ["%s+%s" % (kind, k) for k in sorted(set(a) - set(b))]
                fields += ["%s-%s" % (kind, k) for k in sorted(set(b) - set(a))]
                fields += ["%s~%s" % (kind, k) for k in sorted(set(a) & set(b))
                           if a[k] != b[k]]
            if fields:
                dataset_changes[ds_id] = fields
                print("DATASET_MODIFIED|id=%s|fields=%s" % (ds_id, ",".join(fields)))
        clean = (not dashboard_changes and not added and not removed
                 and not modified and not dataset_changes)
        print("DIFF_DONE|clean=%s" % int(clean))
        raise SystemExit(0 if clean else 2)

    if COMMAND == "restore":
        assert "--confirm" in sys.argv, "restore requires --confirm"
        missing = sorted(
            set(baseline["charts"])
            - {str(chart.id) for chart in dashboard.slices},
            key=int,
        )
        assert not missing, (
            "charts were deleted; restore assets ZIP instead: %s" % missing
        )

        # Always preserve the damaged/current state before restoration.
        emergency_path = os.path.join(
            ROOT,
            "pre_restore_%s.json"
            % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
        )
        write_json(emergency_path, current)

        for field, value in baseline["dashboard"].items():
            if field != "owners" and hasattr(dashboard, field):
                setattr(dashboard, field, value)
        for chart_id, chart_data in baseline["charts"].items():
            chart = db.session.get(Slice, int(chart_id))
            assert chart, "chart missing: %s" % chart_id
            for field, value in chart_data.items():
                if field not in {"owners", "fingerprint"} and hasattr(chart, field):
                    setattr(chart, field, value)
        from superset.connectors.sqla.models import SqlaTable

        for ds_id, ds_data in baseline.get("datasets", {}).items():
            ds = db.session.get(SqlaTable, int(ds_id))
            assert ds, "dataset missing: %s" % ds_id
            for field in DATASET_FIELDS:
                if field in ds_data:
                    setattr(ds, field, ds_data[field])
            for col in list(ds.columns):
                saved = ds_data["columns"].get(col.column_name)
                if saved is None:
                    ds.columns.remove(col)
                    db.session.delete(col)
                    continue
                for field, value in saved.items():
                    setattr(col, field, value)
        db.session.commit()
        print(
            "RESTORE_DONE|dashboard=%s|charts=%s|emergency=%s"
            % (dashboard.id, len(baseline["charts"]), emergency_path)
        )
        raise SystemExit(0)

    raise SystemExit("unknown command: %s" % COMMAND)
