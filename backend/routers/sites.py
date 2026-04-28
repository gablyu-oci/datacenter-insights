"""
Sites endpoints -- Phase 1A real DB queries.
Prefix: /api/sites
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from db.models import Site, SiteCompanyAssociation, Company
from schemas.common import CoverageEnvelope, CoverageMeta, LineageMeta

router = APIRouter(prefix="/api/sites", tags=["sites"])


@router.get("/")
async def list_sites(
    state: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    stage: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Paginated list of sites with filters."""
    query = select(Site)
    count_query = select(func.count(Site.id))

    if state:
        query = query.where(Site.state_code == state.upper())
        count_query = count_query.where(Site.state_code == state.upper())
    if provider:
        query = query.where(Site.provider_name.ilike(f"%{provider}%"))
        count_query = count_query.where(Site.provider_name.ilike(f"%{provider}%"))
    if stage:
        query = query.where(Site.stage == stage)
        count_query = count_query.where(Site.stage == stage)
    if role and company_id:
        sub = select(SiteCompanyAssociation.site_id).where(
            and_(
                SiteCompanyAssociation.company_id == company_id,
                SiteCompanyAssociation.role == role,
            )
        )
        query = query.where(Site.id.in_(sub))
        count_query = count_query.where(Site.id.in_(sub))
    elif company_id:
        sub = select(SiteCompanyAssociation.site_id).where(
            SiteCompanyAssociation.company_id == company_id
        )
        query = query.where(Site.id.in_(sub))
        count_query = count_query.where(Site.id.in_(sub))

    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size).order_by(Site.id)
    result = await db.execute(query)
    sites = result.scalars().all()

    # Distinct states for coverage metadata
    states_result = await db.execute(
        select(Site.state_code).where(Site.state_code.isnot(None)).distinct()
    )
    states_included = [r[0] for r in states_result.fetchall()]

    return CoverageEnvelope(
        data={
            "data": [_site_to_dict(s) for s in sites],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        lineage=LineageMeta(
            source_url="aterio_csv",
            retrieved_at=datetime.utcnow(),
            parser_version="aterio-v1.0.0",
            confidence=0.85,
        ),
        coverage=CoverageMeta(pillar="power_sites", states_included=states_included),
    )


@router.get("/{aterio_dc_uid}")
async def get_site(aterio_dc_uid: str, db: AsyncSession = Depends(get_db)):
    """Single site with all 73 columns."""
    result = await db.execute(
        select(Site).where(Site.aterio_dc_uid == aterio_dc_uid)
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail=f"Site {aterio_dc_uid} not found")
    return CoverageEnvelope(
        data=_site_to_dict(site),
        lineage=LineageMeta(
            source_url=site.datasheet_url or "aterio_csv",
            retrieved_at=datetime.utcnow(),
            parser_version="aterio-v1.0.0",
            confidence=0.85,
        ),
        coverage=CoverageMeta(
            pillar="power_sites",
            states_included=[site.state_code] if site.state_code else [],
        ),
    )


@router.get("/{aterio_dc_uid}/role-summary")
async def site_role_summary(
    aterio_dc_uid: str, db: AsyncSession = Depends(get_db)
):
    """Group site_company_associations by role."""
    site_result = await db.execute(
        select(Site.id).where(Site.aterio_dc_uid == aterio_dc_uid)
    )
    site_id = site_result.scalar_one_or_none()
    if site_id is None:
        raise HTTPException(status_code=404, detail=f"Site {aterio_dc_uid} not found")

    stmt = (
        select(
            SiteCompanyAssociation,
            Company.canonical_name,
            Company.short_name,
            Company.ticker,
        )
        .join(Company, SiteCompanyAssociation.company_id == Company.id)
        .where(SiteCompanyAssociation.site_id == site_id)
        .order_by(SiteCompanyAssociation.role)
    )
    result = await db.execute(stmt)
    rows = result.fetchall()

    roles: dict = {}
    for assoc, canonical_name, short_name, ticker in rows:
        role = assoc.role
        if role not in roles:
            roles[role] = []
        roles[role].append(
            {
                "company_id": assoc.company_id,
                "canonical_name": canonical_name,
                "short_name": short_name,
                "ticker": ticker,
                "confidence": float(assoc.confidence) if assoc.confidence else None,
                "source": assoc.source,
            }
        )

    return CoverageEnvelope(
        data=roles,
        lineage=LineageMeta(
            source_url="aterio_csv",
            retrieved_at=datetime.utcnow(),
            parser_version="aterio-v1.0.0",
            confidence=0.85,
        ),
    )


def _site_to_dict(site: Site) -> dict:
    """Convert Site model to dict, handling all columns."""
    d = {}
    for col in Site.__table__.columns:
        val = getattr(site, col.name, None)
        if isinstance(val, datetime):
            val = val.isoformat()
        d[col.name] = val
    return d
