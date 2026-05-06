"""Triangulation Q&A agent — OpenClaw QA-lane shim.

Phase 5-followup (PRD/ARCH 15 §3-§4): the triangulation agent is now a
thin wrapper around ``backend/openclaw/qa_forwarder.iter_qa_events``.
Tool dispatch (query_database, web_search, run_skill, call_api) happens
inside the OpenClaw gateway under the agent's MCP toolset; this shim
flattens the resulting QAEvent stream into plain text deltas so
``backend/routers/agent.py`` can keep its existing wire contract
(``data: <delta>`` lines terminated by ``data: [DONE]``).

Public surface preserved:
  ``answer_question_stream(session, question) -> AsyncIterator[str]``

The system prompt body lives at
``backend/agents/insights/prompts/triangulation_rules.md``.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from agents.insights.prompts import load_prompt
from openclaw.qa_forwarder import iter_qa_events

logger = logging.getLogger(__name__)


# OpenClaw memory namespace for the triangulation agent. Distinct from
# `qa:global` so the two agents don't share memory state.
_TRIANGULATION_NAMESPACE = "triangulation"


async def answer_question_stream(
    session: AsyncSession,
    question: str,
    *,
    x_session_id: Optional[str] = None,
) -> AsyncIterator[str]:
    """Stream a triangulation Q&A answer as plain text deltas.

    The ``session`` parameter is retained for signature compatibility
    with ``routers/agent.py``; tool dispatch happens inside OpenClaw,
    so this shim does not use the DB session directly.

    Args:
      session: caller-managed AsyncSession (unused; kept for back-compat).
      question: the user's natural-language question.
      x_session_id: optional client-supplied session id; falls back to
        a deterministic hash of the question.

    Yields:
      ``str`` deltas. Errors are yielded as a single
      ``"[error: <message>]"`` marker before the iterator closes —
      the route handler is responsible for the terminal ``[DONE]``.
    """
    del session  # parameter kept for signature compatibility only
    system_prompt = load_prompt("triangulation_rules")

    async for evt in iter_qa_events(
        question=question,
        history=[],
        system_prompt=system_prompt,
        namespace=_TRIANGULATION_NAMESPACE,
        x_session_id=x_session_id,
        # Triangulation answers are prose-only — drop tool plumbing so
        # it doesn't leak into the response stream.
        surface_tool_events=False,
    ):
        cls_name = evt.__class__.__name__
        if cls_name == "TextChunkEvent":
            content = getattr(evt, "content", "") or ""
            if content:
                yield content
        elif cls_name == "ErrorEvent":
            msg = getattr(evt, "message", "unknown") or "unknown"
            yield f"[error: {msg}]"
        # ChartSpecEvent / CitationEvent intentionally dropped — the
        # triangulation lane emits cited prose with inline URLs, not
        # structured chart specs.


__all__ = ["answer_question_stream"]
