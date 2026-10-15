# -*- coding: utf-8 -*-
"""Edge cases of the layout trimming, on synthetic dashboards.

The live test on real dashboards proves the role check and the enforcement;
these cover the tree walking that real data happens not to exercise: datasets
that only hidden charts use, a chart placed in two tabs at once, tabs nested
inside tabs, native filter scopes, and tab containers left empty.

_blocked_tab_ids is stubbed out so each case can name its hidden tabs directly.
"""
from types import SimpleNamespace

from superset.dashboards import tab_access
from superset.utils import json

failures = []


def check(label, ok, detail=""):
    print("   %-4s %s%s" % ("OK" if ok else "FAIL", label,
                            ("  <- %s" % detail) if detail else ""))
    if not ok:
        failures.append(label)


def dash(position, metadata=None, slices=()):
    return SimpleNamespace(
        id=999,
        position_json=json.dumps(position),
        json_metadata=json.dumps(metadata or {}),
        slices=[SimpleNamespace(id=i, datasource_id=d) for i, d in slices],
    )


def tab(tab_id, children):
    return {"id": tab_id, "type": "TAB", "meta": {"text": tab_id},
            "children": children}


def chart(node_id, chart_id):
    return {"id": node_id, "type": "CHART", "meta": {"chartId": chart_id},
            "children": []}


def hide(*tab_ids):
    tab_access._blocked_tab_ids = lambda d: set(tab_ids)


print("=== a chart reachable only through a hidden tab disappears ===")
hide("TAB-hid")
d = dash(
    {
        "ROOT_ID": {"id": "ROOT_ID", "type": "ROOT", "children": ["TABS-1"]},
        "TABS-1": {"id": "TABS-1", "type": "TABS",
                   "children": ["TAB-vis", "TAB-hid"]},
        "TAB-vis": tab("TAB-vis", ["CHART-a"]),
        "TAB-hid": tab("TAB-hid", ["CHART-b"]),
        "CHART-a": chart("CHART-a", 1),
        "CHART-b": chart("CHART-b", 2),
    },
    slices=((1, 10), (2, 20)),
)
check("hidden chart id reported", tab_access.hidden_chart_ids(d) == {2},
      str(tab_access.hidden_chart_ids(d)))
check("visible slice ids exclude it", tab_access.visible_slice_ids(d) == {1})
pos = tab_access.filtered_position(d)
check("hidden tab gone from layout", "TAB-hid" not in pos)
check("its chart node gone too", "CHART-b" not in pos)
check("visible tab still referenced by TABS",
      pos["TABS-1"]["children"] == ["TAB-vis"], str(pos["TABS-1"]["children"]))

print("\n=== a chart placed in both a hidden and a visible tab stays ===")
hide("TAB-hid")
d = dash(
    {
        "ROOT_ID": {"id": "ROOT_ID", "type": "ROOT", "children": ["TABS-1"]},
        "TABS-1": {"id": "TABS-1", "type": "TABS",
                   "children": ["TAB-vis", "TAB-hid"]},
        "TAB-vis": tab("TAB-vis", ["CHART-a"]),
        "TAB-hid": tab("TAB-hid", ["CHART-b"]),
        "CHART-a": chart("CHART-a", 7),
        "CHART-b": chart("CHART-b", 7),  # same chart, second placement
    },
    slices=((7, 10),),
)
check("chart is not hidden", tab_access.hidden_chart_ids(d) == set(),
      str(tab_access.hidden_chart_ids(d)))
check("chart stays readable", tab_access.visible_slice_ids(d) == {7})

print("\n=== hiding an outer tab takes the tabs nested inside it ===")
hide("TAB-outer")
d = dash(
    {
        "ROOT_ID": {"id": "ROOT_ID", "type": "ROOT", "children": ["TABS-1"]},
        "TABS-1": {"id": "TABS-1", "type": "TABS",
                   "children": ["TAB-outer", "TAB-keep"]},
        "TAB-outer": tab("TAB-outer", ["TABS-2"]),
        "TABS-2": {"id": "TABS-2", "type": "TABS",
                   "children": ["TAB-in1", "TAB-in2"]},
        "TAB-in1": tab("TAB-in1", ["CHART-a"]),
        "TAB-in2": tab("TAB-in2", ["CHART-b"]),
        "TAB-keep": tab("TAB-keep", ["CHART-c"]),
        "CHART-a": chart("CHART-a", 1),
        "CHART-b": chart("CHART-b", 2),
        "CHART-c": chart("CHART-c", 3),
    },
    slices=((1, 10), (2, 10), (3, 11)),
)
pos = tab_access.filtered_position(d)
check("nested tabs removed",
      not {"TAB-in1", "TAB-in2", "TABS-2"} & set(pos), str(sorted(pos)))
