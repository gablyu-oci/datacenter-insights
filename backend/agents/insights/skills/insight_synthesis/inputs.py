from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InsightSynthesisInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis: str = Field(..., min_length=1, max_length=400)
    supporting_rows: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] | None = None
