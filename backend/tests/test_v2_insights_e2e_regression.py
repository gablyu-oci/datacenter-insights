"""Regression tests for the v2-AI-Insights five-bug fix.

Background
----------
The v2 AI Insights pipeline was producing 0 insights because of FIVE
distinct bugs (see docs/ai_insights_v2_phase_d_v2_path_fix_PLAN.md):

  P1. orchestrator.py did not forward `version=` to `run_agentic_synthesis`
      so the v2 prompt never loaded.
  P2. SynthesisChunkAccumulator only counted v1 `persist_insight`,
      ignoring `persist_insight_v2`.
  P3. registry.dispatch hardcoded `db=None` for v2 tools, causing
      `db_required` failures.
  P4. mcp_server._invoke did not commit DB writes.
  P5. _force_finalize_degraded trusted the broken accumulator instead
      of doing a SELECT COUNT(*) FROM ai_insight WHERE session_id=...

This module pins each bug-class with a tight, deterministic test.

Scope notes
-----------
Per acceptance-criterion (g) we want a "real v2 session against a mocked
OpenClaw gateway returning canned tool calls". The existing v1 happy-path
test in `test_agentic_synthesis.py` mocks httpx at the forwarder boundary;
we follow the exact same pattern. Tools like persist_insight_v2 / build_chart
are executed server-side by OpenClaw which calls back into our MCP server
-- a full HTTP-loopback test would require standing up the MCP and the
forwarder cooperatively, which is non-deterministic. We therefore drive
`run_agentic_synthesis` directly with a canned SSE stream and verify the
accumulator + driver behaviour. The DB-count regression for P5 is
exercised against the in-memory SQLite fixture. P4 (commit) is best
covered by `test_mcp_server.py` and we leave that contract there.

P4 NOTE: this file covers P1, P2, P3 and P5 directly. P4 (mcp commit) is
covered by the existing test_mcp_server suite -- a separate regression
test would need to spin up the FastMCP loop, which is out of scope here.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import types
import uuid
from datetime import datetime
from typing import Any, AsyncIterator, Optional
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))
for p in (BACKEND_ROOT, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import agents  # noqa: E402,F401
import agents.insights  # noqa: E402,F401

# Mirror the SQLite shims used by `test_agentic_synthesis.py` so we can
# materialise the v2-related tables in-memory.
try:  # pragma: no cover
    import agents.insights.tools.sql_gate as _real_sql_gate  # noqa: F401
except Exception:  # noqa: BLE001
    pass

from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler  # noqa: E402


def _visit_JSONB(self, type_, **kw):  # noqa: N802
    return "TEXT"


def _visit_UUID(self, type_, **kw):  # noqa: N802
    return "CHAR(36)"


SQLiteTypeCompiler.visit_JSONB = _visit_JSONB  # type: ignore[attr-defined]
SQLiteTypeCompiler.visit_UUID = _visit_UUID  # type: ignore[attr-defined]


from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

import agents.insights.db.models as ai_models  # noqa: E402,F401
from agents.insights.db.models import (  # noqa: E402
    AgentChart,
    AgentMessage,
    AIInsight,
    AISession,
    InsightThread,
)
from agents.insights.hypothesizer import (  # noqa: E402
    FactPack,
    FactRow,
    FactSection,
)
from agents.insights.specs.sse_events import (  # noqa: E402
    InsightCompleteEvent,
    InsightStartedEvent,
    SessionCompleteEvent,
)
from openclaw.sse_translator import (  # noqa: E402
    SynthesisChunkAccumulator,
)
import openclaw.forwarder as fwd_mod  # noqa: E402
from agents.insights.agentic_synthesis import (  # noqa: E402
    SynthesisResult,
    _force_finalize_degraded,
    run_agentic_synthesis,
)
from agents.insights.tools import registry as registry_mod  # noqa: E402


# ---------------------------------------------------------------------------
# DB fixtures (mirrors test_agentic_synthesis.py)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sqlite_engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    needed_tables = [
        AISession.__table__,
        AIInsight.__table__,
        InsightThread.__table__,
        AgentMessage.__table__,
        AgentChart.__table__,
    ]
    async with eng.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: SQLModel.metadata.create_all(
                sync_conn, tables=needed_tables
            )
        )
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(sqlite_engine):
    return sessionmaker(sqlite_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def running_session(session_factory):
    sess = AISession(
        id=uuid.uuid4(),
        status="running",
        model="oci/openai.gpt-5.4",
        focus="OC",
        max_insights=5,
        version="v2",
        insights_emitted=0,
    )
    async with session_factory() as s:
        s.add(sess)
        await s.commit()
    return sess


# ---------------------------------------------------------------------------
# Canned-SSE helpers (mirror test_agentic_synthesis.py)
# ---------------------------------------------------------------------------


def _sse(chunk: dict) -> str:
    return f"data: {json.dumps(chunk)}"


def _delta(*, content: str | None = None,
           tool_call: dict | None = None,
           finish_reason: str | None = None) -> dict:
    delta: dict = {}
    if content is not None:
        delta["content"] = content
    if tool_call is not None:
        delta["tool_calls"] = [tool_call]
    return {"choices": [{"delta": delta, "finish_reason": finish_reason}]}


def _tool_call(*, idx: int, call_id: str, name: str, args: dict) -> dict:
    return {
        "index": idx,
        "id": call_id,
        "function": {
            "name": name,
            "arguments": json.dumps(args),
        },
    }


class _CapturedRequest:
    def __init__(self) -> None:
        self.url: str = ""
        self.headers: dict[str, str] = {}
        self.json_body: dict[str, Any] = {}


class _FakeStreamResponse:
    def __init__(self, *, status_code: int, lines: list[str]) -> None:
        self.status_code = status_code
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def aiter_lines(self) -> AsyncIterator[str]:
        for ln in self._lines:
            await asyncio.sleep(0)
            yield ln

    async def aread(self) -> bytes:
        return b""


class _FakeAsyncClient:
    def __init__(self, *, status_code: int, lines: list[str],
                 captured: _CapturedRequest) -> None:
        self._status = status_code
        self._lines = lines
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    def stream(self, method: str, url: str, *, headers=None, json=None):
        self._captured.url = url
        self._captured.headers = dict(headers or {})
        self._captured.json_body = dict(json or {})
        return _FakeStreamResponse(status_code=self._status, lines=self._lines)


@pytest.fixture
def fake_httpx(monkeypatch: pytest.MonkeyPatch):
    captured = _CapturedRequest()
    state = {"status": 200, "lines": []}

    def _factory(*_a, **_kw):
        return _FakeAsyncClient(
            status_code=state["status"],
            lines=state["lines"],
            captured=captured,
        )

    import httpx as _real_httpx

    fake_mod = types.SimpleNamespace(
        AsyncClient=_factory,
        Timeout=_real_httpx.Timeout,
        TimeoutException=_real_httpx.TimeoutException,
        HTTPError=_real_httpx.HTTPError,
    )
    monkeypatch.setattr(fwd_mod, "httpx", fake_mod)
    return state, captured


class _SSESink:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def __call__(self, evt: Any) -> None:
        self.events.append(evt)


def _build_factpack(row_ids: list[str]) -> FactPack:
    return FactPack(
        generated_at=datetime.utcnow(),
        sections=[
            FactSection(
                name="sec",
                description="t",
                rows=[FactRow(row_id=rid, entity="X") for rid in row_ids],
            )
        ],
    )


# ---------------------------------------------------------------------------
# P2: SSE translator counts persist_insight_v2 (and still counts v1)
# ---------------------------------------------------------------------------


def _new_acc() -> SynthesisChunkAccumulator:
    return SynthesisChunkAccumulator(
        session_id="00000000-0000-0000-0000-0000000000bb",
        thread_id="thr_test",
        message_id="msg_test",
        insight_id="",
    )


def test_translator_counts_persist_insight_v2() -> None:
    """Regression P2: persist_insight_v2 must increment total_insights_persisted.

    The accumulator-counter feeds both the SessionCompleteEvent payload
    and the orchestrator's degraded-fallback DB write. If we miss v2
    persists here, we report 0 insights for a successful v2 session.
    """
    from openclaw.sse_translator import translate_synthesis_chunk

    acc = _new_acc()
    # First the model emits the tool-call delta with name persist_insight_v2.
    translate_synthesis_chunk(
        _delta(tool_call=_tool_call(
            idx=0,
            call_id="call_v2_a",
            name="persist_insight_v2",
            args={
                "headline": "v2 headline",
                "confidence": "high",
                "materiality": "high",
                "chart_id": "c_x",
                "citations": ["cit_1"],
            },
        )),
        acc,
    )
    # Then the assistant turn closes -> tool_call_complete.
    translate_synthesis_chunk(_delta(finish_reason="tool_calls"), acc)

    assert acc.total_insights_persisted == 1, (
        "persist_insight_v2 did not advance the accumulator counter "
        "-- regression of P2"
    )
    assert acc.current_insight_idx == 1


def test_translator_still_counts_v1_persist_insight() -> None:
    """V1 demo path protection -- persist_insight must keep counting."""
    from openclaw.sse_translator import translate_synthesis_chunk

    acc = _new_acc()
    translate_synthesis_chunk(
        _delta(tool_call=_tool_call(
            idx=0,
            call_id="call_v1_a",
            name="persist_insight",
            args={"insight": {"headline": "v1 headline"}},
        )),
        acc,
    )
    translate_synthesis_chunk(_delta(finish_reason="tool_calls"), acc)
    assert acc.total_insights_persisted == 1
    assert acc.current_insight_idx == 1


# ---------------------------------------------------------------------------
# P3: dispatch forwards db= to v2 tools, v1 tools unaffected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_forwards_db_to_v2_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression P3: dispatch() must forward db= to build_chart and
    persist_insight_v2 -- not hardcode db=None."""
    sentinel = object()

    captured: dict[str, dict[str, Any]] = {}

    async def _fake_build_chart(**kwargs):
        captured["build_chart"] = kwargs
        return {"ok": True, "chart_id": "c_fake"}

    async def _fake_persist(**kwargs):
        captured["persist_insight_v2"] = kwargs
        return {"ok": True, "insight_id": str(uuid.uuid4())}

    monkeypatch.setitem(registry_mod._DISPATCH, "build_chart", _fake_build_chart)
    monkeypatch.setitem(
        registry_mod._DISPATCH, "persist_insight_v2", _fake_persist
    )

    await registry_mod.dispatch(
        "build_chart",
        {
            "sql": "select 1",
            "encoding": {"x": "a", "y": "b"},
            "chart_type": "bar",
            "title": "t",
        },
        ctx=None,
        db=sentinel,
    )
    await registry_mod.dispatch(
        "persist_insight_v2",
        {
            "headline": "h",
            "confidence": "high",
            "materiality": "high",
            "chart_id": "c_fake",
            "citations": ["cit_1"],
        },
        ctx=None,
        db=sentinel,
    )

    assert "build_chart" in captured
    assert captured["build_chart"].get("db") is sentinel, (
        "dispatch dropped db= for build_chart -- regression of P3"
    )
    assert "persist_insight_v2" in captured
    assert captured["persist_insight_v2"].get("db") is sentinel, (
        "dispatch dropped db= for persist_insight_v2 -- regression of P3"
    )


