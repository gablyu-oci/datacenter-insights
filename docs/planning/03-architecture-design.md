# Architecture Design -- Datacenter & Power Intelligence Platform

**Version:** 1.0
**Date:** 2026-04-28
**Author:** System Architect
**Status:** Proposed
**Scope:** Phase 1 target architecture with Phase 2 extension points

---

## 1. System Overview

The platform ingests public data about hyperscaler power contracts, GPU supply chains, county permits, and satellite imagery, normalizes it against a canonical entity hierarchy (company > site > county > state > country), stores it with full lineage metadata, and serves it through a structured API to a React dashboard. Every metric displayed in the UI must link to its primary source URL.

### Current State Summary

| Concern | Current | Problem |
|---|---|---|
| Data layer | `mock_data.py` (7 functions, `random.*`) + `curated_deals.py` (22 verified deals) | 78% mock; values regenerate per request; no persistence |
| API | Single `main.py`, 12 sync `@app.get` handlers | No modularity; sync handlers block the event loop |
| Ingestion | `edgar_agent.py`: sync `urllib.request`, silent `except Exception`, 12h file cache | Blocking I/O in async framework; errors invisible; no scheduler |
| Frontend | 9 tabs; `useApi` hook sets `error` but no component renders it | Users see blank states on failure, not error messages |
| Ops | No `requirements.txt`, CORS `*`, Google Maps key in `.env.local` | Not deployable; insecure; not reproducible |

---

## 2. Architecture Diagram

```mermaid
graph TB
    subgraph "External Data Sources"
        EDGAR["SEC EDGAR<br/>(8-K / 10-K / 10-Q)"]
        PERMITS["County Permit APIs<br/>(Shovels.ai / direct)"]
        EARNINGS["Earnings Transcripts<br/>(NVIDIA / TSMC / hyperscalers)"]
        SATELLITE["Satellite Imagery<br/>(Planet Labs / Maxar)"]
        UTILITY["Utility Filings<br/>(PJM / Dominion / etc.)"]
    end

    subgraph "Ingestion Layer"
        SCHED["APScheduler<br/>(cron triggers)"]
        EA["EdgarAdapter"]
        PA["PermitAdapter"]
        ETA["EarningsAdapter"]
        SA["SatelliteAdapter"]
        UA["UtilityAdapter"]
        SCHED --> EA & PA & ETA & SA & UA
        EA --> EDGAR
        PA --> PERMITS
        ETA --> EARNINGS
        SA --> SATELLITE
        UA --> UTILITY
    end

    subgraph "Normalization Layer"
        NRM["Normalizer<br/>(raw -> NormalizedRecord)"]
        ER["Entity Resolver<br/>(company/site/geo canonical IDs)"]
        EA & PA & ETA & SA & UA --> NRM
        NRM --> ER
    end

    subgraph "Persistent Store (PostgreSQL)"
        DB[("PostgreSQL")]
        COMPANIES["companies"]
        SITES["sites"]
        GEO["geo_hierarchy<br/>(county/state/country)"]
        DP["data_points<br/>(metric + source_url + confidence)"]
        DEALS["deals<br/>(power contracts)"]
        IR["ingestion_runs<br/>(audit trail)"]
        DB --- COMPANIES & SITES & GEO & DP & DEALS & IR
        ER --> DB
    end

    subgraph "Service Layer"
        TRI["Triangulation Engine<br/>(pure-function service)"]
        TRI --> DB
    end

    subgraph "API Layer (FastAPI + APIRouters)"
        HEALTH["GET /health"]
        R_POWER["routers/power.py"]
        R_GPU["routers/gpu.py"]
        R_SC["routers/supply_chain.py"]
        R_PERM["routers/permits.py"]
        R_SAT["routers/satellite.py"]
        R_TRI["routers/triangulation.py"]
        R_SRC["routers/sources.py"]
        R_POWER & R_GPU & R_SC & R_PERM & R_SAT & R_TRI & R_SRC --> DB
        R_TRI --> TRI
    end

    subgraph "Frontend (React 19 + Vite)"
        TQ["TanStack Query<br/>(cache + retry + error)"]
        TABS["Tab Components<br/>(Power / Satellite / GPU / NICs /<br/>TSMC / Permits / Triangulation / Sources)"]
        EB["ErrorBoundary +<br/>per-query error states"]
        TQ --> R_POWER & R_GPU & R_SC & R_PERM & R_SAT & R_TRI & R_SRC & HEALTH
        TABS --> TQ
        EB --- TABS
    end

    style DB fill:#2d6a4f,stroke:#1b4332,color:#fff
    style TRI fill:#6a040f,stroke:#370617,color:#fff
    style SCHED fill:#3a0ca3,stroke:#240090,color:#fff
```

### ASCII Fallback (for terminals without Mermaid rendering)

```
+---------------------------+     +---------------------------+
|   External Data Sources   |     |       Frontend            |
|  EDGAR / Permits /        |     |  React 19 + Vite          |
|  Earnings / Satellite /   |     |  TanStack Query           |
|  Utility Filings          |     |  ErrorBoundary            |
+------------+--------------+     +------------+--------------+
             |                                  |
             v                                  v
+---------------------------+     +---------------------------+
|    Ingestion Layer        |     |     API Layer (FastAPI)   |
|  APScheduler triggers     |     |  /api/power/*             |
|  EdgarAdapter             |     |  /api/gpu/*               |
|  PermitAdapter            |     |  /api/supply-chain/*      |
|  EarningsAdapter          |     |  /api/permits/*           |
|  SatelliteAdapter         |     |  /api/satellite/*         |
|  UtilityAdapter           |     |  /api/triangulation/*     |
+------------+--------------+     |  /api/sources/*           |
             |                    |  /health                  |
             v                    +------------+--------------+
+---------------------------+                  |
|  Normalization Layer      |                  |
|  raw -> NormalizedRecord  |                  v
|  Entity Resolution        |     +---------------------------+
|  (company/site/county/    |     | Triangulation Engine      |
|   state/country)          |     | (pure-function service)   |
+------------+--------------+     +------------+--------------+
             |                                 |
             v                                 v
+---------------------------------------------------+
|            PostgreSQL (Persistent Store)           |
|  companies | sites | geo_hierarchy | data_points  |
|  deals | ingestion_runs                           |
+---------------------------------------------------+
```

---

## 3. Data Model

All tables use UUID primary keys. Timestamps are UTC. Soft-delete via `deleted_at` where needed.

### 3.1 Entity-Relationship Diagram

```mermaid
erDiagram
    COMPANIES ||--o{ DEALS : "buyer or seller"
    COMPANIES ||--o{ SITES : "owns/operates"
    SITES ||--o{ DATA_POINTS : "measured at"
    SITES }o--|| GEO_HIERARCHY : "located in (county)"
    GEO_HIERARCHY }o--o| GEO_HIERARCHY : "parent (state/country)"
    DEALS ||--o{ DATA_POINTS : "sourced from"
    INGESTION_RUNS ||--o{ DATA_POINTS : "produced by"

    COMPANIES {
        uuid id PK
        text canonical_name "Microsoft | Amazon | Google | Meta | Oracle"
        text[] aliases "AWS, Amazon Web Services, AMZN"
        text ticker "MSFT, AMZN, GOOG, META, ORCL"
        text sec_cik "0000789019"
        jsonb metadata
        timestamp created_at
        timestamp updated_at
    }

    GEO_HIERARCHY {
        uuid id PK
        text name "Loudoun County | Virginia | US"
        text level "county | state | country"
        uuid parent_id FK "state->country, county->state"
        text fips_code "51107"
        float lat
        float lon
        jsonb metadata
    }

    SITES {
        uuid id PK
        uuid company_id FK
        uuid geo_id FK "references geo_hierarchy (county level)"
        text name "AWS Northern Virginia (IAD)"
        text address
        float lat
        float lon
        int size_acres
        text status "Operational | Active Construction | Land Prep | Planned"
        int construction_pct
        text announced_date
        jsonb milestones "array of milestone objects"
        text source_url
        float confidence
        timestamp created_at
        timestamp updated_at
    }

    DEALS {
        uuid id PK
        text legacy_id "msft-ceg-tmi-2023 (from curated_deals.py)"
        uuid buyer_id FK "-> companies"
        uuid seller_id FK "-> companies (nullable)"
        text deal_type "Nuclear PPA | Renewable PPA | Grid Power"
        text energy_source "Nuclear | Solar | Wind | Mixed"
        int capacity_mw "nullable"
        text location_description
        uuid geo_id FK "-> geo_hierarchy"
        date announced_date
        text status "Active | Contracted | FERC Review | RFP Open | Planned"
        int duration_years "nullable"
        text headline
        text excerpt
        text source_type "SEC 8-K | Press Release | Sustainability Report"
        text source_url
        text edgar_url "nullable"
        float confidence
        text data_source
        timestamp created_at
        timestamp updated_at
    }

    DATA_POINTS {
        uuid id PK
        uuid site_id FK "nullable"
        uuid company_id FK "nullable"
        uuid deal_id FK "nullable"
        uuid geo_id FK "nullable"
        uuid ingestion_run_id FK
        text metric_name "contracted_power_gw | gpu_shipped_units | nic_shipments"
        text metric_category "power | gpu | nic_optics | tsmc | permit | satellite"
        float numeric_value "nullable"
        text text_value "nullable"
        jsonb structured_value "nullable (for complex payloads)"
        text period "Q4 2025 | 2025-W17 | 2025-03-15"
        text period_type "quarter | week | date | annual"
        text source_url
        timestamp retrieved_at
        text parser_version "edgar_adapter:1.2.0"
        float confidence "0.0 - 1.0"
        jsonb lineage "upstream IDs, transformation applied"
        timestamp created_at
    }

    INGESTION_RUNS {
        uuid id PK
        text adapter_name "edgar | permits | earnings | satellite | utility"
        text adapter_version "1.0.0"
        timestamp started_at
        timestamp completed_at
        text status "running | success | partial_failure | failure"
        int records_fetched
        int records_normalized
        int records_stored
        int records_skipped
        text trigger "scheduled | manual | event"
        jsonb error_log "array of {message, source_url, timestamp}"
        jsonb config_snapshot "adapter config frozen at run time"
    }
```

