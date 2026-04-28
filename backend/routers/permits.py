"""
Permits endpoints.
Prefix: /api/permits

When MOCK_DATA=0, queries generator_permits table for real data.
When MOCK_DATA=1, returns mock permit data.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from db.models import GeneratorPermit
from schemas.common import CoverageEnvelope, CoverageMeta, LineageMeta

MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"

router = APIRouter(prefix="/api/permits", tags=["permits"])


def _permit_to_dict(p: GeneratorPermit) -> dict:
    """Convert GeneratorPermit model to dict."""
    d = {}
    for col in GeneratorPermit.__table__.columns:
        val = getattr(p, col.name, None)
        if isinstance(val, (datetime, date)):
            val = val.isoformat()
        d[col.name] = val
    return d


@router.get("/")
async def permits_list(
    state: Optional[str] = Query(None, description="Filter by state code"),
    source: Optional[str] = Query(None, description="Filter by permit source (epa_echo, tceq, etc.)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    if MOCK_ENABLED:
        from data.mock_data import get_permits_data, COLORS

        return CoverageEnvelope(
            data={"data": get_permits_data(), "colors": COLORS},
            lineage=LineageMeta(
                source_url="mock",
                retrieved_at=datetime.utcnow(),
                parser_version="mock-v1",
                confidence=0.5,
            ),
            coverage=CoverageMeta(pillar="permits"),
        )

    # Real DB query
    query = select(GeneratorPermit)
    count_query = select(func.count(GeneratorPermit.id))

    if state:
        query = query.where(GeneratorPermit.state_code == state.upper())
        count_query = count_query.where(GeneratorPermit.state_code == state.upper())
    if source:
        query = query.where(GeneratorPermit.source == source)
        count_query = count_query.where(GeneratorPermit.source == source)

    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    query = query.order_by(GeneratorPermit.id).offset(offset).limit(page_size)
    result = await db.execute(query)
    permits = result.scalars().all()

    # States for coverage metadata
    states_result = await db.execute(
        select(GeneratorPermit.state_code)
        .where(GeneratorPermit.state_code.isnot(None))
        .distinct()
    )
    states_included = [r[0] for r in states_result.fetchall()]

    return CoverageEnvelope(
        data={
            "data": [_permit_to_dict(p) for p in permits],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        lineage=LineageMeta(
            source_url="generator_permits",
            retrieved_at=datetime.utcnow(),
            parser_version="permits-v1.0.0",
            confidence=0.85,
        ),
        coverage=CoverageMeta(
            pillar="permits",
            states_included=states_included,
        ),
    )