@pytest.mark.asyncio
async def test_dispatch_v1_tools_unaffected_by_db_kwarg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V1 protection: query_database is not affected by the new db= kwarg."""
    captured: list[dict[str, Any]] = []

    async def _fake_query_database(sql, *args, **kwargs):
        captured.append({"sql": sql, "args": args, "kwargs": kwargs})
        return {"ok": True, "rows": []}

    monkeypatch.setitem(
        registry_mod._DISPATCH, "query_database", _fake_query_database
    )

    # Without db kwarg.
    out_a = await registry_mod.dispatch(
        "query_database", {"sql": "select 1"}, ctx=None
    )
    # With db sentinel kwarg -- must still succeed and not propagate to v1 tool.
    sentinel = object()
    out_b = await registry_mod.dispatch(
        "query_database", {"sql": "select 2"}, ctx=None, db=sentinel
    )

    assert out_a.get("ok") is True
    assert out_b.get("ok") is True
    assert len(captured) == 2
    # The v1 tool's signature (sql, max_rows=...) should not have been
    # passed `db` -- the dispatcher's per-name branch strips it.
    for call in captured:
        assert "db" not in call["kwargs"], (
            "v1 query_database received db kwarg -- v1 contract broken"
        )


# ---------------------------------------------------------------------------
# P1: orchestrator forwards version= to run_agentic_synthesis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_forwards_version_to_synthesis_driver() -> None:
    """Regression P1: InsightOrchestrator must thread version= through to
    run_agentic_synthesis. Without this the v2 prompt never loads.

    We bypass the heavy bootstrap/hypothesize phases by patching them and
    only assert that `run_agentic_synthesis` is invoked with the correct
    `version` kwarg in both v1 and v2 instantiations.
    """
    from agents.insights import orchestrator as orch_mod

    # The orchestrator imports `run_agentic_synthesis` lazily inside
    # `run_session`; we capture by patching that lazy-bound symbol.
    captured: list[dict[str, Any]] = []

    async def _fake_synth(**kwargs):
        captured.append(kwargs)
        # Return a minimal SynthesisResult-shaped object.
        return SynthesisResult(
            insights_count=0, degraded=False, reason=None
        )

    for desired_version in ("v1", "v2"):
        captured.clear()

        # Fake-DB stub that satisfies both `_persist_session_start` and
        # `_prime_cross_day_dedup` and any other DB roundtrips.
        class _R:
            def scalar_one_or_none(self_inner):
                return None

            def first(self_inner):
                return None

            def all(self_inner):
                return []

            def scalars(self_inner):
                return self_inner

        class _FakeDB:
            async def execute(self, *a, **k):
                return _R()

            async def commit(self):
                return None

            async def rollback(self):
                return None

            def add(self, *a, **k):
                return None

        orch = orch_mod.InsightOrchestrator(
            session_id=uuid.uuid4(),
            db=_FakeDB(),  # type: ignore[arg-type]
            llm=None,
            max_insights=5,
            version=desired_version,
        )

        # Force a non-None FactPack so the driver path actually invokes
        # run_agentic_synthesis (else the orchestrator early-returns).
        orch._fact_pack = _build_factpack(["r1"])

        # Patch the heavy phases out so we get straight to the synthesis call.
        async def _empty_iter(self):
            if False:  # pragma: no cover
                yield None
            return

        with patch.object(
            orch_mod.InsightOrchestrator,
            "_persist_session_start",
            new=AsyncMock(return_value=None),
        ), patch.object(
            orch_mod.InsightOrchestrator,
            "_prime_cross_day_dedup",
            new=AsyncMock(return_value=None),
        ), patch.object(
            orch_mod.InsightOrchestrator,
            "_phase_bootstrap_iter",
            new=_empty_iter,
        ), patch.object(
            orch_mod.InsightOrchestrator,
            "_phase_hypothesize_iter",
            new=_empty_iter,
        ), patch(
            "agents.insights.agentic_synthesis.run_agentic_synthesis",
            side_effect=_fake_synth,
        ):
            # Drain the async generator just enough to invoke the driver.
            async for _evt in orch.run_session(filters={}):
                # The terminal events arrive after the driver returns;
                # we don't need to assert their shape here.
                pass

        assert captured, (
            f"run_agentic_synthesis was never called for version={desired_version!r}"
        )
        kw = captured[-1]
        assert kw.get("version") == desired_version, (
            f"orchestrator forwarded version={kw.get('version')!r} but expected "
            f"{desired_version!r} -- regression of P1"
        )


# ---------------------------------------------------------------------------
# P5: _force_finalize_degraded uses SELECT COUNT(*) when accumulator lies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_force_finalize_uses_db_count(
    session_factory, running_session
) -> None:
    """Regression P5: when the accumulator says 0 but the DB has 3 inserted
    rows, the AISession row's insights_emitted must reflect the DB count."""
    sid = running_session.id

    # Insert 3 ai_insight rows directly.
    async with session_factory() as s:
        for i in range(3):
            ins = AIInsight(
                id=uuid.uuid4(),
                session_id=sid,
                idx=i,
                headline=f"h{i}",
                confidence="high",
                materiality="high",
                version="v2",
            )
            s.add(ins)
        await s.commit()

    async with session_factory() as db:
        await _force_finalize_degraded(
            db,
            session_id=sid,
            reason="test_p5_acc_says_zero",
            insights_count=0,  # accumulator (lying) says 0
        )

    # AISession row must now show 3.
    async with session_factory() as s:
        row = (
            (
                await s.execute(
                    select(AISession).where(AISession.id == sid)
                )
            )
            .scalar_one_or_none()
        )
    assert row is not None
    assert row.insights_emitted == 3, (
        f"expected DB-truth count of 3, got {row.insights_emitted} "
        f"-- regression of P5 (accumulator-trusted)"
    )
    assert row.status == "degraded"


