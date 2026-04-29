"""
Datacenter Q&A Agent — schema-aware tools-over-DB agent.

Two tools are exposed to the LLM:
  - `query`        unified, schema-introspecting data tool with WHERE / GROUP BY /
                   metric / ORDER BY / LIMIT support.
  - `propose_chart` render-proposal tool (no DB call); the dispatcher captures
                   the most recent proposal and emits a ChartSpecEvent at the
                   end of the tool loop.

The schema doc is auto-built from a per-table whitelist + the SQLModel column
introspection so the LLM sees the exact column names + types it can ask for.

Public entrypoint: answer_question(session, question, history) -> AsyncIterator[QAEvent].
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, AsyncIterator, Iterable, Optional

from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Company,
    EdgarExtraction,
    EnergyProject,
    Event,
    GeneratorPermit,
    Site,
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
# Schema whitelist — table -> {column: description}
# Hand-written 1-line descriptions; columns are verified against the ORM model
# at module import to defend against typos / drift.
# ---------------------------------------------------------------------------

_TABLE_MODELS: dict[str, Any] = {
    "sites": Site,
    "generator_permits": GeneratorPermit,
    "energy_projects": EnergyProject,
    "edgar_extractions": EdgarExtraction,
    "companies": Company,
    "events": Event,
}


_SCHEMA_WHITELIST: dict[str, dict[str, str]] = {
    "sites": {
        "aterio_dc_uid": "Stable Aterio site UID (preferred external id).",
        "building_name": "Building name within a campus.",
        "campus_name": "Campus / cluster name (groups buildings).",
        "stage": "Lifecycle stage: Announcement, Construction, Activated, Cancelled, Withdrawn.",
        "pct_construction": "Percent complete (0-100).",
        "provider_name": "Datacenter operator (Microsoft, Amazon AWS, Google, Facebook, Oracle, ...).",
        "provider_ticker": "Operator stock ticker.",
        "provider_public_private": "Public / Private classification of operator.",
        "end_user_companies": "Comma-separated end-user / customer names.",
        "full_address": "Free-text street address.",
        "county_name": "US county name.",
        "city_name": "City name.",
        "state_code": "Two-letter US state code (e.g. VA, TX).",
        "country_code": "ISO country code.",
        "latitude": "Decimal latitude.",
        "longitude": "Decimal longitude.",
        "site_acreage": "Site footprint in acres.",
        "tot_facility_space_sqft": "Total facility floor area (sqft).",
        "tot_datacenter_space_sqft": "Datacenter white-space (sqft).",
        "prov_pub_tot_power_capacity_mw": "Operator-published total MW capacity.",
        "aterio_est_mw": "Aterio-estimated MW.",
        "power_capacity_mw": "Selected MW capacity (canonical MW field).",
        "tot_project_cost": "Total project cost (USD).",
        "yearly_pue": "Reported yearly Power Usage Effectiveness.",
        "tot_num_generators": "Total backup generators on site.",
        "announced_date": "Announcement date (text, may be partial).",
        "construction_start_date": "Construction start date (text).",
        "construction_finished_date": "Construction finish date (text).",
        "activation_date": "Site activation date (text).",
        "utility_name": "Serving electric utility.",
        "bal_auth_abbr": "Balancing authority abbreviation (PJM, ERCOT, ...).",
        "datasheet_url": "Aterio datasheet URL (citation source).",
        "permit_url": "Permit document URL (citation source).",
        "project_execution_likelihood": "High / Medium / Low.",
        "is_ai_facility": "Boolean: AI-purpose facility flag.",
        "flg_btm_onsite_power_generation": "Boolean: behind-the-meter onsite gen flag.",
    },
    "generator_permits": {
        "source": "Source registry (epa_echo, tceq, ...).",
        "source_permit_id": "Source-side permit identifier.",
        "facility_name": "Facility name on the permit.",
        "permittee_raw_name": "Permittee LLC raw string.",
        "resolved_company_id": "FK to companies.id when resolved.",
        "site_id": "FK to sites.id when matched.",
        "state_code": "Two-letter US state code.",
        "county_fips": "5-digit county FIPS.",
        "latitude": "Decimal latitude.",
        "longitude": "Decimal longitude.",
        "rated_mw_total": "Total rated generator capacity (MW).",
        "num_units": "Number of generator units.",
        "fuel_type": "Diesel, NG, Dual-Fuel, etc.",
        "permit_status": "Permit status string.",
        "issued_date": "Permit issued date.",
        "expiry_date": "Permit expiry date.",
        "frs_id": "EPA FRS facility id.",
        "naics_code": "NAICS industry code.",
        "confidence": "Resolver confidence (0-1).",
    },
    "energy_projects": {
        "id": "Primary key.",
        "project_name": "Energy project name.",
        "flg_btm_project": "Boolean: behind-the-meter project flag.",
        "developer_companies": "Comma-separated developer company names.",
        "developer_ticker": "Developer stock ticker.",
        "eia_entity_names": "EIA-resolved entity names.",
        "customer_companies": "Comma-separated offtaker / customer names.",
        "tot_contracted_power_mw": "Total contracted power (MW).",
        "tot_project_cost": "Total project cost (USD).",
        "project_footprint_acreage": "Footprint in acres.",
        "state_code": "Two-letter US state code.",
        "latitude": "Decimal latitude.",
        "longitude": "Decimal longitude.",
    },
    "edgar_extractions": {
        "id": "Primary key.",
        "cik": "SEC CIK of filer.",
        "accession_number": "SEC accession number.",
        "form_type": "Form type (10-K, 8-K, ...).",
        "filing_date": "Filing date.",
        "item_codes": "Form item codes hit.",
        "edgar_url": "Direct EDGAR URL (citation source).",
        "capacity_mw": "Extracted capacity (MW).",
        "energy_source": "solar / gas / nuclear / wind / ...",
        "buyer_raw": "Raw buyer string from filing.",
        "seller_raw": "Raw seller string from filing.",
        "parser_version": "Parser version label.",
        "confidence": "Extractor confidence (0-1).",
    },
    "companies": {
        "id": "Primary key.",
        "canonical_name": "Canonical company name.",
        "short_name": "Short / display name.",
        "ticker": "Stock ticker.",
        "cik": "SEC CIK.",
        "parent_company_id": "FK to companies.id of parent.",
        "public_private": "Public / Private classification.",
    },
    "events": {
        "id": "Primary key.",
        "aterio_dc_uid": "Aterio site UID this event refers to.",
        "event_type": "announcement / permit_filed / construction_start / activation / expansion / cancellation.",
        "event_date": "Event date.",
        "event_description": "Free-text description.",
        "source_url": "Source URL (citation).",
    },
}


def _column_python_type(model: Any, name: str) -> str:
    """Best-effort Python type label for an ORM column."""
    col = getattr(model, name, None)
    if col is None:
        return "unknown"
    try:
        sa_col = col.property.columns[0]  # type: ignore[attr-defined]
        py_type = getattr(sa_col.type, "python_type", None)
        if py_type is not None:
            return py_type.__name__
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def _table_columns(table: str) -> dict[str, str]:
    """Return {column: type_label} for the table's whitelisted columns,
    skipping any columns that are not actually defined on the ORM model."""
    model = _TABLE_MODELS.get(table)
    if model is None:
        return {}
    out: dict[str, str] = {}
    for col_name in _SCHEMA_WHITELIST.get(table, {}).keys():
        if getattr(model, col_name, None) is None:
            # Defensive: hand-typed whitelist drift.
            continue
        out[col_name] = _column_python_type(model, col_name)
    return out


_SCHEMA_DOC_CACHE: Optional[str] = None


def _describe_schema_for_llm() -> str:
    """Build a compact schema doc for the system prompt.

    Walks the per-table whitelist, verifies each column on the ORM model, and
    emits `column (type) — description` lines under each table heading.
    Cached at module level so we only build it once.
    """
    global _SCHEMA_DOC_CACHE
    if _SCHEMA_DOC_CACHE is not None:
        return _SCHEMA_DOC_CACHE

    lines: list[str] = []
    for table, model in _TABLE_MODELS.items():
        whitelist = _SCHEMA_WHITELIST.get(table) or {}
        if not whitelist:
            continue
        lines.append(f"### {table}")
        for col_name, desc in whitelist.items():
            if getattr(model, col_name, None) is None:
                continue
            tlabel = _column_python_type(model, col_name)
            lines.append(f"- {col_name} ({tlabel}) — {desc}")
        lines.append("")

    text = "\n".join(lines).strip()
    # Cap at ~3KB for prompt budget.
    if len(text) > 3000:
        text = text[:2997] + "..."
    _SCHEMA_DOC_CACHE = text
    return text


# ---------------------------------------------------------------------------
# Tool schema (OpenAI function-calling shape)
# ---------------------------------------------------------------------------

_ALLOWED_OPS = ["=", "!=", ">", ">=", "<", "<=", "in", "ilike", "is_null", "is_not_null", "between"]

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "query",
            "description": (
                "Unified data tool. Filter (where), select columns, group_by + "
                "metric for aggregation, order_by, limit. Always returns "
                "{total_count, returned, rows, truncated}. Use the schema in "
                "the system prompt to pick valid columns. Operators: " +
                ", ".join(_ALLOWED_OPS) + "."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "enum": list(_TABLE_MODELS.keys()),
                    },
                    "where": {
                        "type": "array",
                        "description": "List of {column, op, value} clauses. AND-combined.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "op": {"type": "string", "enum": _ALLOWED_OPS},
                                "value": {},
                            },
                        },
                    },
                    "select": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Columns to return (raw mode only). Default: all whitelisted columns.",
                    },
                    "group_by": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "If set, switches to aggregation mode.",
                    },
                    "metric": {
                        "type": "string",
                        "description": "Aggregation: count | sum:<col> | avg:<col> | min:<col> | max:<col> | count_distinct:<col>.",
                    },
                    "order_by": {
                        "type": "array",
                        "description": "List of {column, direction} (direction = asc|desc).",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "direction": {"type": "string", "enum": ["asc", "desc"]},
                            },
                        },
                    },
                    "limit": {"type": "integer", "default": 100},
                },
                "required": ["table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_chart",
            "description": (
                "Propose a chart to render. No DB call. The agent captures the "
                "LATEST proposal and emits a ChartSpecEvent at end of round. "
                "Use chart_type='none' to suppress. For pies, x is the "
                "category column and y is the metric column (usually 'value')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chart_type": {
                        "type": "string",
                        "enum": ["bar", "pie", "line", "scatter", "table", "none"],
                    },
                    "title": {"type": "string"},
                    "x": {"type": "string"},
                    "y": {},
                    "series": {"type": "array", "items": {"type": "object"}},
                    "breakdown_by": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
                "required": ["chart_type", "title"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# System prompt with schema doc + worked examples
# ---------------------------------------------------------------------------

def _build_system_prompt() -> str:
    return (
        "You are a research analyst for OCI's Datacenter & Power Intelligence "
        "Platform. You answer questions by calling tools against the live DB.\n\n"
        "Use `query` for ALL data access. The schema below enumerates every "
        "queryable column with type + 1-line description. Pass column names "
        "exactly as listed.\n\n"
        "After data is gathered you MAY call `propose_chart` once to render a "
        "chart. For pure single-fact answers you may skip propose_chart, OR "
        "run a 2nd `query` for a meaningful breakdown then call propose_chart.\n\n"
        "Never fabricate. Cite source_url (datasheet_url / permit_url / "
        "edgar_url / events.source_url) inline when present.\n\n"
        "═══ SCHEMA ═══\n\n"
        f"{_describe_schema_for_llm()}\n\n"
        "═══ WORKED EXAMPLES ═══\n\n"
        "Q: \"How much MW does Microsoft have in Virginia?\"\n"
        "  1) query(table=\"sites\",\n"
        "         where=[{column:\"provider_name\", op:\"=\", value:\"Microsoft\"},\n"
        "                {column:\"state_code\", op:\"=\", value:\"VA\"}],\n"
        "         group_by=[\"provider_name\"], metric=\"sum:power_capacity_mw\")\n"
        "     → returns rows=[{provider_name:\"Microsoft\", value:2544.43}], answer = 2544.43 MW.\n"
        "  2) query(table=\"sites\",\n"
        "         where=[{column:\"provider_name\", op:\"=\", value:\"Microsoft\"},\n"
        "                {column:\"state_code\", op:\"=\", value:\"VA\"}],\n"
        "         group_by=[\"city_name\"], metric=\"sum:power_capacity_mw\",\n"
        "         order_by=[{column:\"value\", direction:\"desc\"}], limit=8)\n"
        "  3) propose_chart(chart_type=\"pie\", title=\"Microsoft VA capacity by city\",\n"
        "         x=\"city_name\", y=\"value\", breakdown_by=\"city_name\",\n"
        "         reasoning=\"small categorical breakdown of one operator's footprint\")\n\n"
        "Q: \"Top 5 hyperscalers by MW.\"\n"
        "  1) query(table=\"sites\", group_by=[\"provider_name\"],\n"
        "         metric=\"sum:power_capacity_mw\",\n"
        "         order_by=[{column:\"value\", direction:\"desc\"}], limit=5)\n"
        "  2) propose_chart(chart_type=\"bar\", title=\"Top 5 operators by total MW\",\n"
        "         x=\"provider_name\", y=\"value\",\n"
        "         reasoning=\"ranking comparison across operators\")\n\n"
        "Q: \"Which sites have PUE under 1.3?\"\n"
        "  1) query(table=\"sites\",\n"
        "         where=[{column:\"yearly_pue\", op:\"<\", value:1.3}],\n"
        "         select=[\"building_name\", \"provider_name\", \"yearly_pue\", \"state_code\", \"datasheet_url\"],\n"
        "         order_by=[{column:\"yearly_pue\", direction:\"asc\"}], limit=20)\n"
        "  → likely no chart (table-style fact list); skip propose_chart or pass chart_type=\"none\".\n\n"
        "Rules:\n"
        "- Reject hallucinated columns: if a column is not in the schema, the\n"
        "  tool will return [{error: ...}]. Re-read the schema and retry.\n"
        "- For 'how much X has Y' use group_by + metric=\"sum:<mw_col>\" and\n"
        "  ALWAYS scope with a where clause for the entity in question.\n"
        "- The 'Company Not Disclosed' sentinel is auto-excluded when grouping\n"
        "  sites by provider_name."
    )


SYSTEM_PROMPT = _build_system_prompt()


# ---------------------------------------------------------------------------
# Per-table aggregate config: maps logical table to ORM model + MW column
# (kept for quick reference; query tool reads via _resolve_column instead)
# ---------------------------------------------------------------------------

_AGG_TABLES: dict[str, dict[str, Any]] = {
    "sites": {"model": Site, "mw": Site.power_capacity_mw},
    "generator_permits": {"model": GeneratorPermit, "mw": GeneratorPermit.rated_mw_total},
    "energy_projects": {"model": EnergyProject, "mw": EnergyProject.tot_contracted_power_mw},
    "edgar_extractions": {"model": EdgarExtraction, "mw": EdgarExtraction.capacity_mw},
    "companies": {"model": Company, "mw": None},
    "events": {"model": Event, "mw": None},
}

# Column-name aliases so the LLM can be slightly fuzzy without a 2nd round-trip.
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

# Canonical hyperscaler provider_name values in the DB.
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
    """Heuristically extract scope (state_code, provider_name) from the user
    question. Returns a dict suitable for query where-clauses."""
    import re

    q = (question or "").lower()
    scope: dict[str, str] = {}

    for name, code in _US_STATES.items():
        if re.search(rf"\b{re.escape(name)}\b", q):
            scope["state_code"] = code
            break
    else:
        for token in re.findall(r"\b[A-Z]{2}\b", question or ""):
            if token in _US_STATES.values():
                scope["state_code"] = token
                break

    for alias, canonical in _PROVIDER_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", q):
            scope["provider_name"] = canonical
            break

    return scope


def _augment_query_args(args: dict, question: str) -> dict:
    """If the LLM called `query` on sites without a where clause covering the
    obvious scope keys (state_code/provider_name) inferred from the question,
    inject them. Existing where-clause keys win."""
    if args.get("table") != "sites":
        return args
    scope = _infer_scope_from_question(question)
    if not scope:
        return args
    where = list(args.get("where") or [])
    # Resolve existing column names through the alias map.
    existing_cols = {
        _COLUMN_ALIASES.get(c.get("column", ""), c.get("column", ""))
        for c in where
        if isinstance(c, dict)
    }
    added = False
    for k, v in scope.items():
        if k not in existing_cols:
            where.append({"column": k, "op": "=", "value": v})
            added = True
    if added:
        new = dict(args)
        new["where"] = where
        return new
    return args


# ---------------------------------------------------------------------------
# Citation builders (per-table, only when useful)
# ---------------------------------------------------------------------------

def _citation_for_row(table: str, row: dict, model_obj: Any) -> Optional[dict]:
    """Build a _citation dict for a row, or None if there's nothing to cite."""
    if table == "sites":
        return {
            "table": "sites",
            "row_id": str(row.get("aterio_dc_uid") or row.get("id") or ""),
            "source_url": (
                row.get("datasheet_url")
                or row.get("permit_url")
                or getattr(model_obj, "map_url", None)
            ),
            "label": row.get("building_name") or row.get("campus_name") or "site",
        }
    if table == "generator_permits":
        raw = getattr(model_obj, "raw_payload", None) or {}
        url = None
        if isinstance(raw, dict):
            url = raw.get("source_url")
        return {
            "table": "generator_permits",
            "row_id": str(row.get("id") or ""),
            "source_url": url,
            "label": row.get("facility_name") or row.get("permittee_raw_name") or "permit",
        }
    if table == "edgar_extractions":
        return {
            "table": "edgar_extractions",
            "row_id": str(row.get("id") or ""),
            "source_url": row.get("edgar_url"),
            "label": f"{row.get('buyer_raw') or '?'} / {row.get('filing_date') or '?'}",
        }
    if table == "events":
        return {
            "table": "events",
            "row_id": str(row.get("id") or ""),
            "source_url": row.get("source_url"),
            "label": row.get("event_type") or "event",
        }
    return None


