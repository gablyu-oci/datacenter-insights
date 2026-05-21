"""Smoke tests for ``routers.earnings``.

Mirrors the SQLite-in-memory fixture pattern in
``test_api_insights_latest.py`` / ``test_openclaw_forwarder.py``:

  * JSONB / UUID compilers are patched down to TEXT / CHAR(36).
  * SQLModel.metadata.create_all materialises only the tables this test
    needs (companies, earnings_transcripts, earnings_passages).
  * ``db.session.async_session_factory`` and the ``get_db`` FastAPI
    dependency are overridden to point at the in-memory engine.
  * The detail endpoint issues ``ts_rank_cd / websearch_to_tsquery`` —
    those don't exist on SQLite, so the detail endpoint's
    ``_fetch_top_passages`` catches the exception and returns []. We
    rely on this documented behaviour (see the try/except in
    ``routers/earnings.py``) so the test still passes the 200 + envelope
    contract without requiring Postgres.

Cases:
  * GET /api/earnings returns 200 + envelope keys + omits raw_text.
  * GET /api/earnings/{id} returns 200 + envelope + omits raw_text.
  * GET /api/companies/{id}/earnings returns 200 + envelope + omits raw_text.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime

import pytest
import pytest_asyncio

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))
for p in (BACKEND_ROOT, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


# -------------------- SQLite compatibility shim ---------------------------
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

import db.models as _db_models  # noqa: E402,F401 — register tables
from db.models import (  # noqa: E402
    Company,
    EarningsPassage,
    EarningsTranscript,
)
import db.session as db_session_mod  # noqa: E402
from db.session import get_db  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from routers.earnings import router as earnings_router  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _patch_created_at_defaults(*tables) -> None:
    """Postgres-only ``server_default=now()`` on created_at columns is
    not honored by SQLite. Make the column nullable for the in-memory
    test schema so inserts succeed without supplying the value.
    """
    for table in tables:
        col = table.columns.get("created_at")
        if col is None:
            continue
        col.server_default = None
        col.nullable = True


def _dedup_indexes(*tables) -> None:
    """The earnings_* models accidentally declare some indexes twice
    (once in ``__table_args__``, once via ``Field(index=True)``). On
    Postgres that's harmless (Alembic owns DDL) but ``create_all``
    on SQLite chokes with ``index ... already exists``. Strip
    duplicates by-name before create_all.
    """
    for table in tables:
        seen: set[str] = set()
        dedup = set()
        for ix in list(table.indexes):
            if ix.name in seen:
                dedup.add(ix)
            else:
                seen.add(ix.name)
        for ix in dedup:
            table.indexes.discard(ix)


@pytest_asyncio.fixture
async def sqlite_engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    tables = [
        Company.__table__,
        EarningsTranscript.__table__,
        EarningsPassage.__table__,
    ]
    _dedup_indexes(*tables)
    _patch_created_at_defaults(*tables)
    async with eng.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=tables)
        )
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(sqlite_engine):
    return sessionmaker(sqlite_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def seeded(session_factory):
    """Seed: one Company (MSFT) + one EarningsTranscript + 2 passages."""
    # Explicit ids: SQLite doesn't auto-increment BigInteger PKs without
    # the INTEGER PRIMARY KEY AUTOINCREMENT incantation, so we supply ids
    # by hand inside the test fixture.
    company = Company(
        id=1,
        canonical_name="Microsoft",
        short_name="MSFT",
        ticker="MSFT",
        cik="0000789019",
        public_private="public",
    )

    transcript = EarningsTranscript(
        id=1,
        cik="0000789019",
        ticker="MSFT",
        company_name="Microsoft",
        quarter="2026Q1",
        fiscal_year=2026,
        fiscal_quarter=1,
        call_date=date(2026, 4, 25),
        transcript_url=(
            "https://www.alphavantage.co/query?function=EARNINGS_CALL_TRANSCRIPT"
            "&symbol=MSFT&quarter=2026Q1"
        ),
        raw_text=(
            "Satya Nadella: AI demand accelerated this quarter "
            "with hyperscaler capex driving datacenter buildout."
        ),
        speaker_count=2,
        word_count=15,
        sentiment_ai_demand="bullish",
        sentiment_power_constraints="cautious",
        sentiment_datacenter_capex="bullish",
        sentiment_overall="bullish",
        guidance={"revenue_growth": "+15%"},
        capex_mentions=[{"quote": "capex driving datacenter buildout"}],
        ai_power_mentions=[],
        competitive_mentions=[],
        mw_capacity_mentions=[],
        extracted_at=datetime.utcnow(),
        extractor_version="1.0.0",
        retrieved_at=datetime.utcnow(),
    )

    async with session_factory() as s:
        s.add(company)
        s.add(transcript)
        await s.commit()
        await s.refresh(company)
        await s.refresh(transcript)
        # Two passages so the detail endpoint has data to (try to) rank.
        s.add(
            EarningsPassage(
                passage_id="11111111-1111-1111-1111-111111111111",
                document_id=transcript.id,
                ord=0,
                text="AI demand accelerated this quarter.",
                char_start=0,
                char_end=36,
                token_count=8,
                tokenizer="cl100k_base",
                speaker="Satya Nadella",
                section="prepared_remarks",
            )
        )
        s.add(
            EarningsPassage(
                passage_id="22222222-2222-2222-2222-222222222222",
                document_id=transcript.id,
                ord=1,
                text="Hyperscaler capex driving datacenter buildout.",
                char_start=37,
                char_end=83,
                token_count=8,
                tokenizer="cl100k_base",
                speaker="Satya Nadella",
                section="prepared_remarks",
            )
        )
        await s.commit()

    return {
        "company_id": int(company.id),
        "transcript_id": int(transcript.id),
    }


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch, session_factory, seeded):
    """ASGIClient wired to the in-memory SQLite session."""
    monkeypatch.setattr(db_session_mod, "async_session_factory", session_factory)

    async def _get_db_override():
        async with session_factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    application = FastAPI()
    application.include_router(earnings_router)
    application.dependency_overrides[get_db] = _get_db_override

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    application.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _walk_strings(node, found: list[str]) -> None:
    if isinstance(node, str):
        found.append(node)
    elif isinstance(node, dict):
        for v in node.values():
            _walk_strings(v, found)
    elif isinstance(node, list):
        for v in node:
            _walk_strings(v, found)


def _assert_no_raw_text(body: dict) -> None:
    """raw_text must never leak in any earnings API response.

    Why: raw_text is the verbatim transcript blob (~100KB+) — surfacing
    it in list responses would 100x the payload size, and even on the
    detail endpoint the design surfaces top-passages + structured
    mentions instead of the full text.
    """
    # 1. Key never appears anywhere in the JSON tree.
    def _check_keys(node):
        if isinstance(node, dict):
            assert "raw_text" not in node, (
                f"raw_text leaked in response body: {node.keys()}"
            )
            for v in node.values():
                _check_keys(v)
        elif isinstance(node, list):
            for v in node:
                _check_keys(v)

    _check_keys(body)


@pytest.mark.asyncio
async def test_list_earnings_returns_envelope_and_omits_raw_text(client, seeded):
    r = await client.get("/api/earnings")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) >= {"data", "lineage", "coverage"}, body.keys()
    items = body["data"]["items"]
    assert len(items) == 1
    assert items[0]["ticker"] == "MSFT"
    assert items[0]["quarter"] == "2026Q1"
    _assert_no_raw_text(body)


@pytest.mark.asyncio
async def test_get_earnings_detail_returns_envelope_and_omits_raw_text(
    client, seeded,
):
    tid = seeded["transcript_id"]
    r = await client.get(f"/api/earnings/{tid}")
    assert r.status_code == 200, r.text
    body = r.json()
    # LineageEnvelope shape: { data, lineage } — no coverage key.
    assert set(body.keys()) >= {"data", "lineage"}, body.keys()
    data = body["data"]
    assert data["id"] == tid
    assert data["ticker"] == "MSFT"
    assert "top_passages" in data
    # On SQLite the tsvector query fails and the handler returns [] — that
    # is the documented failure path; we don't depend on it being populated.
    assert isinstance(data["top_passages"], list)
    _assert_no_raw_text(body)


@pytest.mark.asyncio
async def test_list_company_earnings_returns_envelope_and_omits_raw_text(
    client, seeded,
):
    cid = seeded["company_id"]
    r = await client.get(f"/api/companies/{cid}/earnings")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) >= {"data", "lineage", "coverage"}, body.keys()
    data = body["data"]
    assert data["company_id"] == cid
    assert data["ticker"] == "MSFT"
    assert data["cik"] == "0000789019"
    assert data["total"] == 1
    assert len(data["items"]) == 1
    _assert_no_raw_text(body)


@pytest.mark.asyncio
async def test_get_earnings_detail_returns_404_for_unknown_transcript(
    client, seeded,
):
    r = await client.get("/api/earnings/9999999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_company_earnings_returns_404_for_unknown_company(
    client, seeded,
):
    r = await client.get("/api/companies/9999999/earnings")
    assert r.status_code == 404
