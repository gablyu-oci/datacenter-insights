"""emit_citation (V2) -- validate + persist + emit a web citation.

Per ARCH A6.7 / PRD §5.3:
- snippet ≤280 chars
- agree_or_disagree ∈ {agree, disagree, context}
- URL must be reachable (HEAD 2xx/3xx) within a 5 s timeout
- rationale must appear (case-insensitive, whitespace-normalised) inside the
  snippet -- otherwise reject with `rationale_unsupported`
- For agree/disagree tags, the snippet must contain a numeric token of shape
  ``\\d+\\.?\\d*\\s*(GW|MW|%|\\$)`` -- if not, downgrade to `context` and
  surface a non-fatal warning (still ok=True).

Persistence: writes a row into the existing `agent_citation` table (created
in alembic 009; see backend/agents/insights/db/models.py::AgentCitation).
The kickoff spec used the table name "citations" (plural); we use the
already-created singular table name to avoid a redundant rename. The
migration 011 still adds the V2 fk-stub `insight_subscription` table and
alters `ai_insight` columns.

The legacy `EmitCitationDisabledError` symbol stays exported for any V1
callers that imported it; it is no longer raised from this function.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

UTC = timezone.utc

SNIPPET_MAX = 280
URL_HEAD_TIMEOUT = 5.0

# Numeric/qualified token regex per the spec.
_QUANT_RE = re.compile(r"\d+\.?\d*\s*(GW|MW|%|\$)", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


class EmitCitationDisabledError(NotImplementedError):
    """Legacy V1 marker; no longer raised. Retained for import-stability."""


def _normalise(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").strip().lower())


async def _head_ok(url: str) -> bool:
    """Return True iff a HEAD request resolves to 2xx/3xx within timeout."""
    try:
        async with httpx.AsyncClient(timeout=URL_HEAD_TIMEOUT) as client:
            resp = await client.head(url, follow_redirects=True)
    except httpx.HTTPError:
        return False
    return 200 <= resp.status_code < 400


async def _emit_event(ctx: Any, payload: dict[str, Any]) -> None:
    """Best-effort emit a `citation` SSE event via ctx.emit_event."""
    if ctx is None:
        return
    emitter = getattr(ctx, "emit_event", None)
    if emitter is None:
        return
    try:
        from ..specs.sse_events import (
            CitationEvent,
            CitationEventData,
            WebCitation,
        )

        wc = WebCitation(**payload)
        evt = CitationEvent(
            event_id=f"cit_{uuid.uuid4().hex[:12]}",
            seq=0,
            data=CitationEventData(
                insight_id=getattr(ctx, "insight_id", "") or "",
                citation=wc,
            ),
        )
        result = emitter(evt)
        if hasattr(result, "__await__"):
            await result
    except Exception:  # noqa: BLE001
        logger.debug("ai_insights.emit_citation.emit_failed", exc_info=True)


async def emit_citation(
    *,
    url: str,
    title: str,
    snippet: str,
    agree_or_disagree: str,
    rationale: str,
    search_query: str,
    insight_id: str | None = None,
    provider: str | None = "brave",
    ctx: Any | None = None,
    persister: Any | None = None,
) -> dict[str, Any]:
    """Validate + persist + emit a single web citation.

    Returns ``{"ok": True, "citation": {...}}`` on success, else
    ``{"ok": False, "error": <code>, ...}``.

    ``persister``: optional ``async def(payload: dict) -> None`` (the chat
    router supplies one bound to the active SQLAlchemy session). When
    omitted, the citation is still validated and event-emitted but not
    persisted; the caller is responsible for any later DB write.
    """
    # Snippet length
    if len(snippet or "") > SNIPPET_MAX:
        return {
            "ok": False,
            "error": "snippet_too_long",
            "detail": {"len": len(snippet), "max": SNIPPET_MAX},
        }

    # Tag enum
    tag = (agree_or_disagree or "").strip().lower()
    warnings: list[str] = []
    if tag not in ("agree", "disagree", "context"):
        return {
            "ok": False,
            "error": "invalid_tag",
            "detail": {
                "received": agree_or_disagree,
                "allowed": ["agree", "disagree", "context"],
            },
        }

    # Rationale substring check (case-insensitive, whitespace-normalised).
    norm_snip = _normalise(snippet)
    norm_rat = _normalise(rationale)
    if not norm_rat:
        return {
            "ok": False,
            "error": "rationale_empty",
        }
    if norm_rat not in norm_snip:
        return {
            "ok": False,
            "error": "rationale_unsupported",
        }

    # Quant requirement for agree/disagree -- downgrade to context on miss.
    if tag in ("agree", "disagree") and not _QUANT_RE.search(snippet or ""):
        warnings.append(
            "downgraded to 'context' -- snippet has no GW/MW/%/$ numeric token"
        )
        tag = "context"

    # URL reachability.
    if not url or not isinstance(url, str):
        return {"ok": False, "error": "missing_url"}
    reachable = await _head_ok(url)
    if not reachable:
        return {
            "ok": False,
            "error": "url_unreachable",
            "detail": {"url": url},
        }

    retrieved_at = datetime.now(UTC)
    payload: dict[str, Any] = {
        "url": url,
        "title": title or "",
        "snippet": snippet,
        "agree_or_disagree": tag,
        "rationale": rationale,
        "search_query": search_query,
        "retrieved_at": retrieved_at.isoformat(),
        "provider": provider,
    }

    # Persistence (optional injection).
    persisted_id: str | None = None
    if persister is not None:
        try:
            persist_payload = dict(payload)
            persist_payload["insight_id"] = insight_id or getattr(ctx, "insight_id", None)
            persisted_id = await persister(persist_payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_insights.emit_citation.persist_failed", exc_info=True)
            warnings.append(f"persist_failed:{type(exc).__name__}")

    # Emit SSE event with the validated payload (datetime is JSON-friendly).
    sse_payload = dict(payload)
    sse_payload["retrieved_at"] = retrieved_at  # WebCitation parses as datetime
    await _emit_event(ctx, sse_payload)

    out: dict[str, Any] = {
        "ok": True,
        "citation": payload,
    }
    if persisted_id:
        out["citation_id"] = persisted_id
    if warnings:
        out["warnings"] = warnings
    return out
