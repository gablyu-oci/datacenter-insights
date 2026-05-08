"""Golden-file unit tests for ``scripts.refresh_freshness_doc.render_markdown``.

Phase A AI Insights v2 (arch §1.3 / §2.3).

Render-only: ``collect_freshness`` issues information_schema lookups +
SET LOCAL statement_timeout, both Postgres-specific. The format-stability
tests live on ``render_markdown``, which is a pure function of
``list[FreshnessRow]``.

Cases:
  * Matches golden fixture (sort by delta_7d DESC, hot rollup).
  * Hot threshold: tables with pct_change_7d > 0.05 appear in the rollup,
    others do not.
  * No hot tables -> placeholder line in the rollup.
"""
from __future__ import annotations

import difflib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from scripts.refresh_freshness_doc import (  # noqa: E402
    FreshnessRow,
    render_markdown,
)

GOLDEN = Path(__file__).parent / "golden" / "FRESHNESS.md.golden"

FIXED_NOW = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)


def _build_fixture_rows() -> list[FreshnessRow]:
    return [
        FreshnessRow(
            table="sites",
            rows=400,
            max_ts=datetime(2026, 5, 7, 11, 30, 0, tzinfo=timezone.utc),
            delta_7d=80,
            delta_24h=12,
            pct_change_7d=80 / 400,  # 20% -> hot
        ),
        FreshnessRow(
            table="companies",
            rows=1000,
            max_ts=datetime(2026, 5, 7, 9, 0, 0, tzinfo=timezone.utc),
            delta_7d=10,  # 1% -> not hot
            delta_24h=2,
            pct_change_7d=10 / 1000,
        ),
        FreshnessRow(
            table="events",
            rows=0,
            max_ts=None,
            delta_7d=0,
            delta_24h=0,
            pct_change_7d=0.0,
            note="no_timestamp_column",
        ),
    ]


def _diff(expected: str, actual: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile="expected",
            tofile="actual",
            lineterm="",
        )
    )


def test_render_markdown_matches_golden():
    rendered = render_markdown(_build_fixture_rows(), FIXED_NOW)

    if not GOLDEN.exists() or os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(rendered, encoding="utf-8")

    expected = GOLDEN.read_text(encoding="utf-8")
    if rendered != expected:
        pytest.fail(
            "FRESHNESS.md drift vs golden:\n" + _diff(expected, rendered)
        )


def test_hot_tables_threshold_includes_growers_excludes_quiet():
    rows = [
        FreshnessRow(
            table="hot_table",
            rows=100,
            max_ts=FIXED_NOW,
            delta_7d=20,
            delta_24h=5,
            pct_change_7d=0.20,  # > 0.05 -> hot
        ),
        FreshnessRow(
            table="quiet_table",
            rows=100,
            max_ts=FIXED_NOW,
            delta_7d=4,
            delta_24h=1,
            pct_change_7d=0.04,  # < 0.05 -> NOT hot
        ),
        FreshnessRow(
            table="boundary_table",
            rows=100,
            max_ts=FIXED_NOW,
            delta_7d=5,
            delta_24h=1,
            pct_change_7d=0.05,  # exactly threshold -> per ">", NOT hot
        ),
    ]
    md = render_markdown(rows, FIXED_NOW)

    # The rollup section must exist.
    assert "## Hot tables" in md

    # Split body / hot rollup so we don't false-positive on the table grid.
    hot_section = md.split("## Hot tables", 1)[1]
    assert "- hot_table (+20.0%)" in hot_section
    assert "quiet_table" not in hot_section
    # boundary at exactly 5%: spec uses ">" so excluded.
    assert "boundary_table" not in hot_section


def test_hot_tables_empty_message_when_none_exceed_threshold():
    rows = [
        FreshnessRow(
            table="quiet_a",
            rows=1000,
            max_ts=FIXED_NOW,
            delta_7d=1,
            delta_24h=0,
            pct_change_7d=0.001,
        ),
    ]
    md = render_markdown(rows, FIXED_NOW)
    hot_section = md.split("## Hot tables", 1)[1]
    assert "_(no tables exceeded the threshold this window)_" in hot_section


def test_render_markdown_sort_by_delta_7d_desc():
    rows = [
        FreshnessRow(
            table="small_growth",
            rows=10,
            max_ts=FIXED_NOW,
            delta_7d=2,
            delta_24h=0,
            pct_change_7d=0.2,
        ),
        FreshnessRow(
            table="big_growth",
            rows=10,
            max_ts=FIXED_NOW,
            delta_7d=8,
            delta_24h=1,
            pct_change_7d=0.8,
        ),
    ]
    md = render_markdown(rows, FIXED_NOW)
    big_pos = md.find("| big_growth ")
    small_pos = md.find("| small_growth ")
    assert -1 < big_pos < small_pos