### Sites Table (Aterio Canonical Seed — §3.1)

The `sites` table is seeded from `data_center_inventory_20260428.csv` (73 columns). Key column mappings:

| CSV Column | DB Column | Type | Notes |
|---|---|---|---|
| `ATERIO_DATA_CENTER_UID` | `aterio_dc_uid` | TEXT PK | Natural key |
| `DATA_CENTER_BUILDING_NAME` | `building_name` | TEXT | |
| `ATERIO_DATA_CENTER_CAMPUS_UID` | `aterio_campus_uid` | TEXT FK | Campus grouping |
| `DATA_CENTER_CAMPUS_NAME` | `campus_name` | TEXT | |
| `DATA_CENTER_STAGE` | `stage` | ENUM | Announcement/Construction/Activated/Cancelled/Withdrawn |
| `PCT_CONSTRUCTION_STATUS` | `pct_construction` | FLOAT | 0-100 |
| `PROVIDER_NAME` | `provider_name` | TEXT | Operator |
| `PROVIDER_TICKER_NAME` | `provider_ticker` | TEXT | For EDGAR join |
| `END_USER_COMPANIES` | `end_user_companies` | TEXT | Lessee |
| `FULL_ADDRESS` | `full_address` | TEXT | |
| `COUNTY_FIPS_CODE` | `county_fips` | TEXT | |
| `STATE_CODE` | `state_code` | CHAR(2) | |
| `LOCATION_LATITUDE` | `latitude` | FLOAT | |
| `LOCATION_LONGITUDE` | `longitude` | FLOAT | |
| `SELECTED_POWER_CAPACITY_MW` | `power_capacity_mw` | FLOAT | Best available MW |
| `ATERIO_EST_TOT_POWER_CAPACITY_MW` | `aterio_est_mw` | FLOAT | |
| `ATERIO_EST_TOT_POWER_CAPACITY_MW_LOWER` | `aterio_est_mw_lower` | FLOAT | |
| `ATERIO_EST_TOT_POWER_CAPACITY_MW_UPPER` | `aterio_est_mw_upper` | FLOAT | |
| `FLG_AI_FACILITY` | `is_ai_facility` | BOOLEAN | |
| `UTILITY_NAME` | `utility_name` | TEXT | |
| `BAL_AUTH_NAME` | `bal_auth_name` | TEXT | |
| `DATASHEET_URL` | `datasheet_url` | TEXT | Clickable source |
| `MAP_URL` | `map_url` | TEXT | Clickable source |
| `PROJECT_PERMIT_URL` | `permit_url` | TEXT | Clickable source |
| `RECORD_CREATED_DATE` | `record_created_at` | TIMESTAMP | |
| `RECORD_UPDATED_DATE` | `record_updated_at` | TIMESTAMP | |

Additional columns mapped 1:1 from CSV (see §3.1 of 00-DECISIONS-AND-CONSTRAINTS.md for full list): `SITE_ACREAGE`, `TOT_FACILITY_SPACE_SQFT`, `TOT_DATACENTER_SPACE_SQFT`, `TOT_PROJECT_COST`, `AVG_MARKET_POWER_COST`, `YEARLY_PUE`, `TOT_NUM_GENERATORS`, all date fields, `PROJECT_EXECUTION_LIKELIHOOD`, `FLG_BTM_ONSITE_POWER_GENERATION`, `NOTES`.

Entity resolution: `provider_ticker` joined to internal company IDs via **rapidfuzz alias table** (§2.1).

### Events Table (§3.3)

Sourced from the **Data Centers Events** sheet (957 rows × 48 cols) in `Data Centers's Data Dictionary (Data Product).xlsx`.

| Column | Type | Notes |
|---|---|---|
| `event_id` | UUID PK | |
| `aterio_dc_uid` | TEXT FK → sites | Join to sites table |
| `event_type` | ENUM | announcement, permit_filed, construction_start, activation, expansion, cancellation |
| `event_date` | DATE | |
| `event_description` | TEXT | |
| `source_url` | TEXT | Clickable |
| `created_at` | TIMESTAMP | Lineage |
| `updated_at` | TIMESTAMP | Lineage |

### Energy Projects Table (§3.4)

Sourced from `Energy Project Inventory Data Sample.xlsx` (1695 rows × 65 cols).

| Column | Type | Notes |
|---|---|---|
| `energy_project_id` | UUID PK | |
| `project_name` | TEXT | |
| `flg_btm_project` | BOOLEAN | Behind-the-meter |
| `developer_companies` | TEXT | |
| `developer_ticker` | TEXT | |
| `eia_entity_ids` | TEXT[] | Array of EIA IDs |
| `customer_companies` | TEXT | |
| `tot_contracted_power_mw` | FLOAT | |
| `tot_project_cost` | FLOAT | |
| `project_footprint_acreage` | FLOAT | |
| `payload` | JSONB | Remaining 50+ columns |
| `created_at` | TIMESTAMP | Lineage |
| `updated_at` | TIMESTAMP | Lineage |

Joinable to sites via developer/customer company linkage and EIA entity IDs.

### Companies Canonical Table

Resolves source-shaped company strings (Aterio provider names, EDGAR filers, EPA permittees) into a single canonical entity. Built incrementally as new sources are ingested.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | Internal canonical ID |
| `canonical_name` | TEXT NOT NULL | e.g. "Microsoft Corporation" |
| `short_name` | TEXT | e.g. "Microsoft" — for UI labels |
| `ticker` | TEXT | Public-company ticker (e.g. "MSFT") |
| `cik` | TEXT | SEC Central Index Key, zero-padded |
| `parent_company_id` | BIGINT FK → companies | NULL for top-level; non-NULL for subsidiaries / LLCs |
| `public_private` | TEXT CHECK IN ('Public','Private','Subsidiary') | Mirrors Aterio `*_PUBLIC_PRIVATE` |
| `aliases` | JSONB | `{known_aliases: [...], llc_subsidiaries: [...]}` |
| `created_at`, `updated_at` | TIMESTAMP | Lineage |

### Company Aliases Bridge

Maps every source-shaped raw company string back to a canonical `companies.id` with a confidence score. New rows added on ingestion when a fuzzy match is accepted (rapidfuzz score ≥ threshold) or via the LLC→parent multi-signal resolver (see `03-PIPELINE-ARCHITECTURE.md` §8).

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `company_id` | BIGINT FK → companies | |
| `source` | TEXT NOT NULL | `aterio_csv`, `edgar`, `epa_echo`, `tceq`, `manual`, … |
| `raw_name` | TEXT NOT NULL | Exact string seen in source |
| `match_method` | TEXT | `ticker_exact`, `cik_exact`, `rapidfuzz`, `exhibit_21`, `opencorporates`, `parcel_deed`, `manual` |
| `confidence` | NUMERIC(3,2) | 0.00–1.00 |
| `evidence` | JSONB | Score breakdown / supporting URLs |
| `created_at` | TIMESTAMP | |
| UNIQUE (`source`, `raw_name`) | | One canonical mapping per (source, raw_name) |

### Site Aliases Bridge

Maps source-shaped site identifiers (EPA FRS_ID, county permit IDs, ECHO facility IDs) back to a canonical `sites.id`. Joined via lat/lon + parcel + address when ingestion creates / matches a record.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `site_id` | BIGINT FK → sites | |
| `source` | TEXT NOT NULL | `aterio_csv`, `epa_echo`, `tceq`, `loudoun_county`, … |
| `source_record_id` | TEXT NOT NULL | FRS_ID / permit ID / etc. |
| `match_method` | TEXT | `aterio_uid`, `latlon_within_100m`, `parcel_apn`, `address_normalized`, `manual` |
| `confidence` | NUMERIC(3,2) | 0.00–1.00 |
| `created_at` | TIMESTAMP | |
| UNIQUE (`source`, `source_record_id`) | | |

### Site ↔ Company Associations (Role Edges)

The **single most important table** for the OCI %-share, Companies-tab, and Site-detail views. One row per (site, company, role) triple — same company can appear on the same site in multiple roles (e.g. Microsoft is both `provider` and `end_user` on a self-built Azure region in Quincy).

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `site_id` | BIGINT FK → sites | |
| `company_id` | BIGINT FK → companies | |
| `role` | TEXT NOT NULL | ENUM per `00-DECISIONS-AND-CONSTRAINTS.md` §5.1: `provider`, `provider_backer`, `end_user`, `financing`, `equipment`, `utility`, `developer`, `customer`, `permittee_llc`, `permit_parent` |
| `source` | TEXT NOT NULL | Which ingestion source produced this association |
| `source_record_id` | TEXT | Lineage back to raw row |
| `confidence` | NUMERIC(3,2) | Inherited from alias resolution |
| `mw_share` | NUMERIC | Optional. For multi-tenant sites, MW attributable to this end_user; NULL = full site MW counted at aggregation time. |
| `created_at`, `updated_at` | TIMESTAMP | Lineage |
| UNIQUE (`site_id`, `company_id`, `role`, `source`) | | Prevents duplicate ingest |

#### Population from Aterio CSV

| Aterio column | Role(s) emitted | Notes |
|---|---|---|
| `PROVIDER_NAME` (+ `PROVIDER_TICKER_NAME`) | `provider` | Ticker→CIK→canonical when public; rapidfuzz when private. |
| `PROVIDER_BACKED_BY` | `provider_backer` | Often the parent or strategic investor. Empty for self-owned. |
| `END_USER_COMPANIES` | `end_user` (one row per comma-split entry) | Multi-tenant sites produce N rows; sum semantics at query time. |
| `PROJECT_FINANCING_COMPANIES` | `financing` (split) | |
| `CONSTRUCTION_EQUIPMENT_PROVIDER_COMPANIES` | `equipment` (split) | |
| `UTILITY_NAME` (+ `UTILITY_TICKER_NAME`) | `utility` | |
| `DEVELOPER_COMPANIES` (energy_projects) | `developer` (split) | Joined to sites by EIA entity ID + lat/lon. |
| `CUSTOMER_COMPANIES` (energy_projects) | `customer` (split) | |

