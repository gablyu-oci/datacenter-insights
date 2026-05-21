"""Agentic synthesis driver.

Public entry point: ``run_agentic_synthesis``. The agent grounds its
own claims via the OpenClaw MCP tools (`search_documents`,
`query_database`, `read_workspace`) and persists insights through
`persist_insight`; the driver only orchestrates the stream and writes
a terminal `ai_session.status` based on what landed in the database.

Wire-flow:
  1. Load `prompts/synthesis_rules.md`.
  2. Compose ``messages = [system, user]`` where ``user`` is a small
     JSON pack with workspace pointers + max_insights + session_id +
     run instructions.
  3. Open `_drive_openclaw_stream` against
     `{settings.openclaw_gateway_url}/v1/chat/completions` with
     `x-openclaw-session-key=<derived from mode>`.
  4. Drain the SSE through `translate_synthesis_chunk`.
  5. After the stream ends, re-read the `ai_insight` rows for this
     session and finalize the `ai_session` row:
       - >=1 insight persisted -> ``status='complete'``
       - 0 insights persisted  -> ``status='failed'``

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
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable, Literal, Optional

from pydantic import BaseModel
from sqlalchemy import text, update
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
    """Outcome of one ``run_agentic_synthesis`` invocation.

    Fields:
      insights_count: actual ai_insight rows persisted for this session,
        read back from the DB after the stream ends. Authoritative.
      degraded: True iff zero insights were persisted. The terminal
        ``ai_session.status`` is ``failed`` in that case; the field is
        kept for back-compat with the runner's audit log.
      reason: short slug for why the stream ended early when it did
        (cap_trip / wall_clock / http_error / ...). None on clean ends.
      total_chunks / total_tool_calls: stream-side counters; useful
        for ops telemetry but not load-bearing for status decisions.
    """

    insights_count: int
    degraded: bool
    reason: Optional[str]
    total_chunks: int = 0
    total_tool_calls: int = 0


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


_SYNTHESIS_WALL_TIMEOUT_S = 620.0

# Weekly cron: prime the agent with the last 4 runs' worth of headlines so
# it can pivot away from semantically-equivalent hypotheses instead of
# re-emitting last week's insights.
_RECENT_HEADLINE_LOOKBACK_DAYS = 28
_RECENT_HEADLINE_LIMIT = 40


async def _fetch_recent_insight_headlines(
    db: AsyncSession,
    *,
    days: int = _RECENT_HEADLINE_LOOKBACK_DAYS,
    limit: int = _RECENT_HEADLINE_LIMIT,
) -> list[str]:
    """Return headlines from complete sessions in the last `days`, newest first.

    Best-effort: on any DB error returns []. The caller passes the list
    into the user pack so the agent can avoid restating last week's
    insights. Headlines from running/failed sessions are excluded.
    """
    if db is None or days <= 0:
        return []
    cutoff = datetime.utcnow() - timedelta(days=days)
    sql = text(
        """
        SELECT i.headline
          FROM ai_insight i
          JOIN ai_session s ON s.id = i.session_id
         WHERE i.created_at >= :cutoff
           AND s.status = 'complete'
         ORDER BY i.created_at DESC
         LIMIT :lim
        """
    )
    try:
        result = await db.execute(sql, {"cutoff": cutoff, "lim": limit})
        return [row[0] for row in result.all() if row[0]]
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "agentic_synthesis.recent_headlines_failed",
            extra={"error": str(exc), "days": days},
        )
        return []


async def run_agentic_synthesis(
    *,
    session_id: uuid.UUID,
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

    today_d = datetime.utcnow().date()
    this_week_since = (today_d - timedelta(days=7)).isoformat()
    prior_week_since = (today_d - timedelta(days=14)).isoformat()
    recent_headlines = await _fetch_recent_insight_headlines(db)
    user_pack = {
        "today": today_d.isoformat(),
        # Weekly cron anchors: the agent should bias drills to "what
        # changed in the past 7 days" (since `this_week_since`) and
        # compare to the prior week (since `prior_week_since`).
        "this_week_since": this_week_since,
        "prior_week_since": prior_week_since,
        "session_id": str(session_id),
        "max_insights": int(max_insights),
        # Last 4 weeks of complete-session headlines — the agent reads
        # these to avoid restating semantically-equivalent insights.
        "recent_insight_headlines": recent_headlines,
        # Agent orients by reading workspace artefacts and grounds
        # claims via search_documents + query_database — see
        # synthesis_rules.md.
        "workspace_pointers": [
            ".openclaw/workspace/SCHEMA.md",
            ".openclaw/workspace/FRESHNESS.md",
            ".openclaw/workspace/AI_INSIGHTS_PLAYBOOK.md",
            ".openclaw/workspace/AI_INSIGHTS_PREFLIGHT_CHECKLIST.md",
            ".openclaw/workspace/AI_INSIGHTS_SQL_SCHEMA_DISCIPLINE.md",
        ],
        "instructions": (
            "QUALITY BAR for this run:\n"
            f"  - WEEKLY DELTA: this cron is weekly. Anchor every drill to what CHANGED in the past 7 days (filings/permits/transcripts dated `>= '{this_week_since}'`) and compare against the prior 7 days (`>= '{prior_week_since}' AND < '{this_week_since}'`). Fall back to 30/90-day windows ONLY if the 7-day window is too thin to support an insight.\n"
            f"  - AVOID REPETITION: `recent_insight_headlines` lists insights persisted in the last 4 weeks. Do NOT re-emit a hypothesis whose headline is semantically equivalent. Pivot the protagonist (different neo-cloud / hyperscaler), the table (events vs sites vs edgar_extractions), or the geography (different ISO / state). If you find yourself drafting last week's claim, drop it and drill a fresh angle.\n"
            "  - RECENCY: bias every drill to 2026 / latest year. Filter dates `>= '2026-01-01'` or use `events` for last-90-days. Static cumulative metrics (e.g. 'AWS has 40% of VA MW') are common knowledge — DROP THEM.\n"
            "  - OPPORTUNITY OR THREAT: every insight body MUST close with an explicit 'OCI opportunity:' or 'OCI threat:' sentence naming (a) an entity, (b) a window, (c) a number/named action. 'OCI should monitor' / 'OCI should treat as strategic' / 'competitive read' = AUTO-FAIL.\n"
            "  - PORTFOLIO: ≥3 distinct source tables across the run, ≤2 cards per protagonist, ≥1 forward-looking (permits/projects/filings), ≥1 document-grounded (search_documents/edgar_extractions).\n"
            "  - COMMON-KNOWLEDGE TEST: would a datacenter PM already know this from trade press? If yes → DROP and pick a different hypothesis.\n"
            "\n"
            "Per-insight loop, ONE AT A TIME — DO NOT batch persists at the end:\n"
            "  1. drill: read_workspace + query_database (+ search_documents for prose). Apply recency filter on the SQL.\n"
            "  2. persist_insight(session_id='" + str(session_id) + "', headline=..., body=..., confidence=..., materiality=..., citations=[]). Capture the returned insight_id.\n"
            "  3. build_chart(insight_id=<from step 2>, sql=..., encoding=..., chart_type=..., title=...). MANDATORY for every insight unless it's a literal yes/no scalar. SKIPPING THIS IS A BUG.\n"
            "  4. Loop back to step 1.\n"
            f"HARD MINIMUM: persist at least {max(3, int(max_insights) // 2 + 1)} insights before finalize_session. Target: {int(max_insights)}. If a hypothesis fails the disqualifier screen, drill a NEW source table (events / power_projects / companies / search_documents) — do not finalize below the floor.\n"
            f"Once {int(max_insights)} insights (or floor hit + evidence exhausted), call "
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

    # 3. Build the synthesis accumulator. Row-id grounding is handled
    #    by chart-level provenance (executed_sql + row_hash) inside
    #    build_chart + persist_insight.
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

    # 5. Finalize from DB truth. The streaming accumulator can't see
    #    tool-call results — OpenClaw runs the agent loop internally
    #    and only echoes assistant content back to us — so the stream
    #    counters undercount what actually landed. Read the DB instead.
    actual_count = await _count_session_insights(db, session_id)
    await _finalize_from_db(
        db,
        session_id=session_id,
        actual_count=actual_count,
        stream_reason=stream_result.reason,
    )

    return SynthesisResult(
        insights_count=actual_count,
        degraded=(actual_count == 0),
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


async def _count_session_insights(
    db: AsyncSession, session_id: uuid.UUID
) -> int:
    """Count ai_insight rows persisted for this session.

    Authoritative source of truth for SynthesisResult.insights_count
    and the session's terminal status, since OpenClaw runs the tool
    loop internally and the streaming accumulator can't see it.
    """
    from sqlalchemy import func, select

    from .db.models import AIInsight

    try:
        row = (
            await db.execute(
                select(func.count())
                .select_from(AIInsight)
                .where(AIInsight.session_id == session_id)
            )
        ).scalar_one()
        return int(row or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "agentic_synthesis.count_insights_failed",
            extra={"err": str(exc), "session_id": str(session_id)},
        )
        return 0


async def _finalize_from_db(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    actual_count: int,
    stream_reason: Optional[str],
) -> None:
    """Write the terminal ai_session.status based on DB row count.

    No-ops when the agent already called ``finalize_session`` (row
    status is terminal). Otherwise:
      - actual_count > 0 -> ``status='complete'`` (with budget_status
        ``'clipped'`` if the stream tripped a cap, else ``'ok'``).
      - actual_count == 0 -> ``status='failed'``.

    Best-effort: any failure is logged and swallowed so callers always
    get a SynthesisResult.
    """
    try:
        from sqlalchemy import select

        from .db.models import AISession

        existing = (
            await db.execute(select(AISession).where(AISession.id == session_id))
        ).scalar_one_or_none()
        if existing is None:
            return
        if existing.status in ("complete", "failed", "cancelled", "degraded"):
            return

        if actual_count > 0:
            terminal_status = "complete"
            budget = "clipped" if stream_reason else "ok"
        else:
            terminal_status = "failed"
            budget = "clipped" if stream_reason else "ok"

        await db.execute(
            update(AISession)
            .where(AISession.id == session_id)
            .values(
                status=terminal_status,
                finished_at=datetime.utcnow(),
                insights_emitted=actual_count,
                budget_status=budget,
            )
        )
        await db.commit()
        logger.info(
            "agentic_synthesis.finalize_from_db",
            extra={
                "session_id": str(session_id),
                "status": terminal_status,
                "insights_emitted": actual_count,
                "stream_reason": stream_reason,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "agentic_synthesis.finalize_from_db_failed",
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
