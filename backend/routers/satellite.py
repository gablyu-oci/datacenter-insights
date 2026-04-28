"""
Satellite site-tracking endpoints.
Prefix: /api/satellite

Note: the satellite data in mock_data.py is actually curated real data
(publicly announced sites with real coordinates and milestones), so it is
always returned regardless of MOCK_DATA, wrapped in a LineageEnvelope.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from data.mock_data import get_satellite_sites, COLORS
from schemas.common import LineageEnvelope, LineageMeta

router = APIRouter(prefix="/api/satellite", tags=["satellite"])


@router.get("/")
async def satellite_sites():
    return LineageEnvelope(
        data={"data": get_satellite_sites(), "colors": COLORS},
        lineage=LineageMeta(
            source_url="curated",
            retrieved_at=datetime.utcnow(),
            parser_version="satellite:1.0.0",
            confidence=0.95,
        ),
    )


# Alias for the /api/satellite/sites path
@router.get("/sites")
async def satellite_sites_alias():
    return LineageEnvelope(
        data={"data": get_satellite_sites(), "colors": COLORS},
        lineage=LineageMeta(
            source_url="curated",
            retrieved_at=datetime.utcnow(),
            parser_version="satellite:1.0.0",
            confidence=0.95,
        ),
    )