#### Population from EPA ECHO / state air permits (Phase 1.5)

| Source field | Role | Resolved via |
|---|---|---|
| Permittee (LLC) | `permittee_llc` | `epa_echo` raw_name |
| Resolved parent | `permit_parent` | Multi-signal resolver in `03-PIPELINE-ARCHITECTURE.md` §8: SEC Exhibit 21 → OpenCorporates → parcel deed → news corpus |

### Data Coverage Table (national-MVP coverage truth)

Tracks per-source per-state per-pillar coverage so the UI can render honest `<CoverageBadge />` indicators. Updated by every adapter at end-of-run; read by `/api/coverage`.

| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `pillar` | TEXT NOT NULL | `power_sites`, `sec_filings`, `building_permits`, `generator_permits`, `air_emissions`, `iso_queues`, `earnings`, `satellite`, `triangulation` |
| `state_code` | CHAR(2) | Two-letter US state code; `'US'` = national / federal; `'GLOBAL'` = global. NULL not allowed. |
| `source` | TEXT NOT NULL | `aterio_csv`, `edgar`, `epa_echo`, `va_open_data`, `tceq`, `ny_dec_socrata`, `wa_ecology`, `co_cdphe`, `or_deq`, `pjm_iso`, `sentinel2`, … |
| `coverage_status` | TEXT NOT NULL CHECK IN ('full','partial','federal_baseline','pending','unavailable') | See enum table below |
| `record_count` | INT | Number of canonical records (sites/permits/filings/etc.) currently in scope from this source for this state |
| `last_ingested_at` | TIMESTAMPTZ | Most recent successful ingestion run for this (pillar, state, source) |
| `freshness_sla_hours` | INT | Target staleness; UI compares `now() - last_ingested_at` against this |
| `notes` | TEXT | Human-readable, e.g. "PJM territory only — covers VA, MD, DC, NJ, PA, OH, WV, KY, IL, IN, MI, NC, TN, DE." |
| `roadmap` | TEXT | What's missing and the trigger to add it; e.g. "Iowa building permits: scrape pending standing-records request to IA DNR." |
| `created_at`, `updated_at` | TIMESTAMPTZ | |
| UNIQUE (`pillar`, `state_code`, `source`) | | One row per (pillar, state, source) |

**`coverage_status` enum semantics:**
- `full` — pillar is fully covered for this state/scope by this source.
- `partial` — source covers some but not all records (e.g. only datacenter-tagged permits).
- `federal_baseline` — federal source provides baseline only; state-level depth still missing.
- `pending` — known to be needed; ingestion not yet implemented (e.g. standing public-records request in flight).
- `unavailable` — no free source identified for this state/pillar combination; explicit gap.

**Initial seed at MVP launch (illustrative, exact list maintained in `backend/sources.yaml`):**

| Pillar | Coverage by state_code |
|---|---|
| `power_sites` | All 50 states + DC: `full` (Aterio CSV) |
| `sec_filings` | `US`: `full` (EDGAR is federal) |
| `air_emissions` | All 50 states + DC: `federal_baseline` (EPA ECHO/CAMD/Envirofacts) |
| `building_permits` | VA: `full` · NY/WA/CO/OR: `partial` (Socrata-style, datacenter NAICS filter) · TX: `partial` (TCEQ; air more than building) · all other 43 states+DC: `unavailable` (Phase-2 Shovels.ai) |
| `generator_permits` | All 50 states+DC: `federal_baseline` (EPA ECHO) · TX/CA/NY/WA/CO/OR: `partial` (state APIs) · VA/IA/AZ: `pending` (standing-records requests) · others: `federal_baseline` only |
| `iso_queues` | PJM territory states (VA/MD/DC/NJ/PA/OH/WV/KY/IL/IN/MI/NC/TN/DE): `partial` · others: `pending` |
| `earnings` | `US`: `partial` (best-effort IR-page scraping; FMP deferred) |
| `satellite` | `GLOBAL`: `full` (Sentinel-2 10 m, 5-day revisit) |
| `triangulation` | Computed; per-state status = `min(power_sites, generator_permits or building_permits, earnings)` for that state |

### 3.2 Migration Script Location

```
backend/
  alembic/
    versions/
      001_initial_schema.py
    env.py
    alembic.ini
```

### 3.3 Seed Data

The 22 deals from `data/curated_deals.py` and 16 sites from `get_satellite_sites()` become seed data loaded via `alembic/seed.py`. Each record maps to the new schema:

- `CURATED_DEALS[*].buyer` -> resolve to `companies.id` via alias lookup
- `CURATED_DEALS[*].state` -> resolve to `geo_hierarchy.id` via FIPS or name
- `CURATED_DEALS[*].source_url` -> preserved as `deals.source_url`
- `CURATED_DEALS[*].confidence` -> preserved as `deals.confidence`

---

## 4. API Contract

### 4.1 Router Structure

Replace `main.py` (113 lines, 12 endpoints) with:

```
backend/
  app/
    __init__.py
    main.py              # FastAPI app factory, middleware, router mount
    config.py            # Settings via pydantic-settings
    database.py          # async SQLAlchemy engine + session
    dependencies.py      # get_db, get_current_config
    routers/
      __init__.py
      health.py
      power.py
      gpu.py
      supply_chain.py
      permits.py
      satellite.py
      triangulation.py
      sources.py
    models/
      __init__.py
      company.py
      site.py
      geo.py
      deal.py
      data_point.py
      ingestion_run.py
    schemas/
      __init__.py
      power.py
      gpu.py
      supply_chain.py
      permits.py
      satellite.py
      triangulation.py
      sources.py
      common.py           # PagedResponse, SourceMeta, ErrorDetail
    services/
      __init__.py
      triangulation.py    # pure-function triangulation engine
      entity_resolver.py
    ingestion/
      __init__.py
      base.py             # SourceAdapter protocol
      edgar.py
      permits.py
      earnings.py
      satellite.py
      utility.py
      normalizer.py
      scheduler.py
    seed/
      __init__.py
      load_curated_deals.py
      load_satellite_sites.py
```

### 4.2 Endpoint Definitions

All responses wrap in a standard envelope:

```python
# schemas/common.py
from pydantic import BaseModel
from typing import Generic, TypeVar
from datetime import datetime

T = TypeVar("T")

class SourceMeta(BaseModel):
    source_url: str
    retrieved_at: datetime
    parser_version: str
    confidence: float  # 0.0 - 1.0

class ErrorDetail(BaseModel):
    code: str
    message: str
    detail: str | None = None

class PagedResponse(BaseModel, Generic[T]):
    data: list[T]
    total: int
    page: int
    page_size: int
    colors: dict[str, str] | None = None  # company color map
    sources: list[SourceMeta] | None = None
```

#### routers/health.py

```
GET /health
  Response: { "status": "ok", "version": "1.x.x", "db": "connected" | "error" }
```

#### routers/power.py

```
GET /api/power/capacity
  Query: company (str, optional), geo (str, optional, default "nova"), period (str, optional)
  Response: PagedResponse[PowerCapacityRow]

GET /api/power/timeseries
  Query: company (str, optional), geo (str, optional)
  Response: { data: dict[str, list[TimeseriesPoint]], colors: dict }

GET /api/power/announcements
  Query: company (str, optional, default "All"), include_edgar (bool, default false)
  Response: {
    curated: list[DealSchema],
    edgar: list[EdgarDealSchema],
    gw_summary: dict[str, GWSummary],
    total_deals: int,
    last_updated: str,
    data_sources: list[str]
  }

GET /api/power/gw-summary
  Response: { data: dict[str, GWSummary], colors: dict }
```

#### routers/gpu.py

```
GET /api/gpu/supply
  Query: period_start (str, optional), period_end (str, optional)
  Response: {
    shipped: list[QuarterlyMetric],
    deployed: list[QuarterlyMetric],
    inventory: list[QuarterlyMetric],
    revenue_estimates: list[RevenueEstimate],
    sources: list[SourceMeta]
  }
```

#### routers/supply_chain.py

```
GET /api/supply-chain/nics
  Response: {
    nic_shipments: list[NICShipment],
    optics_shipments: list[OpticsShipment],
    correlation_score: float,
    sources: list[SourceMeta]
  }

GET /api/supply-chain/tsmc
  Response: {
    capacity: list[TSMCCapacity],
    packaging: list[TSMCPackaging],
    sources: list[SourceMeta]
  }
```

#### routers/permits.py

```
GET /api/permits
  Query: county (str, optional), state (str, optional), company (str, optional)
  Response: PagedResponse[PermitRecord]
```

#### routers/satellite.py

```
GET /api/satellite/sites
  Query: company (str, optional), status (str, optional)
  Response: { data: list[SiteSchema], colors: dict }
```

#### routers/triangulation.py

```
GET /api/triangulation
  Query: geo (str, optional, default "nova")
  Response: {
    data: list[TriangulationRow],
    methodology: str,
    assumptions: dict,
    sources: list[SourceMeta]
  }

GET /api/triangulation/explain/{region}
  Response: {
    layers: { L1: ..., L2: ..., L3: ..., L4: ... },
    gap_gw: float,
    status: str,
    sources: list[SourceMeta]
  }
```

#### routers/sources.py

```
GET /api/sources
  Response: { sources: list[DataSourceSchema], agents: list[AgentStatusSchema] }

GET /api/sources/ingestion-runs
  Query: adapter (str, optional), status (str, optional), limit (int, default 20)
  Response: PagedResponse[IngestionRunSchema]
```

### New Endpoints (§3 + §4 of 00-DECISIONS-AND-CONSTRAINTS.md)