# ---------------------------------------------------------------------------
# (g) End-to-end: v2 session with mocked OpenClaw stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v2_session_end_to_end_with_mocked_openclaw(
    fake_httpx, running_session, session_factory
) -> None:
    """Phase D acceptance criterion (g): run a real v2 session against a
    mocked OpenClaw gateway returning canned tool calls.

    We canned-stream simulates: read_workspace -> search_documents ->
    build_chart -> emit_citation -> persist_insight_v2, repeated 3 times,
    then finalize_session(complete). Tool dispatch happens server-side
    through OpenClaw's MCP loopback; in-process we observe only the SSE
    accumulator + driver behaviour, but combined with the existing P1/P2
    direct unit tests above this gives us the full chain coverage the
    plan calls for.
    """
    state, _ = fake_httpx

    chunks: list[dict] = []
    next_idx = 0
    for i in range(3):
        chunks.append(_delta(content=f"v2 reasoning step {i}"))
        chunks.append(_delta(tool_call=_tool_call(
            idx=next_idx,
            call_id=f"call_rw_{i}",
            name="read_workspace",
            args={"file": "SCHEMA.md"},
        )))
        next_idx += 1
        chunks.append(_delta(tool_call=_tool_call(
            idx=next_idx,
            call_id=f"call_sd_{i}",
            name="search_documents",
            args={"query": "datacenter capacity"},
        )))
        next_idx += 1
        chunks.append(_delta(tool_call=_tool_call(
            idx=next_idx,
            call_id=f"call_bc_{i}",
            name="build_chart",
            args={
                "sql": "select 1 as x, 2 as y",
                "encoding": {"x": "x", "y": "y"},
                "chart_type": "bar",
                "title": f"chart {i}",
            },
        )))
        next_idx += 1
        chunks.append(_delta(tool_call=_tool_call(
            idx=next_idx,
            call_id=f"call_ec_{i}",
            name="emit_citation",
            args={
                "url": "https://example.com",
                "title": "src",
                "snippet": "snippet text",
                "agree_or_disagree": "context",
                "rationale": "snippet text",
                "search_query": "q",
            },
        )))
        next_idx += 1
        chunks.append(_delta(tool_call=_tool_call(
            idx=next_idx,
            call_id=f"call_pi_{i}",
            name="persist_insight_v2",
            args={
                "headline": f"v2 insight {i}",
                "confidence": "high",
                "materiality": "high",
                "chart_id": f"c_{i}",
                "citations": [f"cit_{i}"],
            },
        )))
        next_idx += 1
        chunks.append(_delta(finish_reason="tool_calls"))

    # Final turn -> finalize_session.
    chunks.append(_delta(tool_call=_tool_call(
        idx=next_idx,
        call_id="call_fin",
        name="finalize_session",
        args={"status": "complete", "token_estimate": 4242},
    )))
    chunks.append(_delta(finish_reason="tool_calls"))
    chunks.append(_delta(finish_reason="stop"))

    state["lines"] = [_sse(c) for c in chunks] + ["data: [DONE]"]

    sink = _SSESink()
    pack = _build_factpack(["r1"])
    async with session_factory() as db:
        result: SynthesisResult = await asyncio.wait_for(
            run_agentic_synthesis(
                session_id=running_session.id,
                fact_pack=pack,
                max_insights=3,
                db=db,
                sse_emit=sink,
                mode="manual",
                version="v2",
            ),
            timeout=10.0,
        )

    # P2: persist_insight_v2 was counted.
    assert result.insights_count == 3, (
        f"expected 3 insights, got {result.insights_count}; "
        f"events={[type(e).__name__ for e in sink.events]}"
    )
    assert result.degraded is False, (result.reason, result)

    # SSE events: 3 InsightStarted, 3 InsightComplete, 1+ SessionComplete(ok).
    started = [e for e in sink.events if isinstance(e, InsightStartedEvent)]
    completes = [e for e in sink.events if isinstance(e, InsightCompleteEvent)]
    session_completes = [
        e for e in sink.events if isinstance(e, SessionCompleteEvent)
    ]
    assert len(started) >= 3
    assert len(completes) >= 3
    assert len(session_completes) >= 1
    assert session_completes[-1].data.budget_status == "ok"


