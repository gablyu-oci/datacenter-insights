from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MetricUnit = Literal["GW", "MW", "USD", "count", "pct"]


class BreakdownEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    value: float


class BusinessMetricsCalculatorOutputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric_name: str
    value: float
    unit: MetricUnit
    breakdown: list[BreakdownEntry] = Field(default_factory=list)
    inputs_seen: int = 0
    notes: list[str] = Field(default_factory=list)