| Method | Path | Source | Notes |
|---|---|---|---|
| GET | `/api/sites` | sites table | Paginated, filterable by state/provider/stage. Accepts `?role=<role>&company_id=<id>` to filter by association. |
| GET | `/api/sites/{aterio_dc_uid}` | sites table | Single site with all 73 columns. |
| GET | `/api/sites/{aterio_dc_uid}/role-summary` | site_company_associations | **Role-grouped companies on a site** — returns `{provider: [...], end_user: [...], financing: [...], equipment: [...], utility: [...], permittee_llc: [...], permit_parent: [...]}` with each company's confidence. Powers the Site detail role-breakdown card. |
| GET | `/api/events` | events table | Filterable by site, type, date range. |
| GET | `/api/energy-projects` | energy_projects table | Filterable by developer, customer. |
| GET | `/api/companies` | companies + associations | Paginated company directory. Optional `?role=<role>` to filter companies that fill that role anywhere; `?top=N&order_by=site_count\|mw_total` for leaderboards. |
| GET | `/api/companies/{id}` | companies | Company detail (canonical name, ticker, CIK, parent, aliases). |
| GET | `/api/companies/{id}/role-summary` | site_company_associations | **Role distribution for a company** — returns `{provider: {site_count, mw_total}, end_user: {...}, ...}` across all its sites. Powers the Company detail page. |
| GET | `/api/companies/{id}/sites?role=<role>` | site_company_associations + sites | Sites where the company fills the given role. Default `role=any` returns all roles tagged. |
| GET | `/api/edgar/frames/{concept}/{period}` | Pass-through to `data.sec.gov/api/xbrl/frames/` | Cross-company quarterly capex/PP&E. Cached 12h. |
| GET | `/api/{tab}/oci-share?role=<role>` | Computed | **Role-parameterized** OCI %-share. See default-role-per-tab table below. |
| GET | `/api/coverage` | data_coverage table | Full coverage matrix — list of `{pillar, state_code, source, coverage_status, record_count, last_ingested_at, freshness_sla_hours, notes, roadmap}`. Powers the Coverage page. |
| GET | `/api/coverage/{pillar}` | data_coverage table | Coverage rows for one pillar (e.g. `building_permits`). Powers per-tab `<CoverageBadge />`. |
| GET | `/api/coverage/by-state/{state_code}` | data_coverage table | Coverage rows for one state across all pillars. Powers per-state empty-state messages on maps. |
| POST | `/api/agent/qa` | Triangulation Q&A agent (LLM, §6.5) | Streamed (SSE) chat turn. `{conversation_id?, message}` → tool calls + Markdown response. |
| GET | `/api/agent/qa/conversations/{id}` | `/v1/conversations` Llama Stack | Conversation history. |
| POST | `/api/agent/llc-resolve/{permittee_id}` | LLC resolver agent (§6.5) | Manual rerun. |
| GET | `/api/brief/weekly` | Weekly brief agent (§6.5) | Latest cached brief; `?as_of=YYYY-MM-DD` for historical. |
| GET | `/api/brief/weekly/history` | Weekly brief runs | Paginated history. |

All endpoints return a **lineage envelope**:
```json
{
  "data": [...],
  "lineage": {
    "source_url": "...",
    "retrieved_at": "...",
    "parser_version": "...",
    "confidence": 0.85
  }
}
```

### OCI %-Share Computation (Canonical Definition, Role-Parameterized)

> This section is the single canonical definition of OCI %-share computation. All other documents reference this section.

For each category tab, OCI %-share is computed *per role* — a single number is meaningless because the same company plays multiple roles (a hyperscaler can be `provider`, `end_user`, `financing` on different rows or even the same row). Per `00-DECISIONS-AND-CONSTRAINTS.md` §5.1 the role enum is fixed.

#### Formula

```
oci_pct = (oci_value(role) / total_tracked_value(role)) * 100
```

`oci_value(role)` and `total_tracked_value(role)` are computed against `site_company_associations` filtered to that role.

#### Per-tab default role and metric

| Tab | Default role | Numerator | Denominator |
|---|---|---|---|
| **Power** | `provider` (owned footprint) | SUM(`sites.power_capacity_mw`) for sites where Oracle is `provider` | SUM(`sites.power_capacity_mw`) across all tracked providers |
| **Power (alt view)** | `end_user` (operational footprint) | SUM(`sites.power_capacity_mw` × `mw_share` if set, else full MW) for sites where Oracle is `end_user` | SUM equivalent across all tracked end_users |
| **GPU** | `end_user` | Estimated GPUs attributed to Oracle (EDGAR-inferred) | Total estimated GPUs across all hyperscalers |
| **NICs/Optics** | `end_user` | Inferred share of NIC/transceiver shipments | Total tracked shipments |
| **TSMC** | `end_user` | Inferred CoWoS wafer allocation | Total tracked allocation |
| **Permits (building)** | `provider` | COUNT(permits) for Oracle-as-provider sites | COUNT(all tracked permits) |
| **Permits (generator/air)** | `permit_parent` | COUNT(generator permits) where resolved parent = Oracle | COUNT(all tracked generator permits) |
| **Triangulation** | `provider` | Oracle's contracted GW | Total contracted GW |

The UI offers a **role toggle** on every KPI tile (see `04-ux-evolution-plan.md`); the API exposes `?role=<role>` to override the default. `?role=any` collapses all roles into a presence count.

#### Identity resolution

Oracle is resolved to a canonical `companies.id` via:
1. `companies.ticker = 'ORCL'` (deterministic)
2. `companies.cik = '0001341439'` (deterministic)
3. `company_aliases.raw_name ILIKE '%oracle%'` (with curated alias entries; rapidfuzz handles spelling variants).

All `oci_value` queries reference `companies.id`, never raw strings — this guards against new spellings sneaking past.

#### Multi-tenant aggregation rule

When a site has multiple `end_user` associations (e.g. CoreWeave site with Microsoft + xAI as end users), the default behavior is:
- If `mw_share` is populated on the association, use it.
- Otherwise, attribute the full site MW to each end_user (acknowledging double-count) and tag the response with `multi_tenant_warning: true`.

Provider-role aggregations never have this issue (one provider per site).

#### Exposure

1. **SQL view:** `v_oci_share_by_tab` — materialized view, refreshed on ingestion. Includes one row per (tab, role) pair.
2. **API endpoint:** `GET /api/{tab}/oci-share?role=<role>` — returns `{ "oci_pct": 2.3, "oci_value": 150, "total_value": 6500, "unit": "MW", "role": "provider", "multi_tenant_warning": false }`.
3. **Frontend:** KPI tile on each tab with role toggle (see `04-ux-evolution-plan.md`).

---

## 5. Ingestion Layer Design

### 5.1 Adapter Protocol

```python
# ingestion/base.py
from typing import Protocol, runtime_checkable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

@dataclass
class RawRecord:
    """Unprocessed record from an external source."""
    source_url: str
    retrieved_at: datetime
    raw_content: str | dict    # HTML text or parsed JSON
    content_hash: str          # SHA-256 of raw_content for dedup
    metadata: dict = field(default_factory=dict)

@dataclass
class NormalizedRecord:
    """Record ready for entity resolution and storage."""
    metric_name: str           # e.g. "contracted_power_gw"
    metric_category: str       # e.g. "power"
    numeric_value: float | None
    text_value: str | None
    structured_value: dict | None
    period: str                # "Q4 2025", "2025-W17", "2025-03-15"
    period_type: str           # "quarter", "week", "date", "annual"
    company_hint: str          # raw company name for entity resolver
    geo_hint: str              # raw location string for entity resolver
    source_url: str
    retrieved_at: datetime
    parser_version: str
    confidence: float
    lineage: dict = field(default_factory=dict)

@runtime_checkable
class SourceAdapter(Protocol):
    """Interface that every ingestion adapter must implement."""

    @property
    def source_name(self) -> str: ...

    @property
    def version(self) -> str: ...

    async def fetch(self) -> list[RawRecord]:
        """Fetch raw data from external source. Must not raise -- returns empty on failure."""
        ...

    async def normalize(self, raw: list[RawRecord]) -> list[NormalizedRecord]:
        """Transform raw records into normalized form."""
        ...
```

### 5.2 Concrete Adapters

#### EdgarAdapter (ingestion/edgar.py)

Replaces `agents/edgar_agent.py`. Key changes:

| Aspect | Current (`edgar_agent.py`) | Target (`ingestion/edgar.py`) |
|---|---|---|
| HTTP client | `urllib.request` (sync, blocking) | `httpx.AsyncClient` with 10 req/s rate limiter |
| Error handling | `except Exception: pass` | Structured logging via `structlog`; errors recorded in `ingestion_runs.error_log` |
| Cache | File-based JSON in `data/cache/`, 12h TTL | PostgreSQL `data_points` table (idempotent upsert by `content_hash`) |
| Output | Returns list[dict] ad hoc | Returns `list[NormalizedRecord]` conforming to protocol |
| Scheduling | None (on-demand per request) | APScheduler: event-driven (check hourly for new 8-K); full sweep daily |

```python
# ingestion/edgar.py (sketch)
import httpx
import structlog
from .base import SourceAdapter, RawRecord, NormalizedRecord

logger = structlog.get_logger()

class EdgarAdapter:
    source_name = "edgar"
    version = "2.0.0"

    def __init__(self, client: httpx.AsyncClient, rate_limit: float = 0.1):
        self._client = client
        self._delay = rate_limit  # seconds between requests (SEC limit: 10/s)

    async def fetch(self) -> list[RawRecord]:
        records = []
        for company, cik in ENERGY_COMPANIES.items():
            if cik is None:
                continue
            try:
                data = await self._get_submissions(cik)
                filings = self._extract_material_8ks(data, company)
                for filing in filings[:6]:
                    html = await self._fetch_filing(filing["url"])
                    records.append(RawRecord(
                        source_url=filing["url"],
                        retrieved_at=datetime.utcnow(),
                        raw_content=html,
                        content_hash=hashlib.sha256(html.encode()).hexdigest(),
                        metadata={"company": company, "form": "8-K", "date": filing["date"]},
                    ))
            except Exception as exc:
                logger.error("edgar.fetch_failed", company=company, error=str(exc))
        return records

    async def normalize(self, raw: list[RawRecord]) -> list[NormalizedRecord]:
        results = []
        for rec in raw:
            text = html_to_text(rec.raw_content)
            mw = parse_mw_from_text(text)
            is_relevant = detect_tech_keywords(text)
            if is_relevant:
                results.append(NormalizedRecord(
                    metric_name="power_deal_announcement",
                    metric_category="power",
                    numeric_value=float(mw) if mw else None,
                    text_value=text[:600],
                    structured_value=None,
                    period=rec.metadata["date"],
                    period_type="date",
                    company_hint=rec.metadata["company"],
                    geo_hint="",  # extracted from filing text if possible
                    source_url=rec.source_url,
                    retrieved_at=rec.retrieved_at,
                    parser_version=f"edgar_adapter:{self.version}",
                    confidence=0.90,
                ))
        return results
```

