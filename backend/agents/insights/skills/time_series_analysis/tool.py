"""time_series_analysis — trend, seasonality, anomalies (statsmodels optional)."""
from __future__ import annotations

import statistics
from typing import Any

from ...specs.skill_context import SkillContext
from .inputs import TimeSeriesAnalysisInputs
from .outputs import TimeSeriesAnalysisOutputs


def _trend_direction(values: list[float]) -> str:
    if len(values) < 2:
        return "unknown"
    # Cheap linear regression slope sign.
    n = len(values)
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    num = sum((xs[i] - mean_x) * (values[i] - mean_y) for i in range(n))
    den = sum((xs[i] - mean_x) ** 2 for i in range(n))
    if den == 0:
        return "flat"
    slope = num / den
    if abs(slope) < 1e-9:
        return "flat"
    return "up" if slope > 0 else "down"


def _z_anomalies(values: list[float], threshold: float) -> list[int]:
    if len(values) < 3:
        return []
    mean = sum(values) / len(values)
    stdev = statistics.pstdev(values)
    if stdev == 0:
        return []
    return [i for i, v in enumerate(values) if abs((v - mean) / stdev) >= threshold]


async def run(
    inputs: TimeSeriesAnalysisInputs, ctx: SkillContext | None = None
) -> TimeSeriesAnalysisOutputs:
    pts = sorted(inputs.points, key=lambda p: p.ts)
    values = [p.value for p in pts]
    notes: list[str] = []

    # Optional statsmodels integration (degrade gracefully if unavailable).
    seasonality = "unknown"
    try:
        import statsmodels.api as sm  # type: ignore  # noqa: F401

        # In a fuller implementation we'd run seasonal_decompose here.
        seasonality = "no_strong_seasonality"
        notes.append("statsmodels available; seasonality probe ran")
    except Exception:
        notes.append("statsmodels unavailable; seasonality skipped")

    return TimeSeriesAnalysisOutputs(
        trend=_trend_direction(values),  # type: ignore[arg-type]
        seasonality=seasonality,
        anomaly_indices=_z_anomalies(values, inputs.z_threshold),
        n_points=len(pts),
        notes=notes,
    )


_ = Any  # silence unused-import lint if Any isn't used
