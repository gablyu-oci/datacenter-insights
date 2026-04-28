"""
DATA INGESTION LAYER -- Architecture Specification
====================================================
Datacenter & Power Intelligence Platform (OCI)
Author: System Architect | Date: 2026-04-28

This file contains executable Python interface definitions, schema models,
and configuration structures for the data ingestion layer. It is intended
to be split into separate modules during implementation.
"""

# =============================================================================
# 1. ADAPTER INTERFACE DESIGN
# =============================================================================

from __future__ import annotations

import abc
import enum
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field, HttpUrl


# ---------------------------------------------------------------------------
# 1a. Core enums
# ---------------------------------------------------------------------------

class Pillar(str, enum.Enum):
    POWER = "power"
    GPU_SUPPLY = "gpu_supply"
    NICS_OPTICS = "nics_optics"
    TSMC = "tsmc"
    PERMITS = "permits"
    SATELLITE = "satellite"
    EARNINGS = "earnings"


class SourceTier(str, enum.Enum):
    FREE = "free"           # EDGAR, county portals, Sentinel-2
    FREEMIUM = "freemium"   # limited free tier (Shovels trial, etc.)
    PAID = "paid"           # Planet Labs, SemiAnalysis, Maxar


class UpdateCadence(str, enum.Enum):
    REALTIME = "realtime"       # sub-minute (not used in v1)
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    QUARTERLY = "quarterly"
    EVENT_DRIVEN = "event_driven"


# ---------------------------------------------------------------------------
# 1b. Source lineage -- attached to every ingested record
# ---------------------------------------------------------------------------

class SourceLineage(BaseModel):
    """Every metric in the platform carries this metadata."""
    source_id: str                          # e.g. "edgar-8k", "shovels-permits"
    source_url: HttpUrl                     # clickable primary source
    retrieved_at: datetime                  # UTC timestamp of fetch
    parser_version: str                     # semver of parser that produced this record
    confidence: float = Field(ge=0.0, le=1.0)  # parsing certainty, NOT mocked
    raw_hash: str                           # SHA-256 of raw response (for dedup)
    is_cached: bool = False                 # True if served from cache, not live fetch
    cache_age_seconds: Optional[int] = None


# ---------------------------------------------------------------------------
# 1c. Normalized record -- output of every adapter
# ---------------------------------------------------------------------------

T = TypeVar("T")  # adapter-specific payload


class IngestedRecord(BaseModel, Generic[T]):
    """Universal wrapper around any ingested data point."""
    record_id: str                          # deterministic hash of (source_id + key fields)
    pillar: Pillar
    company: Optional[str] = None           # normalized: "Microsoft", "Amazon", etc.
    geography: Optional[str] = None         # normalized: "Loudoun County, VA"
    timestamp: datetime                     # event time (filing date, permit date, etc.)
    payload: T                              # adapter-specific structured data
    lineage: SourceLineage


# ---------------------------------------------------------------------------
# 1d. Abstract adapter interface
# ---------------------------------------------------------------------------

