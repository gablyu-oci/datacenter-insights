"""web_search (V2) -- Brave Search API wrapper + agree/disagree judge.

Provider: Brave Search (primary; per kickoff override of RESEARCH §1.3).
Endpoint: https://api.search.brave.com/res/v1/web/search
Auth header: `X-Subscription-Token: <BRAVE_SEARCH_API_KEY>`

Operational rules:
- Per-session cap: 8 calls (PRD §5.3). Tracked on ``ctx.web_search_count``;
  cap breach returns ``{"ok": False, "error": "web_search_cap"}``.
- Result count capped at 5 per call.
- Snippets truncated to 280 chars (PRD §5.3 Citation schema).
- If ``BRAVE_SEARCH_API_KEY`` is missing: return graceful-degradation
  ``{"ok": True, "results": [], "degraded": True, "reason": "no_api_key"}``
  and emit a `web_search_unavailable` SSE event with ``reason="no_api_key"``.
- Circuit breaker: 3 consecutive 5xx OR 429 responses inside 60 s open the
  breaker for 5 minutes. Open-state calls return graceful-degradation with
  ``reason="circuit_open"`` (no upstream call made).

The two-stage agree/disagree judge (RESEARCH §7) is implemented separately
as ``judge_citations(insight_headline, results)``. It calls
``MODELS["extraction"]`` with low effort and a strict tool-spec asking
"Does snippet (a) corroborate within 20%, (b) contradict, (c) provide
context only -- return JSON {tag, rationale}; rationale must be substring
of snippet."
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

UTC = timezone.utc

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_RESULT_COUNT = 5
SNIPPET_MAX = 280
PER_SESSION_CAP = 8
HTTP_TIMEOUT_SECONDS = 8.0

# Circuit breaker state -- module-level (single-worker, single-process).
_CIRCUIT_WINDOW_S = 60.0
_CIRCUIT_OPEN_FOR_S = 300.0
_CIRCUIT_FAIL_THRESHOLD = 3


class _CircuitState:
    def __init__(self) -> None:
        self.consecutive_failures = 0
        self.first_failure_ts: float | None = None
        self.unhealthy_until_ts: float = 0.0
        self._lock = asyncio.Lock()

    def is_open(self) -> bool:
        return time.monotonic() < self.unhealthy_until_ts

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.first_failure_ts = None

    def record_failure(self) -> None:
        now = time.monotonic()
        if (
            self.first_failure_ts is None
            or (now - self.first_failure_ts) > _CIRCUIT_WINDOW_S
        ):
            self.first_failure_ts = now
            self.consecutive_failures = 1
        else:
            self.consecutive_failures += 1

        if self.consecutive_failures >= _CIRCUIT_FAIL_THRESHOLD:
            self.unhealthy_until_ts = now + _CIRCUIT_OPEN_FOR_S
            logger.warning(
                "ai_insights.web_search.circuit_open",
                extra={"open_for_s": _CIRCUIT_OPEN_FOR_S},
            )


_circuit = _CircuitState()


async def _emit_unavailable(ctx: Any, reason: str) -> None:
    """Best-effort emit a `web_search_unavailable` SSE event via ctx.emit_event."""
    if ctx is None:
        return
    emitter = getattr(ctx, "emit_event", None)
    if emitter is None:
        return
    try:
        from ..specs.sse_events import (
            WebSearchUnavailableData,
            WebSearchUnavailableEvent,
        )

        evt = WebSearchUnavailableEvent(
            event_id=f"wsu_{uuid.uuid4().hex[:12]}",
            seq=0,
            data=WebSearchUnavailableData(
                reason=reason,  # type: ignore[arg-type]
                session_id=getattr(ctx, "session_id", None),
                insight_id=None,
            ),
        )
        result = emitter(evt)
        if asyncio.iscoroutine(result):
            await result
    except Exception:  # noqa: BLE001
        # Never let SSE emission failure break the tool path.
        logger.debug("ai_insights.web_search.emit_failed", exc_info=True)


def _truncate_snippet(text: str | None) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) > SNIPPET_MAX:
        return text[: SNIPPET_MAX - 1] + "…"
    return text


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def web_search(
    query: str,
    n: int = DEFAULT_RESULT_COUNT,
    ctx: Any | None = None,
) -> dict[str, Any]:
    """Run a Brave Search query, return up to ``n`` (≤5) result rows.

    Output shape (success)::

        {
          "ok": True,
          "results": [
            {"url", "title", "snippet", "search_query", "retrieved_at",
             "provider": "brave"},
            ...
          ]
        }

    Output shape (graceful-degradation)::

        {"ok": True, "results": [], "degraded": True, "reason": <str>}

    Output shape (cap breach / hard error)::

        {"ok": False, "error": <code>, ...}
    """
    n = max(1, min(int(n or DEFAULT_RESULT_COUNT), 5))

    # Per-session cap.
    if ctx is not None:
        used = int(getattr(ctx, "web_search_count", 0) or 0)
        if used >= PER_SESSION_CAP:
            return {
                "ok": False,
                "error": "web_search_cap",
                "detail": {"used": used, "cap": PER_SESSION_CAP},
            }

    # Circuit-breaker short-circuit.
    if _circuit.is_open():
        await _emit_unavailable(ctx, "circuit_open")
        return {
            "ok": True,
            "results": [],
            "degraded": True,
            "reason": "circuit_open",
        }

    api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        await _emit_unavailable(ctx, "no_api_key")
        return {
            "ok": True,
            "results": [],
            "degraded": True,
            "reason": "no_api_key",
        }

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params = {"q": query, "count": n}

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.get(BRAVE_ENDPOINT, headers=headers, params=params)
    except httpx.TimeoutException:
        _circuit.record_failure()
        return {"ok": False, "error": "timeout"}
    except httpx.HTTPError as exc:
        _circuit.record_failure()
        return {"ok": False, "error": "transport", "detail": str(exc)}

    if resp.status_code == 429:
        _circuit.record_failure()
        await _emit_unavailable(ctx, "rate_limited")
        return {
            "ok": True,
            "results": [],
            "degraded": True,
            "reason": "rate_limited",
        }
    if 500 <= resp.status_code < 600:
        _circuit.record_failure()
        return {
            "ok": False,
            "error": "upstream_5xx",
            "status_code": resp.status_code,
        }
    if resp.status_code >= 400:
        # 4xx (e.g., bad query, expired key) -- not breaker-eligible.
        return {
            "ok": False,
            "error": "upstream_4xx",
            "status_code": resp.status_code,
        }

    try:
        body = resp.json()
    except json.JSONDecodeError:
        _circuit.record_failure()
        return {"ok": False, "error": "bad_json"}

    _circuit.record_success()

    raw_results = (((body or {}).get("web") or {}).get("results")) or []
    if not isinstance(raw_results, list):
        raw_results = []

    out_rows: list[dict[str, Any]] = []
    retrieved_at = _now_iso()
    for r in raw_results[:n]:
        if not isinstance(r, dict):
            continue
        url = (r.get("url") or "").strip()
        if not url:
            continue
        out_rows.append(
            {
                "url": url,
                "title": (r.get("title") or "").strip(),
                "snippet": _truncate_snippet(r.get("description")),
                "search_query": query,
                "retrieved_at": retrieved_at,
                "provider": "brave",
            }
        )

    # Increment per-session counter on a successful upstream call (degraded
    # paths above already returned without consuming a quota slot).
    if ctx is not None:
        try:
            object.__setattr__(
                ctx, "web_search_count", int(getattr(ctx, "web_search_count", 0)) + 1
            )
        except Exception:  # noqa: BLE001
            pass

    return {"ok": True, "results": out_rows}


# ---------------------------------------------------------------------------
# Two-stage agree/disagree judge (RESEARCH §7)
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM = (
    "You are a strict citation classifier. For each (snippet, insight) pair, "
    "decide if the snippet (a) corroborates the insight's quantitative or "
    "directional claim within 20% tolerance, (b) contradicts it, or (c) "
    "merely provides context. "
    "Output a JSON list, one element per snippet, in the same order, "
    "each shaped {\"url\": str, \"tag\": \"agree\"|\"disagree\"|\"context\", "
    "\"rationale\": str}. The rationale MUST be a substring of the snippet "
    "(case-insensitive whitespace-normalised match). "
    "If you are uncertain, use tag=\"context\". Do not invent facts."
)


async def judge_citations(
    insight_headline: str,
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """LLM-classify a batch of search results against an insight.

    Returns a list of ``{url, tag, rationale}`` dicts, one per input result.
    On any failure, returns a default ``context``-tagged list using the
    snippet as rationale (safest non-quantitative classification).
    """
    if not results:
        return []

    # Default classification used both as fallback and when the LLM omits a
    # url in its response. ``context`` is the safe default per the prompt.
    def _default(r: dict[str, Any]) -> dict[str, Any]:
        snippet = r.get("snippet") or ""
        return {
            "url": r.get("url", ""),
            "tag": "context",
            "rationale": snippet[:280],
        }

    payload = [
        {
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "snippet": r.get("snippet", ""),
        }
        for r in results
    ]
    prompt = (
        f"INSIGHT: {insight_headline.strip()[:500]}\n\n"
        f"SNIPPETS (JSON list):\n{json.dumps(payload, default=str)[:6000]}\n\n"
        "Return JSON list per the system spec. JSON only, no markdown."
    )

    try:
        from backend.llm.client import MODELS, llm_client  # type: ignore

        msgs = [
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": prompt},
        ]
        turn = await llm_client.reason(
            model=MODELS["extraction"],
            prompt_version="ai-insights/judge_citations",
            messages=msgs,
        )
        text = (turn.content or "").strip()
    except Exception:  # noqa: BLE001
        return [_default(r) for r in results]

    # Strip optional code fence.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
        text = text.strip("`\n ")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [_default(r) for r in results]

    if not isinstance(parsed, list):
        return [_default(r) for r in results]

    by_url: dict[str, dict[str, Any]] = {}
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        url = (entry.get("url") or "").strip()
        tag = (entry.get("tag") or "").strip().lower()
        rationale = (entry.get("rationale") or "").strip()
        if tag not in ("agree", "disagree", "context"):
            tag = "context"
        if not url or not rationale:
            continue
        by_url[url] = {"url": url, "tag": tag, "rationale": rationale}

    out: list[dict[str, Any]] = []
    for r in results:
        url = r.get("url", "")
        out.append(by_url.get(url) or _default(r))
    return out
