"""
Power capacity, timeseries, announcements, and GW-summary endpoints.
Prefix: /api/power

When MOCK_DATA=0, queries the sites table for real power capacity data.
When MOCK_DATA=1, returns mock data from data/mock_data.py.
"""
from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from data.curated_deals import get_curated_deals, get_company_gw_summary
from agents.edgar_agent import fetch_real_8k_deals
from db.session import get_db
from db.models import Site
from schemas.common import CoverageEnvelope, CoverageMeta, LineageEnvelope, LineageMeta

MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"

router = APIRouter(prefix="/api/power", tags=["power"])

_MOCK_DISABLED_NOTE = "Mock data disabled. Set MOCK_DATA=1 to enable."


def _colors() -> dict:
    if MOCK_ENABLED:
        from data.mock_data import COLORS
        return COLORS
    return {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/capacity")
async def power_capacity(db: AsyncSession = Depends(get_db)):
    if MOCK_ENABLED:
        from data.mock_data import get_power_data, COLORS

        return LineageEnvelope(
            data={"data": get_power_data(), "colors": COLORS},
            lineage=LineageMeta(
                source_url="mock",
                retrieved_at=datetime.utcnow(),
                parser_version="mock-v1",
                confidence=0.5,
            ),
        )

    # Real DB: aggregate power_capacity_mw by provider_name
    stmt = (
        select(
            Site.provider_name,
            func.count(Site.id).label("site_count"),
            func.coalesce(func.sum(Site.power_capacity_mw), 0).label("total_mw"),
            func.coalesce(func.avg(Site.power_capacity_mw), 0).label("avg_mw"),
            func.coalesce(func.max(Site.power_capacity_mw), 0).label("max_mw"),
        )
        .where(Site.provider_name.isnot(None))
        .group_by(Site.provider_name)
        .order_by(func.sum(Site.power_capacity_mw).desc().nullslast())
    )
    result = await db.execute(stmt)
    rows = result.fetchall()

    data = []
    for provider_name, site_count, total_mw, avg_mw, max_mw in rows:
        data.append(
            {
                "provider": provider_name,
                "site_count": site_count,
                "total_mw": float(total_mw),
                "avg_mw": round(float(avg_mw), 2),
                "max_mw": float(max_mw),
            }
        )

    return CoverageEnvelope(
        data={"data": data, "colors": {}},
        lineage=LineageMeta(
            source_url="sites",
            retrieved_at=datetime.utcnow(),
            parser_version="power-v1.0.0",
            confidence=0.85,
        ),
        coverage=CoverageMeta(pillar="power_capacity"),
    )


@router.get("/timeseries")
async def power_timeseries(db: AsyncSession = Depends(get_db)):
    if MOCK_ENABLED:
        from data.mock_data import get_power_timeseries, COLORS

        return LineageEnvelope(
            data={"data": get_power_timeseries(), "colors": COLORS},
            lineage=LineageMeta(
                source_url="mock",
                retrieved_at=datetime.utcnow(),
                parser_version="mock-v1",
                confidence=0.5,
            ),
        )

    # Real DB: aggregate power_capacity_mw by stage for a rough timeseries proxy
    # Group by provider and stage to show pipeline progression
    stmt = (
        select(
            Site.provider_name,
            Site.stage,
            func.count(Site.id).label("site_count"),
            func.coalesce(func.sum(Site.power_capacity_mw), 0).label("total_mw"),
        )
        .where(Site.provider_name.isnot(None))
        .group_by(Site.provider_name, Site.stage)
        .order_by(Site.provider_name, Site.stage)
    )
    result = await db.execute(stmt)
    rows = result.fetchall()

    # Organize by provider
    timeseries: dict = {}
    for provider_name, stage, site_count, total_mw in rows:
        if provider_name not in timeseries:
            timeseries[provider_name] = {}
        timeseries[provider_name][stage or "unknown"] = {
            "site_count": site_count,
            "total_mw": float(total_mw),
        }

    return CoverageEnvelope(
        data={"data": timeseries, "colors": {}},
        lineage=LineageMeta(
            source_url="sites",
            retrieved_at=datetime.utcnow(),
            parser_version="power-v1.0.0",
            confidence=0.85,
        ),
        coverage=CoverageMeta(pillar="power_timeseries"),
    )


@router.get("/announcements")
def power_announcements(
    company: str = Query(default="All"),
    include_edgar: bool = Query(default=False),
):
    """
    Real power contract announcements from:
    - Curated verified dataset (press releases, SEC filings, sustainability reports)
    - Optionally: live EDGAR 8-K fetches from energy counterparties
    """
    curated = get_curated_deals(company if company != "All" else None)
    gw_summary = get_company_gw_summary()

    edgar_deals: list = []
    if include_edgar:
        try:
            edgar_deals = fetch_real_8k_deals()
            edgar_deals = [d for d in edgar_deals if d.get("is_tech_related")]
        except Exception:
            edgar_deals = []

    payload = {
        "curated": curated,
        "edgar": edgar_deals,
        "gw_summary": gw_summary,
        "total_deals": len(curated) + len(edgar_deals),
        "last_updated": "2026-04-22",
        "data_sources": [
            "SEC EDGAR 8-K Filings",
            "Amazon FY2025 10-K",
            "Microsoft FY2025 10-K",
            "Microsoft Sustainability Report",
            "Amazon Sustainability Report",
            "Google Environmental Report",
            "Meta Sustainability Report",
            "Oracle Press Releases",
            "OpenAI Stargate Announcement",
        ],
    }
    return LineageEnvelope(
        data=payload,
        lineage=LineageMeta(
            source_url="https://www.sec.gov/cgi-bin/browse-edgar",
            retrieved_at=datetime.utcnow(),
            parser_version="curated-v2",
            confidence=0.95,
        ),
    )


@router.get("/gw-summary")
def gw_summary():
    gw = get_company_gw_summary()
    colors = _colors()
    return LineageEnvelope(
        data={"data": gw, "colors": colors},
        lineage=LineageMeta(
            source_url="curated_deals",
            retrieved_at=datetime.utcnow(),
            parser_version="curated-v2",
            confidence=0.95,
        ),
    )
