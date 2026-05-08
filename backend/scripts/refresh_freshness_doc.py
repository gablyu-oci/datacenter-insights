"""Generate `.openclaw/workspace/FRESHNESS.md` for the AI Insights v2 agent.

Phase A deliverable per `docs/ai_insights_v2_phase_a_architecture.md` §1.3.

For every table in ``FRESHNESS_TABLES`` compute:

* ``count(*)``
* ``max(<timestamp>)`` (``updated_at`` preferred, ``created_at`` / a
  per-table override otherwise)
* Δ7d  -- count of rows whose timestamp is within the last 7 days
* Δ24h -- count of rows whose timestamp is within the last 24 hours

A "Hot tables" rollup highlights any table with
``pct_change_7d > HOT_THRESHOLD`` (5% by default).

Pure SQL — no LLM calls. ~2KB output.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WORKSPACE_DIR_ENV = "OPENCLAW_WORKSPACE_DIR"
TARGET_FILENAME = "FRESHNESS.md"

# Subset of HIGH_SIGNAL_TABLES + a few high-traffic operational tables.
# Order is informational only; rendering sorts by delta_7d desc.
FRESHNESS_TABLES: list[str] = [
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
    "transcript_metrics",
    "brief_runs",
    "ingestion_runs",
]

# Override the timestamp column for tables where ``updated_at`` is missing
# or where a domain timestamp is more meaningful for "freshness".
TIMESTAMP_COLUMN: dict[str, str] = {
    "ingestion_runs": "started_at",
    "brief_runs": "generated_at",
    "data_coverage": "last_ingested_at",
    "edgar_extractions": "retrieved_at",
    "press_releases": "retrieved_at",
    "anomalies": "detected_at",
    "building_permits": "retrieved_at",
    "power_deal_links": "matched_at",
}

HOT_THRESHOLD = 0.05  # 5% growth over current row count in the last 7d
PER_QUERY_TIMEOUT_MS = 5000


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FreshnessRow:
    table: str
    rows: int
    max_ts: Optional[datetime]
    delta_7d: int
    delta_24h: int
    pct_change_7d: float
    note: Optional[str] = None  # populated when a column was missing etc.


# ---------------------------------------------------------------------------
# Path helpers (shared shape with refresh_schema_doc)
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def workspace_dir() -> Path:
    env_val = os.environ.get(WORKSPACE_DIR_ENV)
    if env_val:
        return Path(env_val).resolve()
    return (_project_root() / ".openclaw" / "workspace").resolve()


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------


async def _column_exists(conn, table: str, column: str) -> bool:
    sql = text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = current_schema() "
        "AND table_name = :tbl AND column_name = :col LIMIT 1"
    )
    result = await conn.execute(sql, {"tbl": table, "col": column})
    return result.first() is not None


async def _resolve_timestamp_column(conn, table: str) -> Optional[str]:
    override = TIMESTAMP_COLUMN.get(table)
    if override and await _column_exists(conn, table, override):
        return override
    if await _column_exists(conn, table, "updated_at"):
        return "updated_at"
    if await _column_exists(conn, table, "created_at"):
        return "created_at"
    if override:
        # explicit override but column missing
        return None
    return None


# ---------------------------------------------------------------------------
# Per-table query
# ---------------------------------------------------------------------------


async def _gather_one(conn, table: str) -> FreshnessRow:
    # statement_timeout is per-transaction; SET LOCAL is bound to the
    # active transaction. ``connect()`` runs autocommit, so we wrap each
    # table in a one-shot transaction.
    async with conn.begin():
        await conn.execute(
            text(f"SET LOCAL statement_timeout = {PER_QUERY_TIMEOUT_MS}")
        )
        try:
            count_result = await conn.execute(
                text(f'SELECT count(*) FROM "{table}"')
            )
            rows = int(count_result.scalar() or 0)
        except Exception as exc:
            return FreshnessRow(
                table=table,
                rows=0,
                max_ts=None,
                delta_7d=0,
                delta_24h=0,
                pct_change_7d=0.0,
                note=f"count_failed: {exc}",
            )

        ts_col = await _resolve_timestamp_column(conn, table)
        if ts_col is None:
            return FreshnessRow(
                table=table,
                rows=rows,
                max_ts=None,
                delta_7d=0,
                delta_24h=0,
                pct_change_7d=0.0,
                note="no_timestamp_column",
            )

        try:
            max_result = await conn.execute(
                text(f'SELECT max("{ts_col}") FROM "{table}"')
            )
            max_ts = max_result.scalar()
            d7_result = await conn.execute(
                text(
                    f'SELECT count(*) FROM "{table}" '
                    f'WHERE "{ts_col}" >= NOW() - INTERVAL \'7 days\''
                )
            )
            delta_7d = int(d7_result.scalar() or 0)
            d24_result = await conn.execute(
                text(
                    f'SELECT count(*) FROM "{table}" '
                    f'WHERE "{ts_col}" >= NOW() - INTERVAL \'24 hours\''
                )
            )
            delta_24h = int(d24_result.scalar() or 0)
        except Exception as exc:
            return FreshnessRow(
                table=table,
                rows=rows,
                max_ts=None,
                delta_7d=0,
                delta_24h=0,
                pct_change_7d=0.0,
                note=f"delta_query_failed: {exc}",
            )

    pct = (delta_7d / rows) if rows > 0 else 0.0
    return FreshnessRow(
        table=table,
        rows=rows,
        max_ts=max_ts if isinstance(max_ts, datetime) else None,
        delta_7d=delta_7d,
        delta_24h=delta_24h,
        pct_change_7d=pct,
    )


async def collect_freshness(engine: AsyncEngine) -> list[FreshnessRow]:
    out: list[FreshnessRow] = []
    async with engine.connect() as conn:
        for table in FRESHNESS_TABLES:
            try:
                row = await _gather_one(conn, table)
            except Exception as exc:
                row = FreshnessRow(
                    table=table,
                    rows=0,
                    max_ts=None,
                    delta_7d=0,
                    delta_24h=0,
                    pct_change_7d=0.0,
                    note=f"unexpected_error: {exc}",
                )
            out.append(row)
    return out


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _fmt_ts(ts: Optional[datetime]) -> str:
    if ts is None:
        return "\u2014"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.strftime("%Y-%m-%d %H:%MZ")


def _fmt_delta(n: int) -> str:
    if n == 0:
        return "0"
    return f"+{n:,}"


def render_markdown(rows: list[FreshnessRow], generated_at: datetime) -> str:
    sorted_rows = sorted(rows, key=lambda r: (-r.delta_7d, r.table))

    header = f"# Freshness \u2014 generated {generated_at.strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
    out = [header]
    out.append("| table | rows | max(updated_at) | \u0394 7d | \u0394 24h |")
    out.append("|---|---|---|---|---|")
    for r in sorted_rows:
        note = f" _{r.note}_" if r.note else ""
        out.append(
            f"| {r.table}{note} | {r.rows:,} | {_fmt_ts(r.max_ts)} "
            f"| {_fmt_delta(r.delta_7d)} | {_fmt_delta(r.delta_24h)} |"
        )

    hot = [r for r in sorted_rows if r.pct_change_7d > HOT_THRESHOLD]
    out.append("")
    out.append(f"## Hot tables (\u0394 7d > {int(HOT_THRESHOLD * 100)}%)")
    if hot:
        for r in hot:
            out.append(f"- {r.table} (+{r.pct_change_7d * 100:.1f}%)")
    else:
        out.append("_(no tables exceeded the threshold this window)_")
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


async def refresh() -> Path:
    """Best-effort top-level entrypoint. Logs failures, returns the
    target path even when partial.
    """
    target = workspace_dir() / TARGET_FILENAME
    try:
        from agents.insights.db.session import get_readonly_engine

        engine = get_readonly_engine()
        rows = await collect_freshness(engine)
        markdown = render_markdown(rows, datetime.now(timezone.utc))
        _atomic_write(target, markdown)
        logger.info(
            "freshness_doc.refresh.ok",
            extra={"tables": len(rows), "path": str(target)},
        )
    except Exception as exc:
        logger.warning(
            "freshness_doc.refresh.error",
            extra={"error": str(exc), "path": str(target)},
        )
        try:
            stub = (
                f"# Freshness \u2014 refresh failed at "
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
