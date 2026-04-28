# Data Ingestion Layer -- Architecture Specification

**Platform:** Datacenter & Power Intelligence Platform (OCI)
**Author:** System Architect
**Date:** 2026-04-28
**Status:** Proposal for Phase 1

---

## System Overview

The data ingestion layer sits between external data sources (SEC EDGAR, county permit
portals, satellite APIs, earnings transcripts) and the existing FastAPI backend. Its job
is to fetch, normalize, validate, cache, and store data with full source lineage so
that every metric in the dashboard links back to a primary source with a confidence
score grounded in parsing certainty.

The layer is designed around three principles:

1. **Adapter abstraction** -- every source implements the same 4-method interface;
   consumers never know which concrete source is active.
2. **Configuration-driven swapping** -- switching from Sentinel-2 (free) to Planet Labs
   (paid) is a YAML config change, not a code change.
3. **Incremental, deduplicated ingestion** -- only fetch what is new; never store the
   same raw content twice.

---

## Architecture Diagram

```
                           EXTERNAL SOURCES
    +-----------+   +-------------+   +------------+   +---------------+
    | SEC EDGAR |   | County      |   | Sentinel-2 |   | Earnings      |
    | (free)    |   | Permits     |   | (free) /   |   | Transcripts   |
    |           |   | (free/paid) |   | Planet Labs |   | (quarterly)   |
    +-----------+   +-------------+   +------------+   +---------------+
          |               |                 |                  |
          v               v                 v                  v
    +================================================================+
    |                   ADAPTER LAYER                                 |
    |                                                                |
    |  +---------------+  +----------------+  +------------------+   |
    |  | EdgarAdapter  |  | PermitAdapter  |  | SatelliteAdapter |   |
    |  | .fetch()      |  | .fetch()       |  | .fetch()         |   |
    |  | .normalize()  |  | .normalize()   |  | .normalize()     |   |
    |  | .validate()   |  | .validate()    |  | .validate()      |   |
    |  +---------------+  +----------------+  +------------------+   |
    |                                                                |
    |  Each adapter implements: DataSourceAdapter (abstract)         |
    |  Each record carries:     SourceLineage (url, hash, conf.)    |
    +================================================================+
          |                       |                      |
          v                       v                      v
    +================================================================+
    |                 SOURCE REGISTRY                                 |
    |                                                                |
    |  Loaded from config/sources.yaml at startup                    |
    |  Maps: pillar -> [source_id] -> adapter instance               |
    |  Supports: set_active(pillar, source_id) for hot-swap          |
    |  Enforces: one free fallback per pillar                        |
    +================================================================+
          |
          v
    +================================================================+
    |               INGESTION SCHEDULER                              |
    |                                                                |
    |  +-- Cron jobs (APScheduler) ------+                           |
    |  |  permits:  Monday 6 AM UTC      |                           |
    |  |  satellite: Monday 6 AM UTC     |                           |
    |  |  earnings: 15th of Jan/Apr/Jul/Oct                          |
    |  +---------------------------------+                           |
    |                                                                |
    |  +-- Event-driven triggers --------+                           |
    |  |  EDGAR RSS: poll every 15 min   |                           |
    |  |  Earnings calendar: daily check |                           |
    |  +---------------------------------+                           |
    |                                                                |
    |  Retry: exponential backoff (1m -> 5m -> 30m), max 3           |
    +================================================================+
          |
          v
    +================================================================+
    |                    CACHE LAYER                                  |
    |                                                                |
    |  +-- Rate Limiter ---------+  +-- Dedup Filter ---------+      |
    |  | EDGAR: 10 req/s sema   |  | SHA-256 raw_hash check  |      |
    |  | Satellite: 5 req/s     |  | Skip if hash exists     |      |
    |  +------------------------+  +--------------------------+      |
    |                                                                |
    |  +-- TTL Cache (memory + disk) --+                             |
    |  | EDGAR:     12h                |                             |
    |  | Permits:   7d                 |                             |
    |  | Satellite: 24h (metadata)     |                             |
    |  | Earnings:  90d (immutable)    |                             |
    |  +-------------------------------+                             |
    +================================================================+
          |
          v
    +================================================================+
    |                    DATA STORE                                   |
    |                                                                |
    |  Phase 1: PostgreSQL + SQLModel + JSONB (self-hosted on OCI VM)  |
    |  No SQLite phase — PostgreSQL from day one (Decision #1).        |
    |                                                                |
    |  Tables:                                                       |
    |    data_sources       -- registry of all sources               |
    |    ingestion_runs     -- audit log of every fetch              |
    |    ingested_records   -- normalized data + lineage             |
    |                                                                |
    |  Views:                                                        |
    |    v_source_freshness -- FRESH / STALE / NEVER_INGESTED        |
    +================================================================+
          |
          v
    +================================================================+
    |                EXISTING FASTAPI BACKEND                         |
    |                                                                |
    |  /api/power/capacity     -- reads from ingested_records        |
    |  /api/power/announcements -- merges curated + ingested         |
    |  /api/permits            -- reads from ingested_records        |
    |  /api/satellite          -- reads from ingested_records        |
    |  /api/sources            -- reads from v_source_freshness      |
    |                                                                |
    |  New endpoints:                                                |
    |  /api/ingestion/status   -- scheduler status, freshness        |
    |  /api/ingestion/trigger  -- manual re-ingest (admin)           |
    |  /api/lineage/{record_id} -- full lineage for any datapoint   |
    +================================================================+
          |
          v
    +------------------+
    |  React Frontend  |
    |  (existing)      |
    +------------------+
```

