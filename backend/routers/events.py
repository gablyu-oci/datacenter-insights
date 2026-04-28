"""
Events timeline endpoints -- Phase 1A real DB queries.
Prefix: /api/events
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from db.models import Event
from schemas.common import CoverageEnvelope, CoverageMeta, LineageMeta

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("/")
async def list_events(
    aterio_dc_uid: Optional[str] = Query(None, description="Filter by site aterio_dc_uid"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    date_from: Optional[date] = Query(None, description="Events on or after this date"),
    date_to: Optional[date] = Query(None, description="Events on or before this date"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Filterable timeline of events."""
    query = select(Event)
    count_query = select(func.count(Event.id))

    if aterio_dc_uid:
        query = query.where(Event.aterio_dc_uid == aterio_dc_uid)
        count_query = count_query.where(Event.aterio_dc_uid == aterio_dc_uid)
    if event_type:
        query = query.where(Event.event_type == event_type)
        count_query = count_query.where(Event.event_type == event_type)
    if date_from:
        query = query.where(Event.event_date >= date_from)
        count_query = count_query.where(Event.event_date >= date_from)
    if date_to:
        query = query.where(Event.event_date <= date_to)
        count_query = count_query.where(Event.event_date <= date_to)

    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    query = query.order_by(Event.event_date.desc().nullslast(), Event.id).offset(offset).limit(page_size)
    result = await db.execute(query)
    events = result.scalars().all()

    return CoverageEnvelope(
        data={
            "data": [_event_to_dict(e) for e in events],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        lineage=LineageMeta(
            source_url="aterio_events_csv",
            retrieved_at=datetime.utcnow(),
            parser_version="aterio-v1.0.0",
            confidence=0.80,
        ),
        coverage=CoverageMeta(pillar="events"),
    )


def _event_to_dict(event: Event) -> dict:
    """Convert Event model to dict."""
    d = {}
    for col in Event.__table__.columns:
        val = getattr(event, col.name, None)
        if isinstance(val, (datetime, date)):
            val = val.isoformat()
        d[col.name] = val
    return d
