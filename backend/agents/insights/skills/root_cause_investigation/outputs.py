from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RankedCause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cause: str
    rank: int = Field(..., ge=1)
    rationale: str
    likelihood: float = Field(..., ge=0.0, le=1.0)


class RootCauseInvestigationOutputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ranked: list[RankedCause] = Field(default_factory=list)
    recommended_followups: list[str] = Field(default_factory=list)