# ---------------------------------------------------------------------------
# Unified query tool
# ---------------------------------------------------------------------------

def _coerce_for_json(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _row_to_dict(model_obj: Any, table: str, select_cols: Iterable[str]) -> dict:
    out: dict[str, Any] = {}
    for c in select_cols:
        out[c] = _coerce_for_json(getattr(model_obj, c, None))
    return out


def _build_metric_expr(metric: str, model: Any) -> tuple[Any, Optional[str]]:
    """Return (sa_expression, error). Supports count | sum:<col> | avg:<col> |
    min:<col> | max:<col> | count_distinct:<col>."""
    if metric == "count":
        return func.count().label("value"), None
    if ":" not in metric:
        return None, f"unknown metric: {metric}"
    fn, col_name = metric.split(":", 1)
    col, _ = _resolve_column(model, col_name.strip())
    if col is None:
        return None, f"unknown column for metric: {col_name}"
    fn = fn.strip().lower()
    if fn == "sum":
        return func.coalesce(func.sum(col), 0).label("value"), None
    if fn == "avg":
        return func.avg(col).label("value"), None
    if fn == "min":
        return func.min(col).label("value"), None
    if fn == "max":
        return func.max(col).label("value"), None
    if fn == "count_distinct":
        return func.count(func.distinct(col)).label("value"), None
    return None, f"unknown metric function: {fn}"


def _apply_where(stmt, model: Any, where: list[dict], table: str):
    """Apply a list of {column, op, value} clauses. Returns (stmt, error)."""
    allowed_cols = set(_SCHEMA_WHITELIST.get(table, {}).keys())
    for clause in where or []:
        if not isinstance(clause, dict):
            return None, f"bad where clause: {clause!r}"
        col_name = clause.get("column")
        op = clause.get("op", "=")
        value = clause.get("value")
        if not col_name:
            return None, "where clause missing 'column'"
        col, canonical = _resolve_column(model, col_name)
        if col is None or canonical not in allowed_cols:
            return None, f"unknown column on {table}: {col_name}"
        if op == "=":
            stmt = stmt.where(col == value)
        elif op == "!=":
            stmt = stmt.where(col != value)
        elif op == ">":
            stmt = stmt.where(col > value)
        elif op == ">=":
            stmt = stmt.where(col >= value)
        elif op == "<":
            stmt = stmt.where(col < value)
        elif op == "<=":
            stmt = stmt.where(col <= value)
        elif op == "in":
            if not isinstance(value, list):
                return None, "op 'in' requires list value"
            stmt = stmt.where(col.in_(value))
        elif op == "ilike":
            stmt = stmt.where(col.ilike(f"%{value}%"))
        elif op == "is_null":
            stmt = stmt.where(col.is_(None))
        elif op == "is_not_null":
            stmt = stmt.where(col.is_not(None))
        elif op == "between":
            if not isinstance(value, list) or len(value) != 2:
                return None, "op 'between' requires 2-element list"
            stmt = stmt.where(col.between(value[0], value[1]))
        else:
            return None, f"unknown op: {op}"
    return stmt, None


async def _tool_query(
    session: AsyncSession,
    table: str,
    where: Optional[list[dict]] = None,
    select: Optional[list[str]] = None,
    group_by: Optional[list[str]] = None,
    metric: Optional[str] = None,
    order_by: Optional[list[dict]] = None,
    limit: int = 100,
) -> dict:
    """Unified data tool. Returns
    {total_count, returned, rows: list[dict], truncated: bool}.

    On error returns a list-shaped error envelope: [{"error": "..."}]
    so existing callers (and the dispatcher) can detect failures uniformly.
    """
    if table not in _TABLE_MODELS:
        return [{"error": f"unknown table: {table}"}]
    model = _TABLE_MODELS[table]
    allowed_cols = set(_SCHEMA_WHITELIST.get(table, {}).keys())

    try:
        limit = int(limit) if limit is not None else 100
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 1000))

    # --------------------------- aggregation mode ---------------------------
    if group_by:
        # Validate all group_by columns are whitelisted.
        group_cols = []
        canonical_group: list[str] = []
        for g in group_by:
            col, canonical = _resolve_column(model, g)
            if col is None or canonical not in allowed_cols:
                return [{"error": f"unknown column on {table}: {g}"}]
            group_cols.append(col)
            canonical_group.append(canonical)

        agg_metric = metric or "count"
        agg_expr, err = _build_metric_expr(agg_metric, model)
        if err:
            return [{"error": err}]

        stmt = sa_select(*group_cols, agg_expr)
        stmt, err = _apply_where(stmt, model, where or [], table)
        if err:
            return [{"error": err}]

        # Sentinel suppression for sites/provider_name groupings.
        if table == "sites" and "provider_name" in canonical_group:
            stmt = stmt.where(Site.provider_name.is_not(None)).where(
                Site.provider_name != "Company Not Disclosed"
            )

        stmt = stmt.group_by(*group_cols)

        # ORDER BY — supports `value` referring to the aggregate alias.
        ordered = False
        for ob in order_by or []:
            if not isinstance(ob, dict):
                continue
            ob_col = ob.get("column")
            direction = (ob.get("direction") or "desc").lower()
            if ob_col == "value":
                expr = agg_expr
            else:
                col, canonical = _resolve_column(model, ob_col or "")
                if col is None or canonical not in allowed_cols:
                    return [{"error": f"unknown order_by column: {ob_col}"}]
                expr = col
            stmt = stmt.order_by(expr.desc() if direction == "desc" else expr.asc())
            ordered = True
        if not ordered:
            stmt = stmt.order_by(agg_expr.desc())

        stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        raw_rows = result.all()
        rows: list[dict] = []
        for row in raw_rows:
            d: dict[str, Any] = {}
            for i, col_name in enumerate(canonical_group):
                d[col_name] = _coerce_for_json(row[i])
            val = row[len(canonical_group)]
            if val is not None:
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    pass
            d["value"] = val
            rows.append(d)
        return {
            "total_count": len(rows),
            "returned": len(rows),
            "rows": rows,
            "truncated": False,
        }

    # --------------------------- raw row mode -------------------------------
    # Validate select columns.
    if select:
        for s in select:
            _, canonical = _resolve_column(model, s)
            if canonical not in allowed_cols:
                return [{"error": f"unknown column on {table}: {s}"}]
        select_cols = [_COLUMN_ALIASES.get(s, s) for s in select]
    else:
        select_cols = list(allowed_cols)
        # Ensure 'id' is included if it's a real column on the model.
        if getattr(model, "id", None) is not None and "id" not in select_cols:
            select_cols.insert(0, "id")

    stmt = sa_select(model)
    stmt, err = _apply_where(stmt, model, where or [], table)
    if err:
        return [{"error": err}]

    # Order
    ordered = False
    for ob in order_by or []:
        if not isinstance(ob, dict):
            continue
        ob_col = ob.get("column")
        direction = (ob.get("direction") or "desc").lower()
        col, canonical = _resolve_column(model, ob_col or "")
        if col is None or canonical not in allowed_cols:
            return [{"error": f"unknown order_by column: {ob_col}"}]
        stmt = stmt.order_by(col.desc().nullslast() if direction == "desc" else col.asc().nullsfirst())
        ordered = True
    if not ordered:
        # Sensible default: largest MW first when applicable.
        mw_col = _AGG_TABLES.get(table, {}).get("mw")
        if mw_col is not None:
            stmt = stmt.order_by(mw_col.desc().nullslast())

    # total_count over the SAME where clause (no limit).
    count_stmt = sa_select(func.count()).select_from(model)
    count_stmt, err = _apply_where(count_stmt, model, where or [], table)
    if err:
        return [{"error": err}]
    total_count = int((await session.execute(count_stmt)).scalar() or 0)

    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    objs = result.scalars().all()

    rows: list[dict] = []
    for o in objs:
        d = _row_to_dict(o, table, select_cols)
        cite = _citation_for_row(table, d, o)
        if cite:
            d["_citation"] = cite
        rows.append(d)

    return {
        "total_count": total_count,
        "returned": len(rows),
        "rows": rows,
        "truncated": total_count > len(rows),
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

async def dispatch_tool(
    session: AsyncSession,
    name: str,
    args: dict,
    *,
    chart_proposal_holder: Optional[dict] = None,
) -> Any:
    """Run the named tool. Returns either:
      - a dict {total_count, returned, rows, truncated} for `query` success,
      - a list[{"error": ...}] for any error or `propose_chart` ack,
      - {"acknowledged": True} for `propose_chart` (caller stores proposal).
    """
    args = args or {}
    try:
        if name == "query":
            return await _tool_query(session, **args)
        if name == "propose_chart":
            if chart_proposal_holder is not None:
                chart_proposal_holder.clear()
                chart_proposal_holder.update(args)
            return {"acknowledged": True}
        return [{"error": f"unknown tool: {name}"}]
    except TypeError as exc:
        # Bad argument shape from the LLM.
        logger.warning(
            "datacenter_qa.tool_arg_error",
            extra={"tool": name, "args": args, "error": str(exc)},
        )
        return [{"error": f"bad args: {exc}"}]
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "datacenter_qa.tool_error",
            extra={"tool": name, "args": args, "error": str(exc)},
        )
        return [{"error": str(exc)}]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_error_envelope(result: Any) -> bool:
    return (
        isinstance(result, list)
        and len(result) >= 1
        and isinstance(result[0], dict)
        and "error" in result[0]
    )


