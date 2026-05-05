from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


FreshnessFlag = Literal["fresh", "stale", "unknown"]


class SourceFreshness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    flag: FreshnessFlag
    age_days: float | None = None
    sla_days: int


class DataQualityAuditOutputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[SourceFreshness] = Field(default_factory=list)
    n_fresh: int = 0
    n_stale: int = 0
    n_unknown: int = 0