# ---------------------------------------------------------------------------
# (e) V1 demo path still works -- defends the demo soak run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_session_end_to_end_still_works(
    fake_httpx, running_session, session_factory
) -> None:
    """V1 demo regression: same shape as the v2 e2e but with v1 tools
    (emit_chart, persist_insight, emit_citation, finalize_session)."""
    state, _ = fake_httpx

    # 5 v1-style insights; emit_chart per insight; finalize at the end.
    chunks: list[dict] = []
    next_idx = 0
    for i in range(5):
        chunks.append(_delta(content=f"v1 step {i}"))
        chunks.append(_delta(tool_call=_tool_call(
            idx=next_idx,
            call_id=f"call_v1_pi_{i}",
            name="persist_insight",
            args={"insight": {"headline": f"v1 H{i}"}},
        )))
        next_idx += 1
        chunks.append(_delta(tool_call=_tool_call(
            idx=next_idx,
            call_id=f"call_v1_ec_{i}",
            name="emit_chart",
            args={"chart_id": f"c{i}", "chart_type": "bar"},
        )))
        next_idx += 1
        chunks.append(_delta(finish_reason="tool_calls"))

    chunks.append(_delta(tool_call=_tool_call(
        idx=next_idx,
        call_id="call_v1_fin",
        name="finalize_session",
        args={"status": "complete", "token_estimate": 1111},
    )))
    chunks.append(_delta(finish_reason="tool_calls"))
    chunks.append(_delta(finish_reason="stop"))

    state["lines"] = [_sse(c) for c in chunks] + ["data: [DONE]"]

    sink = _SSESink()
    pack = _build_factpack(["r1"])
    async with session_factory() as db:
        result = await asyncio.wait_for(
            run_agentic_synthesis(
                session_id=running_session.id,
                fact_pack=pack,
                max_insights=7,
                db=db,
                sse_emit=sink,
                mode="manual",
                # version omitted -> defaults to v1
            ),
            timeout=10.0,
        )

    assert 5 <= result.insights_count <= 7, (
        f"v1 demo expected 5-7 insights, got {result.insights_count}; "
        "the v1 happy path is the demo soak contract"
    )
    assert result.degraded is False, result
    completes = [e for e in sink.events if isinstance(e, InsightCompleteEvent)]
    assert len(completes) >= 5


# ---------------------------------------------------------------------------
# Round 2 regression tests — cutover fix follow-up
# ---------------------------------------------------------------------------
#
# Background: Round 1 (P1-P5 above) restored the v2 code path but in
# soak the agent was still producing degraded sessions because the LLM
# would call build_chart and then drop persist_insight_v2 from its plan.
# Round 2 adds three guardrails:
#
#   R2-1. synthesis_rules_v2.md was rewritten with a numbered, imperative
#         workflow that mandates persist_insight_v2 as the next call
#         after build_chart.
#   R2-2. persist_insight_v2 logs an "entered" record at the very top
#         of the function body so we can always confirm the agent
#         reached the tool, even when its arguments fail validation.
#   R2-3. _force_finalize_degraded emits a diagnostic WARNING when a
#         v2 session ends with charts but zero persisted insights —
#         the exact "agent skipped persist" pattern Round 1 couldn't
#         distinguish from generic clipping.
# ---------------------------------------------------------------------------


def test_synthesis_rules_v2_prompt_sequences_persist_before_build_chart() -> None:
    """Round 3 invert: the v2 synthesis prompt now sequences
    `persist_insight_v2` BEFORE `build_chart` (insight-first ordering).

    Guards against:
      * a silent prompt revert that puts chart-first ordering back in,
      * prompt drift that drops the "PERSIST FIRST" / "Chart (follow-up)"
        markers,
      * accidental size growth past the 4 KiB ceiling enforced by
        `test_agentic_synthesis_v2.py`.
    """
    import re

    prompt_path = os.path.abspath(
        os.path.join(
            BACKEND_ROOT,
            "agents",
            "insights",
            "prompts",
            "synthesis_rules_v2.md",
        )
    )
    with open(prompt_path, "r", encoding="utf-8") as fh:
        content = fh.read()

    # 1) The v2 persist tool must be named explicitly.
    assert "persist_insight_v2" in content, (
        "synthesis_rules_v2.md no longer mentions persist_insight_v2 — "
        "the agent will not know which sink to use."
    )

    # 2) The Round 3 markers — "PERSIST FIRST" + "Chart (follow-up)" —
    #    must both appear so the insight-first ordering is unambiguous.
    assert "PERSIST FIRST" in content, (
        "synthesis_rules_v2.md is missing the PERSIST FIRST marker that "
        "Round 3 mandates as the lead imperative for the per-insight loop."
    )
    assert "Chart (follow-up)" in content, (
        "synthesis_rules_v2.md is missing the 'Chart (follow-up)' marker "
        "that Round 3 mandates so build_chart is positioned as the "
        "graceful-degradation step after a successful persist."
    )

    # 3) Sequence assertion: in the Workflow section, the FIRST mention
    #    of `persist_insight_v2` MUST precede the FIRST mention of
    #    `build_chart`. Anchor on the Workflow heading so we don't get
    #    fooled by other sections (Hard Rules etc.) that may name both
    #    tools.
    workflow_match = re.search(
        r"##\s+Workflow.*?(?=\n##\s+|\Z)", content, flags=re.DOTALL
    )
    assert workflow_match, "synthesis_rules_v2.md has no '## Workflow' section."
    workflow = workflow_match.group(0)
    pi_pos = workflow.find("persist_insight_v2")
    bc_pos = workflow.find("build_chart")
    assert pi_pos != -1, "Workflow section never names persist_insight_v2."
    assert bc_pos != -1, "Workflow section never names build_chart."
    assert pi_pos < bc_pos, (
        "Round 3 invariant violated: in the Workflow section, "
        "persist_insight_v2 must be mentioned BEFORE build_chart "
        f"(persist@{pi_pos}, build_chart@{bc_pos}). The insight-first "
        "ordering was reverted."
    )

    # 4) Hard size budget — mirrors test_agentic_synthesis_v2.py:157.
    size_bytes = len(content.encode("utf-8"))
    assert size_bytes < 4096, (
        f"synthesis_rules_v2.md grew to {size_bytes}B; the v2 prompt "
        "budget is <4096B."
    )

    # 5) Existing playbook + preflight references must remain.
    assert "AI_INSIGHTS_PLAYBOOK.md" in content, (
        "synthesis_rules_v2.md dropped the AI_INSIGHTS_PLAYBOOK.md reference."
    )
    assert "AI_INSIGHTS_PREFLIGHT_CHECKLIST.md" in content, (
        "synthesis_rules_v2.md dropped the AI_INSIGHTS_PREFLIGHT_CHECKLIST.md reference."
    )


