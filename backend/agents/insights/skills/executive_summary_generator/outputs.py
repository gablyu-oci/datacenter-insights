from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ExecutiveSummaryGeneratorOutputs(BaseModel):
    """Per SKILL_CONVERSION.md S4.2 row 8.

    A compact exec-readable rollup of N session insights.
    """

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(..., min_length=1, max_length=1200)
    top_3_takeaways: list[str] = Field(..., min_length=1, max_length=3)
    call_to_action: str = Field(..., min_length=1, max_length=400)
