"""Unit tests for `agents.insights.agentic_synthesis.run_agentic_synthesis`.

Strategy
--------
We mock at the `httpx.AsyncClient` boundary inside `openclaw.forwarder`
(the module that exposes `_drive_openclaw_stream`). This mirrors the
shim pattern in `test_openclaw_forwarder.py` so the synthesis driver
sees a fake gateway whose canned SSE bytes drive the translator.

What this file covers:
  1. Happy path: 3 reasoning deltas + 3 persist_insight + emit_chart +
     finalize_session(complete) + 3 AIInsight rows in the DB ->
     insights_count=3, degraded=False (the driver reads the DB count,
     since OpenClaw runs the tool loop internally and tool-call
     deltas don't necessarily reach the translator).
  2. Cap exceeded — tool_calls: stream emits 31 tool-call completions
     with no insight rows in the DB -> degraded=True (insights_count
     == 0), reason="tool_cap"; ai_session marked 'failed'.
  3. Cap exceeded — wall_clock: forced wall-clock breach -> degraded,
     no `task.cancel()` involved.
  4. Stop without finalize and zero persisted insights -> ai_session
     marked 'failed' (no longer 'degraded' — that v1 partial-success
     status was removed in v2).
  5. session_key derivation: 3 parametrized cases (manual,
     manual+cron_run_date, scheduled).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import types
import uuid
from datetime import date, datetime
from typing import Any, AsyncIterator, Optional

import pytest
import pytest_asyncio

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))
for p in (BACKEND_ROOT, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------------------------------------------------------------------------
# Pre-import shims (mirrors test_openclaw_forwarder.py / test_mcp_server.py)
# ---------------------------------------------------------------------------
import agents  # noqa: E402,F401
import agents.insights  # noqa: E402,F401

# Only install a fake `agents.insights.tools.sql_gate` if the real one
# cannot be imported (older sqlglot pin). Unconditionally installing the
# stub poisons later tests that exercise the real validator (e.g.
# tests/test_insights_sql_gate.py).
try:  # pragma: no cover — exercised on environments with real sqlglot
    import agents.insights.tools.sql_gate as _real_sql_gate  # noqa: F401
except Exception:  # noqa: BLE001
    if "agents.insights.tools" not in sys.modules:
        _tools_pkg = types.ModuleType("agents.insights.tools")
        _tools_pkg.__path__ = [
            os.path.join(BACKEND_ROOT, "agents", "insights", "tools")
        ]
        sys.modules["agents.insights.tools"] = _tools_pkg

    if "agents.insights.tools.sql_gate" not in sys.modules:
        from pydantic import BaseModel as _BM

        _sg = types.ModuleType("agents.insights.tools.sql_gate")

        class SqlGateError(Exception):
            def __init__(self, code: str = "sql_gate_blocked", *args, **kwargs) -> None:
                super().__init__(*args)
                self.code = code

        class ValidatedSQL(_BM):
            sql: str
            notes: list[str] = []

        def validate_sql(sql: str, **_kw):
            return ValidatedSQL(sql=sql)

        _sg.SqlGateError = SqlGateError
        _sg.ValidatedSQL = ValidatedSQL
        _sg.validate_sql = validate_sql
        _sg.DEFAULT_ROW_LIMIT = 10_000
        sys.modules["agents.insights.tools.sql_gate"] = _sg

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

import agents.insights.db.models as ai_models  # noqa: E402,F401  (registers tables)
from agents.insights.db.models import (  # noqa: E402
    AgentChart,
    AgentMessage,
    AIInsight,
    AISession,
    InsightThread,
)
from agents.insights.specs.sse_events import (  # noqa: E402
    InsightCompleteEvent,
    InsightStartedEvent,
    ReasoningStepEvent,
    SessionCompleteEvent,
    ToolCallStartedEvent,
)

import openclaw.forwarder as fwd_mod  # noqa: E402
from agents.insights.agentic_synthesis import (  # noqa: E402
    SynthesisResult,
    _build_session_key,
    run_agentic_synthesis,
)


# ---------------------------------------------------------------------------
# DB fixtures (in-memory SQLite, mirrors test_openclaw_forwarder.py)
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
# Canned SSE chunk builder + fake httpx.AsyncClient
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


def _persist_insight_call(*, idx: int, call_id: str, headline: str,
                          row_ids: Optional[list[str]] = None) -> dict:
    args_obj: dict[str, Any] = {
        "session_id": "ignored-by-translator",
        "insight": {
            "headline": headline,
            "body": f"body for {headline}",
            "confidence_signal": "strong",
            "materiality": "high",
        },
    }
    if row_ids is not None:
        args_obj["supporting_row_ids"] = row_ids
    return {
        "index": idx,
        "id": call_id,
        "function": {
            "name": "persist_insight",
            "arguments": json.dumps(args_obj),
        },
    }


def _emit_chart_call(*, idx: int, call_id: str) -> dict:
    args_obj = {"chart_id": f"c_{call_id}", "chart_type": "bar"}
    return {
        "index": idx,
        "id": call_id,
        "function": {
            "name": "emit_chart",
            "arguments": json.dumps(args_obj),
        },
    }


def _finalize_call(*, idx: int, call_id: str = "call_fin",
                   status: str = "complete") -> dict:
    args_obj = {"status": status, "token_estimate": 9999}
    return {
        "index": idx,
        "id": call_id,
        "function": {
            "name": "finalize_session",
            "arguments": json.dumps(args_obj),
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
    """Yield a (state, captured) tuple. Patches `httpx` only inside the
    forwarder module so ASGITransport et al. keep their real httpx.
    """
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


# ---------------------------------------------------------------------------
# SSE-event sink
# ---------------------------------------------------------------------------


class _SSESink:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def __call__(self, evt: Any) -> None:
        self.events.append(evt)


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_three_insights_complete(
    fake_httpx, running_session, session_factory
) -> None:
    state, _captured = fake_httpx

    # Build a canned stream that:
    #  - emits 3 reasoning content deltas
    #  - calls persist_insight 3x (each followed by emit_chart)
    #  - calls finalize_session(status=complete)
    chunks: list[dict] = []
    for i in range(3):
        chunks.append(_delta(content=f"thinking {i}"))
        chunks.append(_delta(tool_call=_persist_insight_call(
            idx=2 * i, call_id=f"call_ins_{i}", headline=f"H{i}",
            row_ids=["r1"]
        )))
        chunks.append(_delta(tool_call=_emit_chart_call(
            idx=2 * i + 1, call_id=f"call_chart_{i}"
        )))
        chunks.append(_delta(finish_reason="tool_calls"))
    # Final turn -> finalize_session
    chunks.append(_delta(tool_call=_finalize_call(idx=99)))
    chunks.append(_delta(finish_reason="tool_calls"))
    chunks.append(_delta(finish_reason="stop"))
    state["lines"] = [_sse(c) for c in chunks] + ["data: [DONE]"]

    sink = _SSESink()
    # Production: the agent calls persist_insight via MCP, which writes
    # AIInsight rows. The mocked OpenClaw stream doesn't actually
    # exercise the MCP path, so seed the DB to mirror what would have
    # happened — the driver's terminal status is now derived from this
    # row count, not from streaming-side accumulator state.
    async with session_factory() as s:
        for i in range(3):
            s.add(AIInsight(
                session_id=running_session.id,
                idx=i,
                headline=f"H{i}",
                body=f"body for H{i}",
                confidence="strong",
                materiality="high",
            ))
        await s.commit()

    async with session_factory() as db:
        result: SynthesisResult = await run_agentic_synthesis(
            session_id=running_session.id,
            max_insights=5,
            db=db,
            sse_emit=sink,
            mode="manual",
        )

    assert isinstance(result, SynthesisResult)
    assert result.insights_count == 3, sink.events
    assert result.degraded is False, (result.reason, sink.events)

    started = [e for e in sink.events if isinstance(e, InsightStartedEvent)]
    completes = [e for e in sink.events if isinstance(e, InsightCompleteEvent)]
    session_completes = [
        e for e in sink.events if isinstance(e, SessionCompleteEvent)
    ]
    assert len(started) >= 3, [type(e).__name__ for e in sink.events]
    assert len(completes) >= 3, [type(e).__name__ for e in sink.events]
    assert len(session_completes) >= 1
    # Session complete should be in the OK budget bucket on a clean finalize.
    assert session_completes[-1].data.budget_status == "ok"

    # Driver writes the terminal status to the DB based on the row count.
    async with session_factory() as s:
        row = (
            await s.execute(
                select(AISession).where(AISession.id == running_session.id)
            )
        ).scalar_one_or_none()
    assert row is not None
    assert row.status == "complete", row.status
    assert row.insights_emitted == 3


# ---------------------------------------------------------------------------
# 2. Cap exceeded — tool_calls. Drive 31 tool_call completions; the driver
#    breaks out cooperatively after the 30-cap (set in agentic_synthesis as
#    cap_tool_calls=30). Result must be degraded with reason in
#    {"tool_cap","cap_tool_calls"} (the implementation slug we observe).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_call_cap_trips_failed_when_no_insights(
    fake_httpx, running_session, session_factory
) -> None:
    state, _ = fake_httpx
    # Build 31 distinct tool_call deltas, ALL inside a single model turn
    # (one finish_reason="tool_calls" frame closes them en masse). This
    # keeps the turn counter at 1 so we observe `tool_cap` (not
    # `turn_cap`).
    chunks: list[dict] = []
    for i in range(31):
        chunks.append(_delta(tool_call={
            "index": i,
            "id": f"call_{i}",
            "function": {
                "name": "web_search",
                "arguments": '{"query":"q"}',
            },
        }))
    chunks.append(_delta(finish_reason="tool_calls"))
    # Trailing terminator -- driver should never reach this if cap fires.
    chunks.append(_delta(finish_reason="stop"))
    state["lines"] = [_sse(c) for c in chunks] + ["data: [DONE]"]

    sink = _SSESink()
    async with session_factory() as db:
        result = await run_agentic_synthesis(
            session_id=running_session.id,
            max_insights=5,
            db=db,
            sse_emit=sink,
            mode="manual",
        )

    # Cap-trip with zero persisted insights -> degraded (insights==0)
    # and terminal status 'failed'. The reason slug surfaces the cap.
    assert result.degraded is True, result
    assert result.insights_count == 0, result
    assert result.reason in ("tool_cap", "cap_tool_calls"), result.reason

    async with session_factory() as s:
        row = (
            (
                await s.execute(
                    select(AISession).where(AISession.id == running_session.id)
                )
            )
            .scalar_one_or_none()
        )
    assert row is not None
    assert row.status == "failed", row.status
    assert row.budget_status == "clipped", row.budget_status


# ---------------------------------------------------------------------------
# 3. Cap exceeded — wall_clock. We force `time.monotonic` to advance well
#    past the wall-cap inside the driver. Drive a long stream so the cap
#    check fires before the stream ends. Verify NO task.cancel() was used.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wall_clock_cap_trips_failed_without_cancel(
    fake_httpx, running_session, session_factory, monkeypatch
) -> None:
    state, _ = fake_httpx
    # 60 web_search frames; driver should bail well before consuming them.
    chunks: list[dict] = []
    for i in range(60):
        chunks.append(_delta(tool_call={
            "index": i,
            "id": f"call_{i}",
            "function": {
                "name": "web_search",
                "arguments": '{"query":"q"}',
            },
        }))
        chunks.append(_delta(finish_reason="tool_calls"))
    state["lines"] = [_sse(c) for c in chunks] + ["data: [DONE]"]

    # Replace the *forwarder module's* `time` reference with a
    # SimpleNamespace whose `monotonic` is patched, leaving the real
    # `time` module (and thus asyncio's loop clock) untouched.
    import time as _real_time
    started_at = _real_time.monotonic()
    state_t = {"calls": 0}

    def _fake_monotonic() -> float:
        state_t["calls"] += 1
        # First call (driver's `started = time.monotonic()`) returns real.
        # Subsequent calls (cap-check loop) return >> 600s past start.
        if state_t["calls"] <= 1:
            return started_at
        return started_at + 1_000.0

    fake_time = types.SimpleNamespace(monotonic=_fake_monotonic)
    monkeypatch.setattr(fwd_mod, "time", fake_time)

    # Cooperative-break check: install an asyncio.wait_for shim that
    # records whenever a TimeoutError-driven inner-cancel happens.
    # If the driver's cap logic works, the break-out is purely
    # cooperative and the outer wait_for never fires its cancel path.
    timeout_fired = {"hit": False}
    real_wait_for = asyncio.wait_for

    async def _spy_wait_for(coro, timeout):
        try:
            return await real_wait_for(coro, timeout)
        except asyncio.TimeoutError:
            timeout_fired["hit"] = True
            raise

    monkeypatch.setattr(asyncio, "wait_for", _spy_wait_for)

    sink = _SSESink()
    async with session_factory() as db:
        result = await run_agentic_synthesis(
            session_id=running_session.id,
            max_insights=5,
            db=db,
            sse_emit=sink,
            mode="manual",
        )

    assert result.degraded is True, result
    assert result.insights_count == 0, result
    assert result.reason in ("wall_clock", "cap_wall_clock"), result.reason

    async with session_factory() as s:
        row = (
            await s.execute(
                select(AISession).where(AISession.id == running_session.id)
            )
        ).scalar_one_or_none()
    assert row is not None
    assert row.status == "failed", row.status

    # The driver's wall_clock cap fires cooperatively; the outer
    # asyncio.wait_for(timeout=620) safety belt should NEVER trip
    # because the inner driver returns first. If it did trip, the
    # implementation would have leaned on TimeoutError-driven
    # cancellation (httpx issues #1461 / #2437).
    assert timeout_fired["hit"] is False, (
        "driver must break cooperatively; outer wait_for must not "
        "raise TimeoutError (httpx issues #1461 / #2437)"
    )


# ---------------------------------------------------------------------------
# 4. Stop without finalize and zero insights -> ai_session marked 'failed'.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_without_finalize_marks_session_failed(
    fake_httpx, running_session, session_factory
) -> None:
    state, _ = fake_httpx
    # Stream emits some content + finish_reason=stop (no finalize_session).
    chunks: list[dict] = [
        _delta(content="thinking..."),
        _delta(finish_reason="stop"),
    ]
    state["lines"] = [_sse(c) for c in chunks] + ["data: [DONE]"]

    sink = _SSESink()
    async with session_factory() as db:
        result = await run_agentic_synthesis(
            session_id=running_session.id,
            max_insights=5,
            db=db,
            sse_emit=sink,
            mode="manual",
        )

    assert result.degraded is True
    assert result.insights_count == 0
    session_completes = [
        e for e in sink.events if isinstance(e, SessionCompleteEvent)
    ]
    assert session_completes, [type(e).__name__ for e in sink.events]

    async with session_factory() as s:
        row = (
            await s.execute(
                select(AISession).where(AISession.id == running_session.id)
            )
        ).scalar_one_or_none()
    assert row is not None
    assert row.status == "failed", row.status


# ---------------------------------------------------------------------------
# 5. session_key derivation — direct test of `_build_session_key`.
#    Manual instructions list exactly the three branches.
# ---------------------------------------------------------------------------


def test_session_key_manual_no_cron_date() -> None:
    sid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    key = _build_session_key(mode="manual", cron_run_date=None, session_id=sid)
    assert key.startswith("manual-")
    assert str(sid) in key


def test_session_key_manual_with_cron_run_date() -> None:
    sid = uuid.UUID("22222222-2222-2222-2222-222222222222")
    key = _build_session_key(
        mode="manual", cron_run_date=date(2026, 5, 6), session_id=sid
    )
    assert key == "daily-synthesis-20260506"


def test_session_key_scheduled_with_cron_run_date() -> None:
    sid = uuid.UUID("33333333-3333-3333-3333-333333333333")
    key = _build_session_key(
        mode="scheduled", cron_run_date=date(2026, 5, 6), session_id=sid
    )
    assert key == "daily-synthesis-20260506-scheduled"


@pytest.mark.asyncio
async def test_session_key_header_on_request(
    fake_httpx, running_session, session_factory
) -> None:
    """End-to-end: the captured x-openclaw-session-key matches
    `_build_session_key(mode='manual', cron_run_date=None, ...)`.
    """
    state, captured = fake_httpx
    # Minimal stream: just stop. Driver still sends the request.
    state["lines"] = [_sse(_delta(finish_reason="stop")), "data: [DONE]"]

    sink = _SSESink()
    async with session_factory() as db:
        await run_agentic_synthesis(
            session_id=running_session.id,
            max_insights=5,
            db=db,
            sse_emit=sink,
            mode="manual",
        )

    expected = f"manual-{running_session.id}"
    assert captured.headers.get("x-openclaw-session-key") == expected


