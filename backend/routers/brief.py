"""
Weekly brief endpoints -- Phase 1 stubs.
Prefix: /api/brief
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/brief", tags=["brief"])


@router.get("/weekly")
def weekly_brief():
    raise HTTPException(status_code=501, detail="Not implemented -- scheduled for Phase 1")


@router.get("/weekly/history")
def weekly_brief_history():
    raise HTTPException(status_code=501, detail="Not implemented -- scheduled for Phase 1")
