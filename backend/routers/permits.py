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
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from db.models import Company, GeneratorPermit
from schemas.common import CoverageEnvelope, CoverageMeta, LineageMeta

MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"

# Phase 1.5: data-center-relevant fuel types (per PRD §5)
DATACENTER_FUEL_TYPES = {"diesel", "natural_gas", "dual_fuel"}

router = APIRouter(prefix="/api/permits", tags=["permits"])


def _permit_to_dict(p: GeneratorPermit, parent_name: Optional[str] = None) -> dict:
    """Convert GeneratorPermit model to dict, optionally with joined parent name."""
    d = {}
    for col in GeneratorPermit.__table__.columns:
        val = getattr(p, col.name, None)
        if isinstance(val, (datetime, date)):
            val = val.isoformat()
        d[col.name] = val
    d["resolved_company_name"] = parent_name
    # Surface a clickable source URL (raw_payload may carry one)
    raw = d.get("raw_payload") or {}
    d["source_url"] = (
        raw.get("source_url") if isinstance(raw, dict) else None
    ) or d.get("source_url")
    return d


@router.get("/")
async def permits_list(
    state: Optional[str] = Query(None, description="Filter by state code"),
    source: Optional[str] = Query(None, description="Filter by permit source (epa_echo, tceq, etc.)"),
    fuel_type: Optional[str] = Query(
        None,
        description=(
            "Comma-separated fuel types (diesel,natural_gas,dual_fuel). "
            "Empty/omitted -> all fuel types."
        ),
    ),
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

    # Real DB query -- LEFT JOIN companies to resolve parent name in one trip.
    query = (
        select(GeneratorPermit, Company.canonical_name)
        .outerjoin(Company, Company.id == GeneratorPermit.resolved_company_id)
    )
    count_query = select(func.count(GeneratorPermit.id))

    if state:
        query = query.where(GeneratorPermit.state_code == state.upper())
        count_query = count_query.where(GeneratorPermit.state_code == state.upper())
    if source:
        query = query.where(GeneratorPermit.source == source)
        count_query = count_query.where(GeneratorPermit.source == source)

    # Fuel-type filter -- comma-separated list. Default: no filter (all rows).
    # Real-world fuel_type values are mixed-case and may be semicolon-joined
    # (e.g. PJM emits "Natural Gas; Other"), so we match each requested fuel
    # via case-insensitive substring (ILIKE %fuel%) and OR the predicates.
    # Map our canonical hints to upstream substrings.
    FUEL_HINT_MAP = {
        "diesel": ["diesel", "oil"],
        "natural_gas": ["natural gas", "methane"],
        "dual_fuel": ["dual fuel", "dual-fuel"],
    }
    requested_fuels: Optional[list[str]] = None
    if fuel_type:
        requested_fuels = [f.strip().lower() for f in fuel_type.split(",") if f.strip()]
        if requested_fuels:
            patterns: list[str] = []
            for f in requested_fuels:
                patterns.extend(FUEL_HINT_MAP.get(f, [f]))
            ilike_clauses = [
                GeneratorPermit.fuel_type.ilike(f"%{p}%") for p in patterns
            ]
            query = query.where(or_(*ilike_clauses))
            count_query = count_query.where(or_(*ilike_clauses))

    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    query = query.order_by(GeneratorPermit.id.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    rows = result.all()

    # States for coverage metadata
    states_result = await db.execute(
        select(GeneratorPermit.state_code)
        .where(GeneratorPermit.state_code.isnot(None))
        .distinct()
    )
    states_included = sorted([r[0] for r in states_result.fetchall() if r[0]])

    # Distinct sources (for the citation footer)
    sources_result = await db.execute(
        select(GeneratorPermit.source)
        .where(GeneratorPermit.source.isnot(None))
        .distinct()
    )
    sources_included = sorted([r[0] for r in sources_result.fetchall() if r[0]])

    return CoverageEnvelope(
        data={
            "data": [_permit_to_dict(p, parent_name) for (p, parent_name) in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "fuel_types_requested": requested_fuels,
            "sources_included": sources_included,
        },
        lineage=LineageMeta(
            source_url="generator_permits",
            retrieved_at=datetime.utcnow(),
            parser_version="permits-v1.1.0",
            confidence=0.85,
        ),
        coverage=CoverageMeta(
            pillar="permits",
            states_included=states_included,
        ),
    )


@router.get("/datacenter")
async def permits_datacenter(
    state: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Convenience endpoint pre-filtered to data-center-relevant fuel types.
    Equivalent to /?fuel_type=diesel,natural_gas,dual_fuel."""
    return await permits_list(
        state=state,
        source=None,
        fuel_type=",".join(sorted(DATACENTER_FUEL_TYPES)),
        page=page,
        page_size=page_size,
        db=db,
    )
