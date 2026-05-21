"""Per-user insight_subscription + /counts endpoint tests.

Covers acceptance criteria 8.1, 8.2, and the counts endpoint behavior
described in `docs/planning/save-and-history-per-user/01-PRD.md`.

Harness mirrors `tests/test_subscribe_router.py` (sqlite-in-memory
JSONB/UUID shim, `patched_app` fixture, ASGITransport + AsyncClient).
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


from sqlalchemy import select  # noqa: E402
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
from config import settings  # noqa: E402
from main import app  # noqa: E402
from db.session import get_db  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures (verbatim from test_subscribe_router.py)
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


USER_A = "user-a@oracle.com"
USER_B = "user-b@oracle.com"


async def _seed_session(
    factory,
    *,
    status: str = "complete",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> uuid.UUID:
    sid = uuid.uuid4()
    started_at = started_at or _utcnow_naive()
    if status == "complete" and finished_at is None:
        finished_at = started_at + timedelta(minutes=1)
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
                insights_emitted=0,
                duration_ms=12345,
                budget_status="ok",
                created_by="manual",
            )
        )
        await s.commit()
    return sid


async def _seed_insight(
    factory, *, session_id: uuid.UUID, idx: int = 0
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
    user_email: str,
    created_at: datetime | None = None,
) -> uuid.UUID:
    sub_id = uuid.uuid4()
    async with factory() as s:
        s.add(
            InsightSubscription(
                id=sub_id,
                insight_id=insight_id,
                enabled=enabled,
                user_email=user_email,
                created_at=created_at or _utcnow_naive(),
            )
        )
        await s.commit()
    return sub_id


async def _get_subscriptions(
    factory, *, insight_id: uuid.UUID
) -> list[InsightSubscription]:
    async with factory() as s:
        rows = (
            await s.execute(
                select(InsightSubscription).where(
                    InsightSubscription.insight_id == insight_id
                )
            )
        ).scalars().all()
    return list(rows)


# ---------------------------------------------------------------------------
# 8.1 — Per-user scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_saved_filtered_by_user(patched_app, session_factory):
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_session(session_factory)
    insight_a = await _seed_insight(session_factory, session_id=sid, idx=0)
    insight_b = await _seed_insight(session_factory, session_id=sid, idx=1)

    await _seed_subscription(
        session_factory,
        insight_id=insight_a,
        enabled=True,
        user_email=USER_A,
    )
    await _seed_subscription(
        session_factory,
        insight_id=insight_b,
        enabled=True,
        user_email=USER_B,
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(
            "/api/insights/saved",
            headers={"X-Forwarded-Email": USER_A},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(insight_a)


@pytest.mark.asyncio
async def test_subscribe_writes_user_email(patched_app, session_factory):
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_session(session_factory)
    iid = await _seed_insight(session_factory, session_id=sid, idx=0)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            f"/api/insights/insights/{iid}/subscribe",
            headers={"X-Forwarded-Email": USER_B},
        )

    assert r.status_code == 200, r.text

    rows = await _get_subscriptions(session_factory, insight_id=iid)
    assert len(rows) == 1
    assert rows[0].enabled is True
    assert rows[0].user_email == USER_B


@pytest.mark.asyncio
async def test_unsubscribe_is_noop_across_users(patched_app, session_factory):
    """User A's DELETE on a row owned by user B must not change that row."""
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_session(session_factory)
    iid = await _seed_insight(session_factory, session_id=sid, idx=0)
    b_sub_id = await _seed_subscription(
        session_factory,
        insight_id=iid,
        enabled=True,
        user_email=USER_B,
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete(
            f"/api/insights/insights/{iid}/subscribe",
            headers={"X-Forwarded-Email": USER_A},
        )

    # Endpoint returns 200 even on no-op (per FR-2).
    assert r.status_code == 200, r.text

    rows = await _get_subscriptions(session_factory, insight_id=iid)
    assert len(rows) == 1
    # User B's row is intact: same id, still enabled, still owned by B.
    assert rows[0].id == b_sub_id
    assert rows[0].enabled is True
    assert rows[0].user_email == USER_B


@pytest.mark.asyncio
async def test_is_saved_per_user_on_latest(patched_app, session_factory):
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_session(session_factory)
    iid = await _seed_insight(session_factory, session_id=sid, idx=0)
    await _seed_subscription(
        session_factory,
        insight_id=iid,
        enabled=True,
        user_email=USER_A,
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r_a = await client.get(
            "/api/insights/latest",
            headers={"X-Forwarded-Email": USER_A},
        )
        r_b = await client.get(
            "/api/insights/latest",
            headers={"X-Forwarded-Email": USER_B},
        )

    assert r_a.status_code == 200, r_a.text
    assert r_b.status_code == 200, r_b.text

    a_insights = r_a.json()["insights"]
    b_insights = r_b.json()["insights"]
    assert len(a_insights) == 1
    assert len(b_insights) == 1
    assert a_insights[0]["id"] == str(iid)
    assert b_insights[0]["id"] == str(iid)
    assert a_insights[0]["is_saved"] is True
    assert b_insights[0]["is_saved"] is False


@pytest.mark.asyncio
async def test_email_normalization(patched_app, session_factory):
    """`GABRIELLE.LYU@ORACLE.COM` and `gabrielle.lyu@oracle.com` resolve same."""
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_session(session_factory)
    iid = await _seed_insight(session_factory, session_id=sid, idx=0)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # First POST with uppercase header.
        r1 = await client.post(
            f"/api/insights/insights/{iid}/subscribe",
            headers={"X-Forwarded-Email": "GABRIELLE.LYU@ORACLE.COM"},
        )
        # Second POST with lowercase header should be a no-op on the same row.
        r2 = await client.post(
            f"/api/insights/insights/{iid}/subscribe",
            headers={"X-Forwarded-Email": "gabrielle.lyu@oracle.com"},
        )

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    # Same subscription id returned both times = idempotent under case fold.
    assert r1.json()["id"] == r2.json()["id"]

    rows = await _get_subscriptions(session_factory, insight_id=iid)
    assert len(rows) == 1
    assert rows[0].user_email == "gabrielle.lyu@oracle.com"

    # And the lowercase-header user can read it back via /saved.
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r_get = await client.get(
            "/api/insights/saved",
            headers={"X-Forwarded-Email": "Gabrielle.Lyu@oracle.com"},
        )
    assert r_get.status_code == 200, r_get.text
    body = r_get.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(iid)


# ---------------------------------------------------------------------------
# 8.2 — Dev fallback & production 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_header_in_dev_uses_dev_local(
    patched_app, session_factory, monkeypatch
):
    """`settings.environment != 'production'` + no header -> dev@local."""
    from httpx import ASGITransport, AsyncClient

    # Ensure non-production explicitly.
    monkeypatch.setattr(settings, "environment", "development")

    sid = await _seed_session(session_factory)
    iid = await _seed_insight(session_factory, session_id=sid, idx=0)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(f"/api/insights/insights/{iid}/subscribe")

    assert r.status_code == 200, r.text

    rows = await _get_subscriptions(session_factory, insight_id=iid)
    assert len(rows) == 1
    assert rows[0].user_email == "dev@local"


@pytest.mark.asyncio
async def test_no_header_in_prod_returns_401(
    patched_app, session_factory, monkeypatch
):
    """Production + no header -> 401 missing_x_forwarded_email everywhere."""
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setattr(settings, "environment", "production")

    sid = await _seed_session(session_factory)
    iid = await _seed_insight(session_factory, session_id=sid, idx=0)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r_saved = await client.get("/api/insights/saved")
        r_counts = await client.get("/api/insights/counts")
        r_sub = await client.post(
            f"/api/insights/insights/{iid}/subscribe"
        )

    assert r_saved.status_code == 401, r_saved.text
    assert r_saved.json()["detail"] == "missing_x_forwarded_email"
    assert r_counts.status_code == 401, r_counts.text
    assert r_counts.json()["detail"] == "missing_x_forwarded_email"
    assert r_sub.status_code == 401, r_sub.text
    assert r_sub.json()["detail"] == "missing_x_forwarded_email"


# ---------------------------------------------------------------------------
# Counts endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_counts_saved_is_per_user(patched_app, session_factory):
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_session(session_factory)
    # User A saves two insights.
    a1 = await _seed_insight(session_factory, session_id=sid, idx=0)
    a2 = await _seed_insight(session_factory, session_id=sid, idx=1)
    # User B saves one insight.
    b1 = await _seed_insight(session_factory, session_id=sid, idx=2)

    await _seed_subscription(
        session_factory, insight_id=a1, enabled=True, user_email=USER_A
    )
    await _seed_subscription(
        session_factory, insight_id=a2, enabled=True, user_email=USER_A
    )
    await _seed_subscription(
        session_factory, insight_id=b1, enabled=True, user_email=USER_B
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r_a = await client.get(
            "/api/insights/counts",
            headers={"X-Forwarded-Email": USER_A},
        )
        r_b = await client.get(
            "/api/insights/counts",
            headers={"X-Forwarded-Email": USER_B},
        )

    assert r_a.status_code == 200, r_a.text
    assert r_b.status_code == 200, r_b.text
    assert r_a.json()["saved"] == 2
    assert r_b.json()["saved"] == 1


@pytest.mark.asyncio
async def test_counts_sessions_is_global(patched_app, session_factory):
    """sessions count is global across all users (ai_session stays shared)."""
    from httpx import ASGITransport, AsyncClient

    # Two complete sessions, plus one non-complete (must be excluded).
    base = _utcnow_naive()
    await _seed_session(
        session_factory, status="complete", started_at=base
    )
    await _seed_session(
        session_factory,
        status="complete",
        started_at=base - timedelta(minutes=5),
    )
    await _seed_session(
        session_factory,
        status="failed",
        started_at=base - timedelta(minutes=10),
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r_a = await client.get(
            "/api/insights/counts",
            headers={"X-Forwarded-Email": USER_A},
        )
        r_b = await client.get(
            "/api/insights/counts",
            headers={"X-Forwarded-Email": USER_B},
        )

    assert r_a.status_code == 200, r_a.text
    assert r_b.status_code == 200, r_b.text
    # Both users see the same complete-session count, failed excluded.
    assert r_a.json()["sessions"] == 2
    assert r_b.json()["sessions"] == 2