#### PermitAdapter (ingestion/permits.py)

```python
class PermitAdapter:
    source_name = "permits"
    version = "1.0.0"

    # Phase 1: Shovels.ai API (if approved) or county RSS/scrape
    # Cadence: weekly
    # Geo scope: Loudoun County VA, Prince William County VA (Phase 1)

    async def fetch(self) -> list[RawRecord]: ...
    async def normalize(self, raw: list[RawRecord]) -> list[NormalizedRecord]: ...
```

#### EarningsAdapter (ingestion/earnings.py)

```python
class EarningsAdapter:
    source_name = "earnings"
    version = "1.0.0"

    # Phase 1: NVIDIA + TSMC quarterly transcripts
    # Cadence: event-driven (quarterly earnings dates)
    # Extracts: revenue, unit estimates, capacity guidance

    async def fetch(self) -> list[RawRecord]: ...
    async def normalize(self, raw: list[RawRecord]) -> list[NormalizedRecord]: ...
```

#### SatelliteAdapter (ingestion/satellite.py)

```python
class SatelliteAdapter:
    source_name = "satellite"
    version = "1.0.0"

    # Phase 2: Planet Labs API
    # Cadence: monthly
    # Phase 1: seed from get_satellite_sites() static data

    async def fetch(self) -> list[RawRecord]: ...
    async def normalize(self, raw: list[RawRecord]) -> list[NormalizedRecord]: ...
```

### 5.3 Scheduler Configuration

```python
# ingestion/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

def configure_scheduler(scheduler: AsyncIOScheduler):
    # EDGAR: check for new 8-Ks hourly during market hours, full sweep at 2am UTC
    scheduler.add_job(run_adapter, CronTrigger(hour="14-22", minute=0),
                      args=["edgar"], id="edgar_hourly")
    scheduler.add_job(run_adapter, CronTrigger(hour=2, minute=0),
                      args=["edgar"], id="edgar_daily")

    # Permits: weekly on Monday at 6am UTC
    scheduler.add_job(run_adapter, CronTrigger(day_of_week="mon", hour=6),
                      args=["permits"], id="permits_weekly")

    # Earnings: event-driven (triggered manually or by calendar),
    # but also check quarterly on known dates
    scheduler.add_job(run_adapter, CronTrigger(month="1,4,7,10", day=25, hour=4),
                      args=["earnings"], id="earnings_quarterly")

    # Satellite: monthly on 1st at 3am UTC (Phase 2)
    scheduler.add_job(run_adapter, CronTrigger(day=1, hour=3),
                      args=["satellite"], id="satellite_monthly")
```

### 5.4 Ingestion Pipeline Flow

```
1. Scheduler triggers adapter
2. Create ingestion_runs row (status=running)
3. adapter.fetch() -> list[RawRecord]
4. Dedup by content_hash against existing data_points
5. adapter.normalize(new_records) -> list[NormalizedRecord]
6. Entity resolver: company_hint -> companies.id, geo_hint -> geo_hierarchy.id
7. Upsert into data_points (+ deals if deal-type record)
8. Update ingestion_runs (status=success|partial_failure, counts)
9. Log summary via structlog
```

---

## 6. Triangulation Engine

### 6.1 Design Principle

The triangulation engine is a **pure-function service** with no side effects. It reads from the database, computes, and returns results. It never writes data or calls external APIs. This makes it testable, cacheable, and auditable.

### 6.2 Interface

```python
# services/triangulation.py
from dataclasses import dataclass

@dataclass
class TriangulationInput:
    region: str                      # "nova" | "us-east" | etc.
    contracted_power_gw: float       # L1: from deals table
    gpu_deployed_units: int          # L2: from data_points (gpu category)
    gpu_power_draw_kw: float         # assumption, default 0.7 kW per GPU
    utilization_pct: float           # assumption, default 0.80
    nic_shipped_units: int           # L3: from data_points (nic_optics)
    optics_shipped_units: int        # L3: from data_points (nic_optics)
    permit_signal_count: int         # L4: from data_points (permit)
    permit_total_mw: float           # L4: sum of estimated_mw from permits

@dataclass
class TriangulationAssumptions:
    gpu_power_draw_kw: float = 0.7   # H100 ~700W TDP
    utilization_pct: float = 0.80
    nic_per_gpu_ratio: float = 1.0   # 1 NIC per GPU (simplification)
    optics_per_gpu_ratio: float = 2.0
    pue: float = 1.3                 # Power Usage Effectiveness

@dataclass
class TriangulationResult:
    region: str
    contracted_power_gw: float
    gpu_power_demand_gw: float       # gpus * power_draw * utilization * PUE
    power_gap_gw: float              # contracted - demand
    status: str                      # "Overbuild" | "Balanced" | "Constrained"
    nic_validation_score: float      # 0-1: how well NIC shipments match GPU count
    optics_validation_score: float   # 0-1: how well optics match
    permit_validation_score: float   # 0-1: how well permits match contracted power
    overall_confidence: float        # weighted average of validation scores
    assumptions: TriangulationAssumptions
    layer_sources: dict[str, list[str]]  # L1-L4 -> list of source_urls

def triangulate(
    inp: TriangulationInput,
    assumptions: TriangulationAssumptions | None = None,
) -> TriangulationResult:
    a = assumptions or TriangulationAssumptions()

    # L1 vs L2: Power gap
    gpu_power_gw = (
        inp.gpu_deployed_units * a.gpu_power_draw_kw * a.utilization_pct * a.pue
    ) / 1_000_000  # kW -> GW
    gap = inp.contracted_power_gw - gpu_power_gw

    if gap > 1.5:
        status = "Overbuild"
    elif gap < -0.5:
        status = "Constrained"
    else:
        status = "Balanced"

    # L3: NIC/optics validation
    expected_nics = inp.gpu_deployed_units * a.nic_per_gpu_ratio
    nic_score = min(inp.nic_shipped_units / max(expected_nics, 1), 1.0)

    expected_optics = inp.gpu_deployed_units * a.optics_per_gpu_ratio
    optics_score = min(inp.optics_shipped_units / max(expected_optics, 1), 1.0)

    # L4: Permit validation
    permit_power_gw = inp.permit_total_mw / 1000
    permit_score = 1.0 - min(abs(permit_power_gw - inp.contracted_power_gw) /
                              max(inp.contracted_power_gw, 0.001), 1.0)

    overall = 0.4 * nic_score + 0.3 * optics_score + 0.3 * permit_score

    return TriangulationResult(
        region=inp.region,
        contracted_power_gw=inp.contracted_power_gw,
        gpu_power_demand_gw=round(gpu_power_gw, 3),
        power_gap_gw=round(gap, 3),
        status=status,
        nic_validation_score=round(nic_score, 3),
        optics_validation_score=round(optics_score, 3),
        permit_validation_score=round(permit_score, 3),
        overall_confidence=round(overall, 3),
        assumptions=a,
        layer_sources={},  # populated by caller from DB
    )
```

---

## 6.5 AI Agent Layer

Per `00-DECISIONS-AND-CONSTRAINTS.md` §4.2, MVP includes five LLM-powered components built on the OCI Llama Stack. Each is invoked through a single `LlmClient` wrapper so model swaps and fallbacks live in one place.

### 6.5.1 Backend module structure

```
backend/
  llm/
    client.py           # LlmClient — thin OpenAI-compat wrapper around Llama Stack
    prompts/            # Versioned prompt templates (one file per agent + version)
      edgar_extractor.v3.txt
      permit_extractor.v2.txt
      llc_resolver.v1.txt
      qa_agent.v1.txt
      weekly_brief.v1.txt
    schemas.py          # Pydantic response schemas for structured outputs
    agents/
      edgar_extractor.py        # A — single-turn structured extraction
      permit_extractor.py       # B — vision + structured extraction
      llc_resolver.py           # C — multi-turn agent with tool-use
      qa_agent.py               # D — conversational with tool-use + RAG
      weekly_brief.py           # E — scheduled tool-using agent
    tools/                      # Function-calling tool definitions
      site_query.py             # query_sites, query_site_role_summary
      company_query.py          # query_companies, query_company_role_summary
      coverage_query.py         # query_coverage, query_coverage_by_state
      oci_share_query.py        # query_oci_share(tab, role, state)
      sec_exhibit_21.py         # search_sec_exhibit_21(company_name)
      opencorporates.py         # lookup_opencorporates(llc_name, state)
      parcel_lookup.py          # lookup_parcel_owner(lat, lon)
      iso_queue_lookup.py       # lookup_iso_queue(facility_address)
      vector_search.py          # vector_search_permits(q), _filings(q), _transcripts(q)
      web_search.py             # wraps Llama Stack `builtin::websearch`
    fallback/                   # Deterministic-only paths for when Llama Stack is down
      edgar_regex.py            # The current regex extractor, gated by env var
      llc_deterministic.py      # The original §7.5.4 weighted-scoring resolver
```

The `LlmClient` exposes one method per usage pattern:

```python
class LlmClient:
    async def extract(self, *, model, prompt_version, input_text, schema) -> ExtractionResult: ...
    async def reason(self, *, model, prompt_version, messages, tools) -> AgentTurn: ...
    async def chat_stream(self, *, model, conversation_id, message, tools) -> AsyncIterator[ChatChunk]: ...
    async def embed(self, *, model, texts) -> list[list[float]]: ...
```

Every call records into `llm_extraction_runs` (§6.5.3) regardless of which method was used.

### 6.5.2 Per-agent specifications