@pytest.mark.asyncio
async def test_persist_insight_v2_logs_entered_on_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R2-2: persist_insight_v2 must log "entered" at the top of the
    function body, BEFORE the db-None guard.

    This guarantees ops can always confirm the agent reached the tool,
    even when the call short-circuits on a missing db handle or a
    later guard. We pass db=None on purpose: the log MUST fire before
    the function returns the ``db_required`` error.
    """
    import logging

    from agents.insights.tools.persist_insight_v2 import persist_insight_v2

    caplog.set_level(logging.INFO, logger="agents.insights.tools.persist_insight_v2")

    out = await persist_insight_v2(
        headline="any",
        body=None,
        confidence="med",
        materiality="med",
        chart_id="c_anything",
        citations=["cit_x"],
        db=None,
        session_id=uuid.uuid4(),
    )

    # The function must still short-circuit on db=None.
    assert out["ok"] is False
    assert out["error"] == "db_required"

    # And the entered-log must have fired before that guard.
    entered = [
        r for r in caplog.records
        if r.getMessage() == "ai_insights.persist_insight_v2.entered"
    ]
    assert entered, (
        "persist_insight_v2 did not emit ai_insights.persist_insight_v2.entered "
        "before the db-None guard — Round 2 contract violated. "
        f"records seen: {[r.getMessage() for r in caplog.records]}"
    )
    assert entered[0].levelno == logging.INFO


@pytest.mark.asyncio
async def test_force_finalize_degraded_logs_v2_skipped_persist_warning(
    session_factory,
    running_session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """R2-3: when a v2 session ends with >=1 agent_chart row but 0
    ai_insight rows, _force_finalize_degraded must log the
    "ai_insights.v2_agent_skipped_persist" WARNING with extras.

    Behavioural contract: this is purely diagnostic. The session must
    still be marked degraded (no behaviour regression).
    """
    import logging

    sid = running_session.id  # running_session has version="v2"

    # Insert one AgentChart row, zero AIInsight rows.
    async with session_factory() as s:
        chart = AgentChart(
            id="c_round2",
            session_id=sid,
            spec={"chart_type": "bar"},
            data_source={"sql": "select 1"},
            row_hash="deadbeef",
        )
        s.add(chart)
        await s.commit()

    caplog.set_level(logging.WARNING, logger="agents.insights.agentic_synthesis")

    async with session_factory() as db:
        await _force_finalize_degraded(
            db,
            session_id=sid,
            reason="r2_agent_skipped_persist",
            insights_count=0,
        )

    # Diagnostic WARNING must have fired with the expected extras.
    skipped = [
        r for r in caplog.records
        if r.getMessage() == "ai_insights.v2_agent_skipped_persist"
    ]
    assert skipped, (
        "v2_agent_skipped_persist diagnostic was not logged; "
        f"records seen: {[r.getMessage() for r in caplog.records]}"
    )
    rec = skipped[0]
    assert rec.levelno == logging.WARNING
    # Extras shape (per agentic_synthesis._force_finalize_degraded R2 patch).
    assert getattr(rec, "session_id", None) == str(sid)
    assert getattr(rec, "build_chart_count", None) == 1
    assert getattr(rec, "persist_v2_count", None) == 0
    assert hasattr(rec, "total_tool_calls")

    # Behaviour must still be: session marked degraded.
    async with session_factory() as s:
        row = (
            (
                await s.execute(
                    select(AISession).where(AISession.id == sid)
                )
            )
            .scalar_one_or_none()
        )
    assert row is not None
    assert row.status == "degraded", (
        "diagnostic patch must not skip the degraded-finalize write"
    )


# ---------------------------------------------------------------------------
# Round 3 — insight-first reorder regressions
# ---------------------------------------------------------------------------
#
# Round 3 inverts the per-insight loop so persist_insight_v2 runs BEFORE
# build_chart. The contract changes:
#
#   * persist_insight_v2(chart_id=None | omitted) must succeed and write
#     ai_insight with chart_id=NULL.
#   * build_chart(insight_id=<uuid>) must SELECT ai_insight, validate
#     session match, and INSERT agent_chart with insight_id populated.
#   * build_chart with a stale/cross-session/unknown insight_id must
#     reject before any agent_chart row is written.
#   * build_chart without insight_id must keep legacy chart-first
#     behaviour for v1-demo and ad-hoc callers (insight_id=NULL on
#     agent_chart).
#   * Tool schemas (V2_TOOL_DEFS) must advertise build_chart.insight_id
#     as an optional field and must NOT require persist_insight_v2.chart_id.
# ---------------------------------------------------------------------------


# --- shared FakeDB helpers (mirror test_persist_insight_v2.py shape) -----


class _R3ScalarsProxy:
    def __init__(self, rows):
        self._rows = list(rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _R3ResultProxy:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return _R3ScalarsProxy(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _R3FakeDB:
    """Reads come from `canned`; writes accumulate on `added` + `updates`.

    Compatible with both persist_insight_v2 (which selects AISession,
    AgentChart, AgentCitation, AIInsight.idx) and build_chart (which
    selects AIInsight by id when insight_id is supplied).
    """

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
                    return _R3ResultProxy(rows)
            return _R3ResultProxy([])
        self.updates.append(stmt)
        return _R3ResultProxy([])


def _r3_session_row(sid: uuid.UUID, status: str = "running"):
    from agents.insights.db.models import AISession

    return AISession(id=sid, status=status, max_insights=7, version="v2")


def _r3_citation_row():
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


def _r3_make_persist_db():
    """FakeDB seeded for a happy persist_insight_v2 call without chart."""
    from agents.insights.db.models import AISession, AgentChart, AgentCitation

    sid = uuid.uuid4()
    db = _R3FakeDB()
    db.set_canned(AISession, [_r3_session_row(sid)])
    # No chart canned: chart_id branch is skipped when caller passes None.
    db.set_canned(AgentChart, [])
    cit = _r3_citation_row()
    db.set_canned(AgentCitation, [cit])
    return db, sid, [str(cit.id)]


def _r3_make_insight_row(insight_id: uuid.UUID, session_id: uuid.UUID):
    from agents.insights.db.models import AIInsight

    return AIInsight(
        id=insight_id,
        session_id=session_id,
        idx=0,
        headline="r3 anchor headline",
        body=None,
        confidence="med",
        materiality="med",
    )


def _r3_make_build_chart_db(insight_session_id: uuid.UUID, insight_id: uuid.UUID):
    """FakeDB seeded for build_chart(insight_id=...) lookups."""
    from agents.insights.db.models import AIInsight

    db = _R3FakeDB()
    row = _r3_make_insight_row(insight_id, insight_session_id)
    db.set_canned(AIInsight, [row])
    return db, row


def _r3_make_build_chart_db_unknown_insight():
    """FakeDB where the AIInsight SELECT returns nothing."""
    from agents.insights.db.models import AIInsight

    db = _R3FakeDB()
    db.set_canned(AIInsight, [])
    return db


def _r3_patch_query_database(monkeypatch, rows, columns):
    """Stub query_database so build_chart tests don't need Postgres."""
    from datetime import datetime as _dt, timezone as _tz

    from agents.insights.tools import build_chart as build_chart_mod
    from agents.insights.tools.sql_gate import validate_sql

    async def _stub(sql, ctx=None, *, max_rows=5000):
        validated = validate_sql(sql, max_rows=max_rows)
        return {
            "rows": rows,
            "columns": columns,
            "row_count": len(rows),
            "executed_sql": validated.normalized_sql,
            "fetched_at": _dt.now(_tz.utc).isoformat(),
            "row_hash": "0" * 64,
            "applied_limit": validated.applied_limit,
            "notes": validated.notes,
            "truncated": False,
        }

    monkeypatch.setattr(build_chart_mod, "query_database", _stub)


