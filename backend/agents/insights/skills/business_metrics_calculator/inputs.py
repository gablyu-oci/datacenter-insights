from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MetricName = Literal[
    "gw_total",
    "contracted_renewable_share",
    "gap_vs_implied",
    "deals_per_quarter",
]


class BusinessMetricsCalculatorInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_name: MetricName
    rows: list[dict[str, Any]] = Field(default_factory=list)
    filters: dict[str, Any] | None = None
