"""query_database tool — gated read-only SELECT against the strategic-insights DB.

Flow:
    1. Run the SQL through `validate_sql` (sqlglot AST gate).
    2. Open a connection on the readonly engine (`ai_agent` role).
    3. Wrap in a transaction with statement_timeout=5000ms (already set on
       the role; doubled here defensively per session).
    4. Execute and stream up to 10K rows.
    5. Compute the canonical row_hash so emit_chart can verify provenance.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from ..specs.skill_context import SkillContext
from ..db.session import get_readonly_engine
from .sql_gate import DEFAULT_ROW_LIMIT, SqlGateError, validate_sql

logger = logging.getLogger(__name__)


def _canonical_row_hash(rows: list[dict[str, Any]]) -> str:
    """Sha256 over canonicalised rows. Matches ChartSpec.compute_row_hash exactly."""
    canon = json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canon).hexdigest()


async def query_database(
    sql: str,
    ctx: SkillContext | None = None,
    *,
    max_rows: int = DEFAULT_ROW_LIMIT,
) -> dict[str, Any]:
    """Execute a read-only SELECT and return rows + provenance metadata.

    Returns a dict shaped like::

        {
            "rows": list[dict],
            "columns": list[str],
            "row_count": int,
            "executed_sql": str,         # the normalised, LIMIT-clamped SQL
            "fetched_at": str,           # ISO-8601 UTC
            "row_hash": str,             # sha256 over canonicalised rows
            "applied_limit": int,
            "notes": list[str],
        }

    On a gate failure raises `SqlGateError` (caller maps to a tool_error).
    """
    validated = validate_sql(sql, max_rows=max_rows)

    engine = get_readonly_engine()
    started = time.monotonic()
    rows: list[dict[str, Any]] = []
    columns: list[str] = []

    async with engine.connect() as conn:
        # Defensive timeout (the role itself also enforces 5s).
        await conn.execute(text("SET LOCAL statement_timeout = 5000"))
        result = await conn.execute(text(validated.normalized_sql))
        columns = list(result.keys())
        for record in result.mappings().all():
            rows.append(dict(record))
            if len(rows) >= max_rows:
                break

    latency_ms = int((time.monotonic() - started) * 1000)
    fetched_at = datetime.now(timezone.utc).isoformat()
    row_hash = _canonical_row_hash(rows)

    logger.info(
        "ai_insights.query_database.ok",
        extra={
            "row_count": len(rows),
            "applied_limit": validated.applied_limit,
            "latency_ms": latency_ms,
        },
    )

    return {
        "rows": rows,
        "columns": columns,
        "row_count": len(rows),
        "executed_sql": validated.normalized_sql,
        "fetched_at": fetched_at,
        "row_hash": row_hash,
        "applied_limit": validated.applied_limit,
        "notes": validated.notes,
    }


# Re-export for convenience.
__all__ = ["query_database", "SqlGateError"]