def _r3_make_skill_ctx(session_id: uuid.UUID):
    from agents.insights.specs.skill_context import Capabilities, SkillContext

    return SkillContext(
        session_id=str(session_id),
        turn_id="r3-t",
        correlation_id="r3-c",
        model="gpt-4.1",
        budget_seconds_remaining=300.0,
        capabilities=Capabilities(can_query_db=True, can_emit_chart=True),
    )


# --- B1: persist_insight_v2(chart_id=None) succeeds ----------------------


@pytest.mark.asyncio
async def test_persist_insight_v2_optional_chart_id_persists_without_chart() -> None:
    """Round 3 contract: persist_insight_v2 may be called WITHOUT chart_id.
    The insight lands with chart_id=NULL, version='v2', and a follow-up
    build_chart(insight_id=...) is expected to bind the chart later.
    """
    from agents.insights.db.models import AIInsight
    from agents.insights.tools.persist_insight_v2 import persist_insight_v2

    db, sid, citation_ids = _r3_make_persist_db()
    out = await persist_insight_v2(
        headline="round 3 insight-first headline",
        body=None,
        confidence="med",
        materiality="med",
        chart_id=None,  # explicitly None — Round 3 contract
        citations=citation_ids,
        db=db,
        session_id=sid,
    )
    assert out["ok"] is True, out
    assert out["chart_id"] is None
    assert out["citation_count"] == 1
    assert out["version"] == "v2"

    # Exactly one ai_insight row landed; chart_id is NULL.
    insights = [a for a in db.added if isinstance(a, AIInsight)]
    assert len(insights) == 1
    insight = insights[0]
    assert getattr(insight, "version", None) == "v2"
    assert getattr(insight, "chart_id", "missing") is None


# --- B2: build_chart(insight_id=...) binds FK on session match -----------


@pytest.mark.asyncio
async def test_build_chart_with_insight_id_binds_fk_when_session_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 3 happy path for the chart-bind edge: when build_chart is
    called with a valid insight_id whose ai_insight.session_id matches
    ctx.session_id, the resulting agent_chart row carries
    `insight_id = <that uuid>` (not NULL).
    """
    from agents.insights.db.models import AgentChart
    from agents.insights.tools.build_chart import build_chart

    sid = uuid.uuid4()
    iid = uuid.uuid4()
    db, _ = _r3_make_build_chart_db(insight_session_id=sid, insight_id=iid)
    _r3_patch_query_database(
        monkeypatch,
        [{"region": "us-east", "gw": 1.2}, {"region": "us-west", "gw": 0.9}],
        ["region", "gw"],
    )

    ctx = _r3_make_skill_ctx(sid)
    out = await build_chart(
        sql="SELECT region, gw FROM v_power",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="bar",
        title="Power by region (R3)",
        insight_id=str(iid),
        ctx=ctx,
        db=db,
    )
    assert out["ok"] is True, out
    assert out["chart_id"].startswith("c_")
    assert out["insight_id"] == str(iid)

    chart_rows = [a for a in db.added if isinstance(a, AgentChart)]
    assert len(chart_rows) == 1, "exactly one agent_chart row must be persisted"
    persisted = chart_rows[0]
    assert persisted.id == out["chart_id"]
    # insight_id is the bound UUID, not None.
    assert persisted.insight_id is not None
    assert str(persisted.insight_id) == str(iid)


# --- B3: build_chart rejects insight_id from a different session ---------


@pytest.mark.asyncio
async def test_build_chart_rejects_insight_id_for_other_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cross-session insight_id must be hard-rejected with
    `insight_session_mismatch` and NO agent_chart row may be written.
    """
    from agents.insights.db.models import AgentChart
    from agents.insights.tools.build_chart import build_chart

    other_sid = uuid.uuid4()  # the insight lives here
    ctx_sid = uuid.uuid4()    # the chart call runs here
    iid = uuid.uuid4()
    db, _ = _r3_make_build_chart_db(insight_session_id=other_sid, insight_id=iid)
    _r3_patch_query_database(
        monkeypatch,
        [{"region": "us-east", "gw": 1.2}],
        ["region", "gw"],
    )

    ctx = _r3_make_skill_ctx(ctx_sid)
    out = await build_chart(
        sql="SELECT region, gw FROM v_power",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="bar",
        title="Cross-session leak attempt",
        insight_id=str(iid),
        ctx=ctx,
        db=db,
    )
    assert out["ok"] is False
    assert out["error"] == "insight_session_mismatch", out
    chart_rows = [a for a in db.added if isinstance(a, AgentChart)]
    assert chart_rows == [], (
        "agent_chart row must NOT be written when insight_session_mismatch fires"
    )


# --- B4: build_chart rejects unknown insight_id --------------------------


@pytest.mark.asyncio
async def test_build_chart_rejects_unknown_insight_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An insight_id that does not resolve to any ai_insight row must be
    rejected with `insight_not_found`. No agent_chart row must land.
    """
    from agents.insights.db.models import AgentChart
    from agents.insights.tools.build_chart import build_chart

    sid = uuid.uuid4()
    db = _r3_make_build_chart_db_unknown_insight()
    _r3_patch_query_database(
        monkeypatch,
        [{"region": "us-east", "gw": 1.2}],
        ["region", "gw"],
    )

    ctx = _r3_make_skill_ctx(sid)
    out = await build_chart(
        sql="SELECT region, gw FROM v_power",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="bar",
        title="Unknown insight_id",
        insight_id="00000000-0000-0000-0000-000000000000",
        ctx=ctx,
        db=db,
    )
    assert out["ok"] is False
    assert out["error"] == "insight_not_found", out
    chart_rows = [a for a in db.added if isinstance(a, AgentChart)]
    assert chart_rows == [], (
        "agent_chart row must NOT be written when insight_not_found fires"
    )


# --- B5: build_chart without insight_id keeps legacy NULL FK --------------


@pytest.mark.asyncio
async def test_build_chart_without_insight_id_keeps_legacy_null_fk_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard for legacy chart-first callers: when build_chart
    is called WITHOUT insight_id (or with None), the agent_chart row
    must land with insight_id=NULL — byte-equivalent to Round 2.
    """
    from agents.insights.db.models import AgentChart
    from agents.insights.tools.build_chart import build_chart

    sid = uuid.uuid4()
    db = _R3FakeDB()
    _r3_patch_query_database(
        monkeypatch,
        [{"region": "us-east", "gw": 1.2}, {"region": "us-west", "gw": 0.9}],
        ["region", "gw"],
    )

    ctx = _r3_make_skill_ctx(sid)
    out = await build_chart(
        sql="SELECT region, gw FROM v_power",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="bar",
        title="Legacy chart-first",
        ctx=ctx,
        db=db,
        # insight_id intentionally omitted
    )
    assert out["ok"] is True, out
    assert out.get("insight_id") is None

    chart_rows = [a for a in db.added if isinstance(a, AgentChart)]
    assert len(chart_rows) == 1
    assert chart_rows[0].insight_id is None, (
        "legacy chart-first path must keep agent_chart.insight_id=NULL"
    )


