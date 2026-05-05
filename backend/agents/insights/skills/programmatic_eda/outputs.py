from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ColumnStat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    dtype: str
    null_pct: float
    distinct: int
    stats: dict[str, Any] = Field(default_factory=dict)
    skew_flag: bool = False


class ProgrammaticEdaOutputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_rows: int
    n_cols: int
    grain: str
    columns: list[ColumnStat]
    top_issues: list[str] = Field(default_factory=list)
