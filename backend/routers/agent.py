"""
Agent / QA endpoints.
Prefix: /api/agent

Phase 1C: /ask is wired to the Triangulation Q&A agent.
The /qa/conversations/{id} and /llc-resolve/{permittee_id} routes remain
501 stubs (out of scope for Phase 1C).
"""
from __future__ import annotations

import json as _json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.triangulation_qa import answer_question_stream
from db.session import async_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])


class AskBody(BaseModel):
    question: str


@router.post("/ask")
async def ask(body: AskBody):
    """
    Ask the Triangulation Q&A agent a natural-language question.

    Returns a Server-Sent-Events stream. Each event is a `data:` line
    carrying a partial answer chunk; the stream ends with `data: [DONE]`.
    Errors during streaming are surfaced as a single
    `data: {"error": "..."}` event before [DONE].
    """
    async def gen():
        async with async_session_factory() as session:
            try:
                async for delta in answer_question_stream(session, body.question):
                    # SSE framing: replace embedded newlines so each delta
                    # is exactly one `data:` event.
                    payload = (delta or "").replace("\n", "\\n")
                    yield f"data: {payload}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as exc:  # noqa: BLE001
                logger.exception("agent.ask.stream_failed")
                yield f"data: {_json.dumps({'error': str(exc)})}\n\n"
                yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/qa/conversations/{id}")
def get_conversation(id: str):
    raise HTTPException(status_code=501, detail="Not implemented -- scheduled for Phase 1")


@router.post("/llc-resolve/{permittee_id}")
def llc_resolve(permittee_id: str):
    raise HTTPException(status_code=501, detail="Not implemented -- scheduled for Phase 1")
