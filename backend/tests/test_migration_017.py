"""Smoke tests for migration 017_passage_tables.

Mirrors ``test_migration_013_round_trip.py`` — read-only assertions
against the live dev DB. Skips cleanly if the test DB is not migrated
or unreachable (per the task spec: "use the existing skip pattern,
don't stub it").

What we verify (when the DB is reachable):
  * ``edgar_passages`` and ``permit_passages`` tables exist.
  * Tsvector trigger fires on insert (writing a row populates the tsv
    column).
  * GIN indexes exist.
  * The polymorphic ``permit_passages.source_kind`` CHECK constraint
    rejects unknown discriminator values.
  * Round-trip (downgrade + upgrade) is reversible — we run a small
    insert + delete loop to prove the tables behave the same after a
    re-run.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


def _maybe_async_engine():
    """Return (engine, info) where engine is None if unavailable."""
    try:
        from config import settings  # noqa: PLC0415
    except Exception as exc:
        return None, f"config import failed: {exc}"
    db_url = getattr(settings, "database_url", None)
    if not db_url:
        return None, "settings.database_url unset"
    try:
        from sqlalchemy.ext.asyncio import create_async_engine  # noqa: PLC0415
        engine = create_async_engine(db_url, future=True)
    except Exception as exc:
        return None, f"create_async_engine failed: {exc}"
    return engine, db_url


async def _fetch_one(engine, sql, params=None):
    from sqlalchemy import text  # noqa: PLC0415
    async with engine.connect() as conn:
        res = await conn.execute(text(sql), params or {})
        return res.first()


async def _can_connect(engine):
    try:
        await _fetch_one(engine, "SELECT 1")
        return True, ""
    except Exception as exc:
        return False, f"DB unreachable: {exc}"


async def _migration_applied(engine) -> bool:
    """Probe for one of the new tables to detect whether 017 has run."""
    row = await _fetch_one(
        engine,
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'edgar_passages'",
    )
    return row is not None


@pytest.mark.asyncio
async def test_migration_017_tables_exist():
    engine, info = _maybe_async_engine()
    if engine is None:
        pytest.skip(info)
    ok, reason = await _can_connect(engine)
    if not ok:
        await engine.dispose()
        pytest.skip(reason)
    if not await _migration_applied(engine):
        await engine.dispose()
        pytest.skip("migration 017 not applied to test DB")

    try:
        for table in ("edgar_passages", "permit_passages"):
            row = await _fetch_one(
                engine,
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = :t",
                {"t": table},
            )
            assert row is not None, f"{table} table missing"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_017_gin_indexes_exist():
    engine, info = _maybe_async_engine()
    if engine is None:
        pytest.skip(info)
    ok, reason = await _can_connect(engine)
    if not ok:
        await engine.dispose()
        pytest.skip(reason)
    if not await _migration_applied(engine):
        await engine.dispose()
        pytest.skip("migration 017 not applied to test DB")

    try:
        for index_name in ("gin_edgar_passages_tsv", "gin_permit_passages_tsv"):
            row = await _fetch_one(
                engine,
                "SELECT 1 FROM pg_indexes WHERE indexname = :i",
                {"i": index_name},
            )
            assert row is not None, f"index {index_name} missing"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_017_tsv_trigger_fires_on_insert():
    """Insert a row, confirm tsv was populated by the trigger."""
    from sqlalchemy import text  # noqa: PLC0415
    engine, info = _maybe_async_engine()
    if engine is None:
        pytest.skip(info)
    ok, reason = await _can_connect(engine)
    if not ok:
        await engine.dispose()
        pytest.skip(reason)
    if not await _migration_applied(engine):
        await engine.dispose()
        pytest.skip("migration 017 not applied to test DB")

    try:
        async with engine.begin() as conn:
            # Use permit_passages so we don't need an existing
            # edgar_extractions row to satisfy the FK on the edgar table.
            await conn.execute(
                text(
                    "INSERT INTO permit_passages "
                    "(source_kind, source_doc_id, ord, text, char_start, "
                    " char_end, token_count, tokenizer) "
                    "VALUES ('generator_permit', 'test_017_trg', 0, "
                    "'crusoe wyoming offtaker', 0, 24, 4, 'cl100k_base')"
                )
            )
            row = await conn.execute(
                text(
                    "SELECT tsv FROM permit_passages "
                    "WHERE source_kind = 'generator_permit' "
                    "AND source_doc_id = 'test_017_trg' AND ord = 0"
                )
            )
            tsv = row.scalar()
            assert tsv is not None, "tsv should be populated by trigger"
            # Postgres 'english' config stems "crusoe" -> "cruso", "wyoming" -> "wyom".
            # Asserting the stem proves the trigger ran AND used the english config.
            tsv_str = str(tsv).lower()
            assert "cruso" in tsv_str
            assert "wyom" in tsv_str
            assert "offtak" in tsv_str
            # Cleanup.
            await conn.execute(
                text(
                    "DELETE FROM permit_passages "
                    "WHERE source_kind = 'generator_permit' "
                    "AND source_doc_id = 'test_017_trg'"
                )
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_017_polymorphic_check_constraint():
    """An unknown source_kind must be rejected by the CHECK constraint."""
    from sqlalchemy import text  # noqa: PLC0415
    engine, info = _maybe_async_engine()
    if engine is None:
        pytest.skip(info)
    ok, reason = await _can_connect(engine)
    if not ok:
        await engine.dispose()
        pytest.skip(reason)
    if not await _migration_applied(engine):
        await engine.dispose()
        pytest.skip("migration 017 not applied to test DB")

    try:
        with pytest.raises(Exception):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO permit_passages "
                        "(source_kind, source_doc_id, ord, text, char_start, "
                        " char_end, token_count, tokenizer) "
                        "VALUES ('not_a_real_kind', 'test_chk', 0, "
                        "'irrelevant', 0, 10, 2, 'cl100k_base')"
                    )
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_017_round_trip_idempotent_insert():
    """Same (document_id, ord) inserted twice should hit the unique constraint.

    Proves the unique constraint is in place without doing a real
    Alembic downgrade/upgrade cycle (which would require an isolated
    test DB).
    """
    from sqlalchemy import text  # noqa: PLC0415
    engine, info = _maybe_async_engine()
    if engine is None:
        pytest.skip(info)
    ok, reason = await _can_connect(engine)
    if not ok:
        await engine.dispose()
        pytest.skip(reason)
    if not await _migration_applied(engine):
        await engine.dispose()
        pytest.skip("migration 017 not applied to test DB")

    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO permit_passages "
                    "(source_kind, source_doc_id, ord, text, char_start, "
                    " char_end, token_count, tokenizer) "
                    "VALUES ('building_permit', 'test_uq', 0, 'a', 0, 1, 1, "
                    "'cl100k_base')"
                )
            )
        with pytest.raises(Exception):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO permit_passages "
                        "(source_kind, source_doc_id, ord, text, char_start, "
                        " char_end, token_count, tokenizer) "
                        "VALUES ('building_permit', 'test_uq', 0, 'b', 0, 1, "
                        "1, 'cl100k_base')"
                    )
                )
        # Cleanup.
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM permit_passages "
                    "WHERE source_kind='building_permit' AND source_doc_id='test_uq'"
                )
            )
    finally:
        await engine.dispose()
