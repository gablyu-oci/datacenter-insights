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
from sqlalchemy.orm import aliased

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


@router.get("/aggregate")
async def companies_aggregate(
    stages: str = Query(
        "Active,Construction",
        description="Comma-separated site stage filter — defaults to operational + under-construction. Use 'all' to include announcement / withdrawn / cancelled.",
    ),
    db: AsyncSession = Depends(get_db),
) -> CoverageEnvelope:
    """Top-of-tab summary stats: total companies, total **distinct** sites,
    and total MW — with optional stage filter.

    Why this exists: summing `mw_total` across companies double-counts
    every site that has multiple roles (provider + utility + financing on
    one site = MW counted 3x). And summing across all stages lumps
    pipeline / withdrawn projects with operational ones, which inflates
    the headline number 5-10x. This endpoint computes both correctly:

      - `total_sites` = COUNT(DISTINCT sites.id) under the stage filter
      - `total_mw` = SUM(power_capacity_mw) over distinct sites only
      - `total_companies` = total companies known to the warehouse
    """
    stage_list = [s.strip() for s in stages.split(",") if s.strip()]
    sites_q = select(
        func.count(func.distinct(Site.id)).label("n_sites"),
        func.coalesce(func.sum(Site.power_capacity_mw), 0).label("sum_mw"),
    )
    if stage_list and stage_list != ["all"]:
        sites_q = sites_q.where(Site.stage.in_(stage_list))
    sites_row = (await db.execute(sites_q)).one()

    companies_count = (await db.execute(select(func.count(Company.id)))).scalar() or 0

    return CoverageEnvelope(
        data={
            "total_companies": int(companies_count),
            "total_sites": int(sites_row.n_sites or 0),
            "total_mw": float(sites_row.sum_mw or 0.0),
            "stages_included": stage_list,
        },
        lineage=_LINEAGE,
    )


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
        company_ids_in_page: list[int] = []
        for company, site_count, mw_total in rows:
            d = _company_to_dict(company)
            d["site_count"] = site_count
            d["mw_total"] = float(mw_total) if mw_total else 0.0
            d["roles"] = []  # populated below
            data.append(d)
            company_ids_in_page.append(company.id)

        # Hydrate per-company roles in a single query (one row per
        # (company, role) — keeps the list cheap).
        if company_ids_in_page:
            roles_q = (
                select(
                    SiteCompanyAssociation.company_id,
                    SiteCompanyAssociation.role,
                    func.count(func.distinct(SiteCompanyAssociation.site_id)).label("n"),
                )
                .where(SiteCompanyAssociation.company_id.in_(company_ids_in_page))
                .group_by(SiteCompanyAssociation.company_id, SiteCompanyAssociation.role)
            )
            roles_rows = (await db.execute(roles_q)).all()
            by_cid: dict[int, list[dict]] = {}
            for cid, role_name, n in roles_rows:
                by_cid.setdefault(cid, []).append({"role": role_name, "site_count": int(n)})
            for d in data:
                d["roles"] = sorted(
                    by_cid.get(d["id"], []), key=lambda r: r["site_count"], reverse=True,
                )

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
    """Group associations by role, per role return site_count and mw_total.

    Rolls up child companies (parent_company_id == id) into the parent's
    view so e.g. Amazon (id=2) reflects Amazon Web Services (id=23) in
    addition to its own associations. Walks one level of parent_company_id
    -- depth=1 covers the actual parent/child relationships in the DB
    today (Amazon/AWS, Alphabet/Google Cloud, etc.).
    """
    # Verify company exists
    exists = (await db.execute(select(Company.id).where(Company.id == id))).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail=f"Company {id} not found")

    # Resolve self + child company ids (depth=1)
    child_ids = (await db.execute(
        select(Company.id).where(Company.parent_company_id == id)
    )).scalars().all()
    company_ids = [id] + list(child_ids)

    stmt = (
        select(
            SiteCompanyAssociation.role,
            func.count(SiteCompanyAssociation.site_id.distinct()).label("site_count"),
            func.coalesce(func.sum(Site.power_capacity_mw), 0).label("mw_total"),
        )
        .outerjoin(Site, SiteCompanyAssociation.site_id == Site.id)
        .where(SiteCompanyAssociation.company_id.in_(company_ids))
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


async def _query_counterparties(
    db: AsyncSession,
    company_ids: list[int],
    x_roles: tuple[str, ...],
    y_roles: tuple[str, ...],
) -> list[tuple[int, int, float | None]]:
    """Single self-join: for each counterparty company sharing a site with
    any company in `company_ids` (the focal company + its rolled-up
    children), return (counterparty_company_id, n_sites, total_mw).
    """
    sca_x = aliased(SiteCompanyAssociation)
    sca_y = aliased(SiteCompanyAssociation)
    mw_expr = func.coalesce(sca_y.mw_share, Site.power_capacity_mw)
    stmt = (
        select(
            sca_y.company_id.label("counterparty_id"),
            func.count(func.distinct(sca_x.site_id)).label("n_sites"),
            func.sum(mw_expr).label("total_mw"),
        )
        .join(sca_y, sca_y.site_id == sca_x.site_id)
        .join(Site, Site.id == sca_x.site_id)
        .where(
            sca_x.company_id.in_(company_ids),
            sca_x.role.in_(x_roles),
            sca_y.role.in_(y_roles),
            sca_y.company_id.notin_(company_ids),
        )
        .group_by(sca_y.company_id)
    )
    rows = (await db.execute(stmt)).all()
    return [
        (r.counterparty_id, int(r.n_sites or 0), float(r.total_mw) if r.total_mw is not None else None)
        for r in rows
    ]


async def _query_role_pair_matrix(
    db: AsyncSession,
    company_ids: list[int],
) -> list[tuple[str, str, int, int, float | None]]:
    """Return (my_role, their_role, counterparty_id, n_sites, total_mw)
    for every (my_role, their_role) pair where the focal company holds
    `my_role` and another company holds `their_role` on the same site.
    Used by the Role Distribution view to build a nested donut grid.
    """
    sca_x = aliased(SiteCompanyAssociation)
    sca_y = aliased(SiteCompanyAssociation)
    mw_expr = func.coalesce(sca_y.mw_share, Site.power_capacity_mw)
    stmt = (
        select(
            sca_x.role.label("my_role"),
            sca_y.role.label("their_role"),
            sca_y.company_id.label("counterparty_id"),
            func.count(func.distinct(sca_x.site_id)).label("n_sites"),
            func.sum(mw_expr).label("total_mw"),
        )
        .join(sca_y, sca_y.site_id == sca_x.site_id)
        .join(Site, Site.id == sca_x.site_id)
        .where(
            sca_x.company_id.in_(company_ids),
            sca_y.company_id.notin_(company_ids),
        )
        .group_by(sca_x.role, sca_y.role, sca_y.company_id)
    )
    rows = (await db.execute(stmt)).all()
    return [
        (
            r.my_role,
            r.their_role,
            r.counterparty_id,
            int(r.n_sites or 0),
            float(r.total_mw) if r.total_mw is not None else None,
        )
        for r in rows
    ]


async def _query_focal_role_distribution(
    db: AsyncSession,
    company_ids: list[int],
) -> dict[str, int]:
    """Return {role: site_count} for the focal company across all roles."""
    stmt = (
        select(
            SiteCompanyAssociation.role,
            func.count(func.distinct(SiteCompanyAssociation.site_id)).label("n_sites"),
        )
        .where(SiteCompanyAssociation.company_id.in_(company_ids))
        .group_by(SiteCompanyAssociation.role)
    )
    rows = (await db.execute(stmt)).all()
    return {r.role: int(r.n_sites or 0) for r in rows}


@router.get("/{id}/counterparties")
async def company_counterparties(id: int, db: AsyncSession = Depends(get_db)) -> CoverageEnvelope:
    """Top-7 counterparty rollup for the focal company viewed two ways:
    `as_provider` (focal sells/builds, counterparty buys/uses) and
    `as_end_user` (focal buys/uses, counterparty sells/builds). Mirrors
    the depth=1 child-company rollup used by /role-summary and /sites so
    e.g. Amazon's view includes AWS sites.
    """
    # Verify company exists.
    exists = (await db.execute(select(Company.id).where(Company.id == id))).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail=f"Company {id} not found")

    # Resolve self + child company ids (depth=1) -- same pattern as
    # /role-summary lines 162-166 and /sites lines 207-211.
    child_ids = (await db.execute(
        select(Company.id).where(Company.parent_company_id == id)
    )).scalars().all()
    company_ids = [id] + list(child_ids)

    # Role taxonomy:
    #   SUPPLIER side — sells inputs to / builds the site:
    #     utility, equipment, financing, developer, provider_backer
    #   CONSUMER side — operates / uses the site:
    #     provider, end_user, customer
    #
    # "Buyers when this company supplies" = focal in any supplier role,
    # counterparties in any consumer role.
    # "Sellers when this company consumes" = focal in any consumer role,
    # counterparties in any supplier role.
    SUPPLIER_ROLES = (
        "utility", "equipment", "financing", "developer", "provider_backer",
    )
    CONSUMER_ROLES = ("provider", "end_user", "customer")
    provider_rows = await _query_counterparties(
        db, company_ids, x_roles=SUPPLIER_ROLES, y_roles=CONSUMER_ROLES,
    )
    end_user_rows = await _query_counterparties(
        db, company_ids, x_roles=CONSUMER_ROLES, y_roles=SUPPLIER_ROLES,
    )

    # Hydrate canonical names for every counterparty id seen on either side.
    name_ids = {r[0] for r in provider_rows} | {r[0] for r in end_user_rows}
    name_map: dict[int, str] = {}
    if name_ids:
        name_rows = (await db.execute(
            select(Company.id, Company.canonical_name).where(Company.id.in_(name_ids))
        )).all()
        name_map = {cid: cname for cid, cname in name_rows}

    def _build_side(rows: list[tuple[int, int, float | None]]) -> dict:
        # Drop rows with no sites (defensive -- shouldn't happen given the join).
        clean = [r for r in rows if r[1] > 0]

        # Sites ranking: sort by n_sites desc, top-7 + Other.
        by_sites = sorted(clean, key=lambda r: r[1], reverse=True)
        top_sites = by_sites[:7]
        other_sites = sum(r[1] for r in by_sites[7:])
        sites_arr = [
            {"company_id": cid, "canonical_name": name_map.get(cid, f"Company {cid}"), "count": n}
            for cid, n, _ in top_sites
        ]

        # MW ranking: skip rows with NULL or 0 total_mw entirely (not in top, not in other).
        mw_rows = [(cid, n, mw) for cid, n, mw in clean if mw is not None and mw > 0]
        by_mw = sorted(mw_rows, key=lambda r: r[2], reverse=True)
        top_mw = by_mw[:7]
        other_mw = sum(r[2] for r in by_mw[7:])
        mw_arr = [
            {"company_id": cid, "canonical_name": name_map.get(cid, f"Company {cid}"), "mw": float(mw)}
            for cid, _, mw in top_mw
        ]

        return {
            "sites": sites_arr,
            "mw": mw_arr,
            "other_sites": int(other_sites),
            "other_mw": float(other_mw),
        }

    return CoverageEnvelope(
        data={
            "as_provider": _build_side(provider_rows),
            "as_end_user": _build_side(end_user_rows),
        },
        lineage=_LINEAGE,
    )


