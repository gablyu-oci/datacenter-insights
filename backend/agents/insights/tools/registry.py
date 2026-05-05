"""Tool registry — OpenAI-shaped function specs for the V1+V2 tool surface.

Each entry maps to an async dispatcher function. The list is consumed by
the LlmClient.reason()/chat_stream() `tools=` parameter; the dispatcher map
is consumed by the ToolLoopDriver to invoke the matching async function
when the model emits a tool_call.

V2 lights up `web_search` + `emit_citation` (ARCH A6.4 / A6.7). The
`run_skill` tool's `skill_name` enum now lists 15 names (V1 + V2).
"""
from __future__ import annotations

import inspect
import json
from typing import Any, Awaitable, Callable

from ..specs.skill_context import SkillContext
from .call_api import call_api
from .emit_chart import emit_chart
from .emit_citation import emit_citation
from .get_chart_data import get_chart_data
from .query_database import query_database
from .run_skill import ALL_SKILLS, run_skill
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
                "description": "Inline ChartSpec v1 object (see chart_spec.schema.json).",
            },
        },
    },
    # ---------------- V2 tools ----------------
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "V2: run a Brave Search query and return up to 5 results. "
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
                "V2: persist + emit a validated web citation for the current "
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
]

# Backward-compatible alias retained for V1 callers (orchestrator etc.).
V1_TOOL_DEFS: list[dict[str, Any]] = TOOL_DEFS


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_DISPATCH: dict[str, Callable[..., Awaitable[Any]]] = {
    "query_database": query_database,
    "call_api": call_api,
    "get_chart_data": get_chart_data,
    "run_skill": run_skill,
    "emit_chart": emit_chart,
    "web_search": web_search,
    "emit_citation": emit_citation,
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
) -> Any:
    """Run the dispatcher for the named tool with the provided args."""
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

    # Fallback (shouldn't reach for the registered names).
    return await fn(**args_dict)
