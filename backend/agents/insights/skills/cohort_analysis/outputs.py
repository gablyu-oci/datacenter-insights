from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CohortRetentionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_cohorts: int = Field(..., ge=0)
    n_periods: int = Field(..., ge=0)
    mean_period1_retention: float | None = None
    largest_cohort_key: str | None = None
    largest_cohort_size: int = 0
    biggest_drop_off: dict[str, float | str] | None = Field(
        default=None,
        description="`{cohort, from_period, to_period, drop}` for the largest cohort drop, if any",
    )


class CohortAnalysisOutputs(BaseModel):
    """A pure numerical cohort table.

    `matrix[i][j]` is the retention fraction for cohort `cohort_keys[i]` at
    relative period `j` (j=0 is the cohort's first period; values in
    [0.0, 1.0]). Row 0 of every cohort is 1.0 by construction.

    `notes` carries any caveats applied during the build (truncations,
    skipped null cohorts, etc.).
    """

    model_config = ConfigDict(extra="forbid")

    matrix: list[list[float]] = Field(default_factory=list)
    cohort_keys: list[str] = Field(default_factory=list)
    cohort_sizes: list[int] = Field(default_factory=list)
    retention_summary: CohortRetentionSummary
    notes: list[str] = Field(default_factory=list)
