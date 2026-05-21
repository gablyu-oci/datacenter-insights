"""Session-scoped MCP write-tool handlers (Phase 2 / PRD/ARCH 14 §3).

The MCP server's ``_invoke_session`` looks up handlers by tool name in
``HANDLERS`` and delegates to them. Each handler receives an open
``AsyncSession``, the resolved session UUID, and the raw args dict; it
must return a small JSON-serialisable dict that the MCP envelope wraps
into ``{ok:True, result:..., code:0}``.

Validation failures raise ``ToolValidationError`` with a stable
``code`` slug (e.g. ``"BAD_INPUT"``, ``"DUPLICATE_NOOP"``,
``"MAX_INSIGHTS_EXCEEDED"``, ``"ALREADY_FINALIZED"``,
``"BRIEF_DUPLICATE_PERIOD"``, ``"BRIEF_ALREADY_PERSISTED"``,
``"BRIEF_RUN_NOT_FOUND"``); other exceptions surface as ``"TOOL_FAILED"``.

Why a separate module from `mcp_server.py`?
  * MCP tool handlers must stay thin (per Phase 1 architecture); the
    real work lives here so it can be unit-tested without spinning up
    the FastMCP transport.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ToolValidationError(Exception):
    """Raised for known/structured tool-level failures.

    The MCP envelope maps the ``code`` attribute onto the response's
    ``code`` field so the agent can branch on a stable slug rather than
    parsing a free-form message.
    """

    def __init__(self, message: str, *, code: str = "BAD_INPUT") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Brief-meta registry
# ---------------------------------------------------------------------------


# Process-local registry of session-scoped brief metadata. Populated by
# ``generate_weekly_brief`` before each session and read by
# ``persist_brief`` to recover the (period_start, period_end, model,
# prompt_version) values that are NOT carried in the agent-supplied
# args (the MCP tool signature is ``session_id, sections, citations``
# — see `mcp_server.py::persist_brief`). Keeping the metadata server-
# side rather than agent-supplied is the same tamper-resistance
# rationale architecture §10 OQ-D applies to ``bullet_count``.
_SESSION_BRIEF_META: dict[str, dict[str, Any]] = {}


def register_session_brief_meta(
    session_id: uuid.UUID,
    *,
    period_start: date,
    period_end: date,
    model: str,
    prompt_version: str,
) -> None:
    """Associate brief-context metadata with a session prior to driving.

    Called by ``generate_weekly_brief`` immediately before invoking the
    OpenClaw stream. ``_persist_brief_handler`` reads this back when the
    agent calls the MCP tool so we can compose the BriefRun row server-
    side.
    """
    _SESSION_BRIEF_META[str(session_id)] = {
        "period_start": period_start,
        "period_end": period_end,
        "model": model,
        "prompt_version": prompt_version,
    }


def clear_session_brief_meta(session_id: uuid.UUID) -> None:
    """Drop a session's brief-meta reference; safe to call repeatedly."""
    _SESSION_BRIEF_META.pop(str(session_id), None)


def _get_brief_meta(session_id: uuid.UUID) -> dict[str, Any] | None:
    return _SESSION_BRIEF_META.get(str(session_id))


# ---------------------------------------------------------------------------
# persist_insight handler
# ---------------------------------------------------------------------------


