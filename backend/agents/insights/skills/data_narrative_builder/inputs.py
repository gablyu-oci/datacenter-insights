from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

NarrativeAudience = Literal["ceo", "vp", "director", "analyst"]


class DataNarrativeBuilderInputs(BaseModel):
    """Stitch an insight + chart_spec into a card body. SKILL_CONVERSION §S4.2 row 10."""

    model_config = ConfigDict(extra="forbid")

    # Loose dict shapes are intentional — the dispatcher already serialised
    # the parent insight + chart_spec to JSON before passing them in.
    insight: dict[str, Any] = Field(
        ...,
        description="Insight payload (headline, body, materiality, confidence...).",
    )
    chart_spec: dict[str, Any] = Field(
        ...,
        description="ChartSpec dict (chart_type, title, encoding, data_source...).",
    )
    audience: NarrativeAudience = "vp"
