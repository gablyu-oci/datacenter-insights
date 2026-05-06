# Architecture Evolution PRD: Prototype to Production Platform

**Owner:** Strategic Insights Team (OCI)
**Stakeholder:** the user
**Status:** Draft v1.0
**Date:** 2026-04-28
**Scope:** Backend architecture, data layer, API design, frontend error handling, observability

---

## 1. Overview

This document defines the architecture migration from the current prototype -- a single-file FastAPI server returning randomized mock data on every request -- to a production-grade intelligence platform with real data ingestion, persistence, source lineage, and structured error handling.

It does **not** restate the product vision (see `PRD.md`) or the agent specification (see `requirements.md`). It focuses exclusively on the structural changes required to make the platform trustworthy, reproducible, and operable.

---

## 2. Problem Statement

The current prototype (`backend/main.py`, 113 lines) has six architectural defects that prevent it from serving as a decision-support tool:

### 2.1 Mock Data Everywhere

9 of 12 API endpoints delegate to `data/mock_data.py`, which calls `random.uniform()`, `random.randint()`, and `random.choice()` on every request. A user who refreshes the page gets different GW totals, different permit counts, and different triangulation gaps. There is no persistence layer at all -- no database, no file-backed store, not even an in-memory dict that survives across requests.

Concrete examples from `mock_data.py`:

- `get_power_data()`: generates `gw_total = round(random.uniform(0.1, 2.8), 2)` for every company/region pair, every time.
- `get_triangulation_data()`: produces `contracted_gw = round(random.uniform(1.5, 8.0), 2)` -- the central analytical output of the platform is a random number.
- `get_permits_data()`: generates fake permit records with `source_url: "https://permits.example.gov"` -- a nonexistent URL displayed as a real citation.
- `get_sources_data()` and `get_agent_status()`: return hardcoded dicts with fabricated timestamps (e.g., `"last_ingested": "2024-12-15"`) and record counts (`"records": 1240`) that represent no actual data.

This means the platform currently lies to its users in two ways: (a) numbers change on every page load, making any analysis non-reproducible, and (b) fake source URLs and confidence scores create false credibility.

### 2.2 Monolithic Single-File Backend

All 12 endpoints live in one `main.py` with no routers, no service layer, no dependency injection, and no separation of concerns. Adding a new data source means editing the same file that serves all other endpoints.

### 2.3 Sole Real Data Source is Fragile

The EDGAR agent (`agents/edgar_agent.py`) is the only code path that touches real external data. It has three critical problems:

- **Silent exception swallowing.** Lines 88-89: `except Exception as e: return []`. Lines 130-131: `except Exception: return ""`. Lines 197-198: `except Exception: pass`. When EDGAR fails -- rate limiting, network timeout, schema change -- the system silently returns empty data with no log entry.
- **Blocking synchronous I/O.** Uses `urllib.request.urlopen()` with up to 30-second timeouts inside a FastAPI async event loop. A single slow EDGAR fetch blocks all concurrent requests.
- **Fragile HTML parsing.** Regex-based extraction (`_html_to_text`, `_parse_mw_from_text`) with no validation, no fallback, and no way to know when parsing fails vs when there is genuinely no data.

### 2.4 No Error Propagation to Frontend

The `useApi` hook (`frontend/src/hooks/useApi.ts`) does capture HTTP errors, but the backend never returns them. Every endpoint either returns mock data or silently falls back to empty arrays. The frontend has no way to distinguish "no data exists" from "the data source is down" from "the parse failed."

The `TriangulationTab` renders `const records = data?.data ?? [];` -- if the API errors, the user sees an empty chart with no explanation.

### 2.5 Security Debt

- `CORSMiddleware` configured with `allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]`.
- No `requirements.txt` or `pyproject.toml` for the backend -- dependencies are unversioned and unpinned.
- Google Maps API key referenced in frontend `.env.local` with no domain restriction.

