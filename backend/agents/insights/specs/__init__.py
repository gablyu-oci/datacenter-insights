"""Public schema surface for the AI Insights agent.

Re-exports the Pydantic v2 models that backend orchestrator code, tool
implementations, persistence layers, and the frontend type-codegen pipeline
all import. These modules are pure schema — no business logic.

See ARCHITECTURE.md A4 (ChartSpec), A5 (SSE event taxonomy), A6.5 + A9
(SkillContext capability matrix), and SKILL_CONVERSION.md S1.2.
"""

from .chart_spec import (
    Annotation,
    ChartSpec,
    ChartType,
    ColorEncoding,
    DataSource,
    DataSourceKind,
    Encoding,
    SeriesEncoding,
    SizeEncoding,
    Styling,
    XEncoding,
    YEncoding,
)
from .sse_events import (
    ChartEvent,
    CitationEvent,
    ErrorEvent,
    InsightCompleteEvent,
    InsightStartedEvent,
    PingEvent,
    ReasoningStepEvent,
    SessionCompleteEvent,
    SessionStartedEvent,
    SSEEvent,
    SurveyingEvent,
    TokenEvent,
    ToolCallEvent,
    ToolResultEvent,
    to_sse_text,
)
from .skill_context import (
    Capabilities,
    RAGContext,
    RAGRef,
    SkillContext,
)

__all__ = [
    # ChartSpec
    "Annotation",
    "ChartSpec",
    "ChartType",
    "ColorEncoding",
    "DataSource",
    "DataSourceKind",
    "Encoding",
    "SeriesEncoding",
    "SizeEncoding",
    "Styling",
    "XEncoding",
    "YEncoding",
    # SSE events
    "ChartEvent",
    "CitationEvent",
    "ErrorEvent",
    "InsightCompleteEvent",
    "InsightStartedEvent",
    "PingEvent",
    "ReasoningStepEvent",
    "SessionCompleteEvent",
    "SessionStartedEvent",
    "SSEEvent",
    "SurveyingEvent",
    "TokenEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "to_sse_text",
    # SkillContext
    "Capabilities",
    "RAGContext",
    "RAGRef",
    "SkillContext",
]