| Agent | Endpoint | Input | Output | Tools |
|---|---|---|---|---|
| **A · EDGAR 8-K Extractor** | (internal, called by `EdgarAdapter`) | 8-K Item-1.01 narrative text | `[{counterparty, mw, geography, contract_term, confidence, source_quote}]` | none (single-turn) |
| **B · Permit PDF Extractor** | (internal, called by `EpaEchoAdapter` + state air adapters) | PDF page images + `pdfplumber` table dumps | `{rated_mw_total, num_units, fuel_type, emissions_limits, operational_hours_limit, raw_text_excerpts}` | none (single-turn vision) |
| **C · LLC → Parent Resolver** | `POST /api/agent/llc-resolve/{permittee_id}` | `permittee_raw_name`, `address`, `lat/lon` | `{parent_company_id, confidence, evidence: [{signal, weight, finding}]}` | `search_sec_exhibit_21`, `lookup_opencorporates`, `lookup_parcel_owner`, `lookup_iso_queue`, `web_search` |
| **D · Triangulation Q&A Agent** | `POST /api/agent/qa` (streaming) · `GET /api/agent/qa/conversations/{id}` | User message + `conversation_id` | Streamed Markdown + tool-call trace | `query_sites`, `query_companies`, `query_oci_share`, `query_coverage`, `query_triangulation`, `vector_search_permits`, `vector_search_filings` |
| **E · Weekly Brief Agent** | `GET /api/brief/weekly?as_of=YYYY-MM-DD` (cached) — generated by APScheduler | (nothing — runs on cron) | Markdown briefing + structured deltas | All Q&A tools + `compare_to_last_week(metric, key)` |

### 6.5.3 New tables

```sql
-- One row per LLM call (extraction, reasoning, chat). Powers cost tracking, debugging, idempotency.
CREATE TABLE llm_extraction_runs (
    id BIGSERIAL PRIMARY KEY,
    agent_name TEXT NOT NULL,         -- 'edgar_extractor' | 'permit_extractor' | 'llc_resolver' | 'qa_agent' | 'weekly_brief'
    model TEXT NOT NULL,              -- 'oci/openai.gpt-5.4-mini' etc.
    prompt_version TEXT NOT NULL,     -- 'edgar_extractor.v3'
    input_hash TEXT NOT NULL,         -- sha256 of canonical input — for caching + idempotency
    input_excerpt TEXT,               -- first 500 chars of input, for debugging
    output JSONB,                     -- the structured result
    confidence NUMERIC(3,2),          -- self-reported by the agent
    tool_calls JSONB,                 -- [{tool, args, result, latency_ms}, ...] for reasoning agents
    tokens_prompt INT,
    tokens_completion INT,
    latency_ms INT,
    status TEXT NOT NULL,             -- 'success' | 'fallback' | 'error'
    error_detail TEXT,
    fallback_path TEXT,               -- which deterministic fallback ran, if status='fallback'
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (agent_name, input_hash)   -- idempotent re-runs hit cache
);

CREATE INDEX idx_llm_runs_agent_created ON llm_extraction_runs(agent_name, created_at DESC);
CREATE INDEX idx_llm_runs_status ON llm_extraction_runs(status) WHERE status != 'success';

-- Backs the LLC-resolver human-review queue; introduced in §7.5.4 of 03-PIPELINE-ARCHITECTURE.md
CREATE TABLE permit_parent_review_queue (
    id BIGSERIAL PRIMARY KEY,
    generator_permit_id BIGINT REFERENCES generator_permits(id),
    permittee_raw_name TEXT NOT NULL,
    candidate_parents JSONB,          -- [{company_id, confidence, evidence}, ...]
    agent_run_id BIGINT REFERENCES llm_extraction_runs(id),
    status TEXT DEFAULT 'pending',    -- 'pending' | 'approved' | 'rejected' | 'escalated'
    reviewer_id TEXT,                 -- nullable until claimed
    reviewer_decision JSONB,          -- {company_id, notes, decided_at}
    created_at TIMESTAMPTZ DEFAULT now(),
    decided_at TIMESTAMPTZ
);
CREATE INDEX idx_review_queue_pending ON permit_parent_review_queue(status, created_at);
```

### 6.5.4 Agent endpoints (added to §4 endpoint table)

| Method | Path | Source | Notes |
|---|---|---|---|
| POST | `/api/agent/qa` | Triangulation Q&A agent | Streamed response (SSE). Body: `{conversation_id?, message}`. Returns `text/event-stream` with `chunk`, `tool_call`, `done` events. |
| GET | `/api/agent/qa/conversations/{id}` | `/v1/conversations/{id}/items` (Llama Stack) | Conversation history for resume. |
| POST | `/api/agent/llc-resolve/{permittee_id}` | LLC resolver agent | Manually trigger or rerun resolution. Returns the same shape as the resolver's batch output. |
| GET | `/api/brief/weekly` | weekly_brief_runs view | Latest weekly brief (cached). `?as_of=YYYY-MM-DD` to fetch a historical week. |
| GET | `/api/brief/weekly/history` | weekly_brief_runs view | Paginated list of past briefs. |

All agent endpoints carry the **lineage envelope** plus an `llm_run_id` field so the frontend can fetch the full tool-call trace for debugging or evidence display. Q&A streamed responses include tool calls inline as SSE events so the UI can render an evidence trail in real time.

### 6.5.5 Caching + idempotency

`llm_extraction_runs.UNIQUE (agent_name, input_hash)` makes re-extraction cheap: re-ingesting the same 8-K, the same PDF, or the same permittee yields a cache hit. The Q&A and Weekly Brief agents bypass this cache by varying their prompts (timestamp, conversation context).

### 6.5.6 Prompt versioning

Prompt templates live in `backend/llm/prompts/{agent}.v{N}.txt`. Promoting a new version is a code change (review-gated); the version string is stored on every run for reproducibility. The Llama Stack `/v1/prompts` registry is **not** used in MVP — keeping prompts in-repo is simpler for diffing and PR review. Move to the registry if/when prompts need to be edited at runtime by analysts.

---

## 7. Tech Stack Decisions

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python 3.12+ | Team familiarity; existing codebase; rich async ecosystem |
| Web framework | FastAPI (async) | Already in use; native async; OpenAPI docs; Pydantic validation |
| ORM | SQLAlchemy 2.0 (async) | Industry standard; Alembic migrations; async session support |
| Database | PostgreSQL 16 | JSONB for flexible metadata; PostGIS extension ready for geo queries; robust |
| Migrations | Alembic | Pairs with SQLAlchemy; version-controlled schema changes |
| HTTP client | httpx (async) | Drop-in replacement for urllib; async-native; connection pooling; timeout control |
| Scheduler | APScheduler 4.x (AsyncIOScheduler) | Lightweight; runs in-process; cron triggers; no external broker needed for Phase 1 |
| Logging | structlog | Structured JSON logs; context binding; integrates with stdlib logging |
| Dependency management | uv | Fast resolver; lockfile (`uv.lock`); replaces pip + requirements.txt |
| Frontend framework | React 19 + Vite + TypeScript | Already in use; no change needed |
| Data fetching (FE) | TanStack Query v5 | Replaces custom `useApi`; built-in cache, retry, stale-while-revalidate, error states |
| Charts (FE) | Recharts | Already in use; no change needed |
| Maps (FE) | Google Maps (proxied) | Already in use; key moves to backend proxy |

---

## 8. Architecture Decision Records

### ADR-001: PostgreSQL over SQLite/file-based storage

**Context:** Current system uses in-memory Python dicts (`mock_data.py`) and file-based JSON cache (`data/cache/`). No persistence, no querying, no concurrency safety.

**Decision:** Use PostgreSQL 16 with SQLAlchemy 2.0 async.

**Rationale:**
- JSONB columns for flexible `lineage` and `metadata` fields that will evolve
- PostGIS extension available when satellite/geo queries become complex in Phase 2
- Handles concurrent reads from API + writes from ingestion without file-locking issues
- Alembic provides version-controlled migrations
- SQLite was considered but lacks JSONB, concurrent writes, and PostGIS

**Consequences:**
- Requires self-hosted PostgreSQL process on this OCI VM (no Docker, no managed service)
- Added operational complexity vs file-based approach
- Migration path: seed existing `curated_deals.py` data via Alembic seed script

---

### ADR-002: async httpx replaces sync urllib.request

**Context:** `edgar_agent.py` uses `urllib.request.urlopen()` (synchronous, blocking). When called from FastAPI's async event loop, this blocks the entire server for 10-20 seconds during cold-cache EDGAR fetches.

**Decision:** Replace all HTTP calls with `httpx.AsyncClient`.

**Rationale:**
- Non-blocking: does not stall other requests while waiting on SEC EDGAR
- Connection pooling: reuse TCP connections across requests to same host
- Built-in timeout, retry, and redirect handling
- Rate limiting via `asyncio.Semaphore` or `httpx` transport hooks

**Consequences:**
- All ingestion code must be `async def`
- Need to manage `AsyncClient` lifecycle (create on startup, close on shutdown)
- `time.sleep(0.12)` becomes `await asyncio.sleep(0.12)`

---

### ADR-003: APScheduler (in-process) over Celery/external queue

**Context:** PRD requires scheduled ingestion: permits weekly, filings hourly/daily, earnings quarterly. No scheduler exists today.

**Decision:** Use APScheduler 4.x `AsyncIOScheduler` running in the same FastAPI process.

**Rationale:**
- Phase 1 has 4-5 adapters running at low frequency (hourly at most). No need for distributed task queue.
- Runs in the same event loop as FastAPI -- no broker (Redis/RabbitMQ) to manage.
- Cron triggers match the PRD cadence requirements exactly.
- If Phase 3 requires distributed workers, migration to ARQ or Celery is straightforward since adapters already conform to `SourceAdapter` protocol.

**Consequences:**
- Ingestion runs in the web process; heavy ingestion could theoretically compete with API requests
- Mitigation: ingestion jobs are I/O-bound (HTTP fetches), not CPU-bound; use dedicated async tasks
- If a single process becomes a bottleneck, extract scheduler into a separate worker process sharing the same DB

