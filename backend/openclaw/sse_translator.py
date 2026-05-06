"""OpenClaw SSE -> our SSE-event-taxonomy translator.

Spec:
  - docs/plans/ai-insights-automation/11b-openclaw-migration-architecture.md §5.4
  - docs/plans/ai-insights-automation/11c-openclaw-migration-addendum.md §B

OpenClaw's `/v1/chat/completions` endpoint streams `text/event-stream`
frames whose `data:` payload is an OpenAI `chat.completion.chunk`
(plus a terminating `data: [DONE]` frame). This module is a pure-
function translator that maps those chunks into our project's
existing SSE event union from
`agents.insights.specs.sse_events`. The forwarder feeds chunks in
one at a time and emits the produced events to the StreamingResponse.

Translation table (ADDENDUM 11c §B):

| OpenClaw chunk                                         | Our event                |
|--------------------------------------------------------|--------------------------|
| choices[0].delta.content non-empty                     | assistant_message_token  |
| choices[0].delta.tool_calls[0] first w/ id+function    | tool_call_started        |
| finish_reason == "tool_calls" (or follow-up tool frame)| tool_call_complete       |
| finish_reason == "stop" then `[DONE]`                  | message_complete         |
| error JSON in data: frame                              | error                    |

Streaming tool calls arrive in fragments — OpenAI sends the function
`name` only on the first delta, then arguments incrementally. The
`ChunkAccumulator` in this module assembles those fragments and emits
exactly one `tool_call_started` per tool_call_id at first sight of
the function name.

This module has no I/O and no DB writes. The forwarder owns those.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from agents.insights.specs.sse_events import (
    AssistantMessageTokenData,
    AssistantMessageTokenEvent,
    ChartEvent,
    ChartEventData,
    ErrorData,
    ErrorEvent,
    InsightCompleteData,
    InsightCompleteEvent,
    InsightStartedData,
    InsightStartedEvent,
    MessageCompleteData,
    MessageCompleteEvent,
    ReasoningStepData,
    ReasoningStepEvent,
    SessionCompleteData,
    SessionCompleteEvent,
    ToolCallCompleteData,
    ToolCallCompleteEvent,
    ToolCallStartedData,
    ToolCallStartedEvent,
)

logger = logging.getLogger(__name__)


# Convenience alias for any of the events this translator can produce.
TranslatedEvent = (
    AssistantMessageTokenEvent
    | ToolCallStartedEvent
    | ToolCallCompleteEvent
    | MessageCompleteEvent
    | ErrorEvent
)


# ---------------------------------------------------------------------------
# Sentinel for the [DONE] terminator
# ---------------------------------------------------------------------------


class _Done:  # pragma: no cover - sentinel
    """Marker returned from `parse_sse_data_field` for `data: [DONE]`."""


DONE = _Done()


def parse_sse_data_field(data_field: str) -> Optional[Any]:
    """Parse the `data:` value of an SSE frame.

    Returns:
      - DONE sentinel when the body is the literal `[DONE]`.
      - a dict when the body is JSON.
      - None when the body is unparseable (caller should ignore the frame).
    """
    body = data_field.strip()
    if not body:
        return None
    if body == "[DONE]":
        return DONE
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        logger.warning("openclaw.sse.data_not_json", extra={"len": len(body)})
        return None


# ---------------------------------------------------------------------------
# Per-stream accumulator state
# ---------------------------------------------------------------------------


@dataclass
class _PendingToolCall:
    """Partial tool_call assembled from streaming deltas."""

    tool_call_id: str
    name: Optional[str] = None
    args_buffer: str = ""
    started_emitted: bool = False
    completed_emitted: bool = False


@dataclass
class ChunkAccumulator:
    """Mutable state across the chunks of one OpenClaw response.

    Members:
      - thread_id, message_id, insight_id: identity used to build our events.
      - tool_calls_by_index / tool_calls_by_id: partial tool calls indexed
        both ways since OpenAI streaming uses index, but tool_call_id is
        the stable key once known.
      - assistant_text_seen: true once the model emits any visible content.
      - tool_calls_log: list of completed tool-call records the forwarder
        persists with the assistant message.
    """

    thread_id: str
    message_id: str
    insight_id: str
    tool_calls_by_index: dict[int, _PendingToolCall] = field(default_factory=dict)
    tool_calls_by_id: dict[str, _PendingToolCall] = field(default_factory=dict)
    assistant_text_seen: bool = False
    tool_calls_log: list[dict[str, Any]] = field(default_factory=list)
    finished: bool = False

    # ------------------------------------------------------------------
    # Event-id minting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _amt_id() -> str:
        return f"amt_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _tcs_id() -> str:
        return f"tcs_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _tcc_id() -> str:
        return f"tcc_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _mco_id() -> str:
        return f"mco_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _err_id() -> str:
        return f"err_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------


def translate_chunk(
    chunk: Any, acc: ChunkAccumulator
) -> list[TranslatedEvent]:
    """Translate a single parsed OpenClaw chunk into zero-or-more events.

    `chunk` may be:
      - DONE sentinel (`[DONE]` terminator).
      - dict matching the OpenAI `chat.completion.chunk` shape.
      - dict containing an "error" field (gateway error).
      - any other dict: a structured-log warning is emitted and the
        function returns `[]`.

    `acc` is mutated to record partial state across calls.
    """
    if chunk is DONE:
        return _emit_message_complete(acc, finish_reason="stop")

    if not isinstance(chunk, dict):
        return []

    # Gateway-level error frame.
    if "error" in chunk and "choices" not in chunk:
        return [
            ErrorEvent(
                event_id=ChunkAccumulator._err_id(),
                seq=0,
                data=ErrorData(
                    insight_id=acc.insight_id,
                    code=str(chunk.get("error", {}).get("code") or "openclaw_error"),
                    message=str(
                        chunk.get("error", {}).get("message") or "openclaw upstream error"
                    ),
                    retryable=bool(chunk.get("error", {}).get("retryable", False)),
                ),
            )
        ]

    out: list[TranslatedEvent] = []

    choices = chunk.get("choices") or []
    if not choices:
        return out

    choice = choices[0]
    delta = choice.get("delta") or {}
    finish_reason = choice.get("finish_reason")

    # 1. Token (assistant text).
    content_delta = delta.get("content")
    if content_delta:
        acc.assistant_text_seen = True
        out.append(
            AssistantMessageTokenEvent(
                event_id=ChunkAccumulator._amt_id(),
                seq=0,
                data=AssistantMessageTokenData(
                    thread_id=acc.thread_id,
                    message_id=acc.message_id,
                    delta=str(content_delta),
                ),
            )
        )

    # 2. Tool-call deltas (assemble; emit started once per tool_call_id).
    tool_call_deltas = delta.get("tool_calls") or []
    for tc_delta in tool_call_deltas:
        idx = tc_delta.get("index")
        if idx is None:
            continue
        idx_int = int(idx)

        pending = acc.tool_calls_by_index.get(idx_int)
        if pending is None:
            pending = _PendingToolCall(
                tool_call_id=tc_delta.get("id") or f"tc_{uuid.uuid4().hex[:10]}"
            )
            acc.tool_calls_by_index[idx_int] = pending
            if pending.tool_call_id:
                acc.tool_calls_by_id[pending.tool_call_id] = pending

        # `id` may arrive on a later delta than the index; capture it.
        if not pending.tool_call_id and tc_delta.get("id"):
            pending.tool_call_id = tc_delta["id"]
            acc.tool_calls_by_id[pending.tool_call_id] = pending

        function_block = tc_delta.get("function") or {}
        if "name" in function_block and function_block["name"]:
            pending.name = function_block["name"]
        if "arguments" in function_block and function_block["arguments"]:
            pending.args_buffer += function_block["arguments"]

        # Emit tool_call_started once we know both id and name.
        if (
            pending.name
            and pending.tool_call_id
            and not pending.started_emitted
        ):
            try:
                args_repr = pending.args_buffer or ""
                # Best-effort prettify: if buffer parses as JSON, re-dump compact.
                try:
                    parsed = json.loads(args_repr)
                    args_repr = json.dumps(parsed, default=str)
                except json.JSONDecodeError:
                    pass
            except Exception:  # noqa: BLE001
                args_repr = "<unserialisable>"

            out.append(
                ToolCallStartedEvent(
                    event_id=ChunkAccumulator._tcs_id(),
                    seq=0,
                    data=ToolCallStartedData(
                        thread_id=acc.thread_id,
                        tool_call_id=pending.tool_call_id,
                        tool_name=pending.name,
                        args_truncated=args_repr[:200],
                    ),
                )
            )
            pending.started_emitted = True

    # 3. finish_reason transitions.
    if finish_reason == "tool_calls":
        # Emit tool_call_complete for every pending tool call we have seen
        # but not yet completed. Latency here is unknown (the gateway runs
        # the tool out of band) so we report 0; the agent_tools router's
        # webhook latency is what actually matters for ops.
        for pending in list(acc.tool_calls_by_id.values()):
            if pending.completed_emitted:
                continue
            out.append(
                ToolCallCompleteEvent(
                    event_id=ChunkAccumulator._tcc_id(),
                    seq=0,
                    data=ToolCallCompleteData(
                        thread_id=acc.thread_id,
                        tool_call_id=pending.tool_call_id,
                        ok=True,
                        latency_ms=0,
                        error_code=None,
                    ),
                )
            )
            pending.completed_emitted = True
            acc.tool_calls_log.append(
                {
                    "tool_call_id": pending.tool_call_id,
                    "tool_name": pending.name,
                    "args": pending.args_buffer,
                    "ok": True,
                }
            )
    elif finish_reason in ("stop", "length", "content_filter"):
        out.extend(_emit_message_complete(acc, finish_reason=finish_reason))

    return out


def _emit_message_complete(
    acc: ChunkAccumulator, *, finish_reason: str
) -> list[TranslatedEvent]:
    """Idempotently emit a single message_complete event."""
    if acc.finished:
        return []
    acc.finished = True

    # Map upstream finish_reason to our taxonomy's enum.
    if finish_reason in ("stop",):
        ours = "stop"
    elif finish_reason == "length":
        ours = "length"
    elif finish_reason == "content_filter":
        ours = "error"
    else:
        ours = "stop"

    return [
        MessageCompleteEvent(
            event_id=ChunkAccumulator._mco_id(),
            seq=0,
            data=MessageCompleteData(
                thread_id=acc.thread_id,
                message_id=acc.message_id,
                finish_reason=ours,  # type: ignore[arg-type]
            ),
        )
    ]


# ---------------------------------------------------------------------------
# Optional: line-iterator -> event-iterator convenience
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 2 (PRD/ARCH 14) — sibling synthesis-lane translator
# ---------------------------------------------------------------------------


# Convenience alias for any of the events the synthesis translator can produce.
# Includes the V1 InsightStarted/InsightComplete/SessionComplete event classes
# already on the SSEEvent union plus the chat-lane primitives we re-use for
# tool-call lifecycle and assistant text.
SynthesisTranslatedEvent = (
    AssistantMessageTokenEvent
    | ToolCallStartedEvent
    | ToolCallCompleteEvent
    | InsightStartedEvent
    | InsightCompleteEvent
    | SessionCompleteEvent
    | ReasoningStepEvent
    | ChartEvent
    | ErrorEvent
    | MessageCompleteEvent
)


@dataclass
class SynthesisChunkAccumulator:
    """Mutable per-stream state for `translate_synthesis_chunk`.

    Sibling of `ChunkAccumulator`; the chat lane is intentionally
    untouched (PRD AC-4 / FR-X.6 — chat byte stream is byte-identical).

    Members:
      - session_id: parent AISession.id (UUID string).
      - thread_id, message_id, insight_id: identity used to build chat-
        primitive events (assistant_message_token, tool_call_*).
      - tool_calls_by_index / tool_calls_by_id: streaming tool-call
        partials, same shape as the chat translator.
      - current_insight_idx: monotonic 0-based ordinal incremented on
        each successful `persist_insight`.
      - current_insight_id: insight_id returned by the most recent
        `persist_insight` (None until the first persist).
      - total_insights_persisted: total count of successful persist_insight
        calls in this session.
      - cap_counters: client-side cap tracking (turns, tool_calls,
        wall-clock start). Driver short-circuits when these exceed
        thresholds; see `agentic_synthesis._drive_openclaw_stream`.
      - finalize_seen: set True when finalize_session tool_call_complete
        is observed; the driver uses this to detect degraded close.
      - finished: set True when the stream is logically done (synthetic
        close, finish_reason=stop, or [DONE]).
    """

    session_id: str
    thread_id: str
    message_id: str
    insight_id: str = ""

    tool_calls_by_index: dict[int, _PendingToolCall] = field(default_factory=dict)
    tool_calls_by_id: dict[str, _PendingToolCall] = field(default_factory=dict)

    current_insight_idx: int = 0
    current_insight_id: Optional[str] = None
    total_insights_persisted: int = 0

    # Cap counters live on the accumulator so the driver can read them
    # without an extra side channel. `wall_clock_started_at` is a
    # `time.monotonic()` float set by the driver before the SSE drain.
    cap_counters: dict[str, Any] = field(
        default_factory=lambda: {
            "turns": 0,
            "tool_calls": 0,
            "wall_clock_started_at": None,
        }
    )

    finalize_seen: bool = False
    finished: bool = False

    # Audit trail mirroring ChunkAccumulator.tool_calls_log so the
    # driver can persist the assistant message with the same JSONB
    # shape the chat lane uses.
    tool_calls_log: list[dict[str, Any]] = field(default_factory=list)


def _safe_parse_args(buf: str) -> dict[str, Any]:
    """Parse a streaming tool-call args buffer; return {} on any error.

    OpenAI streams arguments as a string accumulated across deltas and
    the buffer may be incomplete by the time we want to peek at fields
    like ``insight_id`` or ``status``. Best-effort parse; never raise.
    """
    if not buf:
        return {}
    try:
        v = json.loads(buf)
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}


def translate_synthesis_chunk(
    chunk: Any, acc: SynthesisChunkAccumulator
) -> list[SynthesisTranslatedEvent]:
    """Translate a single parsed OpenClaw chunk into synthesis-lane events.

    Sibling of `translate_chunk`. NEVER modifies `translate_chunk` or the
    chat-lane `ChunkAccumulator`.

    Mapping (see ARCH §5):
      * delta.content       -> ReasoningStepEvent(insight_id=current or "session", step="emit")
      * tool_call_started for `persist_insight`     -> InsightStartedEvent(idx=current_insight_idx)
      * tool_call_complete for `persist_insight`    -> InsightCompleteEvent(idx, insight_id)
      * tool_call_complete for `emit_chart`         -> ToolCallCompleteEvent (chart_id surfaced as event_id metadata)
      * tool_call_complete for `finalize_session`   -> SessionCompleteEvent(status, total_insights)
      * generic tool_call_started/complete          -> ToolCallStartedEvent / ToolCallCompleteEvent
      * finish_reason=="stop" without finalize_seen -> degraded SessionCompleteEvent(status="degraded")
      * gateway error frame                         -> ErrorEvent
      * [DONE]                                      -> idempotent close
    """
    if chunk is DONE:
        out: list[SynthesisTranslatedEvent] = []
        if not acc.finalize_seen and not acc.finished:
            out.append(_synthesis_session_complete(acc, status="degraded"))
        acc.finished = True
        return out

    if not isinstance(chunk, dict):
        return []

    # Gateway-level error frame.
    if "error" in chunk and "choices" not in chunk:
        return [
            ErrorEvent(
                event_id=ChunkAccumulator._err_id(),
                seq=0,
                data=ErrorData(
                    insight_id=acc.current_insight_id,
                    code=str(chunk.get("error", {}).get("code") or "openclaw_error"),
                    message=str(
                        chunk.get("error", {}).get("message")
                        or "openclaw upstream error"
                    ),
                    retryable=bool(chunk.get("error", {}).get("retryable", False)),
                ),
            )
        ]

    out: list[SynthesisTranslatedEvent] = []

    choices = chunk.get("choices") or []
    if not choices:
        return out

    choice = choices[0]
    delta = choice.get("delta") or {}
    finish_reason = choice.get("finish_reason")

    # 1. Reasoning step from assistant text deltas. One ReasoningStepEvent
    #    per non-empty content delta keeps the front-end "thinking" feed
    #    populated without pretending to surface tokens 1-1.
    content_delta = delta.get("content")
    if content_delta:
        out.append(
            ReasoningStepEvent(
                event_id=ChunkAccumulator._amt_id(),
                seq=0,
                data=ReasoningStepData(
                    insight_id=acc.current_insight_id or "session",
                    step="emit",
                ),
            )
        )

    # 2. Tool-call deltas. Reuse the chat-lane delta-accumulation logic
    #    inline so we stay sibling-safe (no shared mutable helper).
    tool_call_deltas = delta.get("tool_calls") or []
    for tc_delta in tool_call_deltas:
        idx = tc_delta.get("index")
        if idx is None:
            continue
        idx_int = int(idx)

        pending = acc.tool_calls_by_index.get(idx_int)
        if pending is None:
            pending = _PendingToolCall(
                tool_call_id=tc_delta.get("id") or f"tc_{uuid.uuid4().hex[:10]}"
            )
            acc.tool_calls_by_index[idx_int] = pending
            if pending.tool_call_id:
                acc.tool_calls_by_id[pending.tool_call_id] = pending

        if not pending.tool_call_id and tc_delta.get("id"):
            pending.tool_call_id = tc_delta["id"]
            acc.tool_calls_by_id[pending.tool_call_id] = pending

        function_block = tc_delta.get("function") or {}
        if "name" in function_block and function_block["name"]:
            pending.name = function_block["name"]
        if "arguments" in function_block and function_block["arguments"]:
            pending.args_buffer += function_block["arguments"]

        # Emit started events on first sight of a known tool name.
        if (
            pending.name
            and pending.tool_call_id
            and not pending.started_emitted
        ):
            args_repr = pending.args_buffer or ""
            try:
                parsed = json.loads(args_repr)
                args_repr = json.dumps(parsed, default=str)
            except json.JSONDecodeError:
                pass

            if pending.name == "persist_insight":
                # Surface as InsightStartedEvent so the SSE consumer can
                # render a fresh card before persistence completes.
                parsed_args = _safe_parse_args(pending.args_buffer)
                draft = parsed_args.get("headline") or parsed_args.get("insight", {}).get("headline") if isinstance(parsed_args.get("insight"), dict) else None
                if isinstance(draft, str):
                    headline_draft: Optional[str] = draft[:140]
                else:
                    headline_draft = None
                out.append(
                    InsightStartedEvent(
                        event_id=ChunkAccumulator._tcs_id(),
                        seq=0,
                        data=InsightStartedData(
                            session_id=acc.session_id,
                            insight_id=acc.current_insight_id or pending.tool_call_id,
                            index=acc.current_insight_idx,
                            headline_draft=headline_draft,
                        ),
                    )
                )
            else:
                out.append(
                    ToolCallStartedEvent(
                        event_id=ChunkAccumulator._tcs_id(),
                        seq=0,
                        data=ToolCallStartedData(
                            thread_id=acc.thread_id,
                            tool_call_id=pending.tool_call_id,
                            tool_name=pending.name,
                            args_truncated=args_repr[:200],
                        ),
                    )
                )
            pending.started_emitted = True

    # 3. finish_reason transitions.
    if finish_reason == "tool_calls":
        # Each finish_reason="tool_calls" frame closes one model turn;
        # bump the turn counter once per such frame.
        acc.cap_counters["turns"] = int(acc.cap_counters.get("turns", 0)) + 1

        for pending in list(acc.tool_calls_by_id.values()):
            if pending.completed_emitted:
                continue
            acc.cap_counters["tool_calls"] = (
                int(acc.cap_counters.get("tool_calls", 0)) + 1
            )
            pending.completed_emitted = True

            # Persist a generic audit row for the assistant_message JSONB.
            acc.tool_calls_log.append(
                {
                    "tool_call_id": pending.tool_call_id,
                    "tool_name": pending.name,
                    "args": pending.args_buffer,
                    "ok": True,
                }
            )

            # Branch on tool name. We don't know the result body here —
            # the OpenClaw round-trip happens server-side and we only see
            # the upstream's followup turn — so we treat completion as
            # success unless a future error frame says otherwise. The
            # `current_insight_id`/`finalize_seen` advances happen via
            # the driver after it inspects MCP results; this translator
            # advances only on the agent's tool_call_complete signal.
            if pending.name == "persist_insight":
                # Insight idx was recorded on `started`; the driver will
                # patch `acc.current_insight_id` after observing the MCP
                # tool body's return envelope. We emit InsightComplete
                # with the placeholder id; the driver may emit a richer
                # follow-up event if it captures the real UUID.
                insight_id_for_event = (
                    acc.current_insight_id or pending.tool_call_id
                )
                out.append(
                    InsightCompleteEvent(
                        event_id=ChunkAccumulator._tcc_id(),
                        seq=0,
                        data=InsightCompleteData(
                            insight_id=insight_id_for_event,
                            headline=_safe_parse_args(pending.args_buffer).get(
                                "headline", ""
                            )[:140] or "(insight persisted)",
                            confidence="medium",
                            materiality="medium",
                            skills_run=["agentic_synthesis"],
                        ),
                    )
                )
                acc.current_insight_idx += 1
                acc.total_insights_persisted += 1
            elif pending.name == "finalize_session":
                acc.finalize_seen = True
                parsed_args = _safe_parse_args(pending.args_buffer)
                status_arg = parsed_args.get("status", "complete")
                # SessionCompleteData's budget_status enum is "ok" | "clipped".
                # The agent's textual "succeeded"/"partial"/"failed"/"complete"/
                # "degraded" maps onto this enum: succeeded/complete -> ok,
                # everything else -> clipped.
                budget = "ok" if status_arg in ("succeeded", "complete") else "clipped"
                out.append(
                    SessionCompleteEvent(
                        event_id=ChunkAccumulator._mco_id(),
                        seq=0,
                        data=SessionCompleteData(
                            session_id=acc.session_id,
                            insights_emitted=acc.total_insights_persisted,
                            duration_ms=0,
                            budget_status=budget,  # type: ignore[arg-type]
                        ),
                    )
                )
                acc.finished = True
            else:
                out.append(
                    ToolCallCompleteEvent(
                        event_id=ChunkAccumulator._tcc_id(),
                        seq=0,
                        data=ToolCallCompleteData(
                            thread_id=acc.thread_id,
                            tool_call_id=pending.tool_call_id,
                            ok=True,
                            latency_ms=0,
                            error_code=None,
                        ),
                    )
                )
    elif finish_reason in ("stop", "length", "content_filter"):
        # Bump turn counter for the final assistant turn.
        acc.cap_counters["turns"] = int(acc.cap_counters.get("turns", 0)) + 1
        if not acc.finalize_seen and not acc.finished:
            out.append(_synthesis_session_complete(acc, status="degraded"))
        acc.finished = True

    return out


def _synthesis_session_complete(
    acc: SynthesisChunkAccumulator, *, status: str
) -> SessionCompleteEvent:
    """Build a synthetic SessionCompleteEvent for degraded close.

    Maps the agentic status vocabulary onto the SessionCompleteData
    enum (which only knows "ok" | "clipped").
    """
    budget = "ok" if status in ("succeeded", "complete") else "clipped"
    return SessionCompleteEvent(
        event_id=ChunkAccumulator._mco_id(),
        seq=0,
        data=SessionCompleteData(
            session_id=acc.session_id,
            insights_emitted=acc.total_insights_persisted,
            duration_ms=0,
            budget_status=budget,  # type: ignore[arg-type]
        ),
    )


def translate_sse_lines(
    lines: Iterable[str], acc: ChunkAccumulator
) -> Iterable[TranslatedEvent]:
    """Pump a line stream through `translate_chunk`.

    Useful in tests; the real forwarder uses an async iterator and
    calls `translate_chunk` directly.
    """
    for line in lines:
        if not line:
            continue
        if not line.startswith("data:"):
            # event:, id:, retry: etc. — ignored at this layer.
            continue
        body = line[len("data:") :]
        parsed = parse_sse_data_field(body)
        if parsed is None:
            continue
        for evt in translate_chunk(parsed, acc):
            yield evt
