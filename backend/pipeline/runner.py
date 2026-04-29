"""
APScheduler integration for the ingestion pipeline.

Provides:
  - create_scheduler()   -- build and configure the AsyncIOScheduler
  - start_scheduler()    -- start the scheduler
  - shutdown_scheduler() -- gracefully shut it down

Each scheduled job creates an ingestion_runs audit row at start and
updates it with results or errors at completion.

The APScheduler job store is backed by the same Postgres database
(via the synchronous URL variant) so jobs survive process restarts.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger

from db.session import async_session_factory
from db.models import IngestionRun

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: derive a synchronous connection URL for the APScheduler job store
# ---------------------------------------------------------------------------

def _sync_database_url() -> str:
    """Convert the async database_url (asyncpg) to a sync one (psycopg2).

    APScheduler's SQLAlchemyJobStore requires a synchronous engine.
    """
    from config import settings
    url = settings.database_url
    # asyncpg -> psycopg2
    url = url.replace("postgresql+asyncpg", "postgresql+psycopg2", 1)
    # If it is a plain postgresql:// URL, leave it as-is (libpq default)
    return url


# ---------------------------------------------------------------------------
# Job configuration per section 1.3 cron table
# ---------------------------------------------------------------------------

JOB_CONFIG: dict[str, dict] = {
    "edgar_daily": {
        "adapter": "edgar",
        "trigger": CronTrigger(hour=6, minute=0),              # 0 6 * * *
        "phase": 1,
    },
    "permits_state_daily": {
        "adapter": "permits_state",
        "trigger": CronTrigger(hour=7, minute=0),                # 0 7 * * *
        "phase": 1,
    },
    "permits_air_daily": {
        "adapter": "epa_echo",
        "trigger": CronTrigger(hour=8, minute=0),                # 0 8 * * *
        "phase": 1,
    },
    # aterio_manual is API-trigger only -- not scheduled
    "coverage_refresh": {
        "adapter": "_coverage_refresh",
        "trigger": CronTrigger(minute=0),                       # 0 * * * *
        "phase": 1,
    },
    "cache_cleanup": {
        "adapter": "_cache_cleanup",
        "trigger": CronTrigger(hour=0, minute=0),               # 0 0 * * *
        "phase": 1,
    },
    "stale_check": {
        "adapter": "_stale_check",
        "trigger": CronTrigger(hour="*/4", minute=0),           # 0 */4 * * *
        "phase": 1,
    },
    "weekly_brief": {
        "adapter": "_weekly_brief",
        "trigger": CronTrigger(day_of_week="sun", hour=23, minute=0),  # 0 23 * * 0
        "phase": 1,
        "enabled": True,
    },
}


# ---------------------------------------------------------------------------
# Individual async job functions
# ---------------------------------------------------------------------------

async def run_edgar_job() -> None:
    """Scheduled job: fetch recent EDGAR filings."""
    await _run_adapter_job("edgar", _invoke_edgar)


async def run_permits_weekly_job() -> None:
    """Scheduled job: fetch state building-permit data."""
    await _run_adapter_job("permits_state", _invoke_permits_state)


async def run_epa_echo_job() -> None:
    """Scheduled job: fetch EPA ECHO air-permit data."""
    await _run_adapter_job("epa_echo", _invoke_epa_echo)


async def run_coverage_refresh_job() -> None:
    """Scheduled job: hourly coverage-rollup heartbeat."""
    await _run_adapter_job("_coverage_refresh", _invoke_coverage_refresh)


async def run_cache_cleanup_job() -> None:
    """Scheduled job: remove stale file-cache entries."""
    await _run_adapter_job("_cache_cleanup", _invoke_cache_cleanup)


async def run_stale_check_job() -> None:
    """Scheduled job: warn on data past its freshness SLA."""
    await _run_adapter_job("_stale_check", _invoke_stale_check)


async def run_weekly_brief_job() -> None:
    """Scheduled job: weekly LLM-generated intelligence brief."""
    await _run_adapter_job("_weekly_brief", _invoke_weekly_brief)


# ---------------------------------------------------------------------------
# Job wrapper -- creates and finalises the ingestion_runs audit row
# ---------------------------------------------------------------------------

async def _run_adapter_job(adapter_name: str, invoke_fn) -> None:
    """Generic wrapper that brackets any adapter invocation with an
    ingestion_runs audit row (status = running -> success | failure).
    """
    async with async_session_factory() as session:
        run = IngestionRun(
            adapter_name=adapter_name,
            adapter_version="1.0.0",
            started_at=datetime.utcnow(),
            status="running",
            trigger="scheduled",
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        try:
            result = await invoke_fn(session)
            run.status = "success"
            run.records_fetched = result.get("fetched", result.get("records_fetched", 0))
            run.records_stored = result.get("stored", result.get("records_stored", 0))
            run.records_skipped = result.get("skipped", result.get("records_skipped", 0))
            run.completed_at = datetime.utcnow()
        except Exception as exc:
            logger.error("adapter.%s.failed", adapter_name, exc_info=True)
            run.status = "failure"
            run.error_log = [
                {"error": str(exc), "timestamp": datetime.utcnow().isoformat()}
            ]
            run.completed_at = datetime.utcnow()

        await session.commit()


# ---------------------------------------------------------------------------
# Adapter invocation helpers (lazy imports to avoid circular deps)
# ---------------------------------------------------------------------------

async def _invoke_edgar(session) -> dict:
    from ingestion.edgar import EdgarAdapter
    adapter = EdgarAdapter()
    result = await adapter.run(session, days_back=1)
    await session.commit()
    return result


async def _invoke_permits_state(session) -> dict:
    # Phase 1A only has VA; future phases add more states
    try:
        from ingestion.permits_state.va_open_data import VaOpenDataAdapter
        adapter = VaOpenDataAdapter()
        return await adapter.run(session)
    except ImportError:
        logger.warning("permits_state adapter not yet implemented")
        return {"fetched": 0, "stored": 0}


async def _invoke_epa_echo(session) -> dict:
    from ingestion.epa_echo import EpaEchoAdapter
    adapter = EpaEchoAdapter()
    return await adapter.run(session)


async def _invoke_coverage_refresh(session) -> dict:
    """Safety-net coverage rollup heartbeat."""
    logger.info("coverage_refresh: heartbeat OK")
    return {"fetched": 0, "stored": 0}


async def _invoke_cache_cleanup(session) -> dict:
    """Remove file-based cache entries older than 48 hours."""
    from pathlib import Path

    cache_dir = Path(__file__).resolve().parent.parent / "data" / "cache"
    if not cache_dir.exists():
        return {"fetched": 0, "stored": 0}

    count = 0
    cutoff = datetime.utcnow().timestamp() - (48 * 3600)
    for f in cache_dir.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink()
            count += 1

    logger.info("cache_cleanup: removed %d stale file(s)", count)
    return {"fetched": 0, "stored": 0, "skipped": count}


async def _invoke_stale_check(session) -> dict:
    """Log warnings for data_coverage rows past their freshness SLA."""
    from sqlalchemy import select, text
    from db.models import DataCoverage

    result = await session.execute(
        select(DataCoverage).where(
            DataCoverage.last_ingested_at.isnot(None),
            text(
                "last_ingested_at < NOW() - (freshness_sla_hours || ' hours')::interval"
            ),
        )
    )
    stale = result.scalars().all()
    for row in stale:
        logger.warning(
            "stale_data: %s/%s/%s last_ingested=%s",
            row.pillar,
            row.state_code,
            row.source,
            row.last_ingested_at,
        )
    return {"fetched": len(stale), "stored": 0}


async def _invoke_weekly_brief(session) -> dict:
    """Generate the weekly LLM brief and persist it."""
    from agents.weekly_brief import generate_weekly_brief
    await generate_weekly_brief(session)
    return {"fetched": 1, "stored": 1}


# ---------------------------------------------------------------------------
# Map job IDs to their async functions
# ---------------------------------------------------------------------------

_JOB_FUNCTIONS: dict[str, callable] = {
    "edgar_daily": run_edgar_job,
    "permits_state_daily": run_permits_weekly_job,
    "permits_air_daily": run_epa_echo_job,
    "coverage_refresh": run_coverage_refresh_job,
    "cache_cleanup": run_cache_cleanup_job,
    "stale_check": run_stale_check_job,
    "weekly_brief": run_weekly_brief_job,
}


# ---------------------------------------------------------------------------
# Scheduler factory and lifecycle
# ---------------------------------------------------------------------------

def create_scheduler() -> AsyncIOScheduler:
    """Create, configure, and return the APScheduler instance.

    Uses a PostgreSQL-backed job store (synchronous URL) so that job
    metadata survives process restarts.  Falls back to the default
    in-memory store if the sync driver is unavailable.
    """
    jobstores = {}
    try:
        sync_url = _sync_database_url()
        jobstores["default"] = SQLAlchemyJobStore(url=sync_url)
        logger.info("APScheduler job store: PostgreSQL")
    except Exception as exc:
        # Fall back to in-memory if psycopg2 is not installed or DB is unreachable
        logger.warning(
            "Could not create SQLAlchemy job store, using in-memory: %s", exc
        )

    sched = AsyncIOScheduler(jobstores=jobstores if jobstores else {})

    for job_id, config in JOB_CONFIG.items():
        fn = _JOB_FUNCTIONS.get(job_id)
        if fn is None:
            logger.warning("No function registered for job '%s', skipping", job_id)
            continue
        sched.add_job(
            fn,
            trigger=config["trigger"],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=3600,  # 1-hour grace for misfired jobs
        )

    return sched


def start_scheduler(scheduler: AsyncIOScheduler) -> None:
    """Start the scheduler. Safe to call if already running."""
    if not scheduler.running:
        scheduler.start()
        logger.info(
            "APScheduler started with %d job(s).", len(scheduler.get_jobs())
        )


def shutdown_scheduler(scheduler: AsyncIOScheduler) -> None:
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down.")
