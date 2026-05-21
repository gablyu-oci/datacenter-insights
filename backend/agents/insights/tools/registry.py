"""Tool registry — OpenAI-shaped function specs for the agent's tool surface.

Each entry maps to an async dispatcher function. The list is consumed by
the LlmClient.reason()/chat_stream() `tools=` parameter; the dispatcher map
is consumed by the agentic driver to invoke the matching async function
when the model emits a tool_call. The surface includes `web_search` and
`emit_citation` (ARCH A6.4 / A6.7), and `run_skill` enumerates the 15
converted analytical skills (see `agents.insights.skills.ALL_SKILL_NAMES`).
"""
from __future__ import annotations

import inspect
import json
from typing import Any, Awaitable, Callable

from ..specs.skill_context import SkillContext
from .build_chart import build_chart
from .call_api import call_api
from .emit_chart import emit_chart
from .emit_citation import emit_citation
from .get_chart_data import get_chart_data
from .persist_insight import persist_insight
from .query_database import query_database
from .read_workspace import read_workspace
from .run_skill import ALL_SKILLS, run_skill
from .search_documents import search_documents
from .web_search import web_search


# ---------------------------------------------------------------------------
# OpenAI tool definitions
# ---------------------------------------------------------------------------

TOOL_DEFS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "description": (
                "Run a single read-only SELECT against the strategic-insights "
                "Postgres. Returns rows + row_hash + executed_sql. Max 10000 rows."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "Single Postgres-dialect SELECT statement.",
                    },
                    "max_rows": {
                        "type": "integer",
                        "default": 10000,
                        "maximum": 10000,
                    },
                },
                "required": ["sql"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_api",
            "description": (
                "Invoke an internal /api/ endpoint in-process. GET only. "
                "Use for fetching aggregated views from the existing routers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "endpoint": {
                        "type": "string",
                        "description": "Endpoint path under /api/, e.g. /api/triangulation/l2",
                    },
                    "params": {
                        "type": "object",
                        "additionalProperties": True,
                        "default": {},
                    },
                },
                "required": ["endpoint"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_chart_data",
            "description": (
                "Fetch the data behind a known chart on an existing tab. "
                "Use for warm-start triangulation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tab": {"type": "string"},
                    "chart_id": {"type": "string"},
                },
                "required": ["tab", "chart_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_skill",
            "description": (
                "Invoke a converted analytics skill. The dispatcher injects "
                "the skill's process fragment + RAG chunks for the next "
                "reasoning turn only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string", "enum": list(ALL_SKILLS)},
                    "inputs": {"type": "object", "additionalProperties": True},
                },
                "required": ["skill_name", "inputs"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "emit_chart",
            "description": (
                "Emit a final ChartSpec for the current insight. The spec is "
                "validated and the row_hash recomputed at server side."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": True,
                "description": "Inline ChartSpec object (see chart_spec.schema.json).",
            },
        },
    },
    # ---------------- Web search + citations ----------------
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Run a Brave Search query and return up to 5 results. "
                "Per-session cap: 8 calls (PRD §5.3). Snippets are pre-truncated "
                "to 280 characters. If the API key is missing or the upstream "
                "circuit is open, the tool returns degraded=true with a reason."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Free-text web search query.",
                    },
                    "n": {
                        "type": "integer",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 5,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "emit_citation",
            "description": (
                "Persist + emit a validated web citation for the current "
                "insight. Validates snippet ≤280 chars, agree_or_disagree enum, "
                "URL reachability (HEAD 2xx/3xx), and rationale-substring-of-snippet. "
                "agree/disagree tags require a numeric GW/MW/%/$ token in the "
                "snippet else are downgraded to 'context'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "snippet": {"type": "string", "maxLength": 280},
                    "agree_or_disagree": {
                        "type": "string",
                        "enum": ["agree", "disagree", "context"],
                    },
                    "rationale": {"type": "string"},
                    "search_query": {"type": "string"},
                },
                "required": [
                    "url",
                    "title",
                    "snippet",
                    "agree_or_disagree",
                    "rationale",
                    "search_query",
                ],
                "additionalProperties": False,
            },
        },
    },
    # ---------------- search + persistence ----------------
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": (
                "BM25 search over EDGAR filings + permits + earnings-call "
                "transcripts. Use BEFORE query_database for qualitative or "
                "disclosure-oriented questions. Prefer source='earnings' for "
                "forward-looking guidance and management commentary; prefer "
                "source='edgar' for executed commitments. Returns up to k "
                "passages with source/url/snippet/score."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "source": {
                        "type": "string",
                        "enum": ["edgar", "permits", "earnings", "all"],
                        "default": "all",
                    },
                    "k": {
                        "type": "integer",
                        "default": 8,
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_chart",
            "description": (
                "Validate + persist a chart for an insight. Pass the SQL whose "
                "rows the chart will visualize, an encoding mapping column names "
                "to visual axes, the chart_type, and a title. Always pass "
                "insight_id from the prior persist_insight call so the chart "
                "binds to the insight via FK. Example: build_chart("
                "insight_id='<uuid>', "
                "sql='SELECT state_code, SUM(power_capacity_mw) AS mw FROM sites GROUP BY state_code ORDER BY mw DESC LIMIT 10', "
                "encoding={'x': 'state_code', 'y': 'mw'}, "
                "chart_type='bar', title='Top 10 states by site MW')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "Single read-only SELECT. Same statement that grounded the insight body.",
                    },
                    "encoding": {
                        "type": "object",
                        "additionalProperties": True,
                        "description": (
                            "Column-name → visual-axis map. bar/line/area: "
                            "{'x': '<col>', 'y': '<col>'}. stacked_bar / "
                            "grouped_bar: add 'color': '<col>'. pie/donut: "
                            "{'category': '<col>', 'value': '<col>'}. kpi_tile: "
                            "{'value': '<col>'}."
                        ),
                    },
                    "chart_type": {
                        "type": "string",
                        "description": (
                            "One of: bar, stacked_bar, grouped_bar, pie, donut, "
                            "line, area, stacked_area, sparkline, scatter, "
                            "bubble, kpi_tile, table, treemap, radar, histogram. "
                            "Pick from data shape; do NOT default to bar."
                        ),
                    },
                    "title": {"type": "string"},
                    "subtitle": {"type": "string"},
                    "annotations": {"type": "array", "items": {"type": "object"}},
                    "styling": {"type": "object", "additionalProperties": True},
                    "insight_id": {
                        "type": "string",
                        "description": "UUID returned by persist_insight. Required to bind the chart.",
                    },
                },
                "required": ["sql", "encoding", "chart_type", "title", "insight_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_workspace",
            "description": "Read an allow-listed workspace file (SCHEMA.md, FRESHNESS.md, AI_INSIGHTS_*).",
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "enum": [
                            "SCHEMA.md",
                            "FRESHNESS.md",
                            "AI_INSIGHTS_PLAYBOOK.md",
                            "AI_INSIGHTS_PREFLIGHT_CHECKLIST.md",
                            "AI_INSIGHTS_SQL_SCHEMA_DISCIPLINE.md",
                        ],
                    },
                },
                "required": ["file"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "persist_insight",
            "description": (
                "Persist an insight with structured citations and an optional "
                "chart_id. Insight-first flow: chart_id and citations are both "
                "optional. The server auto-decorates if omitted."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "headline": {"type": "string"},
                    "body": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "materiality": {"type": "string", "enum": ["low", "medium", "high"]},
                    "citations": {"type": "array", "items": {"type": "object"}},
                    "chart_id": {"type": "string"},
                    "open_question_id": {"type": "string"},
                    "skills_run": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["headline", "body", "confidence", "materiality", "citations"],
                "additionalProperties": False,
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, Callable[..., Awaitable[Any]]] = {
    "query_database": query_database,
    "call_api": call_api,
    "get_chart_data": get_chart_data,
    "run_skill": run_skill,
    "emit_chart": emit_chart,           # kept — used by QA path
    "web_search": web_search,
    "emit_citation": emit_citation,
    "search_documents": search_documents,
    "build_chart": build_chart,
    "read_workspace": read_workspace,
    "persist_insight": persist_insight,
}


def _coerce_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Ensure dict shape; tolerate JSON-encoded args from streaming buffers."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return {"_raw": args}
    return args or {}


async def dispatch(
    name: str,
    args: dict[str, Any],
    ctx: SkillContext | None = None,
    db: Any = None,
) -> Any:
    """Run the dispatcher for the named tool with the provided args.

    `db` (AsyncSession) is forwarded to tools that need a transaction —
    write tools (build_chart, persist_insight). Read-only tools
    (query_database, search_documents, etc.) ignore it.
    """
    fn = _DISPATCH.get(name)
    if fn is None:
        return {"ok": False, "error": "unknown_tool", "detail": {"requested": name}}

    args_dict = _coerce_args(name, args)

    sig = inspect.signature(fn)
    accepts_ctx = "ctx" in sig.parameters

    if name == "query_database":
        if accepts_ctx:
            return await fn(args_dict.get("sql", ""), ctx, max_rows=args_dict.get("max_rows", 10_000))
        return await fn(args_dict.get("sql", ""), max_rows=args_dict.get("max_rows", 10_000))

    if name == "call_api":
        return await fn(
            args_dict.get("endpoint", ""),
            args_dict.get("params") or {},
            ctx if accepts_ctx else None,
        )

    if name == "get_chart_data":
        return await fn(
            args_dict.get("tab", ""),
            args_dict.get("chart_id", ""),
            ctx if accepts_ctx else None,
        )

    if name == "run_skill":
        return await fn(
            args_dict.get("skill_name", ""),
            args_dict.get("inputs") or {},
            ctx if accepts_ctx else None,
        )

    if name == "emit_chart":
        return await fn(args_dict, ctx if accepts_ctx else None)

    if name == "web_search":
        return await fn(
            args_dict.get("query", ""),
            int(args_dict.get("n") or 5),
            ctx if accepts_ctx else None,
        )

    if name == "emit_citation":
        return await fn(
            url=args_dict.get("url", ""),
            title=args_dict.get("title", ""),
            snippet=args_dict.get("snippet", ""),
            agree_or_disagree=args_dict.get("agree_or_disagree", ""),
            rationale=args_dict.get("rationale", ""),
            search_query=args_dict.get("search_query", ""),
            insight_id=args_dict.get("insight_id") or getattr(ctx, "insight_id", None),
            ctx=ctx if accepts_ctx else None,
        )

    if name == "search_documents":
        return await fn(
            args_dict.get("query", ""),
            args_dict.get("source", "all"),
            int(args_dict.get("k") or 8),
            ctx=ctx if accepts_ctx else None,
        )

    if name == "build_chart":
        # build_chart needs db + ctx.session_id to bind a chart to an insight.
        # Forward db from the caller (MCP server creates one per request).
        return await fn(
            sql=args_dict.get("sql", ""),
            encoding=args_dict.get("encoding") or {},
            chart_type=args_dict.get("chart_type", ""),
            title=args_dict.get("title", ""),
            subtitle=args_dict.get("subtitle"),
            annotations=args_dict.get("annotations"),
            styling=args_dict.get("styling"),
            insight_id=args_dict.get("insight_id"),
            ctx=ctx if accepts_ctx else None,
            db=db,
        )

    if name == "read_workspace":
        return await fn(
            args_dict.get("file", ""),
            ctx=ctx if accepts_ctx else None,
        )

    if name == "persist_insight":
        return await fn(
            headline=args_dict.get("headline", ""),
            body=args_dict.get("body"),
            confidence=args_dict.get("confidence", "medium"),
            materiality=args_dict.get("materiality", "medium"),
            chart_id=args_dict.get("chart_id"),
            citations=args_dict.get("citations") or [],
            open_question_id=args_dict.get("open_question_id"),
            skills_run=args_dict.get("skills_run"),
            ctx=ctx if accepts_ctx else None,
            db=db,
        )

    # Fallback (shouldn't reach for the registered names).
    return await fn(**args_dict)
