"""Phase C unit tests for `agents.insights.tools.persist_insight_v2`.

We stub the async session with a FakeDB that returns canned rows for
each select() the tool issues. This keeps the tests fast and free of
Postgres while still exercising every guard:

  * session_id must resolve and be open
  * chart_id required + must exist + must match session
  * citations must be a non-empty list and each must resolve
  * headline length cap (140 chars)
  * happy path: row inserted with version='v2', chart bound, citations bound
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.insights.specs.skill_context import Capabilities, SkillContext
from agents.insights.tools.persist_insight import HEADLINE_MAX, persist_insight as persist_insight_v2


# ---------------------------------------------------------------------------
# FakeDB - canned-response async session stub
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


class FakeDB:
    """Reads come from `canned`; writes accumulate on `added` + `updates`."""

    def __init__(self) -> None:
        self.added: list = []
        self.updates: list = []
        self.canned: dict[type, list] = {}

    def set_canned(self, model_cls, rows):
        self.canned[model_cls] = list(rows)

    def add(self, obj) -> None:
        self.added.append(obj)
        # Auto-assign UUID id if absent so binds can find it.
        if getattr(obj, "id", None) is None:
            try:
                obj.id = uuid.uuid4()
            except Exception:
                pass

    async def flush(self) -> None:
        return None

    async def execute(self, stmt):
        # Inspect the statement's described columns to figure out the
        # entity. SQLAlchemy 2.x exposes `.column_descriptions`.
        try:
            descs = stmt.column_descriptions
        except Exception:
            descs = []
        # SELECT path
        if descs:
            entity = descs[0].get("entity") or descs[0].get("type")
            for cls, rows in self.canned.items():
                if entity is cls or (hasattr(entity, "__name__") and entity.__name__ == cls.__name__):
                    return _ResultProxy(rows)
            # Plain column select (e.g. AIInsight.idx)
            return _ResultProxy([])
        # UPDATE path -- record and ack.
        self.updates.append(stmt)
        return _ResultProxy([])


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _make_ctx(session_id: str | None = None) -> SkillContext:
    return SkillContext(
        session_id=session_id or str(uuid.uuid4()),
        turn_id="t1",
        correlation_id="c1",
        model="gpt-4.1",
        budget_seconds_remaining=300.0,
        capabilities=Capabilities(can_emit_chart=True),
    )


def _session_row(sid: uuid.UUID, status: str = "running"):
    from agents.insights.db.models import AISession

    return AISession(id=sid, status=status, max_insights=7, version="v2")


def _chart_row(chart_id: str, sid: uuid.UUID):
    from agents.insights.db.models import AgentChart

    return AgentChart(
        id=chart_id,
        session_id=sid,
        insight_id=uuid.uuid4(),  # placeholder; will be overwritten by bind
        spec={"chart_id": chart_id, "chart_type": "bar"},
        data_source={"kind": "db_query", "spec": {"sql": "SELECT 1"}, "rows": 1, "fetched_at": "2026-05-07T00:00:00+00:00", "row_hash": "0" * 64},
        row_hash="0" * 64,
    )


def _citation_row():
    from agents.insights.db.models import AgentCitation

    cid = uuid.uuid4()
    row = AgentCitation(
        id=cid,
        insight_id=uuid.uuid4(),  # will be overwritten
        url="https://example.com/x",
        title="Example",
        snippet="Snippet text",
        agree_or_disagree="agree",
        rationale="r",
        search_query="q",
    )
    return row


def _make_db_with_session(*, status="running", chart_id="c_abcdef12", with_citations=True):
    sid = uuid.uuid4()
    db = FakeDB()
    db.set_canned(_session_row(sid, status).__class__, [_session_row(sid, status)])
    db.set_canned(_chart_row(chart_id, sid).__class__, [_chart_row(chart_id, sid)])
    cits = [_citation_row()] if with_citations else []
    db.set_canned(_citation_row().__class__, cits)
    return db, sid, [str(c.id) for c in cits]


# ---------------------------------------------------------------------------
# Argument guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_db_required():
    out = await persist_insight_v2(
        headline="x",
        body=None,
        confidence="med",
        materiality="med",
        chart_id="c_abcdef12",
        citations=["x"],
        db=None,
    )
    assert out["ok"] is False and out["error"] == "db_required"


@pytest.mark.asyncio
async def test_session_id_required():
    db = FakeDB()
    out = await persist_insight_v2(
        headline="x",
        body=None,
        confidence="med",
        materiality="med",
        chart_id="c_abcdef12",
        citations=["00000000-0000-0000-0000-000000000000"],
        db=db,
    )
    assert out["ok"] is False and out["error"] == "session_id_required"


@pytest.mark.asyncio
async def test_chart_id_optional_persists_without_chart():
    """Round 3: chart_id is now optional. Empty string is treated the same
    as None: the chart-resolution branch is skipped entirely and the
    insight lands with chart_id=NULL. A follow-up build_chart(insight_id=...)
    is the new way to bind a chart on the agent_chart side.
    """
    db, sid, citation_ids = _make_db_with_session()
    out = await persist_insight_v2(
        headline="round 3 headline",
        body=None,
        confidence="med",
        materiality="med",
        chart_id="",  # empty string == not provided
        citations=citation_ids,
        db=db,
        session_id=sid,
    )
    assert out["ok"] is True, out
    assert out["chart_id"] is None
    assert out["citation_count"] == 1
    assert out["version"] == "v2"
    # The persisted ai_insight row must have chart_id=NULL.
    from agents.insights.db.models import AIInsight

    insight_rows = [a for a in db.added if isinstance(a, AIInsight)]
    assert len(insight_rows) == 1
    assert getattr(insight_rows[0], "chart_id", "missing") is None
    assert getattr(insight_rows[0], "version", None) == "v2"


@pytest.mark.asyncio
async def test_citations_required_empty_list():
    db, sid, _ = _make_db_with_session(with_citations=False)
    out = await persist_insight_v2(
        headline="x",
        body=None,
        confidence="med",
        materiality="med",
        chart_id="c_abcdef12",
        citations=[],
        db=db,
        session_id=sid,
    )
    assert out["ok"] is False and out["error"] == "citations_required"


@pytest.mark.asyncio
async def test_headline_too_long():
    db, sid, citation_ids = _make_db_with_session()
    out = await persist_insight_v2(
        headline="x" * (HEADLINE_MAX + 1),
        body=None,
        confidence="med",
        materiality="med",
        chart_id="c_abcdef12",
        citations=citation_ids,
        db=db,
        session_id=sid,
    )
    assert out["ok"] is False and out["error"] == "headline_too_long"


# ---------------------------------------------------------------------------
# Resolution guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_not_found():
    db = FakeDB()
    # Empty canned for AISession -> not found.
    from agents.insights.db.models import AISession

    db.set_canned(AISession, [])
    out = await persist_insight_v2(
        headline="x",
        body=None,
        confidence="med",
        materiality="med",
        chart_id="c_abcdef12",
        citations=[str(uuid.uuid4())],
        db=db,
        session_id=uuid.uuid4(),
    )
    assert out["ok"] is False and out["error"] == "session_not_found"


@pytest.mark.asyncio
async def test_session_closed():
    db, sid, citation_ids = _make_db_with_session(status="finished")
    out = await persist_insight_v2(
        headline="x",
        body=None,
        confidence="med",
        materiality="med",
        chart_id="c_abcdef12",
        citations=citation_ids,
        db=db,
        session_id=sid,
    )
    assert out["ok"] is False and out["error"] == "session_closed"


@pytest.mark.asyncio
async def test_chart_not_found():
    db, sid, citation_ids = _make_db_with_session()
    # Wipe the chart canned set.
    from agents.insights.db.models import AgentChart

    db.set_canned(AgentChart, [])
    out = await persist_insight_v2(
        headline="x",
        body=None,
        confidence="med",
        materiality="med",
        chart_id="c_abcdef12",
        citations=citation_ids,
        db=db,
        session_id=sid,
    )
    assert out["ok"] is False and out["error"] == "chart_not_found"


@pytest.mark.asyncio
async def test_chart_session_mismatch():
    db, sid, citation_ids = _make_db_with_session()
    # Replace chart with one whose session_id is different.
    from agents.insights.db.models import AgentChart

    other_sid = uuid.uuid4()
    db.set_canned(AgentChart, [_chart_row("c_abcdef12", other_sid)])
    out = await persist_insight_v2(
        headline="x",
        body=None,
        confidence="med",
        materiality="med",
        chart_id="c_abcdef12",
        citations=citation_ids,
        db=db,
        session_id=sid,
    )
    assert out["ok"] is False and out["error"] == "chart_session_mismatch"


@pytest.mark.asyncio
async def test_citation_unresolved():
    db, sid, _ = _make_db_with_session(with_citations=False)
    # Pass a fake citation_id that won't resolve.
    out = await persist_insight_v2(
        headline="x",
        body=None,
        confidence="med",
        materiality="med",
        chart_id="c_abcdef12",
        citations=[str(uuid.uuid4())],
        db=db,
        session_id=sid,
    )
    assert out["ok"] is False and out["error"] == "citation_unresolved"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_inserts_v2_insight_and_binds_chart():
    db, sid, citation_ids = _make_db_with_session()
    out = await persist_insight_v2(
        headline="OCI free-cooling vs AWS dry-bulb spread widens to 4.2C in q2",
        body="Body text here.",
        confidence="med",
        materiality="high",
        chart_id="c_abcdef12",
        citations=citation_ids,
        open_question_id="oq_2026_05_07_a",
        skills_run=["data-quality-audit"],
        db=db,
        session_id=sid,
    )
    assert out["ok"] is True, out
    assert out["chart_id"] == "c_abcdef12"
    assert out["citation_count"] == 1
    assert out["version"] == "v2"
    # Inserted exactly one AIInsight row tagged version='v2'
    from agents.insights.db.models import AIInsight

    insight_rows = [a for a in db.added if isinstance(a, AIInsight)]
    assert len(insight_rows) == 1
    insight = insight_rows[0]
    assert getattr(insight, "version", None) == "v2"
    assert getattr(insight, "chart_id", None) == "c_abcdef12"
    assert getattr(insight, "open_question_id", None) == "oq_2026_05_07_a"
    cits = getattr(insight, "citations", None)
    assert isinstance(cits, list) and len(cits) == 1
    # At least one UPDATE issued (chart bind + citation bind).
    assert len(db.updates) >= 1