### 2.6 No Operational Visibility

Zero structured logging. Zero metrics. No health check beyond `{"status": "ok"}`. No way to know if the EDGAR agent last succeeded 5 minutes ago or 5 days ago.

---

## 3. Goals and Non-Goals

### Goals

| ID | Goal | Measurable Target |
|----|------|-------------------|
| G1 | **Eliminate mock data in delivered tabs.** Replace `random.*` calls with persisted, source-linked data or explicit "no data available" states. | 0 calls to `random.*` in any code path serving delivered tabs. |
| G2 | **Persist normalized data.** Every API response must be deterministic (same data on page refresh) and traceable to an ingestion event. | All endpoints backed by a queryable store (PostgreSQL + SQLModel, self-hosted on OCI VM). |
| G3 | **Source lineage on every metric.** Each data point carries: source URL, retrieval timestamp, parser version, and a confidence score derived from parse quality (not `random.uniform`). | >= 95% of datapoints in delivered tabs link to a primary source URL that resolves. |
| G4 | **Async, non-blocking I/O for all external fetches.** No `urllib.request` inside the event loop. | 0 blocking I/O calls in the request path. |
| G5 | **Structured error handling.** Replace every `except Exception: pass/return []` with logged, categorized errors that propagate to the frontend. | 0 bare `except` clauses. All errors logged with severity, source, and timestamp. |
| G6 | **Modular backend.** Split monolithic `main.py` into domain routers, a service layer, and a data-access layer. | Each domain (power, gpu, permits, triangulation, sources) in its own router module. |
| G7 | **Frontend error states.** Every tab renders loading, error, empty, and populated states distinctly. | Every component using `useApi` renders the `error` return value. |
| G8 | **Operational observability.** Structured JSON logging, ingestion health dashboard, and data freshness tracking. | Log every external fetch with status, latency, and record count. |

### Non-Goals (this PRD)

- Building new product features (new tabs, new pillars, ML models).
- Changing the visual design of the frontend.
- Setting up CI/CD, containerization, or cloud deployment (separate infrastructure PRD).
- Adding authentication/authorization (separate security PRD, though CORS fix is in scope).
- Migrating off React/Vite/FastAPI stack.

---

## 4. User Stories

### US-1: Source-Linked Metrics (Strategy Analyst)

**As a** strategy analyst, **I want** every metric on the dashboard to link to its primary source **so that** I can verify claims before including them in an executive briefing.

**Acceptance Criteria:**
- Every data point returned by the API includes a `source_url` field containing a URL that resolves (HTTP 200).
- Every data point includes `retrieved_at` (ISO 8601 timestamp of ingestion), `parser_version` (semver string), and `confidence` (float 0-1 derived from parse quality, not randomized).
- Clicking a source link in the UI opens the primary document (SEC filing, press release, permit record) in a new tab.
- Data points without a verifiable source are displayed with a "Source Pending" badge instead of a fake URL.
- The Sources tab shows a live inventory of all data sources with their last-successful-ingestion timestamp and record count (actual, not hardcoded).

### US-2: Event-Driven EDGAR Ingestion (Platform)

**As the** platform, **I need to** ingest EDGAR filings on event triggers (new filing published, manual refresh, scheduled daily check) **so that** data is fresh without blocking API requests.

**Acceptance Criteria:**
- EDGAR fetches run as background tasks (FastAPI `BackgroundTasks` or a task queue), never in the request-response path.
- All HTTP calls to `data.sec.gov` use `httpx.AsyncClient` (or equivalent async HTTP client), not `urllib.request`.
- Rate limiting (10 req/s SEC limit) is enforced via a semaphore or token bucket, not `time.sleep()`.
- Every fetch is logged with: company, CIK, filing type, HTTP status, latency (ms), records extracted, and any parse errors.
- Failed fetches retry with exponential backoff (3 attempts, 2/4/8 second delays) before logging an error.
- Cache TTL is configurable per source (default 12h for EDGAR, 7d for permits).
- The `/api/sources` endpoint returns actual last-ingestion timestamps from the database, not hardcoded values.

