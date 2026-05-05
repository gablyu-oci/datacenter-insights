from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    last_ingested_at: Optional[datetime] = None
    sla_days: int = 14


class DataQualityAuditInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[SourceRef] = Field(default_factory=list)
    now: Optional[datetime] = None
