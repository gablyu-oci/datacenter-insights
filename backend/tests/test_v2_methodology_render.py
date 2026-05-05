"""V2 methodology_explainer skill tests.

Pins behaviour of `agents/insights/skills/methodology_explainer/tool.py`:
- Happy path: monkeypatched LLM returns markdown with multiple sections;
  result.methodology_md contains them.
- LLM raises -> deterministic non-empty fallback string is returned.

NOTE (gap vs kickoff brief): the actual Outputs schema field is
`methodology_md` (not `markdown`). There is no `tokens_used` field on the
output -- token counts are tracked at the LLM client layer, not surfaced
back through the skill output. This test asserts the actual contract.
"""
from __future__ import annotations

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

from agents.insights.skills.methodology_explainer.inputs import (  # noqa: E402
    MethodologyExplainerInputs,
    SkillInvocationRecord,
)
from agents.insights.skills.methodology_explainer.tool import run as me_run  # noqa: E402
import backend.llm.client as llm_mod  # noqa: E402


class _FakeTurn:
    def __init__(self, content: str | None) -> None:
        self.content = content
        self.tool_calls = None
        self.model = "fake"
        self.tokens = {"prompt": 10, "completion": 200}


def _inputs() -> MethodologyExplainerInputs:
    return MethodologyExplainerInputs(
        insight_id="ins-abc",
        persisted_skill_invocations=[
            SkillInvocationRecord(skill_name="programmatic_eda", latency_ms=42),
            SkillInvocationRecord(skill_name="cohort_analysis", latency_ms=57),
        ],
        chart_spec={
            "type": "stacked_bar",
            "title": "Cohort retention",
            "subtitle": "Monthly",
            "encoding": {"x": "period", "y": "ret"},
            "data_source": {
                "kind": "sql",
                "spec": {"sql": "SELECT * FROM ai_insight LIMIT 5"},
            },
        },
    )


# ---------------------------------------------------------------------------
# (6a) Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_renders_llm_markdown(monkeypatch: pytest.MonkeyPatch):
    md = (
        "## Methodology\n\n"
        "### Data sources\n- power_deal table\n\n"
        "### Pipeline\nRan EDA then cohort_analysis.\n\n"
        "### Caveats\nLow row count (<50)."
    )

    class _FakeClient:
        async def reason(self, **kwargs: Any) -> _FakeTurn:
            return _FakeTurn(md)

    monkeypatch.setattr(llm_mod, "llm_client", _FakeClient(), raising=True)

    out = await me_run(_inputs())
    text = out.methodology_md
    assert text, "expected non-empty methodology_md"
    # Three section headers should round-trip through the skill.
    assert "## Methodology" in text
    assert "### Data sources" in text
    assert "### Pipeline" in text
    assert "### Caveats" in text


# ---------------------------------------------------------------------------
# (6b) LLM raises -> deterministic non-empty fallback.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_failure_uses_deterministic_fallback(monkeypatch: pytest.MonkeyPatch):
    class _BoomClient:
        async def reason(self, **kwargs: Any) -> _FakeTurn:
            raise RuntimeError("transport down")

    monkeypatch.setattr(llm_mod, "llm_client", _BoomClient(), raising=True)

    out = await me_run(_inputs())
    text = out.methodology_md
    assert text, "fallback must produce a non-empty markdown string"
    # Fallback prepends the H2 if missing; either way it should be present.
    assert text.lstrip().startswith("## Methodology")
    # Fallback enumerates the skill names that ran.
    assert "programmatic_eda" in text or "cohort_analysis" in text
