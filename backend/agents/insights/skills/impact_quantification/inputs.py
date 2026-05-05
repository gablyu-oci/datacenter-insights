from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ImpactQuantificationInputs(BaseModel):
    """SKILL_CONVERSION §S4.2 row 11.

    Convert a qualitative claim into a quantitative magnitude and a range,
    grounded in the supplied supporting rows.
    """

    model_config = ConfigDict(extra="forbid")

    claim: str = Field(..., min_length=1, max_length=400)
    supporting_rows: list[dict[str, Any]] = Field(default_factory=list)
    unit: str = Field(
        ...,
        min_length=1,
        max_length=16,
        description="Unit of measurement (e.g. GW, MW, USD, count, %).",
    )
