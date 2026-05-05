from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProgrammaticEdaInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[dict[str, Any]] = Field(default_factory=list)
    grain: str = Field(default="row", max_length=120)
    sample_size: int = Field(default=10_000, ge=1, le=10_000)
    columns: list[str] | None = None
