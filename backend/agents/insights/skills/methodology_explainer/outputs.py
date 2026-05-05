from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MethodologyExplainerOutputs(BaseModel):
    """A single markdown blob produced by the explainer."""

    model_config = ConfigDict(extra="forbid")

    methodology_md: str = Field(..., min_length=1, max_length=4000)
