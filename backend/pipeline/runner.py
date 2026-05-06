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
    "quarterly_filings_daily": {
        "adapter": "edgar_quarterly",
        "trigger": CronTrigger(hour=6, minute=15),               # 15 6 * * *
        "phase": 2,
    },
    "anomaly_detection_nightly": {
        "adapter": "_anomaly_detection",
        "trigger": CronTrigger(hour=2, minute=30),              # 30 2 * * *
        "phase": 2,
    },
    "permits_state_daily": {
        "adapter": "permits_state",
        "trigger": CronTrigger(hour=7, minute=0),                # 0 7 * * *
        "phase": 1,
    },
    # Karan round-2: daily county-level US building-permit ingestion
    # (Loudoun VA + Mesa AZ + Grant County WA placeholder + Tier-1
    # expansion). Each adapter is independent so one failure does not
    # block the others. Daily so new permits are picked up within ~24h.
    "county_permits_daily": {
        "adapter": "permits_county",
        "trigger": CronTrigger(hour=6, minute=30),               # 30 6 * * *
        "phase": 2,
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
    # Phase 3 (AI Insights automation): fires once per UTC day at 09:00,
    # one hour after the morning EPA ECHO ingest at 08:00. The headless
    # job drains InsightOrchestrator and writes IngestionRun audit. App-
    # level idempotency guard inside _invoke_insights_daily makes a
    # repeat fire on the same UTC day a no-op (D5).
    "insights_daily": {
        "adapter": "_insights_daily",
        "trigger": CronTrigger(hour=9, minute=0),                      # 0 9 * * *
        "phase": 2,
        "enabled": True,
    },
}


# ---------------------------------------------------------------------------
# Individual async job functions
# ---------------------------------------------------------------------------

async def run_edgar_job() -> None:
    """Scheduled job: fetch recent EDGAR filings."""
    await _run_adapter_job("edgar", _invoke_edgar)


async def run_edgar_quarterly_job() -> None:
    """Scheduled job: fetch recent 10-K + 10-Q filings (chunked, multi-form)."""
    await _run_adapter_job("edgar_quarterly", _invoke_edgar_quarterly)


async def run_anomaly_detection_job() -> None:
    """Scheduled job: detect WoW anomalies (±2σ) and persist into anomalies table."""
    await _run_adapter_job("_anomaly_detection", _invoke_anomaly_detection)


async def run_permits_weekly_job() -> None:
    """Scheduled job: fetch state building-permit data."""
    await _run_adapter_job("permits_state", _invoke_permits_state)


async def run_county_permits_weekly_job() -> None:
    """Scheduled job: fetch county-level US building permits.

    Runs Loudoun + Mesa + Grant County adapters sequentially (each is
    independent). Failures in one source must not abort the others, so
    each call is wrapped in its own try/except and contributes to a
    summary log line.
    """
    await _run_adapter_job("permits_county", _invoke_permits_county)


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


async def run_insights_daily_job() -> None:
    """Scheduled job: generate today's AI Insights set headlessly.

    Wraps _invoke_insights_daily in the standard IngestionRun audit
    bracket. Idempotency, retry, and wall-clock guard live inside the
    invoke helper, NOT here, so a repeat-fire on the same UTC day is a
    successful no-op rather than a failure.
    """
    await _run_adapter_job("_insights_daily", _invoke_insights_daily)


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


async def _invoke_edgar_quarterly(session) -> dict:
    """Fetch 10-K + 10-Q filings across all TRACKED_FILERS, chunked, with merge."""
    from agents.edgar_extractor import run_llm_extraction_quarterly
    result = await run_llm_extraction_quarterly(session, days_back=14)
    await session.commit()
    return {
        "fetched": result.get("fetched", 0),
        "stored": result.get("stored", 0),
        "skipped": result.get("skipped", 0),
    }


async def _invoke_anomaly_detection(session) -> dict:
    """Run trailing-12-week ±2σ anomaly detector."""
    from agents.anomaly_detector import detect_anomalies
    result = await detect_anomalies(session)
    await session.commit()
    return {
        "fetched": result.get("metrics_evaluated", 0),
        "stored": result.get("anomalies_recorded", 0),
        "skipped": 0,
    }


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