@router.get("/{id}/role-distribution")
async def company_role_distribution(id: int, db: AsyncSession = Depends(get_db)) -> CoverageEnvelope:
    """Role distribution + nested counterparty donut data.

    Returns:
      {
        focal_roles: {role: site_count, ...},   # what roles this company holds
        pairs: {
          my_role: {
            their_role: {
              sites: [{company_id, canonical_name, count}, ...top 7],
              mw:    [{company_id, canonical_name, mw}, ...top 7],
              other_sites: int, other_mw: float,
            }, ...
          }, ...
        }
      }

    Skips role-pairs with fewer than 3 distinct counterparties — keeps
    the donut grid focused on signal.
    """
    exists = (await db.execute(select(Company.id).where(Company.id == id))).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail=f"Company {id} not found")

    child_ids = (await db.execute(
        select(Company.id).where(Company.parent_company_id == id)
    )).scalars().all()
    company_ids = [id] + list(child_ids)

    focal_roles = await _query_focal_role_distribution(db, company_ids)
    matrix = await _query_role_pair_matrix(db, company_ids)

    # Group rows by (my_role, their_role).
    grouped: dict[tuple[str, str], list[tuple[int, int, float | None]]] = {}
    for my_role, their_role, cid, n, mw in matrix:
        grouped.setdefault((my_role, their_role), []).append((cid, n, mw))

    # Hydrate counterparty names.
    name_ids = {cid for rows in grouped.values() for cid, _, _ in rows}
    name_map: dict[int, str] = {}
    if name_ids:
        name_rows = (await db.execute(
            select(Company.id, Company.canonical_name).where(Company.id.in_(name_ids))
        )).all()
        name_map = {cid: cname for cid, cname in name_rows}

    def _build_side(rows: list[tuple[int, int, float | None]]) -> dict:
        clean = [r for r in rows if r[1] > 0]
        by_sites = sorted(clean, key=lambda r: r[1], reverse=True)
        top_sites = by_sites[:7]
        other_sites = sum(r[1] for r in by_sites[7:])
        sites_arr = [
            {"company_id": cid, "canonical_name": name_map.get(cid, f"Company {cid}"), "count": n}
            for cid, n, _ in top_sites
        ]
        mw_rows = [(cid, n, mw) for cid, n, mw in clean if mw is not None and mw > 0]
        by_mw = sorted(mw_rows, key=lambda r: r[2], reverse=True)
        top_mw = by_mw[:7]
        other_mw = sum(r[2] for r in by_mw[7:])
        mw_arr = [
            {"company_id": cid, "canonical_name": name_map.get(cid, f"Company {cid}"), "mw": float(mw)}
            for cid, _, mw in top_mw
        ]
        return {
            "sites": sites_arr,
            "mw": mw_arr,
            "other_sites": int(other_sites),
            "other_mw": float(other_mw),
        }

    pairs: dict[str, dict[str, dict]] = {}
    MIN_COUNTERPARTIES = 3
    for (my_role, their_role), rows in grouped.items():
        if len({cid for cid, _, _ in rows}) < MIN_COUNTERPARTIES:
            continue
        pairs.setdefault(my_role, {})[their_role] = _build_side(rows)

    return CoverageEnvelope(
        data={"focal_roles": focal_roles, "pairs": pairs},
        lineage=_LINEAGE,
    )


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

    # Resolve self + child company ids (depth=1) so /sites rolls up child
    # companies into the parent view -- mirrors the role-summary fix.
    child_ids = (await db.execute(
        select(Company.id).where(Company.parent_company_id == id)
    )).scalars().all()
    company_ids = [id] + list(child_ids)

    sub = select(SiteCompanyAssociation.site_id).where(
        SiteCompanyAssociation.company_id.in_(company_ids)
    )
    if role:
        sub = sub.where(SiteCompanyAssociation.role == role)

    # COUNT DISTINCT site_id — a single site can hold multiple roles for the
    # same company (e.g. both `provider` and `end_user`), so the association
    # table can have N>1 rows per (company, site). The data query below
    # de-duplicates via `Site.id.in_(sub)`; the count must match.
    count_query = (
        select(func.count(func.distinct(SiteCompanyAssociation.site_id)))
        .where(SiteCompanyAssociation.company_id.in_(company_ids))
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
