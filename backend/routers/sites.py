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
from db.models import Site, SiteCompanyAssociation, Company, Event
from schemas.common import CoverageEnvelope, CoverageMeta, LineageMeta

router = APIRouter(prefix="/api/sites", tags=["sites"])

# event_type -> per-site date field that downstream consumers (chart, detail
# view) already understand. We populate these from the events table rather
# than from sites.* columns; the inventory CSV no longer carries these dates.
_EVENT_TYPE_TO_SITE_FIELD = {
    "announcement": "announced_date",
    "construction_start": "construction_start_date",
    "activation": "activation_date",
    "cancellation": "cancelled_date",
    "withdrawn": "project_withdrawn_date",
}


async def _milestone_dates_for_uids(
    db: AsyncSession, dc_uids: list[str]
) -> dict[str, dict[str, str]]:
    """For each dc_uid, return the earliest event_date per relevant event_type
    as ISO strings, keyed by the site-column name the frontend expects.

    Returns {dc_uid: {announced_date: "2024-...", construction_start_date: "..."}}.
    Empty dict for uids with no relevant events.
    """
    if not dc_uids:
        return {}
    stmt = (
        select(
            Event.aterio_dc_uid,
            Event.event_type,
            func.min(Event.event_date),
        )
        .where(Event.aterio_dc_uid.in_(dc_uids))
        .where(Event.event_type.in_(_EVENT_TYPE_TO_SITE_FIELD.keys()))
        .group_by(Event.aterio_dc_uid, Event.event_type)
    )
    rows = (await db.execute(stmt)).all()
    out: dict[str, dict[str, str]] = {}
    for dc_uid, event_type, event_date in rows:
        field = _EVENT_TYPE_TO_SITE_FIELD.get(event_type)
        if field is None or event_date is None:
            continue
        out.setdefault(dc_uid, {})[field] = event_date.isoformat()
    return out


@router.get("/")
async def list_sites(
    state: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    stage: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=10000),
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

    # Enrich each site with milestone dates joined from the events table.
    # The inventory CSV no longer carries these columns, so events is now
    # the source of truth -- we surface min(event_date) per type back onto
    # the site response for the chart and detail view to consume.
    dc_uids = [s.aterio_dc_uid for s in sites if s.aterio_dc_uid]
    milestone_map = await _milestone_dates_for_uids(db, dc_uids)

    site_dicts: list[dict] = []
    for s in sites:
        d = _site_to_dict(s)
        milestones = milestone_map.get(s.aterio_dc_uid or "", {})
        for field, value in milestones.items():
            # Events table is authoritative -- overwrite even if a stale
            # value happens to be on the sites row.
            d[field] = value
        site_dicts.append(d)

    # Distinct states for coverage metadata
    states_result = await db.execute(
        select(Site.state_code).where(Site.state_code.isnot(None)).distinct()
    )
    states_included = [r[0] for r in states_result.fetchall()]

    return CoverageEnvelope(
        data={
            "data": site_dicts,
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