### US-3: Persistent, Reproducible Data (Platform)

**As the** platform, **I need to** persist all normalized data in a database **so that** API responses are deterministic and results are reproducible across page loads.

**Acceptance Criteria:**
- A relational schema stores: companies, sites, power deals, permits, GPU shipment estimates, NIC/optics data, and triangulation inputs.
- Every record has an `ingested_at` timestamp and a `source_id` foreign key.
- API endpoints query the database, not call `random.*` functions.
- Refreshing the page returns the same data until a new ingestion event updates it.
- The database is seeded with the 22 curated deals from `data/curated_deals.py` as the initial dataset.
- Historical data is versioned: when a record is updated by re-ingestion, the previous version is preserved (append-only or soft-delete pattern).

### US-4: Structured Logging and Error Visibility (Operator)

**As an** operator, **I need** structured logging and error visibility **so that** I can diagnose ingestion failures, slow fetches, and parse errors without reading source code.

**Acceptance Criteria:**
- All backend logs use structured JSON format with fields: `timestamp`, `level`, `module`, `message`, `duration_ms`, `error_type`, `error_detail`.
- No bare `except Exception` clauses. Every exception handler either: (a) logs the error and re-raises with context, or (b) logs the error and returns a typed error response.
- A `/api/health` endpoint returns: database connectivity status, last successful ingestion per source, and count of errors in the last hour.
- Log output is compatible with standard log aggregation (structured JSON to stdout).

### US-5: Frontend Error States (Frontend)

**As the** frontend, **I need** proper error states from the API **so that** users see actionable feedback instead of empty charts.

**Acceptance Criteria:**
- The API returns structured error responses: `{ "error": { "code": "EDGAR_TIMEOUT", "message": "...", "source": "edgar_agent", "timestamp": "..." } }` with appropriate HTTP status codes (502 for upstream failures, 503 for service unavailable, 422 for invalid parameters).
- Every tab component renders four distinct states: loading (skeleton/spinner), error (message + retry button), empty ("No data available for this filter"), and populated (charts/tables).
- The `useApi` hook exposes a `retry()` function so users can re-attempt failed loads.
- Tabs backed entirely by mock data (not yet migrated) display a banner: "Preview Data -- This tab uses sample data and does not reflect real-world metrics."

### US-6: Modular API Structure (Developer)

**As a** developer, **I need** the backend organized into domain modules **so that** I can add a new data source or endpoint without risking regressions in unrelated domains.

**Acceptance Criteria:**
- `main.py` contains only app initialization, middleware configuration, and router registration.
- Each domain has its own FastAPI `APIRouter`: `routers/power.py`, `routers/gpu.py`, `routers/permits.py`, `routers/triangulation.py`, `routers/sources.py`, `routers/satellite.py`.
- Business logic lives in a service layer (`services/`) separate from HTTP concerns.
- Data access lives in a repository layer (`repositories/` or `db/`) separate from business logic.
- Dependencies (database session, HTTP client, configuration) are injected via FastAPI's `Depends()`.

---

## 5. Target Architecture

### 5.1 Backend Structure

```
backend/
  main.py                    # App factory, middleware, router registration
  config.py                  # Settings via pydantic-settings (env vars)
  db/
    models.py                # SQLAlchemy/SQLModel ORM models
    session.py               # Engine, session factory
    migrations/              # Alembic migrations
    seed.py                  # Seed from curated_deals.py
  routers/
    power.py                 # /api/power/* endpoints
    gpu.py                   # /api/gpu/* endpoints
    permits.py               # /api/permits/* endpoints
    triangulation.py         # /api/triangulation/*
    sources.py               # /api/sources/*
    satellite.py             # /api/satellite/*
    health.py                # /api/health (rich health check)
  services/
    power_service.py         # Business logic for power domain
    gpu_service.py
    triangulation_service.py
    ingestion_service.py     # Orchestrates background ingestion
  agents/
    edgar_agent.py           # Async EDGAR client (httpx)
    permits_agent.py         # Future: Shovels.ai adapter
    earnings_agent.py        # Future: transcript parser
    base.py                  # Abstract agent interface
  schemas/
    power.py                 # Pydantic response models
    gpu.py
    common.py                # SourceMetadata, ErrorResponse
  pyproject.toml             # Pinned dependencies
```

