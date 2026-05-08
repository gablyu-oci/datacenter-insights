"""Agentic synthesis driver (Phase 2 / PRD/ARCH 14 §4).

Public entry point: ``run_agentic_synthesis``. The orchestrator calls
this in place of ``_phase_hypothesize_iter`` +
``_phase_verify_and_synthesize_iter`` when ``settings.synthesis_mode ==
"agentic"`` (default after Phase 2 is GA). The legacy phases stay in
the orchestrator until Phase 5 deletes them.

Wire-flow:
  1. Load the per-mode rules from `prompts/synthesis_rules.md`.
  2. Compose ``messages = [system, user]`` where ``user`` is a small
     JSON pack with the FactPack digest + max_insights + session_id.
  3. Open a `_drive_openclaw_stream` against
     `{settings.openclaw_gateway_url}/v1/chat/completions` with
     `x-openclaw-session-key=<derived from mode>`.
  4. Drain the SSE through `translate_synthesis_chunk` and let each
     event flow through the caller-supplied `sse_emit`.
  5. On caps / wall-clock / degraded close, mark the ai_session row
     `degraded` (or leave it `running` for the orchestrator to finish
     finalizing) and return a `SynthesisResult`.

The driver NEVER calls ``task.cancel()``; the only way out is the
cooperative break inside `_drive_openclaw_stream` (httpx issues #1461,
#2437).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Awaitable, Callable, Literal, Optional

from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from openclaw.forwarder import StreamResult, _drive_openclaw_stream
from openclaw.sse_translator import (
    SynthesisChunkAccumulator,
    translate_synthesis_chunk,
)

from .prompts import load_prompt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class SynthesisRunError(RuntimeError):
    """Raised when the agentic synthesis driver cannot proceed.

    This is reserved for unrecoverable errors (e.g. OpenClaw gateway
    refuses every request); cap-trips and degraded closes are reported
    via `SynthesisResult.degraded` instead.
    """


@dataclass
class SynthesisResult:
    """Outcome of one ``run_agentic_synthesis`` invocation."""

    insights_count: int
    degraded: bool
    reason: Optional[str]
    total_chunks: int = 0
    total_tool_calls: int = 0


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


_SYNTHESIS_WALL_TIMEOUT_S = 620.0


async def run_agentic_synthesis(
    *,
    session_id: uuid.UUID,
    max_insights: int = 5,
    db: AsyncSession,
    sse_emit: Optional[Callable[[Any], Awaitable[None]]] = None,
    cron_run_date: Optional[date] = None,
    mode: Literal["manual", "scheduled"] = "manual",
) -> SynthesisResult:
    """Drive one agentic synthesis turn end-to-end (v2).

    Args:
      session_id: UUID of the parent ``ai_session`` row, already
        persisted in `status='running'` by the caller.
      max_insights: target insight count; the agent's stop condition.
      db: open AsyncSession used for the fallback DB write when the
        loop ends degraded WITHOUT the agent calling
        ``finalize_session``.
      sse_emit: per-event async sink. None for cron flows; the manual
        flow passes a queue.put_nowait-style callback so events bubble
        up to the StreamingResponse.
      cron_run_date: when ``mode == "scheduled"`` AND this is set, the
        OpenClaw sessionKey embeds it; otherwise the manual prefix is
        used.
      mode: "manual" (Run again button) or "scheduled" (APScheduler).

    Returns:
      A `SynthesisResult` summarising what happened. Insight rows are
      persisted via the MCP `persist_insight` tool that the agent calls
      itself; this driver does not persist insights directly. The agent
      reads workspace artefacts (SCHEMA.md, FRESHNESS.md, AI_INSIGHTS_*)
      via ``read_workspace`` and grounds claims with ``search_documents``
      / ``query_database`` instead of consuming a server-built FactPack.
    """
    # 1. Derive the OpenClaw session key.
    session_key = _build_session_key(
        mode=mode,
        cron_run_date=cron_run_date,
        session_id=session_id,
    )

    # 2. Compose system + user messages.
    try:
        synthesis_rules = load_prompt("synthesis_rules")
    except FileNotFoundError:
        # Defensive — the file is shipped with the repo. If missing we
        # still want to attempt the run with an empty system prompt so
        # the failure surfaces as a model-level "no insights" rather
        # than an import-time crash.
        logger.warning("agentic_synthesis.synthesis_rules_missing")
        synthesis_rules = ""

    user_pack = {
        "today": datetime.utcnow().date().isoformat(),
        "session_id": str(session_id),
        "max_insights": int(max_insights),
        # v2: agent orients by reading workspace artefacts and grounds
        # claims via search_documents + query_database. No server-built
        # FactPack is shipped in the prompt — see synthesis_rules.md.
        "workspace_pointers": [
            ".openclaw/workspace/SCHEMA.md",
            ".openclaw/workspace/FRESHNESS.md",
            ".openclaw/workspace/AI_INSIGHTS_PLAYBOOK.md",
            ".openclaw/workspace/AI_INSIGHTS_PREFLIGHT_CHECKLIST.md",
            ".openclaw/workspace/AI_INSIGHTS_SQL_SCHEMA_DISCIPLINE.md",
        ],
        "instructions": (
            "Per-insight loop, ONE AT A TIME — DO NOT batch persists at the end:\n"
            "  1. drill: read_workspace + query_database (+ search_documents for prose).\n"
            "  2. persist_insight(session_id='" + str(session_id) + "', headline=..., body=..., confidence=..., materiality=..., citations=[]). Capture the returned insight_id.\n"
            "  3. build_chart(insight_id=<from step 2>, sql=..., encoding=..., chart_type=..., title=...). MANDATORY for every insight unless it's a literal yes/no scalar. SKIPPING THIS IS A BUG.\n"
            "  4. Loop back to step 1.\n"
            f"After {int(max_insights)} insights (or evidence exhausted), call "
            f"finalize_session(session_id='{session_id}', status='complete', token_estimate=...).\n"
            "FORBIDDEN: persisting all insights then calling build_chart at the end. The chart calls land after finalize_session and are silently dropped — the session ends with insights but zero charts. Always persist→chart→persist→chart, interleaved.\n"
            "Caps: 12 turns, 30 tool calls, 600s wall."
        ),
    }
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": synthesis_rules},
        {
            "role": "user",
            "content": json.dumps(user_pack, default=str, separators=(",", ":")),
        },
    ]

    # 3. Build the synthesis accumulator. v2 has no server-side FactPack
    #    registry — row-id grounding is replaced by chart-level provenance
    #    (executed_sql + row_hash) inside build_chart + persist_insight.
    acc = SynthesisChunkAccumulator(
        session_id=str(session_id),
        thread_id=str(session_id),
        message_id=f"msg_{uuid.uuid4().hex[:12]}",
        insight_id="",
    )

    async def _emit(evt: Any) -> None:
        if sse_emit is not None:
            try:
                await sse_emit(evt)
            except Exception:  # noqa: BLE001 — never let a sink kill the stream
                logger.exception("agentic_synthesis.sse_emit_failed")

    # 4. Drive the stream under a wall-clock safety belt. The shared
    #    driver enforces caps cooperatively; the wait_for is a belt-and-
    #    suspenders for pathological httpx hangs.
    stream_result: StreamResult
    try:
        stream_result = await asyncio.wait_for(
            _drive_openclaw_stream(
                session_key=session_key,
                messages=messages,
                on_translated_event=_emit,
                accumulator=acc,
                translator=translate_synthesis_chunk,
                cap_turns=12,
                cap_tool_calls=30,
                cap_wall_seconds=600.0,
            ),
            timeout=_SYNTHESIS_WALL_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning("agentic_synthesis.outer_wall_timeout")
        stream_result = StreamResult(
            degraded=True, reason="wall_clock", total_chunks=0
        )

    # 5. Degraded -> set ai_session.status='degraded' as a server-side
    #    safety net (the agent should have called finalize_session, but
    #    if it didn't we don't want the session row stuck in 'running').
    if stream_result.degraded or not acc.finalize_seen:
        await _force_finalize_degraded(
            db,
            session_id=session_id,
            reason=stream_result.reason or "no_finalize_seen",
            insights_count=acc.total_insights_persisted,
        )

    return SynthesisResult(
        insights_count=acc.total_insights_persisted,
        degraded=bool(stream_result.degraded or not acc.finalize_seen),
        reason=stream_result.reason if stream_result.degraded else None,
        total_chunks=stream_result.total_chunks,
        total_tool_calls=int(acc.cap_counters.get("tool_calls", 0)),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_session_key(
    *,
    mode: str,
    cron_run_date: Optional[date],
    session_id: uuid.UUID,
) -> str:
    """Construct the `x-openclaw-session-key` per ARCH §1 P1."""
    if mode == "scheduled":
        # Manual instructions: cron path explicitly tagged; cron_run_date
        # path uses the daily prefix; otherwise fall back to a stable
        # scheduled-with-no-date marker keyed by session_id.
        if cron_run_date is not None:
            return f"daily-synthesis-{cron_run_date.strftime('%Y%m%d')}-scheduled"
        return f"daily-synthesis-{session_id}-scheduled"
    if cron_run_date is not None:
        return f"daily-synthesis-{cron_run_date.strftime('%Y%m%d')}"
    return f"manual-{session_id}"


async def _force_finalize_degraded(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    reason: str,
    insights_count: int,
) -> None:
    """Direct DB update when the agentic loop ends without finalize.

    Avoids round-tripping the MCP tool here because the loop has
    already returned and the agent is no longer present to retry. Best-
    effort: any failure is logged and swallowed so callers always get a
    SynthesisResult.
    """
    try:
        from .db.models import AISession

        # Don't clobber a row another path already finalized.
        from sqlalchemy import select

        existing = (
            await db.execute(select(AISession).where(AISession.id == session_id))
        ).scalar_one_or_none()
        if existing is None:
            return
        if existing.status in ("complete", "degraded", "failed", "cancelled"):
            return

        await db.execute(
            update(AISession)
            .where(AISession.id == session_id)
            .values(
                status="degraded",
                finished_at=datetime.utcnow(),
                insights_emitted=int(insights_count or 0),
                budget_status="clipped",
            )
        )
        await db.commit()
        logger.warning(
            "agentic_synthesis.force_finalize_degraded",
            extra={"session_id": str(session_id), "reason": reason},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "agentic_synthesis.force_finalize_failed",
            extra={"err": str(exc), "session_id": str(session_id)},
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "run_agentic_synthesis",
    "SynthesisResult",
    "SynthesisRunError",
]
