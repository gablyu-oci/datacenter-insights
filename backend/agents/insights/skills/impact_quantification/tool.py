"""impact_quantification — claim + rows -> quantified impact with a range."""
from __future__ import annotations

import json
from pathlib import Path

from .._shared import llm_reason_short, load_fragment, numeric_columns
from ...specs.skill_context import SkillContext
from .inputs import ImpactQuantificationInputs
from .outputs import ImpactQuantificationOutputs

_SKILL_DIR = Path(__file__).parent


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _fallback(inputs: ImpactQuantificationInputs) -> ImpactQuantificationOutputs:
    """Best-effort numeric fallback: sum the first numeric column we find."""
    rows = inputs.supporting_rows
    cols = numeric_columns(rows)
    if not rows or not cols:
        return ImpactQuantificationOutputs(
            impact_value=0.0,
            impact_unit=inputs.unit,
            range_lo=0.0,
            range_hi=0.0,
            basis=(
                f"No numeric columns in {len(rows)} supporting rows; cannot "
                "quantify impact deterministically."
            ),
        )
    target_col = cols[0]
    values: list[float] = []
    for r in rows:
        v = r.get(target_col)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            values.append(float(v))
    if not values:
        return ImpactQuantificationOutputs(
            impact_value=0.0,
            impact_unit=inputs.unit,
            range_lo=0.0,
            range_hi=0.0,
            basis=f"Column {target_col!r} contained no numeric values.",
        )
    total = sum(values)
    lo = min(values)
    hi = max(values)
    return ImpactQuantificationOutputs(
        impact_value=total,
        impact_unit=inputs.unit,
        range_lo=lo,
        range_hi=max(hi, total),
        basis=(
            f"Fallback sum of `{target_col}` across {len(values)} rows; "
            f"range = [min, max]."
        ),
    )


_SCHEMA_HINT = (
    "Return ONLY a single JSON object — no markdown:\n"
    '{ "impact_value": <number>, "impact_unit": "<unit>", '
    '"range_lo": <number>, "range_hi": <number>, "basis": "..." }'
)


async def run(
    inputs: ImpactQuantificationInputs,
    ctx: SkillContext | None = None,
) -> ImpactQuantificationOutputs:
    fragment = load_fragment(_SKILL_DIR)
    rows_preview = inputs.supporting_rows[:30]
    prompt = (
        f"CLAIM: {inputs.claim}\n\n"
        f"UNIT: {inputs.unit}\n\n"
        f"SUPPORTING_ROWS ({len(inputs.supporting_rows)} total, first 30 shown):\n"
        f"{json.dumps(rows_preview, default=str)[:5000]}\n\n"
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

    impact_value = _coerce_float(obj.get("impact_value"))
    range_lo = _coerce_float(obj.get("range_lo"), default=impact_value)
    range_hi = _coerce_float(obj.get("range_hi"), default=impact_value)
    impact_unit = str(obj.get("impact_unit") or inputs.unit)[:16] or inputs.unit
    basis = str(obj.get("basis") or "Estimate from supplied rows.").strip()[:600] or "—"

    # Repair an inverted range silently rather than fail the skill.
    if range_lo > range_hi:
        range_lo, range_hi = range_hi, range_lo
    # Clamp impact_value into [range_lo, range_hi] when out of bounds.
    if not (range_lo <= impact_value <= range_hi):
        # Widen the range to include the central estimate.
        range_lo = min(range_lo, impact_value)
        range_hi = max(range_hi, impact_value)

    return ImpactQuantificationOutputs(
        impact_value=impact_value,
        impact_unit=impact_unit,
        range_lo=range_lo,
        range_hi=range_hi,
        basis=basis,
    )
