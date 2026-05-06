# PRD: Data-Source Pipeline Subsystem
**Owner:** Strategic Insights team (OCI) | **Stakeholder:** the user | **Status:** Draft v1.0 | **Date:** 2026-04-28

---

## 1. Problem Statement

The Datacenter & Power Intelligence Platform currently runs on approximately 78% mock data. Specifically:

- **`mock_data.py` generates random numbers on every request.** Functions like `get_power_data()`, `get_gpu_data()`, `get_nics_optics_data()`, `get_tsmc_data()`, `get_permits_data()`, and `get_triangulation_data()` all call `random.uniform()` / `random.randint()` / `random.choice()` with no seed and no persistence. Every page load returns different values. Confidence scores are `random.uniform(0.7, 0.98)` -- they communicate nothing about actual certainty.
- **`edgar_agent.py` is live but fragile.** It fetches real SEC EDGAR data but has: (a) silent `except Exception` blocks that swallow errors and return empty lists, making failures invisible; (b) blocking synchronous `urllib.request` calls inside a FastAPI async server; (c) a 12-hour file-based cache with no invalidation strategy; (d) regex-based MW extraction that silently returns `None` on parse failures with no logging; (e) a hardcoded confidence of `0.90` that does not reflect actual parsing certainty.
- **`curated_deals.py` is the one solid asset.** 22 hand-verified deals with real SEC URLs, lat/lon coordinates, MW figures, and meaningful confidence scores. This must be preserved and extended, not replaced.
- **No permit data, no earnings transcripts, no satellite imagery, and no Aterio dataset integration exist** despite the UI displaying tabs for all of them backed by random numbers.

The result: the user and analysts cannot trust any number on the dashboard. The platform looks functional but is not. Decisions made from this data would be wrong.

---

## 2. Goals and Success Metrics

### Goals

| ID | Goal | Phase |
|----|------|-------|
| G1 | Replace every `random.*` call with either real ingested data or an explicit "no data available" state with a clear reason | Phase 1 |
| G2 | Build a source-agnostic ingestion adapter contract so all 5 data sources (and future ones) plug in identically | Phase 1 |
| G3 | Attach a lineage record to every datapoint: source URL, retrieval timestamp, parser version, raw blob reference, confidence derived from parsing certainty | Phase 1 |
| G4 | Deliver a working end-to-end pipeline for Northern Virginia geography covering SEC filings, permits, and curated deals | Phase 1 |
| G5 | Enable the triangulation engine to consume pipeline output without touching `random.*` | Phase 1 |
| G6 | Expand to all 5 sources with national coverage | Phase 2 |

### Success Metrics

| Metric | Phase 1 Target | Current State |
|--------|---------------|---------------|
| Real-data ratio (datapoints backed by a source vs total displayed) | >= 80% for NoVA tabs | ~22% |
| Source-linked datapoints (clickable to primary source) | >= 95% for delivered tabs | ~5% (only curated deals) |
| Filing freshness | <= 24 hours after SEC EDGAR publication | 12-hour cache, no staleness detection |
| Permit freshness | <= 7 days | No permit data exists |
| Earnings freshness | <= 72 hours after call | No earnings data exists |
| Zero `random.*` imports in production data paths | 0 | 47+ calls across `mock_data.py` |
| Silent exception count in data pipeline | 0 (all errors logged and surfaced) | 5 silent `except` blocks in `edgar_agent.py` |

---

## 3. User Stories

### the user (Executive Sponsor)

- **US-K1:** As the user, I want every number on the Power tab for Northern Virginia to link to its primary source (SEC filing, utility agreement, or permit record) so that I can verify claims before citing them in strategy meetings.
- **US-K2:** As the user, I want the dashboard to show "No data available -- source X not yet integrated" instead of a fake number so that I am never misled by plausible-looking fabricated data.
- **US-K3:** As the user, I want to see when each datapoint was last refreshed (e.g., "SEC filing retrieved 2026-04-27 at 14:32 UTC") so that I know how current the intelligence is.

### Strategy Analyst

- **US-A1:** As a strategy analyst, I want to click any power capacity figure and see the source filing excerpt, the parser's confidence score, and the raw text that was parsed so that I can assess reliability before including it in a briefing.
- **US-A2:** As a strategy analyst, I want permit data for Loudoun and Prince William counties refreshed weekly so that I can track construction starts versus announced deals.
- **US-A3:** As a strategy analyst, I want earnings transcript data for NVIDIA and TSMC ingested within 72 hours of each quarterly call so that I can update GPU supply estimates promptly.
- **US-A4:** As a strategy analyst, I want a single "Sources" view that shows every active data source, its last successful ingestion, record count, and any current errors so that I can understand pipeline health at a glance.

### Capacity Planning

