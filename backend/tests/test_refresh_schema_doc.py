"""Golden-file unit tests for ``scripts.refresh_schema_doc.render_markdown``.

Phase A AI Insights v2 (arch §1.1).

Why render-only: ``collect_table_stats`` walks ``SQLModel.metadata`` (the
live app metadata, not an injectable). Exercising it end-to-end would
implicitly seed real app tables — fine for an integration smoke test but
brittle across migrations. The format-stability invariant we actually
care about (header layout, table sort, column rows, FKs, top-rows) lives
in ``render_markdown``, which is a pure function of ``list[TableStat]``.

Pattern: build a small deterministic ``TableStat`` list, render, replace
the timestamp line with ``<TS>``, diff against the golden fixture.
"""
from __future__ import annotations

import difflib
import os
import sys
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

# Avoid the alembic env.py side-effects if anything imports it transitively.
os.environ.setdefault("SKIP_SCHEMA_DOC_REFRESH", "1")

from scripts.refresh_schema_doc import (  # noqa: E402
    ColumnInfo,
    FKInfo,
    TableStat,
    render_markdown,
)

GOLDEN = Path(__file__).parent / "golden" / "SCHEMA.md.golden"


def _build_fixture_stats() -> list[TableStat]:
    """A small deterministic table set covering the format permutations we
    need to lock down: pk + non-null + nullable + FK; primary-metric vs
    no-metric; with-top-rows vs empty.
    """
    companies = TableStat(
        name="companies",
        row_count=3,
        columns=[
            ColumnInfo(name="id", type_str="INTEGER", nullable=False, primary_key=True),
            ColumnInfo(
                name="canonical_name",
                type_str="VARCHAR",
                nullable=False,
                primary_key=False,
            ),
            ColumnInfo(
                name="ticker", type_str="VARCHAR", nullable=True, primary_key=False
            ),
        ],
        fks=[],
        top_rows=[
            {"id": 1, "canonical_name": "Crusoe Energy", "ticker": None},
            {"id": 2, "canonical_name": "QTS Realty", "ticker": "QTS"},
            {"id": 3, "canonical_name": "CoreWeave", "ticker": "CRWV"},
        ],
        primary_metric=None,
    )
    sites = TableStat(
        name="sites",
        row_count=2,
        columns=[
            ColumnInfo(name="id", type_str="INTEGER", nullable=False, primary_key=True),
            ColumnInfo(
                name="power_capacity_mw",
                type_str="FLOAT",
                nullable=True,
                primary_key=False,
            ),
            ColumnInfo(
                name="provider_name",
                type_str="VARCHAR",
                nullable=True,
                primary_key=False,
            ),
            ColumnInfo(
                name="developer_company_id",
                type_str="INTEGER",
                nullable=True,
                primary_key=False,
                fk="companies.id",
            ),
        ],
        fks=[
            FKInfo(
                column="developer_company_id",
                target_table="companies",
                target_column="id",
            ),
        ],
        top_rows=[
            {
                "id": 11,
                "power_capacity_mw": 720.0,
                "provider_name": "PacifiCorp",
                "developer_company_id": 1,
            },
            {
                "id": 12,
                "power_capacity_mw": 220.0,
                "provider_name": "Dominion",
                "developer_company_id": 2,
            },
        ],
        primary_metric="power_capacity_mw",
    )
    # Empty / no-rows fixture, no metric, no FKs.
    events = TableStat(
        name="events",
        row_count=0,
        columns=[
            ColumnInfo(name="id", type_str="INTEGER", nullable=False, primary_key=True),
            ColumnInfo(
                name="event_date", type_str="DATE", nullable=True, primary_key=False
            ),
        ],
        fks=[],
        top_rows=[],
        primary_metric=None,
    )
    return [companies, sites, events]


def _scrub_timestamp(md: str) -> str:
    """Replace the generated-timestamp line so the golden file stays stable."""
    out_lines = []
    for line in md.splitlines():
        if line.startswith("# Schema Digest"):
            # "# Schema Digest — generated 2026-05-07T... (migration test_rev)"
            out_lines.append("# Schema Digest \u2014 generated <TS> (migration test_rev)")
        else:
            out_lines.append(line)
    return "\n".join(out_lines) + "\n" if md.endswith("\n") else "\n".join(out_lines)


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


def test_render_markdown_matches_golden(request):
    stats = _build_fixture_stats()
    rendered = render_markdown(stats, "test_rev")
    scrubbed = _scrub_timestamp(rendered)

    if not GOLDEN.exists() or os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(scrubbed, encoding="utf-8")
        if not GOLDEN.exists():  # pragma: no cover
            pytest.fail(f"wrote initial golden at {GOLDEN}")

    expected = GOLDEN.read_text(encoding="utf-8")
    if scrubbed != expected:
        pytest.fail(
            "SCHEMA.md drift vs golden:\n" + _diff(expected, scrubbed)
        )


def test_render_markdown_sort_by_row_count_desc():
    """Top-level table list must be sorted by row_count DESC then name ASC."""
    stats = [
        TableStat(name="z_small", row_count=1, columns=[], fks=[]),
        TableStat(name="a_large", row_count=100, columns=[], fks=[]),
        TableStat(name="b_medium", row_count=50, columns=[], fks=[]),
        TableStat(name="m_zero", row_count=0, columns=[], fks=[]),
    ]
    md = render_markdown(stats, "rev")

    # Order by row_count DESC: a_large, b_medium, z_small, m_zero
    a_pos = md.find("### `a_large`")
    b_pos = md.find("### `b_medium`")
    z_pos = md.find("### `z_small`")
    m_pos = md.find("### `m_zero`")
    assert -1 < a_pos < b_pos < z_pos < m_pos


def test_render_markdown_truncates_long_cells():
    """Cells longer than MAX_CELL_CHARS (80) are ellipsised."""
    long_value = "x" * 200
    stat = TableStat(
        name="companies",
        row_count=1,
        columns=[
            ColumnInfo(name="id", type_str="INTEGER", nullable=False, primary_key=True),
            ColumnInfo(
                name="canonical_name",
                type_str="VARCHAR",
                nullable=False,
                primary_key=False,
            ),
        ],
        fks=[],
        top_rows=[{"id": 1, "canonical_name": long_value}],
        primary_metric=None,
    )
    md = render_markdown([stat], "rev")
    assert "x" * 200 not in md  # full string must not appear
    # ellipsised form: 79 'x' + horizontal ellipsis
    assert "x" * 79 + "\u2026" in md


def test_render_markdown_includes_skipped_reason():
    stat = TableStat(
        name="locked_table",
        row_count=0,
        columns=[
            ColumnInfo(name="id", type_str="INTEGER", nullable=False, primary_key=True)
        ],
        fks=[],
        skipped_reason="count_failed: permission denied",
    )
    md = render_markdown([stat], "rev")
    assert "_skipped: count_failed: permission denied_" in md
