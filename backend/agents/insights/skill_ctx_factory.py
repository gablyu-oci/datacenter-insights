"""SkillContext factory shared by the agent_tools HTTP router and the
MCP server.

The behavior here is the EXACT code lifted from
``backend/routers/agent_tools.py`` (where it previously lived as the
private ``_build_skill_ctx`` helper). It was extracted so both
``backend/routers/agent_tools.py`` and ``backend/mcp_server.py`` can
share a single construction site and stay in lock-step. Do NOT alter
behavior here without updating both call sites and the architecture
doc (``docs/plans/ai-insights-automation/13-mcp-migration-architecture.md``).

Imports inside the function bodies are deliberately lazy: the callers
are import-cycle sensitive (the chat router pulls in agents/skill code
that itself lazily imports from ``routers.insights``), and matching the
prior shape keeps regression risk to zero.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession


async def _noop_emit_event(_evt: Any) -> None:
    """No-op SSE emitter for tool calls dispatched through OpenClaw.

    The OpenClaw forwarder synthesises tool_call_started / tool_call_complete
    events from its own SSE stream, so individual tool functions do NOT
    need to publish them here. (See ARCH 11b §3.4 step 2.)
    """
    return None


async def build_skill_ctx(
    db: AsyncSession,
    *,
    insight_id: uuid.UUID,
    thread_id_hint: Optional[str],
    session_id_hint: Optional[str],
) -> Any:
    """Construct a `SkillContext` to pass into the tool dispatcher.

    Mirrors the construction inside `post_insight_chat` in
    `backend/routers/insights.py`, with one difference: `emit_event` is
    a no-op (OpenClaw owns the SSE event lifecycle on the chat path).
    If `thread_id_hint` is missing we derive one via the existing
    `_get_or_create_thread` helper from `routers.insights`.
    """
    # Lazy imports — these modules pull in a lot of agents-tier code.
    from agents.insights.specs.skill_context import Capabilities, SkillContext
    from llm.client import MODELS  # type: ignore
    from routers.insights import (
        CHAT_WALL_BUDGET_S,
        _get_or_create_thread,
    )
    from agents.insights.db.models import AIInsight
    from sqlalchemy import select

    # During SYNTHESIS the agent calls tools BEFORE any AIInsight has been
    # persisted, so insight_id is a placeholder that doesn't exist yet.
    # In that case we skip thread creation (chat threads are a chat-lane
    # concern) and reuse session_id_hint as the synthetic thread scope.
    insight_row = (
        await db.execute(select(AIInsight).where(AIInsight.id == insight_id))
    ).scalar_one_or_none()

    if thread_id_hint:
        thread_id_str = thread_id_hint
    elif insight_row is not None:
        thread = await _get_or_create_thread(db, insight_id=insight_id)
        thread_id_str = str(thread.id)
    elif session_id_hint:
        # Synthesis lane: no chat thread needed; use session_id as scope.
        thread_id_str = session_id_hint
    else:
        # Last resort: synthesise a thread_id from the insight uuid itself.
        thread_id_str = str(insight_id)

    if session_id_hint:
        session_id_str = session_id_hint
    elif insight_row is not None:
        session_id_str = str(insight_row.session_id)
    else:
        # QA lane: freeform Q&A has neither an insight nor an AISession.
        # session_id is only used downstream for audit/correlation tags
        # (e.g. web_search log rows), never dereferenced to a DB row, so
        # a synthesised UUID is safe and lets read-only tools run.
        session_id_str = str(uuid.uuid4())

    return SkillContext(
        session_id=session_id_str,
        turn_id=f"oc_{uuid.uuid4().hex[:8]}",
        correlation_id=f"oc_{insight_id}_{uuid.uuid4().hex[:8]}",
        model=MODELS["reasoning"],
        budget_seconds_remaining=CHAT_WALL_BUDGET_S,
        capabilities=Capabilities(
            can_query_db=True,
            can_call_api=True,
            can_get_chart_data=True,
            can_emit_chart=True,
            can_emit_citation=True,
            can_web_search=True,
        ),
        thread_id=thread_id_str,
        insight_id=str(insight_id),
        emit_event=_noop_emit_event,
    )