async def _invoke_permits_county(session) -> dict:
    """Run all county-level building-permit adapters sequentially.

    Aggregates per-source counts into a single summary so the
    ingestion_runs row reflects the full sweep. Adapters that raise
    are logged but do not abort the others.
    """
    from ingestion.permits_county import loudoun, mesa, grantwa

    summary: dict = {"fetched": 0, "stored": 0, "skipped": 0, "by_source": []}
    for adapter_mod in (loudoun, mesa, grantwa):
        name = getattr(adapter_mod, "SOURCE_ID", adapter_mod.__name__)
        try:
            result = await adapter_mod.fetch_and_store(session)
        except Exception as exc:
            logger.error("permits_county.%s.failed: %s", name, exc, exc_info=True)
            summary["by_source"].append({"source": name, "error": str(exc)})
            continue
        summary["fetched"] += result.get("fetched", 0)
        summary["stored"] += result.get("stored", 0)
        summary["skipped"] += result.get("skipped_non_datacenter", 0)
        summary["by_source"].append(result)
    logger.info(
        "permits_county.summary fetched=%s stored=%s skipped=%s",
        summary["fetched"], summary["stored"], summary["skipped"],
    )
    await session.commit()
    return summary


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
# Phase 3: insights_daily — daily AI Insights cron
# ---------------------------------------------------------------------------

# Per-attempt outer wall-clock guard (D11). Belt-and-suspenders against the
# orchestrator's internal V1_WALL_CLOCK_S=480 — if the iterator hangs on a
# stuck embed call before the internal check fires, this terminates cleanly.
INSIGHTS_DAILY_TIMEOUT_S = 600

# Retry policy (user override of arch §10 D13). Up to 2 retries (3 total
# attempts) with a 60-second linear sleep between attempts. After the third
# consecutive failure: AISession.status='failed', exception re-raised so
# the APScheduler EVENT_JOB_ERROR listener fires.
INSIGHTS_DAILY_MAX_RETRIES = 2
INSIGHTS_DAILY_RETRY_SLEEP_S = 60


