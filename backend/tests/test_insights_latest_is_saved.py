"""Phase B step B5: assert that `is_saved` is correctly threaded through
GET /api/insights/latest and GET /api/insights/sessions/{id}/insights.

Harness mirrors `tests/test_api_insights_latest.py` verbatim.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta

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

import agents.insights.db.models as ai_models  # noqa: E402,F401
from agents.insights.db.models import (  # noqa: E402
    AgentChart,
    AgentCitation,
    AgentMessage,
    AIInsight,
    AISession,
    InsightSubscription,
    InsightThread,
)

import db.session as db_session_mod  # noqa: E402
import routers.insights as insights_router  # noqa: E402
from main import app  # noqa: E402
from db.session import get_db  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures (verbatim copy of test_api_insights_latest.py's harness,
# plus InsightSubscription in the needed_tables list).
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
        InsightSubscription.__table__,
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
    return datetime.utcnow()


async def _seed_complete_session(
    factory,
    *,
    started_at: datetime | None = None,
) -> uuid.UUID:
    sid = uuid.uuid4()
    started_at = started_at or (_utcnow_naive() - timedelta(minutes=10))
    finished = started_at + timedelta(minutes=2)
    async with factory() as s:
        s.add(
            AISession(
                id=sid,
                status="complete",
                started_at=started_at,
                finished_at=finished,
                model="oci/openai.gpt-5.4",
                focus=None,
                max_insights=7,
                version="v1",
                insights_emitted=0,
                duration_ms=12345,
                budget_status="ok",
                created_by="manual",
            )
        )
        await s.commit()
    return sid


async def _seed_insight(
    factory,
    *,
    session_id: uuid.UUID,
    idx: int = 0,
) -> uuid.UUID:
    iid = uuid.uuid4()
    async with factory() as s:
        s.add(
            AIInsight(
                id=iid,
                session_id=session_id,
                idx=idx,
                headline=f"Insight {idx}",
                body=f"Body {idx}",
                confidence="medium",
                materiality="medium",
                skills_run=[],
            )
        )
        await s.commit()
    return iid


async def _seed_subscription(
    factory,
    *,
    insight_id: uuid.UUID,
    enabled: bool,
    created_at: datetime | None = None,
    user_email: str = "dev@local",
) -> uuid.UUID:
    """Seed an InsightSubscription. `user_email` defaults to "dev@local"
    so callers that hit /latest without an X-Forwarded-Email header
    (resolving to the dev fallback) still see is_saved=True on these
    rows after migration 021's per-user scoping landed."""
    sub_id = uuid.uuid4()
    async with factory() as s:
        s.add(
            InsightSubscription(
                id=sub_id,
                insight_id=insight_id,
                enabled=enabled,
                created_at=created_at or _utcnow_naive(),
                user_email=user_email,
            )
        )
        await s.commit()
    return sub_id


# ---------------------------------------------------------------------------
# /latest: is_saved true / false / disabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_saved_true_when_enabled_subscription_exists(
    patched_app, session_factory
):
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_complete_session(session_factory)
    iid = await _seed_insight(session_factory, session_id=sid, idx=0)
    await _seed_subscription(session_factory, insight_id=iid, enabled=True)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/latest")

    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["insights"]) == 1
    assert body["insights"][0]["id"] == str(iid)
    assert body["insights"][0]["is_saved"] is True


@pytest.mark.asyncio
async def test_is_saved_false_when_no_subscription(patched_app, session_factory):
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_complete_session(session_factory)
    iid = await _seed_insight(session_factory, session_id=sid, idx=0)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/latest")

    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["insights"]) == 1
    assert body["insights"][0]["id"] == str(iid)
    assert body["insights"][0]["is_saved"] is False


@pytest.mark.asyncio
async def test_is_saved_false_when_subscription_disabled(
    patched_app, session_factory
):
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_complete_session(session_factory)
    iid = await _seed_insight(session_factory, session_id=sid, idx=0)
    await _seed_subscription(session_factory, insight_id=iid, enabled=False)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/latest")

    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["insights"]) == 1
    assert body["insights"][0]["id"] == str(iid)
    assert body["insights"][0]["is_saved"] is False


# ---------------------------------------------------------------------------
# /sessions/{id}/insights: is_saved threaded per-row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_saved_present_on_sessions_endpoint(
    patched_app, session_factory
):
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_complete_session(session_factory)
    i_saved = await _seed_insight(session_factory, session_id=sid, idx=0)
    i_unsaved = await _seed_insight(session_factory, session_id=sid, idx=1)
    await _seed_subscription(session_factory, insight_id=i_saved, enabled=True)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/insights/sessions/{sid}/insights")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    by_id = {item["id"]: item for item in body["items"]}
    assert str(i_saved) in by_id
    assert str(i_unsaved) in by_id
    assert by_id[str(i_saved)]["is_saved"] is True
    assert by_id[str(i_unsaved)]["is_saved"] is False
