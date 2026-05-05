"""Inclusive-boundary lock for is_duplicate cosine threshold (V1 followup).

PRD §5.1: "reject if cosine ≥ 0.85". The `>=` (inclusive) boundary is
intentional — at EXACTLY 0.85 we declare duplicate. This test pins that
behavior so a future tweak to `>` doesn't silently let through a borderline
near-duplicate.

We mock `_embed_one` so the cosine value is deterministic.
"""
from __future__ import annotations

import math

import pytest

from agents.insights import dedup as dedup_mod
from agents.insights.dedup import DEFAULT_COSINE_THRESHOLD, _cosine, is_duplicate


@pytest.mark.asyncio
async def test_cosine_exactly_at_threshold_is_duplicate(monkeypatch):
    """cosine == 0.85 EXACTLY -> duplicate (PRD §5.1 inclusive boundary)."""
    cos_t = DEFAULT_COSINE_THRESHOLD  # 0.85
    sin_t = math.sqrt(max(0.0, 1.0 - cos_t * cos_t))

    target_vec = [1.0, 0.0]
    prior_vec = [cos_t, sin_t]

    # Sanity-check the geometry.
    assert abs(_cosine(target_vec, prior_vec) - DEFAULT_COSINE_THRESHOLD) < 1e-9

    async def fake_embed(text: str):
        return target_vec

    monkeypatch.setattr(dedup_mod, "_embed_one", fake_embed)

    priors = [("zzzz qqqq", prior_vec)]  # tokens disjoint -> Jaccard prefilter skipped
    out = await is_duplicate("totally distinct headline", priors)
    assert out is True, "cosine == 0.85 must be flagged as duplicate per PRD §5.1"


@pytest.mark.asyncio
async def test_cosine_below_threshold_is_not_duplicate(monkeypatch):
    """cosine == 0.84 (just under) -> NOT a duplicate."""
    cos_t = 0.84
    sin_t = math.sqrt(max(0.0, 1.0 - cos_t * cos_t))

    target_vec = [1.0, 0.0]
    prior_vec = [cos_t, sin_t]

    # Sanity-check the geometry.
    assert abs(_cosine(target_vec, prior_vec) - 0.84) < 1e-9

    async def fake_embed(text: str):
        return target_vec

    monkeypatch.setattr(dedup_mod, "_embed_one", fake_embed)

    priors = [("zzzz qqqq", prior_vec)]
    out = await is_duplicate("totally distinct headline", priors)
    assert out is False, "cosine == 0.84 is below threshold; must NOT be duplicate"


@pytest.mark.asyncio
async def test_cosine_just_above_threshold_is_duplicate(monkeypatch):
    """cosine == 0.86 -> duplicate (well above threshold)."""
    cos_t = 0.86
    sin_t = math.sqrt(max(0.0, 1.0 - cos_t * cos_t))

    target_vec = [1.0, 0.0]
    prior_vec = [cos_t, sin_t]

    async def fake_embed(text: str):
        return target_vec

    monkeypatch.setattr(dedup_mod, "_embed_one", fake_embed)

    priors = [("zzzz qqqq", prior_vec)]
    out = await is_duplicate("totally distinct headline", priors)
    assert out is True
