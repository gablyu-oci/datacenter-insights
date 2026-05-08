"""Dedicated regression tests for the AI Insights v2 Phase D Round 3
"insight-first" tool reorder (PRD: docs/ai_insights_v2_phase_d_round3_prd.md).

Round 3 inverts the per-insight loop:

    OLD:  build_chart  ->  emit_citation  ->  persist_insight_v2(chart_id=...)
    NEW:  emit_citation  ->  persist_insight_v2(...)  ->  build_chart(insight_id=...)

The contract changes locked down here:

    1. persist_insight_v2.chart_id is OPTIONAL (None / "" / omitted is OK).
       The insight lands with chart_id=NULL.
    2. build_chart.insight_id is OPTIONAL but, when supplied, is
       SELECT-validated against ai_insight + ai_session_id, and the
       resulting agent_chart row carries the FK populated.
    3. build_chart with a stale, cross-session, or unknown insight_id is
       hard-rejected before any agent_chart row is written.
    4. build_chart without insight_id remains byte-equivalent to Round 2
       (legacy chart-first callers, v1 demo path, ad-hoc tools).
    5. The OpenAI tool schemas in V2_TOOL_DEFS advertise the new shape:
       persist_insight_v2.required no longer includes chart_id;
       build_chart.properties advertises insight_id but does NOT require it.

These tests live in a dedicated file so a future Round-N effort that
unwinds insight-first ordering surfaces in one obvious place. The
e2e regression file (test_v2_insights_e2e_regression.py) keeps the
same contract pinned end-to-end; this file is the unit-tier counterpart.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

# SQLAlchemy SQLite shims so JSONB / UUID columns compile in-process.
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler  # noqa: E402


def _visit_JSONB(self, type_, **kw):  # noqa: N802
    return "TEXT"


def _visit_UUID(self, type_, **kw):  # noqa: N802
    return "CHAR(36)"


SQLiteTypeCompiler.visit_JSONB = _visit_JSONB  # type: ignore[attr-defined]
SQLiteTypeCompiler.visit_UUID = _visit_UUID  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Shared FakeDB helpers (mirror test_persist_insight_v2.py FakeDB shape)
# ---------------------------------------------------------------------------


class _ScalarsProxy:
    def __init__(self, rows):
        self._rows = list(rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _ResultProxy:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return _ScalarsProxy(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeDB:
    """Reads from `canned`; writes accumulate on `added` + `updates`."""

    def __init__(self) -> None:
        self.added: list = []
        self.updates: list = []
        self.canned: dict[type, list] = {}

    def set_canned(self, model_cls, rows):
        self.canned[model_cls] = list(rows)

    def add(self, obj) -> None:
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            try:
                obj.id = uuid.uuid4()
            except Exception:  # noqa: BLE001
                pass

    async def flush(self) -> None:
        return None

    async def execute(self, stmt):
        try:
            descs = stmt.column_descriptions
        except Exception:  # noqa: BLE001
            descs = []
        if descs:
            entity = descs[0].get("entity") or descs[0].get("type")
            for cls, rows in self.canned.items():
                if entity is cls or (
                    hasattr(entity, "__name__")
                    and entity.__name__ == cls.__name__
                ):
                    return _ResultProxy(rows)
            return _ResultProxy([])
        self.updates.append(stmt)
        return _ResultProxy([])


def _session_row(sid: uuid.UUID, status: str = "running"):
    from agents.insights.db.models import AISession

    return AISession(id=sid, status=status, max_insights=7, version="v2")


def _citation_row():
    from agents.insights.db.models import AgentCitation

    return AgentCitation(
        id=uuid.uuid4(),
        insight_id=uuid.uuid4(),
        url="https://example.com/r3",
        title="r3",
        snippet="snip",
        agree_or_disagree="agree",
        rationale="r",
        search_query="q",
    )


def _insight_row(insight_id: uuid.UUID, session_id: uuid.UUID):
    from agents.insights.db.models import AIInsight

    return AIInsight(
        id=insight_id,
        session_id=session_id,
        idx=0,
        headline="round 3 anchor headline",
        body=None,
        confidence="med",
        materiality="med",
    )


def _make_persist_db():
    from agents.insights.db.models import AgentChart, AISession, AgentCitation

    sid = uuid.uuid4()
    db = _FakeDB()
    db.set_canned(AISession, [_session_row(sid)])
    db.set_canned(AgentChart, [])  # chart-resolution path is NOT entered
    cit = _citation_row()
    db.set_canned(AgentCitation, [cit])
    return db, sid, [str(cit.id)]


def _make_build_chart_db(insight_session_id: uuid.UUID, insight_id: uuid.UUID):
    from agents.insights.db.models import AIInsight

    db = _FakeDB()
    row = _insight_row(insight_id, insight_session_id)
    db.set_canned(AIInsight, [row])
    return db


def _make_build_chart_db_no_insight():
    from agents.insights.db.models import AIInsight

    db = _FakeDB()
    db.set_canned(AIInsight, [])
    return db


def _patch_query_database(monkeypatch, rows, columns):
    from datetime import datetime, timezone

    from agents.insights.tools import build_chart as build_chart_mod
    from agents.insights.tools.sql_gate import validate_sql

    async def _stub(sql, ctx=None, *, max_rows=5000):
        validated = validate_sql(sql, max_rows=max_rows)
        return {
            "rows": rows,
            "columns": columns,
            "row_count": len(rows),
            "executed_sql": validated.normalized_sql,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "row_hash": "0" * 64,
            "applied_limit": validated.applied_limit,
            "notes": validated.notes,
            "truncated": False,
        }

    monkeypatch.setattr(build_chart_mod, "query_database", _stub)


def _make_ctx(session_id: uuid.UUID):
    from agents.insights.specs.skill_context import Capabilities, SkillContext

    return SkillContext(
        session_id=str(session_id),
        turn_id="r3-t",
        correlation_id="r3-c",
        model="gpt-4.1",
        budget_seconds_remaining=300.0,
        capabilities=Capabilities(can_query_db=True, can_emit_chart=True),
    )


# ---------------------------------------------------------------------------
# 1. persist_insight_v2(chart_id=None) succeeds and writes chart_id NULL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_insight_v2_optional_chart_id_persists_without_chart() -> None:
    """Round 3: chart_id is optional. With chart_id=None, the insight
    must land successfully with chart_id=NULL and version='v2'.
    """
    from agents.insights.db.models import AIInsight
    from agents.insights.tools.persist_insight_v2 import persist_insight_v2

    db, sid, citation_ids = _make_persist_db()
    out = await persist_insight_v2(
        headline="r3 insight no-chart",
        body=None,
        confidence="med",
        materiality="med",
        chart_id=None,
        citations=citation_ids,
        db=db,
        session_id=sid,
    )
    assert out["ok"] is True, out
    assert out["chart_id"] is None
    assert out["version"] == "v2"
    assert out["citation_count"] == 1

    insights = [a for a in db.added if isinstance(a, AIInsight)]
    assert len(insights) == 1
    insight = insights[0]
    assert getattr(insight, "version", None) == "v2"
    assert getattr(insight, "chart_id", "missing") is None


@pytest.mark.asyncio
async def test_persist_insight_v2_optional_chart_id_persists_with_empty_string() -> None:
    """Round 3 robustness: chart_id="" is treated as None (the registry
    layer maps missing/falsy to None). Confirms `bool("") is False`
    semantics in the chart_id_present guard.
    """
    from agents.insights.db.models import AIInsight
    from agents.insights.tools.persist_insight_v2 import persist_insight_v2

    db, sid, citation_ids = _make_persist_db()
    out = await persist_insight_v2(
        headline="r3 insight empty-chart",
        body=None,
        confidence="med",
        materiality="med",
        chart_id="",
        citations=citation_ids,
        db=db,
        session_id=sid,
    )
    assert out["ok"] is True, out
    assert out["chart_id"] is None

    insights = [a for a in db.added if isinstance(a, AIInsight)]
    assert len(insights) == 1
    assert getattr(insights[0], "chart_id", "missing") is None


# ---------------------------------------------------------------------------
# 2. build_chart(insight_id=...) binds FK on session match
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_chart_with_insight_id_binds_fk_when_session_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 3 happy path. agent_chart row must carry the bound FK."""
    from agents.insights.db.models import AgentChart
    from agents.insights.tools.build_chart import build_chart

    sid = uuid.uuid4()
    iid = uuid.uuid4()
    db = _make_build_chart_db(insight_session_id=sid, insight_id=iid)
    _patch_query_database(
        monkeypatch,
        [{"region": "us-east", "gw": 1.2}, {"region": "us-west", "gw": 0.9}],
        ["region", "gw"],
    )

    out = await build_chart(
        sql="SELECT region, gw FROM v_power",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="bar",
        title="R3 bind happy path",
        insight_id=str(iid),
        ctx=_make_ctx(sid),
        db=db,
    )
    assert out["ok"] is True, out
    assert out["insight_id"] == str(iid)

    chart_rows = [a for a in db.added if isinstance(a, AgentChart)]
    assert len(chart_rows) == 1
    persisted = chart_rows[0]
    assert persisted.insight_id is not None
    assert str(persisted.insight_id) == str(iid)


