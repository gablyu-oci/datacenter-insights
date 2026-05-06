"""Pure-function tests for `translate_synthesis_chunk` + `SynthesisChunkAccumulator`.

PRD/ARCH: docs/plans/ai-insights-automation/14-unified-agent-architecture.md §5.

These tests run with NO HTTP and NO DB. The synthesis translator is the
sibling of the chat-lane `translate_chunk`; chat-lane is required to stay
byte-identical (PRD AC-4 / FR-X.6) so test 8 confirms both translators
coexist and the chat translator still works.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from agents.insights.specs.sse_events import (  # noqa: E402
    AssistantMessageTokenEvent,
    ChartEvent,
    ErrorEvent,
    InsightCompleteEvent,
    InsightStartedEvent,
    MessageCompleteEvent,
    ReasoningStepEvent,
    SessionCompleteEvent,
    ToolCallCompleteEvent,
    ToolCallStartedEvent,
)
from openclaw.sse_translator import (  # noqa: E402
    DONE,
    ChunkAccumulator,
    SynthesisChunkAccumulator,
    translate_chunk,
    translate_synthesis_chunk,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_acc() -> SynthesisChunkAccumulator:
    return SynthesisChunkAccumulator(
        session_id="00000000-0000-0000-0000-0000000000aa",
        thread_id="thr_test",
        message_id="msg_test",
        insight_id="",
    )


def _delta_chunk(*, content: str | None = None,
                 tool_call: dict | None = None,
                 finish_reason: str | None = None) -> dict:
    delta: dict = {}
    if content is not None:
        delta["content"] = content
    if tool_call is not None:
        delta["tool_calls"] = [tool_call]
    return {"choices": [{"delta": delta, "finish_reason": finish_reason}]}


# ---------------------------------------------------------------------------
# 1. tool_call_started for persist_insight emits InsightStartedEvent(idx=0);
#    second persist_insight emits idx=1 only AFTER first complete fires.
# ---------------------------------------------------------------------------


def test_persist_insight_started_increments_idx_only_after_complete() -> None:
    acc = _new_acc()

    # First persist_insight start.
    out1 = translate_synthesis_chunk(
        _delta_chunk(
            tool_call={
                "index": 0,
                "id": "call_a",
                "function": {
                    "name": "persist_insight",
                    "arguments": '{"insight":{"headline":"H0"}}',
                },
            }
        ),
        acc,
    )
    started1 = [e for e in out1 if isinstance(e, InsightStartedEvent)]
    assert len(started1) == 1
    assert started1[0].data.index == 0

    # SECOND persist_insight start before first completes — still idx 0.
    out_mid = translate_synthesis_chunk(
        _delta_chunk(
            tool_call={
                "index": 1,
                "id": "call_b",
                "function": {
                    "name": "persist_insight",
                    "arguments": '{"insight":{"headline":"H1"}}',
                },
            }
        ),
        acc,
    )
    started_mid = [e for e in out_mid if isinstance(e, InsightStartedEvent)]
    assert len(started_mid) == 1
    # current_insight_idx is still 0 because no persist_insight has *completed*.
    assert started_mid[0].data.index == 0

    # Now complete both via tool_calls finish_reason. Idx should advance
    # to 1 then 2 as InsightComplete events fire.
    out_done = translate_synthesis_chunk(
        _delta_chunk(finish_reason="tool_calls"), acc
    )
    completes = [e for e in out_done if isinstance(e, InsightCompleteEvent)]
    assert len(completes) == 2
    assert acc.total_insights_persisted == 2
    assert acc.current_insight_idx == 2


# ---------------------------------------------------------------------------
# 2. tool_call_complete for persist_insight emits InsightCompleteEvent
# ---------------------------------------------------------------------------


def test_persist_insight_complete_emits_insight_complete_event() -> None:
    acc = _new_acc()
    translate_synthesis_chunk(
        _delta_chunk(
            tool_call={
                "index": 0,
                "id": "call_a",
                "function": {
                    "name": "persist_insight",
                    "arguments": '{"insight":{"headline":"hello"}}',
                },
            }
        ),
        acc,
    )
    out = translate_synthesis_chunk(
        _delta_chunk(finish_reason="tool_calls"), acc
    )
    completes = [e for e in out if isinstance(e, InsightCompleteEvent)]
    assert len(completes) == 1
    # The translator does not see the MCP envelope, so insight_id falls
    # back to the tool_call_id placeholder; the driver patches this when
    # it observes the result body.
    assert completes[0].data.insight_id == "call_a"


# ---------------------------------------------------------------------------
# 3. tool_call_complete for emit_chart surfaces; we accept either ChartEvent
#    or generic ToolCallCompleteEvent because the synthesis translator
#    today emits a generic complete envelope for non-persist/finalize tools.
#    The orchestrator-level driver promotes the underlying chart spec to
#    a ChartEvent. This test asserts that an emit_chart tool_call results
#    in a *completion* event tagged with the parent insight context.
# ---------------------------------------------------------------------------


def test_emit_chart_complete_surfaces_with_insight_context() -> None:
    acc = _new_acc()
    # First persist an insight so current_insight_id is set.
    translate_synthesis_chunk(
        _delta_chunk(
            tool_call={
                "index": 0,
                "id": "call_ins",
                "function": {
                    "name": "persist_insight",
                    "arguments": '{"insight":{"headline":"H"}}',
                },
            }
        ),
        acc,
    )
    translate_synthesis_chunk(_delta_chunk(finish_reason="tool_calls"), acc)
    parent_idx = acc.current_insight_idx  # snapshot post-complete

    # Now an emit_chart tool call.
    out = translate_synthesis_chunk(
        _delta_chunk(
            tool_call={
                "index": 1,
                "id": "call_chart",
                "function": {
                    "name": "emit_chart",
                    "arguments": '{"chart_id":"c_1","chart_type":"bar"}',
                },
            }
        ),
        acc,
    )
    started = [e for e in out if isinstance(e, ToolCallStartedEvent)]
    assert any(s.data.tool_name == "emit_chart" for s in started)

    out_done = translate_synthesis_chunk(
        _delta_chunk(finish_reason="tool_calls"), acc
    )
    # Either a synthesis-promoted ChartEvent OR a generic ToolCallComplete
    # is acceptable; both carry forward the parent_idx context via
    # acc.current_insight_idx unchanged.
    has_chart_or_complete = any(
        isinstance(e, (ChartEvent, ToolCallCompleteEvent)) for e in out_done
    )
    assert has_chart_or_complete, out_done
    # emit_chart never advances the insight index.
    assert acc.current_insight_idx == parent_idx


# ---------------------------------------------------------------------------
# 4. tool_call_complete for finalize_session emits SessionCompleteEvent
#    and sets acc.finalize_seen=True.
# ---------------------------------------------------------------------------


def test_finalize_session_complete_emits_session_complete() -> None:
    acc = _new_acc()
    translate_synthesis_chunk(
        _delta_chunk(
            tool_call={
                "index": 0,
                "id": "call_fin",
                "function": {
                    "name": "finalize_session",
                    "arguments": '{"status":"complete","token_estimate":1234}',
                },
            }
        ),
        acc,
    )
    out = translate_synthesis_chunk(
        _delta_chunk(finish_reason="tool_calls"), acc
    )
    completes = [e for e in out if isinstance(e, SessionCompleteEvent)]
    assert len(completes) == 1
    assert acc.finalize_seen is True
    # status="complete" maps onto budget_status="ok".
    assert completes[0].data.budget_status == "ok"


# ---------------------------------------------------------------------------
# 5. delta.content text emits ReasoningStepEvent.
# ---------------------------------------------------------------------------


def test_content_delta_emits_reasoning_step() -> None:
    acc = _new_acc()
    out = translate_synthesis_chunk(_delta_chunk(content="thinking..."), acc)
    steps = [e for e in out if isinstance(e, ReasoningStepEvent)]
    assert len(steps) == 1
    # No persist yet -> insight_id falls back to "session" sentinel.
    assert steps[0].data.insight_id == "session"


# ---------------------------------------------------------------------------
# 6. finish_reason="stop" without finalize_session emits degraded
#    SessionCompleteEvent(status="degraded" -> budget_status="clipped").
# ---------------------------------------------------------------------------


def test_stop_without_finalize_emits_degraded_session_complete() -> None:
    acc = _new_acc()
    out = translate_synthesis_chunk(_delta_chunk(finish_reason="stop"), acc)
    completes = [e for e in out if isinstance(e, SessionCompleteEvent)]
    assert len(completes) == 1
    # degraded close -> budget_status mapped to "clipped".
    assert completes[0].data.budget_status == "clipped"
    assert acc.finalize_seen is False
    assert acc.finished is True


# ---------------------------------------------------------------------------
# 7. Cap counter increments on each tool_call_complete.
# ---------------------------------------------------------------------------


def test_cap_counter_tool_calls_increments() -> None:
    acc = _new_acc()
    assert acc.cap_counters.get("tool_calls", 0) == 0
    # Drive 3 distinct tool_calls (web_search) end-to-end.
    for i, call_id in enumerate(("c1", "c2", "c3")):
        translate_synthesis_chunk(
            _delta_chunk(
                tool_call={
                    "index": i,
                    "id": call_id,
                    "function": {
                        "name": "web_search",
                        "arguments": '{"query":"foo"}',
                    },
                }
            ),
            acc,
        )
    # Now finish the model turn — all 3 should complete in one frame.
    translate_synthesis_chunk(
        _delta_chunk(finish_reason="tool_calls"), acc
    )
    assert int(acc.cap_counters["tool_calls"]) == 3
    # And the assistant turn counter incremented exactly once.
    assert int(acc.cap_counters["turns"]) == 1


# ---------------------------------------------------------------------------
# 8. Chat-lane translate_chunk + ChunkAccumulator are untouched.
#    Confirm both translators coexist and chat-lane still works on a
#    canonical chat-style chunk. PRD AC-4 / FR-X.6.
# ---------------------------------------------------------------------------


def test_chat_lane_translator_untouched() -> None:
    chat_acc = ChunkAccumulator(
        thread_id="thr_chat",
        message_id="msg_chat",
        insight_id="ins_chat",
    )
    # Token delta -> AssistantMessageTokenEvent
    out_token = translate_chunk(
        {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]},
        chat_acc,
    )
    assert any(isinstance(e, AssistantMessageTokenEvent) for e in out_token)
    assert chat_acc.assistant_text_seen is True

    # finish_reason=stop -> MessageCompleteEvent (not SessionCompleteEvent;
    # this is the chat lane).
    out_stop = translate_chunk(
        {"choices": [{"delta": {}, "finish_reason": "stop"}]}, chat_acc
    )
    assert any(isinstance(e, MessageCompleteEvent) for e in out_stop)
    assert chat_acc.finished is True

    # And [DONE] on a fresh acc produces a single MessageCompleteEvent.
    fresh = ChunkAccumulator(
        thread_id="t", message_id="m", insight_id="i"
    )
    out_done = translate_chunk(DONE, fresh)
    assert len(out_done) == 1
    assert isinstance(out_done[0], MessageCompleteEvent)


# ---------------------------------------------------------------------------
# 8b. Chat translator NEVER emits synthesis-only events.
#     Belt-and-suspenders for the chat-byte-identical contract.
# ---------------------------------------------------------------------------


def test_chat_translator_does_not_emit_synthesis_events() -> None:
    chat_acc = ChunkAccumulator(
        thread_id="t", message_id="m", insight_id="i"
    )
    # Even on a tool_call delta with name=persist_insight (which a
    # misbehaved chat client could send), the chat translator must
    # emit ToolCallStartedEvent, not InsightStartedEvent.
    out = translate_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_x",
                                "function": {
                                    "name": "persist_insight",
                                    "arguments": "{}",
                                },
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        },
        chat_acc,
    )
    assert any(isinstance(e, ToolCallStartedEvent) for e in out)
    assert not any(isinstance(e, InsightStartedEvent) for e in out)
    assert not any(isinstance(e, SessionCompleteEvent) for e in out)
