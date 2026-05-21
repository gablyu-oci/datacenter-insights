"""cohort_analysis -- cohort x time retention matrix.

Re-implementation of the algorithm originally housed in
``cohort_builder.py`` + ``retention_matrix.py`` (the Claude-Code skill's
``scripts/`` are off-limits at runtime; we re-derive the algorithm here).

Recharts emits a stacked_bar / heatmap-equivalent via emit_chart; this
skill returns the numerical matrix only and never calls emit_chart from
inside.

Implementation notes:
- pandas + numpy only; no matplotlib, no scikit-learn.
- ``time_col`` accepts either ISO-date-shaped strings, datetime objects,
  or comparable numerics. Period bucketing is "relative integer period"
  per cohort: period 0 is the cohort's first observed time bucket; later
  periods count "+1, +2, ..." of whichever granularity the inputs imply.
- ``event_col`` is treated as a presence marker. Truthy values mean the
  entity was active in ``time_col``'s bucket. Retention denominator at
  period j is the number of unique entities the cohort observed at
  period 0; numerator is unique entities active at period j (entities
  are identified by row identity within a cohort, which is the
  conservative choice when no entity-id column is supplied).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ...specs.skill_context import SkillContext
from .inputs import CohortAnalysisInputs
from .outputs import (
    CohortAnalysisOutputs,
    CohortRetentionSummary,
)


def _coerce_time(value: Any) -> Any:
    """Normalise a time value to something pandas can sort / diff.

    Accepts datetimes, ISO strings, or numerics. Falsy / un-parsable values
    return ``pd.NaT`` so the caller can drop them.
    """
    if value is None or value == "":
        return pd.NaT
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    try:
        return pd.to_datetime(value, errors="coerce", utc=True)
    except (ValueError, TypeError):
        return pd.NaT


def _bucket_period(t: Any, anchor: Any) -> int | None:
    """Return integer relative period of ``t`` from ``anchor``.

    For datetimes we measure full months; for numerics we use integer
    distance. Returns None on incomparable inputs.
    """
    if t is None or anchor is None:
        return None
    if isinstance(t, pd.Timestamp) and isinstance(anchor, pd.Timestamp):
        if pd.isna(t) or pd.isna(anchor):
            return None
        # Period delta in months (rounded down).
        years = t.year - anchor.year
        months = t.month - anchor.month
        return years * 12 + months
    try:
        return int(t) - int(anchor)
    except (TypeError, ValueError):
        return None


def _build_matrix(
    df: pd.DataFrame,
    *,
    cohort_col: str,
    event_col: str,
    time_col: str,
    periods: int,
) -> tuple[list[list[float]], list[str], list[int], dict[str, Any], list[str]]:
    """Return (matrix, cohort_keys, cohort_sizes, summary_payload, notes)."""
    notes: list[str] = []

    if df.empty:
        return [], [], [], {"n_cohorts": 0, "n_periods": 0}, ["empty input frame"]

    # Drop rows whose cohort_col is null or whose time_col cannot be coerced.
    n_total = len(df)
    df = df.copy()
    df["_cohort_norm"] = df[cohort_col].where(df[cohort_col].notna(), other=None)
    df = df[df["_cohort_norm"].astype("object").apply(lambda v: v is not None and v != "")]
    if len(df) < n_total:
        notes.append(f"dropped {n_total - len(df)} rows with null {cohort_col!r}")

    df["_time_norm"] = df[time_col].apply(_coerce_time)
    pre_time = len(df)
    df = df[df["_time_norm"].apply(lambda v: v is not None and not (isinstance(v, float) and np.isnan(v)) and not (hasattr(pd, "NaT") and v is pd.NaT))]
    df = df[df["_time_norm"].apply(lambda v: not (isinstance(v, pd.Timestamp) and pd.isna(v)))]
    if len(df) < pre_time:
        notes.append(f"dropped {pre_time - len(df)} rows with un-parsable {time_col!r}")

    # Truthy event marker.
    def _is_truthy(v: Any) -> bool:
        if v is None or v is False:
            return False
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v != 0
        if isinstance(v, str):
            return v.lower() not in ("", "0", "false", "no", "n", "null", "none")
        return True

    df["_active"] = df[event_col].apply(_is_truthy)

    # Cohort key -> per-row data.
    cohort_keys_sorted = sorted(df["_cohort_norm"].astype(str).unique().tolist())
    matrix: list[list[float]] = []
    cohort_sizes: list[int] = []
    drops: list[tuple[str, int, int, float]] = []  # (cohort, from, to, drop)
    period1_retentions: list[float] = []

    for key in cohort_keys_sorted:
        subset = df[df["_cohort_norm"].astype(str) == key]
        if subset.empty:
            continue
        # Cohort anchor: the earliest time in the subset.
        anchor = subset["_time_norm"].min()
        rel_periods = subset["_time_norm"].apply(lambda t: _bucket_period(t, anchor))
        valid = rel_periods.apply(lambda p: p is not None and p >= 0)
        if not valid.any():
            continue
        sub_valid = subset[valid].copy()
        sub_valid["_period"] = rel_periods[valid].astype(int)

        # Period 0 entity count (denominator). Entities are identified by
        # their row identity *within* the cohort (DataFrame index) when no
        # explicit entity column is supplied. We count unique row indices
        # observed in period 0.
        period0_entities = sub_valid.loc[sub_valid["_period"] == 0].index.unique()
        denom = int(len(period0_entities))
        if denom == 0:
            # Fall back: any entity active in period 0 (by event_col); if
            # still zero, denom = total rows in subset (always >0 here).
            denom = max(1, int(sub_valid.loc[sub_valid["_period"] == 0, "_active"].sum()))

        cohort_sizes.append(denom)

        row: list[float] = []
        for j in range(periods + 1):
            in_period = sub_valid[(sub_valid["_period"] == j) & (sub_valid["_active"])]
            num = int(in_period.index.unique().shape[0])
            ret = (num / denom) if denom else 0.0
            # Period 0 by construction is 1.0 when any entity exists.
            if j == 0:
                ret = 1.0 if denom > 0 else 0.0
            ret = float(max(0.0, min(1.0, ret)))
            row.append(round(ret, 4))

        matrix.append(row)

        if len(row) >= 2:
            period1_retentions.append(row[1])
        # Track largest single drop within this cohort.
        if len(row) >= 2:
            for j in range(1, len(row)):
                drop = row[j - 1] - row[j]
                if drop > 0:
                    drops.append((key, j - 1, j, round(drop, 4)))

    summary_payload: dict[str, Any] = {
        "n_cohorts": len(matrix),
        "n_periods": periods + 1,
    }
    if period1_retentions:
        summary_payload["mean_period1_retention"] = round(
            float(np.mean(period1_retentions)), 4
        )
    if cohort_sizes:
        idx_largest = int(np.argmax(np.asarray(cohort_sizes)))
        summary_payload["largest_cohort_key"] = cohort_keys_sorted[idx_largest]
        summary_payload["largest_cohort_size"] = int(cohort_sizes[idx_largest])
    if drops:
        drops.sort(key=lambda t: t[3], reverse=True)
        cohort, from_p, to_p, drop = drops[0]
        summary_payload["biggest_drop_off"] = {
            "cohort": cohort,
            "from_period": int(from_p),
            "to_period": int(to_p),
            "drop": float(drop),
        }

    return matrix, cohort_keys_sorted[: len(matrix)], cohort_sizes, summary_payload, notes


async def run(
    inputs: CohortAnalysisInputs,
    ctx: SkillContext | None = None,
) -> CohortAnalysisOutputs:
    if not inputs.rows:
        return CohortAnalysisOutputs(
            matrix=[],
            cohort_keys=[],
            cohort_sizes=[],
            retention_summary=CohortRetentionSummary(
                n_cohorts=0,
                n_periods=0,
            ),
            notes=["empty input rows"],
        )

    df = pd.DataFrame.from_records(inputs.rows)
    missing = [c for c in (inputs.cohort_col, inputs.event_col, inputs.time_col) if c not in df.columns]
    if missing:
        return CohortAnalysisOutputs(
            matrix=[],
            cohort_keys=[],
            cohort_sizes=[],
            retention_summary=CohortRetentionSummary(
                n_cohorts=0,
                n_periods=0,
            ),
            notes=[f"missing columns: {missing}"],
        )

    matrix, keys, sizes, summary_payload, notes = _build_matrix(
        df,
        cohort_col=inputs.cohort_col,
        event_col=inputs.event_col,
        time_col=inputs.time_col,
        periods=inputs.periods,
    )
    return CohortAnalysisOutputs(
        matrix=matrix,
        cohort_keys=keys,
        cohort_sizes=sizes,
        retention_summary=CohortRetentionSummary(**summary_payload),
        notes=notes,
    )
