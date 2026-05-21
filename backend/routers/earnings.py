"""Earnings call transcripts API endpoints.

Prefix: ``/api/earnings``

Three endpoints, all wrapped in the shared lineage / coverage envelopes:

  * ``GET  /api/earnings`` — paged list of transcripts, newest first.
    Optional ``?ticker=...``, ``?company=...``, ``?quarter=...``,
    ``?limit=`` (default 50, max 200), ``?offset=``.
  * ``GET  /api/earnings/{transcript_id}`` — full detail for one
    transcript, plus the top-5 BM25 passages keyed off the
    transcript's most relevant terms (datacenter / AI / power /
    capex). Renders into the Earnings tab card stack.
  * ``GET  /api/companies/{company_id}/earnings`` — all transcripts
    for a tracked company resolved by ``companies.id``. We match the
    company's ``cik`` against ``earnings_transcripts.cik`` so the
    join works for entities that share a single SEC CIK (e.g. Intel).

All endpoints are read-only and return ``CoverageEnvelope``. The
``lineage.source_url`` points at the underlying Alpha Vantage call URL
so the UI can render a "View on Alpha Vantage" link with provenance.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import select, desc, func
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from db.models import Company, EarningsTranscript
from schemas.common import (
    CoverageEnvelope,
    CoverageMeta,
    LineageEnvelope,
    LineageMeta,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["earnings"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PARSER_VERSION = "earnings_transcripts.v1"
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200
PASSAGE_TOP_K = 5

# The BM25 query used on the detail endpoint to pull the most thematically
# relevant passages. Kept conservative so it works whether or not the
# transcript actually discusses datacenters — earnings calls overwhelmingly
# do but utility-only calls (Dominion, PG&E) may not.
_DETAIL_PASSAGE_QUERY = (
    "datacenter AI artificial intelligence power capex megawatt gigawatt"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(ts: Any) -> str | None:
    """Best-effort ISO8601 conversion. Returns None on falsy input."""
    if ts is None:
        return None
    if isinstance(ts, (datetime, date)):
        return ts.isoformat()
    return str(ts)


_TOP_QUOTE_MAX_CHARS = 140


def _truncate(s: str | None, limit: int = _TOP_QUOTE_MAX_CHARS) -> str | None:
    """Return ``s`` truncated to ``limit`` chars with ellipsis; passthrough None."""
    if not s:
        return None
    s = s.strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "\u2026"


def _pick_top_quote(row: EarningsTranscript) -> tuple[str | None, str | None]:
    """Return ``(quote, theme)`` for the card preview.

    Priority: first capex_mention.quote → first ai_power_mention.quote →
    guidance.raw_quote. ``theme`` is 'capex' / 'ai_power' / 'guidance' /
    None so the UI can colour-key the snippet. All quotes are verbatim
    substrings of ``raw_text`` (validated by ``earnings_extractor``).
    """
    for entry in (row.capex_mentions or []):
        q = (entry or {}).get("quote") if isinstance(entry, dict) else None
        if q:
            return _truncate(q), "capex"
    for entry in (row.ai_power_mentions or []):
        q = (entry or {}).get("quote") if isinstance(entry, dict) else None
        if q:
            return _truncate(q), "ai_power"
    if isinstance(row.guidance, dict):
        q = row.guidance.get("raw_quote") or row.guidance.get("quote")
        if q:
            return _truncate(q), "guidance"
    return None, None


def _guidance_quote(row: EarningsTranscript) -> str | None:
    """Compact guidance one-liner for the company-timeline rows."""
    if not isinstance(row.guidance, dict):
        return None
    return _truncate(
        row.guidance.get("raw_quote")
        or row.guidance.get("capex_outlook")
        or row.guidance.get("revenue_growth")
    )


def _serialize_transcript_summary(row: EarningsTranscript) -> dict[str, Any]:
    """Lightweight projection used by the list endpoints."""
    top_quote, top_quote_theme = _pick_top_quote(row)
    return {
        "id": row.id,
        "cik": row.cik,
        "ticker": row.ticker,
        "company_name": row.company_name,
        "quarter": row.quarter,
        "fiscal_year": row.fiscal_year,
        "fiscal_quarter": row.fiscal_quarter,
        "call_date": _iso(row.call_date),
        "speaker_count": row.speaker_count,
        "word_count": row.word_count,
        "extracted_at": _iso(row.extracted_at),
        "retrieved_at": _iso(row.retrieved_at),
        "sentiment": {
            "ai_demand": row.sentiment_ai_demand,
            "power_constraints": row.sentiment_power_constraints,
            "datacenter_capex": row.sentiment_datacenter_capex,
            "overall": row.sentiment_overall,
        },
        "has_guidance": bool(row.guidance),
        "capex_mention_count": len(row.capex_mentions or []),
        "ai_power_mention_count": len(row.ai_power_mentions or []),
        "competitive_mention_count": len(row.competitive_mentions or []),
        "mw_capacity_mention_count": len(row.mw_capacity_mentions or []),
        "transcript_url": row.transcript_url,
        # Card-preview fields (see frontend EarningsTab / CompaniesTab timeline)
        "top_quote": top_quote,
        "top_quote_theme": top_quote_theme,
        "guidance_quote": _guidance_quote(row),
    }


def _serialize_transcript_detail(row: EarningsTranscript) -> dict[str, Any]:
    """Full row projection for the detail endpoint."""
    base = _serialize_transcript_summary(row)
    base.update({
        "guidance": row.guidance,
        "capex_mentions": row.capex_mentions or [],
        "ai_power_mentions": row.ai_power_mentions or [],
        "competitive_mentions": row.competitive_mentions or [],
        "mw_capacity_mentions": row.mw_capacity_mentions or [],
        "extractor_version": row.extractor_version,
    })
    return base


def _freshness_status(retrieved_at: datetime | None) -> str:
    """Return ``ok`` if retrieved in the last 30 days, else ``stale``."""
    if retrieved_at is None:
        return "unknown"
    age = datetime.utcnow() - (
        retrieved_at if retrieved_at.tzinfo is None
        else retrieved_at.replace(tzinfo=None)
    )
    return "ok" if age.days <= 30 else "stale"


async def _fetch_top_passages(
    db: AsyncSession, transcript_id: int, k: int = PASSAGE_TOP_K
) -> list[dict[str, Any]]:
    """Return the top-K BM25-ranked passages for a transcript.

    Uses the same ``websearch_to_tsquery`` + ``ts_rank_cd`` shape as
    the ``search_documents`` MCP tool. We score against a fixed
    thematic query (datacenter / AI / power / capex). The Postgres
    ``tsv`` column is maintained by the trigger from migration 019.
    Returns an empty list on any DB error so the detail endpoint
    still renders the parent row.
    """
    try:
        result = await db.execute(
            sa_text(
                """
                SELECT
                  passage_id::text AS passage_id,
                  ord,
                  text,
                  speaker,
                  section,
                  char_start,
                  char_end,
                  token_count,
                  ts_rank_cd(tsv, websearch_to_tsquery('english', :q), 32) AS score
                FROM earnings_passages
                WHERE document_id = :doc
                  AND tsv @@ websearch_to_tsquery('english', :q)
                ORDER BY score DESC
                LIMIT :k
                """
            ),
            {"doc": transcript_id, "q": _DETAIL_PASSAGE_QUERY, "k": k},
        )
        rows = result.mappings().all()
    except Exception as exc:
        logger.warning(
            "earnings.detail.passage_fetch_failed",
            extra={
                "transcript_id": transcript_id,
                "error_class": type(exc).__name__,
                "error": str(exc),
            },
        )
        return []

    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "passage_id": r["passage_id"],
            "ord": r["ord"],
            "text": r["text"],
            "speaker": r["speaker"],
            "section": r["section"],
            "char_start": r["char_start"],
            "char_end": r["char_end"],
            "token_count": r["token_count"],
            "score": float(r["score"] or 0.0),
        })
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/api/earnings")
async def list_earnings(
    ticker: str | None = Query(default=None, max_length=16),
    company: str | None = Query(default=None, max_length=255),
    quarter: str | None = Query(default=None, max_length=8),
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> CoverageEnvelope:
    """List earnings transcripts, newest first.

    Filters are AND-combined. ``company`` matches against
    ``company_name`` exactly (case-sensitive) — the Earnings tab UI
    knows the canonical display names.
    """
    stmt = select(EarningsTranscript)

    if ticker:
        stmt = stmt.where(EarningsTranscript.ticker == ticker.strip().upper())
    if company:
        stmt = stmt.where(EarningsTranscript.company_name == company)
    if quarter:
        stmt = stmt.where(EarningsTranscript.quarter == quarter.strip().upper())

    # Total count for pagination — same filters, COUNT(*).
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(
        desc(EarningsTranscript.call_date),
        desc(EarningsTranscript.retrieved_at),
    ).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    serialized = [_serialize_transcript_summary(r) for r in rows]

    # Surface the newest row's lineage for the envelope so the UI can
    # render a "Last refreshed" badge.
    latest_retrieved = rows[0].retrieved_at if rows else None
    freshness = _freshness_status(latest_retrieved)

    return CoverageEnvelope(
        data={
            "items": serialized,
            "total": int(total),
            "limit": limit,
            "offset": offset,
            "filters": {
                "ticker": ticker,
                "company": company,
                "quarter": quarter,
            },
        },
        lineage=LineageMeta(
            source_url="https://www.alphavantage.co/query"
                       "?function=EARNINGS_CALL_TRANSCRIPT",
            retrieved_at=latest_retrieved,
            parser_version=PARSER_VERSION,
            confidence=0.92,
        ),
        coverage=CoverageMeta(
            pillar="earnings_intelligence",
            states_included=["US"],
            states_excluded_with_reason={
                "non_US": (
                    "Foreign private issuers (TSMC, ASML, ASE, "
                    "GlobalFoundries) excluded — Alpha Vantage transcript "
                    "coverage is US-only."
                ),
            },
            freshness_status=freshness,
        ),
    )


@router.get("/api/earnings/{transcript_id}")
async def get_earnings_detail(
    transcript_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> LineageEnvelope:
    """Return a single transcript with top-5 BM25 passages.

    The passage list is used by the Earnings tab to render "Top quoted
    moments" alongside the LLM-extracted highlights. Passages are
    ranked against a fixed datacenter/AI/power/capex query.
    """
    row = (
        await db.execute(
            select(EarningsTranscript).where(
                EarningsTranscript.id == transcript_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="transcript not found")

    detail = _serialize_transcript_detail(row)
    passages = await _fetch_top_passages(db, transcript_id, k=PASSAGE_TOP_K)
    detail["top_passages"] = passages

    return LineageEnvelope(
        data=detail,
        lineage=LineageMeta(
            source_url=row.transcript_url
                       or "https://www.alphavantage.co/query",
            retrieved_at=row.retrieved_at,
            parser_version=PARSER_VERSION,
            confidence=0.92,
        ),
    )


@router.get("/api/earnings/{transcript_id}/transcript-text")
async def get_earnings_transcript_text(
    transcript_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> LineageEnvelope:
    """Return the cached raw transcript text for in-app reading.

    The Alpha Vantage transcript URL is an API endpoint that requires an
    apikey, so it isn't a useful external link. We've already cached the
    full text on ingest — surface it here so the UI can render it in a
    scrollable block without leaking the apikey.
    """
    row = (
        await db.execute(
            select(EarningsTranscript).where(
                EarningsTranscript.id == transcript_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="transcript not found")

    return LineageEnvelope(
        data={
            "transcript_id": row.id,
            "ticker": row.ticker,
            "company_name": row.company_name,
            "quarter": row.quarter,
            "call_date": _iso(row.call_date),
            "speaker_count": row.speaker_count,
            "word_count": row.word_count,
            "raw_text": row.raw_text or "",
        },
        lineage=LineageMeta(
            source_url="https://www.alphavantage.co/documentation/#earnings-call-transcript",
            retrieved_at=row.retrieved_at,
            parser_version=PARSER_VERSION,
            confidence=0.92,
        ),
    )


@router.get("/api/companies/{company_id}/earnings")
async def list_company_earnings(
    company_id: int = Path(..., ge=1),
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> CoverageEnvelope:
    """Return all earnings transcripts for one company in ``companies``.

    Resolution: we look up the company's ``cik`` (or fall back to
    ``ticker``) and match against ``earnings_transcripts.cik``. A 404
    is returned if no company row exists for the id, but the result
    list may be empty (e.g. private companies, FPIs).
    """
    company = (
        await db.execute(select(Company).where(Company.id == company_id))
    ).scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")

    stmt = select(EarningsTranscript)
    if company.cik:
        stmt = stmt.where(EarningsTranscript.cik == company.cik)
    elif company.ticker:
        stmt = stmt.where(
            EarningsTranscript.ticker == company.ticker.strip().upper()
        )
    else:
        # No identifiers we can match on — return empty list cleanly.
        stmt = stmt.where(sa_text("false"))

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(
        desc(EarningsTranscript.call_date),
        desc(EarningsTranscript.retrieved_at),
    ).offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    serialized = [_serialize_transcript_summary(r) for r in rows]
    latest_retrieved = rows[0].retrieved_at if rows else None
    freshness = _freshness_status(latest_retrieved)

    return CoverageEnvelope(
        data={
            "company_id": company.id,
            "canonical_name": company.canonical_name,
            "ticker": company.ticker,
            "cik": company.cik,
            "items": serialized,
            "total": int(total),
            "limit": limit,
            "offset": offset,
        },
        lineage=LineageMeta(
            source_url="https://www.alphavantage.co/query"
                       "?function=EARNINGS_CALL_TRANSCRIPT",
            retrieved_at=latest_retrieved,
            parser_version=PARSER_VERSION,
            confidence=0.92,
        ),
        coverage=CoverageMeta(
            pillar="earnings_intelligence",
            states_included=["US"],
            freshness_status=freshness,
        ),
    )


__all__ = ["router"]