---

## 1. Adapter Interface Design

All interface definitions are in the companion Python file:
`docs/architecture/data-ingestion-layer.py`

Summary of the abstract `DataSourceAdapter` contract:

```python
class DataSourceAdapter(abc.ABC):

    @abc.abstractmethod
    def get_metadata(self) -> SourceMetadata:
        """Static descriptor: source_id, pillar, tier, cadence, rate_limit, freshness_target."""

    @abc.abstractmethod
    async def fetch(
        self,
        *,
        since: datetime | None = None,
        geography: str | None = None,
        company: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[RawRecord]:
        """Pull raw data. Incremental via `since`. Returns hashed RawRecords."""

    @abc.abstractmethod
    async def normalize(self, raw_records: list[RawRecord]) -> list[IngestedRecord]:
        """Transform to canonical schema with SourceLineage attached."""

    @abc.abstractmethod
    async def validate(self, records: list[IngestedRecord]) -> list[IngestedRecord]:
        """Filter out invalid / duplicate / low-confidence records."""

    async def ingest(self, **kwargs) -> list[IngestedRecord]:
        """Convenience: fetch -> normalize -> validate pipeline."""
```

Every `IngestedRecord` carries a `SourceLineage` with:
- `source_url` (clickable primary source)
- `retrieved_at` (UTC timestamp)
- `parser_version` (semver)
- `confidence` (0.0-1.0, from parsing certainty)
- `raw_hash` (SHA-256 for dedup)

---

## 2. Source Registry Pattern

```
config/sources.yaml
--------------------
sources:
  edgar-8k:
    adapter_class: "ingestion.adapters.edgar.Edgar8KAdapter"
    active: true
    pillar: power
    tier: free
    cadence: event_driven
    freshness_target_hours: 24
    rate_limit:
      requests_per_second: 10
    params:
      user_agent: "Datacenter Intelligence Platform research@oracle.com"
      ciks: { ... }

  shovels-permits:
    adapter_class: "ingestion.adapters.shovels.ShovelsPermitAdapter"
    active: true
    pillar: permits
    tier: paid
    cadence: weekly
    freshness_target_hours: 168
    fallback: "county-permits-scraper"

  county-permits-scraper:
    adapter_class: "ingestion.adapters.permits.CountyPermitScraperAdapter"
    active: false          # free fallback, activates if Shovels unavailable
    pillar: permits
    tier: free
    cadence: weekly
    freshness_target_hours: 168

  sentinel-2:
    adapter_class: "ingestion.adapters.satellite.Sentinel2Adapter"
    active: true           # default free satellite source
    pillar: satellite
    tier: free
    cadence: weekly

  planet-labs:
    adapter_class: "ingestion.adapters.satellite.PlanetLabsAdapter"
    active: false          # activate when budget approved
    pillar: satellite
    tier: paid
    cadence: daily
```

At startup, the `SourceRegistry` reads this YAML:
1. Instantiates each `adapter_class` via importlib
2. Calls `adapter.get_metadata()` to register it
3. Sets `active: true` sources as the default for their pillar
4. If a paid source fails, automatically falls back to `fallback` source

To switch from Sentinel-2 to Planet Labs:
```yaml
# Change in sources.yaml:
  sentinel-2:
    active: false
  planet-labs:
    active: true
```
No code changes. Restart (or hot-reload via `/api/ingestion/reload-config`).

---

## 3. Cadence Management

