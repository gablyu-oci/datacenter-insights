"""ChartSpec Pydantic v2 validation tests (AI Insights V1).

Confirms that a valid line-chart example constructs and round-trips JSON,
that invalid inputs raise ValidationError, and that the on-disk JSON
schema file parses as JSON.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.insights.specs.chart_spec import (
    SCHEMA_PATH,
    ChartSpec,
    DataSource,
    Encoding,
    XEncoding,
    YEncoding,
)


def _valid_line_chart_dict() -> dict:
    rows = [
        {"month": "2026-01", "mw": 1200},
        {"month": "2026-02", "mw": 1300},
    ]
    row_hash = ChartSpec.compute_row_hash(rows)
    return {
        "chart_id": "c_a1b2c3d4",
        "chart_type": "line",
        "title": "MW Trend",
        "data_source": {
            "kind": "db_query",
            "spec": {"sql": "SELECT month, mw FROM trend"},
            "rows": len(rows),
            "fetched_at": datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc).isoformat(),
            "row_hash": row_hash,
        },
        "data": rows,
        "encoding": {
            "x": {"field": "month", "type": "time"},
            "y": {"field": "mw", "type": "quantitative"},
        },
    }


def test_valid_line_chart_constructs_and_round_trips():
    spec_dict = _valid_line_chart_dict()
    spec = ChartSpec.model_validate(spec_dict)
    assert spec.chart_type == "line"
    assert spec.encoding.x.field == "month"
    assert spec.encoding.y.field == "mw"

    # Round-trip JSON
    payload = spec.model_dump_json()
    reparsed = ChartSpec.model_validate_json(payload)
    assert reparsed.chart_id == spec.chart_id
    assert reparsed.recompute_row_hash() == spec.data_source.row_hash


def test_invalid_chart_type_raises():
    bad = _valid_line_chart_dict()
    bad["chart_type"] = "rainbow_pie"  # not in the closed Literal set
    with pytest.raises(ValidationError):
        ChartSpec.model_validate(bad)


def test_missing_required_field_raises():
    bad = _valid_line_chart_dict()
    del bad["title"]  # required
    with pytest.raises(ValidationError):
        ChartSpec.model_validate(bad)


def test_invalid_chart_id_format_raises():
    bad = _valid_line_chart_dict()
    bad["chart_id"] = "bad-chart-id"  # must match c_[0-9a-f]{8}
    with pytest.raises(ValidationError):
        ChartSpec.model_validate(bad)


def test_schema_json_file_loads():
    p = Path(SCHEMA_PATH)
    assert p.exists(), f"chart_spec.schema.json not found at {p}"
    parsed = json.loads(p.read_text())
    assert isinstance(parsed, dict)
    # Top-level JSON-Schema markers
    assert "properties" in parsed or "$defs" in parsed or "definitions" in parsed
