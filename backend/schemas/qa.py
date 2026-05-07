"""
Pydantic v2 event types for the Datacenter Q&A streaming feature.

The agent yields a discriminated union of QAEvent values; each is serialised
to a single SSE `data:` line by the route handler in routers/qa.py.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class TextChunkEvent(BaseModel):
    type: Literal["text_chunk"] = "text_chunk"
    content: str


class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool_name: str
    args: dict


class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_name: str
    summary: str
    row_count: int


class ChartSpec(BaseModel):
    chart_type: Literal[
        "bar",
        "stacked_bar",
        "grouped_bar",
        "pie",
        "donut",
        "line",
        "area",
        "stacked_area",
        "sparkline",
        "scatter",
        "bubble",
        "kpi_tile",
        "table",
        "treemap",
        "radar",
        "histogram",
    ]
    x: str
    y: str
    series: list[dict]
    title: str
    source_table: str
    breakdown_by: Optional[str] = None
    reasoning: Optional[str] = None


class ChartSpecEvent(BaseModel):
    type: Literal["chart_spec"] = "chart_spec"
    chart_type: Literal[
        "bar",
        "stacked_bar",
        "grouped_bar",
        "pie",
        "donut",
        "line",
        "area",
        "stacked_area",
        "sparkline",
        "scatter",
        "bubble",
        "kpi_tile",
        "table",
        "treemap",
        "radar",
        "histogram",
    ]
    x: str
    y: str
    series: list[dict]
    title: str
    source_table: str
    breakdown_by: Optional[str] = None
    reasoning: Optional[str] = None


class Citation(BaseModel):
    table: str
    # row_id is a string so we can carry composite ids without coercing.
    row_id: Optional[str] = None
    source_url: Optional[str] = None
    label: str


class CitationEvent(BaseModel):
    type: Literal["citation"] = "citation"
    table: str
    row_id: Optional[str] = None
    source_url: Optional[str] = None
    label: str


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


QAEvent = Annotated[
    Union[
        TextChunkEvent,
        ToolCallEvent,
        ToolResultEvent,
        ChartSpecEvent,
        CitationEvent,
        DoneEvent,
        ErrorEvent,
    ],
    Field(discriminator="type"),
]


class AskRequest(BaseModel):
    question: str
    history: list[Message] = []
    # Per-chat-panel-instance session id — namespaces OpenClaw memory so
    # different panel instances asking identical questions don't collide
    # in the gateway's per-session cache (which would short-circuit
    # tool calls). Optional for backward compatibility; when omitted the
    # forwarder hashes the question, with the documented downside that
    # repeat questions hit the same memory partition.
    session_id: Optional[str] = None
