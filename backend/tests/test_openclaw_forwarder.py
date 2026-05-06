"""Tests for the OpenClaw forwarder lane of the chat endpoint.

Coverage map (PRD 11a R8, ARCH 11b §5, ARCH 15 cleanup):
  1. POST /chat dials OpenClaw, translates the canned SSE stream, and
     yields our event taxonomy (assistant_message_token,
     tool_call_started, tool_call_complete, message_complete) plus
     persists user + assistant `agent_message` rows with monotonic seq.
  2. Forwarder uses correct headers (Bearer + x-openclaw-session-key).
  3. OpenClaw 5xx -> the forwarder emits an `error` SSE event rather
     than 500'ing to the browser.

The legacy in-process ToolLoopDriver lane and its `OPENCLAW_ENABLED`
rollback flag were removed in Phase 5-followup (ARCH 15). The previous
"flag=0 routes to legacy" test was deleted at the same time.

Implementation notes
--------------------
- We DO NOT spin up the OpenClaw container. The whole external HTTP
  surface is faked by patching `httpx.AsyncClient` on the module under
  test (`backend.openclaw.forwarder`).
- We reuse the SQLite-backed app harness pattern from
  `tests/test_v2_chat_isolation.py` so chat persistence can be observed
  without Postgres.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import types
import uuid
from typing import Any, AsyncIterator

import pytest
import pytest_asyncio

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))
for p in (BACKEND_ROOT, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------------------------------------------------------------------------
# Reuse the SQLite shim + sql_gate stub from test_v2_chat_isolation.
# We must do this before importing routers.insights so its lazy paths
# work against in-memory aiosqlite.
# ---------------------------------------------------------------------------
import agents  # noqa: E402,F401
import agents.insights  # noqa: E402,F401

if "agents.insights.tools" not in sys.modules:
    _tools_pkg = types.ModuleType("agents.insights.tools")
    _tools_pkg.__path__ = [os.path.join(BACKEND_ROOT, "agents", "insights", "tools")]
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
    AgentCitation,
    AgentMessage,
    AIInsight,
    AISession,
    InsightThread,
)

import db.session as db_session_mod  # noqa: E402
import routers.insights as insights_router  # noqa: E402
from db.session import get_db  # noqa: E402
from main import app  # noqa: E402

import openclaw.forwarder as fwd_mod  # noqa: E402
from config import settings  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures (mirroring test_v2_chat_isolation.py)
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
        AgentCitation.__table__,
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
async def seeded_insight(session_factory):
    sess = AISession(
        id=uuid.uuid4(),
        status="completed",
        model="oci/openai.gpt-5.4",
        focus="OC",
        max_insights=7,
        version="v2",
        insights_emitted=1,
    )
    insight = AIInsight(
        id=uuid.uuid4(),
        session_id=sess.id,
        idx=0,
        headline="OC test",
        body="b",
        confidence="medium",
        materiality="medium",
        skills_run=[],
    )
    async with session_factory() as s:
        s.add_all([sess, insight])
        await s.commit()
    return {"insight_id": insight.id, "session_id": sess.id}


@pytest.fixture
def patched_app(monkeypatch: pytest.MonkeyPatch, session_factory):
    monkeypatch.setattr(db_session_mod, "async_session_factory", session_factory)
    monkeypatch.setattr(insights_router, "async_session_factory", session_factory)

    async def _get_db_override():
        async with session_factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db_override
    yield app
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Fake httpx.AsyncClient that streams a canned SSE body
# ---------------------------------------------------------------------------


def _build_canned_chunks(*, with_tool_call: bool = False) -> list[str]:
    """Return SSE `data:` lines mimicking OpenClaw / OpenAI chat.completion.chunk."""
    chunks: list[dict[str, Any]] = []
    chunks.append({"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]})
    chunks.append({"choices": [{"delta": {"content": " world"}, "finish_reason": None}]})

    if with_tool_call:
        # First tool-call delta carries id+name.
        chunks.append(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_abc",
                                    "function": {
                                        "name": "query_database",
                                        "arguments": '{"sql":"SELECT 1"}',
                                    },
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ]
            }
        )
        chunks.append(
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}
        )

    chunks.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})

    import json

    lines = [f"data: {json.dumps(c)}" for c in chunks]
    lines.append("data: [DONE]")
    return lines


class _CapturedRequest:
    def __init__(self):
        self.url: str = ""
        self.headers: dict[str, str] = {}
        self.json_body: dict[str, Any] = {}


class _FakeStreamResponse:
    """Minimal async-context-manager mimicking httpx.Response for streams."""

    def __init__(self, *, status_code: int, lines: list[str], err_body: str = "") -> None:
        self.status_code = status_code
        self._lines = lines
        self._err_body = err_body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def aiter_lines(self) -> AsyncIterator[str]:
        for ln in self._lines:
            await asyncio.sleep(0)
            yield ln

    async def aread(self) -> bytes:
        return self._err_body.encode("utf-8")


class _FakeAsyncClient:
    """Patches in for `httpx.AsyncClient(...)` inside the forwarder."""

    def __init__(self, *, status_code: int, lines: list[str], captured: _CapturedRequest, err_body: str = ""):
        self._status = status_code
        self._lines = lines
        self._captured = captured
        self._err_body = err_body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    def stream(self, method: str, url: str, *, headers=None, json=None):
        self._captured.url = url
        self._captured.headers = dict(headers or {})
        self._captured.json_body = dict(json or {})
        return _FakeStreamResponse(
            status_code=self._status,
            lines=self._lines,
            err_body=self._err_body,
        )


@pytest.fixture
def fake_httpx(monkeypatch: pytest.MonkeyPatch):
    """Yield a (configure, captured) pair so each test wires its own stream."""
    captured = _CapturedRequest()
    state = {"status": 200, "lines": [], "err_body": ""}

    def _factory(*_a, **_kw):
        return _FakeAsyncClient(
            status_code=state["status"],
            lines=state["lines"],
            captured=captured,
            err_body=state["err_body"],
        )

    # IMPORTANT: only patch the httpx symbol *inside the forwarder module*.
    # Patching the global httpx.AsyncClient would also break the test
    # client's own ASGITransport, which uses real httpx internally.
    # We construct a fake httpx-shaped namespace so the forwarder sees
    # `httpx.AsyncClient(...)` returning our fake but `httpx.Timeout`,
    # `httpx.TimeoutException`, `httpx.HTTPError` keep their real values.
    import httpx as _real_httpx

    fake_httpx_mod = types.SimpleNamespace(
        AsyncClient=_factory,
        Timeout=_real_httpx.Timeout,
        TimeoutException=_real_httpx.TimeoutException,
        HTTPError=_real_httpx.HTTPError,
    )
    monkeypatch.setattr(fwd_mod, "httpx", fake_httpx_mod)

    return state, captured


# ---------------------------------------------------------------------------
# Test 1: happy path — text-only stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openclaw_lane_streams_text_and_persists_messages(
    monkeypatch: pytest.MonkeyPatch,
    patched_app,
    seeded_insight,
    session_factory,
    fake_httpx,
) -> None:
    from httpx import ASGITransport, AsyncClient

    state, captured = fake_httpx
    state["lines"] = _build_canned_chunks(with_tool_call=False)
    state["status"] = 200

    monkeypatch.setattr(settings, "openclaw_gateway_token", "test-gateway-token", raising=False)
    monkeypatch.setattr(settings, "openclaw_gateway_url", "http://oc.test:7474", raising=False)

    insight_id = seeded_insight["insight_id"]
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/insights/insights/{insight_id}/chat",
            json={"message": "hi"},
        )
    assert r.status_code == 200, r.text
    # Per StreamingResponse the content-type must be SSE.
    assert r.headers.get("content-type", "").startswith("text/event-stream"), r.headers

    body = r.text
    # Our event-name taxonomy must appear (PRD R5).
    assert "event: assistant_message_token" in body, body[:500]
    assert "event: message_complete" in body, body[:500]

    # Forwarder dialled the right URL with the right headers.
    assert captured.url == "http://oc.test:7474/v1/chat/completions", captured.url
    assert captured.headers.get("Authorization") == "Bearer test-gateway-token"
    expected_session_key = f"agent:main:insight:{insight_id}"
    assert captured.headers.get("x-openclaw-session-key") == expected_session_key
    assert captured.json_body.get("stream") is True
    # Forwarder now prepends chat_rules system prompt + INSIGHT CONTEXT
    # block + prior thread history before the user message. The user
    # turn must always be the last message; system/history come before.
    sent_messages = captured.json_body.get("messages") or []
    assert sent_messages, "messages array must not be empty"
    assert sent_messages[-1] == {"role": "user", "content": "hi"}

    # Persistence: 1 user + 1 assistant row, monotonic seq, correct insight_id.
    async with session_factory() as s:
        rows = (
            (
                await s.execute(
                    select(AgentMessage)
                    .where(AgentMessage.insight_id == insight_id)
                    .order_by(AgentMessage.seq.asc())
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2, rows
        assert [r.role for r in rows] == ["user", "assistant"]
        assert [r.seq for r in rows] == [1, 2]
        assert rows[0].content == "hi"
        # Assistant content should be the concatenated streamed deltas.
        assert rows[1].content == "Hello world", rows[1].content
        # Both rows attach to the same thread.
        assert rows[0].thread_id == rows[1].thread_id


# ---------------------------------------------------------------------------
# Test 2: tool-call lifecycle events surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openclaw_lane_emits_tool_call_events(
    monkeypatch: pytest.MonkeyPatch,
    patched_app,
    seeded_insight,
    session_factory,
    fake_httpx,
) -> None:
    from httpx import ASGITransport, AsyncClient

    state, _ = fake_httpx
    state["lines"] = _build_canned_chunks(with_tool_call=True)
    state["status"] = 200

    insight_id = seeded_insight["insight_id"]
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/insights/insights/{insight_id}/chat",
            json={"message": "what other Crusoe sites are there?"},
        )
    assert r.status_code == 200, r.text
    body = r.text

    # When a tool_calls delta is in the canned stream, both lifecycle
    # events must appear.
    assert "event: tool_call_started" in body, body[:800]
    assert "event: tool_call_complete" in body, body[:800]
    # And the tool-name made it onto the wire.
    assert "query_database" in body

    # Persistence: assistant row should carry tool_calls JSONB populated.
    async with session_factory() as s:
        asst = (
            (
                await s.execute(
                    select(AgentMessage)
                    .where(AgentMessage.insight_id == insight_id)
                    .where(AgentMessage.role == "assistant")
                )
            )
            .scalars()
            .first()
        )
        assert asst is not None
        assert asst.tool_calls is not None, "assistant message lost the tool_calls audit"
        # tool_calls is a JSONB list[dict] per F6 / R7.
        assert any(
            (tc.get("tool_name") == "query_database") for tc in asst.tool_calls
        ), asst.tool_calls


# ---------------------------------------------------------------------------
# Test 3: OpenClaw 5xx -> error event SSE, no 500 to browser
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openclaw_5xx_emits_error_event_not_500(
    monkeypatch: pytest.MonkeyPatch,
    patched_app,
    seeded_insight,
    session_factory,
    fake_httpx,
) -> None:
    from httpx import ASGITransport, AsyncClient

    state, _ = fake_httpx
    state["status"] = 503
    state["err_body"] = "gateway down"
    state["lines"] = []  # body never iterated on error path

    insight_id = seeded_insight["insight_id"]
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/insights/insights/{insight_id}/chat",
            json={"message": "hi"},
        )
    # Endpoint must NOT 500 — the SSE channel surfaces the error instead.
    assert r.status_code == 200, r.text
    body = r.text
    assert "event: error" in body, body[:600]
    # The error code from the forwarder for 5xx is openclaw_unavailable
    # (per backend/openclaw/forwarder.py _yield_error / 5xx branch).
    assert "openclaw_unavailable" in body, body[:600]
    # Session key context preserved on the error frame.
    assert str(insight_id) in body

    # Persistence: even on failure, the user message must have landed
    # (write-through audit; PRD R7 / ARCH §6.1 step 1) and a best-effort
    # assistant row recorded with content=None.
    async with session_factory() as s:
        rows = (
            (
                await s.execute(
                    select(AgentMessage)
                    .where(AgentMessage.insight_id == insight_id)
                    .order_by(AgentMessage.seq.asc())
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) >= 1, "user message was not persisted on failed turn"
        assert rows[0].role == "user"
        assert rows[0].content == "hi"


# ---------------------------------------------------------------------------
# Test 4: forwarder uses the configured session-prefix scheme
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_key_prefix_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
    patched_app,
    seeded_insight,
    fake_httpx,
) -> None:
    from httpx import ASGITransport, AsyncClient

    state, captured = fake_httpx
    state["lines"] = _build_canned_chunks(with_tool_call=False)
    state["status"] = 200

    # Override the prefix to verify the forwarder honours config.
    monkeypatch.setattr(settings, "openclaw_session_prefix", "custom-prefix:", raising=False)

    insight_id = seeded_insight["insight_id"]
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/insights/insights/{insight_id}/chat",
            json={"message": "hi"},
        )
    assert r.status_code == 200, r.text
    assert captured.headers.get("x-openclaw-session-key") == f"custom-prefix:{insight_id}"