class DataSourceAdapter(abc.ABC):
    """
    Contract that every data source must implement.

    Lifecycle:  fetch() -> normalize() -> validate() -> [store]

    Implementors: EdgarAdapter, ShovelsPermitAdapter, SentinelSatelliteAdapter,
                  PlanetLabsAdapter, EarningsTranscriptAdapter, etc.
    """

    @abc.abstractmethod
    def get_metadata(self) -> SourceMetadata:
        """
        Return static metadata about this source.
        Called once at registration time and cached by the registry.
        """
        ...

    @abc.abstractmethod
    async def fetch(
        self,
        *,
        since: datetime | None = None,
        geography: str | None = None,
        company: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[RawRecord]:
        """
        Pull raw data from the upstream source.

        Args:
            since:     Only fetch records newer than this timestamp (incremental).
            geography: Optional geographic filter (e.g. "Loudoun County, VA").
            company:   Optional company filter (e.g. "Microsoft").
            params:    Adapter-specific parameters (CIK, coordinates, etc.).

        Returns:
            List of RawRecord -- unprocessed but timestamped and hashed.

        Raises:
            RateLimitError:   If upstream rate limit is hit.
            SourceUnavailable: If upstream is down.
        """
        ...

    @abc.abstractmethod
    async def normalize(self, raw_records: list[RawRecord]) -> list[IngestedRecord]:
        """
        Transform raw upstream data into IngestedRecord with SourceLineage.

        This is where:
        - Company names are canonicalized
        - Geographies are standardized
        - MW/GW are converted to a common unit
        - Confidence scores are computed from parsing certainty
        """
        ...

    @abc.abstractmethod
    async def validate(self, records: list[IngestedRecord]) -> list[IngestedRecord]:
        """
        Post-normalization validation.

        - Check required fields are populated
        - Ensure confidence >= minimum threshold (drop or flag otherwise)
        - Cross-reference against known entities
        - Deduplicate against already-stored records

        Returns only records that pass validation.
        """
        ...

    # --- Convenience (non-abstract) ---

    async def ingest(
        self,
        *,
        since: datetime | None = None,
        geography: str | None = None,
        company: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[IngestedRecord]:
        """Full pipeline: fetch -> normalize -> validate."""
        raw = await self.fetch(since=since, geography=geography, company=company, params=params)
        normalized = await self.normalize(raw)
        validated = await self.validate(normalized)
        return validated


# ---------------------------------------------------------------------------
# 1e. Supporting types
# ---------------------------------------------------------------------------

class SourceMetadata(BaseModel):
    """Static descriptor for a registered data source."""
    source_id: str                          # unique key, e.g. "edgar-8k"
    name: str                               # human-readable, e.g. "SEC EDGAR 8-K Filings"
    pillar: Pillar
    tier: SourceTier
    cadence: UpdateCadence
    rate_limit: Optional[RateLimit] = None
    freshness_target: timedelta             # e.g. timedelta(hours=24) for filings
    base_url: HttpUrl
    description: str = ""
    fallback_source_id: Optional[str] = None  # free fallback if this source fails


class RateLimit(BaseModel):
    requests_per_second: float
    burst: int = 1
    retry_after_seconds: float = 1.0


class RawRecord(BaseModel):
    """Unprocessed record straight from the upstream API/scraper."""
    source_id: str
    fetched_at: datetime
    raw_content: Any              # JSON dict, HTML string, binary ref, etc.
    raw_hash: str                 # SHA-256 for dedup
    url: HttpUrl                  # the exact URL fetched

    @staticmethod
    def compute_hash(content: bytes | str) -> str:
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()


# =============================================================================
# 2. SOURCE REGISTRY PATTERN
# =============================================================================

class SourceRegistry:
    """
    Configuration-driven registry. Adapters register at startup; the scheduler
    and API layer look up adapters by pillar or source_id.

    Swapping sources (e.g. Sentinel-2 -> Planet Labs) requires only a config
    change -- no code changes in consumers.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, DataSourceAdapter] = {}
        self._metadata: dict[str, SourceMetadata] = {}
        self._pillar_index: dict[Pillar, list[str]] = {}
        self._active_source: dict[Pillar, str] = {}  # currently active per pillar

    def register(self, adapter: DataSourceAdapter) -> None:
        meta = adapter.get_metadata()
        self._adapters[meta.source_id] = adapter
        self._metadata[meta.source_id] = meta
        self._pillar_index.setdefault(meta.pillar, []).append(meta.source_id)

    def set_active(self, pillar: Pillar, source_id: str) -> None:
        """Switch the active source for a pillar (config-driven hot-swap)."""
        if source_id not in self._adapters:
            raise KeyError(f"Source {source_id!r} not registered")
        self._active_source[pillar] = source_id

    def get_adapter(self, source_id: str) -> DataSourceAdapter:
        return self._adapters[source_id]

    def get_active_adapter(self, pillar: Pillar) -> DataSourceAdapter:
        source_id = self._active_source.get(pillar)
        if not source_id:
            # Fallback: pick the first free source for this pillar
            for sid in self._pillar_index.get(pillar, []):
                if self._metadata[sid].tier == SourceTier.FREE:
                    return self._adapters[sid]
            raise KeyError(f"No active or free source for pillar {pillar}")
        return self._adapters[source_id]

    def get_all_for_pillar(self, pillar: Pillar) -> list[DataSourceAdapter]:
        return [self._adapters[sid] for sid in self._pillar_index.get(pillar, [])]

    def list_sources(self) -> list[SourceMetadata]:
        return list(self._metadata.values())


# --- YAML-driven config (loaded at startup) ---
# File: config/sources.yaml
#
# sources:
#   edgar-8k:
#     adapter_class: "ingestion.adapters.edgar.Edgar8KAdapter"
#     active: true
#     pillar: power
#     tier: free
#     cadence: event_driven
#     freshness_target_hours: 24
#     rate_limit:
#       requests_per_second: 10
#       burst: 10
#     params:
#       user_agent: "Datacenter Intelligence Platform research@oracle.com"
#       energy_ciks: [...]
#
#   shovels-permits:
#     adapter_class: "ingestion.adapters.shovels.ShovelsPermitAdapter"
#     active: true
#     pillar: permits
#     tier: paid
#     cadence: weekly
#     freshness_target_hours: 168  # 7 days
#     fallback: "county-permits-scraper"
#     params:
#       api_key_env: "SHOVELS_API_KEY"
#       counties: ["51107", "51153"]  # Loudoun, Prince William FIPS
#
#   sentinel-2:
#     adapter_class: "ingestion.adapters.satellite.Sentinel2Adapter"
#     active: true
#     pillar: satellite
#     tier: free
#     cadence: weekly
#     freshness_target_hours: 336  # 14 days
#     fallback: null
#     params:
#       max_cloud_cover_pct: 20
#
#   planet-labs:
#     adapter_class: "ingestion.adapters.satellite.PlanetLabsAdapter"
#     active: false   # activate when budget approved
#     pillar: satellite
#     tier: paid
#     cadence: daily
#     freshness_target_hours: 72
#     params:
#       api_key_env: "PLANET_API_KEY"
#       resolution: "3m"


# =============================================================================
# 3. CADENCE MANAGEMENT -- SCHEDULER ARCHITECTURE
# =============================================================================

# We use a lightweight async scheduler built on APScheduler 4.x or a simple
# asyncio task loop. Each source's cadence is declared in config; the scheduler
# translates cadence into cron expressions or interval triggers.

CADENCE_TO_CRON = {
    UpdateCadence.HOURLY:        "0 * * * *",
    UpdateCadence.DAILY:         "0 6 * * *",       # 6 AM UTC
    UpdateCadence.WEEKLY:        "0 6 * * 1",       # Monday 6 AM UTC
    UpdateCadence.QUARTERLY:     "0 6 15 1,4,7,10 *",  # 15th of quarter-start months
    UpdateCadence.EVENT_DRIVEN:  None,               # triggered by webhook / EDGAR RSS
}


@dataclass
class IngestionJob:
    source_id: str
    cadence: UpdateCadence
    last_run: Optional[datetime] = None
    last_status: str = "pending"
    next_run: Optional[datetime] = None
    retries: int = 0
    max_retries: int = 3


class IngestionScheduler:
    """
    Manages periodic and event-driven ingestion jobs.

    Architecture:
    - Periodic sources (permits, satellite) run on cron schedules
    - Event-driven sources (EDGAR filings, earnings) are triggered by:
        a) EDGAR ATOM RSS feed polling (every 15 min)
        b) Earnings calendar webhook / daily check
    - All jobs go through: fetch -> normalize -> validate -> store
    - Failed jobs retry with exponential backoff (1m, 5m, 30m)
    """

    def __init__(self, registry: SourceRegistry) -> None:
        self.registry = registry
        self.jobs: dict[str, IngestionJob] = {}

    def schedule_all(self) -> None:
        for meta in self.registry.list_sources():
            self.jobs[meta.source_id] = IngestionJob(
                source_id=meta.source_id,
                cadence=meta.cadence,
            )

    async def run_job(self, source_id: str, **kwargs) -> dict:
        adapter = self.registry.get_adapter(source_id)
        job = self.jobs[source_id]
        try:
            records = await adapter.ingest(since=job.last_run, **kwargs)
            job.last_run = datetime.utcnow()
            job.last_status = "success"
            job.retries = 0
            return {"source_id": source_id, "records_ingested": len(records), "status": "success"}
        except Exception as e:
            job.retries += 1
            job.last_status = f"error: {e}"
            raise


# =============================================================================
# 4. DATA FRESHNESS & CACHING
# =============================================================================

class IngestionCache:
    """
    Two-tier cache: in-memory (hot) + on-disk JSON (warm).

    Policies:
    - EDGAR responses: TTL = 12h, respects 10 req/s via async semaphore
    - Satellite imagery metadata: TTL = 24h (imagery itself stored in object storage)
    - Permit data: TTL = 7 days (weekly refresh)
    - Earnings transcripts: TTL = 90 days (quarterly, immutable once published)
    - Deduplication: raw_hash checked before storing; identical content skipped

    Rate limit enforcement:
    - asyncio.Semaphore(10) for EDGAR (10 req/s)
    - asyncio.Semaphore(5) for satellite APIs
    - Token bucket for bursty sources
    """

    def __init__(self, cache_dir: str = "./data/cache") -> None:
        self.cache_dir = cache_dir
        self._memory: dict[str, tuple[datetime, Any]] = {}
        self._seen_hashes: set[str] = set()

    async def get(self, key: str, max_age: timedelta) -> Optional[Any]:
        """Return cached value if within max_age, else None."""
        if key in self._memory:
            ts, value = self._memory[key]
            if datetime.utcnow() - ts < max_age:
                return value
        # Check disk cache ...
        return None

    async def put(self, key: str, value: Any, raw_hash: str) -> bool:
        """Store value. Returns False if raw_hash already seen (dedup)."""
        if raw_hash in self._seen_hashes:
            return False  # duplicate content, skip
        self._memory[key] = (datetime.utcnow(), value)
        self._seen_hashes.add(raw_hash)
        return True


# Freshness targets (from PRD section 7):
FRESHNESS_TARGETS = {
    Pillar.PERMITS:     timedelta(days=7),
    Pillar.POWER:       timedelta(hours=24),   # filings
    Pillar.EARNINGS:    timedelta(hours=72),
    Pillar.GPU_SUPPLY:  timedelta(hours=72),
    Pillar.NICS_OPTICS: timedelta(hours=72),
    Pillar.SATELLITE:   timedelta(days=14),
    Pillar.TSMC:        timedelta(hours=72),
}


# =============================================================================
# 5. SOURCE LINEAGE SCHEMA (Database)
# =============================================================================

# Using SQLAlchemy-style DDL for PostgreSQL. In Phase 1, SQLite is acceptable.

SOURCE_LINEAGE_DDL = """
-- ==========================================================
-- Core tables for source lineage tracking
-- ==========================================================

