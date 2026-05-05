"""data_narrative_builder — insight + chart_spec -> card narrative."""
from __future__ import annotations

import json
from pathlib import Path

from .._shared import llm_reason_short, load_fragment
from ...specs.skill_context import SkillContext
from .inputs import DataNarrativeBuilderInputs
from .outputs import DataNarrativeBuilderOutputs

_SKILL_DIR = Path(__file__).parent


def _clamp(s: str, n: int) -> str:
    s = (s or "").strip()
    return s[: n - 1] + "…" if len(s) > n else s


def _fallback(inputs: DataNarrativeBuilderInputs) -> DataNarrativeBuilderOutputs:
    raw_headline = (
        inputs.insight.get("headline")
        or inputs.chart_spec.get("title")
        or "Insight"
    )
    raw_body = (
        inputs.insight.get("body")
        or inputs.insight.get("body_md")
        or inputs.chart_spec.get("subtitle")
        or "See chart for supporting data."
    )
    caption = inputs.chart_spec.get("subtitle") or inputs.chart_spec.get("title") or "Chart"
    return DataNarrativeBuilderOutputs(
        headline=_clamp(str(raw_headline), 160),
        body_md=_clamp(str(raw_body), 900),
        caption=_clamp(str(caption), 200),
    )


_SCHEMA_HINT = (
    "Return ONLY a single JSON object — no markdown fence:\n"
    '{ "headline": "...", "body_md": "...", "caption": "..." }'
)


async def run(
    inputs: DataNarrativeBuilderInputs,
    ctx: SkillContext | None = None,
) -> DataNarrativeBuilderOutputs:
    fragment = load_fragment(_SKILL_DIR)

    # Compact chart_spec preview — drop the full inline `data` rows to save tokens.
    chart_preview = {
        k: v
        for k, v in inputs.chart_spec.items()
        if k != "data"
    }

    prompt = (
        f"AUDIENCE: {inputs.audience}\n\n"
        f"INSIGHT:\n{json.dumps(inputs.insight, default=str)[:2500]}\n\n"
        f"CHART_SPEC (rows omitted):\n{json.dumps(chart_preview, default=str)[:2500]}\n\n"
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

    headline = _clamp(str(obj.get("headline") or ""), 160)
    body_md = _clamp(str(obj.get("body_md") or ""), 900)
    caption = _clamp(str(obj.get("caption") or ""), 200)

    if not headline or not body_md or not caption:
        fb = _fallback(inputs)
        if not headline:
            headline = fb.headline
        if not body_md:
            body_md = fb.body_md
        if not caption:
            caption = fb.caption

    return DataNarrativeBuilderOutputs(
        headline=headline,
        body_md=body_md,
        caption=caption,
    )