# --- B6: registry advertises build_chart.insight_id as optional ----------


def test_registry_build_chart_schema_advertises_insight_id() -> None:
    """The OpenAI tool schema for build_chart must include `insight_id`
    in `properties` and must NOT promote it to `required` — Round 3
    insight-first ordering keeps insight_id optional so legacy callers
    keep working.
    """
    from agents.insights.tools.registry import V2_TOOL_DEFS

    spec = next(
        t for t in V2_TOOL_DEFS if t["function"]["name"] == "build_chart"
    )
    params = spec["function"]["parameters"]
    assert "insight_id" in params["properties"], (
        "build_chart schema must advertise insight_id in properties"
    )
    assert "insight_id" not in params["required"], (
        "build_chart insight_id must remain optional, not required"
    )
    # The four required fields are unchanged from pre-Round-3.
    assert params["required"] == ["sql", "encoding", "chart_type", "title"]


# --- B7: registry persist_insight_v2 chart_id no longer required ---------


def test_registry_persist_insight_v2_chart_id_no_longer_required() -> None:
    """The OpenAI tool schema for persist_insight_v2 must NOT list
    `chart_id` in `required` (Round 3 contract). Citations stay
    required with minItems=1.
    """
    from agents.insights.tools.registry import V2_TOOL_DEFS

    spec = next(
        t for t in V2_TOOL_DEFS if t["function"]["name"] == "persist_insight_v2"
    )
    params = spec["function"]["parameters"]
    assert "chart_id" not in params["required"], (
        "Round 3 invariant violated: persist_insight_v2.chart_id is back "
        "in the required list."
    )
    assert set(params["required"]) == {
        "headline",
        "confidence",
        "materiality",
        "citations",
    }
    # chart_id is still accepted optionally for legacy chart-first callers.
    assert "chart_id" in params["properties"]
    assert params["properties"]["citations"]["minItems"] == 1


# ---------------------------------------------------------------------------
# Round 3 follow-up regressions (insight-first reorder)
# ---------------------------------------------------------------------------
#
# These tests pin the explicit Round-3 contract changes:
#
#   R3-A. persist_insight_v2 must accept chart_id=None (insight-first
#         path) and return a dict with chart_id=None, version="v2".
#   R3-B. persist_insight_v2 must STILL accept a populated chart_id so
#         legacy chart-first callers / the dispatch fallback keep
#         working. Chart resolution + chart-bind must run.
#   R3-C. build_chart(insight_id=<uuid>) must FK-bind the new
#         agent_chart row to that insight at INSERT time.
#   R3-D. build_chart with an unknown insight_id must reject with
#         `insight_not_found` and write nothing.
#   R3-E. build_chart with a cross-session insight_id must reject with
#         `insight_session_mismatch` and write nothing.
#   R3-F. The synthesis_rules_v2.md prompt must sequence persist BEFORE
#         build_chart; the chart-first phrasing must be gone; v1 tool
#         names must remain in the "Do NOT call" list.
#
# These tests reuse the _R3FakeDB / _r3_make_* helpers defined above to
# stay in lock-step with the existing Round-3 fixtures.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_insight_v2_accepts_no_chart_id() -> None:
    """R3-A: persist_insight_v2(chart_id=None) is the new happy path.

    When the agent follows the insight-first prompt, it persists with
    chart_id=None and binds a chart only as a follow-up. The tool must
    return ok=True with chart_id None and version='v2'; exactly one
    AIInsight row must land via db.add() with chart_id IS NULL.
    """
    from agents.insights.db.models import AIInsight
    from agents.insights.tools.persist_insight_v2 import persist_insight_v2

    db, sid, citation_ids = _r3_make_persist_db()
    out = await persist_insight_v2(
        headline="OCI east-coast power gap widens vs Azure",
        body=None,
        confidence="high",
        materiality="high",
        chart_id=None,
        citations=citation_ids,
        db=db,
        session_id=sid,
    )

    assert out["ok"] is True, out
    assert out["chart_id"] is None
    assert out["version"] == "v2"
    assert out["citation_count"] == 1
    # Insight insert path executed exactly once.
    insights = [a for a in db.added if isinstance(a, AIInsight)]
    assert len(insights) == 1, "ai_insight insert path must run exactly once"
    assert getattr(insights[0], "chart_id", "missing") is None, (
        "AIInsight row must land with chart_id IS NULL when caller "
        "passed chart_id=None"
    )


@pytest.mark.asyncio
async def test_persist_insight_v2_still_accepts_chart_id_when_supplied() -> None:
    """R3-B: legacy chart-first callers MUST keep working.

    Round 3 made chart_id optional, but a populated chart_id must still
    drive the chart-resolution + chart-bind path. We seed a matching
    agent_chart row in the FakeDB and assert the returned dict echoes
    the chart_id back. We also assert that an UPDATE statement (the
    chart-bind) was issued via db.execute, captured on the
    `_R3FakeDB.updates` list.
    """
    from agents.insights.db.models import (
        AgentChart,
        AIInsight,
        AISession,
        AgentCitation,
    )
    from agents.insights.tools.persist_insight_v2 import persist_insight_v2

    sid = uuid.uuid4()
    chart_id = "c_legacy_first"
    db = _R3FakeDB()
    db.set_canned(AISession, [_r3_session_row(sid)])
    chart_row = AgentChart(
        id=chart_id,
        session_id=sid,
        spec={"chart_type": "bar"},
        data_source={"sql": "select 1"},
        row_hash="cafebabe",
    )
    db.set_canned(AgentChart, [chart_row])
    cit = _r3_citation_row()
    db.set_canned(AgentCitation, [cit])

    out = await persist_insight_v2(
        headline="legacy chart-first headline",
        body=None,
        confidence="med",
        materiality="med",
        chart_id=chart_id,
        citations=[str(cit.id)],
        db=db,
        session_id=sid,
    )

    assert out["ok"] is True, out
    assert out["chart_id"] == chart_id, (
        "chart_id must be echoed back when supplied -- legacy path"
    )
    assert out["version"] == "v2"
    insights = [a for a in db.added if isinstance(a, AIInsight)]
    assert len(insights) == 1
    assert getattr(insights[0], "chart_id", None) == chart_id
    # Chart-bind UPDATE was issued (recorded on the updates queue).
    assert db.updates, (
        "chart-resolution + chart-bind UPDATE was not issued -- "
        "legacy chart-first path regressed"
    )


