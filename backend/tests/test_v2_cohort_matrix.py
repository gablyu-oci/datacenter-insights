"""V2 cohort_analysis skill tests.

Pins behaviour of `agents/insights/skills/cohort_analysis/tool.py`:
- happy path: rows = N distinct cohorts; columns = max periods + 1;
  every retention rate ∈ [0,1]; row 0 of every cohort is 1.0.
- empty rows -> empty matrix, no exception.
- integer cohort keys still bucket correctly.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))
for p in (BACKEND_ROOT, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from agents.insights.skills.cohort_analysis.inputs import CohortAnalysisInputs  # noqa: E402
from agents.insights.skills.cohort_analysis.tool import run as cohort_run  # noqa: E402


# ---------------------------------------------------------------------------
# (5a) Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_monthly_cohort_matrix_shape_and_bounds():
    """Two monthly cohorts, each with 3 periods of activity."""
    rows: list[dict] = []
    # Cohort 2024-01: 2 entities, both active periods 0,1; one drops at 2.
    for ent_idx in range(2):
        rows.append(
            {"cohort": "2024-01", "ts": datetime(2024, 1, 15), "active": 1, "_e": ent_idx}
        )
        rows.append(
            {"cohort": "2024-01", "ts": datetime(2024, 2, 15), "active": 1, "_e": ent_idx}
        )
    # Only entity 0 active at +2.
    rows.append({"cohort": "2024-01", "ts": datetime(2024, 3, 15), "active": 1, "_e": 0})

    # Cohort 2024-02: 2 entities, all active periods 0,1.
    for ent_idx in range(2):
        rows.append(
            {"cohort": "2024-02", "ts": datetime(2024, 2, 15), "active": 1, "_e": ent_idx}
        )
        rows.append(
            {"cohort": "2024-02", "ts": datetime(2024, 3, 15), "active": 1, "_e": ent_idx}
        )

    out = await cohort_run(
        CohortAnalysisInputs(
            rows=rows,
            cohort_col="cohort",
            event_col="active",
            time_col="ts",
            periods=3,
        )
    )

    matrix = out.matrix
    assert len(matrix) == 2, f"expected 2 cohorts, got {len(matrix)}: {out.cohort_keys}"
    # max periods + 1 = 4 columns (period 0..3).
    assert all(len(r) == 4 for r in matrix), [len(r) for r in matrix]
    # Every value in [0,1] and float.
    for r in matrix:
        for v in r:
            assert isinstance(v, float)
            assert 0.0 <= v <= 1.0
    # Row-0 == 1.0 by construction.
    for r in matrix:
        assert r[0] == 1.0
    assert out.retention_summary.n_cohorts == 2
    assert out.retention_summary.n_periods == 4


# ---------------------------------------------------------------------------
# (5b) Empty input -> empty matrix, no exception.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_rows_returns_empty_matrix():
    out = await cohort_run(
        CohortAnalysisInputs(
            rows=[],
            cohort_col="cohort",
            event_col="active",
            time_col="ts",
            periods=3,
        )
    )
    assert out.matrix == []
    assert out.cohort_keys == []
    assert out.retention_summary.n_cohorts == 0


# ---------------------------------------------------------------------------
# (5c) Integer cohort keys still bucket correctly.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integer_cohort_keys_are_bucketed():
    rows = [
        {"cohort": 1, "ts": 0, "active": 1, "_e": "a"},
        {"cohort": 1, "ts": 1, "active": 1, "_e": "a"},
        {"cohort": 1, "ts": 2, "active": 1, "_e": "a"},
        {"cohort": 2, "ts": 0, "active": 1, "_e": "b"},
        {"cohort": 2, "ts": 1, "active": 1, "_e": "b"},
    ]
    out = await cohort_run(
        CohortAnalysisInputs(
            rows=rows,
            cohort_col="cohort",
            event_col="active",
            time_col="ts",
            periods=2,
        )
    )
    assert len(out.matrix) == 2
    # Row-0 of each cohort must be 1.0.
    for r in out.matrix:
        assert r[0] == 1.0
        assert all(0.0 <= v <= 1.0 for v in r)
