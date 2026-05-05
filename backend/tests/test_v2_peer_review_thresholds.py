"""V2 peer_review_template skill tests.

Pins behaviour of `agents/insights/skills/peer_review_template/tool.py`:
- LLM returns {"verdict":"pass", ...} -> output verdict == "pass".
- LLM returns {"verdict":"revise", ...} with issues -> output verdict == "revise".
- LLM raises / returns invalid JSON -> heuristic fallback verdict == "revise".

NOTE (gap vs kickoff brief): the actual verdict enum is
{"pass","revise","reject"} (PRD §5.1 + the Pydantic Outputs Literal). The
brief said "approve". We assert the actual schema.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))
for p in (BACKEND_ROOT, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from agents.insights.skills.peer_review_template.inputs import (  # noqa: E402
    CandidateInsight,
    CitationLite,
    PeerReviewTemplateInputs,
)
from agents.insights.skills.peer_review_template.tool import run as pr_run  # noqa: E402
import backend.llm.client as llm_mod  # noqa: E402


class _FakeTurn:
    def __init__(self, content: str | None) -> None:
        self.content = content
        self.tool_calls = None
        self.model = "fake"
        self.tokens = {}


def _inputs() -> PeerReviewTemplateInputs:
    return PeerReviewTemplateInputs(
        candidate_insight=CandidateInsight(
            headline="Microsoft signed a 12.3 GW power deal with Constellation Energy",
            body="A multi-year compute capacity pact tied to nuclear PPAs.",
            confidence="medium",
            materiality="high",
        ),
        chart_spec={"type": "stacked_bar", "title": "x"},
        citations=[
            CitationLite(
                url="https://example.com/a",
                title="A",
                snippet="Microsoft signed a 12.3 GW deal.",
                agree_or_disagree="agree",
                rationale="Microsoft signed a 12.3 GW deal",
            )
        ],
    )


# ---------------------------------------------------------------------------
# (4a) verdict == "pass"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_pass_verdict(monkeypatch: pytest.MonkeyPatch):
    payload = {
        "verdict": "pass",
        "checklist": {
            "specific": True,
            "supported": True,
            "non_trivial": True,
            "material": True,
        },
        "suggestions": [],
    }

    class _FakeClient:
        async def reason(self, **kwargs: Any) -> _FakeTurn:
            return _FakeTurn(json.dumps(payload))

    monkeypatch.setattr(llm_mod, "llm_client", _FakeClient(), raising=True)
    out = await pr_run(_inputs())
    assert out.verdict == "pass"
    assert out.checklist.specific is True
    assert out.suggestions == []


# ---------------------------------------------------------------------------
# (4b) verdict == "revise" with at least one suggestion.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_revise_verdict(monkeypatch: pytest.MonkeyPatch):
    payload = {
        "verdict": "revise",
        "checklist": {
            "specific": True,
            "supported": False,
            "non_trivial": True,
            "material": True,
        },
        "suggestions": ["Add a corroborating citation with quantitative anchor"],
    }

    class _FakeClient:
        async def reason(self, **kwargs: Any) -> _FakeTurn:
            return _FakeTurn(json.dumps(payload))

    monkeypatch.setattr(llm_mod, "llm_client", _FakeClient(), raising=True)
    out = await pr_run(_inputs())
    assert out.verdict == "revise"
    assert out.checklist.supported is False
    assert len(out.suggestions) >= 1


# ---------------------------------------------------------------------------
# (4c) LLM raises -> deterministic heuristic fallback verdict == "revise".
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_revise(monkeypatch: pytest.MonkeyPatch):
    class _BoomClient:
        async def reason(self, **kwargs: Any) -> _FakeTurn:
            raise RuntimeError("oci unreachable")

    monkeypatch.setattr(llm_mod, "llm_client", _BoomClient(), raising=True)
    out = await pr_run(_inputs())
    assert out.verdict == "revise", (
        "heuristic fallback must default to verdict='revise', never 'pass' or 'reject'"
    )
    assert out.checklist is not None
    # Suggestion should explain the fallback path.
    assert any("peer-review" in s.lower() for s in out.suggestions)


@pytest.mark.asyncio
async def test_llm_invalid_json_falls_back_to_revise(monkeypatch: pytest.MonkeyPatch):
    class _BadJsonClient:
        async def reason(self, **kwargs: Any) -> _FakeTurn:
            return _FakeTurn("not valid json {{{")

    monkeypatch.setattr(llm_mod, "llm_client", _BadJsonClient(), raising=True)
    out = await pr_run(_inputs())
    assert out.verdict == "revise"
