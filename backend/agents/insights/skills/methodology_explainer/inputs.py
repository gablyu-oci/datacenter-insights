from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SkillInvocationRecord(BaseModel):
    """Compact projection of a skill_invocation row passed to the explainer."""

    model_config = ConfigDict(extra="ignore")

    skill_name: str
    inputs_hash: str | None = None
    outputs: dict[str, Any] | None = None
    latency_ms: int | None = None


class MethodologyExplainerInputs(BaseModel):
    """Inputs for methodology_explainer skill (V2)."""

    model_config = ConfigDict(extra="forbid")

    insight_id: str = Field(..., min_length=1, max_length=64)
    persisted_skill_invocations: list[SkillInvocationRecord] = Field(
        default_factory=list, max_length=50
    )
    chart_spec: dict[str, Any] | None = None
