# 03 -- Pipeline Architecture: Data-Source Ingestion System

**Author:** System Architect | **Date:** 2026-04-28 | **Status:** Draft v1.0
**Depends on:** [../../PRD.md](../../PRD.md), [00-DECISIONS-AND-CONSTRAINTS.md](00-DECISIONS-AND-CONSTRAINTS.md), [02-TECH-STACK-RESEARCH.md](02-TECH-STACK-RESEARCH.md). (The earlier `01-DATA-PIPELINE-PRD.md` has been archived under `docs/_archive/`; its content is folded into `PRD.md`.)

---

## 1. System Architecture Overview

### 1.1 High-Level Data Flow

```mermaid
graph TB
    subgraph External Sources
        EDGAR[SEC EDGAR API]
        SHOVELS[Shovels.ai / VA Open Data]
        FMP[Financial Modeling Prep]
        ATERIO[Aterio Excel Files]
        SENTINEL[Sentinel-2 / Earth Engine]
    end

    subgraph Scheduler
        APS[APScheduler AsyncIOScheduler]
    end

    subgraph Ingestion Layer
        A1[EDGAR Adapter]
        A2[Permits Adapter]
        A3[Transcript Adapter]
        A4[Aterio Adapter]
        A5[Satellite Adapter]
    end

    subgraph Processing Pipeline
        FETCH[fetch - RawPayload]
        PARSE[parse - NormalizedRecord list]
        VALIDATE[validate - ValidationResult]
        RESOLVE[resolve_entities - Canonical IDs]
    end

    subgraph Storage Layer
        PG[(PostgreSQL)]
        BLOB[Raw Artifact Store<br/>filesystem / OCI Object Storage]
    end

    subgraph API Layer
        FASTAPI[FastAPI Endpoints]
        TRIANG[Triangulation Engine]
    end

    subgraph Frontend
        REACT[React Dashboard]
    end

    APS -->|triggers on schedule| A1
    APS -->|triggers on schedule| A2
    APS -->|triggers on demand| A3
    APS -->|triggers on file drop| A4
    APS -->|triggers on schedule| A5

    EDGAR --> A1
    SHOVELS --> A2
    FMP --> A3
    ATERIO --> A4
    SENTINEL --> A5

    A1 --> FETCH --> PARSE --> VALIDATE --> RESOLVE
    A2 --> FETCH
    A3 --> FETCH
    A4 --> FETCH
    A5 --> FETCH

    RESOLVE -->|normalized records| PG
    FETCH -->|raw bytes| BLOB
    BLOB -->|raw_blob_ref| PG

    PG --> TRIANG
    PG --> FASTAPI
    TRIANG --> FASTAPI
    FASTAPI --> REACT
```

### 1.2 ASCII Overview (for terminals without Mermaid rendering)

```
  EXTERNAL SOURCES                 SCHEDULER            INGESTION ADAPTERS
  +--------------+              +-------------+       +-------------------+
  | SEC EDGAR    |---+          | APScheduler |------>| EDGAR Adapter     |
  | Shovels.ai   |---+         | AsyncIO     |------>| Permits Adapter   |
  | FMP API      |---+-------->| Scheduler   |------>| Transcript Adapter|
  | Aterio .xlsx |---+         |             |------>| Aterio Adapter    |
  | Sentinel-2   |---+         +-------------+       | Satellite Adapter |
  +--------------+                                    +--------+----------+
                                                               |
                              PROCESSING PIPELINE              |
                    +------------------------------------------v-------+
                    |  fetch() --> parse() --> validate() --> resolve() |
                    +------------------------------------------+-------+
                                                               |
                         STORAGE                               |
            +-------------------+    +------------------+      |
            | Raw Artifact      |<---|  raw bytes       |<-----+
            | Store (FS / OCI)  |    +------------------+      |
            +-------------------+                              |
                      |                                        v
                      |  raw_blob_ref         +----------------+-------+
                      +---------------------->|   PostgreSQL           |
                                              |   - companies          |
                                              |   - filings            |
                                              |   - permits            |
                                              |   - transcript_metrics |
                                              |   - satellite_obs      |
                                              |   - curated_deals      |
                                              |   - data_lineage       |
                                              |   - ingestion_runs     |
                                              +----------------+-------+
                                                               |
                      API LAYER                                |
                    +------------------------------------------v-------+
                    |  FastAPI                                         |
                    |  +------------------+  +----------------------+  |
                    |  | REST Endpoints   |  | Triangulation Engine |  |
                    |  | /api/power/*     |  | L1: Contracted GW    |  |
                    |  | /api/permits/*   |  | L2: GPU Power Draw   |  |
                    |  | /api/gpu/*       |  | L3: NICs/Optics      |  |
                    |  | /api/pipeline/*  |  | L4: Permits          |  |
                    |  +------------------+  +----------------------+  |
                    +------------------------------------------+-------+
                                                               |
                      FRONTEND                                 |
                    +------------------------------------------v-------+
                    |  React Dashboard                                 |
                    |  Power | Permits | GPU | Triangulation | Sources  |
                    +--------------------------------------------------+
```

### 1.3 Scheduler Configuration

| Job ID | Adapter / Agent | Schedule | Trigger Type | Phase |
|--------|---------|----------|-------------|-------|
| `edgar_daily` | EDGAR (deterministic fetch) → Llama Stack 8-K extractor | `0 6 * * *` (daily 06:00 ET) | Cron | 1 |
| `permits_weekly` | Permits (6 free state APIs) | `0 7 * * 1` (Monday 07:00 ET) | Cron | 1 |
| `permits_air_weekly` | EPA ECHO + state air APIs | `0 8 * * 1` (Monday 08:00 ET) | Cron | 1.5 |
| `permit_pdf_extract` | Llama Stack vision agent (PDF→fields) | Triggered after each `permits_air_weekly` run | Event | 1.5 |
| `llc_resolve_weekly` | Llama Stack LLC→parent agent | `0 9 * * 1` (Monday 09:00 ET) — runs after permit jobs settle | Cron | 1.5 |
| `transcript_ondemand` | Transcript (free IR scrape) → Llama Stack metric extractor | Manual / API trigger | Date | 1 |
| `aterio_manual` | Aterio | On file drop (watchdog or API) | Event | 1 |
| `weekly_brief` | Llama Stack Weekly Brief agent | `0 23 * * 0` (Sunday 23:00 ET) | Cron | 1 |
| `satellite_weekly` | Satellite | `0 6 * * 3` (Wednesday 06:00 ET) | Cron | 2 |
| `coverage_refresh` | Internal — refresh `data_coverage` rollups | `0 */1 * * *` (hourly) | Cron | 1 |
| `cache_cleanup` | Internal | `0 0 * * *` (midnight) | Cron | 1 |
| `stale_check` | Internal | `0 */4 * * *` (every 4h) | Cron | 1 |

APScheduler runs as `AsyncIOScheduler` inside the FastAPI process. Job persistence is backed by PostgreSQL via SQLAlchemy so missed runs are detected and re-triggered on process restart.

---

## 2. Source-Agnostic Ingestion Adapter Contract

### 2.1 Abstract Interface

Every data source adapter MUST implement this interface. The pipeline orchestrator calls these methods in sequence for each ingestion run.

```
Interface: DataSourceAdapter

    Properties:
        adapter_name: str           # Human-readable, e.g. "SEC EDGAR 8-K"
        adapter_id: str             # Machine identifier, e.g. "sec_edgar_8k"
        adapter_version: str        # Semantic version, e.g. "1.0.0"
        schedule: ScheduleConfig    # Cron expression or event trigger

    Methods:
        fetch(params: FetchParams) -> RawPayload
            Retrieves raw data from the external source.
            MUST NOT silently swallow exceptions.
            MUST raise: SourceUnavailableError, RateLimitError, or FetchError.
            Returns: raw bytes/text + metadata (content_type, source_url, retrieved_at, size_bytes).

        parse(raw: RawPayload) -> list[NormalizedRecord]
            Transforms raw data into typed records.
            Partial results are acceptable: return what parses, log what fails.
            Each record carries all lineage fields.

        validate(records: list[NormalizedRecord]) -> ValidationResult
            Schema compliance + business rule checks.
            Returns: pass/fail, list of issues, per-record confidence adjustments.
            Does NOT discard records; flags them.

        resolve_entities(records: list[NormalizedRecord]) -> list[NormalizedRecord]
            Maps raw names to canonical company/site/geo IDs.
            Uses rapidfuzz against company_aliases table (threshold >= 85).
            Uses US Census Geocoder for address-to-FIPS resolution.
            Unresolved entities: set canonical_*_id = null, flag for manual review.
```

### 2.2 Supporting Types

```
ScheduleConfig:
    type: "cron" | "event" | "manual"
    expression: str | null          # Cron expression if type = "cron"
    trigger: str | null             # Event name if type = "event"

FetchParams:
    date_range: (date, date)        # Start and end dates
    entity_filter: list[str] | null # CIK list, ticker list, FIPS codes, etc.
    geography_filter: GeoFilter | null

GeoFilter:
    state: str | null
    county_fips: list[str] | null
    bounding_box: (float, float, float, float) | null  # (min_lat, min_lon, max_lat, max_lon)

RawPayload:
    content: bytes
    content_type: str               # "text/html", "application/json", "application/xlsx"
    source_url: str
    retrieved_at: datetime           # UTC
    size_bytes: int
    headers: dict[str, str] | null   # HTTP response headers if applicable

ValidationResult:
    passed: bool
    total_records: int
    valid_records: int
    issues: list[ValidationIssue]

ValidationIssue:
    record_id: str
    field: str
    severity: "error" | "warning"
    message: str
    confidence_adjustment: float    # e.g. -0.1 for a missing required field
```

### 2.3 NormalizedRecord Base Schema

All source-specific records extend this base. These fields are required on EVERY record entering the system.

```
NormalizedRecord:
    record_id: str (UUID v4)
    source_id: str                  # Adapter's adapter_id
    source_url: str                 # Direct link to primary source document
    retrieved_at: datetime (UTC)    # When the data was fetched from the source
    parser_version: str             # Semantic version of the adapter that produced this record
    raw_blob_ref: str               # Path to stored raw artifact (e.g. "raw/edgar/2026/04/28/{accession}.html")
    confidence: float (0.0 - 1.0)  # Computed from parsing certainty, NEVER random
    confidence_rationale: str       # Human-readable explanation, e.g. "MW regex matched + counterparty identified"
    canonical_company_id: str | null    # FK to companies.id; null if unresolved
    canonical_site_id: str | null       # FK to sites.id; null if not site-specific
    canonical_geo_id: str | null        # FIPS code (e.g. "51107" for Loudoun County)
    effective_date: date            # When this data applies (filing date, permit date, etc.)
    ingested_at: datetime (UTC)     # When this record was written to our store
    record_type: str                # "filing" | "permit" | "transcript_metric" | "dataset_row" | "satellite_observation"
    data_state: str                 # See Section 6: Data State Machine
```

