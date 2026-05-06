"""
Weekly Brief Agent -- Phase 4 (PRD/ARCH 14 §8).

Builds a 7-day context window from the database and drives an OpenClaw
agentic turn whose `persist_brief` MCP tool persists the resulting
``brief_runs`` row. Replaces the pre-Phase-4 single-shot
``llm_client.reason()`` call with the same shared ``_drive_openclaw_stream``
helper the synthesis lane uses (`agentic_synthesis.run_agentic_synthesis`).

Public entry point:
    async def generate_weekly_brief(session) -> BriefRun

Wire flow (mirrors `agentic_synthesis.run_agentic_synthesis`):

  1. Build the 7-day context (UNCHANGED helper `_build_context`).
  2. Mint a session UUID and an OpenClaw sessionKey
     ``weekly-brief-YYYYWW`` (ISO year + week, zero-padded).
  3. Register brief metadata (period_start, period_end, model,
     prompt_version) so ``persist_brief`` can recover it server-side
     without trusting the agent.
  4. Build messages = [system from `prompts/brief_rules.md`,
     user JSON pack with the context + iso year/week + session_id].
  5. Drive `_drive_openclaw_stream` with the synthesis-lane translator
     (`SynthesisChunkAccumulator` + `translate_synthesis_chunk`) which
     already understands `persist_brief` + `finalize_session` tool
     calls (they share the synthesis tool palette).
  6. After the stream returns, look up the BriefRun row keyed on
     (period_start, period_end). If present, return it.
  7. On TimeoutError / SynthesisRunError / unexpected exception, write
     a fallback BriefRun row so the UI card never goes stale (preserves
     the AC7 invariant the legacy code held), and return that row.

Caps (per ARCH §8.2 — briefs are smaller than synthesis):
  cap_turns=12, cap_tool_calls=20, cap_wall_seconds=300

Outer wall-clock safety belt: ``asyncio.wait_for(timeout=320)``.

The Sunday-23:00-UTC APScheduler `JOB_CONFIG["weekly_brief"]` schedule
is unchanged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from agents.insights.prompts import load_prompt
from agents.insights.session_tools import (
    clear_session_brief_meta,
    register_session_brief_meta,
)
from db.models import (
    BriefRun,
    EdgarExtraction,
    EnergyProject,
    Event,
    Site,
)
from openclaw.forwarder import StreamResult, _drive_openclaw_stream
from openclaw.sse_translator import (
    SynthesisChunkAccumulator,
    translate_synthesis_chunk,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Caps per ARCH §8.2 — briefs are smaller than synthesis.
_BRIEF_CAP_TURNS = 12
_BRIEF_CAP_TOOL_CALLS = 20
_BRIEF_CAP_WALL_SECONDS = 300.0
# Outer asyncio safety belt: cap_wall_seconds + small headroom for the
# SSE close handshake. Mirrors the synthesis driver pattern.
_BRIEF_OUTER_WALL_TIMEOUT_S = 320.0

# Default model + prompt version recorded on the BriefRun row. The
# OpenClaw gateway is the source of truth for the actual model the
# turn ran against; we record a stable identifier so historical
# queries against `brief_runs.model` keep working.
_BRIEF_MODEL_TAG = "openclaw/default"
_BRIEF_PROMPT_VERSION = "brief_rules@v1"


# ---------------------------------------------------------------------------
# Context builder (UNCHANGED from Phase 1C — ARCH §8.1 says keep)
# ---------------------------------------------------------------------------


async def _safe_query(session, label: str, stmt) -> list:
    """Run a SELECT defensively; on any error log + return []."""
    try:
        result = await session.execute(stmt)
        return list(result.scalars().all())
    except Exception as exc:
        logger.warning(
            "weekly_brief.query_failed",
            extra={"label": label, "error": str(exc)},
        )
        return []


async def _build_context(session, period_start: date) -> dict[str, Any]:
    """Pull last-7-days rows from each pillar table.

    Each per-table block is independently try/except'd via _safe_query so a
    schema drift in one table does not poison the brief.
    """
    period_start_dt = datetime.combine(period_start, datetime.min.time())

    sites_raw = await _safe_query(
        session,
        "sites",
        select(Site).where(Site.created_at >= period_start_dt).limit(50),
    )
    sites = [
        {
            "id": s.id,
            "name": s.building_name or s.campus_name,
            "state": s.state_code,
            "capacity_mw": s.power_capacity_mw,
            "stage": s.stage,
        }
        for s in sites_raw
    ]

    events_raw = await _safe_query(
        session,
        "events",
        select(Event).where(Event.event_date >= period_start).limit(50),
    )
    events = [
        {
            "event_type": e.event_type,
            "headline": (e.event_description or "")[:200],
            "event_date": e.event_date.isoformat() if e.event_date else None,
            "source_url": e.source_url,
        }
        for e in events_raw
    ]

    projects_raw = await _safe_query(
        session,
        "energy_projects",
        select(EnergyProject)
        .where(EnergyProject.created_at >= period_start_dt)
        .limit(50),
    )
    projects = [
        {
            "project_name": p.project_name,
            "tot_contracted_power_mw": p.tot_contracted_power_mw,
            "state": p.state_code,
        }
        for p in projects_raw
    ]

    edgar_raw = await _safe_query(
        session,
        "edgar_extractions",
        select(EdgarExtraction)
        .where(EdgarExtraction.created_at >= period_start_dt)
        .limit(50),
    )
    edgar = [
        {
            "buyer": x.buyer_raw,
            "seller": x.seller_raw,
            "capacity_mw": x.capacity_mw,
            "filing_date": x.filing_date.isoformat() if x.filing_date else None,
            "edgar_url": x.edgar_url,
            "excerpt": (x.excerpt or "")[:300],
        }
        for x in edgar_raw
    ]

    return {
        "sites": sites,
        "events": events,
        "energy_projects": projects,
        "edgar_extractions": edgar,
        "counts": {
            "sites": len(sites),
            "events": len(events),
            "energy_projects": len(projects),
            "edgar_extractions": len(edgar),
        },
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def generate_weekly_brief(session) -> BriefRun:
    """Generate a weekly briefing via OpenClaw + persist it.

    Returns the BriefRun row written by the agent's ``persist_brief``
    MCP tool. On total failure (timeout, gateway down, agent never
    called persist_brief), writes a best-effort fallback BriefRun row
    so the UI card never goes stale and returns that row.
    """
    period_end = datetime.utcnow().date()
    period_start = period_end - timedelta(days=7)
    iso_year, iso_week, _ = period_end.isocalendar()
    session_id = uuid.uuid4()
    session_key = f"weekly-brief-{iso_year:04d}{iso_week:02d}"

    # 1. Build the 7-day context.
    context = await _build_context(session, period_start)

    # 2. Register brief metadata so persist_brief can recover it
    #    server-side without trusting the agent.
    register_session_brief_meta(
        session_id,
        period_start=period_start,
        period_end=period_end,
        model=_BRIEF_MODEL_TAG,
        prompt_version=_BRIEF_PROMPT_VERSION,
    )

    # 3. Build messages.
    try:
        brief_rules = load_prompt("brief_rules")
    except FileNotFoundError:
        # Defensive — the file ships with the repo. Fall back to an
        # empty system prompt so the agent at least attempts the run.
        logger.warning("weekly_brief.brief_rules_missing")
        brief_rules = ""

    user_pack = {
        "iso_year": iso_year,
        "iso_week": iso_week,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "session_id": str(session_id),
        "context": context,
        "instructions": (
            "Use query_database / web_search to drill in if needed, then "
            f"call persist_brief(session_id='{session_id}', sections={{"
            "'thesis':..., 'movers':..., 'outlook':...}}, citations=[...]) "
            f"exactly once. Then call finalize_session(session_id='{session_id}', "
            "status='complete', token_estimate=...). Caps: 12 turns, 20 "
            "tool calls, 300s wall."
        ),
    }

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": brief_rules},
        {
            "role": "user",
            "content": json.dumps(user_pack, default=str, separators=(",", ":")),
        },
    ]

    # 4. Build the synthesis-lane accumulator (the synthesis translator
    #    already handles persist_brief + finalize_session — see ARCH §8.2:
    #    brief shares the synthesis tool palette and SSE event taxonomy).
    acc = SynthesisChunkAccumulator(
        session_id=str(session_id),
        thread_id=str(session_id),
        message_id=f"msg_{uuid.uuid4().hex[:12]}",
        insight_id="",
    )

    async def _log_event(evt: Any) -> None:
        # No SSE consumer for the cron brief flow; log type + a tag so
        # ops can confirm the agent took the expected steps.
        try:
            tag = type(evt).__name__
        except Exception:  # noqa: BLE001
            tag = "?"
        logger.info("weekly_brief.sse type=%s", tag)

    started = time.monotonic()
    stream_result: StreamResult
    try:
        stream_result = await asyncio.wait_for(
            _drive_openclaw_stream(
                session_key=session_key,
                messages=messages,
                on_translated_event=_log_event,
                accumulator=acc,
                translator=translate_synthesis_chunk,
                cap_turns=_BRIEF_CAP_TURNS,
                cap_tool_calls=_BRIEF_CAP_TOOL_CALLS,
                cap_wall_seconds=_BRIEF_CAP_WALL_SECONDS,
            ),
            timeout=_BRIEF_OUTER_WALL_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "weekly_brief.outer_wall_timeout",
            extra={"session_id": str(session_id)},
        )
        stream_result = StreamResult(
            degraded=True, reason="wall_clock", total_chunks=0
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "weekly_brief.unhandled",
            extra={"session_id": str(session_id), "err": str(exc)},
        )
        stream_result = StreamResult(
            degraded=True,
            reason=f"exception:{type(exc).__name__}",
            total_chunks=0,
        )
    finally:
        clear_session_brief_meta(session_id)

    elapsed_ms = int((time.monotonic() - started) * 1000)

    # 5. Look up the BriefRun row the agent's persist_brief MCP tool
    #    wrote. Fall back to a synthetic row if the agent never made
    #    that call (degraded path / gateway unreachable).
    row = await _lookup_latest_brief_row(session, period_start, period_end)
    if row is not None:
        # Stamp latency_ms post-hoc — the MCP tool body leaves it NULL
        # because it has no clock context.
        if row.latency_ms is None:
            row.latency_ms = elapsed_ms
            try:
                await session.commit()
                await session.refresh(row)
            except Exception:  # noqa: BLE001 — defensive; latency is best-effort
                logger.warning(
                    "weekly_brief.latency_stamp_failed",
                    extra={"id": row.id},
                )
        logger.info(
            "weekly_brief.generated",
            extra={
                "id": row.id,
                "session_id": str(session_id),
                "session_key": session_key,
                "bullet_count": row.bullet_count,
                "latency_ms": row.latency_ms,
                "degraded": stream_result.degraded,
                "reason": stream_result.reason,
                "total_chunks": stream_result.total_chunks,
            },
        )
        return row

    # 6. Fallback path — write a synthetic BriefRun so the UI card never
    #    goes stale. This preserves the AC7 invariant the legacy code
    #    held and keeps `tests/test_weekly_brief.py` happy.
    fallback_md = _build_fallback_markdown(
        context=context,
        period_start=period_start,
        period_end=period_end,
        reason=stream_result.reason or "unknown",
    )
    fallback = BriefRun(
        period_start=period_start,
        period_end=period_end,
        markdown=fallback_md,
        model=_BRIEF_MODEL_TAG,
        prompt_version=_BRIEF_PROMPT_VERSION + "+fallback",
        bullet_count=fallback_md.count("\n- ") + fallback_md.count("\n* "),
        tokens_in=0,
        tokens_out=0,
        latency_ms=elapsed_ms,
    )
    session.add(fallback)
    try:
        await session.commit()
        await session.refresh(fallback)
    except Exception:  # noqa: BLE001 — last-resort defensive; tests use a fake session
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
    logger.warning(
        "weekly_brief.fallback_persisted",
        extra={
            "id": fallback.id,
            "session_id": str(session_id),
            "session_key": session_key,
            "reason": stream_result.reason,
            "total_chunks": stream_result.total_chunks,
            "elapsed_ms": elapsed_ms,
        },
    )
    return fallback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _lookup_latest_brief_row(
    session, period_start: date, period_end: date
) -> BriefRun | None:
    """Return the most-recently-generated BriefRun row for the given
    (period_start, period_end) tuple, or None if no row exists.

    Wrapped in try/except so the test suite's FakeSession (which only
    stubs ``execute`` to return empty rows) drives us into the
    fallback path cleanly rather than raising.
    """
    try:
        result = await session.execute(
            select(BriefRun)
            .where(
                BriefRun.period_start == period_start,
                BriefRun.period_end == period_end,
            )
            .order_by(BriefRun.generated_at.desc())
            .limit(1)
        )
        return result.scalars().first()
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.warning(
            "weekly_brief.lookup_failed",
            extra={"err": str(exc)},
        )
        return None


def _build_fallback_markdown(
    *,
    context: dict[str, Any],
    period_start: date,
    period_end: date,
    reason: str,
) -> str:
    """Render a deterministic markdown brief from the raw context dict.

    Used when the OpenClaw round-trip fails or the agent never calls
    persist_brief. Keeps the UI card from going blank and preserves a
    minimal audit trail.
    """
    counts = context.get("counts", {}) if isinstance(context, dict) else {}
    sites_n = int(counts.get("sites", 0) or 0)
    events_n = int(counts.get("events", 0) or 0)
    projects_n = int(counts.get("energy_projects", 0) or 0)
    edgar_n = int(counts.get("edgar_extractions", 0) or 0)

    lines: list[str] = [
        f"## Top developments ({period_start.isoformat()} – {period_end.isoformat()})",
        "",
        f"- New sites this week: {sites_n}",
        f"- Events: {events_n}",
        f"- Energy projects: {projects_n}",
        f"- EDGAR extractions: {edgar_n}",
        "",
        "_Brief was generated via the fallback path because the agentic "
        f"flow ended in a degraded state (reason={reason!s}). Re-run on "
        "the next Sunday cron once the gateway is healthy._",
    ]
    return "\n".join(lines)


__all__ = ["generate_weekly_brief", "_build_context"]