```
+---------------------+-------------------+--------------------------------+
| Source               | Cadence           | Trigger                        |
+---------------------+-------------------+--------------------------------+
| SEC EDGAR 8-K       | Event-driven      | EDGAR ATOM RSS poll (15 min)   |
| SEC EDGAR 10-K/10-Q | Quarterly         | Cron: 15th of Jan/Apr/Jul/Oct  |
| County permits      | Weekly            | Cron: Monday 06:00 UTC         |
| Shovels.ai          | Weekly            | Cron: Monday 06:00 UTC         |
| Sentinel-2          | Weekly            | Cron: Monday 08:00 UTC         |
| Planet Labs         | Daily             | Cron: Daily 06:00 UTC          |
| NVIDIA earnings     | Quarterly (event) | Earnings calendar + 24h delay  |
| TSMC earnings       | Quarterly (event) | Earnings calendar + 24h delay  |
+---------------------+-------------------+--------------------------------+
```

Implementation: APScheduler 4.x running inside the FastAPI process (Phase 1).
Phase 2: migrate to Celery + Redis for distributed scheduling if needed.

Event-driven flow for EDGAR:
```
EDGAR ATOM RSS Feed (https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&...&output=atom)
    |
    v  (poll every 15 min via APScheduler)
RSS Parser --> new filing detected?
    |                          |
    no --> sleep               yes --> enqueue EdgarAdapter.ingest(filing_url)
                                         |
                                         v
                                   fetch -> normalize -> validate -> store
                                         |
                                         v
                                   ingested_records table updated
```

---

## 4. Data Freshness & Caching

### Rate Limit Enforcement

```python
import asyncio

# Module-level semaphores (initialized once)
EDGAR_SEMAPHORE = asyncio.Semaphore(10)     # EDGAR: 10 req/s
SATELLITE_SEMAPHORE = asyncio.Semaphore(5)  # satellite APIs: 5 concurrent

async def rate_limited_fetch(url: str, semaphore: asyncio.Semaphore) -> bytes:
    async with semaphore:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
        await asyncio.sleep(0.1)  # 100ms floor between releases
```

### Cache TTL Policy

| Source | Cache TTL | Rationale |
|--------|-----------|-----------|
| EDGAR submissions JSON | 12h | Filings change rarely; 12h is conservative |
| EDGAR filing HTML | 30d | Filings are immutable once published |
| Permit API responses | 7d | Matches weekly refresh cadence |
| Satellite metadata | 24h | New imagery appears daily |
| Satellite imagery tiles | Indefinite | Imagery is immutable |
| Earnings transcripts | 90d | Immutable once published |

### Freshness Monitoring

The `v_source_freshness` database view (see schema below) provides real-time
freshness status. The `/api/ingestion/status` endpoint exposes this to the
frontend Sources tab.

Alert thresholds:
- STALE: exceeded freshness target by 1x (warn)
- CRITICAL: exceeded freshness target by 2x (page on-call)

---

## 5. Source Lineage Schema

Full DDL is in `docs/architecture/data-ingestion-layer.py` (the `SOURCE_LINEAGE_DDL` variable).

### Entity Relationship Diagram

```
+------------------+       +-------------------+       +--------------------+
| data_sources     |       | ingestion_runs    |       | ingested_records   |
|------------------|       |-------------------|       |--------------------|
| source_id (PK)   |<------| source_id (FK)    |<------| source_id (FK)     |
| name             |       | run_id (PK)       |<------| run_id (FK)        |
| pillar           |       | started_at        |       | record_id (PK)     |
| tier             |       | finished_at       |       | pillar             |
| cadence          |       | status            |       | company            |
| base_url         |       | records_fetched   |       | geography          |
| freshness_target |       | records_stored    |       | event_timestamp    |
| fallback_source  |       | error_message     |       | payload (JSONB)    |
| is_active        |       | parser_version    |       | source_url         |
+------------------+       | parameters (JSONB)|       | retrieved_at       |
                           +-------------------+       | parser_version     |
                                                       | confidence         |
                                                       | raw_hash           |
                                                       | is_cached          |
                                                       +--------------------+

                                                       Indexes:
                                                         UNIQUE(source_id, raw_hash) -- dedup
                                                         (pillar, company, event_timestamp DESC)
                                                         (geography)
                                                         (source_id, retrieved_at DESC)
```

### Key Design Decisions

- **Payload is JSONB:** Each adapter stores its own structured data in `payload`.
  Power deals have `capacity_mw`, `energy_source`, `buyer`, `seller`. Permits have
  `permit_type`, `status`, `estimated_sqft`. This avoids N pillar-specific tables
  while remaining queryable via JSONB operators.

