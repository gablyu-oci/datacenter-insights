from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TSPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ts: str
    value: float
    series: str | None = None


class TimeSeriesAnalysisInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: list[TSPoint] = Field(default_factory=list)
    z_threshold: float = Field(default=3.0, ge=1.0, le=10.0)