### 5.2 Data Model (Core Tables)

| Table | Key Columns | Notes |
|-------|-------------|-------|
| `companies` | id, name, ticker, cik, color_hex | Canonical company registry |
| `sites` | id, company_id, name, lat, lon, county, state, country | Entity-resolved locations |
| `power_deals` | id, buyer_id, seller, capacity_mw, energy_source, status, announced_date, source_url, retrieved_at, parser_version, confidence | Seeded from curated_deals + EDGAR |
| `ingestion_events` | id, source_name, started_at, completed_at, status, records_created, records_updated, error_detail | Audit trail for every ingest run |
| `gpu_estimates` | id, quarter, shipped_units, deployed_units, revenue_b, source_url, retrieved_at, confidence | Quarterly GPU supply chain data |
| `permit_records` | id, site_id, county, permit_type, filed_date, status, estimated_mw, source_url, retrieved_at | County permit data |
| `triangulation_snapshots` | id, region, computed_at, contracted_gw, gpu_demand_gw, gap_gw, nic_validation, permit_signals, inputs_json | Computed, not random |

### 5.3 Frontend Changes

| Component | Current Behavior | Target Behavior |
|-----------|-----------------|-----------------|
| `useApi` hook | Returns `{ data, loading, error }` but most tabs ignore `error` | Add `retry()` function; every consuming component must handle all four states |
| Tab components | Render data or loading spinner; no error UI | Render: loading skeleton, error card with retry, empty state, populated state |
| Mock-backed tabs | Display random data as if real | Show "Preview Data" banner until migrated |
| Source links | Some link to `https://permits.example.gov` | All links validated; broken links show "Source Pending" |

---

## 6. Phased Scope

### Phase 1: Foundation (Weeks 1-6)

**Geography:** Northern Virginia. **Companies:** Microsoft, AWS, Google (GCP), Meta, OCI.
**Objective:** Deliver the Power Map tab and Triangulation tab backed entirely by real, persisted data.

| Week | Deliverable |
|------|-------------|
| 1-2 | **Database and project structure.** Set up PostgreSQL + SQLModel (self-hosted on OCI VM). Define core schema. Seed with 22 curated deals. Refactor `main.py` into routers. Add `pyproject.toml` with pinned deps. Fix CORS to allowlist `localhost:5173` only (dev) and the deployment origin (prod). |
| 2-3 | **EDGAR agent rewrite.** Replace `urllib.request` with `httpx.AsyncClient`. Replace `except Exception: pass` with structured error handling and logging. Add retry logic with backoff. Wire ingested filings into the database. |
| 3-4 | **Power endpoints migration.** `/api/power/capacity`, `/api/power/timeseries`, `/api/power/announcements`, `/api/power/gw-summary` read from the database. Remove `mock_data.get_power_data()` and `get_power_timeseries()` from the serving path. |
| 4-5 | **Triangulation engine.** Compute triangulation from persisted L1 (power deals), L2 (GPU estimates -- manually seeded for Phase 1), L3 (NIC/optics -- manually seeded), L4 (permit data -- curated for NoVA). Store snapshots. Remove `get_triangulation_data()` mock. |
| 5-6 | **Frontend error states and source validation.** Update all migrated tabs to render loading/error/empty/populated states. Add "Preview Data" banner to unmigrated tabs. Validate all source URLs resolve. Add retry to `useApi`. |

