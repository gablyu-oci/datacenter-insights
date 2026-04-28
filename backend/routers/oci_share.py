"""
OCI share-of-wallet per tab -- Phase 1A real DB queries.
Prefix: /api

Computes:  oci_pct = (oci_value / total_tracked_value) * 100

Oracle is identified by companies.ticker = 'ORCL'.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from db.models import (
    Company,
    Site,
    SiteCompanyAssociation,
    GeneratorPermit,
)
from schemas.common import LineageEnvelope, LineageMeta

router = APIRouter(prefix="/api", tags=["oci-share"])

# Per-tab default roles and units
_TAB_DEFAULTS = {
    "power": {"role": "provider", "unit": "MW"},
    "gpu": {"role": "end_user", "unit": "units"},
    "nics": {"role": "end_user", "unit": "units"},
    "tsmc": {"role": "end_user", "unit": "wafers"},
    "permits": {"role": "provider", "unit": "permits"},
    "triangulation": {"role": "provider", "unit": "score"},
}

# Tabs that have no real data yet -- return explicit null response
_NO_DATA_TABS = {"gpu", "nics", "tsmc", "triangulation"}


async def _get_oracle_company_id(db: AsyncSession) -> Optional[int]:
    """Look up Oracle's company_id by ticker ORCL."""
    result = await db.execute(
        select(Company.id).where(Company.ticker == "ORCL")
    )
    return result.scalar_one_or_none()


@router.get("/{tab}/oci-share")
async def oci_share(
    tab: str,
    role: Optional[str] = Query(None, description="Override the default role for this tab"),
    db: AsyncSession = Depends(get_db),
):
    """OCI percentage share for a given tab."""
    if tab not in _TAB_DEFAULTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tab '{tab}'. Valid tabs: {', '.join(sorted(_TAB_DEFAULTS))}",
        )

    defaults = _TAB_DEFAULTS[tab]
    effective_role = role or defaults["role"]
    unit = defaults["unit"]

    # Tabs without real data return explicit null
    if tab in _NO_DATA_TABS:
        return LineageEnvelope(
            data={
                "oci_pct": None,
                "oci_value": None,
                "total_value": None,
                "unit": unit,
                "role": effective_role,
                "multi_tenant_warning": False,
                "note": "No real data available for this tab yet",
            },
            lineage=LineageMeta(
                source_url="n/a",
                retrieved_at=datetime.utcnow(),
                parser_version="oci-share-v1.0.0",
                confidence=0.0,
            ),
        )

    oracle_id = await _get_oracle_company_id(db)

    if tab == "power":
        return await _power_share(db, oracle_id, effective_role, unit)
    elif tab == "permits":
        return await _permits_share(db, oracle_id, effective_role, unit)

    # Fallback for any tab not explicitly handled
    return LineageEnvelope(
        data={
            "oci_pct": None,
            "oci_value": None,
            "total_value": None,
            "unit": unit,
            "role": effective_role,
            "multi_tenant_warning": False,
            "note": f"Computation not yet implemented for tab '{tab}'",
        },
        lineage=LineageMeta(
            source_url="n/a",
            retrieved_at=datetime.utcnow(),
            parser_version="oci-share-v1.0.0",
            confidence=0.0,
        ),
    )


async def _power_share(
    db: AsyncSession, oracle_id: Optional[int], role: str, unit: str
) -> LineageEnvelope:
    """
    Power tab: SUM(sites.power_capacity_mw) grouped by company via
    site_company_associations filtered by role.
    """
    # Total tracked value: sum of power_capacity_mw for all sites associated
    # with any company in this role
    total_stmt = (
        select(func.coalesce(func.sum(Site.power_capacity_mw), 0))
        .select_from(SiteCompanyAssociation)
        .join(Site, SiteCompanyAssociation.site_id == Site.id)
        .where(SiteCompanyAssociation.role == role)
    )
    total_value = (await db.execute(total_stmt)).scalar() or 0

    oci_value = 0.0
    multi_tenant_warning = False
    if oracle_id is not None:
        oci_stmt = (
            select(func.coalesce(func.sum(Site.power_capacity_mw), 0))
            .select_from(SiteCompanyAssociation)
            .join(Site, SiteCompanyAssociation.site_id == Site.id)
            .where(
                SiteCompanyAssociation.role == role,
                SiteCompanyAssociation.company_id == oracle_id,
            )
        )
        oci_value = (await db.execute(oci_stmt)).scalar() or 0

        # Check if any Oracle-associated sites have multiple companies in the same role
        # (multi-tenant warning)
        oracle_sites_sub = (
            select(SiteCompanyAssociation.site_id)
            .where(
                SiteCompanyAssociation.company_id == oracle_id,
                SiteCompanyAssociation.role == role,
            )
        )
        multi_tenant_check = (
            select(func.count())
            .select_from(SiteCompanyAssociation)
            .where(
                SiteCompanyAssociation.site_id.in_(oracle_sites_sub),
                SiteCompanyAssociation.role == role,
                SiteCompanyAssociation.company_id != oracle_id,
            )
        )
        other_count = (await db.execute(multi_tenant_check)).scalar() or 0
        multi_tenant_warning = other_count > 0

    oci_pct = (oci_value / total_value * 100) if total_value > 0 else None

    return LineageEnvelope(
        data={
            "oci_pct": round(oci_pct, 2) if oci_pct is not None else None,
            "oci_value": float(oci_value),
            "total_value": float(total_value),
            "unit": unit,
            "role": role,
            "multi_tenant_warning": multi_tenant_warning,
        },
        lineage=LineageMeta(
            source_url="sites + site_company_associations",
            retrieved_at=datetime.utcnow(),
            parser_version="oci-share-v1.0.0",
            confidence=0.85,
        ),
    )


async def _permits_share(
    db: AsyncSession, oracle_id: Optional[int], role: str, unit: str
) -> LineageEnvelope:
    """
    Permits tab: COUNT(generator_permits) by resolved_company_id.
    """
    total_stmt = select(func.count(GeneratorPermit.id))
    total_value = (await db.execute(total_stmt)).scalar() or 0

    oci_value = 0
    if oracle_id is not None:
        oci_stmt = select(func.count(GeneratorPermit.id)).where(
            GeneratorPermit.resolved_company_id == oracle_id
        )
        oci_value = (await db.execute(oci_stmt)).scalar() or 0

    oci_pct = (oci_value / total_value * 100) if total_value > 0 else None

    return LineageEnvelope(
        data={
            "oci_pct": round(oci_pct, 2) if oci_pct is not None else None,
            "oci_value": oci_value,
            "total_value": total_value,
            "unit": unit,
            "role": role,
            "multi_tenant_warning": False,
        },
        lineage=LineageMeta(
            source_url="generator_permits",
            retrieved_at=datetime.utcnow(),
            parser_version="oci-share-v1.0.0",
            confidence=0.80,
        ),
    )
