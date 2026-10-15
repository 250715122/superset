# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Per-tab access control for dashboards.

Upstream Superset has no notion of tab level permissions - a ``TAB`` node in
``position_json`` is pure layout. Hiding one in the browser would also not be
access control, because a user who may open a dashboard is granted datasource
access to *every* chart on it: see the ``slc in dashboard_.slices`` branch of
``SupersetSecurityManager.raise_for_access``. The data of a hidden tab would
still be one chart data request away.

So a tab is restricted by naming roles in ``json_metadata``::

    {"tab_roles": {"TAB-abc123": ["运维"], "TAB-def456": ["分析师", "运维"]}}

A tab that is absent from that mapping stays visible to everyone who can open
the dashboard, which is what keeps every existing dashboard working untouched.
A tab that is listed is visible only to users holding at least one of its
roles, and the charts underneath it are dropped from the layout, from the
chart and dataset endpoints, and from the dashboard-implies-datasource grant.

Roles are stored by *name* rather than id so that exporting a dashboard and
importing it into another environment keeps working.

The mapping deliberately lives in ``json_metadata`` and not in the ``TAB``
node's ``meta``: layout is rewritten wholesale on every dashboard save, and a
user who can only see some tabs must never be able to drop the roles of the
tabs they cannot see.

All helpers answer for the *current* request's user.
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from superset.utils import json

if TYPE_CHECKING:
    from superset.models.dashboard import Dashboard

logger = logging.getLogger(__name__)

TAB_ROLES_KEY = "tab_roles"

ROOT_ID = "ROOT_ID"


def _position(dashboard: Dashboard) -> dict[str, Any]:
    try:
        return json.loads(dashboard.position_json) if dashboard.position_json else {}
    except (TypeError, json.JSONDecodeError):
        logger.warning("Dashboard %s has unparsable position_json", dashboard.id)
        return {}


def _metadata(dashboard: Dashboard) -> dict[str, Any]:
    try:
        return json.loads(dashboard.json_metadata) if dashboard.json_metadata else {}
    except (TypeError, json.JSONDecodeError):
        logger.warning("Dashboard %s has unparsable json_metadata", dashboard.id)
        return {}


def tab_roles(dashboard: Dashboard) -> dict[str, set[str]]:
    """Tab id -> role names allowed to see it, for tabs that are restricted."""
    raw = _metadata(dashboard).get(TAB_ROLES_KEY) or {}
    if not isinstance(raw, dict):
        return {}
    result: dict[str, set[str]] = {}
    for tab_id, names in raw.items():
        if isinstance(names, (list, tuple, set)) and names:
            result[str(tab_id)] = {str(name) for name in names}
    return result


def has_unrestricted_access(dashboard: Dashboard) -> bool:
    """Admins and owners always see the whole dashboard.

    Without this an owner could not maintain the tabs they cannot see, and
    would silently destroy them on the next layout save.
    """
    from superset import security_manager

    return security_manager.is_admin() or security_manager.is_owner(dashboard)


def _blocked_tab_ids(dashboard: Dashboard) -> set[str]:
    """Restricted tabs the current user holds no role for."""
    restricted = tab_roles(dashboard)
    if not restricted:
        return set()

    from superset import security_manager

    try:
        if has_unrestricted_access(dashboard):
            return set()
        held = {role.name for role in security_manager.get_user_roles()}
    except (AttributeError, RuntimeError):
        # No user bound to the request - a CLI command, an export, a test
        # fixture. Those contexts are already trusted, and the check that
        # actually guards the data (raise_for_access) always runs with a user.
        logger.debug("No user context; serving dashboard %s unfiltered", dashboard.id)
        return set()

    return {tab_id for tab_id, allowed in restricted.items() if not (allowed & held)}


def _descendants(position: dict[str, Any], node_id: str) -> set[str]:
    seen: set[str] = set()
    stack = [node_id]
    while stack:
        node = position.get(stack.pop())
        if not isinstance(node, dict):
            continue
        for child_id in node.get("children") or []:
            if child_id not in seen:
                seen.add(child_id)
                stack.append(child_id)
    return seen


def _dropped_node_ids(dashboard: Dashboard, position: dict[str, Any]) -> set[str]:
    """Every layout node the current user must not receive.

    Nested tabs come along for free: dropping a tab drops its whole subtree,
    which includes any tabs inside it.
    """
    dropped: set[str] = set()
    for tab_id in _blocked_tab_ids(dashboard):
        if tab_id in position:
            dropped.add(tab_id)
            dropped |= _descendants(position, tab_id)
    return dropped


