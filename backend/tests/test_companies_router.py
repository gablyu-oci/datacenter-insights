"""Tests for ``GET /api/companies/`` — the Company Directory listing route
in ``backend/routers/companies.py`` (the ``list_companies`` handler).

Harness
-------
This file uses a HYBRID test harness:

  * Validation-only tests (the trio of 422 cases) use plain FastAPI
    ``TestClient`` against a minimal app that mounts the companies
    router. These do NOT need Postgres because query-string validation
    runs before the handler executes.
  * Data-driven tests use ``httpx.AsyncClient`` against the same ASGI
    app so the async ``get_db`` dependency works. They probe Postgres
    first via ``_probe_db_or_skip`` and skip cleanly if the configured
    DB is unreachable.

The DB probe follows the same engine-dispose / recreate pattern used
by ``test_companies_counterparties.py`` so the asyncpg pool is always
bound to the active pytest-asyncio event loop.

How to run
----------
::

    cd backend
    source .venv/bin/activate
    python -m pytest tests/test_companies_router.py -v
"""
from __future__ import annotations

import os
import sys
from typing import Any

import pytest
import pytest_asyncio

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


# ---------------------------------------------------------------------------
# Module-under-test import
# ---------------------------------------------------------------------------
import routers.companies as companies_mod  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


# ---------------------------------------------------------------------------
# DB-free validation harness (used for 422 cases)
# ---------------------------------------------------------------------------


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(companies_mod.router)
    return app


@pytest.fixture
def validation_client() -> TestClient:
    """Plain TestClient — does not need Postgres because the 422 checks
    happen during FastAPI/Pydantic query-string validation before the
    handler runs."""
    return TestClient(_build_app())


# ---------------------------------------------------------------------------
# DB-probe + per-test async client (used for data-driven tests)
# ---------------------------------------------------------------------------


async def _probe_db_or_skip() -> None:
    """Skip the current test if Postgres / schema isn't reachable.

    Mirrors the engine-rebind dance in ``test_companies_counterparties``:
    pytest-asyncio creates a fresh loop per test, but the engine in
    ``db.session`` captures the first loop it sees, so subsequent tests
    blow up with "Future attached to a different loop". Disposing and
    recreating the engine each test keeps the pool on the active loop.
    """
    try:
        from sqlalchemy import select, text

        from db import session as db_session_mod
        from db.models import Company
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from config import settings
    except Exception as exc:  # pragma: no cover - import-time guard
        pytest.skip(f"backend imports unavailable: {exc!r}")

    try:
        await db_session_mod.engine.dispose()
    except Exception:
        pass

    db_session_mod.engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
    )
    db_session_mod.async_session_factory = async_sessionmaker(
        db_session_mod.engine, expire_on_commit=False
    )

    try:
        async with db_session_mod.async_session_factory() as session:
            await session.execute(text("SELECT 1"))
            await session.execute(select(Company).limit(1))
    except Exception as exc:
        pytest.skip(
            "Postgres test DB unreachable or schema missing; "
            f"skipping live list_companies tests ({type(exc).__name__}: {exc})"
        )


@pytest_asyncio.fixture
async def client():
    """httpx AsyncClient bound to a minimal app exposing only the
    companies router. Probes Postgres first; skips the test if the DB
    is not reachable."""
    await _probe_db_or_skip()

    from httpx import ASGITransport, AsyncClient

    application = _build_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    try:
        from db import session as db_session_mod

        await db_session_mod.engine.dispose()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Seed-data probes
# ---------------------------------------------------------------------------


