"""
Health-check router.
GET /api/health  -- canonical path
GET /health      -- legacy compatibility
"""
from __future__ import annotations

from typing import Optional

import httpx
from fastapi import APIRouter
from sqlalchemy import func, select, text

from config import settings

router = APIRouter(tags=["health"])


async def _check_db() -> str:
    """Attempt a lightweight DB ping via asyncpg."""
    try:
        from db.session import engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "connected"
    except Exception:
        return "error"


async def _check_llama_stack() -> str:
    """Probe Llama Stack health endpoint."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.llama_stack_url}/v1/health")
            if resp.status_code < 400:
                return "connected"
            return "unreachable"
    except Exception:
        return "unreachable"


async def _agent_signals() -> tuple[int, Optional[str]]:
    """Active scheduled agents (size of JOB_CONFIG) and the most-recent
    adapter run that landed data (max IngestionRun.completed_at where
    status in {success, partial_failure}). Returns (count, iso_ts);
    either may be falsy if the runner or DB is unavailable."""
    count = 0
    last_sync: Optional[str] = None
    try:
        from pipeline.runner import JOB_CONFIG
        count = len(JOB_CONFIG)
    except Exception:
        pass
    try:
        from db.models import IngestionRun
        from db.session import engine
        async with engine.connect() as conn:
            stmt = select(func.max(IngestionRun.completed_at)).where(
                IngestionRun.status.in_(["success", "partial_failure"])
            )
            result = await conn.execute(stmt)
            ts = result.scalar_one_or_none()
            if ts is not None:
                last_sync = ts.isoformat()
    except Exception:
        pass
    return count, last_sync


async def _health_payload() -> dict:
    db_status = await _check_db()
    llama_status = await _check_llama_stack()
    agents_active, last_sync = await _agent_signals()
    overall = "ok" if db_status == "connected" else "degraded"
    return {
        "status": overall,
        "version": settings.app_version,
        "db": db_status,
        "llama_stack": llama_status,
        "agents_active": agents_active,
        "last_sync": last_sync,
    }


@router.get("/api/health")
async def health_canonical():
    return await _health_payload()


@router.get("/health")
async def health_legacy():
    """Legacy endpoint preserved for backward compatibility."""
    return await _health_payload()
