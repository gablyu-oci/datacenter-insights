"""Shared chunking + upsert helpers for the AI Insights v2 Phase B.1
passage tables (``edgar_passages``, ``permit_passages``).

Phase B.1 scope: BM25-only. Embeddings are deferred to Phase B.2 if
recall@8 < 0.85 on the golden set.

Each adapter calls one of two helpers after a document has been written:

* ``chunk_and_persist_edgar(session, document_id, text)``
* ``chunk_and_persist_permit(session, source_kind, source_doc_id, text)``

Both are idempotent: re-chunking a document deletes the existing
passages then inserts fresh ones in the same transaction. Concurrent
re-ingestion is serialised by the unique ``(document_id, ord)`` /
``(source_kind, source_doc_id, ord)`` constraints created in migration
017.

If the caller passes empty / whitespace-only text the helper is a
no-op — no rows are written and no error is raised.

The helpers are tolerant of failures: callers should wrap them in a
try/except and log a warning on failure, never break ingestion. This
keeps the chunking hook decoupled from ingestion correctness (per the
task spec D4 instructions).
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agents.insights.util.chunk_text import chunk_text

logger = logging.getLogger(__name__)


PERMIT_SOURCE_KINDS = frozenset(
    {
        "generator_permit",
        "building_permit",
        "epa_echo_pdf",
        "county_pdf",
        "state_pdf",
    }
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


async def chunk_and_persist_edgar(
    session: AsyncSession,
    *,
    document_id: int,
    body: str,
    target_tokens: int = 300,
    overlap: int = 50,
) -> int:
    """Chunk ``body`` and replace the ``edgar_passages`` rows for
    ``document_id``. Returns the number of chunks persisted.

    Idempotent: existing rows for the document are deleted first. Empty
    text is a no-op (returns 0).
    """
    chunks = list(chunk_text(body or "", target_tokens=target_tokens, overlap=overlap))
    # DELETE always runs (even on empty input) so re-ingestion that
    # truncates a document also clears stale chunks.
    await session.execute(
        text("DELETE FROM edgar_passages WHERE document_id = :doc_id"),
        {"doc_id": document_id},
    )
    if not chunks:
        return 0
    await session.execute(
        text(
            "INSERT INTO edgar_passages "
            "(document_id, ord, text, char_start, char_end, token_count, tokenizer) "
            "VALUES (:document_id, :ord, :text, :char_start, :char_end, "
            ":token_count, :tokenizer)"
        ),
        [
            {
                "document_id": document_id,
                "ord": c["ord"],
                "text": c["text"],
                "char_start": c["char_start"],
                "char_end": c["char_end"],
                "token_count": c["token_count"],
                "tokenizer": c["tokenizer"],
            }
            for c in chunks
        ],
    )
    return len(chunks)


async def chunk_and_persist_permit(
    session: AsyncSession,
    *,
    source_kind: str,
    source_doc_id: str,
    body: str,
    target_tokens: int = 300,
    overlap: int = 50,
) -> int:
    """Chunk ``body`` and replace the ``permit_passages`` rows for the
    given polymorphic ``(source_kind, source_doc_id)``.

    Returns the number of chunks persisted.
    """
    if source_kind not in PERMIT_SOURCE_KINDS:
        raise ValueError(
            f"unknown source_kind {source_kind!r}; allowed={sorted(PERMIT_SOURCE_KINDS)}"
        )
    chunks = list(chunk_text(body or "", target_tokens=target_tokens, overlap=overlap))
    await session.execute(
        text(
            "DELETE FROM permit_passages "
            "WHERE source_kind = :source_kind AND source_doc_id = :source_doc_id"
        ),
        {"source_kind": source_kind, "source_doc_id": str(source_doc_id)},
    )
    if not chunks:
        return 0
    await session.execute(
        text(
            "INSERT INTO permit_passages "
            "(source_kind, source_doc_id, ord, text, char_start, char_end, "
            " token_count, tokenizer) "
            "VALUES (:source_kind, :source_doc_id, :ord, :text, :char_start, "
            " :char_end, :token_count, :tokenizer)"
        ),
        [
            {
                "source_kind": source_kind,
                "source_doc_id": str(source_doc_id),
                "ord": c["ord"],
                "text": c["text"],
                "char_start": c["char_start"],
                "char_end": c["char_end"],
                "token_count": c["token_count"],
                "tokenizer": c["tokenizer"],
            }
            for c in chunks
        ],
    )
    return len(chunks)


__all__ = [
    "chunk_and_persist_edgar",
    "chunk_and_persist_permit",
    "PERMIT_SOURCE_KINDS",
]