---

### ADR-004: SourceAdapter protocol for all ingestion

**Context:** Only one adapter exists (`edgar_agent.py`), ad hoc in structure. PRD requires 4+ adapters with consistent behavior, error handling, and audit trails.

**Decision:** Define a `SourceAdapter` Protocol (PEP 544 structural typing) that all adapters implement.

**Rationale:**
- Uniform `fetch() -> normalize() -> store` pipeline
- New sources (Shovels.ai, Planet Labs) plug in without changing pipeline code
- Protocol (not ABC) allows duck typing: adapters do not need to inherit from a base class
- Each adapter carries `source_name` and `version` for lineage tracking

**Consequences:**
- All adapters must implement `fetch()` and `normalize()` with specific return types
- Entity resolution is a shared step *after* normalization, not per-adapter
- Testing: can mock adapters trivially by implementing the protocol

---

### ADR-005: TanStack Query replaces custom useApi hook

**Context:** The custom `useApi` hook (22 lines) sets `error` state, but no tab component reads it. Users see blank screens on API failure with no indication of what went wrong.

**Decision:** Replace `useApi` with TanStack Query v5.

**Rationale:**
- Built-in retry with exponential backoff (3 retries default)
- Stale-while-revalidate: show cached data while refetching
- `isError` + `error` object surfaced to component; pair with `ErrorBoundary` for crash-resilient UI
- Devtools for debugging query state during development
- Automatic cache invalidation and garbage collection
- Much less custom code to maintain

**Consequences:**
- Every tab component is refactored from `useApi("/api/...")` to `useQuery({ queryKey: [...], queryFn: ... })`
- Need to add `<QueryClientProvider>` wrapper in `App.tsx`
- Custom `useApi` can be deleted
- Error UI components must be built (currently nonexistent)

---

### ADR-006: Entity resolution as a shared normalization step

**Context:** Company names vary across sources: "Amazon", "AWS", "Amazon / AWS", "AMZN", "Amazon Web Services". Locations vary: "Ashburn, Virginia", "Loudoun County, VA", "Northern Virginia". No canonical resolution exists.

**Decision:** Build an entity resolver as a shared service that runs between normalization and storage.

**Rationale:**
- `companies` table has `aliases` array: ["AWS", "Amazon Web Services", "AMZN"]
- Resolver does fuzzy match against aliases, returns canonical `company_id`
- `geo_hierarchy` table uses FIPS codes for counties + parent chain to state/country
- Resolver matches location strings against known geo entries
- Centralizing this avoids each adapter re-implementing company/geo matching

**Consequences:**
- Must seed `companies` and `geo_hierarchy` tables with known entities before first ingestion
- Unknown entities logged to `ingestion_runs.error_log` for manual review
- Phase 2: can add ML-based fuzzy matching if needed

---

### ADR-007: Monorepo structure with uv for dependency management

**Context:** No `requirements.txt` exists. The project is not reproducible. pip has no lockfile.

**Decision:** Use `uv` with `pyproject.toml` and `uv.lock`.

**Rationale:**
- `uv` is 10-100x faster than pip for resolution and installation
- Generates a deterministic lockfile (`uv.lock`)
- Supports Python version pinning
- Compatible with standard `pyproject.toml` (PEP 621)
- Single tool replaces pip, pip-tools, virtualenv

**Consequences:**
- All developers must install `uv` (single binary, no Python dependency)
- CI/CD uses `uv sync` instead of `pip install -r requirements.txt`
- `pyproject.toml` becomes the single source of truth for dependencies

---

## 9. Migration Path

### Step 1: Foundation (Week 1)

**Goal:** Establish project skeleton, database, and dependency management.

| Task | Detail |
|---|---|
| 1a. Add `pyproject.toml` | Pin Python 3.12+; add FastAPI, SQLAlchemy, Alembic, httpx, structlog, APScheduler, pydantic-settings, asyncpg |
| 1b. Create `backend/app/` package | New directory structure as defined in Section 4.1 |
| 1c. PostgreSQL + Alembic | Self-hosted PostgreSQL process on OCI VM (no Docker); write initial migration (`001_initial_schema.py`) with all tables from Section 3 |
| 1d. Config | `app/config.py` with `pydantic-settings` reading from `.env` (DATABASE_URL, CORS_ORIGINS, EDGAR_USER_AGENT, etc.) |
| 1e. Database module | `app/database.py`: async engine, async sessionmaker, `get_db` dependency |

**Deliverable:** `uv sync` works; `alembic upgrade head` creates all tables; FastAPI starts with `/health` returning `{"status": "ok", "db": "connected"}`.

### Step 2: Seed Data (Week 1-2)

**Goal:** Migrate curated_deals.py and satellite sites into PostgreSQL.

| Task | Detail |
|---|---|
| 2a. Seed companies | Insert canonical company records: Microsoft, Amazon, Google, Meta, Oracle, Constellation, Talen, Equinix, etc. with aliases and CIK |
| 2b. Seed geo_hierarchy | Insert country (US), states (VA, PA, TX, AZ, etc.), counties (Loudoun, Prince William, etc.) with FIPS codes |
| 2c. Seed deals | Transform `CURATED_DEALS` list -> `deals` table rows, resolving buyer/seller to `companies.id` and location to `geo_hierarchy.id` |
| 2d. Seed sites | Transform `get_satellite_sites()` return -> `sites` table rows |
| 2e. Verification | Script that compares DB row count to source data; assert 22 deals, 16 sites |

**Deliverable:** `python -m app.seed` populates database; all 22 deals and 16 sites queryable.

### Step 3: Split main.py into APIRouters (Week 2)

**Goal:** Replace monolithic `main.py` with modular routers, still returning same response shapes for frontend compatibility.

| Task | Detail |
|---|---|
| 3a. Create router files | `routers/health.py`, `power.py`, `gpu.py`, `supply_chain.py`, `permits.py`, `satellite.py`, `triangulation.py`, `sources.py` |
| 3b. Move endpoints | Each `@app.get("/api/...")` becomes `@router.get("/...")` with appropriate prefix |
| 3c. Mount routers | `app/main.py` does `app.include_router(power.router, prefix="/api/power")` etc. |
| 3d. Add Pydantic schemas | Response models for each endpoint (even if data still comes from mock functions during transition) |
| 3e. CORS fix | Replace `allow_origins=["*"]` with config-driven whitelist: `["http://localhost:5173", "http://localhost:3000"]` for dev; env var for prod |
| 3f. Backward compat | Run old and new side-by-side; frontend should not notice the change |

**Deliverable:** All 12 existing endpoints respond identically from new router structure. CORS restricted.

### Step 4: Convert EDGAR to async httpx (Week 2-3)

**Goal:** Replace `agents/edgar_agent.py` with `ingestion/edgar.py` implementing `SourceAdapter`.

| Task | Detail |
|---|---|
| 4a. Write `ingestion/base.py` | `SourceAdapter` protocol, `RawRecord`, `NormalizedRecord` dataclasses |
| 4b. Write `ingestion/edgar.py` | `EdgarAdapter` class using `httpx.AsyncClient`; structured error logging |
| 4c. Write `ingestion/normalizer.py` | Entity resolution pipeline: company_hint -> `companies.id`, geo_hint -> `geo_hierarchy.id` |
| 4d. Write ingestion pipeline | `run_adapter()` function: create run -> fetch -> dedup -> normalize -> resolve -> store -> update run |
| 4e. Wire into power router | `GET /api/power/announcements?include_edgar=true` now calls async adapter instead of sync function |
| 4f. Remove old agent | Delete `agents/edgar_agent.py` and `data/cache/` directory |

**Deliverable:** EDGAR ingestion is async, non-blocking, with structured logs and audit trail in `ingestion_runs`.

### Step 5: Add APScheduler (Week 3)

**Goal:** Automated ingestion on schedule.

| Task | Detail |
|---|---|
| 5a. Write `ingestion/scheduler.py` | Configure AsyncIOScheduler with cron triggers per Section 5.3 |
| 5b. Wire into app startup | `@app.on_event("startup")` starts scheduler; `shutdown` stops it |
| 5c. Expose run status | `GET /api/sources/ingestion-runs` queries `ingestion_runs` table |
| 5d. Manual trigger | `POST /api/sources/ingest/{adapter_name}` for on-demand runs (dev/debug) |

**Deliverable:** EDGAR adapter runs automatically on schedule. Ingestion history visible in Sources tab.

### Step 6: Wire Triangulation as Pure-Function Service (Week 3-4)

**Goal:** Replace mock triangulation data with real computation.

| Task | Detail |
|---|---|
| 6a. Write `services/triangulation.py` | Pure function per Section 6.2 |
| 6b. Write `routers/triangulation.py` | Query DB for inputs, call triangulation function, return results with source URLs |
| 6c. Add `/api/triangulation/explain/{region}` | Per-layer breakdown showing exact source URLs for each input |
| 6d. Assumption parameters | Expose assumptions (GPU power draw, PUE, utilization) as query params so UI can add sliders |
| 6e. Tests | Unit tests for triangulation function with known inputs/outputs |

**Deliverable:** Triangulation tab shows computed results from real data with source links.

### Step 7: Frontend Hardening (Week 4-5)

**Goal:** Replace custom useApi with TanStack Query; add error handling.

| Task | Detail |
|---|---|
| 7a. Install TanStack Query | `npm install @tanstack/react-query @tanstack/react-query-devtools` |
| 7b. Add QueryClientProvider | Wrap app in `<QueryClientProvider>` in `App.tsx` |
| 7c. Refactor each tab | Replace `useApi<T>(path)` with `useQuery({ queryKey: [key], queryFn: () => fetch(path) })` |
| 7d. Error states | Create `<ErrorAlert>` component; each tab renders `if (isError) return <ErrorAlert error={error} />` |
| 7e. ErrorBoundary | Add React `ErrorBoundary` wrapping tab content for unexpected crashes |
| 7f. Loading states | Add skeleton loaders instead of generic spinner |
| 7g. Google Maps proxy | Move API key to backend; create `GET /api/maps/config` that returns restricted key or tiles |
| 7h. Delete useApi.ts | Remove the old hook |

