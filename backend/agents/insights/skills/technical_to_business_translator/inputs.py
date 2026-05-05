from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TranslationAudience = Literal["ceo", "vp", "director"]


class TechnicalToBusinessTranslatorInputs(BaseModel):
    """SKILL_CONVERSION §S4.2 row 12.

    Convert a technical statement (e.g., "L2 implied GW = 4.4") into
    exec-readable business language.
    """

    model_config = ConfigDict(extra="forbid")

    technical_statement: str = Field(..., min_length=1, max_length=800)
    audience: TranslationAudience = "vp"
    glossary_hints: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Optional term -> definition map the agent should preserve when "
            "rewriting (e.g. {'L2': 'NVIDIA-revenue-implied datacenter GW'})."
        ),
    )
