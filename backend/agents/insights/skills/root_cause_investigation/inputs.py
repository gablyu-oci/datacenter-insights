from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RootCauseInvestigationInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anomaly: str = Field(..., min_length=1, max_length=400)
    candidate_causes: list[str] = Field(default_factory=list)
    context: str = Field(default="", max_length=2000)