### 2.4 Error Handling Contract

Adapters MUST adhere to these rules:

1. **No bare `except Exception`**: Every exception handler must catch a specific type. The minimum specificity is `except (httpx.HTTPStatusError, httpx.TimeoutException) as e:`.
2. **Structured logging**: Every caught exception is logged with: `adapter_id`, `operation` (fetch/parse/validate/resolve), `error_class`, `error_message`, `partial_context` (e.g., CIK being processed).
3. **Retryable vs terminal**: Transient errors (network timeout, 429, 5xx) raise `RetryableError`. Parse failures raise `ParseError`. Both are logged; only `RetryableError` triggers retry.
4. **Retry policy**: Exponential backoff: 1s, 2s, 4s. Max 3 retries. Configurable per adapter.
5. **Partial results**: A batch of 10 filings where 2 fail to parse returns 8 records + 2 logged errors. Never return an empty list when partial data was available.

---

## 3. Per-Source Adapter Specifications

### 3a. SEC EDGAR Adapter (with Llama Stack 8-K extractor)

**Replaces:** `backend/agents/edgar_agent.py` (current implementation has 5 silent `except Exception` blocks, blocking sync I/O, hardcoded confidence, **regex-based MW extraction that misses ~30% of varied 8-K phrasings**).

The adapter now runs in two stages:
1. **Fetch** (deterministic): `edgartools` + `httpx.AsyncClient` + EFTS API to discover filings and download item-1.01 narrative.
2. **Extract** (Llama Stack agent A — `00-DECISIONS-AND-CONSTRAINTS.md` §4.2): single-turn structured extraction via `oci/openai.gpt-5.4-mini` with strict JSON schema. Replaces regex. Output handles "approximately 1.2 GW" / "200 MW with optional 50 MW" / table-of-contracts patterns that regex couldn't.

```
Adapter ID:       sec_edgar
Adapter Version:  3.0.0
Schedule:         cron "0 */6 * * *" (every 6 hours)
Libraries:        edgartools, httpx.AsyncClient, EFTS API, backend.llm.agents.edgar_extractor
LLM model:        oci/openai.gpt-5.4-mini  (fallback: backend.llm.fallback.edgar_regex)
LLM cache:        llm_extraction_runs.UNIQUE (agent_name, input_hash) — re-ingesting same accession = cache hit
```

**Input:**
- CIK list from `ENERGY_COMPANIES` + `HYPERSCALERS` config (not hardcoded in adapter)
- Form types: 8-K (item 1.01), 10-K, 10-Q
- Date range: `since` parameter (default: 2023-01-01 for backfill, last_run for incremental)

**Output Schema -- `EdgarFilingRecord(NormalizedRecord)`:**

```
EdgarFilingRecord extends NormalizedRecord:
    cik: str
    company_name: str               # Raw name from EDGAR
    form_type: str                  # "8-K" | "10-K" | "10-Q"
    filing_date: date
    accession_number: str
    edgar_url: str                  # Direct link to filing document on SEC
    item_codes: list[str]           # e.g. ["1.01"] for material agreements
    capacity_mw: int | null         # Extracted power figure
    energy_contract_mwh: float | null  # For Amazon-style MWh disclosures
    energy_source: str | null       # "nuclear" | "solar" | "wind" | "gas" | "mixed" | null
    buyer: str | null               # Identified buyer (hyperscaler)
    seller: str | null              # Identified seller (energy company)
    excerpt: str                    # Relevant text passage (max 1000 chars)
    keywords_matched: list[str]     # Which extraction keywords matched
```

**Confidence Calculation (deterministic, not random):**

```
base = 0.50   # Filing found and retrieved
+0.20         if capacity_mw regex matched an explicit MW/GW figure
+0.15         if buyer or seller (counterparty) identified in text
+0.10         if energy_source classified (nuclear, solar, wind, gas)
+0.05         if 2+ corroborating keywords found (e.g. "data center" + "power purchase")
cap at 0.99

Examples:
  MW matched + counterparty + energy source + keywords = 0.50 + 0.20 + 0.15 + 0.10 + 0.05 = 0.99 (capped)
  MW matched + no counterparty + no source              = 0.50 + 0.20 = 0.70
  Filing found, keyword-only match, no MW extracted     = 0.50 + 0.05 = 0.55
  Filing found, HTML parse yielded < 100 chars          = 0.10 (degraded base)
```

**Error Handling:**

| Failure | Detection | Response |
|---------|-----------|----------|
| EDGAR 429 (rate limit) | HTTP status | Backoff: 1s, 2s, 4s. Max 3 retries. Log warning. |
| EDGAR 5xx | HTTP status | Retry 3x with 10s backoff. After 3 failures, mark adapter degraded. |
| Network timeout (>20s) | httpx.TimeoutException | Retry 2x. Serve stale cache if available, flagged as stale. |
| Regex MW extraction fails | `_parse_mw_from_text` returns None | Record filing with `capacity_mw: null`, `confidence: 0.50`. Log the attempted text. |
| HTML parse yields <100 chars | Length check | Log as parse failure. Store raw blob. Set `confidence: 0.10`. |
| edgartools internal error | Wrapped in `asyncio.to_thread` | Catch, log with full stack trace, skip filing, continue batch. |

**Cache:** PostgreSQL-backed with configurable TTL (default 12 hours). Cache key: `(cik, form_type, accession_number)`. Force-refresh via API parameter. Cache versioned by `parser_version` -- parser upgrade invalidates cache.

