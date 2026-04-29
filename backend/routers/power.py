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

from db.session import get_db
from db.models import CuratedDeal, EdgarExtraction, Site
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


# Canonical buyer rollups for the gw-summary aggregate. A buyer string in
# the source row may be "Microsoft", "Amazon / AWS", "Google / Alphabet" etc;
# we collapse to the parent brand for the dashboard tile.
_BUYER_CANONICALS = ("Microsoft", "Amazon", "Google", "Meta", "Oracle")


def _canonicalize_buyer(buyer: str | None) -> str:
    if not buyer:
        return "Unknown"
    head = buyer.split(" / ")[0].split("/")[0].strip()
    for canon in _BUYER_CANONICALS:
        if canon.lower() in head.lower():
            return canon
    return head


def _curated_row_to_dict(d: CuratedDeal) -> dict:
    """Surface a CuratedDeal ORM row in the legacy dict shape the frontend expects."""
    return {
        "id": d.legacy_id,
        "buyer": d.buyer,
        "seller": d.seller,
        "deal_type": d.deal_type,
        "energy_source": d.energy_source,
        "capacity_mw": d.capacity_mw,
        "location": d.location,
        "state": d.state,
        "lat": d.lat,
        "lon": d.lon,
        "announced_date": d.announced_date,
        "status": d.status,
        "duration_years": d.duration_years,
        "headline": d.headline,
        "excerpt": d.excerpt,
        "source_type": d.source_type,
        "source_url": d.source_url,
        "edgar_url": d.edgar_url,
        "confidence": float(d.confidence) if d.confidence is not None else None,
        "data_source": d.data_source,
        "energy_contract_mwh_million": d.energy_contract_mwh_million,
    }


def _edgar_row_to_dict(e: EdgarExtraction) -> dict:
    """Surface an EdgarExtraction ORM row in the same dict shape (where it overlaps)."""
    return {
        "id": f"edgar-{e.id}",
        "buyer": e.buyer_raw,
        "seller": e.seller_raw,
        "deal_type": "8-K disclosure",
        "energy_source": e.energy_source,
        "capacity_mw": int(e.capacity_mw) if e.capacity_mw is not None else None,
        "announced_date": e.filing_date.isoformat() if e.filing_date else None,
        "headline": e.excerpt[:160] if e.excerpt else None,
        "excerpt": e.excerpt,
        "source_type": e.form_type,
        "source_url": e.edgar_url,
        "edgar_url": e.edgar_url,
        "confidence": float(e.confidence) if e.confidence is not None else None,
        "data_source": f"SEC EDGAR ({e.form_type})",
    }


@router.get("/announcements")
async def power_announcements(
    company: str = Query(default="All"),
    include_edgar: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
):
    """Power contract announcements: UNION of two live DB-backed sources.

    - `curated_deals`: 23 hand-verified historical deals seeded once with
      real source URLs (press releases, SEC filings, sustainability reports).
    - `edgar_extractions`: live LLM-extracted 8-K disclosures, refreshed
      daily by the `edgar_daily` cron job.

    No source-controlled news in this code path — every row traces to a
    durable DB row with a source_url.
    """
    # Curated deals (DB-backed)
    cd_stmt = select(CuratedDeal)
    if company and company != "All":
        cd_stmt = cd_stmt.where(
            (CuratedDeal.buyer.ilike(f"%{company}%"))
            | (CuratedDeal.seller.ilike(f"%{company}%"))
        )
    cd_stmt = cd_stmt.order_by(CuratedDeal.announced_date.desc().nullslast())
    curated_rows = (await db.execute(cd_stmt)).scalars().all()
    curated = [_curated_row_to_dict(d) for d in curated_rows]

    # Live EDGAR extractions
    edgar_deals: list[dict] = []
    if include_edgar:
        ee_stmt = select(EdgarExtraction)
        if company and company != "All":
            ee_stmt = ee_stmt.where(
                (EdgarExtraction.buyer_raw.ilike(f"%{company}%"))
                | (EdgarExtraction.seller_raw.ilike(f"%{company}%"))
            )
        ee_stmt = ee_stmt.order_by(EdgarExtraction.filing_date.desc().nullslast()).limit(50)
        edgar_rows = (await db.execute(ee_stmt)).scalars().all()
        edgar_deals = [_edgar_row_to_dict(e) for e in edgar_rows]

    # Per-buyer GW summary, computed in SQL (replaces the legacy Python helper).
    gw_summary = await _gw_summary_from_db(db)

    # Latest update timestamp: max of the two streams' latest write.
    latest_curated = (
        await db.execute(select(func.max(CuratedDeal.updated_at)))
    ).scalar_one_or_none()
    latest_edgar = (
        await db.execute(select(func.max(EdgarExtraction.retrieved_at)))
    ).scalar_one_or_none()
    candidates = [t for t in (latest_curated, latest_edgar) if t is not None]
    last_updated = max(candidates).date().isoformat() if candidates else None

    # Distinct data_source labels surfaced as the citation list.
    src_rows = (
        await db.execute(
            select(CuratedDeal.data_source).where(CuratedDeal.data_source.isnot(None)).distinct()
        )
    ).scalars().all()
    data_sources = sorted({s for s in src_rows if s})
    if include_edgar and edgar_deals:
        data_sources.append("SEC EDGAR (live LLM extraction)")

    payload = {
        "curated": curated,
        "edgar": edgar_deals,
        "gw_summary": gw_summary,
        "total_deals": len(curated) + len(edgar_deals),
        "last_updated": last_updated,
        "data_sources": data_sources,
    }
    return LineageEnvelope(
        data=payload,
        lineage=LineageMeta(
            source_url="db://curated_deals + db://edgar_extractions",
            retrieved_at=datetime.utcnow(),
            parser_version="db-v1.0.0",
            confidence=0.95,
        ),
    )


async def _gw_summary_from_db(db: AsyncSession) -> dict:
    """Aggregate contracted GW per canonical buyer from curated_deals."""
    rows = (
        await db.execute(
            select(
                CuratedDeal.buyer,
                CuratedDeal.energy_source,
                CuratedDeal.capacity_mw,
            ).where(CuratedDeal.capacity_mw.isnot(None))
        )
    ).all()

    totals: dict[str, dict] = {}
    for buyer, energy_source, mw in rows:
        canon = _canonicalize_buyer(buyer)
        bucket = totals.setdefault(
            canon, {"gw_total": 0.0, "deals": 0, "nuclear_gw": 0.0, "renewable_gw": 0.0}
        )
        gw = (mw or 0) / 1000.0
        bucket["gw_total"] += gw
        bucket["deals"] += 1
        src = (energy_source or "").lower()
        if "nuclear" in src:
            bucket["nuclear_gw"] += gw
        elif any(r in src for r in ("solar", "wind", "renewable")):
            bucket["renewable_gw"] += gw
    for k in totals:
        for f in ("gw_total", "nuclear_gw", "renewable_gw"):
            totals[k][f] = round(totals[k][f], 2)
    return totals


@router.get("/gw-summary")
async def gw_summary(db: AsyncSession = Depends(get_db)):
    gw = await _gw_summary_from_db(db)
    colors = _colors()
    return LineageEnvelope(
        data={"data": gw, "colors": colors},
        lineage=LineageMeta(
            source_url="db://curated_deals",
            retrieved_at=datetime.utcnow(),
            parser_version="db-v1.0.0",
            confidence=0.95,
        ),
    )
