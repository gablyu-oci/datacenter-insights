"""get_chart_data — registry of (tab, chart_id) -> internal endpoint mappings.

ARCH A6.3 enumerates the registry. Each entry delegates to `call_api`.
Unknown (tab, chart_id) combinations return a `tool_error` shape so the
agent can recover.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from ..specs.skill_context import SkillContext
from .call_api import call_api

logger = logging.getLogger(__name__)


# Each value is a (endpoint, params) tuple.
_REGISTRY: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {
    # Power tab — gigawatts by hyperscaler
    ("power", "gw_by_company"): ("/api/power/gw-summary", {}),
    ("power", "gw_by_hyperscaler"): ("/api/power/gw-summary", {}),
    ("power", "timeseries_by_company"): ("/api/power/timeseries", {"days": 180}),

    # Triangulation
    ("triangulation", "l1_summary"): ("/api/triangulation/l1", {}),
    ("triangulation", "l2_implied_gw"): ("/api/triangulation/l2", {}),

    # Anomalies
    ("anomalies", "recent"): ("/api/anomalies/recent", {}),

    # Permits
    ("permits", "building_recent"): ("/api/permits/building", {"days": 180}),

    # Sites / companies / coverage
    ("sites", "by_state"): ("/api/sites/by-state", {}),
    ("companies", "top50_by_gw"): ("/api/companies/top", {"metric": "gw", "limit": 50}),
    ("coverage", "freshness_by_pillar"): ("/api/coverage/freshness", {}),
}


async def get_chart_data(
    tab: str,
    chart_id: str,
    ctx: SkillContext | None = None,
) -> dict[str, Any]:
    key = (tab, chart_id)
    if key not in _REGISTRY:
        return {
            "ok": False,
            "error": "unknown_chart",
            "detail": {"tab": tab, "chart_id": chart_id, "known": sorted(map(list, _REGISTRY.keys()))},
        }
    endpoint, params = _REGISTRY[key]
    out = await call_api(endpoint, params=params, ctx=ctx)
    return {
        "ok": 200 <= int(out.get("status", 500)) < 300,
        "tab": tab,
        "chart_id": chart_id,
        "endpoint": endpoint,
        "params": params,
        "response": out,
    }


def known_charts() -> list[dict[str, str]]:
    """Used by tool descriptions to enumerate the registry to the model."""
    return [{"tab": t, "chart_id": c} for (t, c) in sorted(_REGISTRY.keys())]