**Rate Limiting:** Shared semaphore across all SEC API calls (edgartools + direct EFTS). Token bucket: 8 req/s (below SEC's 10 req/s limit to leave headroom).

**Backfill:** One-time batch job: all 8-K filings with item 1.01 from 2023-01-01 to present for all configured companies. Throttled at 8 req/s. Estimated: 200-400 filings. Runs as a management command, not via scheduler.

---

### 3b. County Permits Adapter

**Replaces:** `get_permits_data()` in `mock_data.py` (currently returns entirely random data with fake URLs).

```
Adapter ID:       county_permits
Adapter Version:  1.0.0
Schedule:         cron "0 7 * * 1" (weekly Monday 07:00 ET)
Libraries:        httpx.AsyncClient (Shovels API), pandas (CSV fallback)
Primary:          Shovels.ai API
Fallback:         Virginia Open Data Portal CSV
```

**Input:**
- FIPS county codes: `["51107", "51153"]` (Phase 1: Loudoun, Prince William)
- Date range: start (default 2023-01-01), end (today)
- Permit type filter: `["commercial construction", "electrical", "grading"]`

**Output Schema -- `PermitRecord(NormalizedRecord)`:**

```
PermitRecord extends NormalizedRecord:
    permit_id: str                  # County-issued permit number
    county_fips: str                # e.g. "51107"
    county_name: str                # e.g. "Loudoun County"
    state: str                      # "VA"
    applicant_name: str             # Raw name from permit (e.g. "Vadata Inc")
    permit_type: str                # "Construction" | "Electrical" | "Grading" | "Mechanical"
    filed_date: date
    status: str                     # "Approved" | "Pending" | "Under Review" | "Completed" | "Denied"
    estimated_sqft: int | null
    estimated_mw: float | null      # If available from permit details
    description: str                # Raw description text from permit
    address: str | null
    lat: float | null
    lon: float | null
    is_datacenter: bool             # Classification result
    classification_method: str      # "keyword_rule" (Phase 1) or "ml_classifier" (Phase 2)
```

**Datacenter Classification (Phase 1 -- keyword rules):**

```
is_datacenter = TRUE if ANY of:
  - permit_type IN ("commercial construction", "electrical", "grading")
    AND (estimated_sqft > 50,000 OR description contains "data center")
  - applicant_name matches a known datacenter company alias
  - description contains ANY of: "data center", "datacenter", "server farm",
    "colocation", "colo facility", "cloud infrastructure", "technology campus"

confidence for classification:
  - Known company alias match:     0.95
  - description explicit match:    0.85
  - sqft-only heuristic:           0.60
```

**Entity Resolution -- Known Aliases (Phase 1 seed):**

| Alias | Canonical Company | Source |
|-------|------------------|--------|
| Vadata Inc | Amazon / AWS | VA SCC registration |
| Vadata | Amazon / AWS | Permit shorthand |
| Cloverleaf Infrastructure | Microsoft | VA SCC registration |
| Loudoun Heights LLC | Google | News reports |
| Bowman Development | Google | Permit filings |
| QTS Realty | QTS / Blackstone | Corporate name |
| DuPont Fabros / Digital Realty | Digital Realty | Post-merger |

**Failure Handling:**

| Failure | Response |
|---------|----------|
| Shovels API unavailable (5xx, timeout) | Retry 3x with 30s backoff. If down >24h, activate VA Open Data CSV fallback. |
| Shovels 429 | Backoff per Shovels API docs. |
| VA Open Data CSV format changes | Schema validation on headers. Reject + alert if mismatch. |
| Applicant name unresolved | Store record with `canonical_company_id: null`. Add to manual review queue. |
| Classification uncertain (is_datacenter confidence < 0.6) | Store with `is_datacenter: false`. Surface for review. |

---

### 3c. Earnings Transcript Adapter

**Replaces:** `get_gpu_data()`, `get_nics_optics_data()`, `get_tsmc_data()` in `mock_data.py`.

```
Adapter ID:       earnings_transcripts
Adapter Version:  1.0.0
Schedule:         Manual / API trigger (event-driven, ~20 events/year)
Libraries:        httpx.AsyncClient (free IR scraping; FMP deferred), backend.llm.agents.transcript_extractor (Llama Stack)
```

**Input:**
- Ticker list: `["NVDA", "TSM"]` (Phase 1); `["AVGO", "COHR", "LITE"]` (Phase 2)
- Quarter identifier: e.g. `"FY2026-Q1"`
- Filing type: `"10-Q"` | `"earnings_transcript"`

**Output Schema -- `TranscriptMetricRecord(NormalizedRecord)`:**

```
TranscriptMetricRecord extends NormalizedRecord:
    company_name: str
    ticker: str
    fiscal_quarter: str             # e.g. "FY2026-Q1"
    filing_type: str                # "10-Q" | "earnings_transcript"
    metric_name: str                # e.g. "datacenter_revenue_b"
    metric_value: float
    unit: str                       # "USD_B", "units_K", "wafers", "pct"
    is_derived: bool                # True if computed from raw data (e.g. GPU units from revenue / ASP)
    derivation_assumptions: dict | null  # e.g. {"h100_asp_usd": 25000, "utilization_pct": 0.75}
    speaker: str | null             # For transcript: who said it (CEO, CFO)
    context_excerpt: str            # Source text passage (max 500 chars)
    transcript_url: str | null      # Direct link to transcript if from FMP
```

**Target Metrics by Company:**

| Company | Metric Name | Unit | Source | Phase |
|---------|------------|------|--------|-------|
| NVIDIA | `datacenter_revenue_b` | USD_B | 10-Q / transcript | 1 |
| NVIDIA | `gpu_units_shipped_k` | units_K | **derived** (revenue / ASP) | 1 |
| NVIDIA | `datacenter_segment_growth_pct` | pct | 10-Q | 1 |
| NVIDIA | `forward_guidance_b` | USD_B | transcript | 1 |
| TSMC | `revenue_b` | USD_B | 10-Q / 6-K | 1 |
| TSMC | `cowos_monthly_capacity` | wafers | transcript | 1 |
| TSMC | `advanced_node_utilization_pct` | pct | transcript | 1 |
| TSMC | `capex_b` | USD_B | 10-Q | 1 |
| Broadcom | `networking_revenue_b` | USD_B | 10-Q | 2 |
| Broadcom | `nic_shipments_k` | units_K | **derived** | 2 |
| Coherent | `optics_400g_units_k` | units_K | transcript | 2 |
| Coherent | `optics_800g_units_k` | units_K | transcript | 2 |
| Lumentum | `optical_transceiver_revenue_m` | USD_M | 10-Q | 2 |

**LLM Extraction Approach:**

The adapter sends transcript text to OCI Llama Stack (`oci/openai.gpt-5.4-mini` primary, `oci/google.gemini-2.5-flash` fallback per `00-DECISIONS-AND-CONSTRAINTS.md` §4.2) with a structured extraction prompt. The prompt specifies the exact metrics to find and requires JSON output with `value`, `unit`, `excerpt`, and `confidence` per metric. The extraction prompt is versioned in `backend/llm/prompts/transcript_extractor.v{N}.txt` (tracked in `parser_version` and `llm_extraction_runs.prompt_version`) so changes to the prompt invalidate cached results.

**Confidence Calculation:**

```
For 10-Q XBRL data:   0.95 (machine-readable, authoritative)
For transcript LLM extraction:
  - Exact number stated by speaker:  0.85
  - Range given (e.g. "$12-13B"):    0.75 (midpoint used, range stored)
  - Derived metric (e.g. GPU units): 0.65 (assumptions compound uncertainty)
  - Metric not found in text:        0.00 (metric_value = null, explicit no-data)
```

**TSMC Note:** TSMC files as a foreign private issuer using 20-F (annual) and 6-K (current reports), not 10-K/10-Q. The adapter handles both XBRL taxonomies. FMP transcripts are the primary source for TSMC operational metrics (CoWoS capacity, utilization).

---

### 3d. Aterio Dataset Adapter

```
Adapter ID:       aterio_dataset
Adapter Version:  1.0.0
Schedule:         Manual (triggered on file drop or API call)
Libraries:        openpyxl or pandas
```

**Input:**
- File path to `.xlsx` file in `datasets/` directory
- Sheet name (optional; defaults to first sheet)

**Output Schema -- `AterioSiteRecord(NormalizedRecord)`:**

```
AterioSiteRecord extends NormalizedRecord:
    aterio_site_id: str             # Aterio's internal site identifier
    site_name: str
    company_name: str               # Raw company name from Aterio
    address: str | null
    county: str | null
    state: str | null
    country: str
    lat: float
    lon: float
    capacity_mw: float | null
    status: str                     # "Operational" | "Under Construction" | "Planned"
    year_opened: int | null
    total_sqft: int | null
```

**Schema Validation:**

On ingest, the adapter validates Excel column headers against an expected schema. If column names have changed (Aterio updates their format), the adapter rejects the file with a structured error listing expected vs. actual headers.

**Deduplication:**

Aterio sites may overlap with `curated_deals`. Deduplication logic:
1. Match on `(lat, lon)` within 0.01 degree AND same `canonical_company_id`.
2. If match found: prefer `curated_deals` data (higher confidence). Supplement with Aterio fields not present in curated_deals (e.g., `total_sqft`, `year_opened`).
3. Merged records carry `source_id: "aterio_dataset+curated_deals"`.

**Geo Resolution:**

Aterio provides lat/lon. The adapter reverse-geocodes to county/state/FIPS using the US Census TIGERweb API (`censusgeocode` library).

**Confidence:**

```
base = 0.70   # Third-party dataset, not primary source
+0.10         if all required fields (lat, lon, capacity_mw, company) populated
+0.10         if company resolved to canonical ID
+0.05         if county/state resolved via geocoding
cap at 0.90   # Never exceeds primary source (SEC filing) confidence
```

---

### 3e. Satellite Imagery Adapter

```
Adapter ID:       satellite_imagery
Adapter Version:  0.1.0  (Phase 2; Phase 1 uses curated metadata only)
Schedule:         cron "0 6 * * 3" (weekly Wednesday, Phase 2)
Libraries:        earthengine-api (Google Earth Engine), httpx
```

**Phase 1 Behavior:** The adapter wraps the existing `get_satellite_sites()` curated metadata from `mock_data.py` (which contains real, hand-verified site data). It emits `SatelliteObservation` records with `data_state: "curated_metadata_only"` and `confidence_rationale: "Site coordinates and milestones from public sources; no imagery analysis"`. The UI displays "Site metadata only -- satellite imagery coming in Phase 2."

**Phase 2 Input:**
- List of site coordinates from `sites` table
- Bounding box: 1 km around each site center
- Date range for change detection (compare latest vs. 3 months prior)

**Output Schema -- `SatelliteObservation(NormalizedRecord)`:**

```
SatelliteObservation extends NormalizedRecord:
    site_name: str
    observation_date: date
    image_ref: str                  # Path to stored GeoTIFF or PNG
    thumbnail_ref: str              # Path to UI-displayable thumbnail
    resolution_m: float             # 10.0 for Sentinel-2
    cloud_cover_pct: float
    change_detected: bool
    change_type: str | null         # "new_clearing" | "foundation" | "structure_rising" | "no_change"
    change_confidence: float        # 0.0-1.0 for change detection result
    construction_activity_score: float  # 0.0-1.0 composite
    area_cleared_sqm: float | null
    structures_detected: int | null
```

---

## 4. Database Schema Design

### 4.1 Entity-Relationship Diagram

```mermaid
erDiagram
    companies ||--o{ company_aliases : "has many"
    companies ||--o{ sites : "operates"
    companies ||--o{ filings : "filed by"
    companies ||--o{ permits : "attributed to"
    companies ||--o{ transcript_metrics : "reported by"
    companies ||--o{ curated_deals : "buyer or seller"

    sites ||--o{ satellite_observations : "observed at"
    sites ||--o{ permits : "located at"

    ingestion_runs ||--o{ data_lineage : "produced"
    raw_artifacts ||--o{ data_lineage : "stores blob for"

    companies {
        uuid id PK
        string name "Canonical name"
        string cik "SEC CIK if public"
        string ticker "Stock ticker"
        string company_type "hyperscaler | energy | infrastructure | semiconductor"
        jsonb metadata "Additional attributes"
        timestamp created_at
        timestamp updated_at
    }

    company_aliases {
        uuid id PK
        uuid company_id FK
        string alias_text "e.g. Vadata Inc"
        string source_context "e.g. VA SCC, permit filing"
        string match_type "exact | fuzzy"
        int fuzzy_threshold "Minimum rapidfuzz score"
        timestamp created_at
    }

    sites {
        uuid id PK
        uuid company_id FK
        string site_name
        string address
        string county
        string state
        string country
        string county_fips "e.g. 51107"
        float lat
        float lon
        float capacity_mw
        string status "Operational | Under Construction | Planned | Land Prep"
        int size_acres
        jsonb milestones "Array of milestone objects"
        timestamp created_at
        timestamp updated_at
    }

    filings {
        uuid id PK
        uuid company_id FK
        string cik
        string form_type
        date filing_date
        string accession_number UK
        string edgar_url
        string item_codes "Comma-separated"
        int capacity_mw
        float energy_contract_mwh
        string energy_source
        string buyer
        string seller
        text excerpt
        list keywords_matched
        string source_url
        float confidence
        string confidence_rationale
        string parser_version
        string raw_blob_ref
        timestamp retrieved_at
        timestamp ingested_at
        string data_state
    }

    permits {
        uuid id PK
        uuid company_id FK
        uuid site_id FK
        string permit_id UK
        string county_fips
        string county_name
        string state
        string applicant_name
        string permit_type
        date filed_date
        string status
        int estimated_sqft
        float estimated_mw
        text description
        string address
        float lat
        float lon
        bool is_datacenter
        string classification_method
        string source_url
        float confidence
        string confidence_rationale
        string parser_version
        string raw_blob_ref
        timestamp retrieved_at
        timestamp ingested_at
        string data_state
    }

    transcript_metrics {
        uuid id PK
        uuid company_id FK
        string ticker
        string fiscal_quarter
        string filing_type
        string metric_name
        float metric_value
        string unit
        bool is_derived
        jsonb derivation_assumptions
        string speaker
        text context_excerpt
        string transcript_url
        string source_url
        float confidence
        string confidence_rationale
        string parser_version
        string raw_blob_ref
        timestamp retrieved_at
        timestamp ingested_at
        string data_state
    }

    satellite_observations {
        uuid id PK
        uuid site_id FK
        date observation_date
        string image_ref
        string thumbnail_ref
        float resolution_m
        float cloud_cover_pct
        bool change_detected
        string change_type
        float change_confidence
        float construction_activity_score
        float area_cleared_sqm
        int structures_detected
        string source_url
        float confidence
        string parser_version
        string raw_blob_ref
        timestamp retrieved_at
        timestamp ingested_at
        string data_state
    }

    curated_deals {
        uuid id PK
        string deal_id UK "e.g. msft-ceg-tmi-2023"
        uuid buyer_company_id FK
        uuid seller_company_id FK
        string deal_type
        string energy_source
        int capacity_mw
        string location
        string state
        float lat
        float lon
        date announced_date
        string status
        int duration_years
        string headline
        text excerpt
        string source_type
        string source_url
        string edgar_url
        float confidence
        string data_source
        timestamp ingested_at
        string data_state
    }

    data_lineage {
        uuid id PK
        uuid source_record_id "FK to any source table"
        string source_table "filings | permits | transcript_metrics | ..."
        string source_id "Adapter ID"
        string source_url
        timestamp retrieved_at
        string parser_version
        string raw_blob_ref
        float confidence
        string confidence_rationale
        uuid ingestion_run_id FK
        timestamp created_at
    }

    ingestion_runs {
        uuid id PK
        string adapter_id
        string adapter_version
        timestamp started_at
        timestamp completed_at
        string status "running | completed | failed | partial"
        int records_fetched
        int records_parsed
        int records_validated
        int records_stored
        int errors_count
        jsonb error_details "Array of structured error objects"
        jsonb params "FetchParams used"
        timestamp next_scheduled_run
    }

    raw_artifacts {
        uuid id PK
        string blob_ref UK "Path: raw/{source}/{date}/{filename}"
        string content_type
        int size_bytes
        string storage_backend "filesystem | oci_object_storage"
        string checksum_sha256
        timestamp created_at
        timestamp expires_at "Retention policy"
    }
```

### Aterio Dataset Tables (§3 of 00-DECISIONS-AND-CONSTRAINTS.md)

#### `sites` — Canonical Datacenter Inventory (§3.1)

Seeded from `data_center_inventory_20260428.csv` (73 columns). Primary key: `aterio_dc_uid` (from `ATERIO_DATA_CENTER_UID`).

Key columns: `building_name`, `campus_name`, `stage` (Announcement/Construction/Activated/Cancelled/Withdrawn), `pct_construction`, `provider_name`, `provider_ticker`, `end_user_companies`, `full_address`, `county_fips`, `state_code`, `latitude`, `longitude`, `power_capacity_mw` (from `SELECTED_POWER_CAPACITY_MW`), `aterio_est_mw` + `_lower` + `_upper`, `is_ai_facility`, `utility_name`, `bal_auth_name`, `datasheet_url`, `map_url`, `permit_url`, `record_created_at`, `record_updated_at`.

This table replaces `curated_deals.py` as the primary site data source while keeping curated deals as a hand-verified overlay.

#### `events` — Site Events Timeline (§3.3)

Sourced from Data Centers Events sheet (957 rows × 48 cols). Foreign key: `aterio_dc_uid` → `sites`.

Columns: `event_id` (PK), `aterio_dc_uid` (FK), `event_type` (announcement/permit_filed/construction_start/activation/expansion/cancellation), `event_date`, `event_description`, `source_url`, `created_at`, `updated_at`.

#### `energy_projects` — Energy Supply (§3.4)

Sourced from `Energy Project Inventory Data Sample.xlsx` (1695 rows × 65 cols).

Columns: `energy_project_id` (PK), `project_name`, `flg_btm_project`, `developer_companies`, `developer_ticker`, `eia_entity_ids` (TEXT[]), `customer_companies`, `tot_contracted_power_mw`, `tot_project_cost`, `project_footprint_acreage`, `payload` (JSONB for remaining columns), `created_at`, `updated_at`.

Joinable to sites via developer/customer company linkage and EIA entity IDs.

#### `site_aliases` — bridge from external source IDs to canonical sites

Maps external site identifiers (EPA FRS_ID, county permit IDs, ECHO facility IDs) to a canonical `sites.id`. Created when an adapter joins a new source record to an existing site (lat/lon within 100 m, parcel match, normalized address) or creates a new site if no match exists. See full schema in [`03-architecture-design.md`](03-architecture-design.md#site-aliases-bridge).

Columns: `id` (PK), `site_id` (FK → sites), `source` (`epa_echo`, `tceq`, `loudoun_county`, …), `source_record_id`, `match_method` (`aterio_uid` / `latlon_within_100m` / `parcel_apn` / `address_normalized` / `manual`), `confidence` NUMERIC(3,2), `created_at`. UNIQUE (`source`, `source_record_id`).

#### `site_company_associations` — role edges (many-to-many with role)

The driving table for OCI %-share, the Companies tab, and the Site detail role-breakdown card. Same company can fill multiple roles on one site (e.g. `provider` + `end_user` for a self-built Azure region) — one row per (site, company, role, source) tuple. See full schema and population rules in [`03-architecture-design.md`](03-architecture-design.md#site--company-associations-role-edges).

Roles per `00-DECISIONS-AND-CONSTRAINTS.md` §5.1: `provider`, `provider_backer`, `end_user`, `financing`, `equipment`, `utility`, `developer`, `customer`, `permittee_llc`, `permit_parent`.

Adapters populate this table:
- **AterioAdapter** writes `provider`, `provider_backer`, `end_user` (split on comma), `financing` (split), `equipment` (split), `utility`.
- **AterioEnergyAdapter** writes `developer` (split), `customer` (split).
- **EpaEchoAdapter** writes `permittee_llc`.
- **LlcResolverAdapter** (see §8 below) writes `permit_parent` after running the multi-signal scorer.

#### `data_coverage` — per-pillar per-state coverage truth (national MVP)

Drives the `<CoverageBadge />` UI components and per-state empty states. Schema, status enum, and seed values defined in [`03-architecture-design.md`](03-architecture-design.md#data-coverage-table-national-mvp-coverage-truth).

**Adapter contract obligation:** every adapter, at end-of-run, MUST upsert one row per (pillar, state_code, source) into `data_coverage` with current `coverage_status`, `record_count`, `last_ingested_at`. This is part of the standard `IngestionResult` lifecycle — adapters that don't write coverage rows are considered broken.

```python
# Sketch — added to the DataSourceAdapter base
class DataSourceAdapter(Protocol):
    pillar: str                          # 'building_permits' | 'generator_permits' | ...
    coverage_scope: list[str]            # state codes covered by this adapter, e.g. ['VA'], ['US'], ['GLOBAL']
    declared_status: str                 # 'full' | 'partial' | 'federal_baseline' | 'pending' | 'unavailable'

    async def fetch(...) -> list[NormalizedRecord]: ...

    async def write_coverage(self, db, run_result):
        for state_code in self.coverage_scope:
            count = run_result.records_for_state(state_code)
            await db.upsert_coverage(
                pillar=self.pillar,
                state_code=state_code,
                source=self.source_id,
                coverage_status=self.declared_status,
                record_count=count,
                last_ingested_at=run_result.completed_at,
            )
```

The pipeline orchestrator (`backend/pipeline/runner.py`) calls `write_coverage` on every successful adapter run.

### 4.2 Key Indexes

```sql
-- Companies
CREATE UNIQUE INDEX idx_companies_cik ON companies(cik) WHERE cik IS NOT NULL;
CREATE UNIQUE INDEX idx_companies_ticker ON companies(ticker) WHERE ticker IS NOT NULL;

-- Company Aliases (entity resolution hot path)
CREATE INDEX idx_aliases_text_lower ON company_aliases(lower(alias_text));
CREATE INDEX idx_aliases_company ON company_aliases(company_id);

-- Sites (geographic queries)
CREATE INDEX idx_sites_geo ON sites(state, county_fips);
CREATE INDEX idx_sites_company ON sites(company_id);
CREATE INDEX idx_sites_latlon ON sites USING gist (
    ST_MakePoint(lon, lat)
);  -- Requires PostGIS; optional Phase 1

-- Filings
CREATE UNIQUE INDEX idx_filings_accession ON filings(accession_number);
CREATE INDEX idx_filings_company_date ON filings(company_id, filing_date DESC);
CREATE INDEX idx_filings_form_date ON filings(form_type, filing_date DESC);
CREATE INDEX idx_filings_state ON filings(data_state);

-- Permits
CREATE UNIQUE INDEX idx_permits_permit_id ON permits(permit_id, county_fips);
CREATE INDEX idx_permits_county ON permits(county_fips, filed_date DESC);
CREATE INDEX idx_permits_company ON permits(company_id) WHERE company_id IS NOT NULL;
CREATE INDEX idx_permits_datacenter ON permits(is_datacenter, county_fips) WHERE is_datacenter = true;

-- Transcript Metrics
CREATE INDEX idx_transcripts_company_quarter ON transcript_metrics(company_id, fiscal_quarter);
CREATE INDEX idx_transcripts_metric ON transcript_metrics(metric_name, fiscal_quarter);
CREATE INDEX idx_transcripts_ticker_quarter ON transcript_metrics(ticker, fiscal_quarter);

-- Curated Deals
CREATE UNIQUE INDEX idx_deals_deal_id ON curated_deals(deal_id);
CREATE INDEX idx_deals_buyer ON curated_deals(buyer_company_id);
CREATE INDEX idx_deals_state ON curated_deals(state);

-- Satellite Observations
CREATE INDEX idx_satellite_site_date ON satellite_observations(site_id, observation_date DESC);

-- Data Lineage
CREATE INDEX idx_lineage_record ON data_lineage(source_record_id, source_table);
CREATE INDEX idx_lineage_run ON data_lineage(ingestion_run_id);

-- Ingestion Runs
CREATE INDEX idx_runs_adapter ON ingestion_runs(adapter_id, started_at DESC);
CREATE INDEX idx_runs_status ON ingestion_runs(status) WHERE status IN ('running', 'failed');
```

### 4.3 Migration from Current State

The `curated_deals.py` Python dict is migrated to the `curated_deals` table via a one-time migration script. The migration:

1. Creates all 22 deal records with generated UUIDs.
2. Creates corresponding `companies` entries for all buyers/sellers.
3. Populates `company_aliases` with known aliases from `ENERGY_COMPANIES` and `HYPERSCALERS` dicts.
4. The `deal_id` field (e.g., `"msft-ceg-tmi-2023"`) serves as a stable external identifier.
5. After migration, `curated_deals.py` is preserved as a read-only reference but the API reads from PostgreSQL.

---

## 5. Triangulation Layer Data Flow

### 5.1 Overview

```mermaid
graph LR
    subgraph Data Sources
        F[filings]
        CD[curated_deals]
        TM[transcript_metrics]
        P[permits]
    end

    subgraph Triangulation Engine
        L1[L1: Contracted GW]
        L2[L2: GPU Power Draw]
        L3[L3: NICs/Optics]
        L4[L4: Permit Signals]
        AGG[Aggregator]
    end

    F --> L1
    CD --> L1
    TM --> L2
    TM --> L3
    P --> L4

    L1 --> AGG
    L2 --> AGG
    L3 --> AGG
    L4 --> AGG

    AGG --> RESULT[TriangulationResult<br/>per company per geo]
```

### 5.2 Layer 1: Contracted Power (GW) per Company per Geography

**Sources:** `curated_deals` + `filings` (where `capacity_mw IS NOT NULL`) + `sites` (Aterio capacity)

**Aggregation Query Pattern:**

```sql
-- Contracted GW from curated deals
SELECT
    c.id AS company_id,
    c.name AS company_name,
    cd.state,
    SUM(cd.capacity_mw) / 1000.0 AS contracted_gw,
    MIN(cd.confidence) AS min_confidence,
    COUNT(*) AS deal_count,
    array_agg(cd.source_url) AS source_urls
FROM curated_deals cd
JOIN companies c ON c.id = cd.buyer_company_id
WHERE cd.state = :target_state
  AND cd.capacity_mw IS NOT NULL
  AND cd.data_state = 'available'
GROUP BY c.id, c.name, cd.state

UNION ALL

-- Additional capacity from EDGAR filings not in curated deals
SELECT
    c.id AS company_id,
    c.name AS company_name,
    :target_state AS state,
    SUM(f.capacity_mw) / 1000.0 AS contracted_gw,
    MIN(f.confidence) AS min_confidence,
    COUNT(*) AS deal_count,
    array_agg(f.edgar_url) AS source_urls
FROM filings f
JOIN companies c ON c.id = f.company_id
WHERE f.capacity_mw IS NOT NULL
  AND f.data_state = 'available'
  AND f.accession_number NOT IN (
      -- Exclude filings already represented in curated_deals
      SELECT cd2.deal_id FROM curated_deals cd2
  )
GROUP BY c.id, c.name;
```

**Deduplication:** When the same deal appears in both `curated_deals` and `filings`, prefer the source with higher confidence (typically `curated_deals` at 0.85-0.99). Matching is on `(canonical_company_id, capacity_mw, effective_date)` within a 30-day window.

**Output:** `contracted_gw_by_company_geo: dict[(company_id, state), float]`

**Replaces:** `contracted_gw = random.uniform(1.5, 8.0)` in `get_triangulation_data()`.

### 5.3 Layer 2: Estimated Deployed GPUs x Power Draw

**Sources:** `transcript_metrics` (NVIDIA `datacenter_revenue_b`, `gpu_units_shipped_k`)

**Aggregation Logic:**

```
1. Retrieve NVIDIA datacenter_revenue_b for trailing 4 quarters.
2. Sum trailing 4Q revenue.
3. Derive shipped GPU units:
     units = (revenue_b * 1e9) / assumed_asp
     where assumed_asp is user-adjustable (default: $25,000 for H100-class)
4. Estimate power draw:
     power_gw = (units * power_per_gpu_kw * utilization_pct) / 1e6
     where:
       power_per_gpu_kw: H100=0.7, B200=1.0 (config table)
       utilization_pct:  default 0.75 (user-adjustable)
5. Output includes full assumption chain:
     {
       "estimated_gpu_power_gw": 2.34,
       "assumptions": {
         "asp_usd": 25000,
         "gpu_model": "H100",
         "power_per_gpu_kw": 0.7,
         "utilization_pct": 0.75,
         "trailing_quarters": ["FY2026-Q1", "FY2025-Q4", "FY2025-Q3", "FY2025-Q2"],
         "total_revenue_b": 78.5
       },
       "source_urls": [...],
       "confidence": 0.65,
       "confidence_rationale": "Derived metric: revenue from 10-Q (0.95) degraded by ASP assumption uncertainty"
     }
```

**Replaces:** `deployed_gpu_k = random.randint(20, 200)` in `get_triangulation_data()`.

### 5.4 Layer 3: NIC and Optics Validation

**Phase 1 behavior:** This layer returns an explicit no-data response:

```json
{
  "layer": "L3_nic_optics",
  "data_status": "no_data",
  "reason": "NIC/optics data sources (Broadcom, Coherent, Lumentum) deferred to Phase 2",
  "metric_value": null,
  "confidence": null,
  "estimated_availability": "Phase 2 (Q3 2026)"
}
```

**Replaces:** `nic_validation_score = random.uniform(0.75, 0.98)` -- which is entirely removed, not replaced with another random number.

**Phase 2 sources:** `transcript_metrics` for Broadcom `networking_revenue_b`, Coherent/Lumentum optical transceiver shipments.

### 5.5 Layer 4: County Permit Data (Ground Truth)

**Sources:** `permits` (where `is_datacenter = true` and target geography)

**Aggregation Query Pattern:**

```sql
SELECT
    p.county_fips,
    p.county_name,
    c.id AS company_id,
    c.name AS company_name,
    p.status,
    COUNT(*) AS permit_count,
    SUM(p.estimated_sqft) AS total_sqft,
    SUM(p.estimated_mw) AS total_mw,
    array_agg(p.source_url) AS source_urls,
    MIN(p.confidence) AS min_confidence
FROM permits p
LEFT JOIN companies c ON c.id = p.company_id
WHERE p.is_datacenter = true
  AND p.county_fips IN (:target_fips_codes)
  AND p.data_state = 'available'
GROUP BY p.county_fips, p.county_name, c.id, c.name, p.status
ORDER BY p.county_fips, permit_count DESC;
```

**Cross-referencing with L1:** The triangulation engine flags:
- Companies with power contracts (L1) but no permits (L4): "Announced but not yet building"
- Companies with permits (L4) but no power contracts (L1): "Building without disclosed power source"

**Replaces:** `permit_signals = random.randint(3, 18)` in `get_triangulation_data()`.

### 5.6 Triangulation Confidence

Overall triangulation confidence is computed as:

```
triangulation_confidence = min(L1_confidence, L2_confidence, L4_confidence)
  where each layer confidence = min(confidence) of contributing records

If a layer has no data:
  - L3 (Phase 1 deferred): excluded from min(), does not degrade confidence
  - L1, L2, or L4 with no data: confidence = 0.0, result includes reason

The result NEVER uses random.uniform(). It is a deterministic function of input data quality.
```

### OCI %-Share Computation

> The canonical definition of OCI %-share computation is in `03-architecture-design.md`. This section summarizes the pipeline-specific aspects.

The pipeline computes OCI %-share by:
1. Resolving provider names/tickers to canonical company IDs via the **rapidfuzz alias table**
2. OCI is identified by `provider_name ILIKE '%oracle%' OR provider_ticker IN ('ORCL')` plus alias table entries
3. Per-tab aggregation: `oci_pct = (oci_value / total_tracked_value) * 100`
4. Materialized in SQL view `v_oci_share_by_tab`, refreshed on each ingestion run
5. Exposed via `GET /api/{tab}/oci-share`

---

## 6. Data State Machine

### 6.1 State Transitions

```mermaid
stateDiagram-v2
    [*] --> pending_ingestion : Adapter scheduled
    pending_ingestion --> raw_stored : fetch() succeeds
    pending_ingestion --> fetch_failed : fetch() raises error

    raw_stored --> parsed : parse() succeeds
    raw_stored --> parse_failed : parse() raises error

    parsed --> validated : validate() passes
    parsed --> validation_failed : validate() fails critical checks

    validated --> entity_resolved : resolve_entities() completes
    validated --> resolution_pending : Unresolved entities flagged

    entity_resolved --> available : All checks pass
    resolution_pending --> available : Manual resolution or auto-accept

    available --> stale : Staleness threshold exceeded

    fetch_failed --> pending_ingestion : Retry scheduled
    parse_failed --> raw_stored : Manual re-parse after fix
    validation_failed --> parsed : Manual override
    stale --> pending_ingestion : Re-ingestion triggered
```

### 6.2 State Definitions

| State | Description | Visible to API? | Confidence Impact |
|-------|------------|-----------------|-------------------|
| `pending_ingestion` | Scheduled but not yet fetched | No | N/A |
| `raw_stored` | Raw bytes stored, not yet parsed | No | N/A |
| `parsed` | Parsed into NormalizedRecord, awaiting validation | No | N/A |
| `validated` | Passed schema + business rule checks | No | N/A |
| `entity_resolved` | Canonical IDs assigned | No | N/A |
| `available` | Ready for API consumption | **Yes** | As computed |
| `stale` | Available but past freshness threshold | **Yes** (flagged) | -0.1 penalty |
| `fetch_failed` | Source retrieval failed | Indirectly (error in pipeline health) | N/A |
| `parse_failed` | Parsing failed | Indirectly | N/A |
| `validation_failed` | Critical validation failure | Indirectly | N/A |
| `resolution_pending` | Entity resolution incomplete | No | N/A |

### 6.3 Staleness Thresholds

| Source | Staleness Threshold | Action on Stale |
|--------|-------------------|-----------------|
| EDGAR filings | 48 hours since last successful run | Flag as stale; confidence -0.1 |
| Permits | 14 days since last successful run | Flag as stale; confidence -0.05 |
| Earnings | 96 hours after expected earnings date | Flag as stale; confidence -0.1 |
| Aterio | 90 days since last file ingestion | Flag as stale; confidence -0.05 |
| Curated deals | Never (manually curated, no automated refresh) | N/A |
| Satellite | 30 days since last observation | Flag as stale |

### 6.4 What "No Data" Looks Like

When the API has no data for a requested metric, it returns an explicit no-data response. It NEVER generates a random number or returns an empty array without explanation.

```json
{
  "metric": "contracted_power_gw",
  "value": null,
  "data_status": "no_data",
  "reason": "No EDGAR filings or curated deals found for Google in Prince William County",
  "suggested_action": "Check curated_deals for state-level data; county-level data may not exist for this company",
  "last_checked": "2026-04-28T06:00:00Z",
  "source_id": "sec_edgar"
}
```

---

## 7. Phase-1 National Scope

> **Scope update (2026-04-28):** the MVP is **national** — all 50 US states + DC — from day one, with `<CoverageBadge />` indicators where coverage is partial. Per `00-DECISIONS-AND-CONSTRAINTS.md` §5.2, the geographic carve-out from earlier drafts has been removed. The §7 table below describes per-pillar Phase-1 coverage; states with deepest coverage (VA + the 5 Socrata states) act as the proof points but the system runs nationally.

### 7.0 NoVA proof-of-coverage (illustrative depth, not scope limit)

### 7.1 What Phase 1 Produces

| Dimension | Phase 1 Scope |
|-----------|---------------|
| **Geography** | Loudoun County VA (FIPS 51107), Prince William County VA (FIPS 51153) |
| **Companies** | Microsoft, Amazon/AWS, Google/Alphabet (from curated_deals + EDGAR). Meta and Oracle visible in curated_deals but not primary focus. |
| **EDGAR** | Hardened adapter (async, structured errors, lineage). Backfill 2023-01-01 to present. 6-hour refresh. |
| **Curated Deals** | All 22 deals migrated to PostgreSQL. Adapter wrapper emits NormalizedRecord. National (no state filter). |
| **Building Permits** | **Free state-API set** for v1: VA Open Data, NY DEC Socrata, WA Ecology, CO CDPHE, OR DEQ, TX TCEQ. Weekly refresh. Datacenter NAICS / keyword filtering. Other 44 states render `<NoStateCoverage />` empty state per §5.3 of `00-DECISIONS-AND-CONSTRAINTS.md`. Shovels.ai deferred to Phase 2. |
| **Generator / Air Permits** | EPA ECHO (national federal baseline) + state-level depth in TX/CA/NY/WA/CO/OR. VA/IA/AZ standing-records requests pending. Feeds `permittee_llc` and `permit_parent` roles via §7.5 LLC resolver. |
| **Earnings** | NVIDIA + TSMC 10-Q ingestion. 8 quarters backfill per company. LLM extraction prototype for transcripts. |
| **Aterio** | All Excel files in `datasets/` ingested. Entity-resolved. Cross-referenced with curated_deals for dedup. |
| **Satellite** | `get_satellite_sites()` curated metadata preserved and served via adapter. Labeled "site metadata only." No imagery API. |
| **Triangulation** | L1 (real, national) + L2 (real with assumptions, national for tracked public companies) + L3 (national, low-confidence inference) + L4 (real for the 6 covered states; per-state `<NoStateCoverage />` for others). Per-state cards show which layers are populated. |
| **Coverage table** | Every adapter writes a row per (pillar, state_code, source) into `data_coverage` at end of each run. Powers `<CoverageBadge />` and per-state empty states. See §4 schema. |

### 7.2 Data Sources: Active vs. Deferred

```
Phase 1 ACTIVE:
  [x] sec_edgar          -- Hardened, async, lineage-tracked
  [x] curated_deals      -- Migrated from Python dict to PostgreSQL
  [x] county_permits     -- Shovels.ai or VA Open Data for 51107 + 51153
  [x] earnings_transcripts -- NVIDIA + TSMC 10-Q. Transcript LLM extraction prototype.
  [x] aterio_dataset     -- One-time ingest from datasets/ directory

Phase 1 DEFERRED (explicit "coming soon" in UI):
  [ ] satellite_imagery  -- Show curated site metadata. "Imagery coming Phase 2"
  [ ] earnings: Broadcom, Coherent, Lumentum -- "Phase 2: NIC/Optics data sources"
  [ ] permits: Fairfax County (51059) -- "Expanding to Fairfax in Phase 2"
  [ ] permits: TX, AZ, OR, IA counties -- "National coverage in Phase 2"
```

### 7.3 mock_data.py Replacement Plan

Each `mock_data.py` function is replaced as follows:

| Function | Replacement | Phase |
|----------|------------|-------|
| `get_power_data()` | Query `curated_deals` + `filings` grouped by company/state. Return real contracted GW. | 1 |
| `get_power_timeseries()` | Query `curated_deals` + `filings` bucketed by quarter. Gaps show null, not interpolated random values. | 1 |
| `get_gpu_data()` | Query `transcript_metrics` for NVIDIA. `gpu_units_shipped_k` is derived with visible assumptions. | 1 |
| `get_nics_optics_data()` | Return explicit `{"data_status": "no_data", "reason": "Phase 2"}`. No random numbers. | 1 |
| `get_tsmc_data()` | Query `transcript_metrics` for TSMC. Missing quarters show null + reason. | 1 |
| `get_permits_data()` | Query `permits` table for target counties. Real permit records with county source URLs. | 1 |
| `get_satellite_sites()` | **Keep as-is** (already real data). Wrap in adapter interface. Add lineage fields. | 1 |
| `get_triangulation_data()` | Compute from L1-L4 pipeline data. No random.uniform(). Missing layers show null + reason. | 1 |
| `get_sources_data()` | Query `ingestion_runs` table for real pipeline status. | 1 |
| `get_agent_status()` | Query `ingestion_runs` table for real adapter run history. | 1 |

**Gate:** `mock_data.py` remains in the codebase but is gated behind `MOCK_DATA=1` environment variable (default: off). Production code paths MUST NOT import from `mock_data.py` without the gate.

---

## 7.5 Generator-Permit Pipeline (L4 Enrichment, Parallel Track)

A separate ingestion track that **deepens L4** (the County Permits triangulation layer) with air-quality permit signals. While L4 currently answers "is something being built?" via building permits, generator permits answer "who really runs it, how much standby MW, and what's the emissions ceiling?" — with **parent-company attribution** even when the permit applicant is an LLC obscuring the actual hyperscaler. Designed to run **in parallel** with the national MVP, not to block it.

### 7.5.1 Goals

For every major US data center site, emit:
- Number of generator units, rated capacity (MW each, total site MW)
- Fuel type, engine model, emissions tier
- Permitted emissions limits (NOx, CO, PM, SO2, HAPs) and operational hours
- Permittee LLC + ultimate parent company (resolved with confidence score)
- Permit status, issue date, modifications

**Success criteria:** queryable dataset covering ≥80% of US hyperscaler generator capacity, refreshed monthly, with parent-company attribution confidence per record.

### 7.5.2 Sources (free, no auth)

Federal:
- **EPA ECHO** (`echo.epa.gov/tools/web-services`) — national baseline; air-permitted facilities; filter NAICS 518210 + emergency-engine source classes. JSON.
- **EPA Envirofacts** (`data.epa.gov/efservice/`) — NEI emissions; FRS cross-reference; ICIS-AIR detail.
- **EPA CAMD** (`api.epa.gov/easey/`) — CEMS data for units that report it. Catches "emergency standby that actually runs a lot."
- **SEC EDGAR Exhibit 21** — subsidiary lists for the ~8 relevant public hyperscalers. Foundation of the LLC→parent resolver.

State APIs:
- **Texas TCEQ Air Permits API** — DFW, Austin, Abilene, San Antonio.
- **CARB / SCAQMD / BAAQMD** (California regional APIs).

State open-data portals (Socrata-equivalent):
- NY DEC, WA Ecology, CO CDPHE, OR DEQ — generic Socrata adapter.

State no-API (standing public-records requests, monthly delivery):
- VA DEQ (Loudoun, Prince William — *single largest concentration*), IA DNR, AZ ADEQ, GA EPD, LA LDEQ, MS MDEQ, TN TDEC, NE DEE, OH EPA, NC/SC, NV NDEP, NM NMED.

Entity resolution:
- **OpenCorporates API** (free tier in v1, Pro in Phase 2) — state business registries.
- County assessor / GIS portals — parcel ownership, deeds.
- ISO/RTO interconnection queues (PJM, ERCOT, MISO, SPP, CAISO).
- Trade press corpus (DCD, Data Center Frontier RSS) — supporting signal only, not standalone.

### 7.5.3 New tables

```sql
-- Generator permit, one row per permit (modifications produce additional rows)
CREATE TABLE generator_permits (
    id BIGSERIAL PRIMARY KEY,
    site_id BIGINT REFERENCES sites(id),  -- nullable until resolved
    source TEXT NOT NULL,                 -- 'epa_echo' | 'tceq' | 'va_deq' | ...
    source_record_id TEXT NOT NULL,
    frs_id TEXT,                          -- federal FRS facility key
    permittee_raw_name TEXT NOT NULL,     -- LLC string as filed
    permittee_company_id BIGINT REFERENCES companies(id),     -- resolved permittee LLC
    permit_parent_company_id BIGINT REFERENCES companies(id), -- resolved ultimate parent
    parent_attribution_confidence NUMERIC(3,2),
    parent_attribution_evidence JSONB,    -- which signals fired and weights
    permit_status TEXT,                   -- issued | modified | revoked | pending
    issue_date DATE,
    fuel_type TEXT,                       -- diesel | natural_gas | dual
    engine_model TEXT,
    emissions_tier TEXT,                  -- Tier 2 | Tier 4 | etc.
    num_units INT,
    rated_mw_each NUMERIC,
    rated_mw_total NUMERIC,
    emission_limits JSONB,                -- {NOx, CO, PM, SO2, HAPs}
    operational_hours_limit INT,          -- per year
    raw_pdf_url TEXT,
    raw_pdf_local_path TEXT,              -- VM filesystem path under data/raw/
    extracted_at TIMESTAMPTZ,
    parser_version TEXT,
    extraction_provenance JSONB,          -- per-field {page, bbox, raw_text}
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (source, source_record_id)
);

CREATE INDEX idx_genperm_site ON generator_permits(site_id);
CREATE INDEX idx_genperm_parent ON generator_permits(permit_parent_company_id);
CREATE INDEX idx_genperm_state_date ON generator_permits(source, issue_date DESC);
```

Site association is also written to `site_company_associations` with role `permittee_llc` (raw applicant) and `permit_parent` (resolved ultimate parent). This means the Companies tab automatically picks up generator-permit attribution alongside Aterio data.

### 7.5.4 LLC → Parent Resolver (Llama Stack agent with tool-use)

**Updated 2026-04-28:** the resolver is now an LLM agent that orchestrates the deterministic signals as tools. The deterministic signals stay (we never want to call the LLM if SEC Exhibit 21 has a direct match), but the agent handles the ambiguous middle — weighing partial evidence, deciding when web search confirms a tentative match, deciding when to escalate to human review. Per `00-DECISIONS-AND-CONSTRAINTS.md` §4.2 (Agent C), this was promoted from Phase-2 deferred to Phase-1.5 because OCI Llama Stack is internal infra with no cost gating.

**Model:** `oci/openai.gpt-5.4` primary, `oci/xai.grok-4.20-reasoning` fallback. Tool-calling via OpenAI-compatible `/v1/chat/completions` (function-calling).

**Tools available to the agent** (each tool internally is one of the deterministic signals from the previous design):

| Tool name | Implementation | Returns |
|---|---|---|
| `search_sec_exhibit_21(company_name)` | Local DB lookup of pre-ingested Exhibit 21 subsidiaries from the ~8 relevant public hyperscalers | `[{parent_company_id, exact_match, exhibit_21_url}]` |
| `lookup_opencorporates(llc_name, state)` | OpenCorporates free-tier API call | `{officers, registered_agent, principal_address, organizers}` |
| `lookup_parcel_owner(lat, lon)` | County GIS portal lookup (per-state adapter) | `{deed_holder, owner_address, recording_date}` |
| `lookup_iso_queue(facility_address)` | PJM/ERCOT/MISO/SPP/CAISO public queue | `[{project_name, queue_name, capacity_mw}]` |
| `web_search(query)` | Llama Stack `builtin::websearch` (Tavily) | Trade-press articles |

**Agent loop:**
1. Cheap deterministic pre-check: if `search_sec_exhibit_21(permittee)` returns an exact match → publish at `confidence=1.0`, no LLM call needed (most public-hyperscaler LLCs land here).
2. If no exact match: run the agent. The agent decides which tools to call in what order, weighs evidence, and emits a structured output with `parent_company_id`, `confidence` (self-reported, calibrated against eval set), and `evidence: [{signal, weight, finding}]`.
3. If `confidence ≥ 0.7` → auto-publish the `permit_parent` association on `site_company_associations`.
4. If `confidence < 0.7` → enqueue into `permit_parent_review_queue` (schema in `03-architecture-design.md` §6.5.3) for human review with the agent's evidence trail attached.

**Deterministic-only fallback:** if Llama Stack is unavailable, the resolver falls back to the original weighted-scoring algorithm:

| Signal | Weight |
|---|---|
| SEC Exhibit 21 exact match | 1.0 |
| OpenCorporates: registered agent / officer match to known hyperscaler corporate address | 0.8 |
| County parcel deed names a known hyperscaler corporate entity | 0.7 |
| ISO/RTO interconnection queue uses parent's name on same address | 0.5 |
| Filing-attorney clustering | 0.3 |
| Trade-press corpus mentions the LLC + parent | 0.2 |

This fallback path is shipped in `backend/llm/fallback/llc_deterministic.py` and gated by env var; no degradation in coverage, just less judgment on ambiguous cases.

**Run lifecycle:** every agent execution writes a row to `llm_extraction_runs` (agent_name, model, prompt_version, input_hash, tool_calls, confidence, latency, status). Re-running on the same permittee hits the cache via `UNIQUE (agent_name, input_hash)`. The `parent_attribution_evidence` JSONB on `generator_permits` also gets the agent's `tool_calls` trace verbatim, so UI can render which signals fired in what order with what confidence.

### 7.5.5 Document parser (Llama Stack vision agent)

Required because most generator-permit detail (rated MW, emissions, fuel type) lives in PDF attachments, not API JSON. Per `00-DECISIONS-AND-CONSTRAINTS.md` §4.2 (Agent B), the narrative-extraction layer is now a Llama Stack call, not Anthropic Claude.

- **Layout-aware tables:** `pdfplumber` + `pymupdf` (deterministic; runs first).
- **OCR fallback** for scanned docs: Tesseract.
- **Narrative extraction (Llama Stack vision):** `oci/google.gemini-2.5-pro` primary, `oci/cohere.command-a-vision` fallback. Single-turn structured-output extraction with strict JSON schema. Provenance per field (page, bbox, raw_text) preserved. One pass per permit; cached via `llm_extraction_runs.UNIQUE (agent_name, input_hash)` so a re-ingest of the same PDF is free.
- **Schema validation:** Pydantic model in `backend/llm/schemas.py`; failed validation enqueues to a per-agent dead-letter table for re-prompt or human review.
- Validate extractor against 20–30 hand-labeled permits across multiple states before declaring production-ready.

**Fallback path** when Llama Stack is unavailable: pdfplumber-only extraction. Loses narrative fields (emissions narrative, operational-hours commentary); structured fields (rated_mw, fuel_type, num_units from tables) are preserved.

### 7.5.6 Phasing (parallel to national MVP)

| Weeks | Milestone |
|---|---|
| 1–2 | Stand up EPA ECHO ingest. File standing public-records requests with VA DEQ, IA DNR, AZ ADEQ, OR DEQ for monthly delivery (these take 2–6 weeks to set up). Build national candidate list from ECHO using FRS_ID as canonical key. |
| 3–5 | Build TCEQ + Socrata-generic adapters (NY/WA/CO). Build Oregon DEQ bulk-export adapter. Build PDF parser (`pdfplumber` + Tesseract + Claude); validate on Loudoun samples. |
| 5–8 | Build multi-signal LLC→parent resolver. Pull SEC Exhibit 21, then OpenCorporates lookups, then parcel cross-refs. Layer in weaker signals as scoring contributions. Calibrate threshold. |
| 8–10 | Geocoding + parcel matching enrichment. Roll permits up: permits → facilities → campuses → parents. CEMS overlay. Stand up human-review queue for low-confidence extractions and entity links. |
| 10–12 | Schedule under APScheduler (cron weekly for ECHO and state APIs, monthly for entity-resolution refresh, on-arrival hooks for public-records deliveries). Change-detection alerts on new permits and modifications. BI dashboards (capacity by company / region / year; emissions-footprint comparisons; new-permit feed). |

### 7.5.7 Stack alignment with locked decisions

| Concern | Generator plan default | Locked stack | Resolution |
|---|---|---|---|
| Orchestrator | Dagster | APScheduler (`00-DECISIONS-AND-CONSTRAINTS.md` §2.1) | **Use APScheduler for v1.** Cron-style polling of ECHO + state APIs is well within APScheduler's scope. If/when human-review queues + dependency graphs get unwieldy, escalate this pipeline to Dagster *for this pipeline only* — see `docs/OPEN-TENSIONS.md`. |
| Raw PDF storage | OCI Object Storage / S3 | Self-hosted VM (Decision #1 + #4) | **VM filesystem under `data/raw/{source}/{yyyy-mm-dd}/`** for v1. Migrate to OCI Object Storage when disk usage approaches ~50 GB. Tracked in `OPEN-TENSIONS.md`. |
| Entity resolution | Multi-signal scorer + human review | rapidfuzz + curated alias table (locked) | **Both.** rapidfuzz handles the easy cases (public companies via ticker/CIK); the multi-signal scorer is a *new* component layered on top, used only when rapidfuzz fails or the source is a known LLC-obfuscated permit. The locked stack stays intact. |
| Vector search over narratives | pgvector | Not in locked stack | **Defer to Phase 2.** v1 stores raw narratives as TEXT; semantic search is nice-to-have, not required for the queryable dataset goal. |
| BI dashboards | Superset/Metabase | Existing React frontend | Use the existing Recharts-based dashboard. New views (capacity-by-parent, emissions footprint) live as additional tabs/sections per the §5 UX rule. |

### 7.5.8 Caveats (to set expectations)

- **Coverage will never be 100%.** Some facilities permit under permit-by-rule exemptions and never appear in any database.
- **Data is months stale at best.** Permit issuance is slow; press announcements often precede the permit by 6–18 months. For early-warning, supplement with trade-press feeds.
- **Parent attribution is probabilistic.** Confidence scores are real and surfaced in the UI — not hidden.
- **Legal review before launch.** Public records are public, but ToS for OpenCorporates and any commercial source warrant a quick Oracle Legal review before production.

---

## 8. API Contract Changes

### 8.1 Universal Response Envelope

Every API response wraps data in a standard envelope that includes lineage and status information:

```json
{
  "data": [ ... ],
  "meta": {
    "data_status": "real",
    "source_summary": {
      "sources": ["sec_edgar", "curated_deals"],
      "total_records": 14,
      "freshest_record": "2026-04-28T06:00:00Z",
      "oldest_record": "2026-04-21T06:00:00Z"
    },
    "request_timestamp": "2026-04-28T14:32:00Z",
    "geography_filter": "VA",
    "company_filter": null
  }
}
```

### 8.2 Per-Record Lineage Fields

Every data record in the `data` array includes:

```json
{
  "company": "Microsoft",
  "capacity_mw": 835,
  "data_source": "curated_deals",
  "source_url": "https://news.microsoft.com/2023/09/20/...",
  "retrieved_at": "2026-04-22T00:00:00Z",
  "confidence": 0.98,
  "confidence_rationale": "Hand-verified from press release + SEC 8-K",
  "data_status": "real",
  "parser_version": "1.0.0"
}
```

### 8.3 `data_status` Field Values

| Value | Meaning | UI Treatment |
|-------|---------|-------------|
| `"real"` | Backed by an ingested, validated, entity-resolved data source | Normal display |
| `"curated"` | Hand-verified by analyst (from curated_deals) | Normal display + "Verified" badge |
| `"no_data"` | No data exists for this metric/company/geo | Show "No data available" + reason |
| `"stale"` | Data exists but exceeds freshness threshold | Show with "Last updated X days ago" warning |
| `"derived"` | Computed from other data with assumptions | Show with assumptions visible |

### 8.4 Error Responses

Error responses include structured information, not empty arrays:

```json
{
  "data": null,
  "meta": {
    "data_status": "error",
    "error": {
      "code": "ADAPTER_DEGRADED",
      "message": "SEC EDGAR adapter failed 3 consecutive runs. Serving cached data from 2026-04-27.",
      "adapter_id": "sec_edgar",
      "last_success": "2026-04-27T06:00:00Z",
      "last_failure": "2026-04-28T06:00:12Z",
      "retry_scheduled": "2026-04-28T12:00:00Z"
    }
  }
}
```

### 8.5 New Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/pipeline/health` | GET | Returns status of each adapter: last_run, records_ingested, errors, next_scheduled_run |
| `GET /api/pipeline/runs` | GET | Paginated list of ingestion run history |
| `GET /api/pipeline/runs/{run_id}` | GET | Detail of a specific run including error details |
| `POST /api/pipeline/trigger/{adapter_id}` | POST | Manually trigger an ingestion run for a specific adapter |
| `GET /api/lineage/{record_id}` | GET | Full lineage chain for a specific data record |

### 8.6 Changed Endpoints

| Existing Endpoint | Change |
|-------------------|--------|
| `GET /api/power/capacity` | Returns real data from `curated_deals` + `filings`. Each row includes `data_source`, `source_url`, `confidence`, `data_status`. No more `random.uniform()`. |
| `GET /api/power/timeseries` | Returns real quarterly data. Gaps are `null` with `"data_status": "no_data"`. |
| `GET /api/gpu/supply` | Returns NVIDIA metrics from `transcript_metrics`. Derived fields tagged `is_derived: true`. |
| `GET /api/nics` | Returns `{"data_status": "no_data", "reason": "Phase 2"}`. No random data. |
| `GET /api/tsmc` | Returns TSMC metrics from `transcript_metrics`. Missing quarters are explicit nulls. |
| `GET /api/permits` | Returns real permit data from PostgreSQL. Each permit links to county source URL. |
| `GET /api/triangulation` | Computed from L1-L4. Per-layer source citations. Missing layers show null + reason. |
| `GET /api/sources` | Reads from `ingestion_runs` table. Shows real adapter status, not mock data. |
| `GET /api/power/announcements` | Reads from PostgreSQL `curated_deals` + `filings` tables instead of Python dicts. |

### New Endpoints

| Method | Path | Source | Notes |
|---|---|---|---|
| GET | `/api/sites` | sites table | Paginated, filterable |
| GET | `/api/sites/{aterio_dc_uid}` | sites table | Full detail |
| GET | `/api/events` | events table | Filterable by site, type, date |
| GET | `/api/energy-projects` | energy_projects table | Filterable |
| GET | `/api/edgar/frames/{concept}/{period}` | Pass-through to data.sec.gov | Cross-company quarterly. Cached 12h. |
| GET | `/api/{tab}/oci-share` | v_oci_share_by_tab | OCI %-share per tab |

All endpoints return a lineage envelope: `{ "data": [...], "lineage": { "source_url", "retrieved_at", "parser_version", "confidence" } }`

---

## ADRs (Architecture Decision Records)

### ADR-001: PostgreSQL over SQLite for Phase 1

**Context:** The PRD mentions SQLite as an option for Phase 1. The tech stack research recommends PostgreSQL.

**Decision:** Use PostgreSQL from day one.

**Rationale:**
- SQLite has a single-writer limitation. Multiple adapters running concurrent ingestion jobs will conflict.
- PostgreSQL JSONB supports GIN indexes for semi-structured data queries (raw source payloads).
- PostGIS extension is available for future geospatial queries (nearest-site lookups, bounding box filters).
- `asyncpg` provides native async support for FastAPI without blocking the event loop.
- Migrating from SQLite to PostgreSQL later is a project in itself; doing it now avoids that cost.
- Self-hosted PostgreSQL process directly on this OCI VM for both dev and production (Decision #1 + #4 per [00-DECISIONS-AND-CONSTRAINTS.md](00-DECISIONS-AND-CONSTRAINTS.md)). No Docker, no managed service. Install via `apt-get install postgresql` and manage via `systemctl`.

**Consequences:** Adds `asyncpg`, `sqlalchemy[asyncio]`, `alembic` dependencies. Local-dev developers run the same systemd-managed PostgreSQL as the VM (no container layer).

### ADR-002: APScheduler In-Process over Celery

**Context:** The pipeline needs scheduled jobs (daily EDGAR, weekly permits, on-demand transcripts).

**Decision:** Use APScheduler `AsyncIOScheduler` running inside the FastAPI process.

**Rationale:**
- Zero infrastructure cost: no Redis, no RabbitMQ, no separate worker process.
- 2-3 person team cannot afford the operational overhead of Celery (broker + worker + beat = 3 extra processes).
- Phase 1 jobs are infrequent (daily, weekly) and run on a single machine.
- Job persistence via PostgreSQL means missed runs are detected on restart.
- Upgrade path to Celery exists if Phase 2 requires distributed workers; the adapter functions themselves are scheduler-agnostic.

**Consequences:** If the FastAPI process crashes, scheduled jobs stop until auto-restart. Mitigated by process manager (systemd) with auto-restart and PostgreSQL-backed run history for gap detection.

### ADR-003: Deterministic Confidence over Random Confidence

**Context:** Current mock_data.py uses `random.uniform(0.7, 0.98)` for confidence scores. Current edgar_agent.py hardcodes `0.90`.

**Decision:** Confidence scores are computed deterministically from parsing results using per-adapter formulas documented in Section 3.

**Rationale:**
- Random confidence communicates nothing about data quality and actively misleads analysts.
- Hardcoded confidence fails to distinguish high-quality extractions from low-quality ones.
- Deterministic formulas (e.g., EDGAR: base 0.50 + 0.20 for MW match + 0.15 for counterparty + ...) create a meaningful signal that analysts can interpret.
- The formula for each adapter is versioned with `parser_version`, so confidence values can be recalculated if the formula improves.

**Consequences:** Confidence scores may be lower than current random values (which cluster around 0.85). This is correct -- they now reflect actual certainty. The UI should explain what confidence means.

### ADR-004: Adapter Contract Before Implementation

**Context:** Five data sources need to be integrated. Without a common interface, each will have bespoke integration code.

**Decision:** Define the `DataSourceAdapter` interface (Section 2) and `NormalizedRecord` base schema before writing any adapter implementation.

**Rationale:**
- Uniform interface means the pipeline orchestrator, storage layer, triangulation engine, and API response builder can all treat sources generically.
- New sources (Phase 2: Broadcom, Coherent, Lumentum, national permits) plug in by implementing the same interface.
- Lineage fields are guaranteed on every record because they are in the base schema, not optional additions.
- Validation and entity resolution are generic operations that work across all record types.

**Consequences:** Slight over-engineering for sources like Aterio (one-time ingest). Acceptable trade-off for system consistency.

### ADR-005: Explicit No-Data over Silent Empty Arrays

**Context:** Current API returns empty arrays `[]` when data is unavailable, with no explanation. `get_nics_optics_data()` returns random numbers because no real source exists.

**Decision:** Every API response includes a `data_status` field. When no data exists, the response includes `"data_status": "no_data"` with a human-readable `reason` string.

**Rationale:**
- An empty array is ambiguous: does it mean "no data exists" or "the pipeline is broken"?
- Random numbers are worse: they look like real data but are fabricated.
- Explicit no-data with a reason ("Phase 2", "adapter failed", "no filings for this company in this county") lets analysts make informed decisions.
- The UI can render appropriate states (empty state component, "coming soon" badge, error banner) based on `data_status`.

**Consequences:** Frontend must handle all `data_status` values. Additional development for empty-state and error-state UI components.

---

## Risks and Mitigations

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| R-1 | Shovels.ai procurement takes longer than Phase 1 | Medium | High -- no permit data | Build VA Open Data CSV adapter in parallel. Two-week decision gate: if Shovels not approved by Week 2, commit to CSV fallback. |
| R-2 | EDGAR adapter refactor exceeds 1-week estimate | Medium | Medium -- blocks downstream | Time-box to 5 days. Ship with improved error handling + lineage first; async conversion can trail by 1 sprint. |
| R-3 | Entity resolution match rate below 50% for permits | Medium | High -- permits unattributed | Seed alias table aggressively from VA SCC business registrations, news articles, and existing `curated_deals` company names. Accept partial attribution in Phase 1. |
| R-4 | PostgreSQL migration from file-based cache causes data loss | Low | Medium | Run both systems in parallel for 1 week. Validate all curated_deals records match after migration. |
| R-5 | APScheduler in-process jobs miss runs during FastAPI restart/deploy | Medium | Low | Persist run history to PostgreSQL. On startup, check for missed runs (last_completed + interval < now) and trigger catch-up. |
| R-6 | FMP earnings transcript API changes pricing or coverage | Low | Medium | EDGAR 10-Q XBRL is the free fallback. Transcripts add color but 10-Q provides the authoritative numbers. |
| R-7 | SEC EDGAR increases rate limiting below 10 req/s | Low | High -- primary source degraded | Shared token-bucket rate limiter already designed at 8 req/s. Cache aggressively with PostgreSQL-backed cache. Monitor EDGAR developer announcements. |
| R-8 | Team treats "no data" as acceptable long-term | Medium | High -- platform stalls | Track "no_data" count as a KPI on the Sources tab. Every "no_data" cell should link to a Jira ticket. Karan reviews monthly. |
| R-9 | Mixed real + mock data confuses analysts during rollout | Medium | High -- trust erosion | Gate `mock_data.py` behind env var from day one. Add visible "MOCK DATA" watermark to any tab still using mock sources. Roll out tab-by-tab: Power first, then Permits, then GPU, etc. |
| R-10 | Database schema requires breaking changes mid-Phase 1 | Medium | Medium | Use Alembic migrations from the first schema creation. Never modify tables directly; always through versioned migrations. |

---

## Appendix A: Blob Storage Layout

```
raw/
  edgar/
    2026/
      04/
        28/
          {accession_number}.html        # Raw filing HTML
          {accession_number}.meta.json   # Retrieval metadata
  permits/
    2026/
      04/
        28/
          shovels_{county_fips}_{date}.json   # Raw API response
          va_opendata_{county_fips}_{date}.csv # Fallback CSV
  transcripts/
    2026/
      Q1/
        NVDA_FY2026Q1_transcript.json     # Raw FMP response
        NVDA_FY2026Q1_10q.html            # Raw 10-Q filing
  aterio/
    2026/
      04/
        aterio_upload_{timestamp}.xlsx      # Original Excel file
  satellite/
    2026/
      04/
        site_{site_id}_{date}.tif          # GeoTIFF (Phase 2)
        site_{site_id}_{date}_thumb.png    # Thumbnail
```

Phase 1: Local filesystem at `{PROJECT_ROOT}/data/raw/`.
Phase 2: Migrate to OCI Object Storage with same path structure as object keys.

## Appendix B: Configuration Schema

All adapter configuration is externalized (not hardcoded in adapter code):

```yaml
pipeline:
  database_url: "postgresql+asyncpg://user:pass@localhost:5432/strategic_insights"
  raw_storage_path: "/app/data/raw"
  raw_storage_backend: "filesystem"  # or "oci_object_storage"

adapters:
  sec_edgar:
    enabled: true
    schedule: "0 */6 * * *"
    rate_limit_rps: 8
    cache_ttl_hours: 12
    backfill_since: "2023-01-01"
    companies:
      energy:
        "Constellation Energy": "0001868275"
        "Talen Energy": "0001839839"
        # ... (from current ENERGY_COMPANIES dict)
      hyperscalers:
        "Microsoft": "0000789019"
        "Amazon": "0001018724"
        # ... (from current HYPERSCALERS dict)
    form_types: ["8-K", "10-K", "10-Q"]
    retry:
      max_attempts: 3
      backoff_base_seconds: 1
      backoff_multiplier: 2

  county_permits:
    enabled: true
    schedule: "0 7 * * 1"
    primary_source: "shovels"  # or "va_open_data"
    shovels_api_key: "${SHOVELS_API_KEY}"
    target_counties:
      - fips: "51107"
        name: "Loudoun County"
        state: "VA"
      - fips: "51153"
        name: "Prince William County"
        state: "VA"
    datacenter_sqft_threshold: 50000
    retry:
      max_attempts: 3
      backoff_base_seconds: 30

  earnings_transcripts:
    enabled: true
    schedule: "manual"
    fmp_api_key: "${FMP_API_KEY}"
    claude_api_key: "${ANTHROPIC_API_KEY}"
    tickers:
      phase1: ["NVDA", "TSM"]
      phase2: ["AVGO", "COHR", "LITE"]
    backfill_quarters: 8
    gpu_assumptions:
      h100_asp_usd: 25000
      h100_power_kw: 0.7
      b200_asp_usd: 35000
      b200_power_kw: 1.0
      default_utilization_pct: 0.75

  aterio_dataset:
    enabled: true
    schedule: "manual"
    datasets_dir: "/app/datasets"
    expected_columns:
      - "site_name"
      - "company"
      - "lat"
      - "lon"
      - "capacity_mw"
      - "status"

  satellite_imagery:
    enabled: false  # Phase 2
    schedule: "0 6 * * 3"
    provider: "sentinel2"  # or "planet" in Phase 2
    earth_engine_project: "${GEE_PROJECT_ID}"

staleness_thresholds:
  sec_edgar: 48  # hours
  county_permits: 336  # 14 days in hours
  earnings_transcripts: 96  # hours after expected date
  aterio_dataset: 2160  # 90 days in hours
  satellite_imagery: 720  # 30 days in hours
```

---

## Conformance to 00-DECISIONS-AND-CONSTRAINTS.md

- **§1 Decision #1:** PostgreSQL self-hosted on OCI VM (no managed service).
- **§2 Tech Stack:** SQLModel + asyncpg + Alembic, APScheduler, httpx + stamina, rapidfuzz, edgartools.
- **§3 Datasets:** sites (73 cols), events (957 rows), energy_projects (1695 rows) tables defined above.
- **§4 EDGAR APIs:** Frames pass-through endpoint; all 6 endpoint patterns leveraged by adapters.
- **§5 UX Rule:** Pipeline feeds additive UI components. No existing endpoints removed.
- **OCI %-share:** Computation defined here; canonical definition in `03-architecture-design.md`.
