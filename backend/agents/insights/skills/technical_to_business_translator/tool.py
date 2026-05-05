"""technical_to_business_translator — technical -> exec-readable rewrite."""
from __future__ import annotations

import json
from pathlib import Path

from .._shared import llm_reason_short, load_fragment
from ...specs.skill_context import SkillContext
from .inputs import TechnicalToBusinessTranslatorInputs
from .outputs import TechnicalToBusinessTranslatorOutputs

_SKILL_DIR = Path(__file__).parent


def _clamp(s: str, n: int) -> str:
    s = (s or "").strip()
    return s[: n - 1] + "…" if len(s) > n else s


def _fallback(
    inputs: TechnicalToBusinessTranslatorInputs,
) -> TechnicalToBusinessTranslatorOutputs:
    statement = inputs.technical_statement
    # Substitute simple glossary hints inline as a deterministic fallback.
    for term, definition in inputs.glossary_hints.items():
        statement = statement.replace(term, f"{term} ({definition})")
    return TechnicalToBusinessTranslatorOutputs(
        business_statement=_clamp(statement, 600),
        lost_precision_flag=False,
    )


_SCHEMA_HINT = (
    "Return ONLY a single JSON object — no markdown:\n"
    '{ "business_statement": "...", "lost_precision_flag": false }'
)


async def run(
    inputs: TechnicalToBusinessTranslatorInputs,
    ctx: SkillContext | None = None,
) -> TechnicalToBusinessTranslatorOutputs:
    fragment = load_fragment(_SKILL_DIR)
    prompt = (
        f"AUDIENCE: {inputs.audience}\n\n"
        f"TECHNICAL_STATEMENT:\n{inputs.technical_statement}\n\n"
        f"GLOSSARY_HINTS:\n{json.dumps(inputs.glossary_hints, default=str)[:1500]}\n\n"
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

    business_statement = _clamp(str(obj.get("business_statement") or ""), 600)
    if not business_statement:
        return _fallback(inputs)
    lost_precision = bool(obj.get("lost_precision_flag", False))

    return TechnicalToBusinessTranslatorOutputs(
        business_statement=business_statement,
        lost_precision_flag=lost_precision,
    )
