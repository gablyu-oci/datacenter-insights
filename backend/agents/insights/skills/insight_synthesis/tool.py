"""insight_synthesis — verified-hypothesis → headline + body.

LLM-driven; uses _shared.llm_reason_short with the system_fragment loaded
from disk and injected as a mid-conversation system message.
"""
from __future__ import annotations

import json
from pathlib import Path

from .._shared import llm_reason_short, load_fragment
from ...specs.skill_context import SkillContext
from .inputs import InsightSynthesisInputs
from .outputs import ConfidenceSignal, InsightSynthesisOutputs

_SKILL_DIR = Path(__file__).parent


def _clamp(s: str, n: int) -> str:
    s = (s or "").strip()
    return s[: n - 1] + "…" if len(s) > n else s


def _heuristic_signal(n_rows: int) -> ConfidenceSignal:
    if n_rows < 3:
        return "weak"
    if n_rows >= 50:
        return "strong"
    return "moderate"


async def run(
    inputs: InsightSynthesisInputs,
    ctx: SkillContext | None = None,
) -> InsightSynthesisOutputs:
    fragment = load_fragment(_SKILL_DIR)
    rows_preview = inputs.supporting_rows[:20]
    prompt = (
        f"HYPOTHESIS:\n{inputs.hypothesis}\n\n"
        f"SUPPORTING_ROWS ({len(inputs.supporting_rows)} total, first 20 shown):\n"
        f"{json.dumps(rows_preview, default=str)[:6000]}\n\n"
        f"CONTEXT: {json.dumps(inputs.context or {}, default=str)[:1000]}\n\n"
        "Return JSON only per the schema in the system fragment."
    )

    fallback_signal = _heuristic_signal(len(inputs.supporting_rows))

    try:
        text = await llm_reason_short(prompt, system=fragment)
    except Exception:
        # Fallback: deterministic synthesis from the hypothesis itself.
        return InsightSynthesisOutputs(
            headline=_clamp(inputs.hypothesis, 120),
            body=_clamp(
                f"{inputs.hypothesis} (Based on {len(inputs.supporting_rows)} rows.)",
                500,
            ),
            confidence_signal=fallback_signal,
        )

    text = (text or "").strip()
    # Strip optional markdown code fences.
    if text.startswith("```"):
        text = text.strip("`")
        # Drop a leading "json" language tag if present.
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # Last-resort: treat the whole output as the body.
        return InsightSynthesisOutputs(
            headline=_clamp(inputs.hypothesis, 120),
            body=_clamp(text or inputs.hypothesis, 500),
            confidence_signal=fallback_signal,
        )

    headline = _clamp(str(obj.get("headline") or inputs.hypothesis), 120)
    body = _clamp(str(obj.get("body") or inputs.hypothesis), 500)
    sig = obj.get("confidence_signal") or fallback_signal
    if sig not in ("weak", "moderate", "strong"):
        sig = fallback_signal

    return InsightSynthesisOutputs(
        headline=headline,
        body=body,
        confidence_signal=sig,
    )