check("their charts are hidden", tab_access.hidden_chart_ids(d) == {1, 2},
      str(tab_access.hidden_chart_ids(d)))
check("sibling tab survives", "TAB-keep" in pos)

print("\n=== a tab container left with nothing in it collapses ===")
hide("TAB-only")
d = dash(
    {
        "ROOT_ID": {"id": "ROOT_ID", "type": "ROOT",
                    "children": ["TABS-1", "CHART-top"]},
        "TABS-1": {"id": "TABS-1", "type": "TABS", "children": ["TAB-only"]},
        "TAB-only": tab("TAB-only", ["CHART-a"]),
        "CHART-a": chart("CHART-a", 1),
        "CHART-top": chart("CHART-top", 2),
    },
    slices=((1, 10), (2, 11)),
)
pos = tab_access.filtered_position(d)
check("empty TABS node removed", "TABS-1" not in pos, str(sorted(pos)))
check("ROOT no longer points at it",
      pos["ROOT_ID"]["children"] == ["CHART-top"],
      str(pos["ROOT_ID"]["children"]))

print("\n=== native filter scopes follow the trimming ===")
hide("TAB-hid")
d = dash(
    {
        "ROOT_ID": {"id": "ROOT_ID", "type": "ROOT", "children": ["TABS-1"]},
        "TABS-1": {"id": "TABS-1", "type": "TABS",
                   "children": ["TAB-vis", "TAB-hid"]},
        "TAB-vis": tab("TAB-vis", ["CHART-a"]),
        "TAB-hid": tab("TAB-hid", ["CHART-b"]),
        "CHART-a": chart("CHART-a", 1),
        "CHART-b": chart("CHART-b", 2),
    },
    metadata={
        "tab_roles": {"TAB-hid": ["运维"], "TAB-vis": ["分析"]},
        "native_filter_configuration": [
            {"id": "F-only-hidden", "scope": {"rootPath": ["TAB-hid"],
                                              "excluded": []}},
            {"id": "F-global",
             "scope": {"rootPath": ["ROOT_ID"], "excluded": [2]},
             "chartsInScope": [1, 2]},
            {"id": "F-mixed", "scope": {"rootPath": ["TAB-vis", "TAB-hid"],
                                        "excluded": []}},
        ],
        "chart_configuration": {"1": {"x": 1}, "2": {"x": 2}},
        "expanded_slices": {"1": True, "2": True},
        "color_scheme": "supersetColors",
    },
    slices=((1, 10), (2, 20)),
)
meta = tab_access.filtered_metadata(d)
ids = [f["id"] for f in meta["native_filter_configuration"]]
check("filter scoped only to the hidden tab is dropped",
      "F-only-hidden" not in ids, str(ids))
check("global filter kept", "F-global" in ids)
mixed = next(f for f in meta["native_filter_configuration"]
             if f["id"] == "F-mixed")
check("mixed scope loses the hidden tab",
      mixed["scope"]["rootPath"] == ["TAB-vis"],
      str(mixed["scope"]["rootPath"]))
glob = next(f for f in meta["native_filter_configuration"]
            if f["id"] == "F-global")
check("hidden chart dropped from excluded", glob["scope"]["excluded"] == [])
check("hidden chart dropped from chartsInScope",
      glob["chartsInScope"] == [1], str(glob["chartsInScope"]))
check("hidden tab's roles not disclosed",
      set(meta["tab_roles"]) == {"TAB-vis"}, str(meta["tab_roles"]))
check("chart_configuration trimmed", set(meta["chart_configuration"]) == {"1"})
check("expanded_slices trimmed", set(meta["expanded_slices"]) == {"1"})
check("unrelated keys untouched",
      meta.get("color_scheme") == "supersetColors")

print("\n=== an unrestricted dashboard is passed through unchanged ===")
tab_access._blocked_tab_ids = lambda d: set()
original = {
    "ROOT_ID": {"id": "ROOT_ID", "type": "ROOT", "children": ["TAB-a"]},
    "TAB-a": tab("TAB-a", ["CHART-a"]),
    "CHART-a": chart("CHART-a", 1),
}
d = dash(original, slices=((1, 10),))
check("layout identical", tab_access.filtered_position(d) == original)
check("nothing hidden", tab_access.hidden_chart_ids(d) == set())
check("all slices visible", tab_access.visible_slice_ids(d) == {1})

print("\nRESULT=%s failures=%s" % ("PASS" if not failures else "FAIL", failures))
print("DONE")
