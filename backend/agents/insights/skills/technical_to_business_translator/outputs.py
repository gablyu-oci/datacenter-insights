from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TechnicalToBusinessTranslatorOutputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_statement: str = Field(..., min_length=1, max_length=600)
    # True if rewriting necessarily dropped a unit of precision the
    # original statement carried (e.g. losing a confidence interval).
    lost_precision_flag: bool = False
