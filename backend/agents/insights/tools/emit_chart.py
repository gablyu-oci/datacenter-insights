"""emit_chart — final chart sink with strict ChartSpec validation.

Pipeline:
    1. Pydantic-validate the ChartSpec (raises on shape errors).
    2. Recompute row_hash from spec.data; reject mismatch.
    3. Optionally cross-check against the originating tool call's row_hash
       captured on the SkillContext (defended-in-depth provenance check).
    4. Persist the chart blob (handled by orchestrator/persistence layer).

This module is dispatch-only — it does NOT itself open a write transaction.
Persistence is the caller's responsibility (see orchestrator.persistence).
"""
from __future__ import annotations

import logging
from typing import Any

from ..specs.chart_spec import ChartSpec
from ..specs.skill_context import SkillContext

logger = logging.getLogger(__name__)


class EmitChartError(ValueError):
    def __init__(self, code: str, message: str, *, detail: dict[str, Any] | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail or {}


async def emit_chart(
    spec: ChartSpec | dict[str, Any],
    ctx: SkillContext | None = None,
) -> dict[str, Any]:
    """Validate + accept a ChartSpec.

    Returns ``{"chart_id": str, "accepted": True}`` on success. Raises
    `EmitChartError` (caller maps to a tool_error event).
    """
    # 1) Validate.
    try:
        chart = spec if isinstance(spec, ChartSpec) else ChartSpec.model_validate(spec)
    except Exception as exc:
        raise EmitChartError(
            "chart_validation_error",
            f"ChartSpec validation failed: {exc}",
        ) from exc

    # 2) Recompute row_hash.
    recomputed = chart.recompute_row_hash()
    if recomputed != chart.data_source.row_hash:
        raise EmitChartError(
            "row_hash_mismatch",
            "data rows do not match data_source.row_hash",
            detail={
                "expected": chart.data_source.row_hash,
                "recomputed": recomputed,
            },
        )

    # 3) Cross-check against the originating tool_call hash if recorded on ctx.
    expected_hashes: set[str] = set()
    if ctx is not None:
        recorded = getattr(ctx, "_emitted_row_hashes", None)
        if isinstance(recorded, set):
            expected_hashes = recorded
    if expected_hashes and recomputed not in expected_hashes:
        # Soft-warn rather than hard reject; the strict check is the
        # spec.row_hash recomputation above. Logged for audit.
        logger.warning(
            "ai_insights.emit_chart.unrecognised_row_hash",
            extra={"row_hash": recomputed, "known": sorted(expected_hashes)},
        )

    logger.info(
        "ai_insights.emit_chart.accepted",
        extra={"chart_id": chart.chart_id, "rows": len(chart.data)},
    )
    return {"chart_id": chart.chart_id, "accepted": True}
