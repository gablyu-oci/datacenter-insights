"""executive_summary_generator — N insights -> exec-readable summary.

Prompt-only skill (no script port). Pattern matches insight_synthesis: load
the system_fragment, build a user prompt, call the LLM, parse JSON, fall
back to a deterministic synthesis if the LLM fails.

Output schema is per SKILL_CONVERSION.md S4.2 row 8:
    {summary, top_3_takeaways, call_to_action}
"""
from __future__ import annotations

import json
from pathlib import Path

from .._shared import llm_reason_short, load_fragment
from ...specs.skill_context import SkillContext
from .inputs import ExecutiveSummaryGeneratorInputs
from .outputs import ExecutiveSummaryGeneratorOutputs

_SKILL_DIR = Path(__file__).parent


def _clamp(s: str, n: int) -> str:
    s = (s or "").strip()
    return s[: n - 1] + "…" if len(s) > n else s


def _fallback(
    inputs: ExecutiveSummaryGeneratorInputs,
) -> ExecutiveSummaryGeneratorOutputs:
    headlines = [i.headline for i in inputs.insights[:3]]
    summary = " ".join(headlines)[:1200] or "No insights available."
    takeaways = headlines or ["No insights available."]
    cta = "Review the supporting charts and underlying data before next steps."
    return ExecutiveSummaryGeneratorOutputs(
        summary=_clamp(summary, 1200),
        top_3_takeaways=[_clamp(t, 200) for t in takeaways[:3]],
        call_to_action=_clamp(cta, 400),
    )


_SCHEMA_HINT = (
    "Return ONLY a single JSON object with this exact shape — no markdown, "
    "no surrounding prose:\n"
    '{\n'
    '  "summary": "<2-4 sentence rollup, lead with the most material claim>",\n'
    '  "top_3_takeaways": ["...", "...", "..."],\n'
    '  "call_to_action": "<one sentence on what the exec should do next>"\n'
    "}\n"
    "Each takeaway <= 200 chars. The summary must reference at least one "
    "quantified figure across the insights."
)


async def run(
    inputs: ExecutiveSummaryGeneratorInputs,
    ctx: SkillContext | None = None,
) -> ExecutiveSummaryGeneratorOutputs:
    fragment = load_fragment(_SKILL_DIR)
    insights_payload = [
        {"headline": i.headline, "body": (i.body or "")[:500]}
        for i in inputs.insights
    ]
    prompt = (
        f"INSIGHTS ({len(insights_payload)} total):\n"
        f"{json.dumps(insights_payload, default=str)[:6000]}\n\n"
        f"{_SCHEMA_HINT}"
    )

    try:
        text = await llm_reason_short(prompt, system=fragment)
    except Exception:
        return _fallback(inputs)

    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()

    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return _fallback(inputs)

    summary = _clamp(str(obj.get("summary") or ""), 1200)
    takeaways_raw = obj.get("top_3_takeaways") or []
    if not isinstance(takeaways_raw, list):
        takeaways_raw = [str(takeaways_raw)]
    takeaways = [_clamp(str(t), 200) for t in takeaways_raw if str(t).strip()][:3]
    cta = _clamp(str(obj.get("call_to_action") or ""), 400)

    if not summary or not takeaways or not cta:
        # Partial output — splice fallback values in for missing fields.
        fb = _fallback(inputs)
        if not summary:
            summary = fb.summary
        if not takeaways:
            takeaways = fb.top_3_takeaways
        if not cta:
            cta = fb.call_to_action

    return ExecutiveSummaryGeneratorOutputs(
        summary=summary,
        top_3_takeaways=takeaways,
        call_to_action=cta,
    )
