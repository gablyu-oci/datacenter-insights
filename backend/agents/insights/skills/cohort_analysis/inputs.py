from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CohortAnalysisInputs(BaseModel):
    """Inputs for cohort_analysis skill.

    Per SKILL_CONVERSION.md S4.2 row 13: build a cohort x time matrix from a
    flat row set, computing simple retention-style fractions. The agent
    supplies the rows from a prior `query_database` call.
    """

    model_config = ConfigDict(extra="forbid")

    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=10_000)
    cohort_col: str = Field(..., min_length=1, max_length=64)
    event_col: str = Field(..., min_length=1, max_length=64)
    time_col: str = Field(..., min_length=1, max_length=64)
    periods: int = Field(default=12, ge=1, le=60)
