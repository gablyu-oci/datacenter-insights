from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SegmentationAnalysisInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[dict[str, Any]] = Field(default_factory=list)
    group_by: str = Field(..., min_length=1, max_length=80)
    metric_field: str | None = Field(default=None, max_length=80)
    agg: Literal["sum", "avg", "count"] = "sum"
    min_segment_size: int = Field(default=1, ge=1, le=1000)
