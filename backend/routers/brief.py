"""
Weekly brief endpoints -- Phase 1C.
Prefix: /api/brief
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, desc

from db.session import async_session_factory
from db.models import BriefRun
from agents.weekly_brief import generate_weekly_brief

router = APIRouter(prefix="/api/brief", tags=["brief"])


def _serialize(row: BriefRun) -> dict:
    return {
        "id": row.id,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "period_start": row.period_start.isoformat() if row.period_start else None,
        "period_end": row.period_end.isoformat() if row.period_end else None,
        "markdown": row.markdown,
        "model": row.model,
        "prompt_version": row.prompt_version,
        "bullet_count": row.bullet_count,
    }


@router.get("/latest")
async def latest():
    async with async_session_factory() as session:
        row = (await session.execute(
            select(BriefRun).order_by(desc(BriefRun.generated_at)).limit(1)
        )).scalars().first()
        if row is None:
            return {"markdown": None, "generated_at": None}
        return _serialize(row)


@router.post("/run")
async def run():
    async with async_session_factory() as session:
        row = await generate_weekly_brief(session)
        return _serialize(row)


@router.get("/weekly/history")
async def history():
    async with async_session_factory() as session:
        rows = (await session.execute(
            select(BriefRun).order_by(desc(BriefRun.generated_at)).limit(10)
        )).scalars().all()
        return [_serialize(r) for r in rows]