**Phase 1 exit criteria:**
- Power Map tab for NoVA: 5 hyperscalers (Microsoft, AWS, GCP, Meta, OCI), all data from database, all source links resolve.
- Triangulation tab: computed from persisted inputs, not `random.*`.
- Zero `random.*` calls in any code path serving Power or Triangulation tabs.
- Zero bare `except` clauses in EDGAR agent.
- Structured JSON logging on all backend modules.
- `/api/health` returns database status and last ingestion timestamps.

### Phase 2: Scale Data Sources (Weeks 7-14)

- Meta + OCI already included in Phase 1 as full participants in every pillar.
- Integrate Shovels.ai (or alternative) for live permit data -- behind an adapter interface so the vendor can be swapped.
- Build earnings-transcript ingestion for NVIDIA and TSMC quarterly filings.
- Migrate GPU Supply, NICs & Optics, and TSMC tabs off mock data.
- Expand geography to Texas, Arizona, Oregon, Iowa.
- APScheduler already in place from Phase 1; scale job count as needed.

### Phase 3: Intelligence Layer (Weeks 15-20)

- Satellite imagery integration (Planet Labs / Maxar trial).
- Anomaly detection on week-over-week permit and filing deltas.
- Auto-generated weekly briefing from the same data layer.
- All 9 tabs fully backed by real or computed data. `mock_data.py` deleted.

---

## 7. Success Criteria

| Metric | Current State | Phase 1 Target | Phase 2 Target |
|--------|--------------|----------------|----------------|
| **Real-data ratio** (% of datapoints from verified sources) | ~22% (curated deals only) | >= 80% across delivered tabs (Power, Triangulation) | >= 90% across all tabs |
| **Source coverage** (% of datapoints with resolving source URL) | ~10% (curated deals have real URLs; mocks have `permits.example.gov`) | >= 95% in delivered tabs | >= 95% across all tabs |
| **Data freshness -- filings** | No SLA; cache is 12h TTL, silent failure | <= 24h after EDGAR publication | <= 24h |
| **Data freshness -- permits** | No real permit data | Manual seed for NoVA | <= 7 days via Shovels.ai |
| **Reproducibility** | 0% (every refresh returns different numbers) | 100% for delivered tabs (same data until next ingestion) | 100% all tabs |
| **Error visibility** | 0 errors logged (all swallowed) | 100% of external-fetch failures logged with structured metadata | 100% + alerting |
| **Mock code in serving path** | 9 of 12 endpoints call `random.*` | 0 for delivered tabs | 0 across entire backend |
| **Bare except clauses** | >= 5 in `edgar_agent.py` alone | 0 | 0 |

---

## 8. Known Risks and Mitigations

### R1: Mock-Data Hangover

**Risk:** Users (especially the user) may already be treating mock numbers as real. Confidence scores like `0.94` on fabricated data create false trust.

**Mitigation:**
- Phase 1, Week 1: Add a visible "PREVIEW DATA" watermark to all mock-backed tabs immediately, before any backend work begins.
- Document which tabs serve real data vs. mock in the Sources tab.
- Never display a confidence score that is itself randomized. Either compute it from parse quality or do not show it.

### R2: EDGAR Brittleness

**Risk:** The EDGAR agent is the only real data pipeline and it has five silent `except` clauses, blocking sync I/O, and regex-based HTML parsing. A SEC schema change or rate-limit enforcement would silently kill all real data with no alert.

**Mitigation:**
- Rewrite as async with `httpx` in Phase 1, Week 2-3.
- Replace bare `except` with typed exception handling (`httpx.TimeoutException`, `httpx.HTTPStatusError`, `json.JSONDecodeError`).
- Add a parsing-validation step: if `_parse_mw_from_text` returns `None`, log a warning with the filing URL so a human can review.
- Add a circuit breaker: if >50% of fetches for a given company fail in a window, mark the source as degraded in `/api/health`.