def _result_rows(result: Any) -> list[dict]:
    """Extract rows from either query envelope or error envelope."""
    if isinstance(result, dict) and "rows" in result:
        return result["rows"] or []
    if isinstance(result, list):
        return result
    return []


def _result_summary(result: Any) -> tuple[str, int]:
    """Build (summary, row_count) for the ToolResultEvent."""
    if isinstance(result, dict) and "rows" in result:
        rows = result["rows"] or []
        total = result.get("total_count", len(rows))
        if rows and isinstance(rows[0], dict) and "error" in rows[0]:
            return f"error: {rows[0]['error'][:160]}", 0
        if not rows:
            return "no rows", 0
        if total > len(rows):
            return f"{len(rows)} of {total} row(s)", len(rows)
        return f"{len(rows)} row(s)", len(rows)
    if isinstance(result, list):
        if result and isinstance(result[0], dict) and "error" in result[0]:
            return f"error: {result[0]['error'][:160]}", 0
        return f"{len(result)} row(s)", len(result)
    if isinstance(result, dict) and result.get("acknowledged"):
        return "ok", 0
    return "ok", 0


def _build_chart_event_from_proposal(
    proposal: dict,
    last_query_result: Optional[Any],
    last_query_table: Optional[str],
) -> Optional[ChartSpecEvent]:
    """Construct a ChartSpecEvent from the captured propose_chart args. If the
    proposal has explicit `series`, use them; otherwise reconstruct from the
    most recent query result."""
    if not proposal:
        return None
    chart_type = proposal.get("chart_type") or "none"
    if chart_type == "none":
        return None
    if chart_type not in ("bar", "pie", "line", "scatter", "table"):
        return None

    title = proposal.get("title") or ""
    x = proposal.get("x") or ""
    y = proposal.get("y")
    # Coerce y list -> first element to keep schema scalar.
    if isinstance(y, list):
        y = y[0] if y else "value"
    y = y or "value"

    series = proposal.get("series")
    if not series:
        rows = _result_rows(last_query_result) if last_query_result is not None else []
        if rows and x and any(x in r for r in rows if isinstance(r, dict)):
            y_col = "value" if any("value" in r for r in rows if isinstance(r, dict)) else y
            series = [
                {"x": r.get(x), "y": r.get(y_col)}
                for r in rows
                if isinstance(r, dict)
                and r.get(x) is not None
                and r.get(y_col) is not None
            ]
        else:
            series = []

    if not series:
        return None

    return ChartSpecEvent(
        chart_type=chart_type,
        x=x or "x",
        y=str(y),
        series=series,
        title=title,
        source_table=last_query_table or "",
        breakdown_by=proposal.get("breakdown_by"),
        reasoning=proposal.get("reasoning"),
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def answer_question(
    session: AsyncSession,
    question: str,
    history: list[Message] | None = None,
) -> AsyncIterator[QAEvent]:
    """Multi-pass tool-using QA, yielding a discriminated union of events."""
    question = (question or "").strip()
    if not question:
        yield ErrorEvent(message="Please provide a question.")
        yield DoneEvent()
        return

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        for m in history[-8:]:
            try:
                messages.append({"role": m.role, "content": m.content})
            except AttributeError:
                if isinstance(m, dict) and m.get("role") and m.get("content"):
                    messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": question})

    tool_results: list[dict] = []
    seen_citations: set[tuple] = set()

    # Mutable holder for the latest propose_chart args; the dispatcher writes here.
    chart_proposal: dict = {}
    last_query_result: Optional[Any] = None
    last_query_table: Optional[str] = None

    rounds = 0
    max_rounds = 3
    while rounds < max_rounds:
        rounds += 1
        try:
            turn = await llm_client.reason(
                prompt_version="datacenter_qa_v2",
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

            # Safety net: scope inference for sites queries.
            if tool_name == "query":
                args = _augment_query_args(args, question)

            yield ToolCallEvent(tool_name=tool_name, args=args)

            result = await dispatch_tool(
                session, tool_name, args, chart_proposal_holder=chart_proposal
            )
            tool_results.append({"tool": tool_name, "args": args, "result": result})

            # Track most-recent successful query result for chart synthesis.
            if tool_name == "query" and isinstance(result, dict) and "rows" in result:
                last_query_result = result
                last_query_table = args.get("table")

            summary, row_count = _result_summary(result)
            yield ToolResultEvent(
                tool_name=tool_name, summary=summary, row_count=row_count
            )

            # Emit up to 3 unique citations from this result's rows.
            cites_emitted = 0
            for row in _result_rows(result):
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

            # Append a tool message for the LLM. Strip _citation noise + cap size.
            if isinstance(result, dict) and "rows" in result:
                payload_for_llm: Any = {
                    "total_count": result.get("total_count"),
                    "returned": result.get("returned"),
                    "truncated": result.get("truncated"),
                    "rows": [
                        {k: v for k, v in r.items() if k != "_citation"}
                        if isinstance(r, dict)
                        else r
                        for r in (result.get("rows") or [])
                    ],
                }
            else:
                payload_for_llm = result

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": tool_name,
                    "content": json.dumps(payload_for_llm, default=str)[:8000],
                }
            )

    # ----- Chart spec from captured proposal --------------------------------
    chart_event = _build_chart_event_from_proposal(
        chart_proposal, last_query_result, last_query_table
    )
    if chart_event is not None:
        yield chart_event

    # ----- Pass 2: stream natural-language synthesis ------------------------
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
            yield TextChunkEvent(
                content="(No streamed answer available; see tool results.)"
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("datacenter_qa.stream_failed")
        yield ErrorEvent(message=f"Streaming step failed: {exc}")

    yield DoneEvent()