**Deliverable:** Every tab handles loading, error, and success states. No more blank screens on failure.

---

## 10. Risks & Mitigations

### 10.1 Silent Exception Swallowing

**Risk:** `edgar_agent.py` has 5 bare `except Exception` blocks that silently discard errors. The system appears healthy while data ingestion is silently failing.

**Mitigation:**
- All adapters use `structlog` with context-bound fields (adapter name, source URL, CIK)
- Errors are recorded in `ingestion_runs.error_log` (JSONB array)
- `GET /api/sources/ingestion-runs` exposes error history
- Alerting: log aggregator (Phase 2) watches for `status=failure` runs
- No bare `except Exception`; catch specific exceptions or log + re-raise

### 10.2 Blocking Sync I/O in Async Framework

**Risk:** `urllib.request.urlopen()` blocks the FastAPI event loop. A single slow EDGAR request (10-20s) blocks ALL concurrent API requests.

**Mitigation:**
- Replace with `httpx.AsyncClient` (ADR-002)
- Add per-request timeout: 20s connect, 30s read
- Circuit breaker pattern: after 3 consecutive failures to a host, back off for 5 minutes
- Ingestion runs in background tasks, not in request handlers

### 10.3 CORS Wildcard

**Risk:** `allow_origins=["*"]` allows any website to make authenticated requests to the API if auth is added later.

**Mitigation:**
- Step 3e: replace with config-driven whitelist
- Dev: `["http://localhost:5173"]`
- Prod: `["https://insights.internal.oracle.com"]` (or whatever the deployment domain is)
- Stored in `app/config.py` via `pydantic-settings`, sourced from `.env`

### 10.4 Google Maps API Key Exposure

**Risk:** `SatelliteTab.tsx` references Google Maps API key from `import.meta.env.VITE_GOOGLE_MAPS_KEY`. This key is embedded in the client-side JavaScript bundle and visible to anyone who inspects the page.

**Mitigation:**
- Phase 1: Restrict key in Google Cloud Console to specific HTTP referrers and the Maps JavaScript API only
- Phase 2: Proxy map tiles through backend (`GET /api/maps/tiles`) so key never leaves the server
- Alternative: switch to MapLibre GL (open source) + free tiles if Google Maps cost becomes a concern

### 10.5 No Dependency Lock / No requirements.txt

**Risk:** Project is not reproducible. `pip install` resolves to whatever versions are current. Different developers get different versions. No way to audit dependencies for CVEs.

**Mitigation:**
- ADR-007: adopt `uv` with `pyproject.toml` and `uv.lock`
- `uv.lock` checked into git
- CI runs `uv sync --frozen` (fails if lock is stale)
- `uv audit` in CI to check for known vulnerabilities

### 10.6 useApi Error Swallowing

**Risk:** The `useApi` hook sets `error` state, but all 9 tab components ignore it. Pattern in every tab:

```tsx
if (loading) return <Spinner />;
// error is never checked -- if API fails, data is null, component crashes or shows nothing
```

**Mitigation:**
- ADR-005: TanStack Query with explicit `isError` checks
- `<ErrorAlert>` component with retry button
- React `ErrorBoundary` as safety net
- DevTools in development for query state inspection

### 10.7 Mock Data Generating Wrong Conclusions

**Risk:** Seven of nine tabs return `random.*` data per request. Values change on every page load. Users may already be citing these numbers in strategy discussions.

**Mitigation:**
- Phase 1: Tabs backed by real data are unmarked; tabs still on mock data get a visible `[PREVIEW - SIMULATED DATA]` banner
- Implement a `data_status` field on each API response: `"real"` | `"mock"` | `"partial"`
- Frontend reads `data_status` and renders banner conditionally
- Remove `mock_data.py` entirely once all tabs are backed by DB

### 10.8 Single-Process Architecture Limits

**Risk:** APScheduler + FastAPI in one process means a heavy ingestion run competes with API request serving.

**Mitigation:**
- Phase 1 ingestion is I/O-bound (HTTP fetches with `await`), which naturally yields the event loop to API handlers
- Monitor: if p99 API latency spikes during ingestion windows, split into two processes (API + worker) sharing the same DB
- Phase 2 design allows this split without code changes (adapters are standalone async functions)

### 10.9 EDGAR Rate Limiting / Blocking

**Risk:** SEC EDGAR rate limit is 10 requests/second. Exceeding it results in IP-level temporary blocks.

**Mitigation:**
- `EdgarAdapter` uses `asyncio.Semaphore(8)` (stay under 10)
- 120ms delay between requests (`await asyncio.sleep(0.12)`)
- `User-Agent` header set to identify the tool per SEC requirements: `"Datacenter Intelligence Platform research@oracle.com"`
- If blocked, exponential backoff with jitter: 1s, 2s, 4s, 8s, max 60s

---

## 11. Target Directory Structure (Final)

```
strategic-insights-tool/
  backend/
    pyproject.toml
    uv.lock
    alembic.ini
    alembic/
      env.py
      versions/
        001_initial_schema.py
    app/
      __init__.py
      main.py                    # FastAPI app factory
      config.py                  # pydantic-settings
      database.py                # async SQLAlchemy
      dependencies.py            # get_db, etc.
      models/
        __init__.py
        company.py
        site.py
        geo.py
        deal.py
        data_point.py
        ingestion_run.py
      schemas/
        __init__.py
        common.py                # PagedResponse, SourceMeta, ErrorDetail
        power.py
        gpu.py
        supply_chain.py
        permits.py
        satellite.py
        triangulation.py
        sources.py
      routers/
        __init__.py
        health.py
        power.py
        gpu.py
        supply_chain.py
        permits.py
        satellite.py
        triangulation.py
        sources.py
      services/
        __init__.py
        triangulation.py         # pure-function engine
        entity_resolver.py
      ingestion/
        __init__.py
        base.py                  # SourceAdapter protocol
        edgar.py
        permits.py
        earnings.py
        satellite.py
        utility.py
        normalizer.py
        scheduler.py
      seed/
        __init__.py
        load_curated_deals.py
        load_satellite_sites.py
  frontend/
    package.json
    src/
      App.tsx                    # + QueryClientProvider
      hooks/
        (useApi.ts deleted)
      components/
        common/
          ErrorAlert.tsx
          ErrorBoundary.tsx
          SkeletonLoader.tsx
          DataStatusBanner.tsx   # "PREVIEW - SIMULATED DATA"
        tabs/
          PowerTab.tsx           # refactored to TanStack Query
          SatelliteTab.tsx
          GPUSupplyTab.tsx
          NICsOpticsTab.tsx
          TSMCTab.tsx
          PermitsTab.tsx
          TriangulationTab.tsx
          SourcesTab.tsx
          DataCentersTab.tsx
  docs/
    planning/
      01-prd.md
      02-codebase-survey.md
      03-architecture-design.md  # this document
```

---

## 12. Phase 2 Extension Points

The architecture is designed to accommodate Phase 2 without structural rewrites:

| Phase 2 Feature | Extension Point |
|---|---|
| Meta + OCI already full participants | Seed complete from Phase 1; adapters already handle multiple CIKs |
| NIC + optics ingestion (Coherent, Lumentum) | New `SupplyChainAdapter` implementing `SourceAdapter` protocol |
| Satellite imagery (Planet Labs) | `SatelliteAdapter` already stubbed; implement `fetch()` against Planet API |
| Expand building-permit coverage beyond the 6 free states | Add new `geo_hierarchy` entries; instantiate a Socrata-style adapter per new state; or swap in Shovels.ai national adapter (Phase 2) |
| Distributed worker | Extract `ingestion/scheduler.py` into standalone process; adapters unchanged |
| Anomaly detection (Phase 3) | New `services/anomaly.py` reads `data_points` time series; pure function like triangulation |
| Global expansion | Add countries/states to `geo_hierarchy`; no schema changes |

---

## Appendix A: Key File Mappings (Current -> Target)

| Current File | Target Location | Notes |
|---|---|---|
| `backend/main.py` | `backend/app/main.py` + `backend/app/routers/*.py` | Split into 8 router modules |
| `backend/data/mock_data.py` | Deleted (replaced by DB queries) | Mock tabs get `[PREVIEW]` banner until real data |
| `backend/data/curated_deals.py` | `backend/app/seed/load_curated_deals.py` | One-time seed into `deals` table |
| `backend/agents/edgar_agent.py` | `backend/app/ingestion/edgar.py` | Async, structured logging, protocol-compliant |
| `backend/data/cache/` | Deleted (replaced by `data_points` table) | PostgreSQL is the cache |
| `frontend/src/hooks/useApi.ts` | Deleted (replaced by TanStack Query) | Each tab uses `useQuery()` directly |

## Appendix B: Environment Variables

```env
# backend/.env
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/dcpower
CORS_ORIGINS=["http://localhost:5173"]
EDGAR_USER_AGENT=Datacenter Intelligence Platform research@oracle.com
EDGAR_RATE_LIMIT_RPS=8
LOG_LEVEL=INFO
SCHEDULER_ENABLED=true

# frontend/.env.local
VITE_API_BASE_URL=http://localhost:8000
# VITE_GOOGLE_MAPS_KEY removed in Phase 2 (proxied through backend)
```

---

## Conformance to 00-DECISIONS-AND-CONSTRAINTS.md

- **§1 Decisions 1-5:** PostgreSQL self-hosted (no Docker), EDGAR REST APIs, OCI %-share in every tab, OCI VM deploy, no auth.
- **§2 Tech Stack:** PostgreSQL + SQLModel + asyncpg + Alembic, APScheduler, httpx, rapidfuzz, TanStack Query, APIRouter+DI.
- **§3 Datasets:** Sites (73 cols), Events (957 rows), Energy Projects (1695 rows) tables defined above.
- **§4 EDGAR APIs:** Frames pass-through endpoint, all 6 endpoint patterns referenced.
- **§5 UX Rule:** New endpoints are additive. No existing endpoints removed.
- **OCI %-share:** Canonical computation defined in this document; referenced by all other docs.
