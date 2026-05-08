"""Regression tests for ``GET /api/companies/{id}/counterparties``.

The route is implemented in ``backend/routers/companies.py``
(``company_counterparties``) backed by ``_query_counterparties`` and
``_build_side``. The architecture doc is
``docs/architecture/counterparties-pies-arch.md``.

Scope of this file
------------------
These are integration tests: they spin up the ASGI app via
``httpx.AsyncClient`` and run real SQL against the locally configured
Postgres (``DATABASE_URL`` from ``backend/.env``). The router uses
``aliased`` self-joins, ``coalesce``, and ``func.distinct`` -- patterns
that don't translate cleanly to SQLite -- and the schema relies on
JSONB columns, so a SQLite-backed in-memory fixture is not viable.

The conftest in ``backend/tests/conftest.py`` only adjusts ``sys.path``;
no DB or app fixture is provided. Tests therefore either:

  * Skip cleanly when the live Postgres test DB is unreachable
    (``pytest.skip`` raised in the module-scoped ``_db_available``
    fixture); or
  * Run end-to-end against the seeded dataset that ``aterio`` ingestion
    already populated -- the same dataset the dev frontend points at.

Fixture-company pinning
-----------------------
Crusoe (``canonical_name = 'Crusoe'``, ``id = 32`` in the current
seeded dataset) is used as the "rich data" fixture: it has 40+ provider
sites and 4+ distinct end-user counterparties, so the documented shape
including ``other_sites``/``other_mw`` and the top-7 cap is exercised.
The id is resolved at runtime from ``canonical_name`` so the tests do
not break if the seed reassigns ids; failure to resolve raises
``pytest.skip``.

How to run
----------
::

    cd backend
    source .venv/bin/activate
    python -m pytest tests/test_companies_counterparties.py -v

If the local Postgres at ``DATABASE_URL`` is not reachable, every test
in this file is skipped with a clear reason -- the file remains
collectable so the broader suite does not regress.
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
# DB availability probe + per-test client
# ---------------------------------------------------------------------------
#
# The router depends on ``db.session.get_db`` which expects the configured
# Postgres to be live. The engine global in ``db.session`` keeps a
# connection pool bound to whatever asyncio loop first touched it; since
# pytest-asyncio creates a fresh loop per test, we dispose+recreate the
# engine for each test to keep all asyncpg connections on the active loop.


async def _probe_db_or_skip() -> None:
    """Skip the current test if Postgres / schema isn't reachable.

    Recreates the async engine inside the active event loop so the pool
    is bound to the correct loop. Without this, ``async_session_factory``
    captures the loop from the first test and subsequent tests trip
    ``RuntimeError: Task got Future attached to a different loop``.
    """
    try:
        from sqlalchemy import select, text

        from db import session as db_session_mod
        from db.models import Company
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from config import settings
    except Exception as exc:  # pragma: no cover - import-time guard
        pytest.skip(f"backend imports unavailable: {exc!r}")

    # Dispose any pre-existing engine so its asyncpg connections (bound to
    # the previous test's loop) are torn down cleanly. ``dispose`` is
    # safe to call repeatedly.
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
            f"skipping live counterparties tests ({type(exc).__name__}: {exc})"
        )


@pytest_asyncio.fixture
async def client():
    """Yield an httpx AsyncClient bound to a partial app exposing only
    the companies router. Probes the DB first; skips the test cleanly
    if it can't reach Postgres."""
    await _probe_db_or_skip()

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from routers.companies import router as companies_router

    application = FastAPI()
    application.include_router(companies_router)

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    # Tear down the engine so the next test's loop gets a fresh one.
    try:
        from db import session as db_session_mod

        await db_session_mod.engine.dispose()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Fixture-company resolver
# ---------------------------------------------------------------------------


async def _resolve_company_id(canonical_name: str) -> int | None:
    # Import the module (not the symbol) so we always read the
    # current ``async_session_factory`` -- ``_probe_db_or_skip``
    # rebinds it on the module per-test.
    from sqlalchemy import select

    from db import session as db_session_mod
    from db.models import Company

    async with db_session_mod.async_session_factory() as session:
        row = (
            await session.execute(
                select(Company.id).where(Company.canonical_name == canonical_name)
            )
        ).scalar_one_or_none()
        return int(row) if row is not None else None


async def _find_empty_company_id() -> int | None:
    """Find a company that has zero provider/end_user/developer/customer
    associations. Used to exercise the empty-result code path in
    ``_build_side``."""
    from sqlalchemy import text

    from db import session as db_session_mod

    stmt = text(
        """
        SELECT c.id FROM companies c
        LEFT JOIN site_company_associations sca
          ON sca.company_id = c.id
         AND sca.role IN ('provider','end_user','developer','customer')
        WHERE sca.id IS NULL
        ORDER BY c.id
        LIMIT 1
        """
    )
    async with db_session_mod.async_session_factory() as session:
        row = (await session.execute(stmt)).scalar_one_or_none()
        return int(row) if row is not None else None


# ---------------------------------------------------------------------------
# Shape & ranking assertions
# ---------------------------------------------------------------------------


