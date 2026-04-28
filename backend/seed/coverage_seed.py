"""
Initial coverage seed per section 3 of architecture design.

Seeds data_coverage with the declared status for every
(pillar, state_code, source) combination.  Uses ON CONFLICT DO NOTHING
so that adapter-written rows always take precedence over the seed baseline.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DataCoverage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reference sets
# ---------------------------------------------------------------------------

US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
]

PJM_STATES = {
    "VA", "MD", "DC", "NJ", "PA", "OH", "WV", "KY", "IL", "IN",
    "MI", "NC", "TN", "DE",
}

# States with standing records requests for generator_permits
GENERATOR_PERMIT_PENDING_STATES = {"VA", "IA", "AZ"}

# Building permits: mapping state -> (source, status)
BUILDING_PERMIT_SOURCES: dict[str, tuple[str, str]] = {
    "VA": ("va_open_data", "full"),
    "NY": ("ny_dec_socrata", "partial"),
    "WA": ("wa_ecology", "partial"),
    "CO": ("co_cdphe", "partial"),
    "OR": ("or_deq", "partial"),
    "TX": ("tceq", "partial"),
}


# ---------------------------------------------------------------------------
# Seed function
# ---------------------------------------------------------------------------

async def seed_coverage(db: AsyncSession) -> None:
    """Seed the initial coverage matrix into data_coverage.

    Idempotent: uses INSERT ... ON CONFLICT DO NOTHING so existing
    adapter-written rows are never overwritten by seed defaults.
    """
    rows: list[dict] = []

    # -- power_sites: all states full from Aterio CSV ----------------------
    for state in US_STATES:
        rows.append({
            "pillar": "power_sites",
            "state_code": state,
            "source": "aterio_csv",
            "coverage_status": "full",
            "record_count": 0,
            "freshness_sla_hours": 720,
            "notes": "Aterio national CSV snapshot covers all US states",
            "roadmap": "Phase-2 Aterio licensed weekly/monthly feed",
        })

    # -- sec_filings: federal (one row, scope = "US") ----------------------
    rows.append({
        "pillar": "sec_filings",
        "state_code": "US",
        "source": "edgar",
        "coverage_status": "full",
        "record_count": 0,
        "freshness_sla_hours": 24,
        "notes": "EDGAR REST API; 8-K/10-K/10-Q filings for energy and hyperscaler companies",
    })

    # -- air_emissions: federal baseline for every state -------------------
    for state in US_STATES:
        rows.append({
            "pillar": "air_emissions",
            "state_code": state,
            "source": "epa_echo",
            "coverage_status": "federal_baseline",
            "record_count": 0,
            "freshness_sla_hours": 168,
            "notes": "EPA ECHO national air-permit baseline; NAICS 518210 filter",
        })

    # -- building_permits --------------------------------------------------
    for state in US_STATES:
        if state in BUILDING_PERMIT_SOURCES:
            source, status = BUILDING_PERMIT_SOURCES[state]
            notes = None
            if state == "VA":
                notes = "Virginia open-data portal, full permit coverage"
            elif state == "NY":
                notes = "NY DEC via Socrata API"
            elif state == "WA":
                notes = "Washington Ecology permit database"
            elif state == "CO":
                notes = "Colorado CDPHE permit data"
            elif state == "OR":
                notes = "Oregon DEQ permit records"
            elif state == "TX":
                notes = "Texas TCEQ permit database"
            rows.append({
                "pillar": "building_permits",
                "state_code": state,
                "source": source,
                "coverage_status": status,
                "record_count": 0,
                "notes": notes,
            })
        else:
            rows.append({
                "pillar": "building_permits",
                "state_code": state,
                "source": "none",
                "coverage_status": "unavailable",
                "record_count": 0,
                "notes": "No building-permit data source available for this state",
                "roadmap": "Phase-2 Shovels.ai national permit API",
            })

    # -- generator_permits: federal baseline for every state ---------------
    for state in US_STATES:
        rows.append({
            "pillar": "generator_permits",
            "state_code": state,
            "source": "epa_echo",
            "coverage_status": "federal_baseline",
            "record_count": 0,
            "freshness_sla_hours": 168,
            "notes": "EPA ECHO national generator-permit baseline",
        })

    # -- generator_permits: TX state-level depth via TCEQ ------------------
    rows.append({
        "pillar": "generator_permits",
        "state_code": "TX",
        "source": "tceq",
        "coverage_status": "partial",
        "record_count": 0,
        "notes": "TCEQ state-level generator permit data for Texas",
    })

    # -- generator_permits: pending states (standing records requests) -----
    for state in GENERATOR_PERMIT_PENDING_STATES:
        rows.append({
            "pillar": "generator_permits",
            "state_code": state,
            "source": "records_request",
            "coverage_status": "pending",
            "record_count": 0,
            "notes": f"Standing records request submitted for {state}",
            "roadmap": "Awaiting state agency response; expected Phase-1B",
        })

    # -- iso_queues --------------------------------------------------------
    for state in US_STATES:
        if state in PJM_STATES:
            rows.append({
                "pillar": "iso_queues",
                "state_code": state,
                "source": "pjm_iso",
                "coverage_status": "partial",
                "record_count": 0,
                "notes": "PJM interconnection queue; covers this state's territory",
            })
        else:
            rows.append({
                "pillar": "iso_queues",
                "state_code": state,
                "source": "pending",
                "coverage_status": "pending",
                "record_count": 0,
                "roadmap": "ERCOT/MISO/SPP/CAISO/NYISO/ISO-NE to be added in Phase-2",
            })

    # -- earnings: federal (one row) ---------------------------------------
    rows.append({
        "pillar": "earnings",
        "state_code": "US",
        "source": "free_scraping",
        "coverage_status": "partial",
        "record_count": 0,
        "notes": "Best-effort IR-page scraping for earnings transcripts",
        "roadmap": "Phase-2 FMP or paid transcript API for full coverage",
    })

    # -- satellite: global (one row) ---------------------------------------
    rows.append({
        "pillar": "satellite",
        "state_code": "GLOBAL",
        "source": "sentinel2",
        "coverage_status": "full",
        "record_count": 0,
        "notes": "Sentinel-2 L2A, 10m resolution, 5-day revisit cycle",
    })

    # -- Upsert all rows with ON CONFLICT DO NOTHING ----------------------
    now = datetime.utcnow()
    count = 0
    for row in rows:
        row.setdefault("freshness_sla_hours", None)
        row.setdefault("notes", None)
        row.setdefault("roadmap", None)
        row["last_ingested_at"] = None
        row["created_at"] = now
        row["updated_at"] = now

        stmt = (
            pg_insert(DataCoverage)
            .values(**row)
            .on_conflict_do_nothing(
                constraint="uq_coverage_pillar_state_source",
            )
        )
        await db.execute(stmt)
        count += 1

    logger.info("seed_coverage: inserted up to %d coverage rows (conflicts skipped)", count)
