"""Generate `.openclaw/workspace/SCHEMA.md` for the AI Insights v2 agent.

Phase A deliverable per `docs/ai_insights_v2_phase_a_architecture.md` §1.1.

Walks `SQLModel.metadata.tables`, reads row counts and the top-10 sample
rows for each high-signal table (ordered by the table's `PRIMARY_METRIC`
column when one exists), and renders the markdown digest spec'd in
`docs/ai_insights_v2_spec.md` §4.1.

Invariants:
  * Atomic write: render to ``SCHEMA.md.tmp`` then ``os.replace`` so the
    agent never reads a partial file.
  * ``refresh()`` never raises out — failures are logged; a partial file
    is still emitted on best-effort.
  * Header includes ISO-8601 generation timestamp + alembic revision.

Run as a one-shot CLI for manual refresh::

    python -m scripts.refresh_schema_doc
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import SQLModel

# Side-effect: import db.models so SQLModel.metadata is fully populated
# even when this script is invoked outside the FastAPI process (CLI / hook).
from db import models as _db_models  # noqa: F401

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration — workspace path, high-signal tables, primary metric mapping
# ---------------------------------------------------------------------------

WORKSPACE_DIR_ENV = "OPENCLAW_WORKSPACE_DIR"
TARGET_FILENAME = "SCHEMA.md"

# Per arch §2.1 — the 12-table high-signal set used to drive the
# agent's "what entities exist?" lens at session start.
HIGH_SIGNAL_TABLES: list[str] = [
    "companies",
    "sites",
    "energy_projects",
    "power_projects",
    "edgar_extractions",
    "generator_permits",
    "building_permits",
    "power_deal_links",
    "anomalies",
    "events",
    "press_releases",
    "data_coverage",
]

# Primary metric column per arch §2.1 — used as the ORDER BY for the
# "Top 10" sample. ``None`` means no obvious metric column exists; the
# fallback chain is updated_at -> created_at -> unordered LIMIT 10.
PRIMARY_METRIC: dict[str, Optional[str]] = {
    "sites": "power_capacity_mw",
    "power_projects": "tot_phase_nameplate_power_mw",
    "energy_projects": "tot_contracted_power_mw",
    "edgar_extractions": "capacity_mw",
    "generator_permits": "rated_mw_total",
    "building_permits": "valuation_usd",
    "companies": None,
    "anomalies": "z_score",
    "data_coverage": "record_count",
    "events": None,
    "press_releases": None,
    "transcript_metrics": "numeric_value",
    "power_deal_links": "match_score",
    "brief_runs": None,
    "ingestion_runs": "records_stored",
}

# Static known-FK map. SQLModel doesn't always materialise formal FKs
# (some are implicit via ``_id`` columns), so we union this with the
# values returned by ``inspect(engine).get_foreign_keys()``.
KNOWN_FKS: dict[str, list[tuple[str, str, str]]] = {
    # table -> [(column, target_table, target_column), ...]
    "energy_projects": [],
    "power_projects": [],
    "power_deal_links": [
        ("edgar_extraction_id", "edgar_extractions", "id"),
        ("aterio_phase_uid", "power_projects", "aterio_phase_uid"),
    ],
    "edgar_extractions": [
        ("buyer_company_id", "companies", "id"),
        ("seller_company_id", "companies", "id"),
    ],
    "generator_permits": [
        ("resolved_company_id", "companies", "id"),
        ("site_id", "sites", "id"),
    ],
    "site_aliases": [("site_id", "sites", "id")],
    "company_aliases": [("company_id", "companies", "id")],
}

JOIN_PATHS_BLOCK = (
    "## High-signal join paths\n"
    "- companies <-(developer_companies[])- energy_projects -(state_code)-> sites\n"
    "- companies <-(buyer_company_id|seller_company_id)- edgar_extractions\n"
    "- power_projects <-(aterio_phase_uid)- power_deal_links -(edgar_extraction_id)-> edgar_extractions\n"
    "- sites -(state_code, county_fips)-> generator_permits (source='epa_echo')\n"
    "- sites -(state, county)-> building_permits\n"
)

MAX_CELL_CHARS = 80


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ColumnInfo:
    name: str
    type_str: str
    nullable: bool
    primary_key: bool
    fk: Optional[str] = None  # rendered "<target_table>.<target_col>"


@dataclass
class FKInfo:
    column: str
    target_table: str
    target_column: str


@dataclass
class TableStat:
    name: str
    row_count: int
    columns: list[ColumnInfo]
    fks: list[FKInfo]
    top_rows: list[dict[str, Any]] = field(default_factory=list)
    primary_metric: Optional[str] = None
    notes: list[str] = field(default_factory=list)
    skipped_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    """Return the project root (the dir that holds ``backend/`` and
    ``.openclaw/``).
    """
    # this file: <root>/backend/scripts/refresh_schema_doc.py
    return Path(__file__).resolve().parents[2]


def workspace_dir() -> Path:
    """Resolve the workspace dir, honouring ``OPENCLAW_WORKSPACE_DIR``."""
    env_val = os.environ.get(WORKSPACE_DIR_ENV)
    if env_val:
        return Path(env_val).resolve()
    return (_project_root() / ".openclaw" / "workspace").resolve()


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


def _column_type_repr(col) -> str:
    """Best-effort SQL type rendering. Handles Enum, JSONB, ARRAY decently."""
    try:
        # Strip any "(collation='...')" noise; keep the core type ident.
        return str(col.type)
    except Exception:  # pragma: no cover - defensive
        return col.type.__class__.__name__


def _columns_for(table) -> list[ColumnInfo]:
    cols: list[ColumnInfo] = []
    for col in table.columns:
        fk_target: Optional[str] = None
        if col.foreign_keys:
            # take first declared FK; multi-target FKs are rare here
            fk = next(iter(col.foreign_keys))
            fk_target = f"{fk.column.table.name}.{fk.column.name}"
        cols.append(
            ColumnInfo(
                name=col.name,
                type_str=_column_type_repr(col),
                nullable=bool(col.nullable),
                primary_key=bool(col.primary_key),
                fk=fk_target,
            )
        )
    return cols


def _fks_for(table_name: str, columns: list[ColumnInfo]) -> list[FKInfo]:
    """Union of formal FKs from metadata + ``KNOWN_FKS`` static map."""
    seen: set[tuple[str, str, str]] = set()
    fks: list[FKInfo] = []
    for c in columns:
        if c.fk is None:
            continue
        try:
            tgt_table, tgt_col = c.fk.split(".", 1)
        except ValueError:
            continue
        key = (c.name, tgt_table, tgt_col)
        if key in seen:
            continue
        seen.add(key)
        fks.append(FKInfo(column=c.name, target_table=tgt_table, target_column=tgt_col))
    for col, tgt_table, tgt_col in KNOWN_FKS.get(table_name, []):
        key = (col, tgt_table, tgt_col)
        if key in seen:
            continue
        seen.add(key)
        fks.append(FKInfo(column=col, target_table=tgt_table, target_column=tgt_col))
    return fks


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------


async def _row_count(conn, table_name: str) -> int:
    result = await conn.execute(text(f'SELECT count(*) FROM "{table_name}"'))
    val = result.scalar()
    return int(val or 0)


async def _alembic_revision(conn) -> str:
    try:
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        row = result.first()
        if row is None:
            return "unknown"
        return str(row[0])
    except Exception:
        return "unknown"


def _has_column(table, col_name: str) -> bool:
    return col_name in {c.name for c in table.columns}


def _order_by_clause(table, primary_metric: Optional[str]) -> str:
    """Pick an ORDER BY chain per arch §1.1 invariants."""
    if primary_metric and _has_column(table, primary_metric):
        return f'ORDER BY "{primary_metric}" DESC NULLS LAST'
    if _has_column(table, "updated_at"):
        return 'ORDER BY "updated_at" DESC NULLS LAST'
    if _has_column(table, "created_at"):
        return 'ORDER BY "created_at" DESC NULLS LAST'
    if _has_column(table, "id"):
        return 'ORDER BY "id" DESC'
    return ""


async def _top_rows(conn, table, primary_metric: Optional[str]) -> list[dict[str, Any]]:
    order_clause = _order_by_clause(table, primary_metric)
    sql = f'SELECT * FROM "{table.name}" {order_clause} LIMIT 10'.rstrip()
    result = await conn.execute(text(sql))
    out: list[dict[str, Any]] = []
    for record in result.mappings().all():
        out.append(dict(record))
    return out


async def collect_table_stats(engine: AsyncEngine) -> tuple[list[TableStat], str]:
    """Return (stats, alembic_revision). Never raises on individual table
    failures — sets ``skipped_reason`` and continues.
    """
    metadata = SQLModel.metadata
    tables = list(metadata.tables.values())

    stats: list[TableStat] = []
    alembic_rev = "unknown"
    async with engine.connect() as conn:
        alembic_rev = await _alembic_revision(conn)
        for table in tables:
            cols = _columns_for(table)
            fks = _fks_for(table.name, cols)
            metric = PRIMARY_METRIC.get(table.name)

            stat = TableStat(
                name=table.name,
                row_count=0,
                columns=cols,
                fks=fks,
                primary_metric=metric,
            )
            try:
                stat.row_count = await _row_count(conn, table.name)
            except Exception as exc:
                stat.skipped_reason = f"count_failed: {exc}"
                stats.append(stat)
                continue

            # only fetch top-rows for high-signal tables (cost / size budget)
            if table.name in HIGH_SIGNAL_TABLES:
                try:
                    stat.top_rows = await _top_rows(conn, table, metric)
                except Exception as exc:
                    stat.notes.append(f"top_rows_failed: {exc}")
            stats.append(stat)

    return stats, alembic_rev


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _truncate_cell(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    if len(s) > MAX_CELL_CHARS:
        s = s[: MAX_CELL_CHARS - 1] + "\u2026"
    # markdown table escape — replace pipes / newlines so cells stay one row
    return s.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _render_columns_table(cols: list[ColumnInfo]) -> str:
    out = ["| column | type | nullable | fk |", "|---|---|---|---|"]
    for c in cols:
        nullable = "yes" if c.nullable else "no"
        fk = "pk" if c.primary_key else (c.fk or "\u2014")
        out.append(f"| {c.name} | {c.type_str} | {nullable} | {fk} |")
    return "\n".join(out)


def _render_top_rows(stat: TableStat) -> str:
    if not stat.top_rows:
        return ""
    # Limit to a small set of columns: pk + metric + 4-6 highly-readable cols
    interesting = _interesting_columns(stat)
    header = "| " + " | ".join(interesting) + " |"
    sep = "|" + "|".join(["---"] * len(interesting)) + "|"
    lines = [header, sep]
    for row in stat.top_rows:
        cells = [_truncate_cell(row.get(col)) for col in interesting]
        lines.append("| " + " | ".join(cells) + " |")
    metric_label = stat.primary_metric or "default order"
    return f"**Top 10 by `{metric_label}`:**\n" + "\n".join(lines)


def _interesting_columns(stat: TableStat) -> list[str]:
    """Pick a compact column set for the Top-10 table."""
    pks = [c.name for c in stat.columns if c.primary_key]
    candidates: list[str] = []
    for col in pks:
        if col not in candidates:
            candidates.append(col)
    if stat.primary_metric and stat.primary_metric not in candidates:
        candidates.append(stat.primary_metric)

    # Add a few additional descriptive columns by name heuristic.
    name_hints = (
        "name",
        "canonical_name",
        "facility_name",
        "project_name",
        "campus_name",
        "ticker",
        "state",
        "state_code",
        "status",
        "stage",
        "plant_phase_stage",
        "metric_kind",
        "z_score",
        "title",
        "buyer_canonical",
        "seller_canonical",
        "company_canon",
        "match_tier",
        "issued_date",
        "filing_date",
        "published_date",
        "updated_at",
    )
    existing_cols = {c.name for c in stat.columns}
    for hint in name_hints:
        if hint in existing_cols and hint not in candidates:
            candidates.append(hint)
        if len(candidates) >= 7:
            break
    return candidates[:7] if candidates else [c.name for c in stat.columns[:5]]


def _render_fks(stat: TableStat) -> str:
    if not stat.fks:
        return ""
    parts = [f"{fk.column} -> {fk.target_table}.{fk.target_column}" for fk in stat.fks]
    return "**FKs:** " + "; ".join(parts)


def _render_table_block(stat: TableStat) -> str:
    parts = [f"### `{stat.name}` ({stat.row_count:,} rows)"]
    if stat.skipped_reason:
        parts.append(f"_skipped: {stat.skipped_reason}_")
    parts.append(_render_columns_table(stat.columns))
    fk_line = _render_fks(stat)
    if fk_line:
        parts.append(fk_line)
    top = _render_top_rows(stat)
    if top:
        parts.append(top)
    if stat.notes:
        parts.append("\n".join(f"_note: {n}_" for n in stat.notes))
    return "\n\n".join(parts)


def render_markdown(stats: list[TableStat], migration_rev: str) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = f"# Schema Digest \u2014 generated {generated_at} (migration {migration_rev})"

    # Sort tables by row_count DESC for the top-level listing.
    sorted_stats = sorted(stats, key=lambda s: (-s.row_count, s.name))

    body = [header, "", f"## Tables ({len(sorted_stats)})", ""]
    for stat in sorted_stats:
        body.append(_render_table_block(stat))
        body.append("")
    body.append(JOIN_PATHS_BLOCK)
    return "\n".join(body).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Entry point — atomic write
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


async def refresh() -> Path:
    """Top-level entrypoint. Best-effort — returns the target path even
    if rendering hit partial failures.
    """
    target = workspace_dir() / TARGET_FILENAME
    try:
        # Lazy-import to avoid a hard dep at module import time (the
        # alembic hook may import this module before settings are loaded).
        from agents.insights.db.session import get_readonly_engine

        engine = get_readonly_engine()
        stats, rev = await collect_table_stats(engine)
        markdown = render_markdown(stats, rev)
        _atomic_write(target, markdown)
        logger.info(
            "schema_doc.refresh.ok",
            extra={
                "tables": len(stats),
                "migration": rev,
                "path": str(target),
            },
        )
    except Exception as exc:
        logger.warning(
            "schema_doc.refresh.failed",
            extra={"error": str(exc), "path": str(target)},
        )
        # Best-effort partial: write a stub so downstream readers still
        # see something and the agent can detect the degraded state.
        try:
            stub = (
                f"# Schema Digest \u2014 refresh failed at "
                f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n\n"
                f"_error: {exc}_\n"
            )
            _atomic_write(target, stub)
        except Exception:  # pragma: no cover - defensive
            pass
    return target


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    asyncio.run(refresh())


if __name__ == "__main__":
    main()
