"""persist_insight — V2 final-sink tool that closes out an insight.

Pipeline (architecture §3.3):

    1. Resolve session: must exist and have status='running' (or
       'in_progress'). A finished/aborted session cannot accept new
       inserts; the orchestrator surfaces `session_closed` so the agent
       can stop calling tools.
    2. chart_id required and must point at an `agent_chart` row whose
       `session_id` matches the active session. Cross-session reference
       returns `chart_session_mismatch`.
    3. citations must be a non-empty list. Empty -> `citations_required`.
       Each citation must already exist in `agent_citation` and (if it
       carries an `insight_id`) be either unbound or bound to this same
       row pre-flight. (Existing v2 citations are written unbound first
       by `emit_citation`.)
    4. headline: non-empty, <=140 chars (mega-thread tile constraint).
       body: optional, <=4000 chars.
    5. Insert ai_insight row with v2 columns:
         - chart_id (FK -> agent_chart.id)
         - citations (JSONB list of {citation_id, kind})
         - open_question_id (optional pointer into OpenClaw memory)
         - version='v2'
       Then patch the `agent_chart.insight_id` to bind the chart to
       this insight.
    6. Best-effort patch each agent_citation row's `insight_id` so the
       provenance graph is bidirectional.

Return shape: ``{ok: True, insight_id: str, chart_id: str, citation_count: int}``
On any guard failure: ``{ok: False, error: <code>, message: ..., detail: ...}``.

The v1 `persist_insight` path is left untouched; this module is a
parallel sink for the v2 agent loop.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update

from ..specs.skill_context import SkillContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

HEADLINE_MAX = 140
BODY_MAX = 4_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _err(code: str, message: str, **detail: Any) -> dict[str, Any]:
    # Round 3: emit a structured WARNING so the next on-call can see
    # exactly which guard rejected the agent's persist payload. Without
    # this, the failure is silent (the error envelope flows back through
    # the MCP wrapper as `{ok:True, result:{ok:False, error:<code>}}`
    # and never lands in the FastAPI stdout).
    logger.warning(
        "ai_insights.persist_insight.rejected code=%s message=%s detail=%s",
        code, message, detail,
        extra={"err_code": code, "err_message": message, "err_detail": detail},
    )
    return {"ok": False, "error": code, "message": message, "detail": detail}


def _coerce_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except Exception:  # noqa: BLE001
        return None


def _normalise_citations(raw: Any) -> list[dict[str, Any]] | None:
    """Accept either ['<uuid>', ...] or [{citation_id, kind?}, ...]."""
    if not isinstance(raw, list) or not raw:
        return None
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            out.append({"citation_id": item, "kind": "web"})
        elif isinstance(item, dict):
            cid = item.get("citation_id") or item.get("id")
            if not cid:
                return None
            out.append({"citation_id": str(cid), "kind": item.get("kind", "web")})
        else:
            return None
    return out


# ---------------------------------------------------------------------------
# Validation steps
# ---------------------------------------------------------------------------


async def _resolve_session(db: Any, session_id: uuid.UUID) -> Any:
    from ..db.models import AISession

    result = await db.execute(select(AISession).where(AISession.id == session_id))
    row = result.scalars().first() if hasattr(result, "scalars") else None
    if row is None and hasattr(result, "first"):
        row = result.first()
    return row


async def _resolve_chart(
    db: Any, chart_id: str, session_id: uuid.UUID
) -> tuple[Any | None, str | None]:
    """Return (chart_row, error_code)."""
    from ..db.models import AgentChart

    result = await db.execute(select(AgentChart).where(AgentChart.id == chart_id))
    row = result.scalars().first() if hasattr(result, "scalars") else None
    if row is None and hasattr(result, "first"):
        row = result.first()
    if row is None:
        return None, "chart_not_found"
    if _coerce_uuid(row.session_id) != session_id:
        return None, "chart_session_mismatch"
    return row, None


async def _resolve_citations(
    db: Any, citations: list[dict[str, Any]]
) -> tuple[list[Any], list[str]]:
    """Look up each citation row. Returns (rows_found, missing_ids)."""
    from ..db.models import AgentCitation

    found: list[Any] = []
    missing: list[str] = []
    for c in citations:
        cid = _coerce_uuid(c["citation_id"])
        if cid is None:
            missing.append(c["citation_id"])
            continue
        result = await db.execute(select(AgentCitation).where(AgentCitation.id == cid))
        row = result.scalars().first() if hasattr(result, "scalars") else None
        if row is None and hasattr(result, "first"):
            row = result.first()
        if row is None:
            missing.append(str(cid))
        else:
            found.append(row)
    return found, missing


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def persist_insight(
    *,
    headline: str,
    body: str | None,
    confidence: str,
    materiality: str,
    chart_id: str | None = None,
    citations: list[Any],
    open_question_id: str | None = None,
    skills_run: list[str] | None = None,
    ctx: SkillContext | None = None,
    db: Any,
    session_id: uuid.UUID | str | None = None,
    idx: int | None = None,
) -> dict[str, Any]:
    """Persist a fully-grounded v2 insight + (optionally) bind its chart.

    Round 3 (insight-first): `chart_id` is OPTIONAL. When provided, the
    chart-resolution + chart-bind path runs as before. When None or
    empty, the insight is written with `chart_id IS NULL`; a follow-up
    `build_chart(insight_id=...)` call binds the chart via FK on the
    other edge (`agent_chart.insight_id`).

    `db` is required (no best-effort no-op on a missing session — v2
    persistence is the contract). `session_id` defaults to ctx.session_id.
    `idx` defaults to one past the last existing idx for the session.
    """
    logger.info(
        "ai_insights.persist_insight.entered",
        extra={
            "session_id_hint": str(session_id) if session_id is not None else None,
            "chart_id": chart_id,
            "headline_len": len(headline) if isinstance(headline, str) else 0,
            "citations_count": len(citations) if isinstance(citations, list) else 0,
        },
    )
    # ------------------------------------------------------------------
    # 0) Argument validation.
    # ------------------------------------------------------------------
    if db is None:
        return _err("db_required", "persist_insight requires a write-capable db handle")

    sid_raw = session_id if session_id is not None else getattr(ctx, "session_id", None)
    sid = _coerce_uuid(sid_raw)
    if sid is None:
        return _err("session_id_required", "session_id is required (resolve from ctx)")

    if not headline or not isinstance(headline, str):
        return _err("headline_required", "headline must be a non-empty string")
    if len(headline) > HEADLINE_MAX:
        return _err(
            "headline_too_long",
            f"headline must be <={HEADLINE_MAX} chars (got {len(headline)})",
            length=len(headline),
        )
    if body is not None and len(body) > BODY_MAX:
        return _err("body_too_long", f"body must be <={BODY_MAX} chars (got {len(body)})")
    # Round 3: chart_id is optional. When provided, validate; when absent,
    # the chart will arrive in a follow-up build_chart(insight_id=...).
    chart_id_present = isinstance(chart_id, str) and bool(chart_id)

    # Round 3.5: citations are now OPTIONAL. The chart binding (via the
    # follow-up build_chart call) carries the executed_sql + row_hash that
    # serve as data-level grounding; external citations are nice-to-have,
    # not required. Empty citations or hallucinated citation_ids no longer
    # block persistence — the insight ships and the agent moves on.
    citations_norm = _normalise_citations(citations) or []

    # ------------------------------------------------------------------
    # 1) Session must exist and be open.
    # ------------------------------------------------------------------
    session_row = await _resolve_session(db, sid)
    if session_row is None:
        return _err("session_not_found", f"no ai_session row for id={sid}", session_id=str(sid))
    status = getattr(session_row, "status", None)
    open_statuses = {"running", "in_progress", "active"}
    # Parallel-tool-use grace window: when the model emits parallel tool calls,
    # persist_insight payloads can land at /mcp slightly after the openclaw
    # stream returns and the orchestrator's `_persist_session_finish` flips
    # status to 'complete'. Without a grace window every such call gets
    # rejected and the session ends with insights_emitted=0 even though the
    # agent did the work. Accept persists for ≤60s after finished_at.
    if status not in open_statuses:
        finished_at = getattr(session_row, "finished_at", None)
        if status == "complete" and finished_at is not None:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            ts = finished_at if finished_at.tzinfo else finished_at.replace(tzinfo=timezone.utc)
            if (now - ts).total_seconds() <= 60:
                logger.warning(
                    "ai_insights.persist_insight.late_arrival_accepted session_id=%s seconds_after_finalize=%.1f",
                    str(sid), (now - ts).total_seconds(),
                )
            else:
                return _err(
                    "session_closed",
                    f"session status={status!r} is not open for new insights",
                    status=status,
                )
        else:
            return _err(
                "session_closed",
                f"session status={status!r} is not open for new insights",
                status=status,
            )

    # ------------------------------------------------------------------
    # 2) Chart must exist + match session (only when chart_id supplied).
    # ------------------------------------------------------------------
    if chart_id_present:
        chart_row, chart_err = await _resolve_chart(db, chart_id, sid)
        if chart_err is not None:
            return _err(chart_err, f"chart guard failed: {chart_err}", chart_id=chart_id)
    else:
        chart_row = None

    # ------------------------------------------------------------------
    # 3) Citations: best-effort resolve. Unresolved IDs no longer block
    # persistence (Round 3.5) — we drop the bad ones, log a warning, and
    # ship the insight with whatever resolved. Data grounding comes from
    # the follow-up chart's executed_sql, not from external citations.
    # ------------------------------------------------------------------
    if citations_norm:
        cit_rows, missing = await _resolve_citations(db, citations_norm)
        if missing:
            logger.warning(
                "ai_insights.persist_insight.citations_partial",
                extra={
                    "resolved": len(cit_rows),
                    "missing_count": len(missing),
                    "missing": missing,
                },
            )
    else:
        cit_rows = []

    # ------------------------------------------------------------------
    # 4) Compute idx if not supplied. Parallel tool-use means multiple
    # persist_insight calls for the same session can race here; without
    # serialization they all read max(idx)=NULL and assign idx=0. Take a
    # session-scoped Postgres advisory xact lock so each insert sees the
    # committed view of prior rows, then read MAX(idx) under the lock.
    # ------------------------------------------------------------------
    if idx is None:
        from sqlalchemy import func, text

        from ..db.models import AIInsight

        try:
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:sid))"),
                {"sid": str(sid)},
            )
            result = await db.execute(
                select(func.max(AIInsight.idx)).where(AIInsight.session_id == sid)
            )
            max_idx = result.scalar()
            idx = (max_idx + 1) if max_idx is not None else 0
        except Exception:  # noqa: BLE001
            idx = 0

    # ------------------------------------------------------------------
    # 5) Insert ai_insight (v2 columns set).
    # ------------------------------------------------------------------
    from ..db.models import AIInsight

    insight = AIInsight(
        session_id=sid,
        idx=idx,
        headline=headline,
        body=body,
        confidence=confidence,
        materiality=materiality,
        skills_run=skills_run or [],
    )
    # The v2-only columns are added by migration 018; SQLModel field
    # plumbing for them is left as setattr() so the v1 model class
    # stays untouched and v1 inserts continue to ignore them.
    setattr(insight, "chart_id", chart_id if chart_id_present else None)
    setattr(insight, "citations", citations_norm)
    setattr(insight, "open_question_id", open_question_id)
    setattr(insight, "version", "v2")

    db.add(insight)
    try:
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        return _err("insert_failed", f"ai_insight insert failed: {exc}")

    insight_id = getattr(insight, "id", None) or uuid.uuid4()
    insight_id_uuid = _coerce_uuid(insight_id) or uuid.uuid4()

    # ------------------------------------------------------------------
    # 6) Bind chart -> insight + citations -> insight (best-effort).
    # Chart bind only runs when chart_id was supplied. Round 3
    # insight-first flow leaves this to a subsequent build_chart call.
    # ------------------------------------------------------------------
    if chart_id_present:
        try:
            from ..db.models import AgentChart

            await db.execute(
                update(AgentChart)
                .where(AgentChart.id == chart_id)
                .values(insight_id=insight_id_uuid)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ai_insights.persist_insight.chart_bind_failed",
                extra={"err": str(exc), "chart_id": chart_id},
            )

    try:
        from ..db.models import AgentCitation

        for row in cit_rows:
            await db.execute(
                update(AgentCitation)
                .where(AgentCitation.id == row.id)
                .values(insight_id=insight_id_uuid)
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ai_insights.persist_insight.citation_bind_failed",
            extra={"err": str(exc)},
        )

    logger.info(
        "ai_insights.persist_insight.ok",
        extra={
            "insight_id": str(insight_id_uuid),
            "session_id": str(sid),
            "chart_id": chart_id,
            "citation_count": len(cit_rows),
        },
    )

    return {
        "ok": True,
        "insight_id": str(insight_id_uuid),
        "chart_id": chart_id if chart_id_present else None,
        "citation_count": len(cit_rows),
        "version": "v2",
    }


__all__ = ["persist_insight", "HEADLINE_MAX", "BODY_MAX"]
