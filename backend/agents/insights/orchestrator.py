"""InsightOrchestrator — V1 multi-insight session driver.

Per ARCHITECTURE.md §A8 the orchestrator runs five phases per session:

    1. Bootstrap — call_api against fixed survey endpoints (cap 8 calls).
    2. Hypothesize — agent generates 5–15 candidate hypotheses via LLM.
    3. Verify — per-hypothesis 2–4 verification calls; agent confirms / rejects.
    4. Rank — by materiality + novelty (cosine 0.85) + data support; top 5–10.
    5. Synthesize — per kept insight, run insight_synthesis ->
       data_narrative_builder -> visualization_builder; emit chart + insight.

Caps (PRD §5.1, ARCH A10):
    - 40 tool calls per session (V1)
    - 480 s wall-clock per session
    - 12 turns per insight, 4 parallel tools per turn (delegated to ToolLoopDriver)
    - No recursive run_skill (enforced in tools/run_skill.py)

SSE event taxonomy: see specs/sse_events.py (13 events). The orchestrator
yields concrete `_SSEBase` subclasses; the router serialises with
`to_sse_text(event)`.

Persistence covers:
    - ai_session                   — top-level run record
    - ai_insight                   — one row per emitted insight
    - agent_chart                  — one row per emitted chart
    - agent_message                — assistant/tool transcript + SSE replay
    - agent_tool_call              — per tool dispatch
    - skill_invocation             — per run_skill dispatch
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
    ReasoningStepData,
    ReasoningStepEvent,
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
# Caps (V1 — PRD §5.1)
# ---------------------------------------------------------------------------

V1_TOOL_CALL_CAP = 40
V1_WALL_CLOCK_S = 480.0          # 8 minutes
V1_BOOTSTRAP_SURVEY_CAP = 8
V1_MIN_HYPOTHESES = 5
V1_MAX_HYPOTHESES = 15
V1_MIN_INSIGHTS = 5
V1_MAX_INSIGHTS = 10
V1_NOVELTY_COSINE_THRESHOLD = 0.85
V1_MAX_VERIFY_CALLS_PER_HYP = 4
V1_REASONING_MODEL = "oci/openai.gpt-5.4"   # mirrors LlmClient default
HYPOTHESIZER_TOKEN_CEILING = 30_000  # D7 hard cap (tracked in hypothesizer module)


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
assert len(SURVEY_ENDPOINTS) <= V1_BOOTSTRAP_SURVEY_CAP


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _now_event_id() -> str:
    return uuid.uuid4().hex[:16]


def _short_chart_id() -> str:
    return f"c_{uuid.uuid4().hex[:8]}"


_VALID_CHART_TYPES = {
    "bar", "stacked_bar", "grouped_bar", "line", "area",
    "pie", "scatter", "kpi_tile", "sparkline",
}
_KPI_UNIT_MAP = {
    "MW": "MW", "GW": "GW", "USD": "USD", "%": "%",
    "count": "count", "sites": "count",
}


def _chart_from_supporting_rows(
    supporting_rows: list,
    headline: str,
    chart_type_hint: str | None = None,
    y_label_hint: str | None = None,
) -> "ChartSpec | None":
    """Build a ChartSpec from FactRows the LLM cited. The LLM picks the
    chart_type; we fall back to 'bar' (or 'kpi_tile' for single rows) when
    the hint is missing or invalid. Returns None when the LLM said "none"
    or when fewer than 1 rows have a numeric value.
    """
    from .specs.chart_spec import (
        ChartSpec,
        DataSource,
        Encoding,
        Styling,
        XEncoding,
        YEncoding,
    )

    if chart_type_hint == "none":
        return None

    by_entity: dict[str, float] = {}
    for r in supporting_rows:
        v = getattr(r, "value", None)
        ent = getattr(r, "entity", None) or getattr(r, "row_id", "")
        if isinstance(v, (int, float)) and ent:
            ent_s = str(ent)
            cur = by_entity.get(ent_s)
            if cur is None or float(v) > cur:
                by_entity[ent_s] = float(v)
    n = len(by_entity)
    if n == 0:
        return None

    points = [{"entity": e, "value": v} for e, v in by_entity.items()]
    points.sort(key=lambda p: p["value"], reverse=True)
    points = points[:12]

    chart_type = chart_type_hint if chart_type_hint in _VALID_CHART_TYPES else None
    if chart_type is None:
        chart_type = "kpi_tile" if n == 1 else "bar"
    if n == 1 and chart_type not in {"kpi_tile", "sparkline"}:
        chart_type = "kpi_tile"
    # Charts that need a series/time/scatter axis we can't infer from the
    # entity+value shape — fall back to bar so we still render something.
    if chart_type in {"line", "area", "scatter", "stacked_bar", "grouped_bar"}:
        chart_type = "bar"

    y_label = y_label_hint or "MW"
    y_unit = _KPI_UNIT_MAP.get(y_label, None)
    row_hash = ChartSpec.compute_row_hash(points)
    return ChartSpec(
        chart_id=_short_chart_id(),
        chart_type=chart_type,  # type: ignore[arg-type]
        title=headline[:80],
        subtitle=None,
        data_source=DataSource(
            kind="db_query",
            spec={"sql": "-- factpack supporting_rows (synthetic chart) --"},
            rows=len(points),
            fetched_at=datetime.now(timezone.utc),
            row_hash=row_hash,
        ),
        data=points,
        encoding=Encoding(
            x=XEncoding(field="entity", type="category", label=None, tick_format=None),
            y=YEncoding(field="value", type="quantitative", label=y_label, tick_format=None),
        ),
        styling=Styling(palette="oci_brand", y_unit=y_unit, y_precision=0),
    )


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
        model: str = V1_REASONING_MODEL,
        version: str = "v1",
    ) -> None:
        self.session_id = session_id
        self.db = db
        self.llm = llm  # LLMAdapter-shape; optional for unit tests
        self.max_insights = max(V1_MIN_INSIGHTS, min(V1_MAX_INSIGHTS, max_insights))
        self.model = model
        self.version = version

        # Caps + run state
        self._tool_calls_used = 0
        self._started_monotonic = 0.0
        self._cancel_event = asyncio.Event()
        self._seq = 0
        self._terminated = False
        # Headlines emitted in this session, with embeddings — for novelty dedup.
        self._emitted_headlines: list[tuple[str, list[float]]] = []
        self._emitted_count = 0
        # Phase 1 hypothesizer state — populated in _phase_hypothesize_iter.
        self._fact_pack: "FactPack | None" = None
        self._hypothesizer_insights: list = []

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

            async for ev in self._phase_hypothesize_iter():
                yield ev
                if self._cancel_event.is_set():
                    async for term in self._terminate("cancelled", "session cancelled during hypothesize"):
                        yield term
                    return

            # --- Verify + Synthesize (Phases 3-5) ---------------------
            async for ev in self._phase_verify_and_synthesize_iter():
                yield ev
                if self._cancel_event.is_set():
                    async for term in self._terminate("cancelled", "session cancelled during synthesize"):
                        yield term
                    return

            # --- session_complete -------------------------------------
            duration_ms = int((time.monotonic() - self._started_monotonic) * 1000)
            budget_status = "ok"
            if self._tool_call_cap_exceeded() or self._wall_clock_exceeded():
                budget_status = "clipped"

            yield self._build_event(
                SessionCompleteEvent,
                SessionCompleteData(
                    session_id=str(self.session_id),
                    insights_emitted=self._emitted_count,
                    duration_ms=duration_ms,
                    budget_status=budget_status,
                ),
            )
            await self._persist_session_finish(
                status="complete",
                budget_status=budget_status,
                duration_ms=duration_ms,
            )
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
        budget = min(V1_BOOTSTRAP_SURVEY_CAP, len(SURVEY_ENDPOINTS))
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

    async def _phase_hypothesize_iter(self) -> AsyncIterator[_SSEBase]:
        """Phase 2: build a FactPack and synthesize candidate insights.

        Emits exactly one `reasoning_step="hypothesize"` event (the SSE shape
        the frontend reads). On db=None we skip the warehouse pull and leave
        the canned synthesis path in `_phase_verify_and_synthesize_iter` to
        carry the session — keeps unit tests that pass db=None working.
        """
        from .hypothesizer import build_factpack, synthesize_insights

        # Single reasoning_step event for the hypothesize phase (UNCHANGED).
        yield self._build_event(
            ReasoningStepEvent,
            ReasoningStepData(insight_id="session", step="hypothesize"),
        )

        if self.db is None:
            self._fact_pack = None
            self._hypothesizer_insights = []
            return

        try:
            self._fact_pack = await build_factpack(self.db)
            if self._fact_pack is None or self._fact_pack.total_rows() == 0:
                self._hypothesizer_insights = []
                return
            self._hypothesizer_insights = await synthesize_insights(
                self._fact_pack,
                max_insights=self.max_insights,
            )
        except Exception as exc:
            # Catch + log: phase 5 will fall back to the legacy synthesis-skill
            # loop (or emit nothing) rather than crash the SSE session.
            logger.warning(
                "ai_insights.orchestrator.hypothesize_failed",
                extra={"err": str(exc)},
            )
            self._fact_pack = None
            self._hypothesizer_insights = []

    async def _phase_verify_and_synthesize_iter(self) -> AsyncIterator[_SSEBase]:
        """Phases 3-5: per-candidate verify + emit chart + emit insight.

        Phase 1 wiring: when the hypothesizer produced insights, replay them
        directly through the SSE flow with row-id grounding. Otherwise fall
        back to the legacy `insight_synthesis` skill loop so unit tests that
        pass db=None continue to work.
        """
        confidence_map = {"weak": "low", "moderate": "medium", "strong": "high"}

        # ------------------------------------------------------------------
        # New path: hypothesizer produced concrete insights with row_ids.
        # ------------------------------------------------------------------
        if self._fact_pack is not None and self._hypothesizer_insights:
            for idx, insight_out in enumerate(
                self._hypothesizer_insights[: self.max_insights]
            ):
                if self._cancel_event.is_set():
                    return
                if self._tool_call_cap_exceeded() or self._wall_clock_exceeded():
                    return

                insight_id = str(uuid.uuid4())
                yield self._build_event(
                    InsightStartedEvent,
                    InsightStartedData(
                        session_id=str(self.session_id),
                        insight_id=insight_id,
                        index=idx,
                        headline_draft=insight_out.headline[:140],
                    ),
                )
                yield self._build_event(
                    ReasoningStepEvent,
                    ReasoningStepData(insight_id=insight_id, step="verify"),
                )

                # Resolve row_ids back into FactRow objects for downstream use
                # (chart-building / persistence in later phases).
                supporting_rows = self._fact_pack.lookup(insight_out.supporting_row_ids)

                # Best-effort dedup against prior emitted headlines.
                try:
                    duplicate = await is_duplicate(
                        insight_out.headline,
                        self._emitted_headlines,
                        cosine_threshold=V1_NOVELTY_COSINE_THRESHOLD,
                    )
                except Exception:
                    duplicate = False
                if duplicate:
                    yield self._build_event(
                        ErrorEvent,
                        ErrorData(
                            insight_id=insight_id,
                            code="duplicate_insight",
                            message="headline too similar to a prior insight",
                            retryable=False,
                        ),
                    )
                    continue

                yield self._build_event(
                    ReasoningStepEvent,
                    ReasoningStepData(insight_id=insight_id, step="emit"),
                )

                confidence = confidence_map.get(insight_out.confidence_signal, "medium")
                materiality = insight_out.materiality or "medium"

                yield self._build_event(
                    InsightCompleteEvent,
                    InsightCompleteData(
                        insight_id=insight_id,
                        headline=insight_out.headline,
                        confidence=confidence,  # type: ignore[arg-type]
                        materiality=materiality,  # type: ignore[arg-type]
                        skills_run=["mega_synthesis"],
                        low_external_support=None,
                    ),
                )

                self._emitted_headlines.append((insight_out.headline, []))
                self._emitted_count += 1
                await self._persist_insight(
                    insight_id=uuid.UUID(insight_id),
                    idx=idx,
                    headline=insight_out.headline,
                    body=insight_out.body,
                    confidence=confidence,
                    materiality=materiality,
                    skills_run=["mega_synthesis"],
                    supporting_row_ids=insight_out.supporting_row_ids,
                )

                # LLM picks the chart shape; the orchestrator builds the
                # spec deterministically from the cited supporting rows.
                chart = _chart_from_supporting_rows(
                    supporting_rows,
                    insight_out.headline,
                    chart_type_hint=insight_out.chart_type,
                    y_label_hint=insight_out.chart_y_label,
                )
                if chart is not None:
                    async for ev in self.emit_chart_for_insight(insight_id, chart):
                        yield ev

                # Citation prefetch: ground the insight in real web sources
                # before the user opens the chat. Caps at WEB_SEARCH_PER_RUN
                # across the whole session to stay under Brave's 1 RPS / free
                # tier limits.
                await self._prefetch_citations_for_insight(
                    insight_id=insight_id,
                    headline=insight_out.headline,
                )
            return

        # ------------------------------------------------------------------
        # Legacy fallback: keeps unit tests (db=None) green until Phase 2.
        # ------------------------------------------------------------------
        from .skills.insight_synthesis.inputs import InsightSynthesisInputs
        from .skills.insight_synthesis.tool import run as run_insight_synthesis

        for idx in range(self.max_insights):
            if self._cancel_event.is_set():
                return
            if self._tool_call_cap_exceeded() or self._wall_clock_exceeded():
                return

            insight_id = str(uuid.uuid4())
            yield self._build_event(
                InsightStartedEvent,
                InsightStartedData(
                    session_id=str(self.session_id),
                    insight_id=insight_id,
                    index=idx,
                    headline_draft=None,
                ),
            )

            # ---- run insight_synthesis ----
            yield self._build_event(
                ReasoningStepEvent,
                ReasoningStepData(insight_id=insight_id, step="verify"),
            )

            try:
                synth = await run_insight_synthesis(
                    InsightSynthesisInputs(
                        hypothesis=f"Candidate insight #{idx + 1} from session bootstrap.",
                        supporting_rows=[],
                        context={"session_id": str(self.session_id)},
                    ),
                    self._build_skill_context(),
                )
                self._record_skill_invocation("insight_synthesis", synth.model_dump())
            except Exception as exc:
                logger.warning(
                    "ai_insights.orchestrator.insight_synthesis_failed",
                    extra={"err": str(exc)},
                )
                yield self._build_event(
                    ErrorEvent,
                    ErrorData(
                        insight_id=insight_id,
                        code="skill_error",
                        message=f"insight_synthesis failed: {exc}",
                        retryable=True,
                    ),
                )
                continue

            # ---- de-duplicate ----
            try:
                duplicate = await is_duplicate(
                    synth.headline,
                    self._emitted_headlines,
                    cosine_threshold=V1_NOVELTY_COSINE_THRESHOLD,
                )
            except Exception:
                duplicate = False
            if duplicate:
                yield self._build_event(
                    ErrorEvent,
                    ErrorData(
                        insight_id=insight_id,
                        code="duplicate_insight",
                        message="headline too similar to a prior insight",
                        retryable=False,
                    ),
                )
                continue

            # ---- (best-effort) emit a placeholder chart ----
            yield self._build_event(
                ReasoningStepEvent,
                ReasoningStepData(insight_id=insight_id, step="emit"),
            )
            # We do not synthesise a fake chart in V1's minimal path —
            # the agent-driven flow adds charts when verification yields
            # row-backed data. The synthesize_iter shell stays open for V2.

            # ---- persist + emit insight_complete ----
            confidence_map = {"weak": "low", "moderate": "medium", "strong": "high"}
            confidence = confidence_map.get(synth.confidence_signal, "medium")
            materiality = "medium"   # V1 default; agent self-rate lands in V2

            yield self._build_event(
                InsightCompleteEvent,
                InsightCompleteData(
                    insight_id=insight_id,
                    headline=synth.headline,
                    confidence=confidence,  # type: ignore[arg-type]
                    materiality=materiality,  # type: ignore[arg-type]
                    skills_run=["insight_synthesis"],
                    low_external_support=None,
                ),
            )

            self._emitted_headlines.append((synth.headline, []))
            self._emitted_count += 1
            await self._persist_insight(
                insight_id=uuid.UUID(insight_id),
                idx=idx,
                headline=synth.headline,
                body=synth.body,
                confidence=confidence,
                materiality=materiality,
                skills_run=["insight_synthesis"],
            )

    # ------------------------------------------------------------------
    # Caps + termination helpers
    # ------------------------------------------------------------------

    def _reserve_tool_call(self) -> bool:
        """Atomically increment the per-session tool-call counter.

        Returns False if the cap has been reached (the caller MUST then
        skip the dispatch and unwind to terminate the session).
        """
        if self._tool_calls_used >= V1_TOOL_CALL_CAP:
            return False
        self._tool_calls_used += 1
        return True

    def _tool_call_cap_exceeded(self) -> bool:
        return self._tool_calls_used >= V1_TOOL_CALL_CAP

    def _wall_clock_exceeded(self) -> bool:
        return (time.monotonic() - self._started_monotonic) > V1_WALL_CLOCK_S

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
        # Map V1 reasons to ai_session.status/budget_status fields.
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
        budget_remaining = max(0.0, V1_WALL_CLOCK_S - (time.monotonic() - self._started_monotonic))
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
                version=self.version,
                created_by=created_by,
                cron_run_date=cron_run_date,
            )
            self.db.add(session)
            await self.db.flush()
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

            stmt = (
                update(AISession)
                .where(AISession.id == self.session_id)
                .values(
                    status=status,
                    finished_at=_utcnow().replace(tzinfo=None),
                    duration_ms=duration_ms,
                    budget_status=budget_status,
                    insights_emitted=self._emitted_count,
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
        # Skill rows are persisted async outside the hot loop in V2; in V1
        # we keep them in-memory and let the dispatcher's logger emit JSON.
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

        Public so the V2 ToolLoopDriver path can plug in without monkey-
        patching.  Emits exactly one `chart` event.
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
    "V1_TOOL_CALL_CAP",
    "V1_WALL_CLOCK_S",
    "V1_BOOTSTRAP_SURVEY_CAP",
    "V1_NOVELTY_COSINE_THRESHOLD",
    "SURVEY_ENDPOINTS",
]