- **Lineage fields are denormalized** onto `ingested_records` rather than in a
  separate lineage table. This makes the most common query -- "show me this metric
  with its source" -- a single-table read.

- **`raw_hash` unique index** prevents storing the same raw content twice, even
  across runs. This is the primary deduplication mechanism.

---

## 6. Northern Virginia Phase-1 Minimum Architecture

### What to Build

```
+-----------------------------------------------------------------+
|  PHASE 1 SCOPE: Northern Virginia (NoVA)                        |
|                                                                 |
|  Sources (3 adapters):                                          |
|    1. EdgarAdapter        -- 8-K from energy CIKs + 10-K/Q     |
|       Already partially built (edgar_agent.py -- refactor)      |
|    2. PermitAdapter       -- Loudoun + Prince William counties  |
|       Free scrape first; Shovels.ai if approved                 |
|    3. SentinelAdapter     -- Copernicus API (free)              |
|       10m resolution, NoVA site coordinates                     |
|                                                                 |
|  Database: PostgreSQL + SQLModel (self-hosted on OCI VM)         |
|    3 tables + 1 view (see schema above)                         |
|                                                                 |
|  Scheduler: APScheduler in FastAPI process                      |
|    EDGAR RSS poll: every 15 min                                 |
|    Permits: weekly (Monday)                                     |
|    Satellite: weekly (Monday)                                   |
|                                                                 |
|  API changes to main.py:                                        |
|    /api/permits      -> read from ingested_records              |
|    /api/satellite    -> merge curated sites + satellite data    |
|    /api/sources      -> read from v_source_freshness            |
|    /api/lineage/{id} -> new endpoint                            |
|    /api/ingestion/status -> new endpoint                        |
+-----------------------------------------------------------------+
```

### Migration Path from Current Code

The existing `edgar_agent.py` becomes `ingestion/adapters/edgar.py`:
- Replace `urllib.request` (blocking) with `httpx` (async)
- Replace bare `except Exception` with structured error handling + logging
- Keep the existing file-based cache but wrap it in `IngestionCache`
- Output `IngestedRecord` with `SourceLineage` instead of raw dicts

The existing `curated_deals.py` remains as-is (hand-verified seed data). It is
loaded at startup as "source_id: curated-deals" with confidence 0.95-0.99.
New EDGAR ingestion augments (does not replace) curated deals.

The existing `mock_data.py` functions (`get_permits_data`, `get_triangulation_data`,
etc.) are gradually replaced: each endpoint checks if real ingested data exists in
the database, and falls back to mock only if no real data is available. The response
includes a `data_quality: "real" | "mock"` field so the frontend can display a badge.

### Suggested Directory Structure

```
backend/
  ingestion/
    __init__.py
    interfaces.py          # DataSourceAdapter, SourceLineage, etc.
    registry.py            # SourceRegistry + YAML loader
    scheduler.py           # IngestionScheduler (APScheduler wrapper)
    cache.py               # IngestionCache (rate limit + TTL + dedup)
    adapters/
      __init__.py
      edgar.py             # EdgarAdapter (refactored from edgar_agent.py)
      permits.py           # CountyPermitScraperAdapter
      shovels.py           # ShovelsPermitAdapter (stub until approved)
      sentinel.py          # Sentinel2Adapter
      planet.py            # PlanetLabsAdapter (stub until budget)
      earnings.py          # EarningsTranscriptAdapter
  config/
    sources.yaml           # source registry configuration
  data/
    # PostgreSQL database (self-hosted on OCI VM)
    cache/                 # file-based response cache (existing)
    curated_deals.py       # existing hand-verified data (keep)
    mock_data.py           # existing mocks (deprecate gradually)
```

---

## 7. Cost Optimization

| Strategy | Mechanism | Estimated Savings |
|----------|-----------|-------------------|
| Response caching | SHA-256 hash + TTL per source | Eliminates ~80% of redundant fetches |
| Incremental fetch | `since=last_run` on every adapter | Only new filings/permits fetched |
| Dedup on store | UNIQUE(source_id, raw_hash) index | Zero storage waste |
| Free-tier first | Sentinel-2 default; county scrape default | $0 satellite + $0 permits |
| Batch coordinates | Single satellite API call for N sites | 1 call vs N calls |
| EDGAR RSS trigger | Poll RSS (free) instead of scanning all CIKs | ~90% fewer EDGAR requests |
| Immutable caching | Earnings transcripts cached 90d | Quarterly sources fetched once |

