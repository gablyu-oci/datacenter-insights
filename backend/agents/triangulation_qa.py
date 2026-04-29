"""
Triangulation Q&A Agent - Phase 1C Deliverable 3.

A "tools-over-DB" QA agent that exposes 4 read-only tools to the LLM,
gathers data via async SQL queries, then streams a cited natural-language
answer to the user.

Algorithm (pragmatic 2-pass):
  1. Round 1 (reason with tools): The LLM picks which of 4 tools to call.
  2. Execute the chosen tools via dispatch_tool() against the DB.
  3. Round 2 (chat_stream, no tools): Send the gathered tool results
     inline as JSON in the prompt; stream the final cited answer.

The tools always include source URLs (edgar_url, source_url, datasheet_url,
permit_url, etc.) when present so the model can cite them.

Defensively wraps each tool in try/except - on column mismatch we return
[{"error": str(e)}] rather than raising, so the agent loop survives schema
drift.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Optional

from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import EdgarExtraction, EnergyProject, Event, Site
from llm.client import llm_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool schema (OpenAI function-calling shape) presented to the LLM.
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_sites",
            "description": (
                "Find datacenter sites by name, state, operator, or stage. "
                "Returns id, name, state, capacity_mw, stage."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Site name fragment, operator, or keyword",
                    },
                    "state": {
                        "type": "string",
                        "description": "Two-letter US state code (optional)",
                    },
                    "limit": {"type": "integer", "default": 10},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_events",
            "description": (
                "List recent dashboard events of a given type. Types include "
                "'announcement', 'permit_filed', 'satellite_change', 'edgar_filing'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_type": {"type": "string"},
                    "since_days": {"type": "integer", "default": 30},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_energy_projects",
            "description": (
                "List energy generation projects (solar, gas, nuclear) by "
                "capacity or technology."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "technology": {"type": "string"},
                    "min_mw": {"type": "number"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_edgar_extractions",
            "description": (
                "List recent SEC EDGAR 8-K extractions (power deals, "
                "hyperscaler-utility agreements). Returns buyer, seller, "
                "capacity_mw, filing_date, edgar_url, excerpt."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "since_days": {"type": "integer", "default": 90},
                    "buyer_contains": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": [],
            },
        },
    },
]


SYSTEM_PROMPT = (
    "You are a research analyst for the OCI Datacenter & Power Intelligence "
    "Platform. Answer questions using ONLY the data returned by the tools. "
    "Always cite sources with their URLs. If no tool returns relevant data, "
    "say so honestly. Be concise - 3-6 sentences plus a 'Sources:' list."
)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _tool_search_sites(
    session: AsyncSession,
    query: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    limit = min(int(limit or 10), 25)
    stmt = select(Site)
    conditions = []
    if query:
        like = f"%{query}%"
        conditions.append(
            or_(
                Site.building_name.ilike(like),
                Site.campus_name.ilike(like),
                Site.provider_name.ilike(like),
                Site.end_user_companies.ilike(like),
            )
        )
    if state:
        conditions.append(Site.state_code == state.upper())
    if conditions:
        stmt = stmt.where(and_(*conditions))
    stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    out: list[dict] = []
    for s in rows:
        out.append(
            {
                "id": s.id,
                "name": s.building_name or s.campus_name,
                "campus": s.campus_name,
                "state": s.state_code,
                "city": s.city_name,
                "capacity_mw": s.power_capacity_mw,
                "stage": s.stage,
                "provider": s.provider_name,
                "end_user": s.end_user_companies,
                "source_url": s.datasheet_url or s.permit_url or s.map_url,
            }
        )
    return out


async def _tool_list_events(
    session: AsyncSession,
    event_type: Optional[str] = None,
    since_days: int = 30,
    limit: int = 10,
) -> list[dict]:
    limit = min(int(limit or 10), 25)
    since_days = max(int(since_days or 30), 1)
    cutoff = (datetime.utcnow() - timedelta(days=since_days)).date()

    stmt = select(Event).where(Event.event_date >= cutoff)
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
    stmt = stmt.order_by(Event.event_date.desc()).limit(limit)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id": e.id,
            "aterio_dc_uid": e.aterio_dc_uid,
            "event_type": e.event_type,
            "event_date": e.event_date.isoformat() if e.event_date else None,
            "description": e.event_description,
            "source_url": e.source_url,
        }
        for e in rows
    ]


async def _tool_list_energy_projects(
    session: AsyncSession,
    technology: Optional[str] = None,
    min_mw: Optional[float] = None,
    limit: int = 10,
) -> list[dict]:
    limit = min(int(limit or 10), 25)
    stmt = select(EnergyProject)
    if technology:
        like = f"%{technology}%"
        # technology is stored within payload JSONB; fall back to name match.
        stmt = stmt.where(EnergyProject.project_name.ilike(like))
    if min_mw is not None:
        stmt = stmt.where(EnergyProject.tot_contracted_power_mw >= float(min_mw))
    stmt = stmt.order_by(EnergyProject.tot_contracted_power_mw.desc().nullslast()).limit(limit)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id": p.id,
            "project_name": p.project_name,
            "developer": p.developer_companies,
            "customer": p.customer_companies,
            "capacity_mw": p.tot_contracted_power_mw,
            "state": p.state_code,
            "btm": p.flg_btm_project,
            # Attempt to surface URLs out of the payload JSONB if present.
            "source_url": (p.payload or {}).get("source_url") if isinstance(p.payload, dict) else None,
        }
        for p in rows
    ]


async def _tool_list_edgar_extractions(
    session: AsyncSession,
    since_days: int = 90,
    buyer_contains: Optional[str] = None,
    limit: int = 5,
) -> list[dict]:
    limit = min(int(limit or 5), 25)
    since_days = max(int(since_days or 90), 1)
    cutoff = (datetime.utcnow() - timedelta(days=since_days)).date()

    stmt = select(EdgarExtraction).where(EdgarExtraction.filing_date >= cutoff)
    if buyer_contains:
        stmt = stmt.where(EdgarExtraction.buyer_raw.ilike(f"%{buyer_contains}%"))
    stmt = stmt.order_by(EdgarExtraction.filing_date.desc()).limit(limit)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id": e.id,
            "cik": e.cik,
            "form_type": e.form_type,
            "filing_date": e.filing_date.isoformat() if e.filing_date else None,
            "buyer": e.buyer_raw,
            "seller": e.seller_raw,
            "capacity_mw": e.capacity_mw,
            "energy_source": e.energy_source,
            "edgar_url": e.edgar_url,
            "excerpt": (e.excerpt or "")[:400],
        }
        for e in rows
    ]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

async def dispatch_tool(
    session: AsyncSession, name: str, args: dict
) -> list[dict]:
    """
    Run the named tool against the DB. Each tool is wrapped in try/except so
    column-mismatch errors don't abort the agent loop -- we return an
    [{"error": "..."}] list instead.
    """
    args = args or {}
    try:
        if name == "search_sites":
            return await _tool_search_sites(session, **args)
        if name == "list_events":
            return await _tool_list_events(session, **args)
        if name == "list_energy_projects":
            return await _tool_list_energy_projects(session, **args)
        if name == "list_edgar_extractions":
            return await _tool_list_edgar_extractions(session, **args)
        return [{"error": f"unknown tool: {name}"}]
    except Exception as exc:  # noqa: BLE001 - intentionally broad
        logger.warning(
            "triangulation_qa.tool_error",
            extra={"tool": name, "args": args, "error": str(exc)},
        )
        return [{"error": str(exc)}]


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def answer_question_stream(
    session: AsyncSession, question: str
) -> AsyncIterator[str]:
    """
    Two-pass tool-use + streaming answer.

    Pass 1 (non-streaming reason): the LLM proposes tool calls.
    Then we execute those tools against the DB.
    Pass 2 (streaming chat): the LLM produces a cited answer using
    only the tool results.

    Yields plain string deltas suitable for SSE framing by the route.
    """
    question = (question or "").strip()
    if not question:
        yield "Please provide a question."
        return

    # ----- Pass 1: tool selection -----
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"User question: {question}\n\n"
                "Decide which of the available tools to call (at most 3) "
                "and with what arguments. If you have enough context "
                "without tool calls, return none."
            ),
        },
    ]

    tool_results: list[dict] = []
    rounds = 0
    max_rounds = 3

    while rounds < max_rounds:
        rounds += 1
        try:
            turn = await llm_client.reason(
                prompt_version="qa_v1",
                messages=messages,
                tools=TOOLS,
            )
        except NotImplementedError as exc:
            # LlmClient not yet implemented by parallel agent.
            yield (
                "The LLM backend is not yet wired up in this build. "
                f"(LlmClient.reason: {exc}). Returning early."
            )
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("triangulation_qa.reason_failed")
            yield f"Reasoning step failed: {exc}"
            return

        tool_calls = turn.tool_calls or []
        if not tool_calls:
            # No more tools requested -- proceed to final synthesis.
            break

        # Append the assistant's tool-call turn to history (loop bookkeeping).
        messages.append(
            {
                "role": "assistant",
                "content": turn.content or "",
                "tool_calls": tool_calls,
            }
        )

        # Execute every tool call from this round.
        for call in tool_calls:
            # Tool calls follow the OpenAI shape:
            #   {"id": "...", "type": "function",
            #    "function": {"name": "...", "arguments": "{json}"}}
            call_id = call.get("id") or f"call_{rounds}"
            fn = call.get("function") or {}
            tool_name = fn.get("name") or call.get("name") or ""
            raw_args = fn.get("arguments") or call.get("arguments") or "{}"
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    args = {}
            else:
                args = raw_args or {}

            result = await dispatch_tool(session, tool_name, args)
            tool_results.append({"tool": tool_name, "args": args, "result": result})

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": tool_name,
                    "content": json.dumps(result, default=str),
                }
            )

    # ----- Pass 2: stream final answer -----
    final_prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"User question: {question}\n\n"
        f"Tool results (JSON):\n{json.dumps(tool_results, default=str)[:12000]}\n\n"
        "Write a 3-6 sentence answer grounded ONLY in the tool results above. "
        "Cite source URLs inline or in a final 'Sources:' list. "
        "If the tool results are empty or irrelevant, say so plainly."
    )

    try:
        async for chunk in llm_client.chat_stream(message=final_prompt):
            if chunk is None:
                continue
            delta = getattr(chunk, "delta", "") or ""
            if delta:
                yield delta
            if getattr(chunk, "done", False):
                break
    except NotImplementedError as exc:
        # Final-pass streaming unavailable; fall back to a plain summary so the
        # SSE consumer still gets something useful.
        yield (
            "LLM streaming not yet available in this build. "
            f"({exc}) Tool results follow as raw JSON:\n"
        )
        yield json.dumps(tool_results, default=str)[:4000]
    except Exception as exc:  # noqa: BLE001
        logger.exception("triangulation_qa.stream_failed")
        yield f"Streaming step failed: {exc}"

    # Sentinel newline so SSE consumers see a final separator before [DONE].
    yield "\n"
