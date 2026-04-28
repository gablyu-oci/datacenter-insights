"""
Lineage + Coverage envelope schemas per Phase 0 spec.
Wraps all API responses with source-link metadata.

LineageEnvelope[T]: data, lineage{source_url, retrieved_at, parser_version, confidence}
CoverageEnvelope[T]: extends with coverage{pillar, states_included, states_excluded_with_reason, freshness_status}

Existing endpoints wrap their responses in these envelopes WITHOUT
changing the data shape (frontend reads .data; lineage/coverage are additive).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class LineageMeta(BaseModel):
    """Source provenance metadata attached to every API response."""
    source_url: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    parser_version: Optional[str] = None
    confidence: Optional[float] = None


class CoverageMeta(BaseModel):
    """Per-response coverage disclosure so the UI can render badges."""
    pillar: Optional[str] = None
    states_included: Optional[List[str]] = None
    states_excluded_with_reason: Optional[Dict[str, str]] = None
    freshness_status: Optional[str] = None  # "ok" | "stale" | "unknown"


class LineageEnvelope(BaseModel, Generic[T]):
    """Standard envelope wrapping any API response with lineage."""
    data: T
    lineage: Optional[LineageMeta] = None


class CoverageEnvelope(BaseModel, Generic[T]):
    """Extended envelope adding coverage metadata alongside lineage."""
    data: T
    lineage: Optional[LineageMeta] = None
    coverage: Optional[CoverageMeta] = None


class ErrorDetail(BaseModel):
    code: str
    message: str
    detail: Optional[str] = None


class SourceMeta(BaseModel):
    """Backward-compat source meta for PagedResponse."""
    source_url: str
    retrieved_at: datetime
    parser_version: str
    confidence: float


class PagedResponse(BaseModel, Generic[T]):
    data: List[T]  # type: ignore[type-var]
    total: int
    page: int
    page_size: int
    colors: Optional[Dict[str, str]] = None
    sources: Optional[List[SourceMeta]] = None
