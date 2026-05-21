"""AI Insights HTTP surface — per ARCHITECTURE.md A3.

Prefix: /api/insights

Endpoints:
    POST /api/insights/sessions                       SSE stream of typed events
    GET  /api/insights/sessions/{id}                  status snapshot
    GET  /api/insights/sessions/{id}/insights         list insights for a session
    GET  /api/insights/insights/{id}                  insight detail (with chart)
    POST /api/insights/sessions/{id}/cancel           request cancellation
    POST /api/insights/insights/{id}/chat             SSE chat stream
    GET  /api/insights/insights/{id}/chat             paginated thread history
    GET  /api/insights/insights/{id}/citations        list current citations

Latency budget per chat turn: ≤20s p50, ≤45s p95 (PRD §5.4).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.insights.orchestrator import InsightOrchestrator
from agents.insights.specs.sse_events import (
    to_sse_text,
)
from agents.insights.db.models import (
    AIInsight,
    AISession,
    AgentChart,
    AgentCitation,
    AgentMessage,
    InsightSubscription,
    InsightThread,
)
from db.session import async_session_factory, get_db
from config import settings
from openclaw.forwarder import forward_chat as _openclaw_forward_chat

logger = logging.getLogger(__name__)

UTC = timezone.utc


router = APIRouter(prefix="/api/insights", tags=["insights"])


# ---------------------------------------------------------------------------
# In-process session registry (single-worker dev/dogfood, per ARCH A5.1)
# ---------------------------------------------------------------------------

_REPLAY_BUFFER_CAPACITY = 500


class _ActiveSession:
    """Container for orchestrator + tail buffer used by Last-Event-ID resume.

    Also holds a live broadcast queue so the agent can run as a background task
    decoupled from any single SSE client. POST /sessions returns immediately
    with a session_id; the agent fan-outs frames to (a) tail buffer for
    replay/resume and (b) live_queue for the SSE /stream consumer.
    """

    def __init__(self, orch: InsightOrchestrator) -> None:
        self.orch = orch
        # deque of (seq:int, event_id:str, frame_text:str)
        self.tail: deque[tuple[int, str, str]] = deque(maxlen=_REPLAY_BUFFER_CAPACITY)
        # live frame queue for streaming clients; None terminates the stream
        self.live_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        self.completed: bool = False
        self.task: Optional[asyncio.Task] = None

    def remember(self, seq: int, event_id: str, frame_text: str) -> None:
        self.tail.append((seq, event_id, frame_text))

    def replay_after(self, last_event_id: str) -> list[str]:
        """Return wire frames whose event_id appears strictly after `last_event_id`."""
        ids = [eid for (_seq, eid, _f) in self.tail]
        try:
            i = ids.index(last_event_id)
        except ValueError:
            return []
        return [frame for (_, _, frame) in list(self.tail)[i + 1 :]]

    def replay_all(self) -> list[str]:
        """All buffered frames so far (for late connectors with no Last-Event-ID)."""
        return [frame for (_, _, frame) in self.tail]


_active_sessions: dict[uuid.UUID, _ActiveSession] = {}


def _release_session(session_id: uuid.UUID) -> None:
    """Drop a session from the registry; safe to call repeatedly."""
    _active_sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------


class CreateSessionBody(BaseModel):
    focus: Optional[str] = Field(default=None, max_length=240)
    max_insights: int = Field(default=7, ge=5, le=10)
    filters: dict[str, Any] = Field(default_factory=dict)


class SessionStatusResponse(BaseModel):
    id: uuid.UUID
    status: str
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    model: Optional[str]
    focus: Optional[str]
    max_insights: int
    version: str
    insights_emitted: int
    duration_ms: Optional[int]
    budget_status: Optional[str]
    counts: dict[str, int]


class InsightSummary(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    idx: int
    headline: str
    confidence: str
    materiality: str
    skills_run: list[str]
    low_external_support: Optional[bool]
    created_at: Optional[datetime]
    # Save & History (Phase A): present on /sessions/{id}/insights and /latest;
    # left optional for backward compat with older callers.
    is_saved: Optional[bool] = None


class InsightListResponse(BaseModel):
    items: list[InsightSummary]
    total: int


class InsightDetail(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    idx: int
    headline: str
    body: Optional[str]
    confidence: str
    materiality: str
    skills_run: list[str]
    low_external_support: Optional[bool]
    created_at: Optional[datetime]
    chart: Optional[dict[str, Any]] = None
    # Save & History (Phase A); optional for backward compat.
    is_saved: Optional[bool] = None


class CancelResponse(BaseModel):
    ok: bool
    status: str


# ---------------------------------------------------------------------------
# Save & History (Phase A) — Pydantic response shapes
# ---------------------------------------------------------------------------


class SubscribeResponse(BaseModel):
    """Returned by POST/DELETE /api/insights/insights/{insight_id}/subscribe."""

    saved: bool
    id: Optional[uuid.UUID] = None  # subscription row id; None when no row exists


class SavedInsightsResponse(BaseModel):
    """Returned by GET /api/insights/saved.

    `items` mirrors the dict shape used by /latest (id, session_id, idx,
    headline, body, confidence, materiality, skills_run, low_external_support,
    created_at, chart, citations) plus `is_saved=True` and `saved_at`
    (insight_subscription.created_at).
    """

    items: list[dict[str, Any]]
    total: int


class SessionRow(BaseModel):
    """One row in the past-runs list."""

    id: uuid.UUID
    status: str
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    model: Optional[str]
    focus: Optional[str]
    insights_emitted: int
    duration_ms: Optional[int]
    created_by: Optional[str]


class SessionsPage(BaseModel):
    """Returned by GET /api/insights/sessions."""

    items: list[SessionRow]
    limit: int
    offset: int
    total: int
    has_more: bool


# ---------------------------------------------------------------------------
# Save & History (Phase A) — helpers
# ---------------------------------------------------------------------------


def _build_is_saved_column():
    """Correlated EXISTS subquery used as a labeled column on AIInsight selects.

    Returns a SQL expression that evaluates to True when there is at least
    one `insight_subscription` row for the current `ai_insight.id` with
    `enabled=true`. Robust against duplicate subscription rows because EXISTS
    short-circuits on the first match.
    """
    return (
        select(1)
        .where(InsightSubscription.insight_id == AIInsight.id)
        .where(InsightSubscription.enabled.is_(True))
        .exists()
        .label("is_saved")
    )


async def _set_subscription_enabled(
    db: AsyncSession,
    *,
    insight_id: uuid.UUID,
    enabled: bool,
) -> Optional[uuid.UUID]:
    """Soft-upsert the insight_subscription row for `insight_id`.

    Returns the subscription row id when one exists after the call, else None
    (i.e. when caller asked to disable a never-saved insight).

    Idempotency: repeat calls with the same `enabled` value perform no write
    on the second+ invocation. The SELECT uses ORDER BY created_at DESC LIMIT 1
    so it is defensive against duplicate rows (the table lacks a UNIQUE
    constraint on insight_id; see 03-architecture.md §8 / ADR-2).

    Caller is responsible for committing the transaction.
    """
    existing = (
        await db.execute(
            select(InsightSubscription)
            .where(InsightSubscription.insight_id == insight_id)
            .order_by(InsightSubscription.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if existing is None:
        if not enabled:
            # User un-saves an insight that was never saved — no-op.
            return None
        new_row = InsightSubscription(
            id=uuid.uuid4(),
            insight_id=insight_id,
            enabled=True,
        )
        db.add(new_row)
        await db.flush()
        return new_row.id

    if existing.enabled == enabled:
        # Already in the desired state — no write needed.
        return existing.id

    existing.enabled = enabled
    await db.flush()
    return existing.id


# Chat + citations ------------------------------------------------------------


class ChatTurnBody(BaseModel):
    """POST /api/insights/insights/{insight_id}/chat body."""

    message: str = Field(..., min_length=1, max_length=4000)
    last_event_id: Optional[str] = Field(default=None, max_length=64)


class ChatMessageOut(BaseModel):
    id: uuid.UUID
    thread_id: Optional[uuid.UUID]
    seq: int
    role: str
    content: Optional[str]
    tool_calls: Optional[list[dict[str, Any]]]
    created_at: Optional[datetime]


class ChatHistoryResponse(BaseModel):
    thread_id: Optional[uuid.UUID]
    items: list[ChatMessageOut]
    total: int


class CitationOut(BaseModel):
    id: uuid.UUID
    insight_id: uuid.UUID
    url: str
    title: Optional[str]
    snippet: Optional[str]
    agree_or_disagree: Optional[str]
    rationale: Optional[str]
    search_query: Optional[str]
    retrieved_at: Optional[datetime]
    provider: Optional[str]
    created_at: Optional[datetime]


class CitationListResponse(BaseModel):
    items: list[CitationOut]
    total: int


# ---------------------------------------------------------------------------
# SSE create/stream — POST /sessions + GET /sessions/{id}/stream
# ---------------------------------------------------------------------------


async def _run_session_background(
    session_id: uuid.UUID,
    active: _ActiveSession,
    filters: dict[str, Any],
    db_session: AsyncSession,
) -> None:
    """Drive the agent loop, fanning frames into both the tail buffer and the
    live queue so streaming clients can consume them via GET /stream.
    """
    queue = active.live_queue
    try:
        async for event in active.orch.run_session(filters=filters):
            frame = to_sse_text(event)
            seq = getattr(event, "seq", 0)
            event_id = getattr(event, "event_id", "")
            active.remember(seq, event_id, frame)
            await queue.put(frame)

        try:
            await db_session.commit()
        except Exception as commit_exc:
            logger.warning(
                "ai_insights.router.commit_failed",
                extra={"err": str(commit_exc)},
            )
            await db_session.rollback()
    except asyncio.CancelledError:
        active.orch.cancel()
        try:
            await db_session.rollback()
        except Exception:
            pass
    except Exception as exc:
        logger.exception("ai_insights.router.stream_failed")
        err_payload = json.dumps(
            {"code": "stream_error", "message": str(exc), "retryable": False}
        )
        err_frame = f"event: error\ndata: {err_payload}\n\n"
        active.tail.append((0, "", err_frame))
        await queue.put(err_frame)
        try:
            await db_session.rollback()
        except Exception:
            pass
    finally:
        active.completed = True
        await queue.put(None)  # signal end-of-stream
        try:
            await db_session.close()
        except Exception:
            pass


@router.post(
    "/sessions",
    responses={
        200: {"description": "Session created; stream via GET /sessions/{id}/stream"},
        503: {"description": "LLM unavailable"},
    },
)
async def create_session(
    body: CreateSessionBody = Body(default_factory=CreateSessionBody),
):
    """Create a new AI Insights session and kick off the agent in the background.

    Returns JSON with `session_id`. Connect to GET /sessions/{id}/stream to
    receive typed SSE events.
    """
    session_id = uuid.uuid4()

    db_session = async_session_factory()
    orch = InsightOrchestrator(
        session_id=session_id,
        db=db_session,
        max_insights=body.max_insights,
    )
    active = _ActiveSession(orch)
    _active_sessions[session_id] = active

    filters: dict[str, Any] = dict(body.filters)
    if body.focus and "focus" not in filters:
        filters["focus"] = body.focus

    active.task = asyncio.create_task(
        _run_session_background(session_id, active, filters, db_session)
    )

    return {"session_id": str(session_id), "status": "running"}


@router.get(
    "/sessions/{session_id}/stream",
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_session(
    session_id: uuid.UUID,
    request: Request,
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
):
    """Stream typed SSE events for an active session.

    - If `Last-Event-ID` is provided, replays buffered frames after that id, then
      streams live frames.
    - If no Last-Event-ID, replays whatever frames are already buffered (so a
      late client doesn't miss session_started), then streams live.
    - When the agent task finishes, the queue is closed and the stream ends.
    """
    active = _active_sessions.get(session_id)
    if active is None:
        raise HTTPException(status_code=404, detail="session not found or expired")

    async def gen() -> AsyncIterator[bytes]:
        # Replay phase
        if last_event_id:
            for frame in active.replay_after(last_event_id):
                yield frame.encode("utf-8")
        else:
            for frame in active.replay_all():
                yield frame.encode("utf-8")

        # If the agent already finished and we've replayed everything, exit.
        if active.completed and active.live_queue.empty():
            return

        # Live phase: drain the queue
        while True:
            if await request.is_disconnected():
                active.orch.cancel()
                return
            try:
                frame = await asyncio.wait_for(active.live_queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield b": keepalive\n\n"
                continue
            if frame is None:  # end-of-stream sentinel
                return
            yield frame.encode("utf-8")

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "X-Insight-Session-Id": str(session_id),
    }
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


# ---------------------------------------------------------------------------
# Session status snapshot
# ---------------------------------------------------------------------------


@router.get("/sessions/{session_id}", response_model=SessionStatusResponse)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SessionStatusResponse:
    row = (
        await db.execute(select(AISession).where(AISession.id == session_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")

    insight_count = (
        await db.execute(
            select(AIInsight).where(AIInsight.session_id == session_id)
        )
    ).scalars().all()
    chart_count = (
        await db.execute(
            select(AgentChart).where(AgentChart.session_id == session_id)
        )
    ).scalars().all()

    return SessionStatusResponse(
        id=row.id,
        status=row.status,
        started_at=row.started_at,
        ended_at=row.finished_at,
        model=row.model,
        focus=row.focus,
        max_insights=row.max_insights,
        version=row.version,
        insights_emitted=row.insights_emitted,
        duration_ms=row.duration_ms,
        budget_status=row.budget_status,
        counts={
            "insights": len(insight_count),
            "charts": len(chart_count),
        },
    )


@router.get(
    "/sessions/{session_id}/insights",
    response_model=InsightListResponse,
)
async def list_session_insights(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> InsightListResponse:
    sess = (
        await db.execute(select(AISession).where(AISession.id == session_id))
    ).scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")

    saved_expr = _build_is_saved_column()
    rows = (
        await db.execute(
            select(AIInsight, saved_expr)
            .where(AIInsight.session_id == session_id)
            .order_by(AIInsight.created_at.asc(), AIInsight.idx.asc())
        )
    ).all()

    items = [
        InsightSummary(
            id=r.id,
            session_id=r.session_id,
            idx=r.idx,
            headline=r.headline,
            confidence=r.confidence,
            materiality=r.materiality,
            skills_run=r.skills_run or [],
            low_external_support=r.low_external_support,
            created_at=r.created_at,
            is_saved=bool(is_saved_val),
        )
        for (r, is_saved_val) in rows
    ]
    return InsightListResponse(items=items, total=len(items))


@router.get("/insights/{insight_id}", response_model=InsightDetail)
async def get_insight(
    insight_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> InsightDetail:
    row = (
        await db.execute(select(AIInsight).where(AIInsight.id == insight_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="insight not found")

    chart_row = (
        await db.execute(
            select(AgentChart).where(AgentChart.insight_id == insight_id)
        )
    ).scalar_one_or_none()

    chart_payload: Optional[dict[str, Any]] = None
    if chart_row is not None:
        chart_payload = {
            "chart_id": chart_row.id,
            "spec": chart_row.spec,
            "data_source": chart_row.data_source,
            "row_hash": chart_row.row_hash,
            "created_at": chart_row.created_at,
        }

    # Save & History (Phase A): does an enabled subscription exist?
    is_saved_val = (
        await db.execute(
            select(
                select(1)
                .where(InsightSubscription.insight_id == insight_id)
                .where(InsightSubscription.enabled.is_(True))
                .exists()
            )
        )
    ).scalar()

    return InsightDetail(
        id=row.id,
        session_id=row.session_id,
        idx=row.idx,
        headline=row.headline,
        body=row.body,
        confidence=row.confidence,
        materiality=row.materiality,
        skills_run=row.skills_run or [],
        low_external_support=row.low_external_support,
        created_at=row.created_at,
        chart=chart_payload,
        is_saved=bool(is_saved_val),
    )


@router.post(
    "/sessions/{session_id}/cancel",
    response_model=CancelResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_session(session_id: uuid.UUID) -> CancelResponse:
    active = _active_sessions.get(session_id)
    if active is None:
        raise HTTPException(status_code=404, detail="session not active")
    active.orch.cancel()
    return CancelResponse(ok=True, status="cancelled")


# ===========================================================================
# Save & History (Phase A) — subscribe toggle, saved list, sessions history
# ===========================================================================


@router.post(
    "/insights/{insight_id}/subscribe",
    response_model=SubscribeResponse,
)
async def subscribe_insight(
    insight_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SubscribeResponse:
    """Mark an insight as saved (idempotent soft-upsert)."""
    insight = (
        await db.execute(select(AIInsight.id).where(AIInsight.id == insight_id))
    ).scalar_one_or_none()
    if insight is None:
        raise HTTPException(status_code=404, detail="insight not found")

    row_id = await _set_subscription_enabled(
        db, insight_id=insight_id, enabled=True
    )
    await db.commit()
    return SubscribeResponse(saved=True, id=row_id)


@router.delete(
    "/insights/{insight_id}/subscribe",
    response_model=SubscribeResponse,
)
async def unsubscribe_insight(
    insight_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SubscribeResponse:
    """Soft-delete the saved state (flip enabled=false; idempotent)."""
    insight = (
        await db.execute(select(AIInsight.id).where(AIInsight.id == insight_id))
    ).scalar_one_or_none()
    if insight is None:
        raise HTTPException(status_code=404, detail="insight not found")

    await _set_subscription_enabled(db, insight_id=insight_id, enabled=False)
    await db.commit()
    return SubscribeResponse(saved=False, id=None)


@router.get(
    "/saved",
    response_model=SavedInsightsResponse,
)
async def list_saved_insights(
    limit: int = Query(default=100, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> SavedInsightsResponse:
    """List currently-saved insights, newest-saved first (hard cap 100)."""
    # Single JOIN query: subscription → insight, only enabled rows.
    sub_rows = (
        await db.execute(
            select(InsightSubscription, AIInsight)
            .join(AIInsight, AIInsight.id == InsightSubscription.insight_id)
            .where(InsightSubscription.enabled.is_(True))
            .order_by(InsightSubscription.created_at.desc())
            .limit(limit)
        )
    ).all()

    if not sub_rows:
        return SavedInsightsResponse(items=[], total=0)

    insight_ids = [ins.id for (_sub, ins) in sub_rows]

    # Bulk-load charts + citations exactly as /latest does (no N+1).
    chart_rows = (
        (
            await db.execute(
                select(AgentChart).where(AgentChart.insight_id.in_(insight_ids))
            )
        )
        .scalars()
        .all()
    )
    charts_by_insight: dict[uuid.UUID, AgentChart] = {
        c.insight_id: c for c in chart_rows
    }

    citation_rows = (
        (
            await db.execute(
                select(AgentCitation)
                .where(AgentCitation.insight_id.in_(insight_ids))
                .order_by(AgentCitation.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    citations_by_insight: dict[uuid.UUID, list[AgentCitation]] = {}
    for cit in citation_rows:
        citations_by_insight.setdefault(cit.insight_id, []).append(cit)

    items: list[dict[str, Any]] = []
    for sub, ins in sub_rows:
        chart_row = charts_by_insight.get(ins.id)
        chart_payload: Optional[dict[str, Any]] = None
        if chart_row is not None:
            chart_payload = {
                "chart_id": chart_row.id,
                "spec": chart_row.spec,
                "data_source": chart_row.data_source,
                "row_hash": chart_row.row_hash,
                "created_at": chart_row.created_at.isoformat()
                if chart_row.created_at
                else None,
            }
        citation_payload = [
            {
                "id": str(cit.id),
                "url": cit.url,
                "title": cit.title,
                "snippet": cit.snippet,
                "search_query": cit.search_query,
                "provider": cit.provider,
                "agree_or_disagree": cit.agree_or_disagree,
            }
            for cit in citations_by_insight.get(ins.id, [])
        ]
        items.append(
            {
                "id": str(ins.id),
                "session_id": str(ins.session_id),
                "idx": ins.idx,
                "headline": ins.headline,
                "body": ins.body,
                "confidence": ins.confidence,
                "materiality": ins.materiality,
                "skills_run": ins.skills_run or [],
                "low_external_support": ins.low_external_support,
                "created_at": ins.created_at.isoformat()
                if ins.created_at
                else None,
                "chart": chart_payload,
                "citations": citation_payload,
                "is_saved": True,
                "saved_at": sub.created_at.isoformat() if sub.created_at else None,
            }
        )

    return SavedInsightsResponse(items=items, total=len(items))


# Status alias map: request-side "completed" -> DB-side "complete" (singular).
_STATUS_ALIAS: dict[str, Optional[str]] = {
    "completed": "complete",
    "complete": "complete",
    "cancelled": "cancelled",
    "failed": "failed",
    "all": None,  # sentinel → no filter
}


@router.get(
    "/sessions",
    response_model=SessionsPage,
)
async def list_sessions_history(
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default="completed"),
    db: AsyncSession = Depends(get_db),
) -> SessionsPage:
    """Paginated history of past sessions (insights are NOT inlined)."""
    if status not in _STATUS_ALIAS:
        raise HTTPException(
            status_code=400,
            detail=f"invalid status '{status}'; expected one of "
            f"{sorted(_STATUS_ALIAS.keys())}",
        )
    db_status = _STATUS_ALIAS[status]

    list_stmt = select(AISession).order_by(AISession.started_at.desc())
    count_stmt = select(func.count()).select_from(AISession)
    if db_status is not None:
        list_stmt = list_stmt.where(AISession.status == db_status)
        count_stmt = count_stmt.where(AISession.status == db_status)

    list_stmt = list_stmt.limit(limit).offset(offset)

    rows = (await db.execute(list_stmt)).scalars().all()
    total = (await db.execute(count_stmt)).scalar_one() or 0

    items = [
        SessionRow(
            id=r.id,
            status=r.status,
            started_at=r.started_at,
            finished_at=r.finished_at,
            model=r.model,
            focus=r.focus,
            insights_emitted=r.insights_emitted or 0,
            duration_ms=r.duration_ms,
            created_by=r.created_by,
        )
        for r in rows
    ]
    has_more = (offset + len(items)) < int(total)
    return SessionsPage(
        items=items,
        limit=limit,
        offset=offset,
        total=int(total),
        has_more=has_more,
    )


# ---------------------------------------------------------------------------
# Latest completed session (architecture §6 — /api/insights/latest contract)
# ---------------------------------------------------------------------------


@router.get(
    "/latest",
    responses={
        200: {"description": "Most recent completed session + its insights"},
        404: {"description": "No completed session exists yet"},
    },
)
async def get_latest_insights(
    include_failed: bool = False,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the most recent AI Insights session and its insights.

    Selection:
      * `include_failed=False` (default): the single most-recent session
        with `status='complete'`.
      * `include_failed=True`: the single most-recent session of any
        status. When that row is `status='failed'`, additionally fetch
        the most recent completed session and return it as
        `last_successful: {session, insights}`; otherwise `last_successful`
        is `null`.

    For the chosen session, fetch all `ai_insight` rows ordered by `idx
    ASC` and attach the matching `agent_chart` (LEFT JOIN-style) —
    mirroring the behavior of `GET /api/insights/insights/{id}`.

    Returns 404 with detail "no completed session yet" when no candidate
    session exists. (Wording preserved for back-compat.)
    """

    async def _build_session_payload(
        db: AsyncSession, ai_session_row: AISession
    ) -> dict[str, Any]:
        """Build the `{session, insights}` payload for a given AISession row.

        Mirrors the original handler logic: insights are ordered by `idx ASC`
        and any matching `agent_chart` rows are LEFT-JOINed onto each insight.
        Returns an empty `insights` list if the session has no rows (which is
        expected for `running` / `failed` / `cancelled` sessions).
        """
        saved_expr = _build_is_saved_column()
        insight_pairs = (
            await db.execute(
                select(AIInsight, saved_expr)
                .where(AIInsight.session_id == ai_session_row.id)
                .order_by(AIInsight.idx.asc())
            )
        ).all()
        insight_rows = [ins for (ins, _is_saved) in insight_pairs]
        saved_flag_by_id: dict[uuid.UUID, bool] = {
            ins.id: bool(is_saved_val) for (ins, is_saved_val) in insight_pairs
        }

        charts_by_insight: dict[uuid.UUID, AgentChart] = {}
        citations_by_insight: dict[uuid.UUID, list[AgentCitation]] = {}
        if insight_rows:
            chart_rows = (
                (
                    await db.execute(
                        select(AgentChart).where(
                            AgentChart.session_id == ai_session_row.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for c in chart_rows:
                charts_by_insight[c.insight_id] = c

            insight_ids = [ins.id for ins in insight_rows]
            citation_rows = (
                (
                    await db.execute(
                        select(AgentCitation)
                        .where(AgentCitation.insight_id.in_(insight_ids))
                        .order_by(AgentCitation.created_at.asc())
                    )
                )
                .scalars()
                .all()
            )
            for cit in citation_rows:
                citations_by_insight.setdefault(cit.insight_id, []).append(cit)

        insights_payload: list[dict[str, Any]] = []
        for ins in insight_rows:
            chart_row = charts_by_insight.get(ins.id)
            chart_payload: Optional[dict[str, Any]] = None
            if chart_row is not None:
                chart_payload = {
                    "chart_id": chart_row.id,
                    "spec": chart_row.spec,
                    "data_source": chart_row.data_source,
                    "row_hash": chart_row.row_hash,
                    "created_at": chart_row.created_at.isoformat()
                    if chart_row.created_at
                    else None,
                }
            citation_payload = [
                {
                    "id": str(cit.id),
                    "url": cit.url,
                    "title": cit.title,
                    "snippet": cit.snippet,
                    "search_query": cit.search_query,
                    "provider": cit.provider,
                    "agree_or_disagree": cit.agree_or_disagree,
                }
                for cit in citations_by_insight.get(ins.id, [])
            ]
            insights_payload.append(
                {
                    "id": str(ins.id),
                    "session_id": str(ins.session_id),
                    "idx": ins.idx,
                    "headline": ins.headline,
                    "body": ins.body,
                    "confidence": ins.confidence,
                    "materiality": ins.materiality,
                    "skills_run": ins.skills_run or [],
                    "low_external_support": ins.low_external_support,
                    "created_at": ins.created_at.isoformat()
                    if ins.created_at
                    else None,
                    "chart": chart_payload,
                    "citations": citation_payload,
                    "is_saved": saved_flag_by_id.get(ins.id, False),
                }
            )

        session_payload = {
            "id": str(ai_session_row.id),
            "status": ai_session_row.status,
            "started_at": ai_session_row.started_at.isoformat()
            if ai_session_row.started_at
            else None,
            "ended_at": ai_session_row.finished_at.isoformat()
            if ai_session_row.finished_at
            else None,
            "model": ai_session_row.model,
            "focus": ai_session_row.focus,
            "max_insights": ai_session_row.max_insights,
            "insights_emitted": ai_session_row.insights_emitted,
            "duration_ms": ai_session_row.duration_ms,
            "budget_status": ai_session_row.budget_status,
            "created_by": ai_session_row.created_by,
            "version": ai_session_row.version,
        }

        return {"session": session_payload, "insights": insights_payload}

    # Pick the most recent session. `include_failed=False` filters to
    # complete; `include_failed=True` accepts any status (failed rows
    # get a `last_successful` companion below).
    base_query = (
        select(AISession).order_by(AISession.started_at.desc()).limit(1)
    )
    if not include_failed:
        base_query = (
            select(AISession)
            .where(AISession.status == "complete")
            .order_by(AISession.started_at.desc())
            .limit(1)
        )

    chosen = (await db.execute(base_query)).scalars().first()
    if chosen is None:
        # Wording preserved for back-compat regardless of include_failed.
        raise HTTPException(status_code=404, detail="no completed session yet")

    primary = await _build_session_payload(db, chosen)

    # Default branch: byte-identical legacy response shape (no last_successful key).
    if not include_failed:
        return {
            "session": primary["session"],
            "insights": primary["insights"],
            "started_at": primary["session"]["started_at"],
            "status": chosen.status,
        }

    # include_failed=True branch: attach last_successful when the chosen
    # session is failed, else None.
    last_successful: Optional[dict[str, Any]] = None
    if chosen.status == "failed":
        prior_complete = (
            (
                await db.execute(
                    select(AISession)
                    .where(AISession.status == "complete")
                    .order_by(AISession.started_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if prior_complete is not None:
            last_successful = await _build_session_payload(db, prior_complete)

    return {
        "session": primary["session"],
        "insights": primary["insights"],
        "started_at": primary["session"]["started_at"],
        "status": chosen.status,
        "last_successful": last_successful,
    }


# ===========================================================================
# Chat + citations
# ===========================================================================


CHAT_THREAD_RETENTION_DAYS = 90
CHAT_MAX_TURNS = 12  # 12 x 4 = 48 (PRD §5.4)
CHAT_MAX_PARALLEL = 4
CHAT_WALL_BUDGET_S = 45.0  # p95 latency budget per turn (PRD §5.4)
CHAT_HISTORY_LIMIT = 50


def _now_utc() -> datetime:
    # tz-naive to match SQLModel columns (default_factory=datetime.utcnow).
    # The DB columns are timestamptz, but asyncpg picks the encoder from the
    # SQLAlchemy column type, which is naive — passing tz-aware crashes.
    return datetime.utcnow()


async def _get_or_create_thread(
    db: AsyncSession,
    *,
    insight_id: uuid.UUID,
    session_id_hint: Optional[str] = None,
) -> InsightThread:
    """Return the (single) chat thread for an insight, creating it if missing.

    Scope is one-thread-per-insight (PRD §5.4 "Per-insight thread").
    Sets `delete_after = now() + 90 days` on insert (retention is in app
    code per the migration comment).
    """
    existing = (
        await db.execute(
            select(InsightThread).where(InsightThread.insight_id == insight_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.last_active = _now_utc()
        await db.flush()
        return existing

    now = _now_utc()
    thread = InsightThread(
        id=uuid.uuid4(),
        insight_id=insight_id,
        session_id=session_id_hint,
        created_at=now,
        last_active=now,
        delete_after=now + timedelta(days=CHAT_THREAD_RETENTION_DAYS),
    )
    db.add(thread)
    await db.flush()
    return thread


async def _build_chat_context(
    db: AsyncSession, insight_id: uuid.UUID
) -> dict[str, Any]:
    """Assemble the always-in-context payload per PRD §5.4.

    Headline + body + compact chart spec + citations + the chart's
    data-source spec. Other insights' threads are not included.
    """
    insight_row = (
        await db.execute(select(AIInsight).where(AIInsight.id == insight_id))
    ).scalar_one_or_none()
    if insight_row is None:
        raise HTTPException(status_code=404, detail="insight not found")

    chart_row = (
        await db.execute(
            select(AgentChart).where(AgentChart.insight_id == insight_id)
        )
    ).scalar_one_or_none()

    citation_rows = (
        (
            await db.execute(
                select(AgentCitation)
                .where(AgentCitation.insight_id == insight_id)
                .order_by(AgentCitation.created_at.asc())
            )
        )
        .scalars()
        .all()
    )

    chart_compact: dict[str, Any] | None = None
    if chart_row is not None:
        spec = chart_row.spec or {}
        chart_compact = {
            "chart_id": chart_row.id,
            "type": spec.get("type"),
            "title": spec.get("title"),
            "subtitle": spec.get("subtitle"),
            "encoding": spec.get("encoding"),
            "data_source": chart_row.data_source,
        }

    citations = [
        {
            "url": c.url,
            "title": c.title,
            "snippet": c.snippet,
            "agree_or_disagree": c.agree_or_disagree,
            "rationale": c.rationale,
        }
        for c in citation_rows
    ]

    return {
        "insight_id": str(insight_id),
        "headline": insight_row.headline,
        "body": insight_row.body,
        "skills_run": insight_row.skills_run or [],
        "confidence": insight_row.confidence,
        "materiality": insight_row.materiality,
        "chart": chart_compact,
        "citations": citations,
    }


@router.post(
    "/insights/{insight_id}/chat",
    responses={
        200: {"content": {"text/event-stream": {}}},
        404: {"description": "Insight not found"},
    },
)
async def post_insight_chat(
    insight_id: uuid.UUID,
    request: Request,
    body: ChatTurnBody = Body(...),
):
    """Per-insight chat endpoint (PRD/ARCH 11b §5.1, ARCH 15 §3).

    All chat traffic flows through the OpenClaw gateway lane. The
    legacy in-process ToolLoopDriver handler was removed in
    Phase 5-followup (ARCH 15) once OpenClaw had carried 100% of
    chat traffic in production. The frontend wire contract is
    unchanged.
    """
    return await _openclaw_chat_handler(insight_id, request, body)


# ---------------------------------------------------------------------------
# OpenClaw chat lane (PRD 11a, ARCH 11b §5.2, ADDENDUM 11c §B)
# ---------------------------------------------------------------------------


async def _openclaw_chat_handler(
    insight_id: uuid.UUID,
    request: Request,
    body: ChatTurnBody,
):
    """OpenClaw lane: forward the user turn through the OpenClaw gateway.

    The user message is persisted BEFORE we dial OpenClaw so the audit
    trail survives a gateway outage. The streaming SSE response is
    produced by `backend.openclaw.forwarder.forward_chat`, which
    translates OpenClaw chunks into our existing event taxonomy. The
    frontend wire contract is unchanged (PRD R5).
    """
    db_session = async_session_factory()
    try:
        # Resolve insight, thread, and parent session up front so we can
        # 404 deterministically before kicking off any streaming. This
        # mirrors the legacy handler's prelude.
        ctx_payload = await _build_chat_context(db_session, insight_id)  # noqa: F841
        thread = await _get_or_create_thread(
            db_session, insight_id=insight_id, session_id_hint=None
        )
        thread_id = thread.id
        insight_row = (
            await db_session.execute(
                select(AIInsight).where(AIInsight.id == insight_id)
            )
        ).scalar_one()
        parent_session_id = insight_row.session_id
        await db_session.commit()
    except HTTPException:
        await db_session.close()
        raise
    except Exception:
        await db_session.close()
        raise

    user_text = body.message

    async def _stream() -> AsyncIterator[bytes]:
        try:
            async for chunk in _openclaw_forward_chat(
                insight_id=insight_id,
                user_text=user_text,
                db=db_session,
                thread_id=thread_id,
                session_id=parent_session_id,
            ):
                if await request.is_disconnected():
                    break
                yield chunk
        finally:
            try:
                await db_session.close()
            except Exception:  # noqa: BLE001
                pass

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "X-Insight-Thread-Id": str(thread_id),
    }
    return StreamingResponse(_stream(), media_type="text/event-stream", headers=headers)


@router.get(
    "/insights/{insight_id}/chat",
    response_model=ChatHistoryResponse,
)
async def get_insight_chat(
    insight_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ChatHistoryResponse:
    """Return paginated thread history (last 50 messages) for an insight."""
    insight = (
        await db.execute(select(AIInsight).where(AIInsight.id == insight_id))
    ).scalar_one_or_none()
    if insight is None:
        raise HTTPException(status_code=404, detail="insight not found")

    thread = (
        await db.execute(
            select(InsightThread).where(InsightThread.insight_id == insight_id)
        )
    ).scalar_one_or_none()
    if thread is None:
        return ChatHistoryResponse(thread_id=None, items=[], total=0)

    rows = (
        (
            await db.execute(
                select(AgentMessage)
                .where(AgentMessage.thread_id == thread.id)
                .order_by(AgentMessage.seq.desc())
                .limit(CHAT_HISTORY_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    rows = list(reversed(rows))

    items = [
        ChatMessageOut(
            id=r.id,
            thread_id=r.thread_id,
            seq=r.seq,
            role=r.role,
            content=r.content,
            tool_calls=r.tool_calls,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return ChatHistoryResponse(thread_id=thread.id, items=items, total=len(items))


@router.get(
    "/insights/{insight_id}/citations",
    response_model=CitationListResponse,
)
async def list_insight_citations(
    insight_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> CitationListResponse:
    """List current citations for an insight."""
    insight = (
        await db.execute(select(AIInsight).where(AIInsight.id == insight_id))
    ).scalar_one_or_none()
    if insight is None:
        raise HTTPException(status_code=404, detail="insight not found")

    rows = (
        (
            await db.execute(
                select(AgentCitation)
                .where(AgentCitation.insight_id == insight_id)
                .order_by(AgentCitation.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    items = [
        CitationOut(
            id=r.id,
            insight_id=r.insight_id,
            url=r.url,
            title=r.title,
            snippet=r.snippet,
            agree_or_disagree=r.agree_or_disagree,
            rationale=r.rationale,
            search_query=r.search_query,
            retrieved_at=r.retrieved_at,
            provider=r.provider,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return CitationListResponse(items=items, total=len(items))


__all__ = ["router"]
