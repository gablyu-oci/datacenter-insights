"""build_chart — V2 MCP tool that builds, validates, and persists a ChartSpec.

V2 inverts the V1 ordering: the agent issues `build_chart(sql, encoding, ...)`
*before* it has chosen a final headline. The tool:

    1. Validates the SQL through `sql_gate.validate_sql` (DDL/DML, banned
       schemas, multi-statement, function blocklist, attached LIMIT).
    2. Executes the SELECT through the readonly `query_database` engine
       path (10s session statement_timeout, 5000-row hard cap).
    3. Pydantic-validates the encoding via a discriminated union keyed on
       `chart_type` (each shape declares which channels it requires).
    4. Cross-validates the encoding fields against the actual result
       columns — a `y.field` not present in the result is rejected as
       `encoding_field_missing`.
    5. Enforces `chart_type` compatibility per architecture §3.2:
         - stacked_bar / grouped_bar / stacked_area require `series`
         - line / area / stacked_area / sparkline require an `x.type` of
           "time" or "quantitative"
         - scatter / bubble require `y.type == "quantitative"` AND
           `x.type == "quantitative"`
         - bubble additionally requires `size`
         - treemap forbids a temporal x
         - pie / donut forbid `series` (single-axis aggregation only)
    6. Downsamples to the top 200 rows by `encoding.y.field DESC` when the
       result has more than 200 rows; sets `truncated=True`.
    7. Persists the ChartSpec to `agent_chart` scoped to `ctx.session_id`,
       leaving `insight_id` NULL (migration 018 made the column nullable).
       `persist_insight_v2` later updates `agent_chart.insight_id` to bind
       the chart to the freshly minted insight.

Returns ``{ok, chart_id, chart_spec, truncated, row_count, executed_sql}``.
On any validation failure returns ``{ok: False, error: <code>, detail: ...}``.

This module never raises — every failure is a structured tool_error so the
ToolLoopDriver can surface it back to the model as the next-turn input.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from ..specs.chart_spec import (
    ChartSpec,
    ChartType,
    DataSource,
    Encoding as ChartEncoding,
    XEncoding,
    YEncoding,
    SeriesEncoding,
    SizeEncoding,
    ColorEncoding,
    Annotation,
    Styling,
    MAX_ROWS_PER_CHART,
)
from ..specs.skill_context import SkillContext
from .query_database import query_database
from .sql_gate import SqlGateError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Per architecture §3.2: build_chart caps a single chart at 200 rows.
# (Schema-level cap is 500; build_chart is stricter to keep the visual
# tractable.)
DOWNSAMPLE_THRESHOLD = 200

# Chart types that require a `series` channel for grouping.
_REQUIRES_SERIES: set[str] = {"stacked_bar", "grouped_bar", "stacked_area"}

# Chart types that require x to be temporal-or-quantitative (i.e. NOT
# categorical).
_REQUIRES_CONTINUOUS_X: set[str] = {"line", "area", "stacked_area", "sparkline"}

# Chart types that forbid a temporal x.
_FORBIDS_TEMPORAL_X: set[str] = {"treemap", "pie", "donut", "kpi_tile"}

# Chart types that forbid `series`.
_FORBIDS_SERIES: set[str] = {"pie", "donut", "kpi_tile", "histogram"}


# ---------------------------------------------------------------------------
# Request models — discriminated union keyed on `chart_type`.
# ---------------------------------------------------------------------------
#
# We don't reinvent the encoding shape: the agent supplies the same
# Encoding sub-tree as ChartSpec.encoding. The discriminated wrapper here
# is only for *input shape* validation (each chart_type carries its own
# required channels). After the wrapper accepts, we project to the
# canonical `ChartEncoding` for the persisted ChartSpec.


class _BarEncoding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chart_type: Literal["bar", "stacked_bar", "grouped_bar", "histogram"]
    x: XEncoding
    y: YEncoding
    series: SeriesEncoding | None = None
    color: ColorEncoding | None = None


class _LineAreaEncoding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chart_type: Literal["line", "area", "stacked_area", "sparkline"]
    x: XEncoding
    y: YEncoding
    series: SeriesEncoding | None = None
    color: ColorEncoding | None = None


class _ScatterEncoding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chart_type: Literal["scatter", "bubble"]
    x: XEncoding
    y: YEncoding
    series: SeriesEncoding | None = None
    color: ColorEncoding | None = None
    size: SizeEncoding | None = None


class _PieEncoding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chart_type: Literal["pie", "donut"]
    x: XEncoding  # category field
    y: YEncoding  # quantitative measure
    color: ColorEncoding | None = None


class _SimpleEncoding(BaseModel):
    """treemap / kpi_tile / table / radar — single x + y, no series."""

    model_config = ConfigDict(extra="forbid")
    chart_type: Literal["treemap", "kpi_tile", "table", "radar"]
    x: XEncoding
    y: YEncoding
    color: ColorEncoding | None = None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BuildChartError(ValueError):
    def __init__(self, code: str, message: str, *, detail: dict[str, Any] | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail or {}


def _err(code: str, message: str, **detail: Any) -> dict[str, Any]:
    return {"ok": False, "error": code, "message": message, "detail": detail}


# ---------------------------------------------------------------------------
# Encoding compatibility checks
# ---------------------------------------------------------------------------


def _validate_encoding_shape(
    chart_type: str, encoding: dict[str, Any]
) -> ChartEncoding:
    """Pydantic-validate the encoding via the per-chart-type wrapper.

    Returns a canonical ChartEncoding on success; raises BuildChartError
    on shape mismatch.
    """
    enc_with_type = {**encoding, "chart_type": chart_type}
    candidates: list[type[BaseModel]]
    if chart_type in {"bar", "stacked_bar", "grouped_bar", "histogram"}:
        candidates = [_BarEncoding]
    elif chart_type in {"line", "area", "stacked_area", "sparkline"}:
        candidates = [_LineAreaEncoding]
    elif chart_type in {"scatter", "bubble"}:
        candidates = [_ScatterEncoding]
    elif chart_type in {"pie", "donut"}:
        candidates = [_PieEncoding]
    elif chart_type in {"treemap", "kpi_tile", "table", "radar"}:
        candidates = [_SimpleEncoding]
    else:
        raise BuildChartError(
            "unsupported_chart_type",
            f"chart_type={chart_type!r} is not a recognised v1 ChartType",
            detail={"chart_type": chart_type},
        )

    for model in candidates:
        try:
            validated = model.model_validate(enc_with_type)
            break
        except ValidationError as exc:
            raise BuildChartError(
                "encoding_shape_invalid",
                f"encoding payload does not match {chart_type} schema: {exc.errors()[:3]}",
                detail={"errors": exc.errors()[:5]},
            ) from exc

    payload = validated.model_dump(exclude={"chart_type"}, exclude_none=True)
    return ChartEncoding.model_validate(payload)


def _validate_compatibility(chart_type: str, enc: ChartEncoding) -> None:
    """Enforce architecture §3.2 chart_type ↔ encoding rules."""
    if chart_type in _REQUIRES_SERIES and enc.series is None:
        raise BuildChartError(
            "series_required",
            f"chart_type={chart_type!r} requires `series.field`",
            detail={"chart_type": chart_type},
        )
    if chart_type in _FORBIDS_SERIES and enc.series is not None:
        raise BuildChartError(
            "series_forbidden",
            f"chart_type={chart_type!r} does not allow a `series` channel",
            detail={"chart_type": chart_type},
        )
    if chart_type in _REQUIRES_CONTINUOUS_X and enc.x.type == "category":
        raise BuildChartError(
            "x_must_be_continuous",
            f"chart_type={chart_type!r} requires x.type in {{time, quantitative}}; got {enc.x.type!r}",
            detail={"chart_type": chart_type, "x_type": enc.x.type},
        )
    if chart_type in _FORBIDS_TEMPORAL_X and enc.x.type == "time":
        raise BuildChartError(
            "x_must_not_be_temporal",
            f"chart_type={chart_type!r} forbids a temporal x.type",
            detail={"chart_type": chart_type, "x_type": enc.x.type},
        )
    if chart_type in {"scatter", "bubble"}:
        if enc.x.type != "quantitative":
            raise BuildChartError(
                "scatter_x_quantitative_required",
                f"chart_type={chart_type!r} requires x.type='quantitative'; got {enc.x.type!r}",
                detail={"chart_type": chart_type, "x_type": enc.x.type},
            )
        if enc.y.type != "quantitative":
            raise BuildChartError(
                "scatter_y_quantitative_required",
                f"chart_type={chart_type!r} requires y.type='quantitative'; got {enc.y.type!r}",
                detail={"chart_type": chart_type, "y_type": enc.y.type},
            )
    if chart_type == "bubble" and enc.size is None:
        raise BuildChartError(
            "bubble_size_required",
            "chart_type='bubble' requires a `size.field` channel",
        )


def _validate_fields_against_columns(
    enc: ChartEncoding, columns: list[str]
) -> None:
    """Each encoding `*.field` must be a column in the SQL result."""
    col_set = set(columns)
    needed: list[tuple[str, str]] = [("x", enc.x.field), ("y", enc.y.field)]
    if enc.series is not None:
        needed.append(("series", enc.series.field))
    if enc.size is not None:
        needed.append(("size", enc.size.field))
    if enc.color is not None and enc.color.field is not None:
        needed.append(("color", enc.color.field))
    missing = [(c, f) for c, f in needed if f not in col_set]
    if missing:
        raise BuildChartError(
            "encoding_field_missing",
            f"encoding fields not present in result columns: {missing}",
            detail={"missing": missing, "columns": columns},
        )


# ---------------------------------------------------------------------------
# Downsample
# ---------------------------------------------------------------------------


def _downsample(
    rows: list[dict[str, Any]], y_field: str, threshold: int = DOWNSAMPLE_THRESHOLD
) -> tuple[list[dict[str, Any]], bool]:
    """Top-N-by-y-desc downsample. Stable for ties (Python sort)."""
    if len(rows) <= threshold:
        return rows, False

    def _key(r: dict[str, Any]) -> float:
        v = r.get(y_field)
        try:
            return float(v) if v is not None else float("-inf")
        except (TypeError, ValueError):
            return float("-inf")

    sorted_rows = sorted(rows, key=_key, reverse=True)
    return sorted_rows[:threshold], True


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def _resolve_insight(
    db: Any, insight_id: str, session_id: uuid.UUID
) -> tuple[Any | None, str | None]:
    """Round 3: locate an `ai_insight` row to bind a freshly built chart to.

    Mirrors persist_insight_v2._resolve_chart shape. Returns
    (insight_row, error_code). When db is None or insight_id is None/empty
    callers should NOT call this — guard at the caller side.
    """
    if db is None or not insight_id:
        return None, None
    # Local import to keep parity with the rest of the file's lazy imports.
    from ..db.models import AIInsight

    try:
        iid = uuid.UUID(str(insight_id))
    except Exception:  # noqa: BLE001
        return None, "insight_not_found"
    result = await db.execute(select(AIInsight).where(AIInsight.id == iid))
    row = result.scalars().first() if hasattr(result, "scalars") else None
    if row is None and hasattr(result, "first"):
        row = result.first()
    if row is None:
        return None, "insight_not_found"
    row_sid = row.session_id
    try:
        row_sid_uuid = (
            row_sid if isinstance(row_sid, uuid.UUID) else uuid.UUID(str(row_sid))
        )
    except Exception:  # noqa: BLE001
        row_sid_uuid = None
    if row_sid_uuid != session_id:
        return None, "insight_session_mismatch"
    return row, None


async def _persist_chart_row(
    chart: ChartSpec,
    session_id: uuid.UUID | str,
    db: Any,
    insight_id: uuid.UUID | None = None,
) -> None:
    """Insert an `agent_chart` row scoped to the session.

    Round 3: when `insight_id` is provided (insight-first flow), the FK
    is populated at INSERT time so the chart binds to the freshly
    persisted insight in the same MCP transaction. When None, the
    legacy chart-first behaviour is preserved (`insight_id NULL`,
    persist_insight_v2 patches it later).

    Best-effort: persistence failure is logged but does not blow the
    tool.
    """
    if db is None:
        return
    try:
        from ..db.models import AgentChart

        sid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
        row = AgentChart(
            id=chart.chart_id,
            session_id=sid,
            insight_id=insight_id,  # Round 3: bound to ai_insight when insight-first
            spec=chart.model_dump(mode="json"),
            data_source=chart.data_source.model_dump(mode="json"),
            row_hash=chart.data_source.row_hash,
        )
        db.add(row)
        await db.flush()
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning(
            "ai_insights.build_chart.persist_failed",
            extra={"err": str(exc), "chart_id": chart.chart_id},
        )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _short_chart_id() -> str:
    return f"c_{uuid.uuid4().hex[:8]}"


async def build_chart(
    sql: str,
    encoding: dict[str, Any],
    chart_type: str,
    title: str,
    subtitle: str | None = None,
    *,
    annotations: list[dict[str, Any]] | None = None,
    styling: dict[str, Any] | None = None,
    ctx: SkillContext | None = None,
    db: Any = None,
    insight_id: str | None = None,
) -> dict[str, Any]:
    """Build, validate, and persist a ChartSpec for the current session.

    Parameters mirror the JSON tool schema in registry.py V2_TOOL_DEFS.
    `db` is an injection point so unit tests can pass a FakeDB without
    standing up a real Postgres; production callers leave it None and
    the orchestrator persists via `emit_chart_for_insight` afterwards.

    Round 3 (insight-first): ``insight_id`` is OPTIONAL. When provided,
    the freshly built chart's ``agent_chart`` row is FK-bound to the
    named ``ai_insight`` at INSERT time (insight must exist and live
    in the same session — guarded with ``insight_not_found`` /
    ``insight_session_mismatch``). When None or empty, behaviour is
    byte-identical to Round 2: the row lands with ``insight_id IS
    NULL`` and ``persist_insight_v2`` patches the FK on the other
    edge.
    """
    # ------------------------------------------------------------------
    # 0) Argument-level guards.
    # ------------------------------------------------------------------
    if chart_type not in {
        "line", "bar", "stacked_bar", "grouped_bar", "area", "stacked_area",
        "scatter", "bubble", "pie", "donut", "sparkline", "kpi_tile",
        "table", "treemap", "radar", "histogram",
    }:
        return _err(
            "unsupported_chart_type",
            f"chart_type={chart_type!r} is not a v1 ChartType",
            chart_type=chart_type,
        )
    if not title or len(title) > 200:
        return _err(
            "title_invalid",
            "title must be 1..200 chars",
            length=len(title) if title else 0,
        )
    if subtitle is not None and len(subtitle) > 300:
        return _err("subtitle_too_long", "subtitle exceeds 300 chars")

    # ------------------------------------------------------------------
    # 1) Validate the encoding shape *first* so we fail fast before
    #    spending a DB round-trip.
    # ------------------------------------------------------------------
    try:
        enc = _validate_encoding_shape(chart_type, encoding)
        _validate_compatibility(chart_type, enc)
    except BuildChartError as exc:
        return _err(exc.code, exc.message, **exc.detail)

    # ------------------------------------------------------------------
    # 2) Run the SQL through the gate + executor.
    # ------------------------------------------------------------------
    try:
        result = await query_database(sql, ctx=ctx, max_rows=5_000)
    except SqlGateError as exc:
        return _err(
            "sql_gate_rejected",
            exc.message if hasattr(exc, "message") else str(exc),
            gate_code=getattr(exc, "code", None),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ai_insights.build_chart.query_failed", extra={"err": str(exc)})
        return _err("query_failed", str(exc))

    rows: list[dict[str, Any]] = list(result.get("rows") or [])
    columns: list[str] = list(result.get("columns") or [])
    executed_sql: str = result.get("executed_sql") or sql
    fetched_at_str: str = result.get("fetched_at") or datetime.now(timezone.utc).isoformat()

    if not rows:
        return _err(
            "empty_result",
            "SQL returned 0 rows; cannot build a chart from empty data",
            executed_sql=executed_sql,
        )

    # ------------------------------------------------------------------
    # 3) Cross-check encoding fields against actual columns.
    # ------------------------------------------------------------------
    try:
        _validate_fields_against_columns(enc, columns)
    except BuildChartError as exc:
        return _err(exc.code, exc.message, **exc.detail)

    # ------------------------------------------------------------------
    # 4) Downsample if needed.
    # ------------------------------------------------------------------
    final_rows, truncated = _downsample(rows, enc.y.field)

    # ------------------------------------------------------------------
    # 5) Build + validate ChartSpec.
    # ------------------------------------------------------------------
    chart_id = _short_chart_id()
    row_hash = ChartSpec.compute_row_hash(final_rows)
    try:
        fetched_at_dt = datetime.fromisoformat(fetched_at_str.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        fetched_at_dt = datetime.now(timezone.utc)

    try:
        spec = ChartSpec(
            chart_id=chart_id,
            chart_type=chart_type,  # type: ignore[arg-type]
            title=title,
            subtitle=subtitle,
            data_source=DataSource(
                kind="db_query",
                spec={"sql": executed_sql},
                rows=len(final_rows),
                fetched_at=fetched_at_dt,
                row_hash=row_hash,
            ),
            data=final_rows,
            encoding=enc,
            annotations=[Annotation.model_validate(a) for a in (annotations or [])] or None,
            styling=Styling.model_validate(styling) if styling else None,
        )
    except ValidationError as exc:
        return _err(
            "chart_spec_invalid",
            f"ChartSpec validation failed: {exc.errors()[:3]}",
            errors=exc.errors()[:5],
        )

    # Defence-in-depth: a row count beyond ChartSpec's hard MAX_ROWS_PER_CHART
    # (500) means our downsample threshold is mis-set. Refuse rather than
    # silently mutate.
    if len(spec.data) > MAX_ROWS_PER_CHART:
        return _err(
            "row_cap_exceeded",
            f"chart row count {len(spec.data)} exceeds {MAX_ROWS_PER_CHART}",
        )

    # ------------------------------------------------------------------
    # 6) Persist.
    # ------------------------------------------------------------------
    session_id = (
        getattr(ctx, "session_id", None)
        if ctx is not None
        else None
    )

    # Round 3: optional insight_id binds this chart to a freshly
    # persisted ai_insight row in the same session. Resolve + validate
    # before the chart row is INSERTed so the FK either lands populated
    # or the call fails atomically (no orphan chart row).
    insight_id_present = isinstance(insight_id, str) and bool(insight_id)
    resolved_insight_uuid: uuid.UUID | None = None
    if insight_id_present:
        if db is None or session_id is None:
            return _err(
                "insight_not_found",
                "build_chart with insight_id requires db + ctx.session_id",
                insight_id=insight_id,
            )
        try:
            sid_uuid = (
                session_id
                if isinstance(session_id, uuid.UUID)
                else uuid.UUID(str(session_id))
            )
        except Exception:  # noqa: BLE001
            sid_uuid = None
        if sid_uuid is None:
            return _err(
                "session_id_required",
                "build_chart with insight_id requires a uuid-coercible ctx.session_id",
            )
        insight_row, insight_err = await _resolve_insight(db, insight_id, sid_uuid)
        if insight_err is not None:
            return _err(
                insight_err,
                f"insight guard failed: {insight_err}",
                insight_id=insight_id,
            )
        try:
            row_id = getattr(insight_row, "id", None)
            resolved_insight_uuid = (
                row_id if isinstance(row_id, uuid.UUID) else uuid.UUID(str(row_id))
            )
        except Exception:  # noqa: BLE001
            resolved_insight_uuid = None

    if session_id is not None:
        await _persist_chart_row(
            spec, session_id, db, insight_id=resolved_insight_uuid
        )

    if resolved_insight_uuid is not None:
        logger.info(
            "ai_insights.build_chart.bound_to_insight",
            extra={
                "chart_id": chart_id,
                "insight_id": str(resolved_insight_uuid),
            },
        )

    logger.info(
        "ai_insights.build_chart.ok",
        extra={
            "chart_id": chart_id,
            "chart_type": chart_type,
            "row_count": len(final_rows),
            "truncated": truncated,
            "insight_id": (
                str(resolved_insight_uuid) if resolved_insight_uuid else None
            ),
        },
    )

    return {
        "ok": True,
        "chart_id": chart_id,
        "chart_spec": spec.model_dump(mode="json"),
        "row_count": len(final_rows),
        "truncated": truncated,
        "executed_sql": executed_sql,
        "insight_id": (
            str(resolved_insight_uuid) if resolved_insight_uuid else None
        ),
    }


__all__ = ["build_chart", "BuildChartError", "DOWNSAMPLE_THRESHOLD"]
