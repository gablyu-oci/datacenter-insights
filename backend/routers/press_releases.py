"""
Press release endpoints — Phase 2 (AC3).
Prefix: /api/press-releases

Returns recent on-topic IR press releases scraped by
ingestion.press_releases. The Power Contracts modal links to these via
`?company=Microsoft` query.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import select, desc

from db.session import async_session_factory
from db.models import PressRelease
from schemas.common import CoverageEnvelope, CoverageMeta, LineageMeta

MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"

router = APIRouter(prefix="/api/press-releases", tags=["press_releases"])


def _serialize(row: PressRelease) -> dict:
    return {
        "id": row.id,
        "company_canon": row.company_canon,
        "source_url": row.source_url,
        "title": row.title,
        "summary": row.summary,
        "excerpt": row.excerpt,
        "matched_terms": row.matched_terms,
        "published_date": row.published_date.isoformat() if row.published_date else None,
        "retrieved_at": row.retrieved_at.isoformat() if row.retrieved_at else None,
    }


@router.get("/recent")
async def recent(
    company: str | None = Query(default=None),
    days: int = Query(default=180, ge=1, le=720),
    limit: int = Query(default=50, ge=1, le=500),
):
    """Return recent IR press releases. Filter by canonical company name
    (e.g. ?company=Microsoft) and lookback in days.
    """
    if MOCK_ENABLED:
        return CoverageEnvelope(
            data={"data": [
                {"company_canon": "Microsoft",
                 "title": "Microsoft signs 1.2 GW renewables PPA",
                 "source_url": "https://news.microsoft.com/example",
                 "published_date": "2026-04-15",
                 "matched_terms": "GW,PPA,datacenter"},
            ]},
            lineage=LineageMeta(
                source_url="mock", retrieved_at=datetime.utcnow(),
                parser_version="press-v1", confidence=0.5,
            ),
            coverage=CoverageMeta(pillar="press_releases"),
        )

    cutoff = (datetime.utcnow() - timedelta(days=days)).date()
    async with async_session_factory() as session:
        stmt = select(PressRelease).where(
            (PressRelease.published_date >= cutoff)
            | (PressRelease.published_date.is_(None))
        )
        if company:
            stmt = stmt.where(PressRelease.company_canon == company)
        stmt = stmt.order_by(
            desc(PressRelease.published_date),
            desc(PressRelease.retrieved_at),
        ).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

    serialized = [_serialize(r) for r in rows]
    return CoverageEnvelope(
        data={"data": serialized, "count": len(serialized)},
        lineage=LineageMeta(
            source_url="internal://press-release-scraper",
            retrieved_at=datetime.utcnow(),
            parser_version="press-v1",
            confidence=0.55 if serialized else 0.0,
        ),
        coverage=CoverageMeta(
            pillar="press_releases",
            freshness_status="ok" if serialized else "unknown",
        ),
    )
