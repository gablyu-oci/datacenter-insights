"""ChartSpec v1 — Pydantic schema for agent-emitted charts.

Authoritative source for the JSON the agent's `emit_chart` tool produces and
the frontend's `<InsightChart>` consumes. The on-disk JSON Schema lives in
`chart_spec.schema.json` (regenerated via the `dump_json_schema` helper
below).

ARCHITECTURE.md A4 is the ratifying reference. Field naming follows A4.1 —
where A4.1 differs from PRD §5.2 (e.g. `chart_type` vs `type`,
`data_source.kind = "db_query"|"router_call"|"chart_data"` vs PRD's
`"query"|"api"|"chart_data"`, `Styling` vs PRD's `formatting`,
snake_case chart types), the architecture doc wins.

Rules enforced server-side:
- `data` length must be <= 500 rows (PRD §5.2 / ARCH A4.2).
- `chart_id` must match `^c_[0-9a-f]{8}$` (stable per session).
- `data_source.spec` keys must match the chosen `data_source.kind`.
- `data_source.row_hash` must equal a freshly-computed sha256 of the
  canonicalised `data` rows (used at `emit_chart` to defeat fabrication).

NO business logic in this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Closed-set type aliases
# ---------------------------------------------------------------------------

# Per ARCHITECTURE.md A4.1. Closed set; no maps in V1 (deferred V3).
ChartType = Literal[
    "line",
    "bar",
    "stacked_bar",
    "grouped_bar",
    "area",
    "stacked_area",
    "scatter",
    "pie",
    "sparkline",
    "kpi_tile",
]

# Per ARCHITECTURE.md A4.1.
DataSourceKind = Literal["db_query", "router_call", "chart_data"]

XAxisType = Literal["category", "time", "quantitative"]
YAxisType = Literal["quantitative"]
AnnotationType = Literal["line", "band", "point"]
ColorScheme = Literal["categorical", "sequential"]
YUnit = Literal["GW", "MW", "USD", "count", "%"]
Palette = Literal["oci_brand"]

# Stable per-session chart id format (ARCH A4.1 + A4.2).
CHART_ID_RE = re.compile(r"^c_[0-9a-f]{8}$")

# Hard caps (ARCH A4.2).
MAX_ROWS_PER_CHART = 500
MAX_SERIES = 8


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class DataSource(BaseModel):
    """Provenance block — every chart cites where its rows came from."""

    model_config = ConfigDict(extra="forbid")

    kind: DataSourceKind
    # Discriminator-by-key payload. One of:
    #   {"sql": str}                           when kind == "db_query"
    #   {"endpoint": str, "params": dict}      when kind == "router_call"
    #   {"tab": str, "chart_id": str}          when kind == "chart_data"
    spec: dict[str, Any]
    rows: int = Field(..., ge=0)
    fetched_at: datetime
    row_hash: str = Field(..., min_length=64, max_length=64)

    @field_validator("row_hash")
    @classmethod
    def _row_hash_is_hex(cls, v: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", v):
            raise ValueError("row_hash must be a 64-char lowercase hex sha256 digest")
        return v

    @model_validator(mode="after")
    def _spec_matches_kind(self) -> DataSource:
        """ARCH A4.2: data_source.spec must match the declared kind."""
        if self.kind == "db_query":
            required = {"sql"}
        elif self.kind == "router_call":
            required = {"endpoint"}  # `params` optional
        elif self.kind == "chart_data":
            required = {"tab", "chart_id"}
        else:  # pragma: no cover — Literal narrows
            raise ValueError(f"unknown data_source.kind={self.kind!r}")

        missing = required - set(self.spec.keys())
        if missing:
            raise ValueError(
                f"data_source.spec missing required keys for kind={self.kind!r}: {sorted(missing)}"
            )

        # Tighten: forbid stray keys per kind so the agent can't smuggle data.
        allowed: set[str]
        if self.kind == "db_query":
            allowed = {"sql"}
        elif self.kind == "router_call":
            allowed = {"endpoint", "params"}
        else:  # chart_data
            allowed = {"tab", "chart_id"}
        extra = set(self.spec.keys()) - allowed
        if extra:
            raise ValueError(
                f"data_source.spec has unexpected keys for kind={self.kind!r}: {sorted(extra)}"
            )

        return self


class XEncoding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    type: XAxisType
    label: str | None = None
    tick_format: str | None = None


class YEncoding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    type: YAxisType = "quantitative"
    label: str | None = None
    tick_format: str | None = None


class SeriesEncoding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str


class ColorEncoding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str | None = None
    scheme: ColorScheme | None = None


class SizeEncoding(BaseModel):
    """Scatter-only size channel."""

    model_config = ConfigDict(extra="forbid")
    field: str


class Encoding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: XEncoding
    y: YEncoding
    series: SeriesEncoding | None = None
    color: ColorEncoding | None = None
    size: SizeEncoding | None = None


class Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: AnnotationType
    value: str | float
    label: str


class Styling(BaseModel):
    """Formatting / palette block (PRD §5.2 calls this `formatting`; ARCH A4.1
    names it `Styling`. We follow ARCH).
    """

    model_config = ConfigDict(extra="forbid")
    palette: Palette = "oci_brand"
    y_unit: YUnit | None = None
    y_precision: int | None = Field(default=None, ge=0, le=6)


# ---------------------------------------------------------------------------
# Top-level model
# ---------------------------------------------------------------------------


class ChartSpec(BaseModel):
    """ChartSpec v1 — see ARCHITECTURE.md A4."""

    model_config = ConfigDict(extra="forbid")

    chart_id: str
    chart_type: ChartType
    title: str = Field(..., min_length=1, max_length=200)
    subtitle: str | None = Field(default=None, max_length=300)
    data_source: DataSource
    data: list[dict[str, Any]]
    encoding: Encoding
    annotations: list[Annotation] | None = None
    styling: Styling | None = None

    # ------ field validators ------

    @field_validator("chart_id")
    @classmethod
    def _chart_id_format(cls, v: str) -> str:
        if not CHART_ID_RE.fullmatch(v):
            raise ValueError(
                f"chart_id must match {CHART_ID_RE.pattern!r} (e.g. 'c_a1b2c3d4')"
            )
        return v

    @field_validator("data")
    @classmethod
    def _data_size_cap(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(v) > MAX_ROWS_PER_CHART:
            raise ValueError(
                f"data has {len(v)} rows; max is {MAX_ROWS_PER_CHART} (ARCH A4.2)"
            )
        return v

    # ------ helpers ------

    @classmethod
    def canonical_row_bytes(cls, rows: list[dict[str, Any]]) -> bytes:
        """Canonicalise rows for stable hashing.

        Rules (ARCH A4.2 row_hash semantics):
          - keys sorted lexicographically inside each row
          - rows serialised as a JSON array, no whitespace, ensure_ascii
          - row order is preserved (the agent chose it deliberately)
        """
        return json.dumps(
            rows,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        ).encode("utf-8")

    @classmethod
    def compute_row_hash(cls, rows: list[dict[str, Any]]) -> str:
        """Return sha256 hex digest over canonicalised rows."""
        return hashlib.sha256(cls.canonical_row_bytes(rows)).hexdigest()

    def recompute_row_hash(self) -> str:
        """Recompute the hash from `self.data` for emit-time verification."""
        return self.compute_row_hash(self.data)

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        """Pydantic v2 JSON Schema export (alias for `model_json_schema`)."""
        return cls.model_json_schema()


# ---------------------------------------------------------------------------
# CLI / on-disk schema dump
# ---------------------------------------------------------------------------

SCHEMA_PATH = Path(__file__).with_name("chart_spec.schema.json")


def dump_json_schema(path: Path | str = SCHEMA_PATH) -> Path:
    """Write the ChartSpec JSON Schema to `path`. Used by the build script
    that materialises `chart_spec.schema.json` next to this module.
    """
    out = Path(path)
    out.write_text(json.dumps(ChartSpec.model_json_schema(), indent=2) + "\n")
    return out


if __name__ == "__main__":  # pragma: no cover
    written = dump_json_schema()
    print(f"wrote {written}")
    # Surface the timestamp the schema was generated at, for log audit trails.
    print(f"generated_at={datetime.now(UTC).isoformat()}")
