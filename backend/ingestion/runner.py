"""
APScheduler integration for the ingestion pipeline.
Per section 1.3 of pipeline architecture.

Provides:
  - JOB_CONFIG dict mapping job IDs to adapter names + cron triggers
  - run_adapter_job() wraps each adapter call with ingestion_runs tracking
  - create_scheduler() builds and returns the configured AsyncIOScheduler
"""
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import async_session_factory
from db.models import IngestionRun

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Job configuration per section 1.3 cron table
# ---------------------------------------------------------------------------
# NOTE: transcript_ondemand and aterio_manual are manual-only (no cron).
#       satellite_weekly is deferred to Phase 2.

JOB_CONFIG: dict = {
    "edgar_daily": {
        "adapter": "edgar",
        "trigger": CronTrigger(hour=6, minute=0),
        "enabled": True,
    },
    "permits_state_daily": {
        "adapter": "permits_state",
        "trigger": CronTrigger(hour=7, minute=0),
        "enabled": True,
    },
    "permits_air_daily": {
        "adapter": "epa_echo",
        "trigger": CronTrigger(hour=8, minute=0),
        "enabled": True,
    },
    "coverage_refresh": {
        "adapter": "_coverage_refresh",
        "trigger": CronTrigger(minute=0),  # every hour on the hour
        "enabled": True,
    },
    "cache_cleanup": {
        "adapter": "_cache_cleanup",
        "trigger": CronTrigger(hour=0, minute=0),  # midnight UTC
        "enabled": True,
    },
    "stale_check": {
        "adapter": "_stale_check",
        "trigger": CronTrigger(hour="*/4", minute=0),  # every 4 hours
        "enabled": True,
    },
}

# Module-level reference so other code can inspect / pause the scheduler.
scheduler: AsyncIOScheduler | None = None


# ---------------------------------------------------------------------------
# Core job wrapper
# ---------------------------------------------------------------------------

async def run_adapter_job(adapter_name: str) -> None:
    """Execute an adapter and track it via an ingestion_runs row.

    Creates the row in *running* state before dispatching, then updates
    to *success* or *failure* when the adapter returns or raises.
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
            result = await _dispatch_adapter(adapter_name, session)
            run.status = "success"
            run.records_fetched = result.get("fetched", 0)
            run.records_stored = result.get("stored", 0)
            run.records_skipped = result.get("skipped", 0)
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
# Adapter dispatch
# ---------------------------------------------------------------------------

async def _dispatch_adapter(adapter_name: str, session: AsyncSession) -> dict:
    """Route an adapter name to its concrete implementation.

    Internal housekeeping adapters (prefixed with ``_``) are handled inline.
    External adapters are imported lazily to avoid circular imports at
    module load time.
    """
    if adapter_name == "edgar":
        from ingestion.edgar import EdgarAdapter
        adapter = EdgarAdapter()
        return await adapter.run(session)

    elif adapter_name == "permits_state":
        # Phase 1A only has VA; future phases add more states.
        from ingestion.permits_state.va_open_data import VaOpenDataAdapter
        adapter = VaOpenDataAdapter()
        return await adapter.run(session)

    elif adapter_name == "epa_echo":
        from ingestion.epa_echo import EpaEchoAdapter
        adapter = EpaEchoAdapter()
        return await adapter.run(session)

    elif adapter_name == "_coverage_refresh":
        return await _refresh_coverage(session)

    elif adapter_name == "_cache_cleanup":
        return await _cleanup_cache()

    elif adapter_name == "_stale_check":
        return await _check_stale(session)

    else:
        logger.warning("Unknown adapter requested: %s", adapter_name)
        return {"fetched": 0, "stored": 0}


# ---------------------------------------------------------------------------
# Internal housekeeping adapters
# ---------------------------------------------------------------------------

async def _refresh_coverage(session: AsyncSession) -> dict:
    """Safety-net coverage rollup.

    Individual adapters maintain their own coverage rows; this job exists
    so the scheduler has an hourly heartbeat we can monitor.
    """
    logger.info("coverage_refresh: no-op heartbeat")
    return {"fetched": 0, "stored": 0}


async def _cleanup_cache() -> dict:
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


async def _check_stale(session: AsyncSession) -> dict:
    """Log warnings for data_coverage rows that have gone past their SLA."""
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


# ---------------------------------------------------------------------------
# Scheduler factory
# ---------------------------------------------------------------------------

def create_scheduler() -> AsyncIOScheduler:
    """Create, configure, and return the APScheduler instance.

    Uses the in-memory job store (sufficient for a single-process deployment).
    The scheduler is stored in the module-level ``scheduler`` variable so
    that other parts of the app can inspect job state.
    """
    global scheduler
    scheduler = AsyncIOScheduler()

    for job_id, config in JOB_CONFIG.items():
        if not config["enabled"]:
            continue
        scheduler.add_job(
            run_adapter_job,
            trigger=config["trigger"],
            args=[config["adapter"]],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=3600,  # 1 hour grace for misfired jobs
        )

    return scheduler
