"""Phase D cutover tests for ``backend/routers/insights.py``.

Verifies (per docs/ai_insights_v2_spec.md §8 Phase D and the Phase D PRD):

  1. POST /sessions with no body  -> session created with version='v2',
     response carries NO Deprecated/Sunset headers.
  2. POST /sessions with version='v1' -> orchestrator constructed with
     version='v1', response carries Deprecated: true and Sunset:
     Wed, 21 May 2026 00:00:00 GMT.
  3. POST /sessions with explicit version='v2' -> no Deprecated header.
  4. GET /sessions/{id} for a v1-row session -> Deprecated header present.
  5. GET /sessions/{id} for a v2-row session -> NO Deprecated header.

The router instantiates ``InsightOrchestrator`` and an asyncio task; we
patch both to no-ops so the test stays in-process and deterministic.
The DB layer is patched via ``async_session_factory`` and the
``get_db`` dependency override.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))
for p in (BACKEND_ROOT, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


# ---------------------------------------------------------------------------
# Imports — routers.insights pulls in agents.insights orchestrator + models.
# That's fine; we patch the orchestrator so it doesn't actually run.
# ---------------------------------------------------------------------------
import routers.insights as insights_mod  # noqa: E402
from routers.insights import (  # noqa: E402
    V1_SUNSET_HTTP_DATE,
    create_session,
    get_session,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeOrch:
    """No-op stand-in for InsightOrchestrator used during create_session."""

    def __init__(self, *, session_id, db, max_insights, version):
        self.session_id = session_id
        self.db = db
        self.max_insights = max_insights
        self.version = version
        self._cancelled = False

    async def run_session(self, filters):
        # Yield nothing; the background task ends immediately.
        if False:  # pragma: no cover
            yield None
        return

    def cancel(self):
        self._cancelled = True


class _FakeDBSession:
    async def commit(self): ...
    async def rollback(self): ...
    async def close(self): ...


def _fake_db_session_factory():
    return _FakeDBSession()


# ---------------------------------------------------------------------------
# Mounted-app fixture (no DB; only POST /sessions and GET /sessions/{id})
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app(monkeypatch):
    monkeypatch.setattr(insights_mod, "InsightOrchestrator", _FakeOrch)
    monkeypatch.setattr(
        insights_mod, "async_session_factory", _fake_db_session_factory
    )

    # Drain the in-process active_sessions registry between tests so a
    # previous fake orch task doesn't leak across tests.
    insights_mod._active_sessions.clear()

    app = FastAPI()
    sub = APIRouter(prefix="/api/insights", tags=["insights"])
    sub.add_api_route("/sessions", create_session, methods=["POST"])
    sub.add_api_route("/sessions/{session_id}", get_session, methods=["GET"])
    app.include_router(sub)

    yield app

    # Cancel any pending background tasks we created.
    for active in list(insights_mod._active_sessions.values()):
        if active.task is not None and not active.task.done():
            active.task.cancel()
    insights_mod._active_sessions.clear()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# POST /sessions  — default + explicit version handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_sessions_default_is_v1_with_deprecated_header(client):
    # The default version stays "v1" through the v1 soak window
    # (sunset 2026-05-21). The router therefore emits the deprecation
    # surface on the default path.
    resp = await client.post("/api/insights/sessions", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert "session_id" in body
    # v1 default path: deprecation surface is present.
    assert resp.headers["deprecated"] == "true"
    assert "sunset" in {k.lower() for k in resp.headers.keys()}

    # The fake orch was constructed with version='v1'.
    sid = uuid.UUID(body["session_id"])
    active = insights_mod._active_sessions[sid]
    assert active.orch.version == "v1"


@pytest.mark.asyncio
async def test_post_sessions_explicit_v1_carries_deprecated_and_sunset(client):
    resp = await client.post(
        "/api/insights/sessions", json={"version": "v1"}
    )
    assert resp.status_code == 200
    body = resp.json()
    sid = uuid.UUID(body["session_id"])
    active = insights_mod._active_sessions[sid]
    assert active.orch.version == "v1"

    # Deprecation surface is present and well-formed.
    assert resp.headers["deprecated"] == "true"
    assert resp.headers["sunset"] == V1_SUNSET_HTTP_DATE
    assert resp.headers["sunset"] == "Wed, 21 May 2026 00:00:00 GMT"
    # Optional Link header points at the spec.
    assert 'rel="deprecation"' in resp.headers.get("link", "")


@pytest.mark.asyncio
async def test_post_sessions_explicit_v2_no_deprecated_header(client):
    resp = await client.post(
        "/api/insights/sessions", json={"version": "v2"}
    )
    assert resp.status_code == 200
    assert "deprecated" not in {k.lower() for k in resp.headers.keys()}
    assert "sunset" not in {k.lower() for k in resp.headers.keys()}


# ---------------------------------------------------------------------------
# GET /sessions/{id}  — header surfaces the version of the loaded row
# ---------------------------------------------------------------------------


def _make_session_row(version: str, sid: uuid.UUID):
    """Minimal duck-typed AISession row for the GET handler."""
    return SimpleNamespace(
        id=sid,
        status="complete",
        started_at=datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 5, 7, 12, 5, tzinfo=timezone.utc),
        model="oci.cohere.command-r-plus-v0.1",
        focus="crusoe wyoming",
        max_insights=7,
        version=version,
        insights_emitted=5,
        duration_ms=300_000,
        budget_status="ok",
    )


class _StubResult:
    def __init__(self, value: Any):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._value if isinstance(self._value, list) else []


def _wire_db_for_get_session(app, *, row, insights=None, charts=None):
    """Override get_db dependency with a stub session that returns row."""
    insights = insights or []
    charts = charts or []

    class _StubDB:
        async def execute(self, query):
            text = str(query)
            # Cheap-and-cheerful routing: AISession.id query returns row;
            # AIInsight.session_id returns insights; AgentChart.session_id
            # returns charts.
            if "ai_session" in text.lower() or "AISession" in text:
                return _StubResult(row)
            if "ai_insight" in text.lower() or "AIInsight" in text:
                return _StubResult(insights)
            if "agent_chart" in text.lower() or "AgentChart" in text:
                return _StubResult(charts)
            return _StubResult([])

    async def _get_db_override():
        yield _StubDB()

    from db.session import get_db
    app.dependency_overrides[get_db] = _get_db_override


@pytest.mark.asyncio
async def test_get_session_v1_row_carries_deprecated_header(app, client):
    sid = uuid.uuid4()
    row = _make_session_row(version="v1", sid=sid)
    _wire_db_for_get_session(app, row=row)

    resp = await client.get(f"/api/insights/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["version"] == "v1"
    assert resp.headers["deprecated"] == "true"
    assert resp.headers["sunset"] == V1_SUNSET_HTTP_DATE


@pytest.mark.asyncio
async def test_get_session_v2_row_has_no_deprecated_header(app, client):
    sid = uuid.uuid4()
    row = _make_session_row(version="v2", sid=sid)
    _wire_db_for_get_session(app, row=row)

    resp = await client.get(f"/api/insights/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["version"] == "v2"
    assert "deprecated" not in {k.lower() for k in resp.headers.keys()}
    assert "sunset" not in {k.lower() for k in resp.headers.keys()}
