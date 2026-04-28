"""
Agent / QA endpoints -- Phase 1 stubs.
Prefix: /api/agent
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/qa")
def ask_question():
    raise HTTPException(status_code=501, detail="Not implemented -- scheduled for Phase 1")


@router.get("/qa/conversations/{id}")
def get_conversation(id: str):
    raise HTTPException(status_code=501, detail="Not implemented -- scheduled for Phase 1")


@router.post("/llc-resolve/{permittee_id}")
def llc_resolve(permittee_id: str):
    raise HTTPException(status_code=501, detail="Not implemented -- scheduled for Phase 1")