def _chart_ids(position: dict[str, Any], node_ids: set[str] | None = None) -> set[int]:
    ids: set[int] = set()
    for node_id, node in position.items():
        if node_ids is not None and node_id not in node_ids:
            continue
        if not isinstance(node, dict) or node.get("type") != "CHART":
            continue
        chart_id = (node.get("meta") or {}).get("chartId")
        if isinstance(chart_id, int):
            ids.add(chart_id)
    return ids


def hidden_chart_ids(dashboard: Dashboard) -> set[int]:
    """Charts reachable only through tabs the current user cannot see.

    A chart placed both inside and outside a restricted tab stays visible; it
    is only hidden when every one of its placements is.
    """
    position = _position(dashboard)
    dropped = _dropped_node_ids(dashboard, position)
    if not dropped:
        return set()
    kept = set(position) - dropped
    return _chart_ids(position, dropped) - _chart_ids(position, kept)


def visible_slice_ids(dashboard: Dashboard) -> set[int]:
    """Ids of the dashboard's charts the current user may read.

    Charts that are not placed in the layout at all are left visible: they are
    not under any restricted tab.
    """
    all_ids = {slc.id for slc in dashboard.slices}
    return all_ids - hidden_chart_ids(dashboard)


def is_restricted(dashboard: Dashboard) -> bool:
    """Does this dashboard use tab level access control at all?"""
    return bool(tab_roles(dashboard))


def filtered_position(dashboard: Dashboard) -> dict[str, Any]:
    """The layout with the current user's inaccessible tabs removed."""
    position = _position(dashboard)
    dropped = _dropped_node_ids(dashboard, position)
    if not dropped:
        return position

    kept = {
        node_id: node for node_id, node in position.items() if node_id not in dropped
    }
    for node in kept.values():
        if isinstance(node, dict) and node.get("children"):
            node["children"] = [
                child for child in node["children"] if child not in dropped
            ]

    # A TABS node whose tabs were all removed would render as an empty shell,
    # so collapse it away, repeatedly: removing it can empty its parent too.
    while True:
        empty = {
            node_id
            for node_id, node in kept.items()
            if isinstance(node, dict)
            and node.get("type") in ("TABS", "ROW", "COLUMN")
            and not node.get("children")
        }
        if not empty:
            break
        for node_id in empty:
            kept.pop(node_id, None)
        for node in kept.values():
            if isinstance(node, dict) and node.get("children"):
                node["children"] = [
                    child for child in node["children"] if child not in empty
                ]

    return kept


def filtered_metadata(dashboard: Dashboard) -> dict[str, Any]:
    """``json_metadata`` with references to inaccessible tabs and charts removed.

    Native filter scopes address tabs by layout id and charts by chart id, so
    leaving dangling references behind makes filters either error out or widen
    their scope. Keys this function does not know about are passed through
    untouched.
    """
    metadata = _metadata(dashboard)
    position = _position(dashboard)
    dropped = _dropped_node_ids(dashboard, position)
    if not dropped:
        return metadata

    hidden_charts = hidden_chart_ids(dashboard)

    if isinstance(metadata.get(TAB_ROLES_KEY), dict):
        metadata[TAB_ROLES_KEY] = {
            tab_id: names
            for tab_id, names in metadata[TAB_ROLES_KEY].items()
            if tab_id not in dropped
        }

    filters = metadata.get("native_filter_configuration")
    if isinstance(filters, list):
        kept_filters = []
        for fltr in filters:
            if not isinstance(fltr, dict):
                kept_filters.append(fltr)
                continue
            scope = fltr.get("scope")
            if isinstance(scope, dict):
                root_path = [
                    node_id
                    for node_id in scope.get("rootPath") or []
                    if node_id not in dropped
                ]
                if not root_path:
                    # scoped only to tabs this user cannot see
                    continue
                scope["rootPath"] = root_path
                scope["excluded"] = [
                    chart_id
                    for chart_id in scope.get("excluded") or []
                    if chart_id not in hidden_charts
                ]
            if isinstance(fltr.get("chartsInScope"), list):
                fltr["chartsInScope"] = [
                    chart_id
                    for chart_id in fltr["chartsInScope"]
                    if chart_id not in hidden_charts
                ]
            kept_filters.append(fltr)
        metadata["native_filter_configuration"] = kept_filters

    for key in ("chart_configuration", "global_chart_configuration"):
        config = metadata.get(key)
        if isinstance(config, dict):
            metadata[key] = {
                chart_id: value
                for chart_id, value in config.items()
                if _as_int(chart_id) not in hidden_charts
            }

    for key in ("expanded_slices", "default_filters", "filter_scopes"):
        config = metadata.get(key)
        if isinstance(config, dict):
            metadata[key] = {
                chart_id: value
                for chart_id, value in config.items()
                if _as_int(chart_id) not in hidden_charts
            }

    return metadata


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
