"""Datacenter Q&A agent — OpenClaw QA-lane shim.

Phase 5-followup (PRD/ARCH 15 §3-§4): the QA agent no longer drives its
own LLM tool-loop. All tool dispatch (query_database, web_search,
propose_qa_chart, emit_citation, run_skill) happens inside the OpenClaw
gateway under the agent's MCP toolset, and the SSE translator at
``backend/openclaw/sse_translator.translate_qa_chunk`` converts each
streamed gateway frame into the project's frozen ``QAEvent`` union.

This module is therefore a thin shim around
``backend/openclaw/qa_forwarder.iter_qa_events``. It preserves the
public ``answer_question(session, question, history) -> AsyncIterator[QAEvent]``
signature so ``backend/routers/qa.py`` does not need to change.

The full schema-aware system prompt now lives at
``backend/agents/insights/prompts/qa_global_rules.md`` (loaded once,
lru-cached). The OpenClaw gateway holds prior turns under the
session_key, so we forward the user message + history transparently.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from agents.insights.prompts import load_prompt
from openclaw.qa_forwarder import iter_qa_events
from schemas.qa import Message, QAEvent

logger = logging.getLogger(__name__)


# OpenClaw memory namespace for the global QA agent. Different from the
# triangulation namespace so the two lanes do not share memory state.
_QA_NAMESPACE = "qa:global"


async def answer_question(
    session: AsyncSession,
    question: str,
    history: Optional[list[Message]] = None,
    *,
    x_session_id: Optional[str] = None,
) -> AsyncIterator[QAEvent]:
    """Stream QAEvents for a user question.

    The ``session`` parameter is retained for signature compatibility
    with ``routers/qa.py``; tool dispatch happens inside OpenClaw via
    MCP, so this shim does not use the DB session directly.

    Args:
      session: caller-managed AsyncSession (unused; kept for back-compat).
      question: the user's question for this turn.
      history: prior turns. Trimmed by the caller; OpenClaw also keeps
        per-session memory under the session_key.
      x_session_id: optional client-supplied session id; falls back to
        a deterministic hash of the question (see
        ``openclaw.qa_forwarder._qa_session_key``).

    Yields:
      ``QAEvent`` instances — text_chunk, tool_call, tool_result,
      chart_spec, citation, error. The terminal ``done`` event is
      emitted by the route handler's ``finally`` block (matches the
      legacy contract; see ``routers/qa.py``).
    """
    del session  # parameter kept for signature compatibility only
    history = history or []
    system_prompt = load_prompt("qa_global_rules")

    async for evt in iter_qa_events(
        question=question,
        history=history,
        system_prompt=system_prompt,
        namespace=_QA_NAMESPACE,
        x_session_id=x_session_id,
        surface_tool_events=True,
    ):
        # `iter_qa_events` already yields concrete QAEvent variants
        # (TextChunkEvent, ToolCallEvent, ToolResultEvent, ChartSpecEvent,
        # CitationEvent, ErrorEvent); they all satisfy the QAEvent
        # discriminated union without further wrapping.
        yield evt


__all__ = ["answer_question"]
