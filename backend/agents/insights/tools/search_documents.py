"""``search_documents`` MCP tool — Phase B.1 BM25-only document retrieval.

Spec: ``docs/ai_insights_v2_spec.md`` §5.3
Architecture: ``docs/ai_insights_v2_phases_bcd_architecture.md`` §1, §2

This tool lets the synthesis agent ground claims in the text of EDGAR
filings and permit documents. Phase B.1 ships BM25-only via Postgres
``tsvector`` + ``websearch_to_tsquery`` + ``ts_rank_cd``.
Phase B.2 (pgvector hybrid via RRF) is gated on recall@8 < 0.85 on the
30-pair golden set; that work is NOT in this file.

Hardening:
  * Empty / whitespace-only query is rejected up front
    (``ok=False, error='empty_query'``) so the gate never accepts a
    no-op call that ranks every passage equally.
  * ``k`` is clamped at 50 (``MAX_K``); requests above the cap are
    truncated and ``truncated=True`` is set.
  * Source mode is gated on a literal allowlist (``edgar`` / ``permits``
    / ``all``).
  * The tool uses the read-only engine (``ai_agent`` role) — same path
    as ``query_database`` so a privilege escalation in this tool would
    require the same role compromise.
  * All failure modes return a structured ``{ok: False, error, detail}``
    dict; the tool never raises into the OpenClaw forwarder.
  * Latency is logged on every successful call.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import text

from ..specs.skill_context import SkillContext
from ..db.session import get_readonly_engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_K = 8
MAX_K = 50

ALLOWED_SOURCES = ("edgar", "permits", "earnings", "all")


# ---------------------------------------------------------------------------
# Internal queries
# ---------------------------------------------------------------------------

# Edgar branch — joins edgar_extractions for citation metadata. Companies
# table is *not* joined here; the agent can resolve cik->company via
# query_database in a follow-up call. Keeping the query slim wins
# latency.
_EDGAR_SQL = text(
    """
    SELECT
      ep.passage_id::text AS passage_id,
      ep.text             AS passage_text,
      ts_rank_cd(ep.tsv, websearch_to_tsquery('english', :q), 32) AS score,
      ee.cik              AS cik,
      ee.form_type        AS form_type,
      ee.edgar_url        AS url,
      ee.retrieved_at     AS retrieved_at,
      ee.buyer_canonical  AS company
    FROM edgar_passages ep
    JOIN edgar_extractions ee ON ee.id = ep.document_id
    WHERE ep.tsv @@ websearch_to_tsquery('english', :q)
    ORDER BY score DESC
    LIMIT :k
    """
)

# Permits branch — text only; metadata enrichment is dispatched on
# source_kind in Python because the parent tables diverge (per ADR-002).
_PERMIT_SQL = text(
    """
    SELECT
      pp.passage_id::text   AS passage_id,
      pp.source_kind        AS source_kind,
      pp.source_doc_id      AS source_doc_id,
      pp.text               AS passage_text,
      ts_rank_cd(pp.tsv, websearch_to_tsquery('english', :q), 32) AS score
    FROM permit_passages pp
    WHERE pp.tsv @@ websearch_to_tsquery('english', :q)
    ORDER BY score DESC
    LIMIT :k
    """
)

# Earnings branch — joins earnings_transcripts for citation metadata
# (speaker, section, ticker, quarter, transcript_url). Mirrors the
# edgar/permits SQL shape so the merge in source='all' is uniform.
_EARNINGS_SQL = text(
    """
    SELECT
      ep.passage_id::text AS passage_id,
      ep.text             AS passage_text,
      ep.speaker          AS speaker,
      ep.section          AS section,
      ts_rank_cd(ep.tsv, websearch_to_tsquery('english', :q), 32) AS score,
      et.cik              AS cik,
      et.ticker           AS ticker,
      et.company_name     AS company,
      et.quarter          AS quarter,
      et.call_date        AS call_date,
      et.transcript_url   AS url,
      et.retrieved_at     AS retrieved_at
    FROM earnings_passages ep
    JOIN earnings_transcripts et ON et.id = ep.document_id
    WHERE ep.tsv @@ websearch_to_tsquery('english', :q)
    ORDER BY score DESC
    LIMIT :k
    """
)


# ---------------------------------------------------------------------------
# Tool entrypoint
# ---------------------------------------------------------------------------


async def search_documents(
    query: str,
    source: Literal["edgar", "permits", "earnings", "all"] = "all",
    k: int = DEFAULT_K,
    *,
    ctx: SkillContext | None = None,
) -> dict[str, Any]:
    """BM25 passage retrieval over EDGAR filings + permit documents.

    Returns::

        {
          "ok": bool,
          "passages": [
             {
               "text": str,
               "citation": {
                 "source": "edgar" | "permits",
                 "company": str | None,
                 "filing_type": str | None,
                 "url": str | None,
                 "retrieved_at": str (ISO8601) | None,
                 "passage_id": str,
               },
               "score": float,
             }, ...
          ],
          "row_count": int,
          "truncated": bool,
          "diagnostics": {"k_requested": int, "k_returned": int,
                          "latency_ms": int, "source": str}
        }

    On invalid input returns ``{ok: False, error, detail?}``. Never raises.
    """
    # ----------- input validation -----------
    if not query or not query.strip():
        return {"ok": False, "error": "empty_query"}

    if source not in ALLOWED_SOURCES:
        return {
            "ok": False,
            "error": "invalid_source",
            "detail": {"source": source, "allowed": list(ALLOWED_SOURCES)},
        }

    try:
        k_int = int(k)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_k", "detail": {"k": k}}

    if k_int < 1:
        return {"ok": False, "error": "invalid_k", "detail": {"k": k_int}}

    truncated = k_int > MAX_K
    effective_k = min(k_int, MAX_K)

    # ----------- execute -----------
    engine = get_readonly_engine()
    started = time.perf_counter()

    edgar_rows: list[dict[str, Any]] = []
    permit_rows: list[dict[str, Any]] = []
    earnings_rows: list[dict[str, Any]] = []

    try:
        async with engine.connect() as conn:
            if source in ("edgar", "all"):
                result = await conn.execute(
                    _EDGAR_SQL, {"q": query, "k": effective_k}
                )
                edgar_rows = [dict(r) for r in result.mappings().all()]
            if source in ("permits", "all"):
                result = await conn.execute(
                    _PERMIT_SQL, {"q": query, "k": effective_k}
                )
                permit_rows = [dict(r) for r in result.mappings().all()]
            if source in ("earnings", "all"):
                result = await conn.execute(
                    _EARNINGS_SQL, {"q": query, "k": effective_k}
                )
                earnings_rows = [dict(r) for r in result.mappings().all()]
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.warning(
            "ai_insights.search_documents.error",
            extra={
                "error": str(exc),
                "error_class": type(exc).__name__,
                "source": source,
                "latency_ms": latency_ms,
            },
        )
        return {
            "ok": False,
            "error": "search_failed",
            "detail": {"reason": str(exc), "error_class": type(exc).__name__},
        }

    # ----------- shape -----------
    passages: list[dict[str, Any]] = []
    for row in edgar_rows:
        passages.append(_shape_edgar_row(row))
    for row in permit_rows:
        passages.append(_shape_permit_row(row))
    for row in earnings_rows:
        passages.append(_shape_earnings_row(row))

    # Re-rank merged list by score; clamp to effective_k for source='all'.
    passages.sort(key=lambda p: p["score"], reverse=True)
    passages = passages[:effective_k]

    latency_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "ai_insights.search_documents.ok",
        extra={
            "source": source,
            "k_requested": k_int,
            "k_returned": len(passages),
            "latency_ms": latency_ms,
        },
    )

    return {
        "ok": True,
        "passages": passages,
        "row_count": len(passages),
        "truncated": truncated,
        "diagnostics": {
            "k_requested": k_int,
            "k_returned": len(passages),
            "latency_ms": latency_ms,
            "source": source,
        },
    }


# ---------------------------------------------------------------------------
# Citation shaping
# ---------------------------------------------------------------------------


def _iso(ts: Any) -> str | None:
    """Best-effort ISO8601 conversion. Returns None on falsy input."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.isoformat()
    return str(ts)