@pytest.mark.asyncio
async def test_build_chart_binds_to_insight_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R3-C: build_chart(insight_id=<uuid>) FK-binds at INSERT.

    The AgentChart row passed to db.add() must carry `insight_id`
    populated to the supplied uuid -- not None.
    """
    from agents.insights.db.models import AgentChart
    from agents.insights.tools.build_chart import build_chart

    sid = uuid.uuid4()
    iid = uuid.uuid4()
    db, _ = _r3_make_build_chart_db(insight_session_id=sid, insight_id=iid)
    _r3_patch_query_database(
        monkeypatch,
        [{"region": "us-east", "gw": 2.4}, {"region": "us-west", "gw": 1.1}],
        ["region", "gw"],
    )

    ctx = _r3_make_skill_ctx(sid)
    out = await build_chart(
        sql="SELECT region, gw FROM v_power",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="bar",
        title="R3-C bind",
        insight_id=str(iid),
        ctx=ctx,
        db=db,
    )

    assert out["ok"] is True, out
    assert out["insight_id"] == str(iid)
    chart_rows = [a for a in db.added if isinstance(a, AgentChart)]
    assert len(chart_rows) == 1
    recorded_row = chart_rows[0]
    # Critical assertion: the FK was set at INSERT time, not patched later.
    assert recorded_row.insight_id == iid, (
        f"AgentChart.insight_id should be {iid} but was "
        f"{recorded_row.insight_id!r} -- Round 3 FK-at-insert regressed"
    )


@pytest.mark.asyncio
async def test_build_chart_rejects_unknown_insight_id_round3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R3-D: insight_id that resolves to no row -> insight_not_found.

    Distinct from the existing
    `test_build_chart_rejects_unknown_insight_id` test by also
    asserting the canonical zero-uuid is the unknown id, matching
    the request spec.
    """
    from agents.insights.db.models import AgentChart
    from agents.insights.tools.build_chart import build_chart

    sid = uuid.uuid4()
    db = _r3_make_build_chart_db_unknown_insight()
    _r3_patch_query_database(
        monkeypatch,
        [{"region": "us-east", "gw": 1.2}],
        ["region", "gw"],
    )

    ctx = _r3_make_skill_ctx(sid)
    out = await build_chart(
        sql="SELECT region, gw FROM v_power",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="bar",
        title="R3-D unknown",
        insight_id="00000000-0000-0000-0000-000000000000",
        ctx=ctx,
        db=db,
    )

    assert out["ok"] is False
    assert out["error"] == "insight_not_found", out
    chart_rows = [a for a in db.added if isinstance(a, AgentChart)]
    assert chart_rows == [], (
        "no agent_chart row may land when insight_not_found fires"
    )


@pytest.mark.asyncio
async def test_build_chart_rejects_cross_session_insight_id_round3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R3-E: insight_id from a different session -> insight_session_mismatch.

    Mirrors the existing R3-B3 test but is named explicitly per the
    Round-3 follow-up request. Also asserts no chart row was written.
    """
    from agents.insights.db.models import AgentChart
    from agents.insights.tools.build_chart import build_chart

    insight_sid = uuid.uuid4()  # insight lives here
    ctx_sid = uuid.uuid4()      # build_chart called here
    iid = uuid.uuid4()
    db, _ = _r3_make_build_chart_db(
        insight_session_id=insight_sid, insight_id=iid
    )
    _r3_patch_query_database(
        monkeypatch,
        [{"region": "us-east", "gw": 1.2}],
        ["region", "gw"],
    )

    ctx = _r3_make_skill_ctx(ctx_sid)
    out = await build_chart(
        sql="SELECT region, gw FROM v_power",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="bar",
        title="R3-E cross-session",
        insight_id=str(iid),
        ctx=ctx,
        db=db,
    )

    assert out["ok"] is False
    assert out["error"] == "insight_session_mismatch", out
    chart_rows = [a for a in db.added if isinstance(a, AgentChart)]
    assert chart_rows == [], (
        "no agent_chart row may land when insight_session_mismatch fires"
    )


def test_synthesis_rules_v2_sequences_persist_before_chart() -> None:
    """R3-F: prompt-level invariants for the insight-first reorder.

    (a) "PERSIST FIRST" appears BEFORE "build_chart" in the Workflow
        section.
    (b) The old chart-first phrasing "PERSIST IMMEDIATELY" no longer
        appears anywhere in the file.
    (c) v1 tool names persist_insight, emit_chart, get_chart_data are
        still listed in the "Do NOT call" block so the agent does not
        regress to v1.
    """
    prompt_path = os.path.abspath(
        os.path.join(
            BACKEND_ROOT,
            "agents",
            "insights",
            "prompts",
            "synthesis_rules_v2.md",
        )
    )
    with open(prompt_path, "r", encoding="utf-8") as fh:
        content = fh.read()

    # (a) PERSIST FIRST precedes build_chart in the Workflow section.
    import re

    workflow_match = re.search(
        r"##\s+Workflow.*?(?=\n##\s+|\Z)", content, flags=re.DOTALL
    )
    assert workflow_match, "synthesis_rules_v2.md has no '## Workflow' section."
    workflow = workflow_match.group(0)
    persist_first_pos = workflow.find("PERSIST FIRST")
    build_chart_pos = workflow.find("build_chart")
    assert persist_first_pos != -1, (
        "Workflow section is missing the 'PERSIST FIRST' marker"
    )
    assert build_chart_pos != -1, (
        "Workflow section is missing a 'build_chart' reference"
    )
    assert persist_first_pos < build_chart_pos, (
        f"R3-F invariant violated: 'PERSIST FIRST' (@{persist_first_pos}) "
        f"must precede 'build_chart' (@{build_chart_pos}) in Workflow"
    )

    # (b) The chart-first marker must be gone.
    assert "PERSIST IMMEDIATELY" not in content, (
        "synthesis_rules_v2.md still contains the chart-first phrasing "
        "'PERSIST IMMEDIATELY' -- the Round 3 reorder was reverted"
    )

    # (c) v1 tool names remain in the do-not-call list.
    do_not_call_match = re.search(
        r"Do NOT call:.*?(?=\n\s*-\s|\n##\s|\Z)",
        content,
        flags=re.DOTALL,
    )
    assert do_not_call_match, (
        "synthesis_rules_v2.md is missing the 'Do NOT call:' list"
    )
    do_not_call_block = do_not_call_match.group(0)
    for v1_name in ("persist_insight", "emit_chart", "get_chart_data"):
        assert v1_name in do_not_call_block, (
            f"v1 tool {v1_name!r} dropped from the 'Do NOT call' list "
            "-- the agent could regress to v1 surface"
        )
