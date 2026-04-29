"""
Satellite site-tracking endpoints.
Prefix: /api/satellite

When MOCK_DATA=0, queries the sites table for real site data with coordinates.
When MOCK_DATA=1, returns curated mock satellite sites from data/mock_data.py.
"""
from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from db.models import Site
from schemas.common import CoverageEnvelope, CoverageMeta, LineageEnvelope, LineageMeta

MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"

router = APIRouter(prefix="/api/satellite", tags=["satellite"])

# Company brand colors for the map UI (used in both paths)
_COLORS = {
    "Microsoft": "#0078D4",
    "AWS": "#FF9900",
    "Google": "#4285F4",
    "Meta": "#1877F2",
    "Oracle": "#C74634",
    "Apple": "#555555",
    "Equinix": "#E31837",
}


def _site_to_satellite_dict(site: Site) -> dict:
    """Convert a Site ORM row into the shape the satellite frontend expects."""
    return {
        "name": site.building_name or site.campus_name or site.aterio_dc_uid or "Unknown",
        "company": site.provider_name or "Unknown",
        "lat": site.latitude,
        "lon": site.longitude,
        "address": site.full_address or _build_address(site),
        "status": site.stage or "Unknown",
        "size_acres": site.site_acreage,
        "power_capacity_mw": site.power_capacity_mw,
        "construction_pct": site.pct_construction,
        "state_code": site.state_code,
        "county_name": site.county_name,
        "aterio_dc_uid": site.aterio_dc_uid,
    }


def _build_address(site: Site) -> str:
    """Fallback address from city/state fields when full_address is missing."""
    parts = [p for p in (site.city_name, site.state_code) if p]
    return ", ".join(parts) if parts else "Unknown"


@router.get("/")
async def satellite_sites(
    state: str | None = Query(None, description="Filter by state code (e.g. VA, TX)"),
    provider: str | None = Query(None, description="Filter by provider name (partial match)"),
    db: AsyncSession = Depends(get_db),
):
    if MOCK_ENABLED:
        from data.mock_data import get_satellite_sites, COLORS

        return LineageEnvelope(
            data={"data": get_satellite_sites(), "colors": COLORS},
            lineage=LineageMeta(
                source_url="curated",
                retrieved_at=datetime.utcnow(),
                parser_version="satellite:1.0.0",
                confidence=0.95,
            ),
        )

    # Real DB path: sites with non-null coordinates
    query = select(Site).where(
        Site.latitude.isnot(None),
        Site.longitude.isnot(None),
    )
    count_query = select(func.count(Site.id)).where(
        Site.latitude.isnot(None),
        Site.longitude.isnot(None),
    )

    if state:
        query = query.where(Site.state_code == state.upper())
        count_query = count_query.where(Site.state_code == state.upper())
    if provider:
        query = query.where(Site.provider_name.ilike(f"%{provider}%"))
        count_query = count_query.where(Site.provider_name.ilike(f"%{provider}%"))

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(query.order_by(Site.id))
    sites = result.scalars().all()

    # Distinct states for coverage metadata
    states_result = await db.execute(
        select(Site.state_code)
        .where(Site.latitude.isnot(None), Site.longitude.isnot(None), Site.state_code.isnot(None))
        .distinct()
    )
    states_included = [r[0] for r in states_result.fetchall()]

    return CoverageEnvelope(
        data={
            "data": [_site_to_satellite_dict(s) for s in sites],
            "colors": _COLORS,
            "total": total,
        },
        lineage=LineageMeta(
            source_url="aterio_csv",
            retrieved_at=datetime.utcnow(),
            parser_version="satellite:1.1.0",
            confidence=0.85,
        ),
        coverage=CoverageMeta(pillar="satellite", states_included=states_included),
    )


# Alias for the /api/satellite/sites path
@router.get("/sites")
async def satellite_sites_alias(
    state: str | None = Query(None),
    provider: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await satellite_sites(state=state, provider=provider, db=db)