def _shape_edgar_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": row.get("passage_text") or "",
        "score": float(row.get("score") or 0.0),
        "citation": {
            "source": "edgar",
            "company": row.get("company"),
            "filing_type": row.get("form_type"),
            "url": row.get("url"),
            "retrieved_at": _iso(row.get("retrieved_at")),
            "passage_id": row.get("passage_id"),
        },
    }


def _shape_permit_row(row: dict[str, Any]) -> dict[str, Any]:
    """Shape a permit_passages row as a citation. Polymorphic source — we
    map the discriminator to a coarse ``filing_type`` label and leave
    ``company`` / ``url`` null because resolving them requires a join
    against the parent table that diverges per source_kind. The agent can
    follow up with ``query_database`` if needed.
    """
    kind = row.get("source_kind") or ""
    return {
        "text": row.get("passage_text") or "",
        "score": float(row.get("score") or 0.0),
        "citation": {
            "source": "permits",
            "company": None,
            "filing_type": kind,
            "url": None,
            "retrieved_at": None,
            "passage_id": row.get("passage_id"),
        },
    }


def _shape_earnings_row(row: dict[str, Any]) -> dict[str, Any]:
    """Shape an earnings_passages row as a citation.

    Earnings citations extend the base envelope with two transcript-only
    keys (speaker, section). The frontend insight-card renderer treats
    these as optional adornments.
    """
    quarter = row.get("quarter")
    return {
        "text": row.get("passage_text") or "",
        "score": float(row.get("score") or 0.0),
        "citation": {
            "source": "earnings",
            "company": row.get("company"),
            "filing_type": f"earnings_call_{quarter}" if quarter else "earnings_call",
            "url": row.get("url"),
            "retrieved_at": _iso(row.get("retrieved_at")),
            "passage_id": row.get("passage_id"),
            "speaker": row.get("speaker"),
            "section": row.get("section"),
        },
    }


__all__ = ["search_documents", "DEFAULT_K", "MAX_K", "ALLOWED_SOURCES"]
