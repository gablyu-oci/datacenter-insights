"""Phase C tool-registry shape tests.

Lock down the V1/V2 split so a future refactor cannot silently strip a
v1 tool or break the v2 surface contract:

  * V1_TOOL_DEFS contains the exact set of v1 names (no build_chart,
    no persist_insight_v2).
  * V2_TOOL_DEFS is a strict superset of V1 plus exactly two new specs:
    `build_chart` and `persist_insight_v2`.
  * Every name in V2_TOOL_DEFS resolves through the dispatch table.
  * Every spec is JSON-serialisable (the OpenAI client serialises before
    the wire send, so any non-JSON field would blow up at runtime).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.insights.tools import registry as registry_mod
from agents.insights.tools.registry import (
    TOOL_DEFS,
    V1_TOOL_DEFS,
    V2_TOOL_DEFS,
    _DISPATCH,
)


# ---------------------------------------------------------------------------
# V1 surface lock-in
# ---------------------------------------------------------------------------


# These are the v1 tool names that must remain registered. The list is
# the snapshot we shipped before Phase C; do not mutate it without an
# accompanying migration / runbook update.
EXPECTED_V1_NAMES = {
    "query_database",
    "call_api",
    "get_chart_data",
    "run_skill",
    "emit_chart",
    "web_search",
    "read_workspace",
    "search_documents",
    "emit_citation",
}


def _names(defs):
    return {t["function"]["name"] for t in defs}


def test_v1_tool_defs_unchanged():
    """V1_TOOL_DEFS is the authoritative v1 surface and must equal the
    pinned set above. New tools belong on V2_TOOL_DEFS only.
    """
    assert _names(V1_TOOL_DEFS) == EXPECTED_V1_NAMES


def test_v1_tool_defs_alias_matches_legacy_TOOL_DEFS():
    assert V1_TOOL_DEFS is TOOL_DEFS


def test_v1_does_not_contain_v2_only_tools():
    v1 = _names(V1_TOOL_DEFS)
    assert "build_chart" not in v1
    assert "persist_insight_v2" not in v1


# ---------------------------------------------------------------------------
# V2 surface lock-in
# ---------------------------------------------------------------------------


def test_v2_is_strict_superset_of_v1():
    v1 = _names(V1_TOOL_DEFS)
    v2 = _names(V2_TOOL_DEFS)
    assert v1.issubset(v2)


def test_v2_adds_exactly_build_chart_and_persist_insight_v2():
    extra = _names(V2_TOOL_DEFS) - _names(V1_TOOL_DEFS)
    assert extra == {"build_chart", "persist_insight_v2"}


def test_build_chart_spec_required_fields():
    spec = next(t for t in V2_TOOL_DEFS if t["function"]["name"] == "build_chart")
    params = spec["function"]["parameters"]
    assert params["required"] == ["sql", "encoding", "chart_type", "title"]
    enums = params["properties"]["chart_type"]["enum"]
    # Spot-check a few v1 chart types are present.
    assert "stacked_bar" in enums
    assert "treemap" in enums
    assert len(enums) == 16  # ChartSpec ChartType union size


def test_persist_insight_v2_spec_required_fields():
    """Round 3: chart_id is no longer in the `required` list — the
    insight-first ordering means persist runs before build_chart and
    `chart_id` is bound separately via `build_chart(insight_id=...)`.
    chart_id MUST still appear in `properties` (optional, not removed)
    so legacy chart-first callers continue to validate cleanly.
    """
    spec = next(
        t for t in V2_TOOL_DEFS if t["function"]["name"] == "persist_insight_v2"
    )
    params = spec["function"]["parameters"]
    assert set(params["required"]) == {
        "headline",
        "confidence",
        "materiality",
        "citations",
    }
    assert "chart_id" not in params["required"]
    # chart_id stays in properties (still accepted, just no longer required).
    assert "chart_id" in params["properties"]
    cits = params["properties"]["citations"]
    assert cits["minItems"] == 1


# ---------------------------------------------------------------------------
# Dispatch lock-in
# ---------------------------------------------------------------------------


def test_every_v2_tool_has_a_dispatcher():
    for name in _names(V2_TOOL_DEFS):
        assert name in _DISPATCH, f"missing dispatch for {name!r}"


def test_dispatch_includes_v2_only_entries():
    assert "build_chart" in _DISPATCH
    assert "persist_insight_v2" in _DISPATCH


# ---------------------------------------------------------------------------
# JSON-serialisability (pre-flight for the OpenAI tools= argument)
# ---------------------------------------------------------------------------


def test_v2_tool_defs_are_json_serialisable():
    # Must round-trip through json.dumps/loads cleanly.
    payload = json.dumps(V2_TOOL_DEFS)
    restored = json.loads(payload)
    assert _names(restored) == _names(V2_TOOL_DEFS)
