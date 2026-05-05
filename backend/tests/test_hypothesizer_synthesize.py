"""Unit tests for `agents.insights.hypothesizer.synthesize_insights`.

We never hit the real LLM. Two strategies:
  1. AI_INSIGHTS_FAKE_LLM env var -- the production path short-circuits
     and parses the value as JSON.
  2. Monkeypatch `llm_client.reason` -- ensures NO real LLM call happens
     even when the env var is set.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from agents.insights import hypothesizer as hyp_mod
from agents.insights.hypothesizer import (
    FactPack,
    FactRow,
    FactSection,
    InsightOutput,
    synthesize_insights,
)


@pytest.fixture(autouse=True)
def _no_fake_llm(monkeypatch):
    monkeypatch.delenv("AI_INSIGHTS_FAKE_LLM", raising=False)


def _empty_pack() -> FactPack:
    return FactPack(generated_at=datetime.now(timezone.utc), sections=[])


def _single_row_pack() -> FactPack:
    return FactPack(
        generated_at=datetime.now(timezone.utc),
        sections=[
            FactSection(
                name="s1",
                description="single section",
                rows=[FactRow(row_id="s1:0", entity="Microsoft")],
            )
        ],
    )


def _multi_row_pack(n: int) -> FactPack:
    return FactPack(
        generated_at=datetime.now(timezone.utc),
        sections=[
            FactSection(
                name="s1",
                description="multi",
                rows=[FactRow(row_id=f"s1:{i}", entity=f"E{i}") for i in range(n)],
            )
        ],
    )


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_empty_factpack_returns_empty():
    out = await synthesize_insights(_empty_pack())
    assert out == []


@pytest.mark.asyncio
async def test_synthesize_uses_fake_llm_env_var(monkeypatch):
    payload = {
        "insights": [
            {
                "headline": "H1",
                "body": "B1",
                "confidence_signal": "strong",
                "materiality": "high",
                "supporting_row_ids": ["s1:0"],
            }
        ]
    }
    monkeypatch.setenv("AI_INSIGHTS_FAKE_LLM", json.dumps(payload))

    out = await synthesize_insights(_single_row_pack())
    assert len(out) == 1
    ins = out[0]
    assert isinstance(ins, InsightOutput)
    assert ins.headline == "H1"
    assert ins.body == "B1"
    assert ins.confidence_signal == "strong"
    assert ins.materiality == "high"
    assert ins.supporting_row_ids == ["s1:0"]


@pytest.mark.asyncio
async def test_synthesize_drops_unknown_supporting_row_ids(monkeypatch):
    payload = {
        "insights": [
            {
                "headline": "Mixed refs",
                "body": "Some real, some fake row_ids",
                "confidence_signal": "moderate",
                "materiality": "medium",
                "supporting_row_ids": ["s1:0", "ghost:1", "s1:9999"],
            }
        ]
    }
    monkeypatch.setenv("AI_INSIGHTS_FAKE_LLM", json.dumps(payload))

    out = await synthesize_insights(_single_row_pack())
    assert len(out) == 1
    # Only the real row_id survives; phantom refs are filtered.
    assert out[0].supporting_row_ids == ["s1:0"]


@pytest.mark.asyncio
async def test_synthesize_drops_insights_with_no_valid_row_ids(monkeypatch):
    payload = {
        "insights": [
            {
                "headline": "All bogus",
                "body": "no real refs",
                "confidence_signal": "weak",
                "materiality": "low",
                "supporting_row_ids": ["ghost:1", "phantom:2"],
            },
            {
                "headline": "Anchored",
                "body": "real ref",
                "confidence_signal": "strong",
                "materiality": "high",
                "supporting_row_ids": ["s1:0"],
            },
        ]
    }
    monkeypatch.setenv("AI_INSIGHTS_FAKE_LLM", json.dumps(payload))

    out = await synthesize_insights(_single_row_pack())
    headlines = [i.headline for i in out]
    assert "Anchored" in headlines
    assert "All bogus" not in headlines


@pytest.mark.asyncio
async def test_synthesize_truncates_to_max_insights(monkeypatch):
    """12 fake insights -> max_insights=7 returns exactly 7."""
    insights_list = []
    for i in range(12):
        insights_list.append({
            "headline": f"H{i}",
            "body": f"B{i}",
            "confidence_signal": "moderate",
            "materiality": "medium",
            "supporting_row_ids": [f"s1:{i}"],
        })
    monkeypatch.setenv("AI_INSIGHTS_FAKE_LLM", json.dumps({"insights": insights_list}))

    pack = _multi_row_pack(12)
    out = await synthesize_insights(pack, max_insights=7)
    assert len(out) == 7
    # Order preserved: first 7 of the input list.
    assert [i.headline for i in out] == [f"H{i}" for i in range(7)]


@pytest.mark.asyncio
async def test_synthesize_no_real_llm_call(monkeypatch):
    """When AI_INSIGHTS_FAKE_LLM is set, llm_client.reason MUST NOT run."""

    def _explode(*args, **kwargs):
        pytest.fail("LLM was called -- short-circuit broken")

    # The hypothesizer module imports `llm_client` at module import time;
    # patching that attribute on the module works because the call site
    # is `await llm_client.reason(...)` resolved against the module.
    monkeypatch.setattr(hyp_mod.llm_client, "reason", _explode)

    payload = {
        "insights": [
            {
                "headline": "OK",
                "body": "B",
                "confidence_signal": "strong",
                "materiality": "high",
                "supporting_row_ids": ["s1:0"],
            }
        ]
    }
    monkeypatch.setenv("AI_INSIGHTS_FAKE_LLM", json.dumps(payload))

    out = await synthesize_insights(_single_row_pack())
    assert len(out) == 1
    assert out[0].headline == "OK"
