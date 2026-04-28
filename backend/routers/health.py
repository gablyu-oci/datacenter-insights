"""
Health-check router.
GET /api/health  -- canonical path
GET /health      -- legacy compatibility
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter
from sqlalchemy import text

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
                return "ok"
            return "unreachable"
    except Exception:
        return "unreachable"


async def _health_payload() -> dict:
    db_status = await _check_db()
    llama_status = await _check_llama_stack()
    overall = "ok" if db_status == "connected" else "degraded"
    return {
        "status": overall,
        "version": settings.app_version,
        "db": db_status,
        "llama_stack": llama_status,
    }


@router.get("/api/health")
async def health_canonical():
    return await _health_payload()


@router.get("/health")
async def health_legacy():
    """Legacy endpoint preserved for backward compatibility."""
    return await _health_payload()
