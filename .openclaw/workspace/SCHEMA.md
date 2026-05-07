# Strategic Insights Warehouse — Schema Reference

## Overview

This Postgres database (`strategic_insights`, owner `sit_app`) is the warehouse for the OCI Datacenter & Power Intelligence Platform. It tracks:

- **Hyperscaler datacenter buildout** — sites, operators, end users, capacity in MW.
- **Power supply** — energy projects (solar/gas/nuclear/wind PPAs), generator permits (EPA ECHO + state air permits + PJM ISO queue), county building permits.
- **Corporate intel** — SEC EDGAR filings (10-K/10-Q/8-K) parsed for power-contract and vendor-supply mentions, plus IR press releases.
- **Entity resolution** — canonical `companies` joined to raw permittee/buyer/seller strings via `company_aliases` and `site_aliases`.
- **AI-insights pipeline state** — agentic synthesis sessions, persisted insights, chart specs, citations, message history, weekly briefs.

**Grain summary** (most-important fact tables):

| Table | Grain | Approx rows |
|---|---|---|
| `sites` | one row per data-center building (Aterio's 73-col CSV) | 6,973 |
| `events` | one row per (site, event) — announcement/start/activation/expansion | 13,304 |
| `site_company_associations` | one row per (site, company, role, source) | 15,153 |
| `generator_permits` | one row per (source registry, source_permit_id) | 4,150 |
| `building_permits` | one row per (county source, source_permit_id) | 347 |
| `energy_projects` | one row per generation-project (PPA-grain) | 84 |
| `edgar_extractions` | one row per (accession_number, deal_index) — N rows per filing for multi-deal 10-Q/8-K | 104 |
| `companies` | one canonical company per row | 1,254 |
| `ai_insight` | one row per insight emitted by a synthesis session | 146 |

### `query_database` allow-list / sandbox

The `query_database` MCP tool body lives at `backend/agents/insights/tools/query_database.py` and gates SQL through `backend/agents/insights/tools/sql_gate.py` (`validate_sql`). The gate is **AST-based via sqlglot**; it allows:

- Exactly **one** statement per call.
- `SELECT` root, optionally wrapped in `WITH` / `UNION`.
- Aggregates, window functions, JOINs, GROUP BY, ORDER BY, allowlisted scalar/date functions.
- Any table outside `pg_*` and `information_schema.*`.

It rejects:

- DDL / DML (`INSERT/UPDATE/DELETE/MERGE/CREATE/DROP/ALTER/TRUNCATE/GRANT/REVOKE/SET/COPY`).
- Multi-statement payloads.
- `pg_sleep`, `pg_read_file`, `pg_ls_dir`, `pg_advisory_*`, `dblink*`, `lo_import/export`, `current_setting`, `set_config`.
- Any reference to `pg_*` or `information_schema.*` tables.

A hard **`LIMIT 10000`** is auto-attached if missing, or clamped if the query asks for more. Statement timeout is **5000 ms** (set on the role and re-set on each connection). The connection runs as the `ai_agent` read-only role.

There is **no per-table allow-list** beyond the schema check — the agent can SELECT from any user table in `public`. The intended public surface for the insights agent is documented in `backend/agents/insights/prompts/qa_global_rules.md` (loaded as the QA system prompt) — sites, generator_permits, energy_projects, edgar_extractions, companies, events. The agent CAN go beyond that, but the rest are mostly empty / stale (see "Stale & empty tables" below).

### Naming conventions

- All identifiers are `snake_case`.
- Surrogate primary keys are `bigint id` with sequence default; AI-pipeline tables (`ai_session`, `ai_insight`, `agent_*`, `insight_thread`, `insight_subscription`, `skill_invocation`, `skill_reference`) use `uuid` PKs.
- Foreign keys are `<table_singular>_id` (e.g. `site_id`, `company_id`, `session_id`, `insight_id`).
- Internal timestamps are `created_at` / `updated_at`, both `TIMESTAMP WITHOUT TIME ZONE` (UTC) on warehouse tables; AI-pipeline tables use `TIMESTAMP WITH TIME ZONE`.
- Source-side timestamps preserved as `record_created_at` / `record_updated_at` / `updated_at_source` (sites only).
- Power capacity is `MW` everywhere except `energy_contract_mwh_million` on `curated_deals`. Costs are USD (no thousands scaling).
- `state_code` is 2-letter US (sometimes `varchar(10)` to allow non-US in `sites`/`data_coverage`); `country_code` is ISO; `county_fips` is the 5-digit FIPS string.

### Stale & empty tables (avoid querying these)

The following tables exist but have ~0 rows or no recent inserts. Querying them costs the agent a turn for nothing.

| Table | Row count | Status |
|---|---|---|
| `anomalies` | 0 | `_anomaly_detection` cron runs daily (last 2026-05-06) but no signals cross the 2σ threshold yet. Used by hypothesizer's `anomalies_today` section, currently always empty. |
| `transcript_metrics` | 0 | Earnings-call metrics table — never wired to an ingestion adapter. |
| `agent_tool_call` | 0 | Agentic tool-call audit table — agentic loop currently writes to `agent_message.tool_calls` JSONB instead. Schema present, never populated. |
| `skill_invocation` | 0 | Per-skill audit row — schema present, currently bypassed by the OpenClaw forwarder. |
| `skill_reference` | 0 | pgvector(3072) embedding chunks for skill RAG — embeddings pipeline not deployed yet. |
| `insight_subscription` | 0 | V2 follow-up button writes here; V3 cron consumes — V3 not deployed. |
| `transcript_metrics`, `permit_parent_review_queue` (88 rows but workflow inactive), `data_lineage` (36 rows, sparse) | low | Used by ingestion only — agent should not query unless the user explicitly asks about ingestion provenance. |

### Important schema gotchas

1. **`generator_permits.parent_company` is NOT a real column** — `backend/agents/insights/prompts/qa_global_rules.md:121` documents it as a "virtual column", but `SELECT parent_company FROM generator_permits` errors. Roll up parents via `JOIN companies c ON c.id = generator_permits.resolved_company_id` and group by `c.canonical_name`.
2. **`events.event_date` has bizarre future values** — max date is `2048-06-30`; the column accepts whatever the source CSV said. When filtering "recent events", clamp upper bound to today (`event_date <= CURRENT_DATE`).
3. **`sites` date columns are stored as `varchar`, not `date`** — `announced_date`, `construction_start_date`, `construction_finished_date`, `activation_date`, `cancelled_date`, `project_withdrawn_date`, `latest_satellite_picture_date`, `estimated_active_date_by`. Some are partial ("2024", "Q3 2025"). Cast with `to_date` at your peril; prefer `record_updated_at`/`updated_at_source` for true timestamps.
4. **`sites.power_capacity_mw` is the canonical MW column** — there are also `prov_pub_tot_power_capacity_mw` (operator-published), `aterio_est_mw` (Aterio's estimate), and `aterio_est_mw_lower`/`aterio_est_mw_upper`. Use `power_capacity_mw` unless the question is specifically about operator disclosure vs estimate.
5. **`sites.end_user_companies` is a comma-separated string, not an array** — to count tenants use `array_length(string_to_array(end_user_companies, ','), 1)`. Special sentinel values: `NULL`, empty string, `'null'`, `'[]'`. The hypothesizer treats all four as "no end user".
6. **`sites.provider_name` includes `'Company Not Disclosed'` (1,355 rows)** — exclude this when ranking operators by MW.
7. **`edgar_extractions` no longer has `UNIQUE(accession_number)`** — multi-deal filings (Constellation Q3 10-Q with 3 power items) produce N rows sharing one accession, disambiguated by `deal_index`. Use `UNIQUE(accession_number, deal_index)` if dedup needed.
8. **`companies` has 1,254 rows but most are unresolved permittee LLCs.** When the user asks "which big-tech …", filter by `ticker IN ('AMZN','MSFT','GOOGL','META','ORCL','AAPL','NVDA')` or by canonical_name in a hard-coded set; do NOT trust `parent_company_id` (sparse).
9. **Brief-runs / ai_session timestamp drift** — `ai_session.started_at` is `TIMESTAMPTZ`, `brief_runs.generated_at` is `TIMESTAMP` (no tz). When joining or comparing, normalize to UTC.

---

## Domain: Companies and corporate hierarchy

### `companies`

**What it represents:** the canonical company entity. Authority for "what is the same legal company" across all sources.
**Grain:** one row per canonical company.
**Primary key:** `id` (bigint).
**Key columns:**

| column | type | meaning |
|---|---|---|
| `id` | bigint | surrogate PK |
| `canonical_name` | varchar | indexed; canonical display name (e.g. "Microsoft", "Amazon AWS") |
| `short_name` | varchar | optional shorter label |
| `ticker` | varchar(20) | indexed; stock ticker (AMZN, MSFT, …) |
| `cik` | varchar(20) | indexed; SEC CIK as 10-digit zero-padded string |
| `parent_company_id` | bigint | FK back to `companies.id` (sparse — most rows null) |
| `public_private` | varchar(20) | "public" / "private" |
| `aliases` | jsonb | denormalised alias bag; the source-of-truth join is `company_aliases` |
| `created_at`, `updated_at` | timestamp | UTC |

**Foreign keys:** `parent_company_id` → `companies.id` (self-FK, NOT enforced, sparse).
**Indexes:** `canonical_name`, `ticker`, `cik`.
**Common joins:** `companies.id = generator_permits.resolved_company_id`; `companies.id = edgar_extractions.buyer_company_id`/`seller_company_id`; `companies.id = site_company_associations.company_id`.
**Notes:** Hyperscaler examples: Microsoft, Amazon AWS, Google, Facebook (=Meta in this dataset), Oracle, Tract, Digital Realty, QTS Data Centers, STACK Infrastructure, CyrusOne. Most rows (~1100 of 1254) are unresolved permittee LLCs with no ticker/cik.

### `company_aliases`

**What it represents:** alias-to-canonical mapping per source.
**Grain:** one row per `(source, raw_name)` — UNIQUE.
**Key columns:**

| column | type | meaning |
|---|---|---|
| `company_id` | bigint | FK to `companies.id` |
| `source` | varchar(100) | which adapter saw the alias (`aterio_csv`, `epa_echo`, `edgar_llm`, …) |
| `raw_name` | varchar | the raw string from the source (e.g. "Vadata, Inc.", "Microsoft Azure FXS LLC") |
| `match_method` | varchar(50) | `exact`, `fuzzy`, `llm_seed`, … |
| `confidence` | numeric(3,2) | 0–1 |
| `evidence` | jsonb | provenance |

**Notes:** Use this when the user asks "what shell LLCs has Amazon filed permits under" — query for `source='epa_echo'` joined back to `companies.canonical_name = 'Amazon'`.

### `site_company_associations`

**What it represents:** role-edge from a site to a company (operator, end_user, equipment supplier, financier, utility, …).
**Grain:** one row per `(site_id, company_id, role, source)` — UNIQUE.
**Key columns:**

| column | type | meaning |
|---|---|---|
| `site_id` | bigint | FK to `sites.id` |
| `company_id` | bigint | FK to `companies.id` |
| `role` | varchar(30) | enum: `provider`, `provider_backer`, `end_user`, `financing`, `equipment`, `utility`, `developer`, `customer`, `permittee_llc`, `permit_parent` |
| `source` | varchar(100) | provenance — `aterio_csv` (15,150 rows) or `epa_echo` (3 rows) |
| `mw_share` | numeric | partial MW attributable to this company at this site (often null) |
| `confidence` | numeric(3,2) | resolver confidence |

**Indexes:** `site_id`, `company_id`.
**Notes:** Most rows are `role='provider'` (the operator). For "who builds for AWS", query for `provider_name='Amazon AWS'` then look up the corresponding `equipment` and `financing` rows via this table. **Currently the only roles populated at meaningful volume are `provider` (6,973), `utility` (4,272), `equipment` (2,050), `provider_backer` (841), `end_user` (526), `financing` (488).**

---

## Domain: Datacenter sites

### `sites`

**What it represents:** one data-center building (or campus, when buildings aren't broken out). Mirror of Aterio's 73-column CSV.
**Grain:** one row per building (`aterio_dc_uid` UNIQUE).
**Primary key:** `id` (bigint).
**Foreign keys:** none formal; `aterio_dc_uid` joins to `events.aterio_dc_uid`.

**Key columns — identity:**

| column | type | meaning |
|---|---|---|
| `aterio_dc_uid` | varchar(255) | UNIQUE; stable Aterio site UID, the preferred external id |
| `aterio_campus_uid` | varchar(255) | groups multi-building campuses |
| `building_name` | varchar | building label within a campus |
| `campus_name` | varchar | campus / cluster name |

**Key columns — status / lifecycle:**

| column | type | meaning |
|---|---|---|
| `stage` | varchar(50) | `Announcement`, `Construction`, `Activated`, `Cancelled`, `Withdrawn` (note: real values include things like "Active under construction" — match with `ILIKE '%active%'`) |
| `pct_construction` | float | percent complete 0–100 |
| `project_execution_likelihood` | varchar(50) | `High` / `Medium` / `Low` |
| `is_ai_facility` | boolean | flagged AI-purpose facility |
| `flg_btm_onsite_power_generation` | boolean | behind-the-meter onsite generation flag |

**Key columns — operator/customer:**

| column | type | meaning |
|---|---|---|
| `provider_name` | varchar | indexed; datacenter operator (Microsoft, Amazon AWS, Google, Facebook, Oracle, Tract, …). Exclude `'Company Not Disclosed'` for hyperscaler ranking. |
| `provider_ticker`, `provider_bloomberg_ticker` | varchar | tickers |
| `provider_public_private` | varchar(100) | label |
| `provider_backed_by` | varchar | parent / backer string |
| `end_user_companies` | varchar | comma-separated tenant names. Sentinel "no tenant" values: NULL, '', 'null', '[]'. |
| `construction_equipment_provider_companies` | varchar | comma-separated equipment vendor names (Caterpillar, Cummins, Vertiv, …) |
| `project_financing_companies` | varchar | comma-separated financing partner names |

**Key columns — geography:**

| column | type | meaning |
|---|---|---|
| `full_address` | varchar | free-text |
| `state_code` | varchar(10) | indexed; 2-letter US (sometimes longer for non-US) |
| `state_name`, `country_code`, `country_name` | varchar | label vars |
| `county_fips`, `county_name`, `city_name`, `place_fips_code`, `zip_code` | varchar | locality |
| `latitude`, `longitude` | float | decimal degrees |

**Key columns — physical / power (units in MW unless noted):**

| column | type | meaning |
|---|---|---|
| `site_acreage` | float | site footprint in acres |
| `tot_facility_space_sqft` | float | total floor area, sqft |
| `tot_datacenter_space_sqft` | float | datacenter white-space, sqft |
| `prov_pub_tot_power_capacity_mw` | float | operator-published total MW |
| `aterio_est_mw` | float | Aterio's MW estimate |
| `aterio_est_mw_lower`, `aterio_est_mw_upper` | float | MW estimate range |
| `power_capacity_mw` | float | indexed; **canonical MW field — use this** |
| `tot_project_cost` | float | USD (not USD-thousands) |
| `avg_market_power_cost` | float | USD/MWh approximate |
| `yearly_pue` | float | Power Usage Effectiveness (target ≤1.5; <1.3 is excellent) |
| `tot_num_generators` | int | backup generator count |

**Key columns — timeline (stored as `varchar`!):**

`announced_date`, `construction_start_date`, `construction_finished_date`, `activation_date`, `estimated_active_date_by`, `cancelled_date`, `project_withdrawn_date`, `latest_satellite_picture_date`. Free-text — may be partial ("Q3 2025"). Use `record_updated_at` / `updated_at_source` for real timestamp logic.

**Key columns — utility / grid:**

| column | type | meaning |
|---|---|---|
| `utility_name` | varchar | serving electric utility (Dominion, AEP, …) |
| `utility_public_private`, `utility_ticker` | varchar | label/ticker |
| `bal_auth_abbr`, `bal_auth_name` | varchar | balancing authority (PJM, ERCOT, MISO, CAISO, SERC, …) |
| `bal_auth_subregion_code`, `bal_auth_subregion_name` | varchar | subregion |

**Key columns — citations:**

| column | type | meaning |
|---|---|---|
| `datasheet_url` | varchar | Aterio datasheet URL |
| `map_url` | varchar | site map URL |
| `permit_url` | varchar | permit document URL |
| `capex_url` | varchar | capex source URL |
| `notes` | text | free-text |

**Indexes worth knowing:** `aterio_dc_uid` (unique), `aterio_campus_uid`, `provider_name`, `state_code`, `county_fips`, `power_capacity_mw`. State + provider rollups are cheap; sub-state aggregations need full table scan.

**Common joins:** `sites.aterio_dc_uid = events.aterio_dc_uid`; `sites.id = generator_permits.site_id` (sparse); `sites.id = site_company_associations.site_id`; `sites.id = site_aliases.site_id`.

**Notes:** Top operators by site count: Amazon AWS (702), Microsoft (294), Tract (230), Google (217), QTS (203), Facebook/Meta (201). Top states by total MW: TX (88GW), VA (62GW), GA (30GW), OH (27GW), UT (20GW), AZ (18GW), PA (16GW), IL (15GW).

### `events`

**What it represents:** lifecycle events at a site (announcement, permit_filed, construction_start, activation, expansion, cancellation).
**Grain:** one row per (`aterio_dc_uid`, event).
**Primary key:** `id`.
**Key columns:**

| column | type | meaning |
|---|---|---|
| `aterio_dc_uid` | varchar(255) | indexed; FK-style join to `sites.aterio_dc_uid` |
| `event_type` | varchar(50) | `announcement` (4,638), `activation` (6,960), `construction_start` (1,678), `expansion`, `cancellation` (28). NOTE: **`permit_filed` is documented but unused in current data.** |
| `event_date` | date | indexed; **CAUTION: contains future dates up to 2048-06-30** — clamp to `<= CURRENT_DATE` for "recent events" queries |
| `event_description` | text | free-text |
| `source_url` | varchar | citation URL |
| `payload` | jsonb | extras |

**Indexes:** `aterio_dc_uid`, `event_date`.
**Notes:** Useful for "recent activations" / "construction-start trend by quarter". Always join through `sites.aterio_dc_uid` to attach operator + state + MW.

### `site_aliases`

Bridge from external source-record-id to canonical site. Only 3 rows currently — most sites are joined via `aterio_dc_uid` directly. Schema: `(site_id, source, source_record_id, match_method, confidence)` UNIQUE on `(source, source_record_id)`.

---

## Domain: Power capacity / electrical (energy projects)

### `energy_projects`

**What it represents:** generation-side projects (solar / gas / nuclear / wind PPAs) — distinct from `sites` (demand side).
**Grain:** one row per generation project.
**Primary key:** `id`.
**Key columns:**

| column | type | meaning |
|---|---|---|
| `project_name` | varchar | label |
| `flg_btm_project` | bool | behind-the-meter flag |
| `developer_companies` | varchar | comma-separated developer names — group by this for "top developers by MW" (NOT by parent_company_id, which is null on this table). |
| `developer_ticker` | varchar(20) | |
| `eia_entity_ids` | jsonb | EIA entity IDs |
| `eia_entity_names` | varchar | EIA entity labels |
| `customer_companies` | varchar | comma-separated offtaker names |
| `tot_contracted_power_mw` | float | **canonical MW field for energy projects** |
| `tot_project_cost` | float | USD |
| `project_footprint_acreage`, `site_boundary_acreage` | float | acreage |
| `state_code` | varchar(2) | indexed |
| `latitude`, `longitude` | float | |
| `payload` | jsonb | the remaining 50+ Aterio columns dumped here |
| `created_at`, `updated_at` | timestamp | UTC |

**Indexes:** `state_code`.
**Notes:** Only 84 rows total — small fact table. Used by hypothesizer's `top_capacity_movers_24h` and `top_companies_by_delta_7d` sections. Recently re-touched once on 2026-04-28 — most queries against this table will return the same handful of projects.

---

## Domain: Permits and regulatory

### `generator_permits`

**What it represents:** generator-permit landing table. One row per (source registry, source_permit_id).
**Grain:** UNIQUE on `(source, source_permit_id)`.
**Primary key:** `id`.
**Key columns:**

| column | type | meaning |
|---|---|---|
| `source` | varchar(100) | indexed; the registry — `pjm` (3,631 rows, **PJM ISO interconnection queue**), `epa_echo` (500 rows), `tceq` (7), `va_open_data` (3), `socrata_ny` (1), `smoke_test` (8). **`pjm` is the dominant source — don't filter to `source='epa_echo'` if you actually want all permits.** |
| `source_permit_id` | varchar(255) | source-side identifier |
| `facility_name` | varchar | |
| `permittee_raw_name` | varchar | indexed; raw permittee LLC string (e.g. "Vadata, Inc." for an Amazon-owned shell) |
| `resolved_company_id` | bigint | FK to `companies.id` (NULL when unresolved). Use this to roll up parent-level. |
| `site_id` | bigint | indexed; FK to `sites.id` (mostly NULL — geo-joins are best-effort) |
| `state_code` | varchar(2) | indexed |
| `county_fips` | varchar(10) | 5-digit FIPS |
| `latitude`, `longitude` | float | |
| `rated_mw_total` | float | total rated generator capacity in MW (NULL on PJM ISO-queue rows!) |
| `num_units` | int | generator count |
| `fuel_type` | varchar(100) | "Diesel", "NG", "Dual-Fuel", "Solar", "Nuclear", "Wind", … |
| `permit_status` | varchar(100) | source-specific status string |
| `issued_date` | date | when issued |
| `expiry_date` | date | when expires |
| `frs_id` | varchar(100) | indexed; EPA FRS facility id (cross-source key) |
| `naics_code` | varchar(50) | NAICS industry code |
| `raw_payload` | jsonb | the full source row |
| `confidence` | numeric(3,2) | resolver confidence |

**Indexes:** `source`, `permittee_raw_name`, `state_code`, `site_id`, `frs_id`. UNIQUE `(source, source_permit_id)`.
**Common joins:** `JOIN companies c ON c.id = generator_permits.resolved_company_id` for hyperscaler roll-up.
**Notes:**
- **There is NO `parent_company` column** (the QA prompt mistakenly documents one). Always join through `resolved_company_id`.
- For "permits filed by hyperscalers", filter `c.canonical_name IN ('Amazon','Microsoft','Google','Meta','Oracle')` or `c.ticker IN (...)`.
- For PJM-ISO-queue rows, `rated_mw_total` is often NULL — capacity sits in `raw_payload->>'capacity_mw'` or similar; reach for `raw_payload` JSONB extraction.

### `building_permits`

**What it represents:** county-level building permits. Distinct from `generator_permits` (which is air/generator) — this catches the data-center construction permits at the county-clerk level.
**Grain:** UNIQUE on `(source, source_permit_id)`.
**Key columns:**

| column | type | meaning |
|---|---|---|
| `source` | varchar(40) | only two sources today: `loudoun_va` (271 rows) and `mesa_az` (76 rows). The model docstring mentions `grantwa` (Grant County WA) but no rows yet. |
| `source_permit_id` | varchar(80) | county permit number |
| `county` | varchar(80) | county name |
| `state` | varchar(2) | 2-letter |
| `jurisdiction` | varchar(80) | sub-jurisdiction within county |
| `address` | text | |
| `latitude`, `longitude` | float | |
| `permit_type` | varchar(80) | source-specific type label |
| `permit_status` | varchar(40) | "Issued", "Submitted", "Final", … |
| `applied_date`, `issued_date`, `completed_date` | date | timeline |
| `valuation_usd` | float | declared construction valuation, USD |
| `square_footage` | int | declared sq ft |
| `applicant_name` | varchar(200) | applicant — often a shell LLC; cross-reference `company_aliases` to map to a hyperscaler |
| `raw_payload` | jsonb | full source row |

**Indexes:** `(state, county)`, `issued_date`, `permit_status`. UNIQUE `(source, source_permit_id)`.
**Notes:** Used by hypothesizer's `new_permits_24h` section. **Coverage is two counties only** — don't promise national permit coverage to the user. Date range: 2008-09-03 to 2026-02-09.

### `permit_parent_review_queue`

Human-in-the-loop queue for parent-resolution adjudication. 88 rows, mostly inactive workflow. Schema: `generator_permit_id`, `permittee_raw_name`, `candidate_parents` (jsonb), `agent_run_id`, `status` ('pending'/'approved'/'rejected'/'escalated'), `reviewer_id`, `reviewer_decision`. Used by ingestion only — agent should not query.

---

## Domain: SEC EDGAR / public-filing intel

### `edgar_extractions`

**What it represents:** structured extracts from SEC EDGAR filings (10-K, 10-Q, 8-K) that match power-contract or vendor-supply heuristics.
**Grain:** one row per `(accession_number, deal_index)` — UNIQUE. Multi-deal filings produce N rows sharing one accession_number.
**Key columns:**

| column | type | meaning |
|---|---|---|
| `cik` | varchar(20) | indexed; SEC CIK as string (10-digit zero-padded) |
| `accession_number` | varchar(30) | indexed; SEC accession ("0001234567-25-000123") |
| `form_type` | varchar(10) | "10-K", "10-Q", "8-K", … |
| `filing_date` | date | indexed; when filed with SEC |
| `signing_date` | date | body-extracted contract signing date (e.g. "On January 10, 2025…") — distinct from filing_date |
| `item_codes` | varchar(100) | hit form item codes (e.g. "1.01,9.01" for 8-K) |
| `edgar_url` | varchar | direct EDGAR URL (citation source) |
| `capacity_mw` | float | extracted capacity in MW |
| `energy_source` | varchar(50) | "solar" / "gas" / "nuclear" / "wind" / "battery" / "hydro" / … |
| `buyer_raw` | varchar | raw buyer string from filing |
| `seller_raw` | varchar | raw seller string from filing |
| `buyer_canonical` | varchar | indexed; canonicalized when entity-resolution `confidence ≥ 0.90` |
| `seller_canonical` | varchar | canonicalized when confident |
| `buyer_company_id`, `seller_company_id` | bigint | FKs to `companies.id` (sparse) |
| `rejected_buyer_raw`, `rejected_seller_raw` | varchar | LLM-proposed values rejected by validator |
| `methodology` | text | MWh→MW derivation methodology note |
| `excerpt` | text | filing excerpt |
| `parser_version` | varchar(50) | "regex-v1" (legacy) or "llm-v1+" |
| `confidence` | numeric(3,2) | extractor confidence 0–1 |
| `pillar` | varchar(32) | indexed; **`power_contract` (8 rows) or `vendor_supply` (79 rows)**. NULL on 17 legacy rows. Filter by this to separate PPA filings from chip/equipment-supplier disclosures. |
| `is_power_related` | bool | indexed; `True` when LLM flags filing as power/datacenter even if no MW extracted |
| `canonical_deal_id` | varchar(20) | indexed; 16-char hash for dedup `(buyer | seller | 100MW bucket | quarter)` — same deal disclosed in 10-Q + later 8-K shares this id |
| `appearance_count` | int | how many rows share this `canonical_deal_id` (≥1) |
| `flagged_capacity` | bool | True when `capacity_mw > 100,000` (sanity guard) |
| `deal_index` | int | disambiguates multi-deal-per-filing rows (0,1,2,…) |
| `retrieved_at`, `created_at` | timestamp | UTC |

**Indexes:** `cik`, `accession_number`, `filing_date`, `pillar`, `is_power_related`, `buyer_canonical`, `canonical_deal_id`, `(canonical_deal_id, filing_date DESC)`.
**Notes:** Used by hypothesizer's `edgar_capacity_mentions_7d`. Date range: filings 2024-10-30 to 2026-05-01. To dedupe multi-disclosure deals, use `DISTINCT ON (canonical_deal_id)` keyed by latest `filing_date`.

### `press_releases`

**What it represents:** investor-relations press releases scraped from hyperscaler IR pages.
**Grain:** UNIQUE on `source_url`.
**Key columns:**

| column | type | meaning |
|---|---|---|
| `company_canon` | varchar(100) | indexed; canonical company name (Microsoft, Amazon, …) — note this is a STRING, not a FK |
| `source_url` | varchar(1024) | UNIQUE; direct release URL |
| `published_date` | date | indexed; ISO date as published |
| `title` | varchar(500) | release headline |
| `summary` | text | LLM- or heuristic-generated 1–3 sentence summary |
| `matched_terms` | varchar(300) | which keywords triggered (datacenter, power, GW, …) |
| `excerpt` | text | filing excerpt |
| `pillar` | varchar(32) | indexed; same enum as `edgar_extractions.pillar` (`power_contract`, `vendor_supply`) |
| `parser_version` | varchar(50) | "press-v1" |
| `retrieved_at`, `created_at` | timestamp | UTC |

**Indexes:** `(company_canon, published_date)`, `company_canon`, `published_date`, `pillar`.
**Notes:** 15 rows total — coverage is sparse. All 15 are `pillar='power_contract'`.

### `curated_deals`

**What it represents:** hand-curated deal table — pre-pipeline seed data, 22 rows. Used by Phase-1 routes; mostly superseded by `edgar_extractions`.
**Grain:** one row per legacy_id.
**Key columns:** `legacy_id` (UNIQUE), `buyer`, `seller`, `deal_type`, `energy_source`, `capacity_mw` (int!), `location`, `state`, `lat`, `lon`, `announced_date` (varchar, partial), `status`, `duration_years`, `headline`, `excerpt`, `source_type`, `source_url`, `edgar_url`, `confidence`, `data_source`, `energy_contract_mwh_million` (annual TWh-equivalent), `note`.
**Notes:** Stale. Don't rely on it for current intel. Capacity is **integer MW**, not float.

---

## Domain: AI Insights pipeline state

### `ai_session`

**What it represents:** one synthesis or QA session.
**Grain:** one row per session.
**Key columns:**

| column | type | meaning |
|---|---|---|
| `id` | uuid | PK |
| `status` | varchar(32) | indexed; `running`, `complete`, `degraded`, `failed` |
| `started_at` | timestamptz | indexed |
| `finished_at` | timestamptz | |
| `model` | varchar(80) | LLM identifier |
| `focus` | text | free-text focus / topic |
| `max_insights` | int | target insight count |
| `version` | varchar(8) | schema version (default 'v1') |
| `insights_emitted` | int | count of `ai_insight` rows persisted |
| `duration_ms` | int | wall-clock |
| `budget_status` | varchar(16) | `ok` / `warn` / `exceeded` |
| `created_by` | varchar(120) | `cron` / `user:<id>` / agent-id |
| `cron_run_date` | date | idempotency guard for daily cron runs (NULL on manual sessions) |
| `token_estimate` | int | post-flight token accounting |

**Indexes:** `status`, `started_at`, `(created_by, cron_run_date)`.
**Common joins:** parent of `ai_insight`, `agent_message`, `agent_chart`, `agent_tool_call`, `skill_invocation` (all ON DELETE CASCADE).

### `ai_insight`

**What it represents:** a single insight emitted by a synthesis session.
**Grain:** one row per insight (via `(session_id, idx)`).
**Key columns:**

| column | type | meaning |
|---|---|---|
| `id` | uuid | PK |
| `session_id` | uuid | indexed; FK to `ai_session.id` ON DELETE CASCADE |
| `idx` | int | ordinal within the session (1, 2, 3, …) |
| `headline` | text | ≤140 chars by convention |
| `body` | text | 1–3 sentences |
| `confidence` | varchar(16) | `weak` / `moderate` / `strong` |
| `materiality` | varchar(16) | `low` / `medium` / `high` |
| `skills_run` | jsonb | array of skill names invoked during synthesis (default `[]`) |
| `low_external_support` | bool | true if web_search returned little corroboration |
| `citation_count` | int | denormalised count of attached `agent_citation` rows |
| `web_search_calls` | int | denormalised count of web_search calls |
| `headline_embedding` | vector(3072) | pgvector embedding for cross-day "ongoing" linkage |
| `ongoing_of_id` | uuid | indexed; FK back to `ai_insight.id` — when current headline cosine-matches a prior-14-day headline at ≥0.85, points there |
| `supporting_row_ids` | jsonb | array of `"section_name:N"` strings drawn from the FactPack |
| `created_at` | timestamptz | indexed |

**Indexes:** `session_id`, `created_at`, `ongoing_of_id`.
**Common joins:** parent of `agent_citation`, `agent_chart`, `insight_thread`, `insight_subscription` (all ON DELETE CASCADE).

### `agent_message`

**What it represents:** one chat message in a session — system / user / assistant / tool.
**Grain:** one row per message.
**Key columns:**

| column | type | meaning |
|---|---|---|
| `id` | uuid | PK |
| `session_id` | uuid | indexed; FK to `ai_session.id` |
| `insight_id` | uuid | indexed; nullable; FK to `ai_insight.id` (when message is scoped to an insight chat) |
| `thread_id` | uuid | indexed; nullable; FK to `insight_thread.id` (V2 chat-thread scoping) |
| `seq` | int | 0-based ordinal within `(session_id, seq)` index |
| `role` | varchar(16) | `system`, `user`, `assistant`, `tool` |
| `content` | text | message body |
| `tool_calls` | jsonb | OpenAI-shaped tool_call objects when assistant emitted them |
| `tool_call_id` | varchar(80) | the call id this message is replying to (when role=`tool`) |
| `delete_after` | timestamptz | indexed; TTL for message-level retention |
| `event_id`, `event_name`, `event_payload` | varchar/jsonb | optional gateway-event annotation |
| `created_at` | timestamptz | |

**Indexes:** `session_id`, `(session_id, seq)`, `insight_id`, `thread_id`, `delete_after`.

### `agent_chart`

**What it represents:** persisted chart spec emitted by `emit_chart`.
**Grain:** one row per chart (`id` is a 32-char string emitted by the tool).
**Key columns:** `id` (varchar(32) PK), `session_id`, `insight_id`, `spec` (jsonb — ChartSpec v1), `data_source` (jsonb — `{tool, args, executed_sql, …}`), `row_hash` (sha256 over canonicalised rows), `created_at`.
**Indexes:** `session_id`, `insight_id`. Both FKs ON DELETE CASCADE.
**Notes:** `row_hash` ties back to the `query_database` result that fed the chart — re-running the SQL should reproduce the hash.

### `agent_citation`

**What it represents:** validated web citation attached to an insight.
**Grain:** one row per citation.
**Key columns:** `id` (uuid PK), `insight_id` (FK CASCADE, indexed), `url`, `title`, `snippet` (≤280 chars), `agree_or_disagree` (`agree` / `disagree` / `context`), `rationale`, `search_query`, `retrieved_at`, `provider` (`brave`, `tavily`, …), `created_at`.

### `agent_tool_call`

**What it represents:** per-tool-call audit trail. **CURRENTLY EMPTY (0 rows)** — agentic loop writes tool calls into `agent_message.tool_calls` JSONB instead. Schema: `id`, `session_id`, `insight_id`, `tool_call_id`, `tool_name`, `args` (jsonb), `ok`, `error_code`, `started_at`, `latency_ms`, `token_estimate`, `row_hash`. Used by ingestion only — agent should not query.

### `insight_thread`

**What it represents:** V2 chat-thread per insight (lets a user follow up on a single insight without polluting the parent session).
**Key columns:** `id` (uuid PK), `insight_id` (FK CASCADE, indexed), `session_id` (text — opaque session key from gateway), `created_at`, `last_active`, `delete_after`.

### `insight_subscription`

**What it represents:** V2 follow-up button writes here; V3 cron consumes. **CURRENTLY EMPTY** — V3 not deployed.
**Key columns:** `id` (uuid PK), `insight_id` (FK CASCADE, indexed), `criteria_json` (jsonb), `enabled` (bool), `created_at`.

### `brief_runs`

**What it represents:** weekly LLM-generated intelligence briefing. Frontend `/api/brief/latest` reads the most-recent row by `generated_at`.
**Grain:** one row per generation (typically Sunday 23:00 UTC cron).
**Key columns:** `id`, `generated_at` (timestamp, indexed DESC), `period_start` (date), `period_end` (date), `markdown` (text), `model`, `prompt_version`, `bullet_count`, `tokens_in`, `tokens_out`, `latency_ms`, `created_at`.
**Notes:** 3 rows total. The "fallback" path (when the OpenClaw round-trip fails) writes `prompt_version` ending in `+fallback`.

### `skill_invocation` & `skill_reference`

Both empty. `skill_invocation` is the per-skill audit row (would carry `session_id`, `skill_name`, `inputs_hash`, `outputs`, `latency_ms`, `fragment_mode`); `skill_reference` is the pgvector(3072) RAG chunk store keyed on `(skill_name, source_path, chunk_index)` UNIQUE on `chunk_id`. Don't query — pipeline not deployed.

---

## Domain: Source / provenance

### `ingestion_runs`

**What it represents:** audit trail per ingestion-adapter run.
**Grain:** one row per run.
**Key columns:** `id`, `adapter_name` (indexed), `adapter_version`, `started_at`, `completed_at`, `status` (`running`/`success`/`partial_failure`/`failure`), `records_fetched`, `records_normalized`, `records_stored`, `records_skipped`, `trigger`, `error_log` (jsonb), `config_snapshot` (jsonb).
**Notes:** Active adapters as of 2026-05-06: `epa_echo`, `va_open_data`, `permits_state`, `permits_county`, `edgar`, `edgar_quarterly`, `pjm_iso`, `tceq`, `socrata_ny`, `ny_dec_*` (per-county adapters), `ir_press_releases`. Internal cron jobs run as adapter `_coverage_refresh`, `_stale_check`, `_insights_daily`, `_anomaly_detection`, `_cache_cleanup`, `_weekly_brief`. To answer "is data X fresh", filter `adapter_name = ...` and check `MAX(started_at)` and `status`.

### `data_lineage`

Per-record lineage trace. 36 rows — sparse, used by ingestion only. Schema: `table_name`, `record_id`, `ingestion_run_id`, `source_url`, `retrieved_at`, `parser_version`, `confidence`, `raw_blob_ref`, `transformation` (jsonb).

### `data_coverage`

**What it represents:** per-pillar per-state-per-source coverage scorecard. Used by the platform's coverage matrix UI.
**Grain:** UNIQUE `(pillar, state_code, source)`.
**Key columns:** `pillar` (indexed; e.g. "power", "permits", "edgar"), `state_code` (indexed; "ALL" allowed), `source`, `coverage_status` (`full`/`partial`/`federal_baseline`/`pending`/`unavailable`), `record_count`, `last_ingested_at`, `freshness_sla_hours`, `notes` (text), `roadmap` (text).
**Notes:** Used by hypothesizer's `coverage_gaps` section (filters `coverage_status = 'partial'`, oldest `last_ingested_at` first). 280 rows.

### `llm_extraction_runs`

LLM-side per-call audit (separate from `ingestion_runs`, which tracks adapter-level). UNIQUE `(agent_name, input_hash)` for idempotency. Schema: `agent_name`, `model`, `prompt_version`, `input_hash`, `input_excerpt`, `output` (jsonb), `confidence`, `tool_calls`, `tokens_prompt`, `tokens_completion`, `latency_ms`, `status` (`success`/`fallback`/`error`), `error_detail`, `fallback_path`. 39 rows. Used by ingestion only.

### `transcript_metrics`

Empty — earnings-call metric extraction never wired. Schema present: `(company_id, ticker, period, period_type, metric_name, metric_category, numeric_value, text_value, source_url, confidence, parser_version, retrieved_at, payload)`. Don't query.

### `anomalies`

**Currently empty (0 rows)** but the `_anomaly_detection` cron runs daily and may produce rows in the future. Schema: UNIQUE `(metric_kind, dimension, period_end)`. Columns: `metric_kind` (e.g. "pjm_queue_mw", "permit_filings_va", "edgar_capacity_mw"), `dimension` (sub-bucket like state code or fuel type, "ALL" if N/A), `period_end` (ISO week-ending date), `value`, `baseline_mean`, `baseline_stddev`, `z_score`, `direction` (`spike` | `drop`), `sample_size`, `note`, `detected_at`, `created_at`. Used by hypothesizer's `anomalies_today` section.

---

## Cross-domain relationships

```
companies (1,254)
  ├── company_aliases (1,424)              [source-side raw names → canonical]
  ├── generator_permits.resolved_company_id [join for parent rollup]
  ├── edgar_extractions.buyer_company_id
  ├── edgar_extractions.seller_company_id
  └── site_company_associations.company_id

sites (6,973)
  ├── events.aterio_dc_uid                  [JOIN via aterio_dc_uid, not id!]
  ├── site_aliases.site_id                  [external source-record-ids → site]
  ├── site_company_associations.site_id     [operator/end-user/equipment/financier roles]
  └── generator_permits.site_id              [sparse — most NULL]

energy_projects (84)                         [generation side, separate from sites]
  └── grouped by developer_companies (free-text, NOT a FK)

building_permits (347)                       [no FK — county-level standalone]
generator_permits (4,150)                    [pjm + epa_echo + tceq + va_open_data + socrata_ny]
edgar_extractions (104)                      [pillar in {power_contract, vendor_supply}]
press_releases (15)                          [pillar = power_contract only]

ai_session (54)
  ├── ai_insight (146)
  │     ├── agent_chart (93)                [ChartSpec v1]
  │     ├── agent_citation (255)            [web citations]
  │     ├── insight_thread (4)              [V2 follow-up chats]
  │     │     └── agent_message.thread_id
  │     └── insight_subscription (0)        [V3, not deployed]
  ├── agent_message (62)                    [chat history]
  ├── agent_tool_call (0)                   [empty — tool calls live in agent_message.tool_calls jsonb]
  └── skill_invocation (0)                  [empty — pipeline not deployed]

brief_runs (3)                               [weekly cron output]
ingestion_runs (609)                         [per-adapter audit]
data_coverage (280)                          [per-(pillar, state, source) scorecard]
data_lineage (36)                            [per-record provenance, sparse]
llm_extraction_runs (39)                     [LLM call audit]
anomalies (0)                                [WoW deviation detector — currently no signals cross 2σ]

curated_deals (23)                           [stale seed, mostly superseded by edgar_extractions]
permit_parent_review_queue (88)              [HITL queue, ingestion only]
transcript_metrics (0)                       [empty — never wired]
skill_reference (0)                          [empty — RAG not deployed]
```

**Triangulation pattern (the platform's core value-add)**: a single deal often shows up across three sources — `edgar_extractions` (the SEC disclosure), `generator_permits` (the air permit if it's gas), and `building_permits` (the county building permit). Cross-correlate by:
1. `edgar_extractions.buyer_canonical = companies.canonical_name`
2. `generator_permits.resolved_company_id = companies.id` and `state_code` match
3. `building_permits.applicant_name` LIKE-matched via `company_aliases.raw_name`
4. Optional: `sites.provider_name = companies.canonical_name` and `state_code` match for the demand-side endpoint.
