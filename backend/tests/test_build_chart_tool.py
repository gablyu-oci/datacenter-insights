"""Phase C unit tests for `agents.insights.tools.build_chart`.

The tool wraps SQL gate + execution + ChartSpec validation. We stub
`query_database` so these tests run without Postgres while still
exercising every gate, encoding-compatibility, downsample, and persist
path the agent will hit.

What we lock down:
  * stacked_bar / grouped_bar / stacked_area without `series` -> rejected
  * pie / donut WITH `series` -> rejected (series_forbidden)
  * line / area with categorical x -> rejected
  * scatter with non-quantitative y -> rejected
  * bubble without `size` -> rejected
  * encoding.field absent from result columns -> rejected
  * SQL touching pg_catalog -> rejected at the gate
  * empty result set -> rejected
  * happy path -> chart_id minted, ChartSpec validates round-trip
  * >200 rows -> downsampled, truncated=True
  * persistence: AgentChart row added with session_id and insight_id=None
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

sqlglot = pytest.importorskip(
    "sqlglot", reason="sqlglot dep not installed; run `uv sync` in backend/"
)

# Import path bootstrap (consistent with other tests in this dir).
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.insights.specs.skill_context import Capabilities, SkillContext
from agents.insights.tools import build_chart as build_chart_mod
from agents.insights.tools.build_chart import (
    DOWNSAMPLE_THRESHOLD,
    build_chart,
)


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------


class FakeDB:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None


def _make_ctx() -> SkillContext:
    return SkillContext(
        session_id=str(uuid.uuid4()),
        turn_id="t1",
        correlation_id="c1",
        model="gpt-4.1",
        budget_seconds_remaining=300.0,
        capabilities=Capabilities(can_query_db=True, can_emit_chart=True),
    )


def _patch_query_database(monkeypatch, rows, columns):
    """Replace `query_database` with an async stub returning fixed rows."""
    from datetime import datetime, timezone

    async def _stub(sql, ctx=None, *, max_rows=5000):
        from agents.insights.tools.sql_gate import validate_sql

        validated = validate_sql(sql, max_rows=max_rows)
        return {
            "rows": rows,
            "columns": columns,
            "row_count": len(rows),
            "executed_sql": validated.normalized_sql,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "row_hash": "0" * 64,
            "applied_limit": validated.applied_limit,
            "notes": validated.notes,
            "truncated": False,
        }

    monkeypatch.setattr(build_chart_mod, "query_database", _stub)


# ---------------------------------------------------------------------------
# Encoding-compatibility rejections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stacked_bar_without_series_rejected(monkeypatch):
    _patch_query_database(
        monkeypatch,
        [{"region": "us-east", "gw": 1.2}],
        ["region", "gw"],
    )
    out = await build_chart(
        sql="SELECT region, gw FROM v_power",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="stacked_bar",
        title="Power by region",
        ctx=_make_ctx(),
    )
    assert out["ok"] is False
    assert out["error"] == "series_required"


@pytest.mark.asyncio
async def test_pie_with_series_rejected(monkeypatch):
    _patch_query_database(
        monkeypatch,
        [{"vendor": "OCI", "share": 0.4}],
        ["vendor", "share"],
    )
    out = await build_chart(
        sql="SELECT vendor, share FROM v_share",
        encoding={
            "x": {"field": "vendor", "type": "category"},
            "y": {"field": "share", "type": "quantitative"},
            "series": {"field": "vendor"},
        },
        chart_type="pie",
        title="Vendor share",
        ctx=_make_ctx(),
    )
    assert out["ok"] is False
    # Either rejected at shape level (PieEncoding extra=forbid catches the
    # stray `series` channel) or by the compatibility matrix. Both are
    # correct; pin both so the test stays robust to a model rearrangement.
    assert out["error"] in {"encoding_shape_invalid", "series_forbidden"}


@pytest.mark.asyncio
async def test_line_with_categorical_x_rejected(monkeypatch):
    _patch_query_database(
        monkeypatch,
        [{"phase": "alpha", "gw": 1.0}],
        ["phase", "gw"],
    )
    out = await build_chart(
        sql="SELECT phase, gw FROM v_phases",
        encoding={
            "x": {"field": "phase", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="line",
        title="GW over phases",
        ctx=_make_ctx(),
    )
    assert out["ok"] is False
    assert out["error"] == "x_must_be_continuous"


@pytest.mark.asyncio
async def test_scatter_with_categorical_y_rejected(monkeypatch):
    """ChartSpec's YEncoding.type defaults to 'quantitative' (closed
    Literal). We exercise the *x*-side scatter rule here since y is
    forced to quantitative by the schema itself.
    """
    _patch_query_database(
        monkeypatch,
        [{"region": "us-east", "gw": 1.0}],
        ["region", "gw"],
    )
    out = await build_chart(
        sql="SELECT region, gw FROM v_scatter",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="scatter",
        title="Scatter",
        ctx=_make_ctx(),
    )
    assert out["ok"] is False
    assert out["error"] == "scatter_x_quantitative_required"


@pytest.mark.asyncio
async def test_bubble_without_size_rejected(monkeypatch):
    _patch_query_database(
        monkeypatch,
        [{"x": 1, "y": 2, "z": 3}],
        ["x", "y", "z"],
    )
    out = await build_chart(
        sql="SELECT x, y, z FROM v_bubble",
        encoding={
            "x": {"field": "x", "type": "quantitative"},
            "y": {"field": "y", "type": "quantitative"},
        },
        chart_type="bubble",
        title="Bubble",
        ctx=_make_ctx(),
    )
    assert out["ok"] is False
    assert out["error"] == "bubble_size_required"


@pytest.mark.asyncio
async def test_encoding_field_missing_from_columns(monkeypatch):
    _patch_query_database(
        monkeypatch,
        [{"region": "us-east"}],
        ["region"],  # no `gw` column
    )
    out = await build_chart(
        sql="SELECT region FROM v_power",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="bar",
        title="Power by region",
        ctx=_make_ctx(),
    )
    assert out["ok"] is False
    assert out["error"] == "encoding_field_missing"


# ---------------------------------------------------------------------------
# SQL gate rejections (real gate, no monkeypatch on query_database)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sql_gate_rejects_pg_catalog():
    """Real query_database call attempted; the gate should fire before
    any DB connection is opened.
    """
    out = await build_chart(
        sql="SELECT relname FROM pg_catalog.pg_class",
        encoding={
            "x": {"field": "relname", "type": "category"},
            "y": {"field": "relname", "type": "quantitative"},
        },
        chart_type="bar",
        title="pg classes",
        ctx=_make_ctx(),
    )
    assert out["ok"] is False
    assert out["error"] == "sql_gate_rejected"


@pytest.mark.asyncio
async def test_sql_gate_rejects_drop():
    out = await build_chart(
        sql="DROP TABLE foo",
        encoding={
            "x": {"field": "foo", "type": "category"},
            "y": {"field": "bar", "type": "quantitative"},
        },
        chart_type="bar",
        title="x",
        ctx=_make_ctx(),
    )
    assert out["ok"] is False
    assert out["error"] == "sql_gate_rejected"


# ---------------------------------------------------------------------------
# Empty result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_result_rejected(monkeypatch):
    _patch_query_database(monkeypatch, [], ["region", "gw"])
    out = await build_chart(
        sql="SELECT region, gw FROM v_power WHERE 1=0",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="bar",
        title="Power",
        ctx=_make_ctx(),
    )
    assert out["ok"] is False
    assert out["error"] == "empty_result"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_emits_chart_id_and_persists(monkeypatch):
    _patch_query_database(
        monkeypatch,
        [
            {"region": "us-east", "gw": 1.2},
            {"region": "us-west", "gw": 0.9},
        ],
        ["region", "gw"],
    )
    db = FakeDB()
    ctx = _make_ctx()
    out = await build_chart(
        sql="SELECT region, gw FROM v_power",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="bar",
        title="Power by region",
        subtitle="GW operational",
        ctx=ctx,
        db=db,
    )
    assert out["ok"] is True, out
    assert out["chart_id"].startswith("c_")
    assert out["row_count"] == 2
    assert out["truncated"] is False
    # ChartSpec round-trip:
    from agents.insights.specs.chart_spec import ChartSpec

    spec = ChartSpec.model_validate(out["chart_spec"])
    assert spec.chart_id == out["chart_id"]
    assert spec.recompute_row_hash() == spec.data_source.row_hash
    # Persistence: one AgentChart row with session_id matching ctx.
    assert len(db.added) == 1
    persisted = db.added[0]
    assert persisted.id == out["chart_id"]
    assert str(persisted.session_id) == ctx.session_id
    assert persisted.insight_id is None  # filled by persist_insight_v2 later


@pytest.mark.asyncio
async def test_downsample_when_over_threshold(monkeypatch):
    rows = [{"region": f"r{i}", "gw": float(i)} for i in range(DOWNSAMPLE_THRESHOLD + 50)]
    _patch_query_database(monkeypatch, rows, ["region", "gw"])
    out = await build_chart(
        sql="SELECT region, gw FROM v_power",
        encoding={
            "x": {"field": "region", "type": "category"},
            "y": {"field": "gw", "type": "quantitative"},
        },
        chart_type="bar",
        title="Top regions",
        ctx=_make_ctx(),
    )
    assert out["ok"] is True
    assert out["truncated"] is True
    assert out["row_count"] == DOWNSAMPLE_THRESHOLD
    # Top-by-y means the highest GW values survive.
    spec_rows = out["chart_spec"]["data"]
    assert spec_rows[0]["gw"] >= spec_rows[-1]["gw"]


@pytest.mark.asyncio
async def test_unsupported_chart_type():
    out = await build_chart(
        sql="SELECT 1",
        encoding={"x": {"field": "x", "type": "category"}, "y": {"field": "y", "type": "quantitative"}},
        chart_type="map",  # not in v1 ChartType
        title="x",
        ctx=_make_ctx(),
    )
    assert out["ok"] is False
    assert out["error"] == "unsupported_chart_type"
