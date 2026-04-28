"""
Data sources and agent status endpoints.
Prefix: /api/sources

When MOCK_DATA=1, returns mock source data.
When MOCK_DATA=0, queries ingestion_runs table for real source info.
"""
from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from db.models import IngestionRun
from schemas.common import LineageEnvelope, LineageMeta

MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("/")
async def sources(db: AsyncSession = Depends(get_db)):
    if MOCK_ENABLED:
        from data.mock_data import get_sources_data, get_agent_status

        return LineageEnvelope(
            data={"sources": get_sources_data(), "agents": get_agent_status()},
            lineage=LineageMeta(
                source_url="mock",
                retrieved_at=datetime.utcnow(),
                parser_version="mock-v1",
                confidence=0.5,
            ),
        )

    # Real DB query: aggregate ingestion_runs by adapter_name
    stmt = (
        select(
            IngestionRun.adapter_name,
            IngestionRun.adapter_version,
            func.max(IngestionRun.started_at).label("last_run_at"),
            func.max(IngestionRun.completed_at).label("last_completed_at"),
            # Most recent status per adapter (via subquery would be ideal,
            # but for simplicity we grab the latest)
            func.sum(IngestionRun.records_stored).label("total_records_stored"),
            func.count(IngestionRun.id).label("run_count"),
        )
        .group_by(IngestionRun.adapter_name, IngestionRun.adapter_version)
        .order_by(IngestionRun.adapter_name)
    )
    result = await db.execute(stmt)
    rows = result.fetchall()

    sources_list = []
    agents_list = []
    for row in rows:
        adapter_name, adapter_version, last_run_at, last_completed_at, total_stored, run_count = row
        sources_list.append(
            {
                "name": adapter_name,
                "version": adapter_version,
                "last_run_at": last_run_at.isoformat() if last_run_at else None,
                "last_completed_at": last_completed_at.isoformat() if last_completed_at else None,
                "total_records_stored": total_stored or 0,
                "run_count": run_count,
            }
        )
        agents_list.append(
            {
                "name": adapter_name,
                "status": "active" if last_completed_at else "unknown",
                "last_run": last_run_at.isoformat() if last_run_at else None,
            }
        )

    # Get the latest run status per adapter for richer agent info
    latest_runs_stmt = (
        select(IngestionRun)
        .order_by(IngestionRun.started_at.desc())
        .limit(20)
    )
    latest_result = await db.execute(latest_runs_stmt)
    latest_runs = latest_result.scalars().all()

    # Override agent status with latest run info
    latest_by_adapter = {}
    for run in latest_runs:
        if run.adapter_name not in latest_by_adapter:
            latest_by_adapter[run.adapter_name] = run

    for agent in agents_list:
        run = latest_by_adapter.get(agent["name"])
        if run:
            agent["status"] = run.status
            if run.error_log:
                agent["last_error"] = str(run.error_log)[:200]

    return LineageEnvelope(
        data={"sources": sources_list, "agents": agents_list},
        lineage=LineageMeta(
            source_url="ingestion_runs",
            retrieved_at=datetime.utcnow(),
            parser_version="sources-v1.0.0",
            confidence=1.0,
        ),
    )
