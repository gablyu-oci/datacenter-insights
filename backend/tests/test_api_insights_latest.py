"""Tests for GET /api/insights/latest (architecture §6 contract).

Runs the FastAPI app against an in-memory sqlite DB seeded with `ai_session`
+ `ai_insight` (+ optional `agent_chart`) rows. Mirrors the SQLite fixture
pattern from `test_v2_chat_isolation.py`:

  - JSONB / UUID compilers are patched to lower to TEXT / CHAR(36).
  - SQLModel.metadata.create_all is run only for the tables we need.
  - `db.session.async_session_factory` and the `get_db` dependency are
    overridden to point at the in-memory engine.
  - The `agents.insights.tools.sql_gate` import is short-circuited via a
    sys.modules stub so importing routers.insights doesn't break on the
    pinned sqlglot version.

Cases covered (from the user-supplied contract):
  1. Empty DB                         -> 404 + detail "no completed session yet"
  2. One complete session w/ insights -> 200, top-level status='complete'
  3. running + complete               -> running ignored
  4. Two complete today, one scheduler one manual -> scheduler wins
  5. Today empty, yesterday has one   -> yesterday's row is returned
"""
from __future__ import annotations

import os
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))
for p in (BACKEND_ROOT, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


# Note: The /api/insights/latest handler does NOT need the tools package; the
# chat handlers lazy-import tools.registry inside the request body. So we
# don't need to pre-load or stub anything in `agents.insights.tools`.
# Importing `routers.insights` is therefore safe -- its module-level imports
# do not touch the tools package.
import agents  # noqa: E402,F401
import agents.insights  # noqa: E402,F401


# -------------------- SQLite compatibility shim ----------------------------
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler  # noqa: E402


def _visit_JSONB(self, type_, **kw):  # noqa: N802
    return "TEXT"


def _visit_UUID(self, type_, **kw):  # noqa: N802
    return "CHAR(36)"


SQLiteTypeCompiler.visit_JSONB = _visit_JSONB  # type: ignore[attr-defined]
SQLiteTypeCompiler.visit_UUID = _visit_UUID  # type: ignore[attr-defined]


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
from main import app  # noqa: E402
from db.session import get_db  # noqa: E402


# ---------------------------------------------------------------------------
# Pytest fixtures
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
# Helpers
# ---------------------------------------------------------------------------


def _utcnow_naive() -> datetime:
    """Return a tz-naive UTC `now`. AISession columns are tz-naive in the
    SQLModel definitions, so we match that to avoid sqlite/psycopg friction.
    """
    return datetime.utcnow()


async def _seed_session(
    factory,
    *,
    status: str,
    started_at: datetime,
    created_by: str | None = None,
    finished_at: datetime | None = None,
    insights: int = 0,
) -> uuid.UUID:
    """Insert an AISession (+ N insights) and return its id."""
    sid = uuid.uuid4()
    async with factory() as s:
        s.add(
            AISession(
                id=sid,
                status=status,
                started_at=started_at,
                finished_at=finished_at,
                model="oci/openai.gpt-5.4",
                focus=None,
                max_insights=7,
                version="v1",
                insights_emitted=insights,
                duration_ms=12345,
                budget_status="ok",
                created_by=created_by,
            )
        )
        for i in range(insights):
            s.add(
                AIInsight(
                    id=uuid.uuid4(),
                    session_id=sid,
                    idx=i,
                    headline=f"Headline {i}",
                    body=f"Body {i}",
                    confidence="medium",
                    materiality="medium",
                    skills_run=[],
                )
            )
        await s.commit()
    return sid


# ---------------------------------------------------------------------------
# Case 1: empty DB -> 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_latest_returns_404_when_no_completed_session(patched_app):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/latest")
    assert r.status_code == 404, r.text
    assert r.json() == {"detail": "no completed session yet"}


# ---------------------------------------------------------------------------
# Case 2: single completed session with N insights
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_latest_returns_completed_session_with_insights(
    patched_app, session_factory
):
    from httpx import ASGITransport, AsyncClient

    started = _utcnow_naive() - timedelta(minutes=10)
    finished = _utcnow_naive() - timedelta(minutes=5)
    sid = await _seed_session(
        session_factory,
        status="complete",
        started_at=started,
        finished_at=finished,
        created_by="manual",
        insights=3,
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/latest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "complete"
    assert body["session"]["id"] == str(sid)
    assert body["session"]["status"] == "complete"
    assert body["session"]["created_by"] == "manual"
    assert body["session"]["version"] == "v1"
    assert len(body["insights"]) == 3
    # idx ASC ordering.
    assert [i["idx"] for i in body["insights"]] == [0, 1, 2]
    # Each insight has the contract fields.
    for ins in body["insights"]:
        assert ins["session_id"] == str(sid)
        assert "headline" in ins and "body" in ins
        assert ins["confidence"] == "medium"
        assert ins["chart"] is None  # no chart seeded
    assert body["started_at"] == body["session"]["started_at"]


# ---------------------------------------------------------------------------
# Case 3: running session is ignored; complete session is returned.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_latest_ignores_running_session(patched_app, session_factory):
    from httpx import ASGITransport, AsyncClient

    now = _utcnow_naive()
    # Running session, started LATER than the completed one. The
    # endpoint must still return the completed one.
    await _seed_session(
        session_factory,
        status="running",
        started_at=now,
        created_by="manual",
        insights=0,
    )
    completed_id = await _seed_session(
        session_factory,
        status="complete",
        started_at=now - timedelta(minutes=30),
        finished_at=now - timedelta(minutes=20),
        created_by="manual",
        insights=1,
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/latest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session"]["id"] == str(completed_id)


# ---------------------------------------------------------------------------
# Case 4: two completed sessions same UTC day, scheduler wins over manual.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_latest_prefers_scheduler_over_manual_same_day(
    patched_app, session_factory
):
    from httpx import ASGITransport, AsyncClient

    today = datetime.utcnow().replace(hour=12, minute=0, second=0, microsecond=0)
    # Manual is the more recent of the two by started_at, but scheduler
    # must still win per the §6 contract.
    manual_id = await _seed_session(
        session_factory,
        status="complete",
        started_at=today + timedelta(hours=1),
        finished_at=today + timedelta(hours=1, minutes=5),
        created_by="manual",
        insights=2,
    )
    scheduler_id = await _seed_session(
        session_factory,
        status="complete",
        started_at=today,
        finished_at=today + timedelta(minutes=5),
        created_by="scheduler",
        insights=1,
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/latest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session"]["id"] == str(scheduler_id)
    assert body["session"]["created_by"] == "scheduler"
    # Sanity: the manual row exists in the DB but is not the chosen one.
    assert body["session"]["id"] != str(manual_id)


# ---------------------------------------------------------------------------
# Case 5: nothing today, yesterday has a completed session -> falls back.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_latest_falls_back_to_most_recent_when_today_empty(
    patched_app, session_factory
):
    from httpx import ASGITransport, AsyncClient

    yesterday = datetime.utcnow().replace(
        hour=12, minute=0, second=0, microsecond=0
    ) - timedelta(days=1)
    yday_id = await _seed_session(
        session_factory,
        status="complete",
        started_at=yesterday,
        finished_at=yesterday + timedelta(minutes=5),
        created_by="scheduler",
        insights=2,
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/latest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session"]["id"] == str(yday_id)
    assert body["status"] == "complete"


# ---------------------------------------------------------------------------
# Case 6: include_failed=true returns the failed session as primary AND
# attaches the most recent prior completed session as `last_successful`.
# Default behaviour (no flag) must STILL return the completed session and
# must NOT add a `last_successful` key.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_latest_with_include_failed_returns_failed_plus_last_successful(
    patched_app, session_factory
):
    from httpx import ASGITransport, AsyncClient

    now = _utcnow_naive()
    # Completed yesterday with 3 insights.
    complete_id = await _seed_session(
        session_factory,
        status="complete",
        started_at=now - timedelta(days=1),
        finished_at=now - timedelta(days=1) + timedelta(minutes=5),
        created_by="scheduler",
        insights=3,
    )
    # Failed today, more recent than the completed row.
    failed_id = await _seed_session(
        session_factory,
        status="failed",
        started_at=now,
        finished_at=now + timedelta(minutes=2),
        created_by="scheduler",
        insights=0,
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Default: must return the completed session, no last_successful key.
        r1 = await client.get("/api/insights/latest")
        # include_failed=true: must return the failed session + last_successful.
        r2 = await client.get("/api/insights/latest?include_failed=true")

    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["session"]["id"] == str(complete_id)
    assert body1["status"] == "complete"
    assert "last_successful" not in body1

    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["session"]["id"] == str(failed_id)
    assert body2["status"] == "failed"
    assert body2["last_successful"] is not None
    assert body2["last_successful"]["session"]["id"] == str(complete_id)
    assert len(body2["last_successful"]["insights"]) == 3


# ---------------------------------------------------------------------------
# Case 7: include_failed=true with only a running session (no completed
# history) returns the running session as primary and `last_successful` is
# null.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_latest_with_include_failed_running_session_no_last_successful(
    patched_app, session_factory
):
    from httpx import ASGITransport, AsyncClient

    now = _utcnow_naive()
    running_id = await _seed_session(
        session_factory,
        status="running",
        started_at=now,
        created_by="manual",
        insights=0,
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/latest?include_failed=true")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session"]["id"] == str(running_id)
    assert body["status"] == "running"
    assert body["last_successful"] is None