# ---------------------------------------------------------------------------
# 3. build_chart rejects insight_id from a different session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_chart_rejects_insight_id_for_other_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents.insights.db.models import AgentChart
    from agents.insights.tools.build_chart import build_chart

    other_sid = uuid.uuid4()
    ctx_sid = uuid.uuid4()
    iid = uuid.uuid4()
    db = _make_build_chart_db(insight_session_id=other_sid, insight_id=iid)
    _patch_query_database(
        monkeypatch,
        [{"region": "us-east", "gw": 1.2}],
        ["region", "gw"],
    )

    out = await build_chart(
        sql="SELECT region, gw FROM v_power",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="bar",
        title="R3 cross-session reject",
        insight_id=str(iid),
        ctx=_make_ctx(ctx_sid),
        db=db,
    )
    assert out["ok"] is False
    assert out["error"] == "insight_session_mismatch", out
    assert [a for a in db.added if isinstance(a, AgentChart)] == [], (
        "no agent_chart row may be written when session-mismatch fires"
    )


# ---------------------------------------------------------------------------
# 4. build_chart rejects unknown insight_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_chart_rejects_unknown_insight_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents.insights.db.models import AgentChart
    from agents.insights.tools.build_chart import build_chart

    sid = uuid.uuid4()
    db = _make_build_chart_db_no_insight()
    _patch_query_database(
        monkeypatch,
        [{"region": "us-east", "gw": 1.2}],
        ["region", "gw"],
    )

    out = await build_chart(
        sql="SELECT region, gw FROM v_power",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="bar",
        title="R3 unknown-id reject",
        insight_id="00000000-0000-0000-0000-000000000000",
        ctx=_make_ctx(sid),
        db=db,
    )
    assert out["ok"] is False
    assert out["error"] == "insight_not_found", out
    assert [a for a in db.added if isinstance(a, AgentChart)] == []


