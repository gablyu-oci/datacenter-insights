"""Phase B tests for Save & History subscribe + history routes.

Covers steps B1-B4 of `docs/planning/save-and-history/00-PLAN.md`:
  - POST   /api/insights/insights/{insight_id}/subscribe
  - DELETE /api/insights/insights/{insight_id}/subscribe
  - GET    /api/insights/saved
  - GET    /api/insights/sessions

Harness mirrors `tests/test_api_insights_latest.py` verbatim (sqlite-in-memory
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


async def _seed_session(
    factory,
    *,
    status: str = "complete",
    started_at: datetime | None = None,
    created_by: str | None = "manual",
    finished_at: datetime | None = None,
    insights: int = 0,
) -> uuid.UUID:
    sid = uuid.uuid4()
    started_at = started_at or _utcnow_naive()
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


async def _seed_insight(
    factory,
    *,
    session_id: uuid.UUID,
    idx: int = 0,
) -> uuid.UUID:
    """Insert a single AIInsight tied to `session_id` and return its id."""
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
    """Insert an InsightSubscription row and return its id.

    `user_email` defaults to "dev@local" so existing tests that don't
    set an `X-Forwarded-Email` header (and therefore resolve to the dev
    fallback in `current_user_email`) still see their seeded rows in
    /saved and /latest after migration 021's per-user scoping landed.
    """
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


async def _count_subscriptions(factory, *, insight_id: uuid.UUID) -> int:
    async with factory() as s:
        rows = (
            await s.execute(
                select(InsightSubscription).where(
                    InsightSubscription.insight_id == insight_id
                )
            )
        ).scalars().all()
    return len(rows)


async def _get_subscription(
    factory, *, insight_id: uuid.UUID
) -> InsightSubscription | None:
    async with factory() as s:
        row = (
            await s.execute(
                select(InsightSubscription).where(
                    InsightSubscription.insight_id == insight_id
                )
            )
        ).scalar_one_or_none()
    return row


# ---------------------------------------------------------------------------
# B1: POST /subscribe — happy path, idempotency, re-enable, 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_post_happy_path(patched_app, session_factory):
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_session(session_factory, insights=0)
    iid = await _seed_insight(session_factory, session_id=sid, idx=0)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(f"/api/insights/insights/{iid}/subscribe")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] is True
    assert body["id"] is not None
    # UUID-shaped string
    uuid.UUID(body["id"])

    # One row, enabled=true.
    assert await _count_subscriptions(session_factory, insight_id=iid) == 1
    row = await _get_subscription(session_factory, insight_id=iid)
    assert row is not None
    assert row.enabled is True


@pytest.mark.asyncio
async def test_subscribe_post_idempotent(patched_app, session_factory):
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_session(session_factory, insights=0)
    iid = await _seed_insight(session_factory, session_id=sid, idx=0)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.post(f"/api/insights/insights/{iid}/subscribe")
        r2 = await client.post(f"/api/insights/insights/{iid}/subscribe")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
    assert r1.json()["saved"] is True
    assert r2.json()["saved"] is True

    # Only ONE row exists.
    assert await _count_subscriptions(session_factory, insight_id=iid) == 1
    row = await _get_subscription(session_factory, insight_id=iid)
    assert row.enabled is True


@pytest.mark.asyncio
async def test_subscribe_post_reenables_disabled_row(patched_app, session_factory):
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_session(session_factory, insights=0)
    iid = await _seed_insight(session_factory, session_id=sid, idx=0)
    pre_sub_id = await _seed_subscription(
        session_factory, insight_id=iid, enabled=False
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(f"/api/insights/insights/{iid}/subscribe")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] is True
    assert body["id"] == str(pre_sub_id)

    # Still one row, now enabled.
    assert await _count_subscriptions(session_factory, insight_id=iid) == 1
    row = await _get_subscription(session_factory, insight_id=iid)
    assert row.enabled is True


@pytest.mark.asyncio
async def test_subscribe_post_404_on_unknown_insight(patched_app):
    from httpx import ASGITransport, AsyncClient

    bogus = uuid.uuid4()
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(f"/api/insights/insights/{bogus}/subscribe")

    assert r.status_code == 404, r.text
    assert r.json() == {"detail": "insight not found"}


# ---------------------------------------------------------------------------
# B2: DELETE /subscribe — flips enabled to false, idempotent, 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_subscribe_delete_flips_to_disabled(patched_app, session_factory):
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_session(session_factory, insights=0)
    iid = await _seed_insight(session_factory, session_id=sid, idx=0)
    pre_sub_id = await _seed_subscription(
        session_factory, insight_id=iid, enabled=True
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete(f"/api/insights/insights/{iid}/subscribe")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] is False
    assert body["id"] is None

    # Row still present (soft-delete), now disabled.
    assert await _count_subscriptions(session_factory, insight_id=iid) == 1
    row = await _get_subscription(session_factory, insight_id=iid)
    assert row is not None
    assert row.id == pre_sub_id
    assert row.enabled is False


@pytest.mark.asyncio
async def test_subscribe_delete_idempotent_when_never_saved(
    patched_app, session_factory
):
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_session(session_factory, insights=0)
    iid = await _seed_insight(session_factory, session_id=sid, idx=0)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete(f"/api/insights/insights/{iid}/subscribe")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] is False
    assert body["id"] is None

    # No row was created.
    assert await _count_subscriptions(session_factory, insight_id=iid) == 0


@pytest.mark.asyncio
async def test_subscribe_delete_404_on_unknown_insight(patched_app):
    from httpx import ASGITransport, AsyncClient

    bogus = uuid.uuid4()
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete(f"/api/insights/insights/{bogus}/subscribe")

    assert r.status_code == 404, r.text
    assert r.json() == {"detail": "insight not found"}


# ---------------------------------------------------------------------------
# B3: GET /saved — ordering, cap, disabled-exclusion, payload shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_saved_endpoint_orders_by_created_at_desc(
    patched_app, session_factory
):
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_session(session_factory, insights=0)
    i1 = await _seed_insight(session_factory, session_id=sid, idx=0)
    i2 = await _seed_insight(session_factory, session_id=sid, idx=1)
    i3 = await _seed_insight(session_factory, session_id=sid, idx=2)

    base = _utcnow_naive()
    # Subscriptions in descending created_at order: i3 (newest), i2, i1
    await _seed_subscription(
        session_factory, insight_id=i1, enabled=True,
        created_at=base - timedelta(minutes=30),
    )
    await _seed_subscription(
        session_factory, insight_id=i2, enabled=True,
        created_at=base - timedelta(minutes=20),
    )
    await _seed_subscription(
        session_factory, insight_id=i3, enabled=True,
        created_at=base - timedelta(minutes=10),
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/saved")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    ids_in_order = [item["id"] for item in body["items"]]
    assert ids_in_order == [str(i3), str(i2), str(i1)]


@pytest.mark.asyncio
async def test_saved_endpoint_caps_at_100(patched_app, session_factory):
    from httpx import ASGITransport, AsyncClient

    # limit=200 must be rejected by the Pydantic Query validator (le=100).
    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r_invalid = await client.get("/api/insights/saved?limit=200")
    assert r_invalid.status_code == 422

    # Seed 101 enabled subscriptions; default limit (100) must return 100 items
    # newest-first, with total == 100 (handler computes total = len(items)).
    sid = await _seed_session(session_factory, insights=0)
    base = _utcnow_naive()
    ids_in_seed_order: list[uuid.UUID] = []
    for i in range(101):
        iid = await _seed_insight(session_factory, session_id=sid, idx=i)
        ids_in_seed_order.append(iid)
        # created_at increases with i, so i=100 is newest.
        await _seed_subscription(
            session_factory,
            insight_id=iid,
            enabled=True,
            created_at=base + timedelta(seconds=i),
        )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/saved")

    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 100
    assert body["total"] == 100

    # Newest-first ordering: first item is the LAST seeded insight.
    assert body["items"][0]["id"] == str(ids_in_seed_order[-1])
    # The very first-seeded insight (oldest subscription) must be excluded by the cap.
    returned_ids = {item["id"] for item in body["items"]}
    assert str(ids_in_seed_order[0]) not in returned_ids


@pytest.mark.asyncio
async def test_saved_endpoint_excludes_disabled(patched_app, session_factory):
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_session(session_factory, insights=0)
    i_enabled = await _seed_insight(session_factory, session_id=sid, idx=0)
    i_disabled = await _seed_insight(session_factory, session_id=sid, idx=1)

    await _seed_subscription(
        session_factory, insight_id=i_enabled, enabled=True
    )
    await _seed_subscription(
        session_factory, insight_id=i_disabled, enabled=False
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/saved")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(i_enabled)


@pytest.mark.asyncio
async def test_saved_endpoint_includes_session_id_and_saved_at(
    patched_app, session_factory
):
    from httpx import ASGITransport, AsyncClient

    sid = await _seed_session(session_factory, insights=0)
    iid = await _seed_insight(session_factory, session_id=sid, idx=0)
    created = _utcnow_naive() - timedelta(minutes=7)
    await _seed_subscription(
        session_factory, insight_id=iid, enabled=True, created_at=created
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/saved")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["session_id"] == str(sid)
    assert item["is_saved"] is True
    # saved_at echoes the subscription's created_at, ISO-encoded.
    assert item["saved_at"] == created.isoformat()


# ---------------------------------------------------------------------------
# B4: GET /sessions — pagination, status filter, ordering, validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sessions_pagination_defaults(patched_app, session_factory):
    from httpx import ASGITransport, AsyncClient

    base = _utcnow_naive()
    seeded_ids: list[uuid.UUID] = []
    for i in range(25):
        sid = await _seed_session(
            session_factory,
            status="complete",
            started_at=base - timedelta(minutes=i),  # i=0 is newest
            finished_at=base - timedelta(minutes=i) + timedelta(seconds=30),
            created_by="scheduler",
            insights=0,
        )
        seeded_ids.append(sid)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/sessions")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 25
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert body["has_more"] is True
    assert len(body["items"]) == 20

    # Order: newest started_at first. seeded_ids[0] was started base-0min (newest).
    returned_ids = [item["id"] for item in body["items"]]
    expected = [str(seeded_ids[i]) for i in range(20)]
    assert returned_ids == expected


@pytest.mark.asyncio
async def test_sessions_pagination_offset(patched_app, session_factory):
    from httpx import ASGITransport, AsyncClient

    base = _utcnow_naive()
    seeded_ids: list[uuid.UUID] = []
    for i in range(25):
        sid = await _seed_session(
            session_factory,
            status="complete",
            started_at=base - timedelta(minutes=i),
            insights=0,
        )
        seeded_ids.append(sid)

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/sessions?offset=20")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 25
    assert body["offset"] == 20
    assert body["has_more"] is False
    assert len(body["items"]) == 5

    # Items 20..24 are the oldest five.
    returned_ids = [item["id"] for item in body["items"]]
    expected = [str(seeded_ids[i]) for i in range(20, 25)]
    assert returned_ids == expected


@pytest.mark.asyncio
async def test_sessions_status_filter_defaults_completed(
    patched_app, session_factory
):
    from httpx import ASGITransport, AsyncClient

    base = _utcnow_naive()
    complete_id = await _seed_session(
        session_factory, status="complete", started_at=base, insights=0
    )
    await _seed_session(
        session_factory,
        status="cancelled",
        started_at=base - timedelta(minutes=1),
        insights=0,
    )
    await _seed_session(
        session_factory,
        status="failed",
        started_at=base - timedelta(minutes=2),
        insights=0,
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/sessions")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(complete_id)
    assert body["items"][0]["status"] == "complete"


@pytest.mark.asyncio
async def test_sessions_status_all_returns_everything(
    patched_app, session_factory
):
    from httpx import ASGITransport, AsyncClient

    base = _utcnow_naive()
    await _seed_session(
        session_factory, status="complete", started_at=base, insights=0
    )
    await _seed_session(
        session_factory,
        status="cancelled",
        started_at=base - timedelta(minutes=1),
        insights=0,
    )
    await _seed_session(
        session_factory,
        status="failed",
        started_at=base - timedelta(minutes=2),
        insights=0,
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/sessions?status=all")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    statuses = {item["status"] for item in body["items"]}
    assert statuses == {"complete", "cancelled", "failed"}


@pytest.mark.asyncio
async def test_sessions_status_failed_returns_only_failed(
    patched_app, session_factory
):
    from httpx import ASGITransport, AsyncClient

    base = _utcnow_naive()
    await _seed_session(
        session_factory, status="complete", started_at=base, insights=0
    )
    failed_id = await _seed_session(
        session_factory,
        status="failed",
        started_at=base - timedelta(minutes=1),
        insights=0,
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/sessions?status=failed")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(failed_id)
    assert body["items"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_sessions_limit_over_50_rejected(patched_app):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/sessions?limit=51")

    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_sessions_returns_session_metadata(patched_app, session_factory):
    from httpx import ASGITransport, AsyncClient

    started = _utcnow_naive() - timedelta(minutes=10)
    finished = started + timedelta(minutes=2)
    sid = await _seed_session(
        session_factory,
        status="complete",
        started_at=started,
        finished_at=finished,
        created_by="scheduler",
        insights=3,
    )

    transport = ASGITransport(app=patched_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/insights/sessions")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    # Every field the SessionRow contract promises.
    assert item["id"] == str(sid)
    assert item["status"] == "complete"
    assert item["started_at"] is not None
    assert item["finished_at"] is not None
    assert item["model"] == "oci/openai.gpt-5.4"
    assert item["focus"] is None
    assert item["insights_emitted"] == 3
    assert item["duration_ms"] == 12345
    assert item["created_by"] == "scheduler"
