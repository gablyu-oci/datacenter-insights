from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DataNarrativeBuilderOutputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(..., min_length=1, max_length=160)
    body_md: str = Field(..., min_length=1, max_length=900)
    caption: str = Field(..., min_length=1, max_length=200)
