"""root_cause_investigation — LLM-driven ranked-cause analysis."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .._shared import llm_reason_short, load_fragment
from ...specs.skill_context import SkillContext
from .inputs import RootCauseInvestigationInputs
from .outputs import RankedCause, RootCauseInvestigationOutputs


_FRAGMENT = load_fragment(Path(__file__).parent)


async def run(
    inputs: RootCauseInvestigationInputs, ctx: SkillContext | None = None
) -> RootCauseInvestigationOutputs:
    candidates = inputs.candidate_causes or ["unknown_cause"]
    prompt = (
        "Anomaly:\n"
        f"{inputs.anomaly}\n\n"
        "Context:\n"
        f"{inputs.context}\n\n"
        "Candidate causes:\n"
        + "\n".join(f"- {c}" for c in candidates)
        + "\n\nReturn a JSON object with keys 'ranked' (list of "
        "{cause, rank, rationale, likelihood in [0,1]}) "
        "and 'recommended_followups' (list of strings). "
        "Reply with JSON only, no prose."
    )
    raw = await llm_reason_short(prompt, system=_FRAGMENT)

    parsed: dict | None = None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        # Try to extract first JSON object from prose.
        m = re.search(r"\{[\s\S]*\}", raw or "")
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                parsed = None

    if not parsed:
        # Heuristic fallback: rank candidates uniformly low.
        ranked = [
            RankedCause(cause=c, rank=i + 1, rationale="LLM parse failed", likelihood=0.2)
            for i, c in enumerate(candidates)
        ]
        return RootCauseInvestigationOutputs(
            ranked=ranked, recommended_followups=["query supporting rows then re-rank"]
        )

    ranked_items: list[RankedCause] = []
    for i, item in enumerate(parsed.get("ranked", []) or []):
        try:
            ranked_items.append(
                RankedCause(
                    cause=str(item.get("cause", f"cause_{i+1}")),
                    rank=int(item.get("rank", i + 1)),
                    rationale=str(item.get("rationale", "")),
                    likelihood=max(0.0, min(1.0, float(item.get("likelihood", 0.5)))),
                )
            )
        except (TypeError, ValueError):
            continue

    follow = [str(x) for x in (parsed.get("recommended_followups") or [])][:5]
    return RootCauseInvestigationOutputs(ranked=ranked_items, recommended_followups=follow)
