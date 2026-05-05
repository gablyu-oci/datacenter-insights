"""Async engine factories for the AI Insights backend.

Two engines run side-by-side:

1. WRITE_ENGINE (`get_write_engine`)   bound to the application role
   (env DATABASE_URL). Used for persisting ai_session/ai_insight/agent_*/
   skill_* rows.

2. READONLY_ENGINE (`get_readonly_engine`) bound to the `ai_agent` role
   (env AI_AGENT_DB_URL). Used exclusively by the `query_database` tool
   so even a SQL-gate bypass cannot mutate.

If `AI_AGENT_DB_URL` is unset, the readonly engine falls back to
`DATABASE_URL` with a warning logged. In production this falls back is
rejected at session start by the orchestrator (it asserts the agent role
is in use).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger(__name__)


_WRITE_ENGINE: Optional[AsyncEngine] = None
_READONLY_ENGINE: Optional[AsyncEngine] = None


def _resolve_write_dsn() -> str:
    # Prefer settings if available; fall back to env.
    try:
        from config import settings  # type: ignore

        return settings.database_url
    except Exception:
        pass
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL is unset and config.settings could not be loaded"
        )
    return dsn


def _resolve_readonly_dsn() -> str:
    dsn = os.environ.get("AI_AGENT_DB_URL")
    if dsn:
        return dsn
    # Fallback: same DSN as the write engine but log loudly. In tests we
    # accept this; in prod the orchestrator should refuse.
    fallback = _resolve_write_dsn()
    logger.warning(
        "ai_insights.readonly_engine.fallback_to_write_dsn "
        "(AI_AGENT_DB_URL is unset) — "
        "this is acceptable only in tests/dev"
    )
    return fallback


def get_write_engine() -> AsyncEngine:
    """Return (and lazily create) the write engine bound to DATABASE_URL."""
    global _WRITE_ENGINE
    if _WRITE_ENGINE is None:
        _WRITE_ENGINE = create_async_engine(
            _resolve_write_dsn(),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
    return _WRITE_ENGINE


def get_readonly_engine() -> AsyncEngine:
    """Return (and lazily create) the readonly engine bound to AI_AGENT_DB_URL.

    The connection-level statement_timeout is enforced by the role itself
    via `ALTER ROLE ai_agent SET statement_timeout = '5s'`, applied at
    role-provisioning time by `provision_ai_agent_role.sql`.
    """
    global _READONLY_ENGINE
    if _READONLY_ENGINE is None:
        _READONLY_ENGINE = create_async_engine(
            _resolve_readonly_dsn(),
            pool_pre_ping=True,
            # Tight pool to match `CONNECTION LIMIT 4` on the role.
            pool_size=2,
            max_overflow=2,
        )
    return _READONLY_ENGINE


async def close_engines() -> None:
    """Dispose both engines. Used in test teardown / app shutdown."""
    global _WRITE_ENGINE, _READONLY_ENGINE
    if _WRITE_ENGINE is not None:
        await _WRITE_ENGINE.dispose()
        _WRITE_ENGINE = None
    if _READONLY_ENGINE is not None:
        await _READONLY_ENGINE.dispose()
        _READONLY_ENGINE = None
