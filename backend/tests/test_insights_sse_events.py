"""SSE event taxonomy round-trip tests (AI Insights V1).

For every SSE event class in agents/insights/specs/sse_events.py, we
construct a minimal valid instance, serialize via model_dump_json(),
parse back via model_validate_json(), and assert key fields equal.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agents.insights.specs import chart_spec as cs_mod
from agents.insights.specs.chart_spec import ChartSpec
from agents.insights.specs.sse_events import (
    ChartEvent,
    ChartEventData,
    CitationEvent,
    CitationEventData,
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
    TokenData,
    TokenEvent,
    ToolCallData,
    ToolCallEvent,
    ToolResultData,
    ToolResultEvent,
    WebCitation,
    to_sse_text,
)

UTC = timezone.utc


def _ts() -> datetime:
    return datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)


def _make_chart_spec() -> ChartSpec:
    rows = [{"x": 1, "y": 2}]
    return ChartSpec.model_validate(
        {
            "chart_id": "c_deadbeef",
            "chart_type": "bar",
            "title": "T",
            "data_source": {
                "kind": "db_query",
                "spec": {"sql": "SELECT 1"},
                "rows": 1,
                "fetched_at": _ts().isoformat(),
                "row_hash": ChartSpec.compute_row_hash(rows),
            },
            "data": rows,
            "encoding": {
                "x": {"field": "x", "type": "quantitative"},
                "y": {"field": "y", "type": "quantitative"},
            },
        }
    )


def _build_session_started():
    return SessionStartedEvent(
        event_id="e1",
        seq=0,
        data=SessionStartedData(
            session_id="s1", model="m", started_at=_ts(), max_insights=5
        ),
    )


def _build_surveying():
    return SurveyingEvent(
        event_id="e2",
        seq=1,
        data=SurveyingData(session_id="s1", candidates_seen=3),
    )


def _build_insight_started():
    return InsightStartedEvent(
        event_id="e3",
        seq=2,
        data=InsightStartedData(session_id="s1", insight_id="i1", index=0),
    )


def _build_token():
    return TokenEvent(
        event_id="e4",
        seq=3,
        data=TokenData(insight_id="i1", field="headline", delta="hello"),
    )


def _build_reasoning_step():
    return ReasoningStepEvent(
        event_id="e5",
        seq=4,
        data=ReasoningStepData(insight_id="i1", step="EDA"),
    )


def _build_tool_call():
    return ToolCallEvent(
        event_id="e6",
        seq=5,
        data=ToolCallData(
            tool_call_id="tc1",
            tool_name="query_database",
            args_truncated="{}",
            started_at=_ts(),
        ),
    )


def _build_tool_result():
    return ToolResultEvent(
        event_id="e7",
        seq=6,
        data=ToolResultData(tool_call_id="tc1", ok=True, latency_ms=42),
    )


def _build_chart_event():
    return ChartEvent(
        event_id="e8",
        seq=7,
        data=ChartEventData(insight_id="i1", chart=_make_chart_spec()),
    )


def _build_citation():
    return CitationEvent(
        event_id="e9",
        seq=8,
        data=CitationEventData(
            insight_id="i1",
            citation=WebCitation(
                url="https://example.com",
                title="t",
                snippet="snip",
                agree_or_disagree="agree",
                rationale="r",
                search_query="q",
                retrieved_at=_ts(),
            ),
        ),
    )


def _build_insight_complete():
    return InsightCompleteEvent(
        event_id="e10",
        seq=9,
        data=InsightCompleteData(
            insight_id="i1",
            headline="h",
            confidence="medium",
            materiality="high",
            skills_run=["eda"],
        ),
    )


def _build_session_complete():
    return SessionCompleteEvent(
        event_id="e11",
        seq=10,
        data=SessionCompleteData(
            session_id="s1",
            insights_emitted=3,
            duration_ms=1234,
            budget_status="ok",
        ),
    )


def _build_error():
    return ErrorEvent(
        event_id="e12",
        seq=11,
        data=ErrorData(code="x", message="boom", retryable=False),
    )


def _build_ping():
    return PingEvent(event_id="e13", seq=12)


ALL_BUILDERS = [
    ("session_started", _build_session_started),
    ("surveying", _build_surveying),
    ("insight_started", _build_insight_started),
    ("token", _build_token),
    ("reasoning_step", _build_reasoning_step),
    ("tool_call", _build_tool_call),
    ("tool_result", _build_tool_result),
    ("chart", _build_chart_event),
    ("citation", _build_citation),
    ("insight_complete", _build_insight_complete),
    ("session_complete", _build_session_complete),
    ("error", _build_error),
    ("ping", _build_ping),
]


@pytest.mark.parametrize("name,builder", ALL_BUILDERS, ids=[n for n, _ in ALL_BUILDERS])
def test_event_round_trips_json(name, builder):
    ev = builder()
    payload = ev.model_dump_json()
    assert isinstance(payload, str) and payload.startswith("{")

    cls = type(ev)
    reparsed = cls.model_validate_json(payload)
    assert reparsed.event_id == ev.event_id
    assert reparsed.seq == ev.seq
    assert getattr(reparsed, "event") == name


def test_to_sse_text_wire_format():
    """Spot-check the on-wire SSE frame shape for one event."""
    ev = _build_token()
    frame = to_sse_text(ev)
    assert frame.startswith("id: e4\n")
    assert "event: token\n" in frame
    assert "\ndata: " in frame
    # SSE frames are terminated by a blank line.
    assert frame.endswith("\n\n")


def test_all_thirteen_event_classes_covered():
    """Guard: ARCH A5 enumerates 13 SSE event types — make sure we exercise all of them."""
    assert len(ALL_BUILDERS) == 13
