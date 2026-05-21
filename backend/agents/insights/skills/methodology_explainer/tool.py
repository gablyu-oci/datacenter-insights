"""methodology_explainer -- prompt-only skill.

Drives a low-effort gpt-5.4-mini call (via `_shared.llm_reason_short` against
`MODELS["extraction"]`) to produce a Markdown walkthrough of how an insight
was computed, given the persisted skill invocations + the emitted chart
spec. Pure narrative; no deterministic preprocessing.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .._shared import load_fragment
from ...specs.skill_context import SkillContext
from .inputs import MethodologyExplainerInputs
from .outputs import MethodologyExplainerOutputs

_SKILL_DIR = Path(__file__).parent


def _compact_chart_spec(spec: dict[str, Any] | None) -> dict[str, Any]:
    """Pull only the methodology-relevant slice of a chart spec."""
    if not spec:
        return {}
    out: dict[str, Any] = {}
    for k in ("type", "title", "subtitle", "encoding"):
        if k in spec:
            out[k] = spec[k]
    ds = spec.get("data_source") or {}
    if isinstance(ds, dict):
        ds_compact: dict[str, Any] = {}
        for k in ("kind", "rows", "fetched_at"):
            if k in ds:
                ds_compact[k] = ds[k]
        sub = ds.get("spec") or {}
        if isinstance(sub, dict):
            ds_compact["spec"] = {
                k: sub[k] for k in ("sql", "endpoint", "params", "tab_chart") if k in sub
            }
        out["data_source"] = ds_compact
    return out


def _fallback_markdown(inputs: MethodologyExplainerInputs) -> str:
    """Deterministic fallback used if the LLM call fails.

    Keeps the user-visible footer non-empty even on transport errors.
    """
    lines = ["## Methodology", ""]
    if not inputs.persisted_skill_invocations:
        lines.append("No skill invocations recorded for this insight.")
    else:
        lines.append(
            f"Insight `{inputs.insight_id}` was assembled across "
            f"{len(inputs.persisted_skill_invocations)} skill calls:"
        )
        lines.append("")
        for inv in inputs.persisted_skill_invocations:
            lines.append(f"- `{inv.skill_name}`")
    cs = inputs.chart_spec or {}
    ds = (cs.get("data_source") or {}).get("spec") or {} if isinstance(cs, dict) else {}
    src = ds.get("endpoint") or ds.get("sql")
    if src:
        # Truncate long SQL to keep the footer compact.
        if isinstance(src, str) and len(src) > 120:
            src = src[:117] + "..."
        lines.append("")
        lines.append(f"Data source: `{src}`")
    return "\n".join(lines).strip()


async def run(
    inputs: MethodologyExplainerInputs,
    ctx: SkillContext | None = None,
) -> MethodologyExplainerOutputs:
    fragment = load_fragment(_SKILL_DIR)

    # Compact the chart spec so we don't overload the prompt.
    chart_spec_compact = _compact_chart_spec(inputs.chart_spec)
    invocations_payload = [
        inv.model_dump(exclude_none=True) for inv in inputs.persisted_skill_invocations
    ]

    prompt = (
        f"INSIGHT_ID: {inputs.insight_id}\n\n"
        f"SKILL_INVOCATIONS (in order):\n"
        f"{json.dumps(invocations_payload, default=str)[:6000]}\n\n"
        f"CHART_SPEC (compact): {json.dumps(chart_spec_compact, default=str)[:2000]}\n\n"
        "Produce the methodology Markdown per the system fragment. Markdown only."
    )

    text: str | None = None
    try:
        # Call gpt-5.4-mini directly with low effort. We avoid llm_reason_short
        # because that helper is hard-wired to the reasoning model; the
        # methodology explainer should stay on the cheaper extraction model.
        from backend.llm.client import MODELS, llm_client  # type: ignore

        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": fragment},
            {"role": "user", "content": prompt},
        ]
        turn = await llm_client.reason(
            model=MODELS["extraction"],
            prompt_version="ai-insights/methodology_explainer",
            messages=msgs,
        )
        text = (turn.content or "").strip()
    except Exception:
        text = None

    if not text:
        text = _fallback_markdown(inputs)

    # Ensure the leading H2 is present (system fragment requires it).
    if not text.lstrip().startswith("## Methodology"):
        text = f"## Methodology\n\n{text}"

    # Hard cap to the output schema.
    if len(text) > 4000:
        text = text[:3997] + "..."

    return MethodologyExplainerOutputs(methodology_md=text)
