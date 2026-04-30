"""
Company endpoints -- Phase 1A real DB queries.
Prefix: /api/companies
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_, case, literal_column, or_ as sql_or
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from db.models import Company, CompanyAlias, SiteCompanyAssociation, Site, EdgarExtraction
from schemas.common import CoverageEnvelope, LineageMeta

router = APIRouter(prefix="/api/companies", tags=["companies"])

_LINEAGE = LineageMeta(
    source_url="aterio_csv",
    retrieved_at=datetime.utcnow(),
    parser_version="aterio-v1.0.0",
    confidence=0.85,
)


def _company_to_dict(c: Company) -> dict:
    """Convert Company model to dict."""
    d = {}
    for col in Company.__table__.columns:
        val = getattr(c, col.name, None)
        if isinstance(val, datetime):
            val = val.isoformat()
        d[col.name] = val
    return d


@router.get("/")
async def list_companies(
    role: Optional[str] = Query(None, description="Filter to companies that have this role in site_company_associations"),
    top: Optional[int] = Query(None, ge=1, le=100, description="Return top N companies"),
    order_by: Optional[str] = Query("site_count", regex="^(site_count|mw_total)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Paginated company directory with optional role, top-N, and ordering filters."""

    if role or top or order_by:
        # Build an aggregated query joining companies to site_company_associations + sites
        base = (
            select(
                Company,
                func.count(SiteCompanyAssociation.site_id.distinct()).label("site_count"),
                func.coalesce(func.sum(Site.power_capacity_mw), 0).label("mw_total"),
            )
            .outerjoin(SiteCompanyAssociation, Company.id == SiteCompanyAssociation.company_id)
            .outerjoin(Site, SiteCompanyAssociation.site_id == Site.id)
        )
        count_base = (
            select(func.count(Company.id.distinct()))
            .outerjoin(SiteCompanyAssociation, Company.id == SiteCompanyAssociation.company_id)
        )

        if role:
            base = base.where(SiteCompanyAssociation.role == role)
            count_base = count_base.where(SiteCompanyAssociation.role == role)

        base = base.group_by(Company.id)

        # Ordering
        if order_by == "mw_total":
            base = base.order_by(literal_column("mw_total").desc(), Company.id)
        else:
            base = base.order_by(literal_column("site_count").desc(), Company.id)

        total = (await db.execute(count_base)).scalar() or 0

        effective_limit = top if top else page_size
        offset = 0 if top else (page - 1) * page_size
        base = base.offset(offset).limit(effective_limit)

        result = await db.execute(base)
        rows = result.all()

        data = []
        for company, site_count, mw_total in rows:
            d = _company_to_dict(company)
            d["site_count"] = site_count
            d["mw_total"] = float(mw_total) if mw_total else 0.0
            data.append(d)

        return CoverageEnvelope(
            data={"data": data, "total": total, "page": page, "page_size": effective_limit},
            lineage=_LINEAGE,
        )

    # Simple paginated list without aggregation
    count_query = select(func.count(Company.id))
    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    query = select(Company).order_by(Company.id).offset(offset).limit(page_size)
    result = await db.execute(query)
    companies = result.scalars().all()

    return CoverageEnvelope(
        data={
            "data": [_company_to_dict(c) for c in companies],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        lineage=_LINEAGE,
    )


@router.get("/{id}")
async def get_company(id: int, db: AsyncSession = Depends(get_db)):
    """Canonical company row plus aliases."""
    result = await db.execute(select(Company).where(Company.id == id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=404, detail=f"Company {id} not found")

    # Fetch aliases
    alias_result = await db.execute(
        select(CompanyAlias).where(CompanyAlias.company_id == id)
    )
    aliases = alias_result.scalars().all()

    d = _company_to_dict(company)
    d["alias_list"] = [
        {
            "source": a.source,
            "raw_name": a.raw_name,
            "match_method": a.match_method,
            "confidence": float(a.confidence) if a.confidence else None,
        }
        for a in aliases
    ]

    return CoverageEnvelope(data=d, lineage=_LINEAGE)


@router.get("/{id}/role-summary")
async def company_role_summary(id: int, db: AsyncSession = Depends(get_db)):
    """Group associations by role, per role return site_count and mw_total."""
    # Verify company exists
    exists = (await db.execute(select(Company.id).where(Company.id == id))).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail=f"Company {id} not found")

    stmt = (
        select(
            SiteCompanyAssociation.role,
            func.count(SiteCompanyAssociation.site_id.distinct()).label("site_count"),
            func.coalesce(func.sum(Site.power_capacity_mw), 0).label("mw_total"),
        )
        .outerjoin(Site, SiteCompanyAssociation.site_id == Site.id)
        .where(SiteCompanyAssociation.company_id == id)
        .group_by(SiteCompanyAssociation.role)
        .order_by(SiteCompanyAssociation.role)
    )
    result = await db.execute(stmt)
    rows = result.fetchall()

    roles = {}
    for role, site_count, mw_total in rows:
        roles[role] = {
            "site_count": site_count,
            "mw_total": float(mw_total) if mw_total else 0.0,
        }

    return CoverageEnvelope(data=roles, lineage=_LINEAGE)


@router.get("/{id}/sites")
async def company_sites(
    id: int,
    role: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
):
    """Sites associated with this company, with optional role filter."""
    # Verify company exists
    exists = (await db.execute(select(Company.id).where(Company.id == id))).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail=f"Company {id} not found")

    sub = select(SiteCompanyAssociation.site_id).where(
        SiteCompanyAssociation.company_id == id
    )
    if role:
        sub = sub.where(SiteCompanyAssociation.role == role)

    # COUNT DISTINCT site_id — a single site can hold multiple roles for the
    # same company (e.g. both `provider` and `end_user`), so the association
    # table can have N>1 rows per (company, site). The data query below
    # de-duplicates via `Site.id.in_(sub)`; the count must match.
    count_query = (
        select(func.count(func.distinct(SiteCompanyAssociation.site_id)))
        .where(SiteCompanyAssociation.company_id == id)
    )
    if role:
        count_query = count_query.where(SiteCompanyAssociation.role == role)
    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    query = (
        select(Site)
        .where(Site.id.in_(sub))
        .order_by(Site.id)
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(query)
    sites = result.scalars().all()

    return CoverageEnvelope(
        data={
            "data": [_site_to_dict(s) for s in sites],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        lineage=_LINEAGE,
    )


def _site_to_dict(site: Site) -> dict:
    """Convert Site model to dict."""
    d = {}
    for col in Site.__table__.columns:
        val = getattr(site, col.name, None)
        if isinstance(val, datetime):
            val = val.isoformat()
        d[col.name] = val
    return d


@router.get("/{id}/filings")
async def company_filings(
    id: int,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Recent EDGAR 8-K / 10-K filings where this company appears as buyer
    or seller. Matches against the company's canonical_name + every alias
    in company_aliases via case-insensitive substring (ILIKE %name%)."""

    company = await db.get(Company, id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    # Build the set of names to match against. Drop very short names
    # (e.g. 2-letter tickers) to avoid spurious substring hits.
    name_candidates: set[str] = set()
    if company.canonical_name:
        name_candidates.add(company.canonical_name)
    if company.short_name:
        name_candidates.add(company.short_name)
    alias_rows = (
        await db.execute(select(CompanyAlias.raw_name).where(CompanyAlias.company_id == id))
    ).scalars().all()
    name_candidates.update(a for a in alias_rows if a)
    names = [n for n in name_candidates if n and len(n) >= 4]

    if not names:
        return CoverageEnvelope(data={"data": [], "total": 0}, lineage=_LINEAGE)

    # OR-of-ILIKEs on buyer_raw and seller_raw.
    buyer_clauses = [EdgarExtraction.buyer_raw.ilike(f"%{n}%") for n in names]
    seller_clauses = [EdgarExtraction.seller_raw.ilike(f"%{n}%") for n in names]
    name_clause = sql_or(*buyer_clauses, *seller_clauses)

    stmt = (
        select(EdgarExtraction)
        .where(name_clause)
        .order_by(EdgarExtraction.filing_date.desc().nullslast())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()

    data = [
        {
            "id": e.id,
            "cik": e.cik,
            "accession_number": e.accession_number,
            "form_type": e.form_type,
            "filing_date": e.filing_date.isoformat() if e.filing_date else None,
            "edgar_url": e.edgar_url,
            "capacity_mw": float(e.capacity_mw) if e.capacity_mw is not None else None,
            "energy_source": e.energy_source,
            "buyer_raw": e.buyer_raw,
            "seller_raw": e.seller_raw,
            "excerpt": e.excerpt,
            "confidence": float(e.confidence) if e.confidence is not None else None,
        }
        for e in rows
    ]
    return CoverageEnvelope(
        data={"data": data, "total": len(data)},
        lineage=_LINEAGE,
    )
