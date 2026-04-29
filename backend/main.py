"""
Datacenter & Power Intelligence Platform -- FastAPI application.

Run from the backend/ directory:
    cd backend && python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings

# -- Router imports -----------------------------------------------------------
from routers.health import router as health_router
from routers.power import router as power_router
from routers.gpu import router as gpu_router
from routers.supply_chain import router as supply_chain_router
from routers.supply_chain import legacy_router as supply_chain_legacy_router
from routers.permits import router as permits_router
from routers.satellite import router as satellite_router
from routers.triangulation import router as triangulation_router
from routers.sources import router as sources_router
from routers.sites import router as sites_router
from routers.companies import router as companies_router
from routers.events import router as events_router
from routers.energy_projects import router as energy_projects_router
from routers.coverage import router as coverage_router
from routers.agent import router as agent_router
from routers.qa import router as qa_router
from routers.brief import router as brief_router
from routers.edgar_frames import router as edgar_frames_router
# oci_share has a wildcard {tab} path -- register last to avoid shadowing
from routers.oci_share import router as oci_share_router

logger = logging.getLogger("uvicorn.error")


# -- Lifespan ----------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: seed data on startup, manage scheduler."""

    # --- Startup: verify DB connectivity ---
    try:
        from db.session import engine
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection verified.")
    except Exception as exc:
        logger.warning("Database not reachable at startup: %s", exc)

    # --- Startup: seed companies + coverage (idempotent) ---
    try:
        from db.session import async_session_factory
        from seed.canonical_companies import seed_companies
        from seed.coverage_seed import seed_coverage

        async with async_session_factory() as session:
            await seed_companies(session)
            await seed_coverage(session)
            await session.commit()
        logger.info("Seed data loaded.")
    except Exception as exc:
        logger.warning("Seed failed: %s", exc)

    # --- Startup: APScheduler ---
    scheduler = None
    if os.environ.get("SCHEDULER_ENABLED", "1") == "1":
        try:
            from pipeline.runner import (
                create_scheduler,
                start_scheduler,
                shutdown_scheduler,
            )
            scheduler = create_scheduler()
            start_scheduler(scheduler)
        except Exception as exc:
            logger.warning("APScheduler failed to start: %s", exc)

    yield

    # --- Shutdown ---
    if scheduler is not None:
        try:
            from pipeline.runner import shutdown_scheduler
            shutdown_scheduler(scheduler)
        except Exception as exc:
            logger.warning("APScheduler shutdown error: %s", exc)


# -- App creation -------------------------------------------------------------

app = FastAPI(
    title="Datacenter & Power Intelligence Platform",
    version=settings.app_version,
    lifespan=lifespan,
)

# -- Middleware ----------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- Register routers ---------------------------------------------------------
# Order matters: more-specific prefixes first, wildcard-ish routers last.

app.include_router(health_router)
app.include_router(power_router)
app.include_router(gpu_router)
app.include_router(supply_chain_router)
app.include_router(supply_chain_legacy_router)
app.include_router(permits_router)
app.include_router(satellite_router)
app.include_router(triangulation_router)
app.include_router(sources_router)
app.include_router(sites_router)
app.include_router(companies_router)
app.include_router(events_router)
app.include_router(energy_projects_router)
app.include_router(coverage_router)
app.include_router(agent_router)
app.include_router(qa_router)
app.include_router(brief_router)
app.include_router(edgar_frames_router)
# oci_share must be last -- its /api/{tab}/oci-share pattern is broad
app.include_router(oci_share_router)
