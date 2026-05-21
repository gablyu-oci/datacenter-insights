"""InsightOrchestrator — multi-insight session driver.

Two phases per session:

    1. Bootstrap — call_api against fixed survey endpoints (cap 8 calls).
    2. Synthesize — delegate to the agentic synthesis driver
       (`agentic_synthesis.run_agentic_synthesis`). The driver streams
       insights through OpenClaw + MCP write-tools and emits SSE events
       back into this generator's event queue. The agent orients via
       `read_workspace` (SCHEMA.md / FRESHNESS.md / playbook) and grounds
       claims with `search_documents` + `query_database`.

Caps (PRD §5.1, ARCH A10):
    - 40 tool calls per session
    - 480 s wall-clock per session
    - Inner agentic caps (12 turns / 30 tool calls / 600 s) live in
      `agentic_synthesis` and `openclaw.forwarder._drive_openclaw_stream`.
    - No recursive run_skill (enforced in tools/run_skill.py)

SSE event taxonomy: see specs/sse_events.py. The orchestrator yields
concrete `_SSEBase` subclasses; the router serialises with
`to_sse_text(event)`.

Persistence covers:
    - ai_session                   — top-level run record
    - ai_insight                   — one row per emitted insight (written
      by the `persist_insight` MCP write-tool)
    - agent_chart                  — one row per emitted chart
    - agent_message                — assistant/tool transcript + SSE replay
    - agent_tool_call              — per tool dispatch
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from .dedup import is_duplicate
from .specs.chart_spec import ChartSpec
from .specs.skill_context import Capabilities, SkillContext
from .specs.sse_events import (
    ChartEvent,
    ChartEventData,
    ErrorData,
    ErrorEvent,
    InsightCompleteData,
    InsightCompleteEvent,
    InsightStartedData,
    InsightStartedEvent,
    PingEvent,
    SessionCompleteData,
    SessionCompleteEvent,
    SessionStartedData,
    SessionStartedEvent,
    SurveyingData,
    SurveyingEvent,
    ToolCallData,
    ToolCallEvent,
    ToolResultData,
    ToolResultEvent,
    _SSEBase,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session caps (PRD §5.1)
# ---------------------------------------------------------------------------

TOOL_CALL_CAP = 40
WALL_CLOCK_S = 480.0              # 8 minutes
BOOTSTRAP_SURVEY_CAP = 8
MIN_INSIGHTS = 5
MAX_INSIGHTS = 10
REASONING_MODEL = "oci/openai.gpt-5.4"   # mirrors LlmClient default


# Fixed survey endpoints (from ARCH A6.3 + A8.1). Capped at 8 calls.
SURVEY_ENDPOINTS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("/api/power/gw-summary", {}),
    ("/api/power/timeseries", {"days": 180}),
    ("/api/triangulation/l1", {}),
    ("/api/triangulation/l2", {}),
    ("/api/anomalies/recent", {}),
    ("/api/companies/top", {"metric": "gw", "limit": 50}),
    ("/api/permits/building", {"days": 180}),
    ("/api/coverage/freshness", {}),
)
assert len(SURVEY_ENDPOINTS) <= BOOTSTRAP_SURVEY_CAP


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _now_event_id() -> str:
    return uuid.uuid4().hex[:16]


def _short_chart_id() -> str:
    return f"c_{uuid.uuid4().hex[:8]}"


def _truncate_args(args: Any, max_len: int = 200) -> str:
    try:
        text = json.dumps(args, default=str, separators=(",", ":"))
    except Exception:
        text = str(args)
    return text[: max_len - 1] + "…" if len(text) > max_len else text


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class InsightOrchestrator:
    """Drives a single AI Insights session, emitting typed SSE events.

    Usage::

        orch = InsightOrchestrator(session_id, db, llm)
        async for event in orch.run_session(filters={...}):
            yield to_sse_text(event)
    """

    def __init__(
        self,
        session_id: uuid.UUID,
        db: AsyncSession | None,
        llm: Any | None = None,
        *,
        max_insights: int = 7,
        model: str = REASONING_MODEL,
    ) -> None:
        self.session_id = session_id
        self.db = db
        self.llm = llm  # LLMAdapter-shape; optional for unit tests
        self.max_insights = max(MIN_INSIGHTS, min(MAX_INSIGHTS, max_insights))
        self.model = model

        # Caps + run state
        self._tool_calls_used = 0
        self._started_monotonic = 0.0
        self._cancel_event = asyncio.Event()
        self._seq = 0
        self._terminated = False
        # Headlines emitted in this session, with embeddings — for novelty dedup.
        self._emitted_headlines: list[tuple[str, list[float]]] = []
        self._emitted_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """Flip the cancellation flag.

        The run loop checks `_cancel_event` between iterations and at
        every tool dispatch boundary. On trip the loop emits
        `session_terminated` (modelled here as a final `session_complete`
        with `budget_status='clipped'` plus an `error` event with code
        `cancelled`, per ARCH A13).
        """
        self._cancel_event.set()

    async def run_session(
        self, filters: dict[str, Any] | None = None
    ) -> AsyncIterator[_SSEBase]:
        """Drive one session and yield SSE events.

        On any uncaught exception emits an `error` + `session_complete`
        with budget_status='clipped' before propagating control back to
        the caller.
        """
        self._started_monotonic = time.monotonic()
        filters = filters or {}

        try:
            # --- session_started -------------------------------------
            yield self._build_event(
                SessionStartedEvent,
                SessionStartedData(
                    session_id=str(self.session_id),
                    model=self.model,
                    started_at=_utcnow(),
                    max_insights=self.max_insights,
                ),
            )
            await self._persist_session_start(filters)

            # Phase 2 (D8): prime _emitted_headlines with the last 14 days
            # of successful AIInsight rows that already carry an embedding.
            # Best-effort — a failure (e.g. pgvector missing in a test DB)
            # logs a warning and falls back to an empty prior list, which
            # degrades gracefully to in-session-only dedup.
            await self._prime_cross_day_dedup()

            if self._cancel_event.is_set():
                async for ev in self._terminate("cancelled", "session cancelled before start"):
                    yield ev
                return

        except StopAsyncIteration:
            # Defensive — should not normally happen here.
            return
        except Exception:
            # Fall through to a generic error path; never hide the trace.
            logger.exception("ai_insights.orchestrator.unexpected_in_setup")
            async for ev in self._terminate("error", "unexpected error during session setup"):
                yield ev
            return

        # The above exits early on cancel; below is the streaming body.
        try:
            async for ev in self._phase_bootstrap_iter():
                yield ev
                if self._cancel_event.is_set():
                    async for term in self._terminate("cancelled", "session cancelled during bootstrap"):
                        yield term
                    return

            # The agent orients via read_workspace(SCHEMA.md /
            # FRESHNESS.md / playbook) and grounds claims with
            # search_documents + query_database.

            # Lazy import to avoid a hard dependency at import time
            # (agentic_synthesis pulls in openclaw.forwarder which
            # imports httpx; keeping this lazy preserves the ability
            # to import the orchestrator from minimal envs).
            from .agentic_synthesis import (  # noqa: F401
                SynthesisRunError,
                run_agentic_synthesis,
            )

            # Bridge the agentic loop's `sse_emit` callback into our
            # async-generator stream via an asyncio.Queue. The driver
            # task pushes events; this generator drains them while
            # also watching for cancel + driver completion.
            event_queue: asyncio.Queue[_SSEBase] = asyncio.Queue()
            _SENTINEL: object = object()

            async def _sse_emit(evt: _SSEBase) -> None:
                await event_queue.put(evt)

            cron_run_date = filters.get("cron_run_date") if filters else None

            async def _driver() -> None:
                try:
                    await run_agentic_synthesis(
                        session_id=self.session_id,
                        max_insights=self.max_insights,
                        db=self.db,
                        sse_emit=_sse_emit,
                        cron_run_date=cron_run_date,
                        mode="manual",
                    )
                except SynthesisRunError as exc:
                    logger.warning(
                        "ai_insights.orchestrator.agentic_run_error",
                        extra={"err": str(exc)},
                    )
                except Exception:
                    logger.exception(
                        "ai_insights.orchestrator.agentic_unexpected"
                    )
                finally:
                    await event_queue.put(_SENTINEL)  # type: ignore[arg-type]

            driver_task = asyncio.create_task(_driver())

            try:
                while True:
                    item = await event_queue.get()
                    if item is _SENTINEL:
                        break
                    yield item  # type: ignore[misc]
                    if self._cancel_event.is_set():
                        # Cooperative: do NOT cancel the driver task —
                        # let it drain naturally; emit terminate now.
                        async for term in self._terminate(
                            "cancelled",
                            "session cancelled during synthesize",
                        ):
                            yield term
                        # Best-effort: wait for the driver so the
                        # asyncio task does not leak; the agentic
                        # loop's own cap-checks will close out.
                        try:
                            await driver_task
                        except Exception:  # noqa: BLE001
                            pass
                        return
            finally:
                if not driver_task.done():
                    try:
                        await driver_task
                    except Exception:  # noqa: BLE001
                        pass

            # Agentic path emits session_complete via the synthesis
            # SSE translator (finalize_session MCP tool). Skip the
            # orchestrator-level session_complete to avoid a double
            # emit.
            await self._persist_session_finish(
                status="complete",
                budget_status="ok",
                duration_ms=int((time.monotonic() - self._started_monotonic) * 1000),
            )
            return
        except Exception as exc:
            logger.exception("ai_insights.orchestrator.unexpected_in_run")
            async for ev in self._terminate("error", f"unexpected error: {exc}"):
                yield ev
            return

    # ------------------------------------------------------------------
    # Phases
    # ------------------------------------------------------------------

    async def _phase_bootstrap_iter(self) -> AsyncIterator[_SSEBase]:
        """Phase 1: bootstrap survey via call_api (capped at 8)."""
        from .tools.call_api import call_api

        # Respect the bootstrap cap independently of the global tool cap.
        budget = min(BOOTSTRAP_SURVEY_CAP, len(SURVEY_ENDPOINTS))
        candidates_seen = 0
        for endpoint, params in SURVEY_ENDPOINTS[:budget]:
            if self._cancel_event.is_set():
                return
            if not self._reserve_tool_call():
                # Cap exceeded mid-bootstrap; stop and let main loop terminate.
                return
            tool_call_id = f"call_{uuid.uuid4().hex[:8]}"
            yield self._build_event(
                ToolCallEvent,
                ToolCallData(
                    insight_id=None,
                    tool_call_id=tool_call_id,
                    tool_name="call_api",
                    args_truncated=_truncate_args({"endpoint": endpoint, "params": params}),
                    started_at=_utcnow(),
                ),
            )
            t0 = time.monotonic()
            try:
                result = await call_api(endpoint, params=params)
                ok = 200 <= int(result.get("status", 500)) < 300
                if ok:
                    body = result.get("body") or {}
                    if isinstance(body, dict):
                        rows = body.get("rows") or body.get("items") or []
                        candidates_seen += len(rows) if isinstance(rows, list) else 0
                err = None if ok else "non_2xx"
            except Exception as exc:
                ok = False
                err = f"call_api_exc:{type(exc).__name__}"
            latency_ms = int((time.monotonic() - t0) * 1000)
            yield self._build_event(
                ToolResultEvent,
                ToolResultData(
                    tool_call_id=tool_call_id,
                    ok=ok,
                    row_count=None,
                    latency_ms=latency_ms,
                    error_code=err,
                ),
            )

        yield self._build_event(
            SurveyingEvent,
            SurveyingData(
                session_id=str(self.session_id),
                candidates_seen=candidates_seen,
                message="Surveying the platform…",
            ),
        )
        # An idle ping to nudge keep-alive after bootstrap.
        yield self._build_event(PingEvent, None)

    # ------------------------------------------------------------------
    # Caps + termination helpers
    # ------------------------------------------------------------------

    def _reserve_tool_call(self) -> bool:
        """Atomically increment the per-session tool-call counter.

        Returns False if the cap has been reached (the caller MUST then
        skip the dispatch and unwind to terminate the session).
        """
        if self._tool_calls_used >= TOOL_CALL_CAP:
            return False
        self._tool_calls_used += 1
        return True

    def _tool_call_cap_exceeded(self) -> bool:
        return self._tool_calls_used >= TOOL_CALL_CAP

    def _wall_clock_exceeded(self) -> bool:
        return (time.monotonic() - self._started_monotonic) > WALL_CLOCK_S

    async def _terminate(self, reason: str, message: str) -> AsyncIterator[_SSEBase]:
        """Emit a terminal `error` + `session_complete` + persist."""
        if self._terminated:
            return
        self._terminated = True
        retryable = reason in ("timeout", "cap_exceeded")
        yield self._build_event(
            ErrorEvent,
            ErrorData(
                insight_id=None,
                code=reason,
                message=message,
                retryable=retryable,
            ),
        )
        duration_ms = int((time.monotonic() - self._started_monotonic) * 1000)
        yield self._build_event(
            SessionCompleteEvent,
            SessionCompleteData(
                session_id=str(self.session_id),
                insights_emitted=self._emitted_count,
                duration_ms=duration_ms,
                budget_status="clipped",
            ),
        )
        # Map terminal reasons to ai_session.status/budget_status fields.
        await self._persist_session_finish(
            status="cancelled" if reason == "cancelled" else "failed" if reason == "error" else "complete",
            budget_status="clipped",
            duration_ms=duration_ms,
            error_code=reason,
            error_message=message,
        )

    # ------------------------------------------------------------------
    # Event/skill plumbing
    # ------------------------------------------------------------------

    def _build_event(self, cls: type, data: Any) -> Any:
        self._seq += 1
        kwargs: dict[str, Any] = {
            "event_id": _now_event_id(),
            "seq": self._seq,
            "ts": _utcnow(),
        }
        if data is not None:
            kwargs["data"] = data
        return cls(**kwargs)

    def _build_skill_context(self) -> SkillContext:
        budget_remaining = max(0.0, WALL_CLOCK_S - (time.monotonic() - self._started_monotonic))
        return SkillContext(
            session_id=str(self.session_id),
            turn_id=uuid.uuid4().hex[:8],
            correlation_id=uuid.uuid4().hex[:12],
            model=self.model,
            budget_seconds_remaining=budget_remaining,
            capabilities=Capabilities(),
            rag=None,
        )

    # ------------------------------------------------------------------
    # Persistence (best-effort — never hard-fail the stream on DB issues)
    # ------------------------------------------------------------------

    async def _prime_cross_day_dedup(self) -> None:
        """Seed `_emitted_headlines` with the last 14 days of priors (D8).

        Best-effort: any failure (DB unavailable, pgvector missing in a
        test environment, malformed rows) is logged at WARNING and the
        method returns silently. Today's run still produces valid
        insights, just without the cross-day "ongoing" linkage.
        """
        if self.db is None:
            return
        try:
            from .dedup import fetch_recent_embeddings

            rows = await fetch_recent_embeddings(self.db)
            for _row_id, headline, embedding in rows:
                if headline and embedding:
                    self._emitted_headlines.append((headline, embedding))
            logger.info(
                "ai_insights.orchestrator.cross_day_primed",
                extra={"prior_count": len(rows)},
            )
        except Exception as exc:
            logger.warning(
                "ai_insights.orchestrator.cross_day_priming_failed",
                extra={"err": str(exc)},
            )

    async def _persist_session_start(self, filters: dict[str, Any]) -> None:
        if self.db is None:
            return
        try:
            from .db.models import AISession

            # Phase 2 (migration 013): the cron path passes
            # filters={"focus": "daily-cron", "created_by": "scheduler",
            #          "cron_run_date": <date.today()>}. We persist
            # those fields explicitly so the Phase 3 idempotency guard
            # `WHERE created_by='scheduler' AND cron_run_date=today` can
            # find this row before the orchestrator finishes.
            created_by_raw = filters.get("created_by")
            created_by = str(created_by_raw)[:120] if created_by_raw else None
            cron_run_date = filters.get("cron_run_date")  # date | None
            session = AISession(
                id=self.session_id,
                status="running",
                started_at=_utcnow().replace(tzinfo=None),
                model=self.model,
                focus=str(filters.get("focus") or "")[:240] or None,
                max_insights=self.max_insights,
                created_by=created_by,
                cron_run_date=cron_run_date,
            )
            self.db.add(session)
            await self.db.commit()
            # IMPORTANT: must commit (not just flush) so the OpenClaw-side
            # MCP server (separate DB connection) can see the AISession row
            # when the agent calls persist_insight / finalize_session. With a
            # flush-only the row is invisible across connections, agent gets
            # ai_session_not_found, and the synthesis loop produces 0 insights.
        except Exception as exc:
            logger.warning("ai_insights.orchestrator.persist_start_failed", extra={"err": str(exc)})

    async def _persist_session_finish(
        self,
        *,
        status: str,
        budget_status: str,
        duration_ms: int,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if self.db is None:
            return
        try:
            from sqlalchemy import update

            from .db.models import AISession

            # NOTE: insights_emitted is NOT written here. The agentic path
            # owns that field via the persist_insight + finalize_session
            # MCP handlers (session_tools.py). self._emitted_count stays 0
            # in the agentic mode because the orchestrator never sees the
            # per-insight completes (those happen inside OpenClaw -> MCP),
            # so writing it here would clobber the correct value the MCP
            # handlers already persisted.
            stmt = (
                update(AISession)
                .where(AISession.id == self.session_id)
                .values(
                    status=status,
                    finished_at=_utcnow().replace(tzinfo=None),
                    duration_ms=duration_ms,
                    budget_status=budget_status,
                )
            )
            await self.db.execute(stmt)
            await self.db.flush()
            # error metadata is captured in agent_message as a side-record
            if error_code:
                from .db.models import AgentMessage

                msg = AgentMessage(
                    session_id=self.session_id,
                    seq=self._seq,
                    role="system",
                    content=f"[terminated:{error_code}] {error_message or ''}",
                )
                self.db.add(msg)
                await self.db.flush()
        except Exception as exc:
            logger.warning("ai_insights.orchestrator.persist_finish_failed", extra={"err": str(exc)})

    async def _persist_insight(
        self,
        *,
        insight_id: uuid.UUID,
        idx: int,
        headline: str,
        body: str | None,
        confidence: str,
        materiality: str,
        skills_run: list[str],
        supporting_row_ids: list[str] | None = None,
        headline_embedding: list[float] | None = None,
        ongoing_of_id: uuid.UUID | None = None,
    ) -> None:
        if self.db is None:
            return
        # Phase 2 (migration 013): supporting_row_ids now lands in a
        # dedicated JSONB column on ai_insight, NOT as a footer string in
        # body. The Phase 1 `_Sources: row_ids=[...]_` stop-gap is gone.
        # Body stays clean.
        try:
            from .db.models import AIInsight

            row = AIInsight(
                id=insight_id,
                session_id=self.session_id,
                idx=idx,
                headline=headline,
                body=body,
                confidence=confidence,
                materiality=materiality,
                skills_run=skills_run,
                low_external_support=None,
                supporting_row_ids=(
                    list(supporting_row_ids) if supporting_row_ids else None
                ),
                headline_embedding=headline_embedding,
                ongoing_of_id=ongoing_of_id,
            )
            self.db.add(row)
            await self.db.flush()
        except Exception as exc:
            logger.warning("ai_insights.orchestrator.persist_insight_failed", extra={"err": str(exc)})

    def _record_skill_invocation(self, skill_name: str, outputs: dict[str, Any]) -> None:
        # Skill invocations are kept in-memory; the dispatcher's logger
        # emits a JSON entry per call.
        logger.info(
            "ai_insights.orchestrator.skill_invocation",
            extra={"skill": skill_name, "session_id": str(self.session_id)},
        )

    # ------------------------------------------------------------------
    # Citation prefetch
    # ------------------------------------------------------------------

    # Hard cap per session — Brave free-tier RPS + monthly quota
    WEB_SEARCH_PER_RUN = 8
    CITATIONS_PER_INSIGHT = 3

    async def _prefetch_citations_for_insight(
        self,
        insight_id: str,
        headline: str,
    ) -> None:
        """Run a single web_search per insight and persist top hits to
        agent_citation. Best-effort: any failure is logged and skipped — the
        insight still ships, just without prefetched citations.
        """
        if self.db is None:
            return
        # Per-session budget: shared with the chat-time web_search.
        used = int(getattr(self, "_synthesis_web_search_count", 0))
        if used >= self.WEB_SEARCH_PER_RUN:
            return

        try:
            from .tools.web_search import web_search
            from .db.models import AgentCitation

            result = await web_search(
                query=headline[:200],
                n=self.CITATIONS_PER_INSIGHT,
                ctx=None,
            )
            self._synthesis_web_search_count = used + 1
            if not result.get("ok"):
                # Degraded path (no key, circuit open, etc.) — skip silently.
                logger.info(
                    "ai_insights.orchestrator.citation_prefetch_skipped",
                    extra={"reason": result.get("reason"), "insight_id": insight_id},
                )
                return
            rows = result.get("results") or []
            for r in rows:
                cit = AgentCitation(
                    insight_id=uuid.UUID(insight_id),
                    url=r.get("url", ""),
                    title=r.get("title"),
                    snippet=r.get("snippet"),
                    search_query=r.get("search_query"),
                    # tz-naive to match SQLModel's inferred DateTime() type;
                    # asyncpg picks the encoder from SA, not the DB column.
                    retrieved_at=datetime.utcnow(),
                    provider=r.get("provider", "brave"),
                )
                self.db.add(cit)
            await self.db.flush()
        except Exception as exc:
            logger.warning(
                "ai_insights.orchestrator.citation_prefetch_failed",
                extra={"err": str(exc), "insight_id": insight_id},
            )

    # ------------------------------------------------------------------
    # Chart emit pathway (used by the agent-driven flow when wired)
    # ------------------------------------------------------------------

    async def emit_chart_for_insight(
        self,
        insight_id: str,
        chart: ChartSpec,
    ) -> AsyncIterator[_SSEBase]:
        """Persist + emit a chart event for an insight that is mid-flight.

        Public so the agentic-loop driver can plug in without monkey-
        patching. Emits exactly one `chart` event.
        """
        if not chart.chart_id:
            chart = chart.model_copy(update={"chart_id": _short_chart_id()})
        yield self._build_event(
            ChartEvent,
            ChartEventData(insight_id=insight_id, chart=chart),
        )
        if self.db is None:
            return
        try:
            from .db.models import AgentChart

            row = AgentChart(
                id=chart.chart_id,
                session_id=self.session_id,
                insight_id=uuid.UUID(insight_id),
                spec=chart.model_dump(mode="json"),
                data_source=chart.data_source.model_dump(mode="json"),
                row_hash=chart.data_source.row_hash,
            )
            self.db.add(row)
            await self.db.flush()
        except Exception as exc:
            logger.warning("ai_insights.orchestrator.persist_chart_failed", extra={"err": str(exc)})


__all__ = [
    "InsightOrchestrator",
    "TOOL_CALL_CAP",
    "WALL_CLOCK_S",
    "BOOTSTRAP_SURVEY_CAP",
    "SURVEY_ENDPOINTS",
]
