"""peer_review_template (V2) -- defensive self-review.

Costs an extra `gpt-5.4-mini` call per insight (PRD §6.3 -- accepted at V2).
Returns a strictly typed pydantic verdict; on transport / parse failures,
falls back to a deterministic "revise" with conservative checklist.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .._shared import load_fragment
from ...specs.skill_context import SkillContext
from .inputs import PeerReviewTemplateInputs
from .outputs import PeerReviewChecklist, PeerReviewTemplateOutputs

_SKILL_DIR = Path(__file__).parent


def _looks_specific(headline: str) -> bool:
    """Cheap heuristic: a quantity (digit) AND a proper-noun-ish capital token."""
    has_digit = any(ch.isdigit() for ch in headline)
    tokens = headline.split()
    has_proper = any(
        tok[0].isupper() and tok[1:].lower() != tok[1:].upper() and len(tok) > 2
        for tok in tokens
    )
    return has_digit and has_proper


def _heuristic_fallback(inputs: PeerReviewTemplateInputs) -> PeerReviewTemplateOutputs:
    """Deterministic fallback verdict used when the LLM call fails or returns
    un-parsable output. Conservative: never `pass`, never `reject`.
    """
    headline = inputs.candidate_insight.headline
    has_chart = bool(inputs.chart_spec)
    has_quant_citation = any(
        c.agree_or_disagree in ("agree", "disagree") for c in inputs.citations
    )
    checklist = PeerReviewChecklist(
        specific=_looks_specific(headline),
        supported=bool(has_chart or has_quant_citation),
        non_trivial=True,
        material=True,
    )
    return PeerReviewTemplateOutputs(
        verdict="revise",
        checklist=checklist,
        suggestions=[
            "peer-review LLM unavailable; please re-run for an authoritative verdict",
        ],
    )


def _strip_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        # Trim the opening fence (and optional `json` tag) and the closing one.
        s = s.lstrip("`")
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
        if s.endswith("```"):
            s = s[: -3]
        # Re-strip any leftover whitespace / fence remainders.
        s = s.strip("`\n ")
    return s


async def run(
    inputs: PeerReviewTemplateInputs,
    ctx: SkillContext | None = None,
) -> PeerReviewTemplateOutputs:
    fragment = load_fragment(_SKILL_DIR)
    payload = {
        "candidate_insight": inputs.candidate_insight.model_dump(exclude_none=True),
        "chart_spec_present": bool(inputs.chart_spec),
        "chart_spec": inputs.chart_spec or {},
        "citations": [c.model_dump(exclude_none=True) for c in inputs.citations],
    }

    try:
        from backend.llm.client import MODELS, llm_client  # type: ignore

        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": fragment},
            {
                "role": "user",
                "content": (
                    f"CANDIDATE PAYLOAD:\n{json.dumps(payload, default=str)[:6000]}\n\n"
                    "Return JSON exactly per the schema in the system fragment."
                ),
            },
        ]
        turn = await llm_client.reason(
            model=MODELS["extraction"],
            prompt_version="ai-insights/peer_review_template",
            messages=msgs,
        )
        text = _strip_fence(turn.content or "")
        if not text:
            return _heuristic_fallback(inputs)
        obj = json.loads(text)
    except (json.JSONDecodeError, Exception):  # noqa: BLE001
        return _heuristic_fallback(inputs)

    try:
        return PeerReviewTemplateOutputs.model_validate(obj)
    except ValidationError:
        return _heuristic_fallback(inputs)