CREATE TABLE IF NOT EXISTS data_sources (
    source_id       TEXT PRIMARY KEY,           -- "edgar-8k", "shovels-permits"
    name            TEXT NOT NULL,
    pillar          TEXT NOT NULL,               -- "power", "permits", etc.
    tier            TEXT NOT NULL,               -- "free", "freemium", "paid"
    cadence         TEXT NOT NULL,
    base_url        TEXT NOT NULL,
    freshness_target_hours INTEGER NOT NULL,
    fallback_source_id TEXT REFERENCES data_sources(source_id),
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id          TEXT PRIMARY KEY,            -- UUID
    source_id       TEXT NOT NULL REFERENCES data_sources(source_id),
    started_at      TIMESTAMP NOT NULL,
    finished_at     TIMESTAMP,
    status          TEXT NOT NULL,               -- "running", "success", "error"
    records_fetched INTEGER DEFAULT 0,
    records_stored  INTEGER DEFAULT 0,
    error_message   TEXT,
    parser_version  TEXT NOT NULL,
    parameters      JSONB                        -- adapter-specific params used
);

CREATE TABLE IF NOT EXISTS ingested_records (
    record_id       TEXT PRIMARY KEY,            -- deterministic hash
    run_id          TEXT NOT NULL REFERENCES ingestion_runs(run_id),
    source_id       TEXT NOT NULL REFERENCES data_sources(source_id),
    pillar          TEXT NOT NULL,
    company         TEXT,                        -- normalized company name
    geography       TEXT,                        -- normalized geography
    event_timestamp TIMESTAMP NOT NULL,          -- when the event occurred (filing date, etc.)
    payload         JSONB NOT NULL,              -- adapter-specific structured data
    -- Lineage fields (denormalized for query speed):
    source_url      TEXT NOT NULL,               -- clickable primary source
    retrieved_at    TIMESTAMP NOT NULL,
    parser_version  TEXT NOT NULL,
    confidence      REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    raw_hash        TEXT NOT NULL,               -- SHA-256 of raw response
    is_cached       BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Deduplication index: same source + same content = skip
CREATE UNIQUE INDEX IF NOT EXISTS idx_dedup
    ON ingested_records(source_id, raw_hash);

-- Fast lookups by pillar + company + time
CREATE INDEX IF NOT EXISTS idx_pillar_company_time
    ON ingested_records(pillar, company, event_timestamp DESC);

-- Fast lookups by geography
CREATE INDEX IF NOT EXISTS idx_geography
    ON ingested_records(geography);

-- Freshness monitoring: latest record per source
CREATE INDEX IF NOT EXISTS idx_source_latest
    ON ingested_records(source_id, retrieved_at DESC);

-- ==========================================================
-- View: data freshness dashboard
-- ==========================================================
CREATE OR REPLACE VIEW v_source_freshness AS
SELECT
    ds.source_id,
    ds.name,
    ds.pillar,
    ds.freshness_target_hours,
    MAX(ir.retrieved_at) AS last_retrieved,
    EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - MAX(ir.retrieved_at))) / 3600
        AS hours_since_last,
    CASE
        WHEN MAX(ir.retrieved_at) IS NULL THEN 'NEVER_INGESTED'
        WHEN EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - MAX(ir.retrieved_at))) / 3600
             > ds.freshness_target_hours THEN 'STALE'
        ELSE 'FRESH'
    END AS freshness_status,
    COUNT(ir.record_id) AS total_records
