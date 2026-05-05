"""Typed SSE event taxonomy for AI Insights.

Authoritative reference: ARCHITECTURE.md A5. Names below match A5 exactly:
  session_started, surveying, insight_started, token, reasoning_step,
  tool_call, tool_result, chart, citation, insight_complete,
  session_complete, error, ping
(13 events, V1 + V2 inclusive — `citation` is V2-only on the wire.)

Each event carries:
  - event_id: monotonic id used by the SSE `id:` line; clients echo it back
    via the `Last-Event-ID` header to resume from the in-process replay
    ring buffer (ARCH A5.1).
  - seq: monotonically increasing integer per session (used by the client
    to detect dropped events even when the EventSource auto-reconnects).
  - ts: timezone-aware UTC timestamp.

A discriminated `SSEEvent` union dispatches on the `event` field, which
matches the on-wire `event:` line. `to_sse_text(event)` formats one event
to its SSE wire representation.

NO business logic — pure schema + a serialisation helper.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from .chart_spec import ChartSpec

# ---------------------------------------------------------------------------
# Common base
# ---------------------------------------------------------------------------


class _SSEBase(BaseModel):
    """Fields shared by every SSE event."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., min_length=1, max_length=64)
    seq: int = Field(..., ge=0)
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Per-event payload models
# ---------------------------------------------------------------------------


class SessionStartedData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    model: str
    started_at: datetime
    max_insights: int = Field(..., ge=1, le=20)


class SessionStartedEvent(_SSEBase):
    event: Literal["session_started"] = "session_started"
    data: SessionStartedData


class SurveyingData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    candidates_seen: int = Field(..., ge=0)
    message: str = "Surveying the platform…"


class SurveyingEvent(_SSEBase):
    event: Literal["surveying"] = "surveying"
    data: SurveyingData


class InsightStartedData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    insight_id: str
    index: int = Field(..., ge=0)
    headline_draft: str | None = None


class InsightStartedEvent(_SSEBase):
    event: Literal["insight_started"] = "insight_started"
    data: InsightStartedData


class TokenData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    insight_id: str
    field: Literal["headline", "body"]
    delta: str


class TokenEvent(_SSEBase):
    """Streaming text chunk for an insight's headline or body."""

    event: Literal["token"] = "token"
    data: TokenData


ReasoningStepName = Literal["EDA", "hypothesize", "verify", "emit"]


class ReasoningStepData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    insight_id: str
    step: ReasoningStepName


class ReasoningStepEvent(_SSEBase):
    event: Literal["reasoning_step"] = "reasoning_step"
    data: ReasoningStepData


class ToolCallData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    insight_id: str | None = None
    tool_call_id: str
    tool_name: str
    args_truncated: str = Field(..., max_length=200)
    started_at: datetime


class ToolCallEvent(_SSEBase):
    event: Literal["tool_call"] = "tool_call"
    data: ToolCallData


class ToolResultData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_call_id: str
    ok: bool
    row_count: int | None = None
    latency_ms: int = Field(..., ge=0)
    error_code: str | None = None


class ToolResultEvent(_SSEBase):
    event: Literal["tool_result"] = "tool_result"
    data: ToolResultData


class ChartEventData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    insight_id: str
    chart: ChartSpec


class ChartEvent(_SSEBase):
    event: Literal["chart"] = "chart"
    data: ChartEventData


class WebCitation(BaseModel):
    """V2 web citation payload (ARCH A6.7). Defined here so the SSE event is
    self-contained; canonical persistence shape lives in persistence/models.py
    when V2 lights up.
    """

    model_config = ConfigDict(extra="forbid")
    url: str
    title: str
    snippet: str = Field(..., max_length=280)
    agree_or_disagree: Literal["agree", "disagree", "context"]
    rationale: str
    search_query: str
    retrieved_at: datetime
    provider: Literal["tavily", "brave"] | None = None


class CitationEventData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    insight_id: str
    citation: WebCitation


class CitationEvent(_SSEBase):
    event: Literal["citation"] = "citation"
    data: CitationEventData


InsightConfidence = Literal["low", "medium", "high"]
InsightMateriality = Literal["low", "medium", "high"]


class InsightCompleteData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    insight_id: str
    headline: str
    confidence: InsightConfidence
    materiality: InsightMateriality
    skills_run: list[str]
    low_external_support: bool | None = None


class InsightCompleteEvent(_SSEBase):
    event: Literal["insight_complete"] = "insight_complete"
    data: InsightCompleteData


SessionBudgetStatus = Literal["ok", "clipped"]


class SessionCompleteData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    insights_emitted: int = Field(..., ge=0)
    duration_ms: int = Field(..., ge=0)
    budget_status: SessionBudgetStatus


