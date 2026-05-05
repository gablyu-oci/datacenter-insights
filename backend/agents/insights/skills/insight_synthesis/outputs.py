from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ConfidenceSignal = Literal["weak", "moderate", "strong"]


class InsightSynthesisOutputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1, max_length=500)
    confidence_signal: ConfidenceSignal = "moderate"