### API Call Budget (Phase 1 Estimate)

```
Source              Calls/week    Cost/call    Weekly cost
------              ----------    ---------    -----------
EDGAR               ~200          $0           $0
County permits       ~20          $0           $0
Sentinel-2          ~10           $0           $0
Shovels.ai          ~50           TBD          TBD (vendor pricing)
Planet Labs          --           --           $0 (not active Phase 1)
------                                         ------
Phase 1 total                                  ~$0 (all free sources)
```

---

## ADRs (Architecture Decision Records)

### ADR-001: Adapter Interface over Direct Integration

**Context:** The existing `edgar_agent.py` makes direct urllib calls with bare
exception handling. Adding more sources (permits, satellite) in the same style
would create tightly coupled, hard-to-test code.

**Decision:** Define an abstract `DataSourceAdapter` interface that all sources
implement. Four methods: `get_metadata()`, `fetch()`, `normalize()`, `validate()`.

**Consequence:** New sources are added by implementing one class. Testing is
straightforward via mock adapters. Source swapping is a config change.

### ADR-002: PostgreSQL Self-Hosted from Phase 1

**Context:** Phase 1 has 3 data sources and serves a single geography. A full
PostgreSQL deployment adds ops overhead.

**Decision:** Use PostgreSQL + SQLModel self-hosted on the OCI VM from Phase 1 (per Decision #1 in 00-DECISIONS-AND-CONSTRAINTS.md). JSONB columns for semi-structured payloads. Alembic for migrations.

**Consequence:** Eliminates a migration step. PostgreSQL JSONB operators available from day one. Self-hosted on OCI VM keeps cost at $0. Schema managed via Alembic migrations.

### ADR-003: Async Adapters with Sync Compatibility

**Context:** The existing edgar_agent.py uses blocking `urllib`. FastAPI supports
async natively.

**Decision:** All adapter methods are `async def`. The existing blocking code is
wrapped in `asyncio.to_thread()` during migration, then rewritten with `httpx`.

**Consequence:** No blocking I/O in the FastAPI event loop. EDGAR rate limits
enforced via `asyncio.Semaphore(10)`.

### ADR-004: Source Lineage Denormalized onto Records

**Context:** Lineage could be a separate table joined at query time, or
denormalized onto each record.

**Decision:** Denormalize `source_url`, `retrieved_at`, `parser_version`,
`confidence`, `raw_hash` onto `ingested_records`.

**Consequence:** The most common query (metric + its source) is a single-table
read. Slight storage overhead (~100 bytes/record) is acceptable at our scale.

### ADR-005: Free Fallback per Pillar

**Context:** PRD risk section states "design ingestion behind adapter interfaces;
have one free fallback per pillar."

**Decision:** Every pillar has at least one `tier: free` adapter registered. The
registry's `get_active_adapter()` method falls back to free if the paid source
is not configured or fails.

**Consequence:**
- Power: EDGAR (free) is always available
- Permits: county scraper (free) backs up Shovels.ai (paid)
- Satellite: Sentinel-2 (free) backs up Planet Labs (paid)
- Earnings: SEC EDGAR 10-Q text (free) backs up paid transcript APIs

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| EDGAR rate limit (10 req/s) hit during bulk backfill | 403 responses, IP ban | asyncio.Semaphore(10) + 100ms floor + exponential backoff |
| County permit portals have no API (HTML scraping) | Brittle parsers break on redesign | Abstract behind adapter; easy to swap to Shovels.ai |
| Sentinel-2 10m resolution insufficient for change detection | Cannot verify construction progress | Design adapter interface so Planet Labs (3m) is a drop-in swap |
| PostgreSQL connection pool exhaustion under concurrent ingestion | Slow writes | asyncpg pool with max_size=20; connection timeout + retry |
| Paid vendor (Shovels) not approved by procurement | No permit data | County scraper fallback is the free backup |
| Mock data still served alongside real data | User confusion | Every API response includes `data_quality: "real" | "mock"` field |

---

## Conformance to 00-DECISIONS-AND-CONSTRAINTS.md

- **§1 Decision #1:** PostgreSQL self-hosted on OCI VM from Phase 1 (not SQLite → PostgreSQL migration path).
- **§2 Tech Stack:** httpx (not aiohttp), APScheduler, SQLModel + asyncpg + Alembic.
- **§4 EDGAR APIs:** 10 req/s rate limit, User-Agent header, no CORS (backend-only calls).
- **§5 UX Rule:** Additive only — architecture supports new endpoints without removing existing ones.