class SessionCompleteEvent(_SSEBase):
    event: Literal["session_complete"] = "session_complete"
    data: SessionCompleteData


class ErrorData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    insight_id: str | None = None
    code: str
    message: str
    retryable: bool


class ErrorEvent(_SSEBase):
    event: Literal["error"] = "error"
    data: ErrorData


class PingData(BaseModel):
    """Heartbeat — empty payload (ARCH A5.1)."""

    model_config = ConfigDict(extra="forbid")


class PingEvent(_SSEBase):
    event: Literal["ping"] = "ping"
    data: PingData = Field(default_factory=PingData)


# ---------------------------------------------------------------------------
# V2 events: web_search availability + chat-thread lifecycle
# ---------------------------------------------------------------------------


WebSearchUnavailableReason = Literal["no_api_key", "circuit_open", "rate_limited"]


class WebSearchUnavailableData(BaseModel):
    """Surface that web_search is operating in degraded mode.

    Triggered (a) when BRAVE_SEARCH_API_KEY is unset, (b) when the module
    circuit breaker is open, or (c) when upstream rate-limits us. The UI
    renders a banner; the agent loop continues without citations.
    """

    model_config = ConfigDict(extra="forbid")
    reason: WebSearchUnavailableReason
    session_id: str | None = None
    insight_id: str | None = None


class WebSearchUnavailableEvent(_SSEBase):
    event: Literal["web_search_unavailable"] = "web_search_unavailable"
    data: WebSearchUnavailableData


class AssistantMessageTokenData(BaseModel):
    """Streaming text chunk emitted by the chat agent."""

    model_config = ConfigDict(extra="forbid")
    thread_id: str
    message_id: str
    delta: str


class AssistantMessageTokenEvent(_SSEBase):
    event: Literal["assistant_message_token"] = "assistant_message_token"
    data: AssistantMessageTokenData


class ToolCallStartedData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str
    tool_call_id: str
    tool_name: str
    args_truncated: str = Field(..., max_length=200)


class ToolCallStartedEvent(_SSEBase):
    event: Literal["tool_call_started"] = "tool_call_started"
    data: ToolCallStartedData


class ToolCallCompleteData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str
    tool_call_id: str
    ok: bool
    latency_ms: int = Field(..., ge=0)
    error_code: str | None = None


class ToolCallCompleteEvent(_SSEBase):
    event: Literal["tool_call_complete"] = "tool_call_complete"
    data: ToolCallCompleteData


MessageFinishReason = Literal["stop", "length", "tool_cap", "error"]


class MessageCompleteData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str
    message_id: str
    finish_reason: MessageFinishReason


class MessageCompleteEvent(_SSEBase):
    event: Literal["message_complete"] = "message_complete"
    data: MessageCompleteData


# ---------------------------------------------------------------------------
# Discriminated union
# ---------------------------------------------------------------------------

SSEEvent = Annotated[
    Union[
        SessionStartedEvent,
        SurveyingEvent,
        InsightStartedEvent,
        TokenEvent,
        ReasoningStepEvent,
        ToolCallEvent,
        ToolResultEvent,
        ChartEvent,
        CitationEvent,
        InsightCompleteEvent,
        SessionCompleteEvent,
        ErrorEvent,
        PingEvent,
        # V2 additions
        WebSearchUnavailableEvent,
        AssistantMessageTokenEvent,
        ToolCallStartedEvent,
        ToolCallCompleteEvent,
        MessageCompleteEvent,
    ],
    Field(discriminator="event"),
]

# Adapter for parsing arbitrary dicts into the right concrete event type.
SSEEventAdapter: TypeAdapter[Any] = TypeAdapter(SSEEvent)


# ---------------------------------------------------------------------------
# Wire-format helper
# ---------------------------------------------------------------------------


def to_sse_text(event: _SSEBase) -> str:
    """Format an SSE event as the on-wire text frame.

    Output shape::

        id: <event_id>
        event: <event-name>
        data: <json>
        \\n

    The trailing blank line terminates the SSE event per the spec. The
    `data:` payload is the event's `data` field serialised to JSON
    (timestamps as ISO-8601, dicts compacted).
    """
    # `event` attribute is always present on concrete subclasses thanks to
    # the Literal default; _SSEBase is only a static type alias here.
    event_name: str = getattr(event, "event")
    payload: Any = getattr(event, "data", None)

    if isinstance(payload, BaseModel):
        data_json = payload.model_dump_json()
    elif payload is None:
        data_json = "{}"
    else:
        data_json = json.dumps(payload, default=str, separators=(",", ":"))

    return (
        f"id: {event.event_id}\n"
        f"event: {event_name}\n"
        f"data: {data_json}\n"
        f"\n"
    )