async def _pick_name_fragment() -> str | None:
    """Find a 4-char fragment of some canonical_name in the seeded data.

    Prefer well-known hyperscaler names so the fragment is meaningful in
    test failure output; fall back to the first company that has a long
    enough name.
    """
    from sqlalchemy import select

    from db import session as db_session_mod
    from db.models import Company

    preferred = ["Amazon", "Microsoft", "Google", "Meta", "Oracle", "Crusoe"]
    async with db_session_mod.async_session_factory() as session:
        # Try preferred hyperscaler names first.
        for name in preferred:
            row = (
                await session.execute(
                    select(Company.canonical_name)
                    .where(Company.canonical_name == name)
                    .limit(1)
                )
            ).first()
            if row and row[0]:
                # Return a 4-char lowercase fragment from the start of the name.
                return str(row[0])[:4].lower()
        # Fallback: any company name >= 4 chars.
        row = (
            await session.execute(select(Company.canonical_name).limit(1))
        ).first()
        if row and row[0] and len(row[0]) >= 4:
            return str(row[0])[:4].lower()
    return None


async def _pick_ticker_fragment() -> str | None:
    """Find a known ticker fragment in the seed."""
    from sqlalchemy import select

    from db import session as db_session_mod
    from db.models import Company

    preferred = ["AMZN", "MSFT", "GOOGL", "META", "ORCL", "AAPL", "NVDA"]
    async with db_session_mod.async_session_factory() as session:
        for tk in preferred:
            row = (
                await session.execute(
                    select(Company.ticker).where(Company.ticker == tk).limit(1)
                )
            ).first()
            if row and row[0]:
                return str(row[0]).lower()
        # Fallback: any non-null ticker with >= 2 chars.
        row = (
            await session.execute(
                select(Company.ticker).where(Company.ticker.isnot(None)).limit(1)
            )
        ).first()
        if row and row[0] and len(row[0]) >= 2:
            return str(row[0]).lower()
    return None