FROM data_sources ds
LEFT JOIN ingested_records ir ON ds.source_id = ir.source_id
GROUP BY ds.source_id, ds.name, ds.pillar, ds.freshness_target_hours;
"""


# =============================================================================
# 6. NORTHERN VIRGINIA PHASE-1 MINIMUM ARCHITECTURE
# =============================================================================
#
# See ASCII diagram in the companion architecture document.
# The minimum viable ingestion for NoVA Phase 1 consists of:
#
#   Source 1: SEC EDGAR (free) -- 8-K + 10-K for energy companies + hyperscalers
#   Source 2: County permits   -- Loudoun + Prince William county portals (free scrape)
#                                 OR Shovels.ai API (paid, if approved)
#   Source 3: Sentinel-2       -- Free ESA satellite imagery (10m resolution)
#                                 via Copernicus Data Space API
#
# Minimal components:
#   - 3 adapter implementations (EdgarAdapter, PermitAdapter, SentinelAdapter)
#   - SQLite database (single file, upgrade to PostgreSQL in Phase 2)
#   - APScheduler running in the FastAPI process
#   - Cache layer (file-based, same as existing edgar_agent.py pattern)
#   - FastAPI endpoints (extend existing main.py)


# =============================================================================
# 7. COST OPTIMIZATION STRATEGIES
# =============================================================================

COST_OPTIMIZATION_NOTES = """
1. CACHING
   - Every raw response is SHA-256 hashed and stored in cache/
   - Cache TTLs match freshness targets (no refetch if still fresh)
   - EDGAR: 12h cache (current pattern, keep it)
   - Satellite: cache metadata 24h; imagery tiles cached indefinitely (immutable)
   - Permits: 7-day cache (matches weekly cadence)

2. DEDUPLICATION
   - raw_hash unique index prevents storing identical content twice
   - Incremental fetch: pass `since=last_run` to adapters
   - EDGAR: use filing date filter to skip already-processed filings
   - Permits: track last-seen permit ID per county

3. INCREMENTAL INGESTION
   - Every adapter receives `since` parameter = last successful run timestamp
   - EDGAR: filter filingDate >= since in submissions JSON
   - Permits: filter by date_filed >= since
   - Satellite: only request tiles where change detection score > threshold

4. FREE-TIER MAXIMIZATION
   - Sentinel-2 (free, 10m) as default satellite source
   - Planet Labs only for sites where 10m is insufficient
   - County portal scraping (free) as permit fallback if Shovels not approved
   - EDGAR ATOM RSS feed (free) for event-driven filing alerts

5. API CALL BUDGETING
   - Track API calls per source per day in ingestion_runs table
   - Alert if approaching paid-tier limits
   - Satellite: batch coordinate requests (one API call for multiple sites)
"""
