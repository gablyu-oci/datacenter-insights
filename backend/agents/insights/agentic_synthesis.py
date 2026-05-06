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

from .hypothesizer import FactPack
from .prompts import load_prompt
from .session_tools import (
    clear_session_fact_pack,
    register_session_fact_pack,
)

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
    fact_pack: FactPack,
    max_insights: int = 5,
    db: AsyncSession,
    sse_emit: Optional[Callable[[Any], Awaitable[None]]] = None,
    cron_run_date: Optional[date] = None,
    mode: Literal["manual", "scheduled"] = "manual",
) -> SynthesisResult:
    """Drive one agentic synthesis turn end-to-end.

    Args:
      session_id: UUID of the parent ``ai_session`` row, already
        persisted in `status='running'` by the caller.
      fact_pack: pre-built FactPack; used both as a digest in the user
        prompt and (in-memory) as the row-id allowlist for
        ``persist_insight``.
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
      itself; this driver does not persist insights directly.
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
        # Ship a digest, not the full FactPack — the agent uses
        # query_database / get_chart_data to drill in (FR-2.7).
        "factpack_digest": _factpack_digest(fact_pack),
        "instructions": (
            "Use query_database / get_chart_data / web_search / run_skill to "
            "drill into the FactPack. Persist each insight via "
            f"persist_insight(session_id='{session_id}', insight=..., "
            "supporting_row_ids=[...]). Optionally emit_chart per insight. "
            f"After {int(max_insights)} insights (or when evidence is "
            f"exhausted), call finalize_session(session_id='{session_id}', "
            "status='complete', token_estimate=...). Caps: 12 turns, 30 "
            "tool calls, 600s wall."
        ),
    }
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": synthesis_rules},
        {
            "role": "user",
            "content": json.dumps(user_pack, default=str, separators=(",", ":")),
        },
    ]

    # 3. Build the synthesis accumulator + register the FactPack so
    #    persist_insight can filter row_ids server-side.
    acc = SynthesisChunkAccumulator(
        session_id=str(session_id),
        thread_id=str(session_id),
        message_id=f"msg_{uuid.uuid4().hex[:12]}",
        insight_id="",
    )
    register_session_fact_pack(session_id, fact_pack)

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
    finally:
        clear_session_fact_pack(session_id)

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


def _factpack_digest(fact_pack: FactPack | None) -> dict[str, Any]:
    """Full FactPack payload for the synthesis prompt.

    The agent needs the actual row bodies (entity, metric, value, detail) to
    ground insights — sending only section names + counts forced the agent
    to drill via query_database without knowing what to look for, which
    consistently produced 0 insights. Inline the full pack: ~100 rows
    typical, ~10KB serialized, well under the 200K context budget. The
    agent can still call query_database for follow-on drill-down.
    """
    if fact_pack is None:
        return {"sections": [], "total_rows": 0}

    sections_payload: list[dict[str, Any]] = []
    total = 0
    for section in fact_pack.sections:
        rows_out: list[dict[str, Any]] = []
        for r in (section.rows or []):
            rows_out.append({
                "row_id": r.row_id,
                "entity": r.entity,
                "metric": r.metric,
                "value": r.value,
                "delta": r.delta,
                "detail": r.detail or {},
            })
        total += len(rows_out)
        sections_payload.append({
            "name": section.name,
            "description": section.description,
            "rows": rows_out,
        })
    return {
        "sections": sections_payload,
        "total_rows": total,
    }


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