async def _public_company_count() -> int:
    """How many companies have public_private == 'public'."""
    from sqlalchemy import func, select

    from db import session as db_session_mod
    from db.models import Company

    async with db_session_mod.async_session_factory() as session:
        row = (
            await session.execute(
                select(func.count(Company.id)).where(Company.public_private == "public")
            )
        ).scalar()
        return int(row or 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    return body["data"]["data"]


# ---------------------------------------------------------------------------
# Data-driven tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_q_matches_name_case_insensitive(client):
    """``q`` should match canonical_name (or ticker) case-insensitively.

    We resolve a real seeded name fragment so this test follows the
    actual data rather than hardcoding strings that may drift.
    """
    fragment = await _pick_name_fragment()
    if not fragment:
        pytest.skip("Seed data has no canonical_name fragment to test against")

    # Use mixed case to exercise case-insensitivity.
    probe = fragment.upper()
    r = await client.get(f"/api/companies/?q={probe}")
    assert r.status_code == 200, r.text
    body = r.json()
    rows = _rows(body)
    assert len(rows) >= 1, f"Expected at least one row matching q={probe!r}, got 0"

    lowered = probe.lower()
    for row in rows:
        name = (row.get("canonical_name") or "").lower()
        ticker = (row.get("ticker") or "").lower()
        assert lowered in name or lowered in ticker, (
            f"Row {row.get('id')} ({row.get('canonical_name')!r}, "
            f"ticker={row.get('ticker')!r}) does not contain {lowered!r}"
        )


@pytest.mark.asyncio
async def test_q_matches_ticker_case_insensitive(client):
    """``q`` should match ticker case-insensitively."""
    tk = await _pick_ticker_fragment()
    if not tk:
        pytest.skip("No non-null tickers in seed data")

    # Use upper-case to exercise case-insensitivity.
    probe = tk.upper()
    r = await client.get(f"/api/companies/?q={probe}")
    assert r.status_code == 200, r.text
    body = r.json()
    rows = _rows(body)
    assert len(rows) >= 1, f"Expected at least one row matching ticker q={probe!r}"

    lowered = probe.lower()
    for row in rows:
        name = (row.get("canonical_name") or "").lower()
        ticker = (row.get("ticker") or "").lower()
        assert lowered in name or lowered in ticker, (
            f"Row {row.get('id')} ({row.get('canonical_name')!r}, "
            f"ticker={row.get('ticker')!r}) does not contain {lowered!r}"
        )


@pytest.mark.asyncio
async def test_public_private_public_only(client):
    """``public_private=public`` must filter to only public companies."""
    if await _public_company_count() == 0:
        pytest.skip("No public companies in seed data")

    r = await client.get("/api/companies/?public_private=public&page_size=100")
    assert r.status_code == 200, r.text
    rows = _rows(r.json())
    assert len(rows) >= 1, "Expected at least one public company"
    for row in rows:
        assert row.get("public_private") == "public", (
            f"Row {row.get('id')} leaked public_private={row.get('public_private')!r} "
            "into a public-only query"
        )


@pytest.mark.asyncio
async def test_order_by_canonical_name_asc(client):
    """``order_by=canonical_name&direction=asc`` returns A->Z order."""
    r = await client.get(
        "/api/companies/?order_by=canonical_name&direction=asc&page_size=10"
    )
    assert r.status_code == 200, r.text
    rows = _rows(r.json())
    assert len(rows) >= 2, "Need at least 2 rows to verify ordering"

    names = [r["canonical_name"] for r in rows[:5]]
    # Case-insensitive ascending sort: Postgres default collation may be
    # case-sensitive, but our seeded names share a consistent casing.
    assert names == sorted(names), f"Expected ascending order, got {names}"


@pytest.mark.asyncio
async def test_order_by_mw_total_desc_regression(client):
    """Existing ``order_by=mw_total`` (default direction=desc) still works."""
    r = await client.get("/api/companies/?order_by=mw_total&page_size=10")
    assert r.status_code == 200, r.text
    rows = _rows(r.json())
    assert len(rows) >= 2, "Need at least 2 rows for ordering check"

    mws = [float(row.get("mw_total") or 0.0) for row in rows]
    # Descending: each value <= the previous.
    for i in range(1, len(mws)):
        assert mws[i] <= mws[i - 1], (
            f"mw_total not desc at index {i}: {mws}"
        )


@pytest.mark.asyncio
async def test_pagination_slice(client):
    """``total`` is the full filtered count, not the slice. Two
    consecutive pages of size 5 yield disjoint id sets and ``total``
    remains constant."""
    r1 = await client.get("/api/companies/?page=1&page_size=5")
    r2 = await client.get("/api/companies/?page=2&page_size=5")
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text

    body1 = r1.json()["data"]
    body2 = r2.json()["data"]

    # Slice sizes must be bounded by page_size.
    assert len(body1["data"]) <= 5
    assert len(body2["data"]) <= 5

    # Total is invariant across pages.
    assert body1["total"] == body2["total"], (
        f"total changed between pages: {body1['total']} vs {body2['total']}"
    )
    # And it should be >= the number of unique rows we observed.
    seen_ids = {r["id"] for r in body1["data"]} | {r["id"] for r in body2["data"]}
    assert body1["total"] >= len(seen_ids)

    if body2["data"]:
        ids1 = {r["id"] for r in body1["data"]}
        ids2 = {r["id"] for r in body2["data"]}
        assert ids1.isdisjoint(ids2), (
            f"Page 1 and Page 2 overlap: {ids1 & ids2}"
        )


# ---------------------------------------------------------------------------
# Validation-only tests (no DB needed)
# ---------------------------------------------------------------------------


def test_validation_errors(validation_client: TestClient) -> None:
    """Out-of-allowed-set query values must produce 422 before any DB call."""
    r1 = validation_client.get("/api/companies/?direction=sideways")
    assert r1.status_code == 422, r1.text

    r2 = validation_client.get("/api/companies/?order_by=garbage")
    assert r2.status_code == 422, r2.text

    r3 = validation_client.get("/api/companies/?public_private=other")
    assert r3.status_code == 422, r3.text
