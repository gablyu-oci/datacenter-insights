from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VisualizationBuilderInputs(BaseModel):
    """Input for the visualization-builder skill.

    Per SKILL_CONVERSION.md S4.2 row 9. The skill is prompt-only — the
    matplotlib chart_builder.py script is intentionally NOT ported. After
    the LLM returns its recommendation, tool.py runs a deterministic
    JSON-Schema validation against the chart_spec.schema.json `Encoding`
    sub-schema.
    """

    model_config = ConfigDict(extra="forbid")

    # data_shape describes the columns (name/type/cardinality) so the LLM
    # can pick a sensible chart type without seeing the rows themselves.
    data_shape: dict[str, Any] = Field(
        ...,
        description=(
            "Shape descriptor with at minimum {n_rows: int, columns: "
            "[{name: str, type: 'category'|'time'|'quantitative', "
            "distinct_n?: int}]}."
        ),
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=400,
        description="The single declarative message the chart should communicate.",
    )
    target: str | None = Field(
        default=None,
        description=(
            "Optional desired chart type from the closed Recharts set. If "
            "supplied the LLM still validates and may override with a "
            "rationale."
        ),
    )
