"""
Coverage metadata endpoints -- Phase 1A real DB queries.
Prefix: /api/coverage
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from db.models import DataCoverage
from schemas.common import LineageEnvelope, LineageMeta

router = APIRouter(prefix="/api/coverage", tags=["coverage"])

_LINEAGE = LineageMeta(
    source_url="data_coverage_table",
    retrieved_at=datetime.utcnow(),
    parser_version="coverage-v1.0.0",
    confidence=1.0,
)


def _coverage_to_dict(row: DataCoverage) -> dict:
    """Convert DataCoverage model to dict."""
    d = {}
    for col in DataCoverage.__table__.columns:
        val = getattr(row, col.name, None)
        if isinstance(val, datetime):
            val = val.isoformat()
        d[col.name] = val
    return d


@router.get("/")
async def coverage_overview(db: AsyncSession = Depends(get_db)):
    """Full data_coverage matrix."""
    result = await db.execute(
        select(DataCoverage).order_by(DataCoverage.pillar, DataCoverage.state_code)
    )
    rows = result.scalars().all()
    return LineageEnvelope(
        data=[_coverage_to_dict(r) for r in rows],
        lineage=_LINEAGE,
    )


@router.get("/by-state/{state_code}")
async def coverage_by_state(state_code: str, db: AsyncSession = Depends(get_db)):
    """Coverage for one state across all pillars.

    Registered before /{pillar} to avoid path conflicts.
    """
    result = await db.execute(
        select(DataCoverage)
        .where(DataCoverage.state_code == state_code.upper())
        .order_by(DataCoverage.pillar)
    )
    rows = result.scalars().all()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No coverage data found for state {state_code.upper()}",
        )
    return LineageEnvelope(
        data=[_coverage_to_dict(r) for r in rows],
        lineage=_LINEAGE,
    )


@router.get("/{pillar}")
async def coverage_by_pillar(pillar: str, db: AsyncSession = Depends(get_db)):
    """Coverage for one pillar across all states."""
    result = await db.execute(
        select(DataCoverage)
        .where(DataCoverage.pillar == pillar)
        .order_by(DataCoverage.state_code)
    )
    rows = result.scalars().all()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No coverage data found for pillar '{pillar}'",
        )
    return LineageEnvelope(
        data=[_coverage_to_dict(r) for r in rows],
        lineage=_LINEAGE,
    )
