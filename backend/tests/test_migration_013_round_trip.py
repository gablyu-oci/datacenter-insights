"""Phase 2 migration 013 smoke tests against the live dev DB.

These run read-only queries against `information_schema.columns` and
`pg_indexes` to confirm migration `013_ai_insight_embedding_vector` has
been applied. They are NOT alembic up/down round-trip tests — that's
covered by the alembic test machinery elsewhere — but they catch the
common failure mode of "alembic ran but the column didn't actually
land" (e.g. mid-migration crash, partial rollback).

If `settings.database_url` is not set or the DB is unreachable, both
tests skip cleanly so this file does not break developer workflows
that lack a local Postgres.
"""
from __future__ import annotations

import asyncio

import pytest


def _maybe_async_engine():
    """Return (engine, db_url) or (None, reason). Skip on any failure."""
    try:
        from config import settings
    except Exception as exc:  # pragma: no cover - config import error
        return None, f"config import failed: {exc}"

    db_url = getattr(settings, "database_url", None)
    if not db_url:
        return None, "settings.database_url unset"

    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        engine = create_async_engine(db_url, future=True)
    except Exception as exc:
        return None, f"create_async_engine failed: {exc}"

    return engine, db_url


async def _fetch_one(engine, sql: str, params: dict | None = None):
    from sqlalchemy import text
    async with engine.connect() as conn:
        res = await conn.execute(text(sql), params or {})
        return res.first()


async def _fetch_all(engine, sql: str, params: dict | None = None):
    from sqlalchemy import text
    async with engine.connect() as conn:
        res = await conn.execute(text(sql), params or {})
        return res.fetchall()


async def _can_connect(engine) -> tuple[bool, str]:
    """Probe the DB; return (ok, reason)."""
    try:
        await _fetch_one(engine, "SELECT 1")
        return True, ""
    except Exception as exc:
        return False, f"DB unreachable: {exc}"


@pytest.mark.asyncio
async def test_migration_013_columns_present():
    """All 5 new columns from 013 must be present with the right udt_name."""
    engine, info = _maybe_async_engine()
    if engine is None:
        pytest.skip(info)
    ok, reason = await _can_connect(engine)
    if not ok:
        await engine.dispose()
        pytest.skip(reason)

    expected = [
        ("ai_insight", "headline_embedding", "vector"),
        ("ai_insight", "ongoing_of_id", "uuid"),
        ("ai_insight", "supporting_row_ids", "jsonb"),
        ("ai_session", "cron_run_date", "date"),
        ("ai_session", "token_estimate", "int4"),
    ]

    try:
        for table, column, udt_name in expected:
            row = await _fetch_one(
                engine,
                """
                SELECT udt_name
                  FROM information_schema.columns
                 WHERE table_name = :t
                   AND column_name = :c
                """,
                {"t": table, "c": column},
            )
            assert row is not None, f"{table}.{column} not found in information_schema"
            assert row[0] == udt_name, (
                f"{table}.{column}: expected udt_name={udt_name!r}, got {row[0]!r}"
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_migration_013_indexes_present():
    """The two new indexes from 013 must be present."""
    engine, info = _maybe_async_engine()
    if engine is None:
        pytest.skip(info)
    ok, reason = await _can_connect(engine)
    if not ok:
        await engine.dispose()
        pytest.skip(reason)

    expected_indexes = [
        ("ai_session", "ix_ai_session_created_by_cron_run_date"),
        ("ai_insight", "ix_ai_insight_ongoing_of_id"),
    ]

    try:
        for table, index_name in expected_indexes:
            row = await _fetch_one(
                engine,
                """
                SELECT indexname
                  FROM pg_indexes
                 WHERE tablename = :t
                   AND indexname = :i
                """,
                {"t": table, "i": index_name},
            )
            assert row is not None, (
                f"index {index_name} on {table} not found in pg_indexes"
            )
    finally:
        await engine.dispose()
