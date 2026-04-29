"""
Datacenter Q&A Agent — additive companion to triangulation_qa.py.

Like triangulation_qa, this is a tools-over-DB agent: the LLM picks tool
calls, we run async SQL against the live DB, and we stream a cited
natural-language answer back. Unlike the simpler agent, this one yields
a discriminated union of events (TextChunk / ToolCall / ToolResult /
ChartSpec / Citation / Done / Error) so the new chat UI can render
running tool transcripts and inline charts.

Public entrypoint: answer_question(session, question, history) -> AsyncIterator[QAEvent].

We intentionally do NOT import or patch triangulation_qa.py — same
patterns, separate file.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Company,
    EdgarExtraction,
    EnergyProject,
    GeneratorPermit,
    Site,
    SiteCompanyAssociation,
)
from llm.client import llm_client
from schemas.qa import (
    ChartSpecEvent,
    CitationEvent,
    DoneEvent,
    ErrorEvent,
    Message,
    QAEvent,
    TextChunkEvent,
    ToolCallEvent,
    ToolResultEvent,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool schema (OpenAI function-calling shape)
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "query_sites",
            "description": (
                "Query the sites table for datacenter sites. Filter by "
                "state code, provider/operator name, stage, or minimum MW."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {"type": "string", "description": "Two-letter US state code"},
                    "provider": {"type": "string", "description": "Provider/operator name fragment"},
                    "stage": {"type": "string", "description": "Site stage e.g. Construction, Activated"},
                    "min_mw": {"type": "number", "description": "Minimum power_capacity_mw"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_companies",
            "description": "Query the canonical companies table by name fragment and optional role.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name_contains": {"type": "string"},
                    "role": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_energy_projects",
            "description": "Query the energy_projects table (solar, gas, nuclear etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {"type": "string"},
                    "energy_source": {"type": "string"},
                    "status": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_generator_permits",
            "description": "Query air-permitted backup/onsite generators by state, fuel type, or parent company.",
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {"type": "string"},
                    "fuel_type": {"type": "string"},
                    "parent": {"type": "string", "description": "Parent / permittee LLC name fragment"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_edgar_extractions",
            "description": "Query SEC EDGAR-extracted power deal records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Buyer or seller name fragment"},
                    "since": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate",
            "description": (
                "Group-and-aggregate over one of the core tables. Use for "
                "'top N', totals, and breakdowns. ALWAYS pass filter_eq when "
                "the question is scoped to a specific provider/state/etc — "
                "otherwise the chart will show unrelated global numbers. "
                "Canonical group_by/filter_eq column names: "
                "sites=[provider_name, state_code, stage, city_name, country_code]; "
                "generator_permits=[state, fuel_type]; "
                "energy_projects=[state, energy_source, status]; "
                "edgar_extractions=[ticker, period, metric_category]. "
                "On sites, when grouping by provider_name, the agent "
                "automatically excludes the 'Company Not Disclosed' sentinel."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "enum": ["sites", "generator_permits", "energy_projects", "edgar_extractions"],
                    },
                    "group_by": {"type": "array", "items": {"type": "string"}},
                    "metric": {"type": "string", "enum": ["count", "sum_mw", "avg_mw"]},
                    "filter_eq": {"type": "object"},
                    "top_n": {"type": "integer", "default": 10},
                },
                "required": ["table", "group_by", "metric"],
            },
        },
    },
]


SYSTEM_PROMPT = (
    "You are a research analyst for OCI's Datacenter & Power Intelligence "
    "Platform. You answer questions by calling tools against the live DB.\n\n"
    "═══ WORKED EXAMPLE — follow this pattern for any 'how much X has Y' "
    "question ═══\n\n"
    "Q: \"How much MW does Microsoft have in Virginia?\"\n"
    "STEP 1 (REQUIRED — get the precise total):\n"
    "  aggregate(\n"
    "    table=\"sites\",\n"
    "    group_by=[\"provider_name\"],\n"
    "    metric=\"sum_mw\",\n"
    "    filter_eq={\"provider_name\": \"Microsoft\", \"state_code\": \"VA\"}\n"
    "  )\n"
    "  → returns [{provider_name: \"Microsoft\", value: 2544.43}]\n"
    "  → that single value IS the answer.\n"
    "STEP 2 (citations only — do NOT sum these rows):\n"
    "  query_sites(state=\"VA\", provider=\"Microsoft\", limit=5)\n"
    "  → use 3-5 of these rows for citation links.\n"
    "STEP 3:\n"
    "  Write the answer: \"Microsoft has 2,544.43 MW of capacity in Virginia.\"\n"
    "  Do NOT emit a chart — single-number answer.\n\n"
    "═══ TOOL CHOICE — never violate these ═══\n\n"
    "1. 'how much' / 'total' / 'sum' / 'count' questions: ALWAYS aggregate. "
    "   NEVER query_sites then sum the rows yourself — query_sites returns at "
    "   most 100 sample rows and your in-text quote of those rows is even "
    "   more truncated. SQL SUM is the source of truth.\n\n"
    "2. Always pass filter_eq when the question scopes to a specific entity. "
    "   filter_eq={provider_name: \"Microsoft\"} restricts to Microsoft only; "
    "   without it you'll get a global aggregate that won't match the "
    "   question.\n\n"
    "3. Only emit a chart for comparison/ranking/breakdown questions ("
    "   multiple categories on the x-axis). Single-number answers — even "
    "   'how much' totals — do NOT need a chart.\n\n"
    "4. If you DO emit a chart, the underlying aggregate MUST use the same "
    "   filter_eq as the answer. A scoped question + global chart misleads "
    "   the user.\n\n"
    "═══ CANONICAL COLUMN NAMES ═══\n\n"
    "- sites: provider_name, state_code, stage, city_name, country_code\n"
    "- generator_permits: state, fuel_type\n"
    "- energy_projects: state, energy_source, status\n"
    "- edgar_extractions: ticker, period, metric_category\n\n"
    "Aliases (provider, company, state, city, …) are auto-resolved but the "
    "canonical form above is preferred. filter_eq is exact-match; "
    "query_sites's provider parameter is substring/ILIKE. Common provider_name "
    "values in the DB: 'Microsoft', 'Amazon AWS', 'Google', 'Facebook' (Meta "
    "is filed as 'Facebook'), 'Oracle'.\n\n"
    "Cite source_url when present. Never fabricate numbers — if a tool "
    "returns no rows, say so."
)


# ---------------------------------------------------------------------------
# Per-table aggregate config: maps logical table to ORM model + MW column
# ---------------------------------------------------------------------------

_AGG_TABLES: dict[str, dict[str, Any]] = {
    "sites": {"model": Site, "mw": Site.power_capacity_mw},
    "generator_permits": {"model": GeneratorPermit, "mw": GeneratorPermit.rated_mw_total},
    "energy_projects": {"model": EnergyProject, "mw": EnergyProject.tot_contracted_power_mw},
    "edgar_extractions": {"model": EdgarExtraction, "mw": EdgarExtraction.capacity_mw},
}

# Common LLM column-name slips → canonical column. Saves a tool round-trip
# when the model writes `provider` or `state` instead of the canonical form.
_COLUMN_ALIASES: dict[str, str] = {
    "provider": "provider_name",
    "company": "provider_name",
    "hyperscaler": "provider_name",
    "operator": "provider_name",
    "state": "state_code",
    "state_abbr": "state_code",
    "state_name": "state_code",
    "city": "city_name",
}


def _resolve_column(model: Any, name: str) -> tuple[Any, str]:
    """Return (column_attr or None, canonical_name) — accepts known aliases."""
    canonical = _COLUMN_ALIASES.get(name, name)
    return getattr(model, canonical, None), canonical


# ---------------------------------------------------------------------------
# Scope inference — programmatic safety net for the LLM's tool calls
# ---------------------------------------------------------------------------

# US state lookup. We accept "Virginia" or "VA" (case-insensitive) and emit "VA".
_US_STATES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}

# Canonical hyperscaler provider_name values in the DB (verified via SELECT
# DISTINCT). Maps user-spoken aliases → exact provider_name match for filter_eq.
_PROVIDER_ALIASES: dict[str, str] = {
    "microsoft": "Microsoft",
    "msft": "Microsoft",
    "amazon": "Amazon AWS",
    "aws": "Amazon AWS",
    "amazon aws": "Amazon AWS",
    "google": "Google",
    "alphabet": "Google",
    "gcp": "Google",
    "facebook": "Facebook",
    "meta": "Facebook",
    "oracle": "Oracle",
    "oci": "Oracle",
}


def _infer_scope_from_question(question: str) -> dict[str, str]:
    """
    Heuristically extract scope (state_code, provider_name) from the user's
    question. Returns a dict suitable for filter_eq on the sites table.

    Matches whole-word occurrences of state names + 2-letter codes and a
    small set of canonical hyperscaler aliases. Conservative — only kicks in
    when there's an unambiguous match.
    """
    import re

    q = (question or "").lower()
    scope: dict[str, str] = {}

    # State name (multi-word) takes precedence over 2-letter code.
    for name, code in _US_STATES.items():
        if re.search(rf"\b{re.escape(name)}\b", q):
            scope["state_code"] = code
            break
    else:
        # Fall through: try 2-letter codes — but only against the original
        # casing so we don't match common English words like "in" or "or".
        for token in re.findall(r"\b[A-Z]{2}\b", question or ""):
            if token in _US_STATES.values():
                scope["state_code"] = token
                break

    for alias, canonical in _PROVIDER_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", q):
            scope["provider_name"] = canonical
            break

    return scope


def _augment_aggregate_args(args: dict, question: str) -> dict:
    """
    If the LLM called `aggregate` without filter_eq but the user's question
    obviously scopes to a specific provider/state, inject those into
    filter_eq. Existing filter_eq keys win (we never overwrite the LLM's
    explicit choice).
    """
    if args.get("table") != "sites":
        return args
    scope = _infer_scope_from_question(question)
    if not scope:
        return args
    existing = dict(args.get("filter_eq") or {})
    # Resolve existing keys through the alias map so 'state' doesn't shadow
    # an inferred 'state_code'.
    canonical_existing = {_COLUMN_ALIASES.get(k, k) for k in existing.keys()}
    for k, v in scope.items():
        if k not in canonical_existing:
            existing[k] = v
    if existing != (args.get("filter_eq") or {}):
        new = dict(args)
        new["filter_eq"] = existing
        return new
    return args


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def _tool_query_sites(
    session: AsyncSession,
    state: Optional[str] = None,
    provider: Optional[str] = None,
    stage: Optional[str] = None,
    min_mw: Optional[float] = None,
    limit: int = 50,
) -> list[dict]:
    limit = min(int(limit or 50), 100)
    stmt = select(Site)
    conds = []
    if state:
        conds.append(Site.state_code == state.upper())
    if provider:
        conds.append(Site.provider_name.ilike(f"%{provider}%"))
    if stage:
        conds.append(Site.stage.ilike(f"%{stage}%"))
    if min_mw is not None:
        conds.append(Site.power_capacity_mw >= float(min_mw))
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.order_by(Site.power_capacity_mw.desc().nullslast()).limit(limit)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    out: list[dict] = []
    for s in rows:
        out.append(
            {
                "id": s.id,
                "aterio_dc_uid": s.aterio_dc_uid,
                "building_name": s.building_name,
                "campus_name": s.campus_name,
                "state_code": s.state_code,
                "city_name": s.city_name,
                "provider_name": s.provider_name,
                "end_user_companies": s.end_user_companies,
                "power_capacity_mw": s.power_capacity_mw,
                "stage": s.stage,
                "_citation": {
                    "table": "sites",
                    "row_id": str(s.aterio_dc_uid or s.id),
                    "source_url": s.datasheet_url or s.permit_url or s.map_url,
                    "label": s.building_name or s.campus_name or "site",
                },
            }
        )
    return out


async def _tool_query_companies(
    session: AsyncSession,
    name_contains: Optional[str] = None,
    role: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    limit = min(int(limit or 50), 100)
    stmt = select(Company)
    if name_contains:
        stmt = stmt.where(Company.canonical_name.ilike(f"%{name_contains}%"))
    if role:
        # Optional join: only surface companies that have at least one
        # association with the requested role.
        stmt = stmt.join(
            SiteCompanyAssociation,
            SiteCompanyAssociation.company_id == Company.id,
        ).where(SiteCompanyAssociation.role == role).distinct()
    stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id": c.id,
            "canonical_name": c.canonical_name,
            "ticker": c.ticker,
            "cik": c.cik,
            "public_private": c.public_private,
            "_citation": {
                "table": "companies",
                "row_id": str(c.id),
                "source_url": None,
                "label": c.canonical_name,
            },
        }
        for c in rows
    ]


async def _tool_query_energy_projects(
    session: AsyncSession,
    state: Optional[str] = None,
    energy_source: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    limit = min(int(limit or 50), 100)
    stmt = select(EnergyProject)
    conds = []
    if state:
        conds.append(EnergyProject.state_code == state.upper())
    if energy_source:
        # energy_source isn't a column; fall back to project_name fuzzy match.
        conds.append(EnergyProject.project_name.ilike(f"%{energy_source}%"))
    if status:
        # Status lives in JSONB payload; best-effort name match.
        conds.append(EnergyProject.project_name.ilike(f"%{status}%"))
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.order_by(
        EnergyProject.tot_contracted_power_mw.desc().nullslast()
    ).limit(limit)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    out: list[dict] = []
    for p in rows:
        payload = p.payload if isinstance(p.payload, dict) else {}
        out.append(
            {
                "id": p.id,
                "project_name": p.project_name,
                "developer_companies": p.developer_companies,
                "customer_companies": p.customer_companies,
                "state_code": p.state_code,
                "tot_contracted_power_mw": p.tot_contracted_power_mw,
                "flg_btm_project": p.flg_btm_project,
                "_citation": {
                    "table": "energy_projects",
                    "row_id": str(p.id),
                    "source_url": payload.get("source_url") if payload else None,
                    "label": p.project_name or "energy_project",
                },
            }
        )
    return out


async def _tool_query_generator_permits(
    session: AsyncSession,
    state: Optional[str] = None,
    fuel_type: Optional[str] = None,
    parent: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    limit = min(int(limit or 50), 100)
    stmt = select(GeneratorPermit)
    conds = []
    if state:
        conds.append(GeneratorPermit.state_code == state.upper())
    if fuel_type:
        conds.append(GeneratorPermit.fuel_type.ilike(f"%{fuel_type}%"))
    if parent:
        conds.append(GeneratorPermit.permittee_raw_name.ilike(f"%{parent}%"))
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.order_by(GeneratorPermit.rated_mw_total.desc().nullslast()).limit(limit)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    out: list[dict] = []
    for p in rows:
        raw = p.raw_payload if isinstance(p.raw_payload, dict) else {}
        out.append(
            {
                "id": p.id,
                "facility_name": p.facility_name,
                "permittee_raw_name": p.permittee_raw_name,
                "state_code": p.state_code,
                "rated_mw_total": p.rated_mw_total,
                "fuel_type": p.fuel_type,
                "permit_status": p.permit_status,
                "_citation": {
                    "table": "generator_permits",
                    "row_id": str(p.id),
                    "source_url": raw.get("source_url") if raw else None,
                    "label": p.facility_name or p.permittee_raw_name or "permit",
                },
            }
        )
    return out


async def _tool_query_edgar_extractions(
    session: AsyncSession,
    company: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    limit = min(int(limit or 50), 100)
    stmt = select(EdgarExtraction)
    conds = []
    if company:
        like = f"%{company}%"
        conds.append(or_(EdgarExtraction.buyer_raw.ilike(like), EdgarExtraction.seller_raw.ilike(like)))
    if since:
        try:
            cutoff = datetime.fromisoformat(since).date()
            conds.append(EdgarExtraction.filing_date >= cutoff)
        except ValueError:
            # Tolerate freeform "since" strings such as "2024" by ignoring them.
            pass
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.order_by(EdgarExtraction.filing_date.desc().nullslast()).limit(limit)

    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [
        {
            "id": e.id,
            "cik": e.cik,
            "form_type": e.form_type,
            "filing_date": e.filing_date.isoformat() if e.filing_date else None,
            "buyer_raw": e.buyer_raw,
            "seller_raw": e.seller_raw,
            "capacity_mw": e.capacity_mw,
            "energy_source": e.energy_source,
            "edgar_url": e.edgar_url,
            "_citation": {
                "table": "edgar_extractions",
                "row_id": str(e.id),
                "source_url": e.edgar_url,
                "label": f"{e.buyer_raw or '?'} / {e.filing_date or '?'}",
            },
        }
        for e in rows
    ]


async def _tool_aggregate(
    session: AsyncSession,
    table: str,
    group_by: list[str],
    metric: str,
    filter_eq: Optional[dict] = None,
    top_n: int = 10,
) -> list[dict]:
    """
    Group-and-aggregate. Each output row carries the group_by columns plus a
    `value` field with the metric. Limited to columns we recognise on the
    target ORM model (so the agent cannot probe unrelated columns).
    """
    cfg = _AGG_TABLES.get(table)
    if cfg is None:
        return [{"error": f"unknown table: {table}"}]
    model = cfg["model"]
    mw_col = cfg["mw"]

    # Resolve group_by columns against the model. Aliases (provider, state,
    # city, …) get rewritten to the canonical column. The output dict uses
    # the canonical name so the chart spec is self-consistent.
    group_cols = []
    canonical_group_by: list[str] = []
    for col_name in group_by or []:
        col, canonical = _resolve_column(model, col_name)
        if col is None:
            return [{"error": f"unknown column on {table}: {col_name}"}]
        group_cols.append(col)
        canonical_group_by.append(canonical)
    if not group_cols:
        return [{"error": "group_by must be non-empty"}]
    # Use the canonical names from here on for output keys.
    group_by = canonical_group_by

    if metric == "count":
        agg = func.count().label("value")
    elif metric == "sum_mw":
        agg = func.coalesce(func.sum(mw_col), 0).label("value")
    elif metric == "avg_mw":
        agg = func.avg(mw_col).label("value")
    else:
        return [{"error": f"unknown metric: {metric}"}]

    stmt = select(*group_cols, agg)

    # Optional equality filters — also goes through the alias map.
    if filter_eq:
        for k, v in filter_eq.items():
            col, _ = _resolve_column(model, k)
            if col is None:
                return [{"error": f"unknown filter column on {table}: {k}"}]
            stmt = stmt.where(col == v)

    # Suppress the Aterio "no provider known" sentinel when grouping by
    # provider on the sites table — it's a data-quality bucket, not a real
    # competitor, and dominates aggregates if left in.
    if table == "sites" and "provider_name" in group_by:
        stmt = stmt.where(
            (Site.provider_name.is_(None)) == False,  # noqa: E712 — needed by SQLAlchemy
        ).where(Site.provider_name != "Company Not Disclosed")

    stmt = stmt.group_by(*group_cols).order_by(agg.desc()).limit(int(top_n or 10))

    result = await session.execute(stmt)
    rows = result.all()
    out: list[dict] = []
    for row in rows:
        row_dict: dict[str, Any] = {}
        for i, col_name in enumerate(group_by):
            row_dict[col_name] = row[i]
        # value is the last column
        val = row[len(group_by)]
        # SQL avg returns Decimal; cast for cleaner JSON
        if val is not None:
            try:
                val = float(val)
            except (TypeError, ValueError):
                pass
        row_dict["value"] = val
        out.append(row_dict)
    return out


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

async def dispatch_tool(
    session: AsyncSession, name: str, args: dict
) -> list[dict]:
    """Run the named tool against the DB; on any error return [{"error": ...}]."""
    args = args or {}
    try:
        if name == "query_sites":
            return await _tool_query_sites(session, **args)
        if name == "query_companies":
            return await _tool_query_companies(session, **args)
        if name == "query_energy_projects":
            return await _tool_query_energy_projects(session, **args)
        if name == "query_generator_permits":
            return await _tool_query_generator_permits(session, **args)
        if name == "query_edgar_extractions":
            return await _tool_query_edgar_extractions(session, **args)
        if name == "aggregate":
            return await _tool_aggregate(session, **args)
        return [{"error": f"unknown tool: {name}"}]
    except Exception as exc:  # noqa: BLE001 - intentionally broad
        logger.warning(
            "datacenter_qa.tool_error",
            extra={"tool": name, "args": args, "error": str(exc)},
        )
        return [{"error": str(exc)}]


# ---------------------------------------------------------------------------
# Helpers for chart spec inference
# ---------------------------------------------------------------------------

_COMPARATIVE_KEYWORDS = (
    "top",
    "compare",
    "by state",
    "by provider",
    "by company",
    "most",
    "total",
    "how much",
    "ranking",
    "leaderboard",
    "share",
    "breakdown",
)


def _looks_comparative(question: str) -> bool:
    q = (question or "").lower()
    return any(k in q for k in _COMPARATIVE_KEYWORDS)


def _build_chart_spec_event(
    *, table: str, group_by: list[str], metric: str, rows: list[dict]
) -> Optional[ChartSpecEvent]:
    """
    Build a ChartSpecEvent from the most-recent aggregate result. Returns
    None if there is nothing chartable.
    """
    if not rows:
        return None
    # Reject error envelopes
    if any("error" in r for r in rows[:1]):
        return None
    if not group_by:
        return None
    x_col = group_by[0]
    series = [
        {"x": r.get(x_col), "y": r.get("value")}
        for r in rows
        if r.get(x_col) is not None and r.get("value") is not None
    ]
    if not series:
        return None

    # Pie only if it's a small categorical breakdown of count.
    if len(group_by) == 1 and metric == "count" and len(series) <= 8:
        chart_type = "pie"
    elif len(group_by) == 1:
        chart_type = "bar"
    else:
        chart_type = "table"

    title_metric = {"count": "count", "sum_mw": "total MW", "avg_mw": "average MW"}.get(metric, metric)
    title = f"{title_metric.title()} by {', '.join(group_by)} ({table})"
    return ChartSpecEvent(
        chart_type=chart_type,
        x=x_col,
        y="value",
        series=series,
        title=title,
        source_table=table,
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def answer_question(
    session: AsyncSession,
    question: str,
    history: list[Message] | None = None,
) -> AsyncIterator[QAEvent]:
    """
    Multi-pass tool-using QA, yielding a discriminated union of events.

    Pass 1 (up to 3 rounds): llm_client.reason picks tool calls; we run
    them and yield ToolCall, ToolResult, and Citation events.
    Pass 2: llm_client.chat_stream produces the final cited answer; we
    yield TextChunk events. We may emit a ChartSpec event between passes
    when the question is comparative/numeric and an aggregate result is
    available.
    """
    question = (question or "").strip()
    if not question:
        yield ErrorEvent(message="Please provide a question.")
        yield DoneEvent()
        return

    # Build the message stack. Include short history so the LLM keeps context.
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        for m in history[-8:]:  # cap context size
            try:
                messages.append({"role": m.role, "content": m.content})
            except AttributeError:
                # tolerate raw dict history
                if isinstance(m, dict) and m.get("role") and m.get("content"):
                    messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": question})

    tool_results: list[dict] = []
    last_aggregate_meta: Optional[dict] = None
    seen_citations: set[tuple] = set()

    rounds = 0
    max_rounds = 3
    while rounds < max_rounds:
        rounds += 1
        try:
            turn = await llm_client.reason(
                prompt_version="datacenter_qa_v1",
                messages=messages,
                tools=TOOLS,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("datacenter_qa.reason_failed")
            yield ErrorEvent(message=f"Reasoning step failed: {exc}")
            yield DoneEvent()
            return

        tool_calls = turn.tool_calls or []
        if not tool_calls:
            break

        # Append the assistant's tool-call turn to history (loop bookkeeping).
        messages.append(
            {
                "role": "assistant",
                "content": turn.content or "",
                "tool_calls": tool_calls,
            }
        )

        for call in tool_calls:
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

            # Safety net: if the LLM forgot filter_eq on a scoped aggregate
            # call, inject the scope inferred from the question. The LLM's
            # explicit filters always win over inferred ones.
            if tool_name == "aggregate":
                args = _augment_aggregate_args(args, question)

            # Emit the tool-call event for live UI transcript.
            yield ToolCallEvent(tool_name=tool_name, args=args)

            result = await dispatch_tool(session, tool_name, args)
            tool_results.append({"tool": tool_name, "args": args, "result": result})

            # Track aggregate metadata for later chart synthesis.
            if tool_name == "aggregate" and result and "error" not in result[0]:
                last_aggregate_meta = {
                    "table": args.get("table"),
                    "group_by": args.get("group_by") or [],
                    "metric": args.get("metric"),
                    "rows": result,
                }

            # Build a short summary string for the UI.
            row_count = len(result)
            if row_count == 1 and "error" in result[0]:
                summary = f"error: {result[0]['error'][:160]}"
            elif row_count == 0:
                summary = "no rows"
            else:
                summary = f"{row_count} row(s)"

            yield ToolResultEvent(
                tool_name=tool_name, summary=summary, row_count=row_count
            )

            # Emit up to 3 unique citations from this result.
            cites_emitted = 0
            for row in result:
                if cites_emitted >= 3:
                    break
                cite = row.get("_citation") if isinstance(row, dict) else None
                if not cite:
                    continue
                key = (cite.get("table"), cite.get("row_id"))
                if key in seen_citations:
                    continue
                seen_citations.add(key)
                cites_emitted += 1
                yield CitationEvent(
                    table=cite.get("table") or "",
                    row_id=cite.get("row_id"),
                    source_url=cite.get("source_url"),
                    label=cite.get("label") or "",
                )

            # Append a tool message back to the LLM. Strip _citation noise to
            # save tokens — the LLM doesn't need it for synthesis.
            stripped = []
            for row in result:
                if isinstance(row, dict):
                    stripped.append({k: v for k, v in row.items() if k != "_citation"})
                else:
                    stripped.append(row)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": tool_name,
                    "content": json.dumps(stripped, default=str)[:8000],
                }
            )

    # ----- Optional chart spec ------------------------------------------------
    used_aggregate = any(tr["tool"] == "aggregate" for tr in tool_results)
    if (used_aggregate or _looks_comparative(question)) and last_aggregate_meta is not None:
        chart_event = _build_chart_spec_event(
            table=last_aggregate_meta["table"],
            group_by=last_aggregate_meta["group_by"],
            metric=last_aggregate_meta["metric"],
            rows=last_aggregate_meta["rows"],
        )
        if chart_event is not None:
            yield chart_event

    # ----- Pass 2: stream natural-language synthesis --------------------------
    # Build a compact synthesis prompt that includes the gathered tool results.
    synthesis_prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"User question: {question}\n\n"
        f"Tool results (JSON, truncated):\n"
        f"{json.dumps(tool_results, default=str)[:10000]}\n\n"
        "Write a concise 3-6 sentence answer grounded ONLY in the tool "
        "results above. Cite source URLs inline or in a final 'Sources:' "
        "list. If the tool results are empty or irrelevant, say so."
    )

    try:
        any_text = False
        async for chunk in llm_client.chat_stream(message=synthesis_prompt):
            if chunk is None:
                continue
            delta = getattr(chunk, "delta", "") or ""
            if delta:
                any_text = True
                yield TextChunkEvent(content=delta)
            if getattr(chunk, "done", False):
                break
        if not any_text:
            # Streamer returned nothing useful — degrade gracefully.
            yield TextChunkEvent(
                content=(
                    "(No streamed answer available; see tool results.)"
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("datacenter_qa.stream_failed")
        yield ErrorEvent(message=f"Streaming step failed: {exc}")

    yield DoneEvent()
