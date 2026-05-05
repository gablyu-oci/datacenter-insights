from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CandidateInsight(BaseModel):
    """The minimal projection of a candidate insight the reviewer needs."""

    model_config = ConfigDict(extra="ignore")

    headline: str = Field(..., min_length=1, max_length=300)
    body: str | None = Field(default=None, max_length=2000)
    confidence: Literal["low", "medium", "high"] | None = None
    materiality: Literal["low", "medium", "high"] | None = None


class CitationLite(BaseModel):
    """A flat citation projection used by the reviewer."""

    model_config = ConfigDict(extra="ignore")

    url: str
    title: str | None = None
    snippet: str | None = None
    agree_or_disagree: Literal["agree", "disagree", "context"] | None = None
    rationale: str | None = None


class PeerReviewTemplateInputs(BaseModel):
    """Inputs for peer_review_template (V2)."""

    model_config = ConfigDict(extra="forbid")

    candidate_insight: CandidateInsight
    chart_spec: dict[str, Any] | None = None
    citations: list[CitationLite] = Field(default_factory=list, max_length=10)
