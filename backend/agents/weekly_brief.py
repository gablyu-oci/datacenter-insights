"""
Weekly Brief Agent -- Phase 1C.

Builds a 7-day context window from the database, calls the reasoning LLM
to summarise it as markdown bullets, and persists a row in brief_runs.

Public entry point:
    async def generate_weekly_brief(session) -> BriefRun
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from db.models import (
    BriefRun,
    EdgarExtraction,
    EnergyProject,
    Event,
    Site,
)
from llm.client import MODELS, llm_client

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are a research analyst for the OCI Datacenter & Power Intelligence "
    "Platform. Produce a 5-10 bullet markdown weekly briefing summarising what "
    "changed this week across sites, events, energy projects, and SEC EDGAR "
    "filings. Cite source URLs where available. Group bullets under "
    "'## Top developments'. If a category is empty, say so briefly. "
    "Keep it tight -- under 400 words."
)


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


async def generate_weekly_brief(session) -> BriefRun:
    """Generate a weekly briefing and persist it. Returns the BriefRun row."""
    period_end = datetime.utcnow().date()
    period_start = period_end - timedelta(days=7)

    context = await _build_context(session, period_start)
    user_message = (
        "## Context (JSON)\n\n"
        + json.dumps(context, default=str, indent=2)
    )

    model = MODELS["reasoning"]
    prompt_version = "weekly_brief_v1"

    turn = await llm_client.reason(
        model=model,
        prompt_version=prompt_version,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )

    markdown = turn.content or "_(no content returned by LLM)_"
    bullet_count = markdown.count("\n- ") + markdown.count("\n* ")
    tokens_in = (turn.tokens or {}).get("prompt", 0) or 0
    tokens_out = (turn.tokens or {}).get("completion", 0) or 0

    row = BriefRun(
        period_start=period_start,
        period_end=period_end,
        markdown=markdown,
        model=model,
        prompt_version=prompt_version,
        bullet_count=bullet_count,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=turn.latency_ms,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    logger.info(
        "weekly_brief.generated",
        extra={
            "id": row.id,
            "bullet_count": bullet_count,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": turn.latency_ms,
        },
    )
    return row
