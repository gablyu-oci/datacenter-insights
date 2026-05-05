"""
AI Insights HTTP surface (V1 + V2) -- per ARCHITECTURE.md A3.

Prefix: /api/insights

V1 endpoints implemented:
    POST /api/insights/sessions              SSE stream of typed events
    GET  /api/insights/sessions/{id}         status snapshot
    GET  /api/insights/sessions/{id}/insights list insights for a session
    GET  /api/insights/insights/{id}          insight detail (with chart)
    POST /api/insights/sessions/{id}/cancel   request cancellation

V2 endpoints implemented:
    POST /api/insights/insights/{id}/chat            SSE chat stream
    GET  /api/insights/insights/{id}/chat            paginated thread history
    GET  /api/insights/insights/{id}/citations       list current citations

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

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.insights.orchestrator import InsightOrchestrator
from agents.insights.specs.sse_events import (
    AssistantMessageTokenData,
    AssistantMessageTokenEvent,
    ErrorData,
    ErrorEvent,
    MessageCompleteData,
    MessageCompleteEvent,
    ToolCallCompleteData,
    ToolCallCompleteEvent,
    ToolCallStartedData,
    ToolCallStartedEvent,
    to_sse_text,
)
from agents.insights.db.models import (
    AIInsight,
    AISession,
    AgentChart,
    AgentCitation,
    AgentMessage,
    InsightThread,
)
from db.session import async_session_factory, get_db

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
    version: str = Field(default="v1", pattern=r"^v[12]$")
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


class CancelResponse(BaseModel):
    ok: bool
    status: str


# V2 -------------------------------------------------------------------------


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
# SSE create/stream (V1 sessions endpoint -- unchanged)
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
        version=body.version,
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

    rows = (
        (
            await db.execute(
                select(AIInsight)
                .where(AIInsight.session_id == session_id)
                .order_by(AIInsight.created_at.asc(), AIInsight.idx.asc())
            )
        )
        .scalars()
        .all()
    )

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
        )
        for r in rows
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

    Selection rules (architecture §6):
      1. Look at the 5 most recent sessions (ORDER BY started_at DESC). When
         `include_failed=False` (default), only `status='complete'` rows are
         considered; otherwise rows of any status are considered.
      2. Among rows whose `date(started_at)` matches today's UTC date, prefer
         `created_by='scheduler'` over `'manual'`.
      3. If no row matches today's date, fall back to the single most recent
         row in the candidate set.

    For the chosen session, fetch all `ai_insight` rows ordered by `idx ASC`
    and attach the matching `agent_chart` (LEFT JOIN-style) — mirroring the
    behavior of `GET /api/insights/insights/{id}`.

    When `include_failed=True` and the chosen session has `status='failed'`,
    additionally fetch the most recent completed session (any date) and
    return it as `last_successful: {session, insights}`. For non-failed
    chosen sessions, `last_successful` is `null`.

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
        insight_rows = (
            (
                await db.execute(
                    select(AIInsight)
                    .where(AIInsight.session_id == ai_session_row.id)
                    .order_by(AIInsight.idx.asc())
                )
            )
            .scalars()
            .all()
        )

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

    # Build the candidate query. Default branch keeps the existing
    # `status='complete'` filter so behaviour is byte-identical.
    base_query = select(AISession).order_by(AISession.started_at.desc()).limit(5)
    if not include_failed:
        base_query = (
            select(AISession)
            .where(AISession.status == "complete")
            .order_by(AISession.started_at.desc())
            .limit(5)
        )

    recent_rows = (await db.execute(base_query)).scalars().all()
    if not recent_rows:
        # Wording preserved for back-compat regardless of include_failed.
        raise HTTPException(status_code=404, detail="no completed session yet")

    today = datetime.now(UTC).date()

    def _row_date(s: AISession) -> Optional[Any]:
        return s.started_at.date() if s.started_at is not None else None

    todays = [s for s in recent_rows if _row_date(s) == today]
    chosen: AISession
    if todays:
        scheduler_today = [s for s in todays if (s.created_by or "") == "scheduler"]
        if scheduler_today:
            # Prefer scheduler row; among those, the most recent wins.
            chosen = scheduler_today[0]
        else:
            chosen = todays[0]
    else:
        # No row for today -> most recent in the candidate set.
        chosen = recent_rows[0]

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
# V2: chat + citations
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

    V2 scope is one-thread-per-insight (PRD §5.4 "Per-insight thread").
    Sets `delete_after = now() + 90 days` on insert (retention is in app code
    per the migration comment).
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


def _chat_system_prompt(context: dict[str, Any]) -> str:
    """Compact system prompt giving the chat agent its scope."""
    return (
        "You are the AI Insights chat agent, scoped to ONE specific insight. "
        "You have access to platform tools: query_database, call_api, "
        "get_chart_data, web_search, run_skill, emit_chart, emit_citation. "
        "Use them when a question needs grounding you do not already have. "
        "You may emit additional charts and citations.\n\n"
        "Conversational style:\n"
        " - Treat 'yes', 'sure', 'go ahead' as confirmation of whatever you "
        "just offered. Follow through immediately; do NOT ask for "
        "clarification.\n"
        " - Be terse. Two or three sentences is usually enough.\n"
        " - Skip filler like 'Within this insight context', 'What I can "
        "say, grounded in', 'Important nuance'. Just say the thing.\n"
        " - Do NOT end every response with a bulleted list of follow-up "
        "offers. Offer at most one next step, and only when genuinely "
        "useful.\n"
        " - When you do not know something, say so in one line and stop.\n"
        " - If a question is off-topic for this insight, redirect briefly.\n\n"
        f"INSIGHT CONTEXT (JSON):\n{json.dumps(context, default=str)[:8000]}"
    )


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
    """Chat one turn with the agent scoped to a single insight (V2, SSE).

    Reuses the platform ToolLoopDriver with caps `max_turns=12, max_parallel=4`
    (chat stays at 48 per turn). Web-search counter is shared with the
    parent insight session via the threads table (`web_search_calls`
    cumulative on `ai_insight`).
    """
    db_session = async_session_factory()
    try:
        # Eagerly fetch insight context + thread.
        ctx_payload = await _build_chat_context(db_session, insight_id)
        thread = await _get_or_create_thread(
            db_session, insight_id=insight_id, session_id_hint=None
        )
        thread_id = thread.id
        # Reuse the parent insight's session_id for agent_message FK
        # (agent_message.session_id is NOT NULL per migration 009).
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

    sys_prompt = _chat_system_prompt(ctx_payload)
    user_message = body.message
    assistant_message_id = f"msg_{uuid.uuid4().hex[:12]}"

    # Lazy-imported here to avoid the V1 tools/__init__ side-effects on cold
    # boot (sql_gate may fail to import on broken sqlglot versions; this
    # router's V1 code paths already work and we keep the chat path tolerant).
    from agents.insights.specs.skill_context import Capabilities, SkillContext
    from agents.insights.tool_loop import ToolLoopDriver
    from agents.insights.tools.registry import TOOL_DEFS, dispatch
    from llm.client import MODELS, llm_client  # type: ignore

    # SSE event queue + emitter the SkillContext can publish to.
    event_queue: asyncio.Queue[Any] = asyncio.Queue()

    async def emit_event(evt: Any) -> None:
        await event_queue.put(evt)

    skill_ctx = SkillContext(
        session_id=str(parent_session_id),
        turn_id=f"chat_{uuid.uuid4().hex[:8]}",
        correlation_id=f"chat_{insight_id}_{uuid.uuid4().hex[:8]}",
        model=MODELS["reasoning"],
        budget_seconds_remaining=CHAT_WALL_BUDGET_S,
        capabilities=Capabilities(
            can_query_db=True,
            can_call_api=True,
            can_get_chart_data=True,
            can_emit_chart=True,
            can_emit_citation=True,
            can_web_search=True,
        ),
        thread_id=str(thread_id),
        insight_id=str(insight_id),
        emit_event=emit_event,
    )

    # ToolLoopDriver harness with chat-specific caps.
    async def llm_call(
        messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        turn = await llm_client.reason(
            model=MODELS["reasoning"],
            prompt_version="ai-insights/chat",
            messages=messages,
            tools=tools,
        )
        return {
            "content": turn.content,
            "tool_calls": turn.tool_calls,
            "model": turn.model,
            "tokens": turn.tokens,
        }

    # Wrap dispatch to emit tool_call_started / tool_call_complete events.
    async def chat_dispatch(name: str, args: dict[str, Any], ctx: Any | None) -> Any:
        tcid = f"tc_{uuid.uuid4().hex[:10]}"
        try:
            args_repr = json.dumps(args, default=str)[:200]
        except Exception:  # noqa: BLE001
            args_repr = "<unserialisable>"
        await emit_event(
            ToolCallStartedEvent(
                event_id=f"tcs_{uuid.uuid4().hex[:12]}",
                seq=0,
                data=ToolCallStartedData(
                    thread_id=str(thread_id),
                    tool_call_id=tcid,
                    tool_name=name,
                    args_truncated=args_repr,
                ),
            )
        )
        import time as _time
        t0 = _time.monotonic()
        ok = True
        error_code: str | None = None
        try:
            result = await dispatch(name, args, ctx)
            if isinstance(result, dict) and result.get("ok") is False:
                ok = False
                error_code = str(result.get("error") or "tool_error")
        except Exception as exc:  # noqa: BLE001
            ok = False
            error_code = "dispatch_exception"
            result = {"ok": False, "error": error_code, "detail": str(exc)}
        latency_ms = int((_time.monotonic() - t0) * 1000)
        await emit_event(
            ToolCallCompleteEvent(
                event_id=f"tcc_{uuid.uuid4().hex[:12]}",
                seq=0,
                data=ToolCallCompleteData(
                    thread_id=str(thread_id),
                    tool_call_id=tcid,
                    ok=ok,
                    latency_ms=latency_ms,
                    error_code=error_code,
                ),
            )
        )
        return result

    driver = ToolLoopDriver(
        llm_call=llm_call,
        dispatch=chat_dispatch,
        max_turns=CHAT_MAX_TURNS,
        max_parallel_tool_calls=CHAT_MAX_PARALLEL,
        wall_budget_seconds=CHAT_WALL_BUDGET_S,
    )

    # Load prior thread history so the agent has memory across turns.
    # Without this, "yes" / "go ahead" lose all context. Cap at the last 20
    # messages (10 round-trips) to keep prompt tokens bounded.
    history_rows = (
        (
            await db_session.execute(
                select(AgentMessage)
                .where(AgentMessage.thread_id == thread_id)
                .order_by(AgentMessage.seq.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    history_msgs: list[dict[str, Any]] = []
    for m in reversed(history_rows):
        if m.role not in ("user", "assistant"):
            continue
        if not m.content:
            continue
        history_msgs.append({"role": m.role, "content": m.content})

    initial_messages: list[dict[str, Any]] = [
        {"role": "system", "content": sys_prompt},
        *history_msgs,
        {"role": "user", "content": user_message},
    ]

    async def runner() -> dict[str, Any]:
        return (await driver.run(initial_messages, TOOL_DEFS, ctx=skill_ctx)).__dict__

    runner_task = asyncio.create_task(runner())

    async def gen() -> AsyncIterator[bytes]:
        # Flush queued events as they arrive while the runner is in-flight.
        try:
            while True:
                if await request.is_disconnected():
                    runner_task.cancel()
                    break

                # Pull events with a short timeout so we can also detect the
                # runner's completion in a single loop.
                get_event = asyncio.create_task(event_queue.get())
                done, pending = await asyncio.wait(
                    {get_event, runner_task},
                    timeout=0.5,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if get_event in done:
                    evt = get_event.result()
                    yield to_sse_text(evt).encode("utf-8")
                else:
                    get_event.cancel()

                if runner_task.done() and event_queue.empty():
                    break

            # Drain any final queued events.
            while not event_queue.empty():
                evt = event_queue.get_nowait()
                yield to_sse_text(evt).encode("utf-8")

            try:
                result = await runner_task
            except asyncio.CancelledError:
                result = {"final_content": None, "terminated_reason": "cancelled"}
            except Exception as exc:  # noqa: BLE001
                logger.exception("ai_insights.chat.runner_failed")
                err = ErrorEvent(
                    event_id=f"err_{uuid.uuid4().hex[:12]}",
                    seq=0,
                    data=ErrorData(
                        insight_id=str(insight_id),
                        code="runner_error",
                        message=str(exc),
                        retryable=False,
                    ),
                )
                yield to_sse_text(err).encode("utf-8")
                result = {"final_content": None, "terminated_reason": "error"}

            final_content: str = result.get("final_content") or ""
            terminated_reason: str = result.get("terminated_reason") or "completed"
            finish: str
            if terminated_reason == "completed":
                finish = "stop"
            elif terminated_reason == "turn_budget_exceeded":
                finish = "tool_cap"
            elif terminated_reason == "wall_budget_exceeded":
                finish = "length"
            else:
                finish = "error"

            # Stream the final assistant text as one token event so the UI
            # has a single delta to render. (Llama Stack streaming would
            # emit multiple deltas; this V2 surface defers token-level
            # streaming until the underlying client supports it.)
            if final_content:
                yield to_sse_text(
                    AssistantMessageTokenEvent(
                        event_id=f"amt_{uuid.uuid4().hex[:12]}",
                        seq=0,
                        data=AssistantMessageTokenData(
                            thread_id=str(thread_id),
                            message_id=assistant_message_id,
                            delta=final_content,
                        ),
                    )
                ).encode("utf-8")

            yield to_sse_text(
                MessageCompleteEvent(
                    event_id=f"mco_{uuid.uuid4().hex[:12]}",
                    seq=0,
                    data=MessageCompleteData(
                        thread_id=str(thread_id),
                        message_id=assistant_message_id,
                        finish_reason=finish,  # type: ignore[arg-type]
                    ),
                )
            ).encode("utf-8")

            # Persist the user + assistant messages.
            try:
                # Determine next seq for this thread.
                last_seq = (
                    await db_session.execute(
                        select(AgentMessage.seq)
                        .where(AgentMessage.thread_id == thread_id)
                        .order_by(AgentMessage.seq.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none() or 0
                user_seq = int(last_seq) + 1
                asst_seq = user_seq + 1
                db_session.add(
                    AgentMessage(
                        id=uuid.uuid4(),
                        session_id=parent_session_id,
                        insight_id=insight_id,
                        thread_id=thread_id,
                        seq=user_seq,
                        role="user",
                        content=user_message,
                    )
                )
                db_session.add(
                    AgentMessage(
                        id=uuid.uuid4(),
                        session_id=parent_session_id,
                        insight_id=insight_id,
                        thread_id=thread_id,
                        seq=asst_seq,
                        role="assistant",
                        content=final_content or None,
                        tool_calls=None,
                    )
                )
                # Bump web_search_calls on the insight if any were used.
                ws_used = int(getattr(skill_ctx, "web_search_count", 0) or 0)
                if ws_used:
                    insight_row.web_search_calls = (insight_row.web_search_calls or 0) + ws_used
                    db_session.add(insight_row)
                await db_session.commit()
            except Exception:  # noqa: BLE001
                logger.exception("ai_insights.chat.persist_failed")
                try:
                    await db_session.rollback()
                except Exception:
                    pass
        finally:
            try:
                await db_session.close()
            except Exception:
                pass

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "X-Insight-Thread-Id": str(thread_id),
    }
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


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
    """List current citations for an insight (V2)."""
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


# ---------------------------------------------------------------------------
# Legacy V2 stubs (keep V1 surface stable; the new endpoints above replace
# the per-session/messages stubs as well; the old stub paths return 410 now
# to signal they have moved to /insights/{id}/chat).
# ---------------------------------------------------------------------------


@router.post("/sessions/{session_id}/messages", deprecated=True)
async def post_session_message(session_id: uuid.UUID) -> None:
    raise HTTPException(
        status_code=410,
        detail="V2 chat moved to POST /api/insights/insights/{insight_id}/chat",
    )


@router.get("/sessions/{session_id}/messages", deprecated=True)
async def list_session_messages(session_id: uuid.UUID) -> None:
    raise HTTPException(
        status_code=410,
        detail="V2 chat moved to GET /api/insights/insights/{insight_id}/chat",
    )


@router.post("/citations", deprecated=True)
async def create_citation() -> None:
    raise HTTPException(
        status_code=410,
        detail="Citations are emitted by the agent via emit_citation; manual POST is no longer supported",
    )


__all__ = ["router"]
