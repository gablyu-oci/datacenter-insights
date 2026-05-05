from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class InsightCardSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str
    body: str | None = None


class ExecutiveSummaryGeneratorInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    insights: list[InsightCardSummary] = Field(..., min_length=1, max_length=20)