def _assert_side_shape(side: dict[str, Any]) -> None:
    """Documented ``_build_side`` contract: keys + element shape."""
    assert set(side.keys()) == {"sites", "mw", "other_sites", "other_mw"}, side.keys()

    assert isinstance(side["sites"], list)
    assert isinstance(side["mw"], list)
    assert isinstance(side["other_sites"], int)
    assert isinstance(side["other_mw"], float)
    assert side["other_sites"] >= 0
    assert side["other_mw"] >= 0.0

    # Top-7 cap (router slices ``[:7]`` per metric).
    assert len(side["sites"]) <= 7
    assert len(side["mw"]) <= 7

    for entry in side["sites"]:
        assert set(entry.keys()) == {"company_id", "canonical_name", "count"}, entry
        assert isinstance(entry["company_id"], int)
        assert isinstance(entry["canonical_name"], str) and entry["canonical_name"]
        assert isinstance(entry["count"], int) and entry["count"] > 0

    for entry in side["mw"]:
        assert set(entry.keys()) == {"company_id", "canonical_name", "mw"}, entry
        assert isinstance(entry["company_id"], int)
        assert isinstance(entry["canonical_name"], str) and entry["canonical_name"]
        assert isinstance(entry["mw"], float) and entry["mw"] > 0.0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_counterparties_returns_documented_shape_with_known_data(client):
    """Crusoe is the seeded fixture with 2+ provider sites and 2+ distinct
    end-user counterparties. Assert the response matches the architecture
    doc: ``data.as_provider`` and ``data.as_end_user`` each have the
    documented ``sites``/``mw``/``other_sites``/``other_mw`` shape, and a
    ``lineage`` envelope is present."""
    cid = await _resolve_company_id("Crusoe")
    if cid is None:
        pytest.skip("Crusoe not in seed data; cannot exercise rich-data path")

    r = await client.get(f"/api/companies/{cid}/counterparties")
    assert r.status_code == 200, r.text

    body = r.json()
    assert "data" in body
    assert "lineage" in body, "CoverageEnvelope must include lineage block"

    data = body["data"]
    assert set(data.keys()) >= {"as_provider", "as_end_user"}

    _assert_side_shape(data["as_provider"])
    _assert_side_shape(data["as_end_user"])

    # The fixture guarantees at least one populated side.
    populated = data["as_provider"]["sites"] or data["as_end_user"]["sites"]
    assert populated, "Crusoe should yield at least one provider/end_user counterparty"


@pytest.mark.asyncio
async def test_counterparties_empty_when_no_data(client):
    """A company with no provider/end_user associations must return all
    four arrays empty and Other counts at zero. Exercises the
    ``clean = []`` branch of ``_build_side``."""
    empty_id = await _find_empty_company_id()
    if empty_id is None:
        pytest.skip("No empty-association company in seed data")

    r = await client.get(f"/api/companies/{empty_id}/counterparties")
    assert r.status_code == 200, r.text

    data = r.json()["data"]

    for side_name in ("as_provider", "as_end_user"):
        side = data[side_name]
        assert side["sites"] == [], f"{side_name}.sites should be empty"
        assert side["mw"] == [], f"{side_name}.mw should be empty"
        assert side["other_sites"] == 0
        assert side["other_mw"] == 0.0


@pytest.mark.asyncio
async def test_counterparties_404_for_unknown_company(client):
    """Unknown company id must surface as a 404 (mirrors ``/role-summary``
    and ``/sites``). Uses an id well outside the seeded range."""
    r = await client.get("/api/companies/99999999/counterparties")
    assert r.status_code == 404, r.text
    body = r.json()
    # FastAPI's default error envelope.
    assert "detail" in body
    assert "99999999" in str(body["detail"]) or "not found" in str(body["detail"]).lower()


@pytest.mark.asyncio
async def test_counterparties_excludes_self_and_orders_by_metric(client):
    """The router whitelists ``sca_y.company_id NOT IN company_ids`` so
    the focal company (and any rolled-up child) must never appear in its
    own counterparty list. Additionally the ``sites`` array must be
    sorted descending by ``count`` and the ``mw`` array descending by
    ``mw``."""
    cid = await _resolve_company_id("Crusoe")
    if cid is None:
        pytest.skip("Crusoe not in seed data")

    r = await client.get(f"/api/companies/{cid}/counterparties")
    assert r.status_code == 200, r.text

    data = r.json()["data"]

    for side_name in ("as_provider", "as_end_user"):
        side = data[side_name]

        # Self-exclusion.
        for entry in side["sites"] + side["mw"]:
            assert entry["company_id"] != cid, (
                f"{side_name}: focal company {cid} leaked into counterparty list"
            )

        # Descending order by metric.
        site_counts = [e["count"] for e in side["sites"]]
        assert site_counts == sorted(site_counts, reverse=True), (
            f"{side_name}.sites not sorted desc by count: {site_counts}"
        )

        mw_values = [e["mw"] for e in side["mw"]]
        assert mw_values == sorted(mw_values, reverse=True), (
            f"{side_name}.mw not sorted desc by mw: {mw_values}"
        )
