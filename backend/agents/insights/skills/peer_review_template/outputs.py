from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PeerReviewChecklist(BaseModel):
    """Boolean rubric per PRD §5.1 (specific, supported, non-trivial, material)."""

    model_config = ConfigDict(extra="forbid")

    specific: bool
    supported: bool
    non_trivial: bool
    material: bool


class PeerReviewTemplateOutputs(BaseModel):
    """Verdict + checklist + suggestions."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["pass", "revise", "reject"]
    checklist: PeerReviewChecklist
    suggestions: list[str] = Field(default_factory=list, max_length=10)