# ---------------------------------------------------------------------------
# 5. build_chart without insight_id keeps legacy NULL FK behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_chart_without_insight_id_keeps_legacy_null_fk_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v1 demo + ad-hoc chart-first callers must keep working: when
    insight_id is omitted/None, the agent_chart row lands with
    insight_id=NULL.
    """
    from agents.insights.db.models import AgentChart
    from agents.insights.tools.build_chart import build_chart

    sid = uuid.uuid4()
    db = _FakeDB()
    _patch_query_database(
        monkeypatch,
        [{"region": "us-east", "gw": 1.2}, {"region": "us-west", "gw": 0.9}],
        ["region", "gw"],
    )

    out = await build_chart(
        sql="SELECT region, gw FROM v_power",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="bar",
        title="R3 legacy-NULL-fk",
        ctx=_make_ctx(sid),
        db=db,
    )
    assert out["ok"] is True, out
    assert out.get("insight_id") is None

    chart_rows = [a for a in db.added if isinstance(a, AgentChart)]
    assert len(chart_rows) == 1
    assert chart_rows[0].insight_id is None


# ---------------------------------------------------------------------------
# 6. Registry: build_chart advertises insight_id (optional)
# ---------------------------------------------------------------------------


def test_registry_build_chart_schema_advertises_insight_id() -> None:
    from agents.insights.tools.registry import V2_TOOL_DEFS

    spec = next(
        t for t in V2_TOOL_DEFS if t["function"]["name"] == "build_chart"
    )
    params = spec["function"]["parameters"]
    assert "insight_id" in params["properties"]
    assert "insight_id" not in params["required"]
    assert params["required"] == ["sql", "encoding", "chart_type", "title"]


# ---------------------------------------------------------------------------
# 7. Registry: persist_insight_v2.chart_id no longer required
# ---------------------------------------------------------------------------


def test_registry_persist_insight_v2_chart_id_no_longer_required() -> None:
    from agents.insights.tools.registry import V2_TOOL_DEFS

    spec = next(
        t for t in V2_TOOL_DEFS if t["function"]["name"] == "persist_insight_v2"
    )
    params = spec["function"]["parameters"]
    assert "chart_id" not in params["required"]
    assert set(params["required"]) == {
        "headline",
        "confidence",
        "materiality",
        "citations",
    }
    assert "chart_id" in params["properties"]
    assert params["properties"]["citations"]["minItems"] == 1


# ---------------------------------------------------------------------------
# 8. Prompt-contract sanity: persist precedes build_chart in Workflow
# ---------------------------------------------------------------------------


def test_synthesis_rules_v2_prompt_orders_persist_before_chart() -> None:
    """A second copy of the prompt-ordering invariant lives here so the
    Round 3 dedicated file can stand alone as the regression manifest.
    """
    import re

    prompt_path = Path(BACKEND_ROOT) / "agents" / "insights" / "prompts" / "synthesis_rules_v2.md"
    content = prompt_path.read_text(encoding="utf-8")

    assert "PERSIST FIRST" in content
    assert "Chart (follow-up)" in content

    workflow = re.search(
        r"##\s+Workflow.*?(?=\n##\s+|\Z)", content, flags=re.DOTALL
    )
    assert workflow, "Workflow section missing"
    pi = workflow.group(0).find("persist_insight_v2")
    bc = workflow.group(0).find("build_chart")
    assert pi != -1 and bc != -1
    assert pi < bc, (
        "Round 3 invariant: persist_insight_v2 must precede build_chart "
        "in the Workflow section"
    )

    assert len(content.encode("utf-8")) < 4096, "prompt exceeded 4 KiB ceiling"