### R3: Vendor Lock-In

**Risk:** The platform's differentiation depends on premium data sources (Shovels.ai for permits, SemiAnalysis for industry research) that may not be approved, may change pricing, or may revoke access.

**Mitigation:**
- Define an abstract `DataSourceAdapter` interface in `agents/base.py` with methods: `fetch()`, `parse()`, `validate()`, `health_check()`.
- Implement each vendor behind this interface so swapping Shovels.ai for direct county-API scraping requires only a new adapter, not a rewrite.
- For each premium source, identify one free fallback: county government RSS feeds for permits, SEC EDGAR for filings, public earnings-call transcripts for supply chain.

### R4: Security Debt

**Risk:** `allow_origins=["*"]` in CORS, no dependency pinning, Google Maps API key in `.env.local` with no domain restriction. Any of these could be flagged in a security review and block deployment.

**Mitigation:**
- Phase 1, Week 1: Restrict CORS to `["http://localhost:5173"]` for development and the production domain.
- Phase 1, Week 1: Create `pyproject.toml` with pinned dependencies (currently zero dependency management for the backend).
- Phase 1, Week 1: Add Google Maps API key to backend environment and proxy map tile requests, or restrict the key to specific HTTP referrers.
- The frontend currently uses both `@googlemaps/js-api-loader` and `react-leaflet` -- consolidate to one mapping library.

### R5: Frontend Error Swallowing

**Risk:** The `useApi` hook correctly captures errors into state, but most tab components (e.g., `TriangulationTab` line 32: `const { data, loading } = useApi<TriangResponse>("/api/triangulation")`) destructure only `data` and `loading`, discarding `error`. Users see empty charts with no explanation when the backend is down.

**Mitigation:**
- Create a shared `<DataStateWrapper>` component that takes `{ data, loading, error }` and renders the appropriate state (skeleton, error card with retry, empty state, or children).
- Require all tab components to use this wrapper. Add a lint rule or code-review checklist item.
- Add the `retry()` function to `useApi` so the error card can offer a re-fetch button.

### R6: Entity Resolution Complexity

**Risk:** The same datacenter site may appear under different names across sources (e.g., "AWS Ashburn" vs "Amazon us-east-1" vs "AWS IAD datacenter"). Without entity resolution, the database will accumulate duplicates that inflate GW totals.

**Mitigation:**
- Phase 1: Start with a manually curated company/site registry (seed from `curated_deals.py` + `get_satellite_sites()`).
- Phase 2: Build fuzzy-matching heuristics on (company_name, lat/lon within 5km, state) to flag potential duplicates for human review.
- Never auto-merge without human confirmation in Phase 1.

### R7: Curated Data Staleness

**Risk:** The 22 curated deals in `curated_deals.py` are a point-in-time snapshot. Without a process to update them, they will become stale and the "real data" percentage will be misleading.

**Mitigation:**
- Migrate curated deals into the database as seed data with `data_source = "manual_curation"`.
- Track `last_verified_at` per deal. Flag deals not verified in >90 days.
- Phase 2: Build a review workflow where EDGAR-ingested deals are surfaced for analyst verification and promoted to "curated" status.

---

## 9. Out of Scope

- **New product features.** No new tabs, no new pillars, no new visualizations. This PRD is about making existing features real.
- **CI/CD and deployment.** Infrastructure automation is a separate concern.
- **Authentication and authorization.** Required before external exposure but not for internal prototype evolution.
- **Mobile or responsive design.** Desktop-only for internal use.
- **Performance optimization beyond removing blocking I/O.** No caching layer, CDN, or query optimization unless blocking I/O removal proves insufficient.

---

## 10. Resolved Decisions

All open questions are now resolved. See [00-DECISIONS-AND-CONSTRAINTS.md](00-DECISIONS-AND-CONSTRAINTS.md) §1.

