"""visualization_builder — chart-type + encoding recommender.

Prompt-only port (SKILL_CONVERSION.md S4.2 row 9: matplotlib chart_builder.py
intentionally NOT ported). After the LLM responds, we run a deterministic
JSON-Schema validation against the Encoding sub-schema embedded in
backend/agents/insights/specs/chart_spec.schema.json. On invalid encoding
we raise SkillValidationError so the orchestrator can recover with one
retry.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .._shared import llm_reason_short, load_fragment
from ...specs.skill_context import SkillContext
from .inputs import VisualizationBuilderInputs
from .outputs import RecommendedChartType, VisualizationBuilderOutputs

logger = logging.getLogger(__name__)

_SKILL_DIR = Path(__file__).parent
_SCHEMA_PATH = (
    Path(__file__).parents[2] / "specs" / "chart_spec.schema.json"
)

_ALLOWED_TYPES: tuple[str, ...] = (
    "line",
    "bar",
    "area",
    "scatter",
    "heatmap",
    "table",
)


class SkillValidationError(ValueError):
    """Raised when LLM-proposed encoding fails JSON-Schema validation.

    Orchestrator policy: catch + retry once before failing the insight.
    """

    def __init__(self, code: str, message: str, *, detail: dict[str, Any] | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail or {}


def _load_chart_spec_schema() -> dict[str, Any] | None:
    try:
        return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(
            "ai_insights.viz_builder.schema_load_failed",
            extra={"err": str(exc), "path": str(_SCHEMA_PATH)},
        )
        return None


def _validate_encoding(encoding: dict[str, Any]) -> None:
    """Validate `encoding` against the Encoding sub-schema in chart_spec.schema.json.

    We do a manual structural check (no jsonschema dep) consistent with the
    Pydantic Encoding model: `x` and `y` are required objects with `field`
    and `type`; optional `series`/`color`/`size` are objects.
    """
    if not isinstance(encoding, dict):
        raise SkillValidationError(
            "encoding_invalid_root",
            "encoding must be a JSON object",
        )

    schema = _load_chart_spec_schema()
    encoding_def: dict[str, Any] | None = None
    if schema and isinstance(schema.get("$defs"), dict):
        encoding_def = schema["$defs"].get("Encoding")

    # Required keys (per chart_spec.Encoding): x, y.
    if "x" not in encoding or "y" not in encoding:
        raise SkillValidationError(
            "encoding_missing_axes",
            "encoding requires 'x' and 'y' channels",
            detail={"keys": sorted(encoding.keys())},
        )

    # x channel
    x = encoding.get("x") or {}
    if not isinstance(x, dict) or not isinstance(x.get("field"), str):
        raise SkillValidationError("encoding_x_invalid", "x.field must be a string")
    if x.get("type") not in ("category", "time", "quantitative"):
        raise SkillValidationError(
            "encoding_x_type_invalid",
            "x.type must be one of category|time|quantitative",
            detail={"got": x.get("type")},
        )

    # y channel
    y = encoding.get("y") or {}
    if not isinstance(y, dict) or not isinstance(y.get("field"), str):
        raise SkillValidationError("encoding_y_invalid", "y.field must be a string")
    if y.get("type", "quantitative") != "quantitative":
        raise SkillValidationError(
            "encoding_y_type_invalid",
            "y.type must be 'quantitative'",
            detail={"got": y.get("type")},
        )

    # Optional channels — must be objects when present.
    for opt_key in ("series", "color", "size"):
        if opt_key in encoding and not isinstance(encoding[opt_key], dict):
            raise SkillValidationError(
                f"encoding_{opt_key}_invalid",
                f"{opt_key} must be an object when present",
            )

    # Forbid unknown top-level keys to keep us aligned with extra='forbid' on Encoding.
    allowed = {"x", "y", "series", "color", "size"}
    extra = set(encoding.keys()) - allowed
    if extra:
        raise SkillValidationError(
            "encoding_unexpected_keys",
            f"unexpected keys in encoding: {sorted(extra)}",
            detail={"unexpected": sorted(extra), "allowed": sorted(allowed), "schema_loaded": encoding_def is not None},
        )


def _coerce_recommended_type(value: Any, fallback: RecommendedChartType = "bar") -> RecommendedChartType:
    if isinstance(value, str) and value in _ALLOWED_TYPES:
        return value  # type: ignore[return-value]
    return fallback


def _heuristic_recommendation(
    inputs: VisualizationBuilderInputs,
) -> VisualizationBuilderOutputs:
    """Best-effort fallback when the LLM is unreachable or returns garbage."""
    cols: list[dict[str, Any]] = (
        inputs.data_shape.get("columns") if isinstance(inputs.data_shape, dict) else []
    ) or []
    time_col = next((c for c in cols if c.get("type") == "time"), None)
    quant_col = next((c for c in cols if c.get("type") == "quantitative"), None)
    cat_col = next((c for c in cols if c.get("type") == "category"), None)

    if time_col and quant_col:
        return VisualizationBuilderOutputs(
            recommended_type="line",
            encoding={
                "x": {"field": time_col["name"], "type": "time"},
                "y": {"field": quant_col["name"], "type": "quantitative"},
            },
            rationale="Time vs quantitative — line chart shows trend.",
        )
    if cat_col and quant_col:
        return VisualizationBuilderOutputs(
            recommended_type="bar",
            encoding={
                "x": {"field": cat_col["name"], "type": "category"},
                "y": {"field": quant_col["name"], "type": "quantitative"},
            },
            rationale="Category vs quantitative — bar chart compares groups.",
        )
    # Final fallback — table-like.
    field_x = (cols[0]["name"] if cols else "label")
    field_y = (cols[1]["name"] if len(cols) > 1 else "value")
    return VisualizationBuilderOutputs(
        recommended_type="table",
        encoding={
            "x": {"field": field_x, "type": "category"},
            "y": {"field": field_y, "type": "quantitative"},
        },
        rationale="No clear chart shape; rendering as table.",
    )


_SCHEMA_HINT = (
    "Return ONLY a single JSON object with this shape — no markdown:\n"
    '{\n'
    '  "recommended_type": "line|bar|area|scatter|heatmap|table",\n'
    '  "encoding": {\n'
    '    "x": {"field": "...", "type": "category|time|quantitative"},\n'
    '    "y": {"field": "...", "type": "quantitative"},\n'
    '    "series": {"field": "..."}\n'
    '  },\n'
    '  "rationale": "..."\n'
    '}\n'
    "Field names MUST appear in data_shape.columns."
)


async def run(
    inputs: VisualizationBuilderInputs,
    ctx: SkillContext | None = None,
) -> VisualizationBuilderOutputs:
    fragment = load_fragment(_SKILL_DIR)

    prompt = (
        f"DATA SHAPE:\n{json.dumps(inputs.data_shape, default=str)[:2000]}\n\n"
        f"MESSAGE: {inputs.message}\n\n"
        f"TARGET (optional): {inputs.target or 'none'}\n\n"
        f"{_SCHEMA_HINT}"
    )

    try:
        text = await llm_reason_short(prompt, system=fragment)
    except Exception as exc:
        logger.warning("ai_insights.viz_builder.llm_failed", extra={"err": str(exc)})
        return _heuristic_recommendation(inputs)

    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("ai_insights.viz_builder.json_decode_failed")
        return _heuristic_recommendation(inputs)

    recommended = _coerce_recommended_type(obj.get("recommended_type"))
    encoding = obj.get("encoding") or {}
    rationale = (obj.get("rationale") or "(no rationale provided)").strip()[:500] or "—"

    # Deterministic JSON-Schema validation. Raises SkillValidationError on
    # invalid encoding so the orchestrator can retry once before giving up.
    _validate_encoding(encoding)

    return VisualizationBuilderOutputs(
        recommended_type=recommended,
        encoding=encoding,
        rationale=rationale,
    )
