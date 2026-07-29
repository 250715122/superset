# -*- coding: utf-8 -*-
"""Make the dashboard time-range filter actually reach every chart in its scope.

Why it was broken: a native "Time range" filter only sets `time_range` on the
query. The backend turns that into a WHERE clause only via a TEMPORAL_RANGE
adhoc filter (which names the column) -- a chart without one produces SQL with
no time predicate at all, so the filter is silently ignored. Verified by
rendering the SQL: time_range alone -> no WHERE; time_range + a
TEMPORAL_RANGE 'No filter' placeholder -> the range is applied.

Fix: give every in-scope chart a TEMPORAL_RANGE placeholder on its dataset's
main temporal column, comparator "No filter" (a no-op -- renders `true = 1` --
until the user picks a range, so default behaviour is unchanged).

Scope is derived per time filter the same way the frontend does it
(DashboardContainer.tsx): every chart under scope.rootPath minus
scope.excluded. The stored `chartsInScope` is only a cache -- after the
dev->prod dashboard import it still held dev chart ids, so trusting it would
match nothing in prod. This script also refreshes that stale cache.

Dev & prod compatible. Idempotent. ASCII-safe output.
"""
import json
import os

CONF = ("/opt/superset/superset_config.py"
        if os.path.exists("/opt/superset/superset_config.py")
        else "/mnt/data/superset/superset_config.py")
os.environ.setdefault("SUPERSET_CONFIG_PATH", CONF)

from superset.app import create_app  # noqa: E402

DASH_SLUG = "pb-device-analysis"

app = create_app()
with app.app_context():
    from superset import db
    from superset.models.dashboard import Dashboard

    d = db.session.query(Dashboard).filter_by(slug=DASH_SLUG).first()
    if not d:
        print("DASH NOT FOUND")
        raise SystemExit(1)

    meta = json.loads(d.json_metadata or "{}")
    by_id = {s.id: s for s in d.slices}
    all_ids = set(by_id)

    filters = meta.get("native_filter_configuration") or []
    in_scope = set()
    meta_dirty = False
    for f in filters:
        excluded = set((f.get("scope") or {}).get("excluded") or [])
        computed = sorted(all_ids - excluded)
        stale = [c for c in (f.get("chartsInScope") or []) if c not in all_ids]
        if stale or sorted(f.get("chartsInScope") or []) != computed:
            f["chartsInScope"] = computed
            meta_dirty = True
            print("SCOPE_REFRESH|%s|charts=%d|dropped_stale=%d"
                  % ((f.get("name") or "").encode("unicode_escape").decode(),
                     len(computed), len(stale)))
        if f.get("filterType") == "filter_time":
            in_scope.update(computed)

    if meta_dirty:
        d.json_metadata = json.dumps(meta, ensure_ascii=False)
    print("TIME_FILTER_SCOPE|charts=%d" % len(in_scope))

    fixed, skipped, problems = 0, 0, []
    for cid in sorted(in_scope):
        s = by_id.get(cid)
        if not s:
            problems.append("%s: not on dashboard" % cid)
            continue
        ds = s.datasource
        if ds is None:
            problems.append("%s: no datasource" % cid)
            continue

        p = json.loads(s.params or "{}")
        adhoc = p.get("adhoc_filters") or []
        if any(f.get("operator") == "TEMPORAL_RANGE" for f in adhoc):
            skipped += 1
            continue

        col = ds.main_dttm_col
        if not col:
            problems.append("%s: dataset %s has no main_dttm_col"
                            % (cid, ds.table_name))
            continue

        adhoc.append({"clause": "WHERE", "comparator": "No filter",
                      "expressionType": "SIMPLE",
                      "operator": "TEMPORAL_RANGE", "subject": col})
        p["adhoc_filters"] = adhoc
        s.params = json.dumps(p, ensure_ascii=False)
        fixed += 1
        print("FIX|%s|%s|col=%s"
              % (cid, s.slice_name.encode("unicode_escape").decode(), col))

    db.session.commit()
    print("TIMEFILTER_DONE|fixed=%d|already_ok=%d|problems=%d"
          % (fixed, skipped, len(problems)))
    for pr in problems:
        print("  PROBLEM|%s" % pr)