- **US-C1:** As a capacity planner, I want the triangulation engine to consume only pipeline-sourced data (never random values) so that the power-vs-compute gap calculation for NoVA is grounded in reality.
- **US-C2:** As a capacity planner, I want entity resolution to join SEC filings, permits, and curated deals to the same canonical company/site/geography IDs so that I can see a unified view per location.
- **US-C3:** As a capacity planner, I want historical backfill of SEC filings back to 2023-01-01 so that I can analyze trends, not just the current snapshot.

---

## 4. Data Source Requirements

### 4.1 SEC EDGAR 8-K / 10-K Filings

**Current state:** Partially built in `edgar_agent.py`. Functional but brittle.

**(a) Parser interface:**

```
Input:  CIK (string), form_type ("8-K" | "10-K" | "10-Q"), date_range (start, end)
Output: List[FilingRecord]

FilingRecord:
  - company_canonical_id: str       # Resolved to canonical company ID
  - cik: str
  - form_type: str
  - filing_date: date
  - accession_number: str
  - edgar_url: str                  # Direct link to filing document
  - capacity_mw: Optional[int]     # Extracted power figure
  - energy_source: Optional[str]   # Nuclear, solar, wind, gas, mixed
  - counterparty: Optional[str]    # The other party in the deal
  - excerpt: str                   # Relevant text passage (max 1000 chars)
  - raw_blob_ref: str              # S3/local path to cached raw HTML
  - confidence: float              # 0.0-1.0, derived from: (a) did regex match? (b) how specific was the match? (c) were multiple corroborating signals found?
  - parser_version: str            # Semantic version of the parser that produced this record
  - retrieved_at: datetime         # UTC timestamp of retrieval
```

**(b) Freshness SLA:** <= 24 hours after filing appears on EDGAR. Check EDGAR full-text search index every 6 hours via scheduled job (not on user request).

**(c) Failure modes and retry strategy:**

| Failure | Detection | Response |
|---------|-----------|----------|
| EDGAR API returns 429 (rate limit) | HTTP status code | Exponential backoff: 1s, 2s, 4s, 8s, max 3 retries. Log warning. |
| EDGAR API returns 5xx | HTTP status code | Retry 3x with 10s backoff. After 3 failures, mark source as degraded. Alert. |
| Network timeout (>20s) | Socket timeout | Retry 2x. Fall back to cached data if available (serve stale + flag). |
| Regex MW extraction fails | `_parse_mw_from_text` returns None | Record the filing with `capacity_mw: null` and `confidence: 0.3` (we found the filing but could not parse a number). Never silently discard. |
| HTML parsing yields empty text | `_html_to_text` returns <100 chars | Log as parse failure. Store raw blob for manual review. Set `confidence: 0.1`. |

**(d) Lineage record:** Every `FilingRecord` carries: `edgar_url`, `retrieved_at`, `parser_version`, `raw_blob_ref` (path to stored raw HTML), `confidence` computed as described above. Confidence formula: `base = 0.5` if filing found; `+0.2` if MW regex matched; `+0.15` if counterparty identified; `+0.1` if energy source classified; `+0.05` if multiple corroborating keywords found. Cap at 0.99.

**(e) Entity resolution:** Map CIK to canonical `company_id` via a lookup table (ENERGY_COMPANIES + HYPERSCALERS dictionaries already exist). Geographic resolution: extract state/county from filing text or cross-reference with curated_deals lat/lon. Join key: `(company_canonical_id, state, county)`.

