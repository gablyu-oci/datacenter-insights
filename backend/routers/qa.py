"""
Datacenter Q&A SSE route.

Prefix: /api/qa
POST /api/qa/ask -- streams a sequence of typed events (text_chunk,
tool_call, tool_result, chart_spec, citation, error, done) as SSE.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from agents.datacenter_qa import answer_question
from db.session import async_session_factory
from schemas.qa import AskRequest

router = APIRouter(prefix="/api/qa", tags=["qa"])
logger = logging.getLogger(__name__)


@router.post("/ask")
async def ask(body: AskRequest):
    """
    Stream a tool-using QA answer over Server-Sent Events.

    Each `data:` line is a JSON object with a `type` discriminator that
    matches one of the QAEvent variants in schemas/qa.py.
    """

    async def gen():
        async with async_session_factory() as session:
            try:
                async for event in answer_question(
                    session,
                    body.question,
                    body.history,
                    x_session_id=body.session_id,
                ):
                    payload = event.model_dump()
                    yield f"data: {json.dumps(payload, default=str)}\n\n"
            except Exception as exc:  # noqa: BLE001
                logger.exception("qa.ask.failed")
                err = {"type": "error", "message": str(exc)}
                yield f"data: {json.dumps(err)}\n\n"
            finally:
                # Always emit a terminal done event so the client can close.
                yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
