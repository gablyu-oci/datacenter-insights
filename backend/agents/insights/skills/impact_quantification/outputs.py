from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ImpactQuantificationOutputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    impact_value: float
    impact_unit: str = Field(..., min_length=1, max_length=16)
    range_lo: float
    range_hi: float
    basis: str = Field(..., min_length=1, max_length=600)