**(f) Backfill strategy:** On first deployment, backfill all 8-K filings with item 1.01 (material agreements) back to 2023-01-01 for all companies in ENERGY_COMPANIES and HYPERSCALERS. Backfill runs as a one-time batch job throttled to 8 req/s (below EDGAR's 10 req/s limit). Estimated volume: ~200-400 filings. Store all raw HTML blobs.

---

### 4.2 County Building Permits

**Current state:** No implementation. `get_permits_data()` in `mock_data.py` returns entirely random data with fake URLs like `https://permits.example.gov`.

**(a) Parser interface:**

```
Input:  county_fips (str), date_range (start, end), permit_type_filter (Optional[List[str]])
Output: List[PermitRecord]

PermitRecord:
  - permit_id: str                  # County-issued permit number
  - county_fips: str
  - county_name: str
  - state: str
  - lat: float
  - lon: float
  - applicant_name: str             # Raw applicant name from permit
  - company_canonical_id: Optional[str]  # Resolved (may be null if unknown applicant)
  - permit_type: str                # Construction, Electrical, Grading, Mechanical
  - filed_date: date
  - status: str                     # Approved, Pending, Under Review, Completed, Denied
  - estimated_sqft: Optional[int]
  - estimated_mw: Optional[float]   # If available from permit details
  - description: str                # Raw description from permit record
  - is_datacenter: bool             # Classification: does this look like a datacenter permit?
  - source_url: str                 # Direct link to county permit record
  - raw_blob_ref: str
  - confidence: float               # Based on: classification certainty that this is a datacenter permit
  - parser_version: str
  - retrieved_at: datetime
```

**(b) Freshness SLA:** <= 7 days. Weekly ingestion on a fixed schedule (e.g., every Monday 02:00 UTC).

**(c) Failure modes and retry strategy:**

| Failure | Detection | Response |
|---------|-----------|----------|
| Shovels.ai API unavailable | HTTP 5xx or timeout | Retry 3x with 30s backoff. If Shovels down for >24h, activate fallback: direct county portal scraping for Loudoun + Prince William. |
| Shovels.ai rate limit | HTTP 429 | Backoff per Shovels API docs. |
| County portal HTML changes (fallback scraper) | Parse yields <50% of expected fields | Alert. Mark source as degraded. Manual scraper update required. |
| Permit applicant name does not resolve to known company | Entity resolution returns null | Store record with `company_canonical_id: null`. Surface in analyst review queue. |
| Permit classification uncertain (is this a datacenter?) | Classifier confidence < 0.6 | Store with `is_datacenter: false` and `confidence` reflecting classifier score. Surface for manual review. |

**(d) Lineage record:** `source_url` (direct link to permit on county site or Shovels record ID), `retrieved_at`, `parser_version`, `raw_blob_ref`, `confidence` (based on datacenter classification score).

**(e) Entity resolution:** Applicant names on permits often differ from canonical company names (e.g., "Vadata Inc" = AWS, "Cloverleaf Infrastructure" = Microsoft, "Bowman Development" = Google). Maintain an alias table: `{alias_name: company_canonical_id}`. Start with known aliases for MSFT/AWS/GCP/Meta in NoVA. Flag unresolved names for manual triage.

**(f) Backfill strategy:** Phase 1: Backfill Loudoun County and Prince William County permits back to 2023-01-01 with datacenter-type filtering. Estimated volume: 500-2000 permits. Phase 2: Expand to Fairfax County VA, then TX/AZ/OR/IA counties.

**Vendor decision (Phase 1):**
- **Primary:** Shovels.ai API (if procurement approved). Provides structured permit data with geocoding.
- **Fallback:** Direct scraping of Loudoun County LMIS and Prince William County permit portals. Higher maintenance cost but no vendor dependency.
- **Decision needed by:** Week 1 of Phase 1. If Shovels procurement takes >2 weeks, start with fallback scraper.

---

### 4.3 Earnings Transcripts and 10-Q Filings

**Current state:** No implementation. `get_gpu_data()`, `get_nics_optics_data()`, and `get_tsmc_data()` all return random numbers.

**Target companies (Phase 1):** NVIDIA, TSMC
**Target companies (Phase 2):** Coherent, Lumentum, Broadcom

**(a) Parser interface:**

```
Input:  company_canonical_id (str), filing_type ("10-Q" | "earnings_transcript"), fiscal_quarter (str)
Output: List[EarningsRecord]

EarningsRecord:
  - company_canonical_id: str
  - fiscal_quarter: str              # e.g., "FY2026-Q1"
  - filing_type: str                 # "10-Q" or "earnings_transcript"
  - source_url: str
  - metrics: Dict[str, MetricValue]  # Keyed by metric name
  - raw_blob_ref: str
  - parser_version: str
  - retrieved_at: datetime

MetricValue:
  - value: float
  - unit: str                        # "USD_B", "units_K", "wafers", "pct", etc.
  - excerpt: str                     # Source text passage
  - confidence: float                # Parsing certainty
```

**Required metrics by company:**

| Company | Metrics to extract |
|---------|-------------------|
| NVIDIA | datacenter_revenue_usd_b, gpu_units_shipped_k (derived), datacenter_segment_growth_pct, forward_guidance_usd_b |
| TSMC | revenue_usd_b, cowos_monthly_capacity, advanced_node_utilization_pct (3nm, 5nm), capex_usd_b |
| Coherent (Phase 2) | optical_transceiver_revenue_usd_m, 800g_shipment_units_k |
| Lumentum (Phase 2) | optical_transceiver_revenue_usd_m, cloud_segment_growth_pct |
| Broadcom (Phase 2) | networking_revenue_usd_b, nic_shipment_units_k (derived) |

**(b) Freshness SLA:** <= 72 hours after earnings call or 10-Q filing date. Event-driven: trigger on SEC EDGAR RSS for 10-Q filings; trigger on earnings calendar for transcripts.

**(c) Failure modes and retry strategy:**

| Failure | Detection | Response |
|---------|-----------|----------|
| 10-Q not yet filed (after expected date) | EDGAR query returns no new filing | Retry daily for 7 days. After 7 days, alert analyst. |
| Transcript not available from free source | Scrape returns 403/404 | Fall back to 10-Q only (less granular but free). Log that transcript was unavailable. |
| Metric extraction regex/LLM fails | Expected metric key missing from output | Store partial record. Set confidence for missing metrics to 0.0. Alert. |
| Revenue-to-units derivation uncertain | Assumption-dependent (ASP varies) | Store both raw revenue AND derived units. Tag derived values with `is_derived: true` and document assumptions (e.g., "assumed H100 ASP of $25K"). |

**(d) Lineage record:** Standard lineage fields plus `assumptions` dict for any derived metrics (e.g., GPU ASP used in revenue-to-units conversion).

**(e) Entity resolution:** Straightforward -- these are known public companies. Map by ticker/CIK. The challenge is mapping NVIDIA GPU shipments to specific hyperscaler buyers (not disclosed). This is an inference, not a parsing problem -- flag accordingly.

**(f) Backfill strategy:** Backfill NVIDIA and TSMC 10-Q filings back to Q1 2023 (8 quarters each = 16 filings). Earnings transcripts: backfill where freely available (Seeking Alpha, Motley Fool archives). Estimated volume: 16-32 documents.

---

### 4.4 Aterio Excel Datasets

**Current state:** Sample file(s) exist in `datasets/` directory but are not wired into any pipeline.

**(a) Parser interface:**

```
Input:  file_path (str), sheet_name (Optional[str])
Output: List[AterioRecord]

AterioRecord:
  - site_id: str                     # Aterio's site identifier
  - company_canonical_id: Optional[str]  # Resolved from Aterio company name
  - site_name: str
  - lat: float
  - lon: float
  - county: Optional[str]
  - state: Optional[str]
  - country: str
  - capacity_mw: Optional[float]
  - status: str                      # Operational, Under Construction, Planned
  - year_opened: Optional[int]
  - raw_blob_ref: str                # Path to stored Excel file
  - confidence: float                # Based on: how many fields were populated and passed validation
  - parser_version: str
  - retrieved_at: datetime
```

**(b) Freshness SLA:** Manual upload cadence. When a new Aterio file arrives, ingest within 24 hours. No automated pull (Aterio is not an API -- it is a dataset delivered as Excel files).

**(c) Failure modes and retry strategy:**

| Failure | Detection | Response |
|---------|-----------|----------|
| Excel schema changes (columns renamed/reordered) | Column header validation fails | Reject file. Alert analyst with diff of expected vs actual headers. |
| Missing required fields (lat/lon, capacity) | Null check on required columns | Ingest row with nulls. Set `confidence` proportional to field completeness. |
| Duplicate sites (same site in Aterio and curated_deals) | Deduplication check on (lat, lon, company) within 0.01 degree | Merge: prefer curated_deals data (higher confidence), supplement with Aterio fields not in curated_deals. |

**(d) Lineage record:** `raw_blob_ref` = path to stored Excel file. `retrieved_at` = upload timestamp. `parser_version` = Excel parser version. `source_url` = "Aterio Dataset v{version}" (no URL -- file-based source).

**(e) Entity resolution:** Map Aterio company names to canonical IDs. Aterio may use different naming conventions. Maintain alias table. Geographic resolution: Aterio provides lat/lon; reverse-geocode to county/state using a geocoding library.

**(f) Backfill strategy:** Ingest all existing files in `datasets/` as the initial load. This is the full backfill -- Aterio data is a point-in-time snapshot, not a time series.

- **Aterio datacenter inventory** (§3 of 00-DECISIONS-AND-CONSTRAINTS.md): `data_center_inventory_20260428.csv` (73 cols) as canonical site seed; Data Dictionary events sheet (957 rows) for Events view; Energy Project Inventory (1695 rows) for Energy Supply tab.

---

### 4.5 Satellite Imagery (Planet Labs or Maxar)

**Current state:** No implementation. `get_satellite_sites()` in `mock_data.py` returns hand-curated site metadata (this is actually good data -- real sites with real coordinates and plausible milestones) but no actual imagery or change detection.

**(a) Parser interface:**

```
Input:  site_coordinates (lat, lon), bounding_box_km (float), date_range (start, end), resolution_m (float)
Output: List[SatelliteRecord]

SatelliteRecord:
  - site_canonical_id: str           # Linked to canonical site ID
  - capture_date: date
  - image_ref: str                   # S3 path to stored image
  - thumbnail_ref: str               # S3 path to thumbnail for UI
  - resolution_m: float
  - cloud_cover_pct: float
  - change_detection: Optional[ChangeDetection]
  - source: str                      # "Planet Labs" or "Maxar"
  - source_url: str                  # API reference or order ID
  - confidence: float                # Image quality + change detection certainty
  - parser_version: str
  - retrieved_at: datetime

ChangeDetection:
  - construction_activity_score: float  # 0.0-1.0
  - area_cleared_sqm: Optional[float]
  - structures_detected: int
  - delta_vs_previous: str              # "new_clearing", "foundation", "structure_rising", "no_change"
```

**(b) Freshness SLA:** TBD pending vendor selection and budget. Proposed: monthly for active construction sites, quarterly for operational sites. Daily is cost-prohibitive for Phase 1.

**(c) Failure modes and retry strategy:**

| Failure | Detection | Response |
|---------|-----------|----------|
| Cloud cover >80% | Metadata check | Discard image. Request next available clear capture. |
| API quota exceeded | HTTP 429 | Queue request for next billing cycle. |
| Change detection model uncertain | Confidence < 0.5 | Store image but flag change_detection as unreliable. Surface for manual review. |
| Vendor API down | HTTP 5xx | Retry 3x. Satellite is not time-critical; retry next day. |

**(d) Lineage record:** Image stored as blob with S3 path. Metadata includes capture date, resolution, cloud cover. Change detection includes model version.

**(e) Entity resolution:** Sites are identified by coordinates. Match to canonical site ID via nearest-neighbor lookup against known datacenter coordinates from curated_deals + Aterio.

**(f) Backfill strategy:** Phase 2. Request historical imagery (quarterly intervals back to 2023) for top 10 NoVA sites. Expensive -- budget approval required before execution.

**Vendor decision (not Phase 1):**
- Planet Labs: Lower cost per km2, daily revisit, 3-5m resolution. Better for change detection cadence.
- Maxar: Higher resolution (30cm), less frequent. Better for detailed site analysis.
- Recommendation: Defer to Phase 2. Use `get_satellite_sites()` curated metadata (it is real) as the Phase 1 satellite tab, clearly labeled as "site metadata only -- imagery coming Phase 2."

---

## 5. Source-Agnostic Ingestion Adapter Contract

Every data source must implement the following interface. This ensures the pipeline, storage layer, and triangulation engine can treat all sources uniformly.

```
Interface: DataSourceAdapter

  name() -> str
      # Human-readable source name, e.g., "SEC EDGAR 8-K"

  source_id() -> str
      # Machine identifier, e.g., "sec_edgar_8k"

  version() -> str
      # Semantic version of this adapter, e.g., "1.2.0"

  schedule() -> ScheduleConfig
      # Returns cron expression or event trigger definition
      # e.g., {"type": "cron", "expression": "0 */6 * * *"}
      # e.g., {"type": "event", "trigger": "sec_rss_new_filing"}

  fetch(params: FetchParams) -> RawPayload
      # Retrieves raw data from the source.
      # params includes: date_range, entity_filter, geography_filter
      # Returns: raw bytes/text + metadata (content_type, source_url, retrieved_at)
      # MUST NOT silently swallow exceptions.
      # MUST raise SourceUnavailableError, RateLimitError, or ParseError.

  parse(raw: RawPayload) -> List[NormalizedRecord]
      # Transforms raw data into typed records.
      # Each NormalizedRecord includes all lineage fields.
      # Partial results are acceptable (return what you can, log what you cannot).

  validate(records: List[NormalizedRecord]) -> ValidationResult
      # Runs quality checks: schema compliance, null counts, anomaly detection.
      # Returns: pass/fail, issue list, record-level confidence adjustments.

  entity_resolve(records: List[NormalizedRecord], resolver: EntityResolver) -> List[NormalizedRecord]
      # Resolves raw names to canonical company/site/geo IDs.
      # Unresolved entities are flagged, not discarded.
```

**NormalizedRecord base schema (all sources extend this):**

```
NormalizedRecord:
  - record_id: str (UUID)
  - source_id: str
  - source_url: str
  - retrieved_at: datetime (UTC)
  - parser_version: str
  - raw_blob_ref: str
  - confidence: float (0.0 - 1.0)
  - confidence_rationale: str         # Human-readable explanation of score
  - company_canonical_id: Optional[str]
  - site_canonical_id: Optional[str]
  - geo: Optional[GeoRef]            # {county, state, country, lat, lon}
  - effective_date: date              # When this data applies (filing date, permit date, etc.)
  - ingested_at: datetime (UTC)       # When this record entered our store
  - record_type: str                  # "filing", "permit", "earnings", "dataset_row", "satellite"
```

**Error handling contract:**
- Adapters MUST NOT use bare `except Exception: pass` or `except Exception: continue`.
- All exceptions must be caught as specific types and logged with: source_id, operation, error class, error message, and any partial context.
- Transient errors (network, rate limit) must raise retryable error types.
- Parse errors must be logged and result in partial records with reduced confidence, not empty results.

---

## 6. Triangulation Layer Consumption

The triangulation engine computes the gap between contracted power and estimated compute deployment. It reads from the pipeline as follows:

### Layer 1: Contracted Power (GW) per Company per Geography

**Pipeline sources consumed:**
- `curated_deals.py` records filtered by geography (primary, highest confidence)
- SEC EDGAR `FilingRecord` where `capacity_mw` is not null
- Aterio `AterioRecord` where `capacity_mw` is not null

**Aggregation logic:**
1. Group by `(company_canonical_id, state)`.
2. Sum `capacity_mw` across all sources, deduplicating by deal ID (curated_deals `id` field) or `(company, counterparty, capacity_mw, date)` tuple.
3. When the same deal appears in multiple sources, prefer the source with the highest confidence. Do not double-count.
4. Output: `contracted_gw_by_company_geo: Dict[(company_id, state), float]`

**What changes from current state:** Currently `get_triangulation_data()` generates `contracted_gw = random.uniform(1.5, 8.0)`. After Phase 1, this value comes from the aggregation above.

### Layer 2: Estimated Deployed GPUs x Power Draw

**Pipeline sources consumed:**
- NVIDIA `EarningsRecord` metrics: `datacenter_revenue_usd_b`, `gpu_units_shipped_k`

**Aggregation logic:**
1. Take NVIDIA datacenter revenue for the trailing 4 quarters.
2. Derive shipped GPU units using assumed ASP (exposed as a user-adjustable parameter, default $25K for H100-class).
3. Estimate power draw: `shipped_units * power_per_gpu_kw * assumed_utilization_pct`.
4. Power per GPU is model-dependent (H100 = 0.7 kW TDP; B200 = 1.0 kW TDP). Default assumption table maintained in config.
5. Output: `estimated_gpu_power_gw: float` with full assumption chain documented.

**What changes:** Currently `deployed_gpu_k = random.randint(20, 200)`. After Phase 1, this is derived from NVIDIA filings with explicit assumptions surfaced to the user.

### Layer 3: NIC and Optics Validation

**Pipeline sources consumed (Phase 2):**
- Broadcom, Coherent, Lumentum `EarningsRecord` metrics

**Phase 1 behavior:** This layer is not populated in Phase 1. The triangulation engine shows "NIC/optics validation: not yet available" instead of random numbers. The `correlation_score` field currently returned by `get_nics_optics_data()` (a random float) is removed entirely.

### Layer 4: County Permit Data (Ground Truth)

**Pipeline sources consumed:**
- `PermitRecord` filtered to `is_datacenter = true` and target geography

**Aggregation logic:**
1. Group by `(county_fips, company_canonical_id)`.
2. Count permits by status (Approved, Under Construction, Completed).
3. Sum `estimated_sqft` where available.
4. Cross-reference with L1 contracted power: flag companies with power contracts but no permits (announced but not building) or permits but no power contracts (building without disclosed power source).
5. Output: `permit_signal_by_company_county: Dict[(company_id, county), PermitSummary]`

**What changes:** Currently `permit_signals = random.randint(3, 18)`. After Phase 1, this is a real count from county records.

### Consumption contract

The triangulation engine MUST:
1. Accept a `TriangulationInput` object assembled from pipeline data, never call `random.*`.
2. For any layer with no data, output `null` with a reason string, not a fabricated number.
3. Propagate confidence: triangulation confidence = `min(L1_confidence, L2_confidence, ...)` across the layers that contributed. Missing layers reduce overall confidence.
4. Return a `TriangulationResult` with per-layer source citations.

---

## 7. Phase 1 Cut: Northern Virginia MVP

### In scope

| Component | Specifics |
|-----------|-----------|
| Geography | Loudoun County VA (FIPS 51107), Prince William County VA (FIPS 51153) |
| SEC EDGAR | Harden `edgar_agent.py`: async I/O, structured error handling, lineage records. Backfill 2023-01-01 to present. |
| Curated deals | Keep `curated_deals.py` as-is. Add adapter wrapper to emit `NormalizedRecord` format. Filter to VA deals for NoVA view. |
| Permits | Integrate Shovels.ai (or fallback scraper) for Loudoun + Prince William. Weekly cadence. Datacenter filtering. |
| Earnings | NVIDIA + TSMC 10-Q ingestion. Backfill 8 quarters. |
| Aterio | Ingest existing Excel file(s) from `datasets/`. Wire into entity resolution. |
| Satellite | Use existing `get_satellite_sites()` curated metadata for NoVA sites. Label as "site metadata only." No imagery API in Phase 1. |
| Storage | **PostgreSQL + SQLModel** (self-hosted on OCI VM, Decision #1). JSONB for semi-structured payloads. Raw blob storage on local filesystem (migrate to S3 in Phase 2). |
| Triangulation | L1 (real) + L2 (real with assumptions) + L3 (not available) + L4 (real for NoVA). |
| Mock elimination | Remove all `random.*` calls from data paths. `mock_data.py` may remain for development/testing only, gated behind an env flag. |

### Out of scope for Phase 1

- Geographies beyond Loudoun and Prince William counties
- Coherent, Lumentum, Broadcom earnings ingestion (Phase 2)
- Satellite imagery API integration (Phase 2)
- SemiAnalysis, CleanView, datacentermap.com integration
- ML-based permit classification (use keyword rules in Phase 1)
- Real-time streaming ingestion (batch is sufficient)
- Multi-user access control

### Phase 1 timeline estimate

| Week | Deliverable |
|------|------------|
| 1 | Adapter contract finalized. EDGAR agent refactored (async, error handling, lineage). Backfill job runs. |
| 2 | Permit ingestion (Shovels or scraper) for Loudoun + Prince William. Entity resolution alias table seeded. |
| 3 | NVIDIA + TSMC earnings parser. Aterio Excel ingestion. Storage layer with lineage. |
| 4 | Triangulation engine rewired to consume pipeline. Mock data gated behind flag. |
| 5 | Integration testing. Source-link every datapoint in NoVA tabs. Confidence score audit. |
| 6 | Buffer / polish. the user demo. |

---

## 8. Current State Assessment

### `edgar_agent.py` -- Live but Fragile

| Issue | Severity | Location | Impact |
|-------|----------|----------|--------|
| Silent `except Exception` returning empty list | High | `_get_material_8ks()` line 88-89 | EDGAR failures are invisible. Users see "no deals" when the real problem is a network error or schema change. |
| Silent `except Exception: continue` in main loop | High | `fetch_real_8k_deals()` line 189 | Same as above, per-company. One company's failure silently skips it. |
| Silent `except Exception: pass` for Amazon 10-K | High | `fetch_real_8k_deals()` line 198 | Amazon energy commitment extraction silently fails. |
| Silent `except Exception: return ""` in `_extract_power_context()` | High | Line 130-131 | HTML fetch failure returns empty string, recorded as "no context" rather than "fetch failed." |
| Blocking synchronous `urllib.request` | Medium | `_fetch()` line 46 | Blocks the FastAPI event loop. Under load, one slow EDGAR response blocks all other requests. |
| 12-hour file cache with no invalidation | Medium | `CACHE_TTL_HOURS = 12` | Stale data served for up to 12 hours. No way to force refresh. No cache versioning. |
| Hardcoded `confidence: 0.90` / `0.95` | Medium | Lines 188, 240 | Confidence does not reflect parsing quality. A filing where regex matched "megawatt" gets the same score as one where nothing matched. |
| Regex MW extraction without fallback | Low | `_parse_mw_from_text()` | Returns None silently. No logging of what text was attempted. |
| `time.sleep(0.12)` in sync code | Low | Lines 166, 168 | Blocks thread. Should be async sleep or handled by rate limiter. |

### `mock_data.py` -- Must Be Eliminated from Production Paths

| Function | Random calls | What it fakes |
|----------|-------------|---------------|
| `get_power_data()` | `random.uniform` x3 per row (70 rows) | GW total, contracted, operational, confidence |
| `get_power_timeseries()` | `random.uniform` x2 per datapoint | Base GW, quarterly increment |
| `get_gpu_data()` | `random.randint` x6+, `random.uniform` x8 | GPU shipped, deployed, inventory, revenue, units implied |
| `get_nics_optics_data()` | `random.randint` x4, `random.uniform` x1 per quarter | InfiniBand, Ethernet, 400G, 800G shipments, correlation score |
| `get_tsmc_data()` | `random.randint` x3, `random.uniform` x1, `random.choice` x1 per quarter | Wafer counts, utilization, CoWoS capacity, constraint flag |
| `get_permits_data()` | `random.sample`, `random.choice` x3, `random.randint` x2, `random.uniform` x1 per permit | Company assignment, permit type, status, sqft, MW |
| `get_triangulation_data()` | `random.uniform` x4, `random.randint` x2 per region | Contracted GW, deployed GPUs, NIC score, permit signals, confidence |
| `get_satellite_sites()` | 0 | This function is actually good -- returns curated real data. Keep it. |

**Total:** ~47 `random.*` calls generating new fake data on every page load.

### `curated_deals.py` -- Solid Foundation, Keep and Extend

- 22 hand-verified deals with real SEC URLs, press release links, lat/lon, MW, and meaningful confidence scores (0.85-0.99).
- Covers Microsoft, Amazon, Google, Meta, Oracle.
- Mix of nuclear, renewable, grid, and AI infrastructure deals.
- Includes 2026 announcements (fresh).
- **Action:** Wrap in adapter interface. Do not modify the data. Add new deals via the same format as they are discovered by the EDGAR pipeline.

---

## 9. Resolved Decisions

All open questions are now resolved. See [00-DECISIONS-AND-CONSTRAINTS.md](00-DECISIONS-AND-CONSTRAINTS.md) §1.

| # | Former Question | Resolution |
|---|---|---|
| 1 | PostgreSQL hosting | Self-hosted on this OCI VM. No managed service. |
| 2 | SEC EDGAR approach | Official `data.sec.gov` REST APIs per §4 of the brief. |
| 3 | OCI tracking | Full participant in every pillar with %-share KPI. |
| 4 | Shovels.ai vs county scraping | Shovels.ai primary ($599/mo), VA Open Data fallback. |
| 5 | Transcript source | Financial Modeling Prep ($29-99/mo) + LLM extraction. |
| 6 | Satellite source | Sentinel-2 via GEE (free, Phase 1). Maxar deferred. |
| 7 | Auth | No auth in v1. |

---

## 10. Acceptance Criteria (Phase 1 Definition of Done)

### Pipeline infrastructure

- [ ] Source-agnostic adapter interface is defined and documented. All 4 Phase 1 adapters (EDGAR, Permits, Earnings, Aterio) implement it.
- [ ] Every `NormalizedRecord` includes: `source_url`, `retrieved_at`, `parser_version`, `raw_blob_ref`, `confidence`, `confidence_rationale`.
- [ ] Raw blobs (HTML, Excel, JSON) are persisted for every ingested record and can be retrieved by `raw_blob_ref`.
- [ ] No `random.*` calls exist in any production data path. Grep for `random.uniform`, `random.randint`, `random.choice`, `random.sample` in non-test files returns zero hits.
- [ ] `mock_data.py` is either deleted or gated behind `MOCK_DATA=1` environment variable, defaulting to off.

### SEC EDGAR

- [ ] `edgar_agent.py` has zero bare `except Exception` blocks. All exceptions are caught by specific type and logged with source context.
- [ ] EDGAR fetches use async HTTP (`httpx` per locked stack §2.1), not blocking `urllib.request`.
- [ ] Backfill completed: all 8-K item 1.01 filings from 2023-01-01 to present for ENERGY_COMPANIES + HYPERSCALERS are stored with lineage.
- [ ] Confidence scores reflect parsing quality (not hardcoded). A filing where MW was extracted has higher confidence than one where extraction failed.
- [ ] Scheduled job runs every 6 hours, ingesting new filings within 24 hours of EDGAR publication.

### Permits

- [ ] Loudoun County and Prince William County permit data ingested for 2023-01-01 to present.
- [ ] Datacenter-relevant permits filtered (keyword-based classification in Phase 1).
- [ ] At least 3 hyperscaler shell company names resolved to canonical IDs (e.g., Vadata -> AWS).
- [ ] Weekly refresh job operational.
- [ ] Each permit record links to county source URL or Shovels record ID.

### Earnings

- [ ] NVIDIA 10-Q filings for trailing 8 quarters ingested with `datacenter_revenue_usd_b` extracted.
- [ ] TSMC 10-Q filings for trailing 8 quarters ingested with `cowos_monthly_capacity` or `advanced_node_utilization_pct` extracted.
- [ ] Derived metrics (GPU units from revenue) are tagged `is_derived: true` with assumptions documented.

### Aterio

- [ ] All Excel files in `datasets/` ingested into normalized store.
- [ ] Schema validation runs on ingest; mismatched files are rejected with a clear error.
- [ ] Aterio sites matched to canonical company IDs where possible.

### Triangulation

- [ ] L1 (contracted power) computed from curated_deals + EDGAR for NoVA. No random values.
- [ ] L2 (GPU power draw) computed from NVIDIA earnings. Assumptions exposed.
- [ ] L3 returns "not available" (not random numbers).
- [ ] L4 (permits) computed from real permit data for NoVA.
- [ ] Triangulation result includes per-layer source citations.
- [ ] Overall triangulation confidence is computed from input layer confidences, not `random.uniform()`.

### UI integration

- [ ] Every datapoint displayed in the Power, Permits, and Triangulation tabs for the NoVA geography links to a source (clickable URL or citation).
- [ ] Tabs without real data show "Data source not yet integrated" instead of charts with random numbers.
- [ ] A "Data Freshness" indicator shows when each source was last successfully ingested.

### Observability

- [ ] Ingestion errors are logged to structured logs (JSON format) with: source_id, error_type, error_message, timestamp.
- [ ] A `/api/pipeline/health` endpoint returns status of each adapter: last_run, records_ingested, errors, next_scheduled_run.
- [ ] Alert mechanism (at minimum: log line at ERROR level) fires when any adapter fails 3 consecutive runs.

---

## Conformance to 00-DECISIONS-AND-CONSTRAINTS.md

- **§1 Decisions 1-5:** All reflected in Section 9 above.
- **§2 Tech Stack:** PostgreSQL + SQLModel, APScheduler, httpx, rapidfuzz, edgartools.
- **§3 Datasets:** Aterio CSV, events, energy projects referenced as Phase 1 ingest sources.
- **§4 EDGAR APIs:** Full endpoint set (submissions, companyfacts, frames, EFTS, bulk ZIPs).
- **§5 UX Rule:** Pipeline feeds additive UI components only.
