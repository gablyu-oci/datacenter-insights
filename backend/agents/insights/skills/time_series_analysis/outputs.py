from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TrendDirection = Literal["up", "down", "flat", "unknown"]


class TimeSeriesAnalysisOutputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trend: TrendDirection = "unknown"
    seasonality: str = "unknown"
    anomaly_indices: list[int] = Field(default_factory=list)
    n_points: int = 0
    notes: list[str] = Field(default_factory=list)