async def _persist_insight_handler(
    db: AsyncSession,
    session_uuid: uuid.UUID,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Persist one insight under an existing ai_session.

    Thin wrapper around `tools.persist_insight.persist_insight`.
    Returns ``{insight_id, chart_id, citation_count}``.
    """
    from .tools.persist_insight import persist_insight as _persist

    return await _persist(
        headline=args.get("headline", ""),
        body=args.get("body"),
        confidence=args.get("confidence", "medium"),
        materiality=args.get("materiality", "medium"),
        chart_id=args.get("chart_id"),
        citations=args.get("citations") or [],
        open_question_id=args.get("open_question_id"),
        skills_run=args.get("skills_run"),
        db=db,
        session_id=session_uuid,
    )


# ---------------------------------------------------------------------------
# finalize_session handler
# ---------------------------------------------------------------------------


_VALID_FINALIZE_STATUSES = {"complete", "degraded", "failed"}


async def _finalize_session_handler(
    db: AsyncSession,
    session_uuid: uuid.UUID,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Update an ai_session to a terminal status."""
    status = args.get("status")
    if status not in _VALID_FINALIZE_STATUSES:
        raise ToolValidationError(
            f"status must be one of {sorted(_VALID_FINALIZE_STATUSES)}; got {status!r}",
            code="BAD_INPUT",
        )
    token_estimate = int(args.get("token_estimate") or 0)
    if token_estimate < 0:
        raise ToolValidationError(
            "token_estimate must be >= 0", code="BAD_INPUT"
        )

    from .db.models import AISession

    existing = (
        await db.execute(select(AISession).where(AISession.id == session_uuid))
    ).scalar_one_or_none()
    if existing is None:
        raise ToolValidationError(
            f"ai_session_not_found: {session_uuid}", code="BAD_INPUT"
        )

    # Idempotency: a second finalize on a terminal row is a no-op.
    if existing.status in ("complete", "degraded", "failed", "cancelled"):
        return {
            "session_id": str(session_uuid),
            "status": existing.status,
            "idempotent": True,
        }

    # Defensive: re-count actual insight rows so the counter on the
    # session row matches what the user will see. The per-call
    # persist_insight bump should have done this already, but if a
    # prior in-flight write was rolled back we still want truth.
    from .db.models import AIInsight as _AIInsight
    from sqlalchemy import func as _sa_func

    actual_count_row = (
        await db.execute(
            select(_sa_func.count()).select_from(_AIInsight).where(
                _AIInsight.session_id == session_uuid
            )
        )
    ).scalar_one()
    actual_count = int(actual_count_row or 0)

    stmt = (
        update(AISession)
        .where(AISession.id == session_uuid)
        .values(
            status=status,
            finished_at=datetime.utcnow(),
            token_estimate=token_estimate,
            insights_emitted=actual_count,
        )
    )
    await db.execute(stmt)
    await db.flush()

    logger.info(
        "mcp.finalize_session",
        extra={"session_id": str(session_uuid), "status": status},
    )
    return {"session_id": str(session_uuid), "status": status}


# ---------------------------------------------------------------------------
# persist_brief handler (Phase 2 stub; Phase 4 fills the body)
# ---------------------------------------------------------------------------


_VALID_BRIEF_SECTION_KEYS = {"thesis", "movers", "outlook"}


def _assemble_brief_markdown(
    sections: dict[str, str], citations: list[dict[str, Any]]
) -> str:
    """Render the agent's section dict + citation list into a single
    markdown string suitable for ``BriefRun.markdown``.

    Only well-known section keys are rendered with dedicated headings;
    unknown keys are appended in insertion order under a generic
    `## <Title>` heading so we never silently drop content.
    """
    parts: list[str] = []

    # Stable canonical order: thesis -> movers -> outlook -> extras.
    canonical_order = ("thesis", "movers", "outlook")
    rendered: set[str] = set()
    for key in canonical_order:
        body = sections.get(key)
        if not body:
            continue
        title = key.capitalize()
        parts.append(f"## {title}\n\n{str(body).strip()}")
        rendered.add(key)
    for key, body in sections.items():
        if key in rendered or not body:
            continue
        title = str(key).replace("_", " ").strip().capitalize() or "Section"
        parts.append(f"## {title}\n\n{str(body).strip()}")

    md = "\n\n".join(parts).strip()

    # Append a Sources section if citations were supplied. We render as
    # a markdown bullet list so the existing bullet_count derivation
    # (count("\n- ") + count("\n* ")) picks them up alongside the
    # movers list.
    if citations:
        cite_lines: list[str] = ["", "## Sources", ""]
        for c in citations:
            if not isinstance(c, dict):
                continue
            url = str(c.get("url") or "").strip()
            if not url:
                continue
            title = str(c.get("title") or url).strip()
            excerpt = str(c.get("excerpt") or "").strip()
            if excerpt:
                cite_lines.append(f"- [{title}]({url}) — {excerpt}")
            else:
                cite_lines.append(f"- [{title}]({url})")
        md = (md + "\n" + "\n".join(cite_lines)).strip() + "\n"

    return md or "_(no brief content)_"


async def _persist_brief_handler(
    db: AsyncSession,
    session_uuid: uuid.UUID,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Persist one weekly-brief BriefRun row (Phase 4 / ARCH §3.4).

    Inputs (per MCP `persist_brief` signature):
      - ``sections``: dict of section markdown bodies, e.g.
        ``{"thesis": "...", "movers": "...", "outlook": "..."}``. Must
        be a non-empty dict.
      - ``citations``: list of dicts each shaped
        ``{"url": str, "title": str, "excerpt": str?}``. May be empty.

    The (period_start, period_end, model, prompt_version) tuple is
    looked up from the process-local ``register_session_brief_meta``
    registry rather than trusting the agent — both for tamper-
    resistance and because the MCP tool signature does not carry these
    fields (the synthesis tool's signature is fixed at ``session_id,
    sections, citations`` in `mcp_server.py`).

    Behaviour:
      * If a BriefRun row already exists with the same (period_start,
        period_end), update its ``markdown`` in place and return the
        existing brief_id (idempotency for re-runs in the same week —
        ARCH §3.4 "If existing row's status is ``failed``, it is
        overwritten in place").
      * Otherwise INSERT a new BriefRun row with ``markdown`` rendered
        from sections + citations. ``bullet_count`` is server-computed
        per ARCH §10 OQ-D (tamper resistance).
      * If the brief metadata for ``session_uuid`` was never
        registered, surface ``BRIEF_RUN_NOT_FOUND`` so the agent stops
        cleanly.
    """
    sections = args.get("sections")
    citations = args.get("citations") or []
    if not isinstance(sections, dict) or not sections:
        raise ToolValidationError(
            "sections must be a non-empty object", code="BAD_INPUT"
        )
    if not isinstance(citations, list):
        raise ToolValidationError("citations must be a list", code="BAD_INPUT")

    # Validate section values are strings (per task: dict[str, str]).
    for k, v in sections.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ToolValidationError(
                "sections must map string keys to string values",
                code="BAD_INPUT",
            )

    # Validate citation entries.
    for c in citations:
        if not isinstance(c, dict):
            raise ToolValidationError(
                "each citation must be an object", code="BAD_INPUT"
            )
        url = c.get("url")
        title = c.get("title")
        if not isinstance(url, str) or not url.strip():
            raise ToolValidationError(
                "citation.url must be a non-empty string", code="BAD_INPUT"
            )
        if title is not None and not isinstance(title, str):
            raise ToolValidationError(
                "citation.title must be a string when present", code="BAD_INPUT"
            )

    # Recover the brief metadata registered by generate_weekly_brief.
    meta = _get_brief_meta(session_uuid)
    if meta is None:
        raise ToolValidationError(
            f"brief_run_not_found: no brief metadata registered for "
            f"session_id={session_uuid}",
            code="BRIEF_RUN_NOT_FOUND",
        )

    period_start = meta.get("period_start")
    period_end = meta.get("period_end")
    model = meta.get("model") or "unknown"
    prompt_version = meta.get("prompt_version") or "brief_rules@v1"
    if not isinstance(period_start, date) or not isinstance(period_end, date):
        raise ToolValidationError(
            "brief_run_meta_corrupted: period_start/period_end missing",
            code="BRIEF_RUN_NOT_FOUND",
        )

    try:
        from db.models import BriefRun  # type: ignore
    except Exception as exc:  # pragma: no cover — env-dependent
        raise ToolValidationError(
            f"brief_run_model_unavailable: {exc}",
            code="BRIEF_RUN_NOT_FOUND",
        ) from exc

    # Compose markdown server-side.
    markdown = _assemble_brief_markdown(sections, citations)
    bullet_count = markdown.count("\n- ") + markdown.count("\n* ")

    # Idempotency: a same-period run should overwrite in place rather
    # than spawning a duplicate row. ARCH §3.4 'If existing row's
    # status is failed, it is overwritten in place'. Today's BriefRun
    # has no `status` column, so we always overwrite the most-recent
    # match for the period (ordered by generated_at desc).
    existing_row = (
        await db.execute(
            select(BriefRun)
            .where(
                BriefRun.period_start == period_start,
                BriefRun.period_end == period_end,
            )
            .order_by(BriefRun.generated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if existing_row is not None:
        existing_row.markdown = markdown
        existing_row.model = model
        existing_row.prompt_version = prompt_version
        existing_row.bullet_count = bullet_count
        # Preserve tokens_in/out/latency_ms if already set; otherwise
        # leave NULL (driver-supplied values are accounted via the
        # finalize_session token_estimate path).
        existing_row.generated_at = datetime.utcnow()
        await db.flush()
        logger.info(
            "mcp.persist_brief.updated",
            extra={
                "session_id": str(session_uuid),
                "brief_id": existing_row.id,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "bullet_count": bullet_count,
            },
        )
        return {"brief_id": str(existing_row.id), "idempotent": True}

    new_row = BriefRun(
        period_start=period_start,
        period_end=period_end,
        markdown=markdown,
        model=model,
        prompt_version=prompt_version,
        bullet_count=bullet_count,
        # tokens / latency are populated by the agent's finalize_session
        # call on AISession.token_estimate; BriefRun retains NULL here
        # for now (Phase 5 may surface them via ai_session join).
        tokens_in=None,
        tokens_out=None,
        latency_ms=None,
    )
    db.add(new_row)
    await db.flush()
    logger.info(
        "mcp.persist_brief.inserted",
        extra={
            "session_id": str(session_uuid),
            "brief_id": new_row.id,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "bullet_count": bullet_count,
        },
    )
    return {"brief_id": str(new_row.id), "idempotent": False}


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------


HANDlerSig = Callable[
    [AsyncSession, uuid.UUID, dict[str, Any]], Awaitable[dict[str, Any]]
]

HANDLERS: dict[str, HANDlerSig] = {
    "persist_insight": _persist_insight_handler,
    "finalize_session": _finalize_session_handler,
    "persist_brief": _persist_brief_handler,
}


__all__ = [
    "ToolValidationError",
    "HANDLERS",
    "register_session_brief_meta",
    "clear_session_brief_meta",
]
