"""Dedup cosine-similarity tests (AI Insights V1).

The production `is_duplicate()` couples a Jaccard pre-filter with a real
embedding call. We bypass both: we test the cosine math directly via
`_cosine`, and we test `is_duplicate` end-to-end with a stubbed embedder
so no LLM is touched.

NOTE: matches current dedup.py behavior — comparison is `>=`
(see agents/insights/dedup.py line 88: `if _cosine(target_vec, vec) >= cosine_threshold`).
Verify against PRD C-1 / TASKS.md T2.
"""
from __future__ import annotations

import pytest

from agents.insights import dedup as dedup_mod
from agents.insights.dedup import DEFAULT_COSINE_THRESHOLD, _cosine, is_duplicate


# ---------------------------------------------------------------------------
# Pure cosine math
# ---------------------------------------------------------------------------


def test_cosine_near_identical_vectors_high():
    # Two near-identical vectors -> cosine ~ 1.0 (well above 0.85)
    u = [1.0, 0.5, 0.2, 0.1]
    v = [1.01, 0.49, 0.21, 0.11]
    sim = _cosine(u, v)
    assert sim >= 0.95, f"expected near-identical vectors to be >= 0.95, got {sim}"


def test_cosine_orthogonal_vectors_zero():
    u = [1.0, 0.0]
    v = [0.0, 1.0]
    sim = _cosine(u, v)
    assert abs(sim) < 1e-9, f"orthogonal vectors must be ~0.0, got {sim}"


# ---------------------------------------------------------------------------
# is_duplicate() with stubbed embedder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_duplicate_returns_true_for_near_identical(monkeypatch):
    # Stub _embed_one so we don't hit the LLM.
    target_vec = [1.0, 0.0]

    async def fake_embed(text: str):
        return target_vec

    monkeypatch.setattr(dedup_mod, "_embed_one", fake_embed)

    # Prior headline shares no token vocabulary with the new one to
    # bypass the Jaccard pre-filter, but its embedding is identical.
    priors = [("zzzz qqqq", [1.0, 0.0])]
    out = await is_duplicate("brand new wholly distinct headline", priors)
    assert out is True


@pytest.mark.asyncio
async def test_is_duplicate_returns_false_for_orthogonal(monkeypatch):
    async def fake_embed(text: str):
        return [1.0, 0.0]

    monkeypatch.setattr(dedup_mod, "_embed_one", fake_embed)

    priors = [("zzzz qqqq", [0.0, 1.0])]  # orthogonal
    out = await is_duplicate("brand new wholly distinct headline", priors)
    assert out is False


@pytest.mark.asyncio
async def test_is_duplicate_boundary_at_threshold(monkeypatch):
    """Threshold semantics: dedup.py uses `>=`, so cosine == 0.85 IS a duplicate.

    NOTE: matches current dedup.py behavior; verify against PRD C-1.
    """
    # Construct two unit vectors with exact cosine = DEFAULT_COSINE_THRESHOLD (0.85).
    # u = (1, 0); v = (cos t, sin t) where cos t = 0.85.
    import math

    cos_t = DEFAULT_COSINE_THRESHOLD
    sin_t = math.sqrt(max(0.0, 1.0 - cos_t * cos_t))

    target_vec = [1.0, 0.0]
    prior_vec = [cos_t, sin_t]

    # Sanity-check the geometry before relying on it.
    assert abs(_cosine(target_vec, prior_vec) - DEFAULT_COSINE_THRESHOLD) < 1e-9

    async def fake_embed(text: str):
        return target_vec

    monkeypatch.setattr(dedup_mod, "_embed_one", fake_embed)

    priors = [("zzzz qqqq", prior_vec)]
    out = await is_duplicate("brand new wholly distinct headline", priors)
    # `>=` semantics: at exactly the threshold we ARE a duplicate.
    assert out is True


@pytest.mark.asyncio
async def test_is_duplicate_empty_priors_returns_false():
    out = await is_duplicate("anything", [])
    assert out is False


def test_dedup_module_imports():
    """Lock the import path so we don't regress to backend.llm.* (cwd=backend/)."""
    import importlib
    mod = importlib.import_module("agents.insights.dedup")
    assert callable(mod._embed_one)
    assert callable(mod.is_duplicate)
