from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    n_rows: int
    value: float
    share_of_total: float = Field(..., ge=0.0, le=1.0)
    z_score: float | None = None


class SegmentationAnalysisOutputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segments: list[Segment] = Field(default_factory=list)
    outlier_segments: list[Segment] = Field(default_factory=list)
    total_value: float = 0.0
    notes: list[str] = Field(default_factory=list)
