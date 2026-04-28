"""
Energy projects endpoints -- Phase 1A real DB queries.
Prefix: /api/energy-projects
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from db.models import EnergyProject
from schemas.common import CoverageEnvelope, CoverageMeta, LineageMeta

router = APIRouter(prefix="/api/energy-projects", tags=["energy-projects"])


@router.get("/")
async def list_energy_projects(
    developer: Optional[str] = Query(None, description="Filter by developer name (partial match)"),
    customer: Optional[str] = Query(None, description="Filter by customer company (partial match)"),
    state: Optional[str] = Query(None, description="Filter by state code"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Filterable, paginated list of energy projects."""
    query = select(EnergyProject)
    count_query = select(func.count(EnergyProject.id))

    if developer:
        query = query.where(EnergyProject.developer_companies.ilike(f"%{developer}%"))
        count_query = count_query.where(EnergyProject.developer_companies.ilike(f"%{developer}%"))
    if customer:
        query = query.where(EnergyProject.customer_companies.ilike(f"%{customer}%"))
        count_query = count_query.where(EnergyProject.customer_companies.ilike(f"%{customer}%"))
    if state:
        query = query.where(EnergyProject.state_code == state.upper())
        count_query = count_query.where(EnergyProject.state_code == state.upper())

    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    query = query.order_by(EnergyProject.id).offset(offset).limit(page_size)
    result = await db.execute(query)
    projects = result.scalars().all()

    # States for coverage metadata
    states_result = await db.execute(
        select(EnergyProject.state_code)
        .where(EnergyProject.state_code.isnot(None))
        .distinct()
    )
    states_included = [r[0] for r in states_result.fetchall()]

    return CoverageEnvelope(
        data={
            "data": [_project_to_dict(p) for p in projects],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        lineage=LineageMeta(
            source_url="aterio_energy_projects_csv",
            retrieved_at=datetime.utcnow(),
            parser_version="aterio-v1.0.0",
            confidence=0.80,
        ),
        coverage=CoverageMeta(
            pillar="energy_projects",
            states_included=states_included,
        ),
    )


def _project_to_dict(proj: EnergyProject) -> dict:
    """Convert EnergyProject model to dict."""
    d = {}
    for col in EnergyProject.__table__.columns:
        val = getattr(proj, col.name, None)
        if isinstance(val, datetime):
            val = val.isoformat()
        d[col.name] = val
    return d
