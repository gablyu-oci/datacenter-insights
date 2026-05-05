from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Closed set — must remain a strict subset of ChartSpec.ChartType. We expose
# six high-level families to the agent (per kickoff §S4.2 row 9 spec). The
# agent later expands `bar` -> `bar`/`stacked_bar`/`grouped_bar` etc. when
# composing the full ChartSpec.
RecommendedChartType = Literal[
    "line",
    "bar",
    "area",
    "scatter",
    "heatmap",
    "table",
]


class VisualizationBuilderOutputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommended_type: RecommendedChartType
    encoding: dict[str, Any] = Field(
        ...,
        description=(
            "Encoding object aligning with chart_spec.Encoding: "
            "{x: {field, type}, y: {field, type}, series?: {field}, ...}"
        ),
    )
    rationale: str = Field(..., min_length=1, max_length=500)