| # | Former Question | Resolution |
|---|---|---|
| 1 | PostgreSQL hosting model | Self-hosted on OCI VM. No managed service. (Decision #1) |
| 2 | Docker Compose for dev? | No Docker. Direct PostgreSQL process on OCI VM. |
| 3 | Migration strategy | Alembic from day one. No SQLite intermediate. |
| 4 | APScheduler vs Celery | APScheduler in-process for v1. (§2.1) |
| 5 | Auth/RBAC | Deferred — no auth in v1. (Decision #5) |
| 6 | OCI tracking | OCI is full participant in every pillar with %-share KPI. (Decision #3) |
| 7 | Deploy target | This OCI compute instance via systemd/start.sh. (Decision #4) |

---

## Appendix A: Current Mock-Data Inventory

This table maps every endpoint to its data source, classifying each as Real, Curated (hand-verified, static), or Mock (randomized per request).

| Endpoint | Function Called | Classification | Notes |
|----------|----------------|----------------|-------|
| `GET /api/power/capacity` | `mock_data.get_power_data()` | **Mock** | `random.uniform()` for GW, confidence |
| `GET /api/power/timeseries` | `mock_data.get_power_timeseries()` | **Mock** | `random.uniform()` for base GW |
| `GET /api/gpu/supply` | `mock_data.get_gpu_data()` | **Mock** | `random.randint()` for units, revenue |
| `GET /api/nics` | `mock_data.get_nics_optics_data()` | **Mock** | `random.randint()` for shipments |
| `GET /api/tsmc` | `mock_data.get_tsmc_data()` | **Mock** | `random.randint()` for wafers, capacity |
| `GET /api/permits` | `mock_data.get_permits_data()` | **Mock** | `random.*` everything; source_url is `permits.example.gov` |
| `GET /api/satellite` | `mock_data.get_satellite_sites()` | **Curated** | 16 hardcoded sites with real URLs and milestones |
| `GET /api/triangulation` | `mock_data.get_triangulation_data()` | **Mock** | `random.uniform()` for contracted GW, the platform's core output |
| `GET /api/sources` | `mock_data.get_sources_data()` + `get_agent_status()` | **Mock** | Hardcoded timestamps and record counts representing no real data |
| `GET /api/power/announcements` | `curated_deals.get_curated_deals()` + optionally `edgar_agent.fetch_real_8k_deals()` | **Real + Curated** | 22 verified deals; EDGAR fetch is real but fragile |
| `GET /api/power/gw-summary` | `curated_deals.get_company_gw_summary()` | **Curated** | Aggregation of the 22 curated deals |
| `GET /health` | inline | **Real** | Returns `{"status": "ok"}` |

**Summary:** 2 of 12 endpoints serve real/curated data. 9 of 12 return randomized mock data. 1 returns a static health check.

---

## Appendix B: Silent Exception Locations in edgar_agent.py

| Line(s) | Code Pattern | Impact |
|---------|-------------|--------|
| 88-89 | `except Exception as e: return []` | `_get_material_8ks` silently returns empty list on any EDGAR API failure |
| 130-131 | `except Exception: return ""` | `_extract_power_context` silently returns empty string if filing HTML fetch fails |
| 188-189 | `except Exception as e: continue` | `fetch_real_8k_deals` skips entire company on any error in the fetch/parse loop |
| 197-198 | `except Exception: pass` | Amazon 10-K mining silently fails with no record |

Each of these locations must be replaced with typed exception handling, structured logging, and appropriate error propagation.

---

## Conformance to 00-DECISIONS-AND-CONSTRAINTS.md

- **§1 Decisions 1-5:** All reflected in Section 10 above.
- **§2 Tech Stack:** PostgreSQL + SQLModel, APScheduler, httpx, rapidfuzz, TanStack Query, APIRouter+DI.
- **§3 Datasets:** Aterio CSV as canonical site seed, events table, energy_projects table.
- **§5 UX Rule:** Additive only — no visual changes to existing tabs.