async def _invoke_insights_daily(session) -> dict:
    """Drive an OpenClaw agentic-synthesis turn for today's AI Insights.

    Phase 3 retarget (PRD/ARCH §14, FR-3.1..FR-3.6): replaces the
    previous `InsightOrchestrator.run_session` drain with a server-side
    `build_factpack` + `run_agentic_synthesis` against the OpenClaw
    gateway. The legacy orchestrator is intentionally retained for the
    manual UI path (Phase 5 cleanup).

    Behaviour:
      1. Idempotency guard: if a `created_by='scheduler'` AISession
         already exists today with status in (running, complete), no-op.
      2. Build the FactPack server-side (so the agent sees a stable
         input regardless of MCP availability) and pre-create the
         AISession row in `status='running'`. Commit so a same-day
         retry hits the idempotency guard.
      3. Drive `run_agentic_synthesis` under a 600s wall-clock guard.
         The agent persists insight rows + finalizes the AISession via
         MCP tools (`persist_insight`, `finalize_session`). This driver
         only handles failure-path force-finalisation.
      4. Up to 2 retries with 60s linear backoff. Final failure
         re-raises so APScheduler's EVENT_JOB_ERROR listener fires.

    Returns the standard runner summary dict
    ({"fetched": N, "stored": M, ...}). On idempotency-skip we return
    `skipped=1` so the audit row reflects the no-op truthfully.
    """
    import asyncio
    import logging
    import time
    import traceback
    import uuid as _uuid
    from datetime import date, datetime

    from sqlalchemy import select, update

    from agents.insights.agentic_synthesis import (
        SynthesisRunError,
        run_agentic_synthesis,
    )
    from agents.insights.db.models import AISession
    from agents.insights.hypothesizer import build_factpack

    log = logging.getLogger(__name__)
    today = date.today()

    # ---------- 1) Idempotency guard ----------
    existing = await session.execute(
        select(AISession.id).where(
            AISession.created_by == "scheduler",
            AISession.cron_run_date == today,
            AISession.status.in_(("running", "complete")),
        )
    )
    if existing.first() is not None:
        log.info(
            "insights_daily.idempotency_skip",
            extra={"cron_run_date": today.isoformat()},
        )
        return {
            "fetched": 0,
            "stored": 0,
            "skipped": 1,
            "reason": "idempotency_guard",
        }

    # ---------- 2) Run with retry ----------
    last_exc: BaseException | None = None
    sid: _uuid.UUID | None = None
    insights_emitted = 0
    fact_pack_rows = 0
    degraded_final = False

    for attempt in range(INSIGHTS_DAILY_MAX_RETRIES + 1):
        sid = _uuid.uuid4()
        attempt_started = time.monotonic()

        # 2a. Build the FactPack server-side. Done per attempt so a
        # transient DB blip on the first attempt is recoverable.
        try:
            fact_pack = await build_factpack(session)
            fact_pack_rows = (
                fact_pack.total_rows()
                if hasattr(fact_pack, "total_rows")
                else sum(len(s.rows or []) for s in getattr(fact_pack, "sections", []))
            )
        except Exception as exc:
            last_exc = exc
            log.warning(
                "insights_daily.factpack_build_failed",
                extra={
                    "attempt": attempt + 1,
                    "session_id": str(sid),
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            if attempt < INSIGHTS_DAILY_MAX_RETRIES:
                await asyncio.sleep(INSIGHTS_DAILY_RETRY_SLEEP_S)
                continue
            raise

        # 2b. Pre-create the AISession row so the idempotency guard
        # catches a same-day retry once we've started this attempt.
        ai_session = AISession(
            id=sid,
            status="running",
            started_at=datetime.utcnow(),
            max_insights=5,
            created_by="scheduler",
            cron_run_date=today,
            focus="daily-cron",
        )
        session.add(ai_session)
        try:
            await session.commit()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "insights_daily.session_precreate_failed",
                extra={"err": str(exc), "session_id": str(sid)},
            )
            try:
                await session.rollback()
            except Exception:
                pass

        async def _scheduler_sse_log(event):
            # Cron path has no UI consumer; we just log the event type
            # for ops visibility (matching the manual flow's debug log).
            try:
                ev_type = getattr(event, "type", None) or (
                    event.get("type") if isinstance(event, dict) else "?"
                )
            except Exception:
                ev_type = "?"
            log.info("insights_daily.sse type=%s", ev_type)

        # 2c. Drive the agentic synthesis under the outer wall-clock.
        try:
            result = await asyncio.wait_for(
                run_agentic_synthesis(
                    session_id=sid,
                    fact_pack=fact_pack,
                    max_insights=5,
                    db=session,
                    sse_emit=_scheduler_sse_log,
                    cron_run_date=today,
                    mode="scheduled",
                ),
                timeout=INSIGHTS_DAILY_TIMEOUT_S,
            )
            insights_emitted = int(getattr(result, "insights_count", 0) or 0)
            degraded_final = bool(getattr(result, "degraded", False))
            wall_seconds = round(time.monotonic() - attempt_started, 3)

            # Read back token_estimate set by the agent's finalize_session call.
            token_estimate: int | None = None
            try:
                refreshed = (
                    await session.execute(
                        select(AISession.token_estimate).where(AISession.id == sid)
                    )
                ).first()
                if refreshed is not None:
                    token_estimate = refreshed[0]
            except Exception:  # pragma: no cover - defensive
                pass

            last_exc = None
            log.info(
                "insights_daily.success",
                extra={
                    "attempt": attempt + 1,
                    "session_id": str(sid),
                    "cron_run_date": today.isoformat(),
                    "factpack_rows": fact_pack_rows,
                    "total_insights": insights_emitted,
                    "degraded": degraded_final,
                    "wall_clock_seconds": wall_seconds,
                    "token_estimate": token_estimate,
                    "reason": getattr(result, "reason", None),
                },
            )
            break  # success — leave retry loop

        except asyncio.TimeoutError as exc:
            last_exc = exc
            log.warning(
                "insights_daily.attempt_wall_timeout",
                extra={
                    "attempt": attempt + 1,
                    "max_attempts": INSIGHTS_DAILY_MAX_RETRIES + 1,
                    "session_id": str(sid),
                },
            )
            # Force-finalize to 'degraded' since run_agentic_synthesis
            # was cancelled before its own finalize hook could fire.
            await _force_finalize_status(session, sid, status="degraded")

            if attempt < INSIGHTS_DAILY_MAX_RETRIES:
                await asyncio.sleep(INSIGHTS_DAILY_RETRY_SLEEP_S)
                continue
            log.error(
                "insights_daily.exhausted_retries_timeout",
                extra={
                    "session_id": str(sid),
                    "attempts": INSIGHTS_DAILY_MAX_RETRIES + 1,
                },
            )
            raise

        except SynthesisRunError as exc:
            last_exc = exc
            log.warning(
                "insights_daily.attempt_synthesis_error",
                extra={
                    "attempt": attempt + 1,
                    "max_attempts": INSIGHTS_DAILY_MAX_RETRIES + 1,
                    "session_id": str(sid),
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            await _force_finalize_status(session, sid, status="failed")

            if attempt < INSIGHTS_DAILY_MAX_RETRIES:
                await asyncio.sleep(INSIGHTS_DAILY_RETRY_SLEEP_S)
                continue
            log.error(
                "insights_daily.exhausted_retries_synthesis_error",
                extra={
                    "session_id": str(sid),
                    "attempts": INSIGHTS_DAILY_MAX_RETRIES + 1,
                    "final_error": str(exc),
                },
            )
            raise

        except Exception as exc:
            last_exc = exc
            log.warning(
                "insights_daily.attempt_failed",
                extra={
                    "attempt": attempt + 1,
                    "max_attempts": INSIGHTS_DAILY_MAX_RETRIES + 1,
                    "session_id": str(sid),
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            await _force_finalize_status(session, sid, status="failed")

            if attempt < INSIGHTS_DAILY_MAX_RETRIES:
                await asyncio.sleep(INSIGHTS_DAILY_RETRY_SLEEP_S)
                continue
            log.error(
                "insights_daily.exhausted_retries",
                extra={
                    "session_id": str(sid),
                    "attempts": INSIGHTS_DAILY_MAX_RETRIES + 1,
                    "final_error": str(exc),
                },
            )
            raise

    if last_exc is not None:  # pragma: no cover - defensive
        raise last_exc

    return {
        "fetched": fact_pack_rows,
        "stored": insights_emitted,
        "skipped": 0,
        "session_id": str(sid) if sid else None,
        "degraded": degraded_final,
    }


async def _force_finalize_status(session, session_id, *, status: str) -> None:
    """Best-effort UPDATE that flips an AISession row to a terminal
    status when run_agentic_synthesis was cut off before its own
    finalize_session hook could fire.

    Only flips rows still in 'running' so we never clobber a row that
    the agent (or the synthesis driver's own degraded-finalize) already
    wrote.
    """
    from sqlalchemy import update
    from datetime import datetime
    from agents.insights.db.models import AISession

    try:
        await session.execute(
            update(AISession)
            .where(
                AISession.id == session_id,
                AISession.status == "running",
            )
            .values(status=status, finished_at=datetime.utcnow())
        )
        await session.commit()
    except Exception as flip_exc:  # pragma: no cover - defensive
        logger.warning(
            "insights_daily.force_finalize_failed",
            extra={
                "err": str(flip_exc),
                "session_id": str(session_id),
                "target_status": status,
            },
        )
        try:
            await session.rollback()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Map job IDs to their async functions
# ---------------------------------------------------------------------------

_JOB_FUNCTIONS: dict[str, callable] = {
    "edgar_daily": run_edgar_job,
    # Renamed weekly -> daily per Karan round-2 AC6.
    "quarterly_filings_daily": run_edgar_quarterly_job,
    "anomaly_detection_nightly": run_anomaly_detection_job,
    "permits_state_daily": run_permits_weekly_job,
    "county_permits_daily": run_county_permits_weekly_job,
    "permits_air_daily": run_epa_echo_job,
    "coverage_refresh": run_coverage_refresh_job,
    "cache_cleanup": run_cache_cleanup_job,
    "stale_check": run_stale_check_job,
    "weekly_brief": run_weekly_brief_job,
    "insights_daily": run_insights_daily_job,
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
        # Weekly jobs need a far longer grace window: if the backend was
        # down on a Sunday morning, a 1-hour grace would silently drop the
        # run forever (this is the AC7 weekly_brief bug). 24h grace +
        # coalesce=True means we still fire once at the next opportunity.
        # Daily jobs are fine with 1h.
        if job_id == "weekly_brief":
            grace = 86400
            coalesce = True
        else:
            grace = 3600
            coalesce = True
        sched.add_job(
            fn,
            trigger=config["trigger"],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=grace,
            coalesce=coalesce,
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
