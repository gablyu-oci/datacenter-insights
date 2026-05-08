"""Backfill script for AI Insights v2 Phase B.1 passage tables.

Reads parent documents (``edgar_extractions`` and the polymorphic permit
sources), chunks each document into ~300-token passages, and upserts
them into ``edgar_passages`` / ``permit_passages``.

CLI::

    python -m backend.scripts.backfill_document_passages \
        --source {edgar|permits|all} \
        --batch-size 200 \
        [--limit N] \
        [--no-resume]

Behaviour:
  * Idempotent — for each document, the helper deletes existing passages
    first and re-inserts the deterministic chunker output. Re-running
    against an already-populated table is safe.
  * Per-batch commits so a crash partway through doesn't lose all
    progress. Resume is implicit because deterministic chunking +
    delete-then-insert is a no-op on documents already at the current
    chunker version.
  * One malformed document logs a warning and increments the failure
    count but does NOT abort the run. The script returns exit code 0
    only if every document succeeded; otherwise 1.

Usage notes:
  * ``--source permits`` chunks the four permit document tables that
    actually carry document text (generator_permits, building_permits,
    and any rows where pdf parsing wrote raw text). Polymorphic source
    ids are prefixed with ``"<table>:"`` for stability.
  * The script does NOT modify ingestion code — it's a one-shot catchup
    that runs against documents already in the DB. The ongoing chunking
    hooks in ``ingestion/_passages.py`` keep new documents indexed.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger("ai_insights.backfill_passages")


# ---------------------------------------------------------------------------
# Engine / session
# ---------------------------------------------------------------------------


def _make_session_factory():
    """Build a writeable async session factory (lazily, so test imports
    don't connect)."""
    # Local import — avoids loading config / db at module import time.
    from agents.insights.db.session import get_write_engine

    engine = get_write_engine()
    return async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Edgar backfill
# ---------------------------------------------------------------------------


async def _iter_edgar_docs(
    session: AsyncSession, *, batch_size: int, limit: int | None
) -> Iterable[dict[str, Any]]:
    """Yield ``{id, body}`` rows from edgar_extractions, batch by batch.

    Body source: ``excerpt`` (existing column carrying the parsed text
    snippet, capped at 2000 chars per migration 002 / ingestion).
    """
    last_id = 0
    fetched = 0
    while True:
        if limit is not None and fetched >= limit:
            return
        remaining = batch_size if limit is None else min(batch_size, limit - fetched)
        rows = (
            await session.execute(
                text(
                    "SELECT id, COALESCE(excerpt, '') AS body "
                    "FROM edgar_extractions "
                    "WHERE id > :last_id "
                    "ORDER BY id "
                    "LIMIT :limit"
                ),
                {"last_id": last_id, "limit": remaining},
            )
        ).mappings().all()
        if not rows:
            return
        for row in rows:
            yield dict(row)
            last_id = max(last_id, int(row["id"]))
            fetched += 1
            if limit is not None and fetched >= limit:
                return


async def _backfill_edgar(
    session_factory, *, batch_size: int, limit: int | None
) -> dict[str, int]:
    from ingestion._passages import chunk_and_persist_edgar

    processed = 0
    chunks_written = 0
    failures = 0
    async with session_factory() as session:
        async for doc in _iter_edgar_docs(
            session, batch_size=batch_size, limit=limit
        ):
            try:
                n = await chunk_and_persist_edgar(
                    session,
                    document_id=int(doc["id"]),
                    body=doc.get("body") or "",
                )
                chunks_written += n
                processed += 1
                if processed % 100 == 0:
                    await session.commit()
                    logger.info(
                        "edgar.progress processed=%d chunks=%d failures=%d",
                        processed,
                        chunks_written,
                        failures,
                    )
            except Exception as exc:
                failures += 1
                logger.warning(
                    "edgar.doc_failed id=%s err=%s", doc.get("id"), exc
                )
                # Roll back the failed unit but keep the session alive.
                await session.rollback()
        await session.commit()
    return {
        "processed": processed,
        "chunks_written": chunks_written,
        "failures": failures,
    }


# ---------------------------------------------------------------------------
# Permits backfill
# ---------------------------------------------------------------------------


async def _backfill_permits(
    session_factory, *, batch_size: int, limit: int | None
) -> dict[str, int]:
    """Chunk the permit document tables.

    Sources covered:
      * ``generator_permits`` -> source_kind='generator_permit'
        Body = best-effort concatenation of facility_name, raw_payload->>'description'
        when present (kept defensive — many rows have only structured fields).
      * ``building_permits`` -> source_kind='building_permit'
        Body = concatenation of permit_type, address, applicant_name when present.

    Real PDF-derived text lives in raw_payload JSON for many adapters; we
    pull it when available and fall back to the structured columns.
    """
    from ingestion._passages import chunk_and_persist_permit

    processed = 0
    chunks_written = 0
    failures = 0

    async with session_factory() as session:
        # Generator permits.
        # Only rows where there's some text body to index.
        result = await session.execute(
            text(
                "SELECT id, COALESCE(facility_name, '') AS facility_name, "
                "       raw_payload "
                "FROM generator_permits "
                + (
                    "ORDER BY id LIMIT :lim"
                    if limit is not None
                    else "ORDER BY id"
                )
            ),
            {"lim": limit} if limit is not None else {},
        )
        rows = result.mappings().all()
        for row in rows:
            body = _gather_generator_body(row)
            if not body:
                continue
            try:
                n = await chunk_and_persist_permit(
                    session,
                    source_kind="generator_permit",
                    source_doc_id=str(row["id"]),
                    body=body,
                )
                chunks_written += n
                processed += 1
                if processed % 100 == 0:
                    await session.commit()
                    logger.info(
                        "permits.progress processed=%d chunks=%d failures=%d",
                        processed,
                        chunks_written,
                        failures,
                    )
            except Exception as exc:
                failures += 1
                logger.warning(
                    "permits.gen_failed id=%s err=%s", row.get("id"), exc
                )
                await session.rollback()

        # Building permits.
        result = await session.execute(
            text(
                "SELECT id, COALESCE(permit_type, '') AS permit_type, "
                "       COALESCE(address, '') AS address, "
                "       COALESCE(applicant_name, '') AS applicant_name "
                "FROM building_permits ORDER BY id"
                + (" LIMIT :lim" if limit is not None else "")
            ),
            {"lim": limit} if limit is not None else {},
        )
        rows = result.mappings().all()
        for row in rows:
            body = " ".join(
                str(row[k] or "")
                for k in ("permit_type", "address", "applicant_name")
                if row.get(k)
            ).strip()
            if not body:
                continue
            try:
                n = await chunk_and_persist_permit(
                    session,
                    source_kind="building_permit",
                    source_doc_id=str(row["id"]),
                    body=body,
                )
                chunks_written += n
                processed += 1
            except Exception as exc:
                failures += 1
                logger.warning(
                    "permits.bld_failed id=%s err=%s", row.get("id"), exc
                )
                await session.rollback()

        await session.commit()

    return {
        "processed": processed,
        "chunks_written": chunks_written,
        "failures": failures,
    }


def _gather_generator_body(row: dict[str, Any]) -> str:
    """Pull a chunkable body out of a generator_permits row.

    raw_payload is JSONB and may contain free-text fields named things
    like "description", "narrative", "permit_text". We keep the gather
    permissive — anything we can find that's a string longer than 20
    chars gets concatenated.
    """
    parts: list[str] = []
    fac = row.get("facility_name")
    if fac:
        parts.append(str(fac))
    raw = row.get("raw_payload")
    if isinstance(raw, dict):
        for key in (
            "description",
            "narrative",
            "permit_text",
            "summary",
            "extracted_text",
            "body",
        ):
            v = raw.get(key)
            if isinstance(v, str) and len(v) > 20:
                parts.append(v)
    return "\n\n".join(parts).strip()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill AI Insights v2 passage tables (Phase B.1)."
    )
    parser.add_argument(
        "--source",
        choices=("edgar", "permits", "all"),
        default="all",
    )
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap total documents processed per source (dev only).",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help=(
            "Reserved for future explicit resume tokens. Today the "
            "backfill is implicitly resumable because re-chunking is a "
            "no-op on already-current documents."
        ),
    )
    return parser.parse_args(argv)


async def _amain(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)

    session_factory = _make_session_factory()

    summary: dict[str, Any] = {}
    failures = 0

    if args.source in ("edgar", "all"):
        edgar = await _backfill_edgar(
            session_factory, batch_size=args.batch_size, limit=args.limit
        )
        summary["edgar"] = edgar
        failures += edgar["failures"]
    if args.source in ("permits", "all"):
        permits = await _backfill_permits(
            session_factory, batch_size=args.batch_size, limit=args.limit
        )
        summary["permits"] = permits
        failures += permits["failures"]

    logger.info("backfill.summary %s", summary)
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(list(argv or sys.argv[1:])))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
