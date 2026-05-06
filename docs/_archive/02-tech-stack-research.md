# 02 — Tech Stack Research: Architecture Evolution

> **Date:** 2026-04-28
> **Status:** Draft — awaiting team review
> **Audience:** Engineering team (2-3 engineers)
> **Context:** Evolving from a single-file FastAPI prototype (78% mock data) to a production-grade Datacenter & Power Intelligence Platform

---

## Table of Contents

1. [Persistent Store](#1-persistent-store)
2. [Task Queue / Scheduler](#2-task-queue--scheduler)
3. [Async HTTP Client](#3-async-http-client)
4. [Entity Resolution / Data Normalization](#4-entity-resolution--data-normalization)
5. [Data Lineage / Citation Tracking](#5-data-lineage--citation-tracking)
6. [Frontend State Management](#6-frontend-error-handling--state-management)
7. [API Structure](#7-api-structure)
8. [Summary Decision Matrix](#summary-decision-matrix)

---

## 1. Persistent Store

**Current state:** No database. Data lives in Python dicts (`curated_deals.py`), `random.*` generators (`mock_data.py`), and a file-based cache for EDGAR responses.

**Requirements:** Versioned data lineage, citation metadata per metric, entity resolution tables, time-series queries, ACID writes from ingestion agents.

### Options

| Criteria | PostgreSQL + SQLModel | DuckDB (embedded) | SQLite |
|---|---|---|---|
| **Query model** | Full OLTP + decent OLAP; JSONB for semi-structured data | Columnar OLAP; vectorized execution excels at aggregations | Row-oriented OLTP; adequate for small datasets |
| **Concurrency** | Hundreds of concurrent readers/writers | Single writer, concurrent readers | Single writer, WAL mode allows concurrent reads |
| **Async support** | Yes — `asyncpg` driver, `sqlmodel.ext.asyncio.session` | No native async; needs thread pool | No native async; `aiosqlite` wrapper exists |
| **FastAPI integration** | Excellent — SQLModel is by the same author (tiangolo), shares Pydantic models | Manual; no ORM parity | Manual; `databases` library or raw `aiosqlite` |
| **Schema migrations** | Alembic (mature, well-documented) | Manual DDL | Alembic works but less common |
| **Time-series** | `tsrange`, window functions, `pg_partman` for partitioning | Window functions; fast analytical scans | Basic; no native time-series features |
| **Operational overhead** | Requires running a Postgres server (or managed service on OCI) | Zero — pip install, single file | Zero — single file |
| **Ecosystem** | PostGIS, pg_trgm (fuzzy search), JSONB, full-text search | Parquet/CSV ingestion, good for ETL | Minimal |
| **Scale ceiling** | TB-scale | Hundreds of GB (single machine) | Low GB (practical limit) |

### Recommendation: **PostgreSQL + SQLModel**

**Rationale:**
- SQLModel eliminates the dual-model problem (ORM model vs. Pydantic schema) by combining both into a single class, reducing boilerplate by ~20% compared to raw SQLAlchemy.
- SQLModel supports async via `sqlmodel.ext.asyncio.session.AsyncSession` with the `asyncpg` driver, which aligns with FastAPI's async handlers.
- PostgreSQL's JSONB columns are ideal for storing semi-structured citation metadata and variable-schema filing data.
- Alembic migrations give us version-controlled schema evolution.
- If analytical query performance becomes a bottleneck later, `pg_duckdb` (a PostgreSQL extension) can accelerate OLAP queries without changing the primary store.

**Why not DuckDB?** DuckDB is outstanding for analytics but its single-writer model is a poor fit for concurrent ingestion agents writing permits, filings, and satellite data. It could serve as a future read-replica for dashboards, but not as the primary store.

**Why not SQLite?** Too limited for concurrent writes from multiple agents. No JSONB, no PostGIS, no `pg_trgm` for fuzzy entity matching.

**Migration difficulty: MEDIUM**
- Define SQLModel classes for ~6 tables (deals, filings, permits, companies, metrics, audit_log).
- Write Alembic initial migration.
- Replace `curated_deals.py` dict with a seed script.
- Replace file-based EDGAR cache with DB rows.
- Estimated: 3-4 days for one engineer.

---

## 2. Task Queue / Scheduler

**Current state:** No scheduler. EDGAR fetches are synchronous and triggered only when a user hits `/api/power/announcements?include_edgar=true`. No background refresh of any data.

**Requirements:** Weekly permit scraping, event-driven filing checks, quarterly earnings parsing. Small team — minimal ops overhead.

### Options

| Criteria | Celery + Redis | APScheduler (in-process) | Dramatiq + Redis |
|---|---|---|---|
| **Architecture** | Distributed; separate worker processes | In-process; runs in FastAPI event loop | Distributed; separate worker processes |
| **Broker dependency** | Redis or RabbitMQ required | None (in-process) or SQLAlchemy job store | Redis or RabbitMQ required |
| **Async support** | Limited (async tasks via `celery.contrib.asyncio`) | `AsyncIOScheduler` integrates with asyncio loop | No native async; sync workers |
| **Scheduling** | Via `celery-beat` (separate process) | Built-in cron, interval, date triggers | Needs external scheduler (APScheduler or cron) |
| **Monitoring** | Flower dashboard | Minimal; custom logging | Built-in Prometheus metrics |
| **Operational cost** | High — Redis + worker + beat = 3 processes minimum | Low — zero extra processes | Medium — Redis + worker = 2 processes |
| **Retry / error handling** | Mature, configurable | Basic; manual retry logic | Excellent — automatic retries, dead-letter queues |
| **Scalability** | Enterprise-grade horizontal scaling | Single-process only | Good horizontal scaling |
| **Complexity** | High for small teams | Low | Medium |

### Recommendation: **APScheduler (in-process) now, with a path to Dramatiq later**

**Rationale:**
- Our scheduling needs are modest: ~5 recurring jobs (permits weekly, EDGAR daily, earnings quarterly, satellite monthly, deal refresh daily). This does not warrant a distributed task queue.
- APScheduler's `AsyncIOScheduler` runs inside the FastAPI event loop, meaning zero additional processes, zero Redis dependency, and zero deployment complexity.
- The `fastapi-apscheduler` integration library provides a clean startup/shutdown lifecycle via FastAPI's `lifespan` events.
- If we later need distributed workers (e.g., parallel scraping of 50 EDGAR filings), Dramatiq is the upgrade path — simpler than Celery, with better defaults for retries and dead-letter queues.

**Why not Celery?** Overkill for 5 scheduled jobs. Requires Redis + worker process + beat process. Configuration is notoriously complex. Not justified for a 2-3 person team.

**Why not Dramatiq now?** Still requires Redis and a separate worker process. Premature for our current scale.

**Migration difficulty: LOW**
- Add `APScheduler` + `fastapi-apscheduler` to requirements.
- Define 5 job functions (mostly wrapping existing data-fetch logic).
- Register them in FastAPI lifespan.
- Estimated: 1 day for one engineer.

---

## 3. Async HTTP Client

**Current state:** `urllib.request` with manual JSON parsing in `edgar_agent.py`. Synchronous, blocks the FastAPI worker thread. Basic file-based caching. No retry logic beyond a simple try/except.

**Requirements:** SEC EDGAR compliance (10 req/s rate limit, proper User-Agent), async-compatible with FastAPI, exponential backoff, response caching.

### Options

| Criteria | httpx | aiohttp |
|---|---|---|
| **Sync + Async** | Both modes in one library | Async only |
| **API familiarity** | Near-identical to `requests` | Unique API; steeper learning curve |
| **HTTP/2** | Supported (opt-in) | Not supported |
| **FastAPI alignment** | Recommended by FastAPI docs; same author ecosystem | Works but not idiomatic |
| **Rate limiting** | Via `httpx-ratelimiter` or manual `asyncio.Semaphore` | Via `aiohttp-throttle` or manual |
| **Retry** | Via `stamina` or `tenacity` libraries | Via `aiohttp-retry` |
| **Connection pooling** | Built-in `AsyncClient` with configurable pool | Built-in `ClientSession` with pool |
| **Performance** | Slightly slower than aiohttp for raw throughput | ~2x faster for high-concurrency async |
| **Bundle size / deps** | Lightweight | Heavier (C extensions) |

### Recommendation: **httpx**

**Rationale:**
- httpx provides both sync and async modes, enabling incremental migration: start by replacing `urllib` with sync httpx, then convert to async when handlers are made async.
- The API mirrors `requests`, so the migration from `urllib` is nearly mechanical.
- For SEC EDGAR specifically: httpx makes it trivial to set default headers (User-Agent), timeouts, and base URLs on a shared `AsyncClient` instance.
- Rate limiting for EDGAR's 10 req/s limit is cleanly implemented with `asyncio.Semaphore(8)` (keeping 2 req/s headroom) or the `stamina` library for exponential backoff.
- aiohttp's raw throughput advantage is irrelevant when we are rate-limited to 10 req/s anyway.

**SEC EDGAR-specific implementation notes:**
- Always set `User-Agent: "Datacenter Intelligence Platform research@oracle.com"` (already in current code).
- Target 8 req/s (not 10) to avoid 403 blocks.
- Cache responses locally (DB or file) since SEC data changes infrequently.
- Use exponential backoff: 1s, 2s, 4s on 429/5xx responses. Never retry 403.

> **EDGAR endpoints (§4 of 00-DECISIONS-AND-CONSTRAINTS.md):** submissions, companyfacts, companyconcept, frames (cross-company quarterly capex/PP&E), EFTS full-text search, nightly bulk ZIPs. 10 req/s rate limit. No CORS — backend-only.

**Migration difficulty: LOW**
- Replace `urllib.request.Request` + `urlopen` with `httpx.AsyncClient.get()`.
- ~50 lines of code to change in `edgar_agent.py`.
- Add retry decorator via `stamina` or `tenacity`.
- Estimated: 0.5 days for one engineer.

---

## 4. Entity Resolution / Data Normalization

**Current state:** Company names are hardcoded strings in `curated_deals.py` (e.g., "Microsoft", "Amazon", "Google"). No normalization. EDGAR agent uses CIK numbers for lookup but returns raw company names from filings.

**Requirements:** Map company variants to canonical names, link companies to sites to counties to states, handle ~50-100 entities (not millions).

### Options

| Criteria | Hand-coded mapping tables | spaCy + custom NER | rapidfuzz (fuzzy matching) |
|---|---|---|---|
| **Accuracy** | 100% for known entities | ~85-95% after training | ~90-95% with tuned thresholds |
| **Maintenance** | Manual updates when new entities appear | Requires retraining on new data | Thresholds may need tuning |
| **Setup time** | 1 hour | 2-3 days (model training) | 2 hours |
| **Runtime cost** | O(1) dict lookup | Heavy — loads spaCy model (~500MB) | Lightweight — C++ backend |
| **Handles unknowns** | No — fails silently on new entities | Yes — can identify new entities | Partial — matches to closest known |
| **Dependencies** | None | spaCy + model download (~500MB) | rapidfuzz (~2MB) |
| **Suited for dataset size** | Small (< 200 entities) | Large (thousands+) | Medium (100-1000 entities) |

### Recommendation: **Hand-coded mapping tables + rapidfuzz as a fallback**

**Rationale:**
- With ~50-100 known entities (companies, sites, counties), a curated mapping table stored in PostgreSQL is the most reliable approach. It guarantees 100% accuracy for known entities and is trivially auditable.
- rapidfuzz serves as a fallback for ingestion pipelines: when a new company name appears in an EDGAR filing or permit record, rapidfuzz can suggest the closest canonical match (e.g., "AMAZON.COM INC" -> "Amazon") with a confidence score. Below a threshold (e.g., 85%), flag for human review.
- This two-tier approach gives us deterministic matching for known entities and graceful handling of new ones.

**Why not spaCy?** A 500MB model dependency to resolve ~50 companies is not justified. NER is designed for extracting entities from unstructured text, not for matching known company names across structured data sources.

**Schema design:**
```sql
-- companies table (canonical entities)
companies (id, canonical_name, ticker, cik, aliases JSONB)

-- entity_aliases table (for rapid lookup)
entity_aliases (alias_text, company_id, source, added_at)

-- hierarchy
sites (id, company_id, name, county, state, lat, lng, capacity_mw)
```

**Migration difficulty: LOW**
- Create company/alias tables, seed from existing `curated_deals.py` data.
- Add rapidfuzz as a pip dependency (~2MB).
- Write a `resolve_company(name: str) -> Company` function (~30 lines).
- Estimated: 1 day for one engineer.

---

## 5. Data Lineage / Citation Tracking

**Current state:** No lineage tracking. `curated_deals.py` has `source` and `date` fields in the Python dict. EDGAR agent has a file-based cache with no versioning. Mock data has no source attribution.

**Requirements:** Every displayed metric must link to its primary source. Re-runs of ingestion must be reproducible. Auditors (and the user) need to know "where did this number come from?"

### Options

| Criteria | Custom metadata columns | W3C PROV-O ontology | Simple audit trail table |
|---|---|---|---|
| **Complexity** | Low — add columns to existing tables | High — RDF graphs, specialized tooling | Low — single append-only table |
| **Query ergonomics** | Trivial — `SELECT source_url FROM deals WHERE id = X` | Requires SPARQL or graph traversal | Requires JOIN to audit table |
| **Storage overhead** | Minimal — 5-6 extra columns per row | Significant — triples store | Moderate — one row per change |
| **Standards compliance** | None (proprietary) | Full W3C compliance | None (proprietary) |
| **Tooling ecosystem** | None needed | `prov` Python library; Protege | None needed |
| **Fits our dataset** | Yes — dozens to hundreds of rows | Overkill | Yes |
| **Versioning** | Via `parser_version`, `retrieved_at` columns | Native — provenance chains | Via timestamped entries |

### Recommendation: **Custom metadata columns + a lightweight audit trail table**

**Rationale:**
- Every data table gets these standard columns: `source_url`, `source_type` (enum: SEC_FILING, PRESS_RELEASE, PERMIT_DB, SATELLITE, MANUAL), `retrieved_at`, `parser_version`, `confidence` (float 0-1), `raw_snippet` (text excerpt from source).
- A separate `audit_log` table records every ingestion run: `run_id`, `agent_name`, `started_at`, `completed_at`, `records_created`, `records_updated`, `errors`, `git_sha`.
- This is simple, queryable with standard SQL, and fully meets the "where did this number come from?" requirement.

**Why not PROV-O?** The W3C PROV model is designed for complex multi-hop provenance chains (entity A was derived from entity B which was generated by activity C). Our lineage is flat: "this metric came from this URL, fetched at this time, parsed by this version." PROV-O adds conceptual and tooling overhead with no practical benefit for our use case.

**Schema design:**
```sql
-- Standard columns on every data table:
-- source_url       TEXT
-- source_type      VARCHAR(20)  -- SEC_FILING, PRESS_RELEASE, etc.
-- retrieved_at     TIMESTAMPTZ
-- parser_version   VARCHAR(20)  -- e.g., "edgar_v2.1"
-- confidence       FLOAT        -- 0.0 to 1.0
-- raw_snippet      TEXT         -- verbatim excerpt for citation

-- Audit trail table
audit_log (
    id              SERIAL PRIMARY KEY,
    run_id          UUID,
    agent_name      VARCHAR(50),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    records_created INTEGER,
    records_updated INTEGER,
    records_skipped INTEGER,
    errors          JSONB,
    config_snapshot JSONB,      -- parameters used for this run
    git_sha         VARCHAR(40)
)
```

**Migration difficulty: LOW**
- Add columns to SQLModel table definitions (designed in step 1).
- Create the audit_log table.
- Modify ingestion functions to populate metadata.
- Estimated: 1 day for one engineer (done alongside DB migration).

---

## 6. Frontend Error Handling / State Management

**Current state:** Custom `useApi` hook in `frontend/src/hooks/useApi.ts` with basic fetch calls. Sets `error` state but no component renders it. No retry logic. No cache invalidation strategy.

**Requirements:** Consistent loading and error UI across all dashboard panels. Automatic retry on transient failures. Background refetch for stale data. DevTools for debugging.

### Options

| Criteria | TanStack Query (React Query) | SWR | Custom hook (fix existing) |
|---|---|---|---|
| **Bundle size** | 16.2 KB gzipped | 5.3 KB gzipped | 0 KB (already in bundle) |
| **Caching** | Stale-while-revalidate + configurable stale time + garbage collection | Stale-while-revalidate | Manual implementation |
| **Retry** | Built-in exponential backoff (3 retries default) | Built-in (limited config) | Must implement |
| **DevTools** | Official DevTools panel | Community plugin only | None |
| **Mutations** | `useMutation` with optimistic updates, rollback | `useSWRMutation` (simpler) | Manual |
| **Pagination** | `useInfiniteQuery` with bi-directional support | `useSWRInfinite` | Manual |
| **Offline support** | Built-in offline detection + mutation queue | Limited | None |
| **Window focus refetch** | Yes (configurable) | Yes | No |
| **Garbage collection** | Automatic (5-min default) | None | None |
| **Dependent queries** | `enabled` option for query chaining | Conditional fetching | Manual |
| **Learning curve** | Medium — more concepts to learn | Low — simpler API | None |
| **Community / docs** | 42k GitHub stars, excellent docs | 30k GitHub stars, good docs | N/A |

### Recommendation: **TanStack Query (React Query)**

**Rationale:**
- TanStack Query's `staleTime` and garbage collection are critical for a dashboard that displays data with different freshness requirements (permits: weekly, filings: daily, satellite: monthly).
- The DevTools panel is invaluable during development — inspect cache state, trigger refetches, simulate errors.
- Built-in retry with exponential backoff eliminates the need to implement this in every component.
- The `enabled` option allows dependent queries (e.g., only fetch site details after company selection).
- The 16 KB bundle cost is negligible for a dashboard application.

**Why not SWR?** Lacks garbage collection, DevTools, and granular stale-time control. These are important for a multi-panel dashboard with heterogeneous data freshness.

**Why not fix the custom hook?** Reimplementing caching, retry, stale-while-revalidate, garbage collection, and DevTools would take weeks and produce an inferior result.

**Migration pattern:**
```tsx
// Before: custom useApi hook
const { data, loading, error } = useApi('/api/power/capacity');

// After: TanStack Query
const { data, isLoading, error } = useQuery({
  queryKey: ['power', 'capacity'],
  queryFn: () => fetch('/api/power/capacity').then(r => r.json()),
  staleTime: 5 * 60 * 1000,  // 5 minutes
  retry: 3,
});
```

**Migration difficulty: LOW-MEDIUM**
- Install `@tanstack/react-query` and `@tanstack/react-query-devtools`.
- Wrap app in `QueryClientProvider`.
- Replace each `useApi` call with `useQuery` (~12 call sites matching the 12 endpoints).
- Estimated: 1-2 days for one engineer.

---

## 7. API Structure

**Current state:** Single `main.py` with 12 `@app.get()` handlers. No shared dependencies. No middleware. No request validation beyond one `Query()` parameter.

**Requirements:** Modular routing by domain, shared database sessions, consistent error responses, API versioning readiness.

### Options

| Criteria | APIRouter (modular routing) | APIRouter + Dependency Injection | Keep monolithic |
|---|---|---|---|
| **File organization** | Split by domain: `routers/power.py`, `routers/gpu.py`, etc. | Same as left + shared deps | Single file |
| **Shared state** | Via imports | Via `Depends()` — DB sessions, auth, rate limits | Global variables |
| **Testability** | Good — test routers in isolation | Excellent — mock dependencies | Poor — must test entire app |
| **Middleware** | Per-router or global | Per-router or global | Global only |
| **Complexity** | Low | Medium | Lowest |
| **Versioning** | `app.include_router(v1_router, prefix="/api/v1")` | Same | Hard to version |

### Recommendation: **APIRouter + Dependency Injection**

**Rationale:**
- FastAPI's `APIRouter` is the idiomatic way to structure larger applications. The official docs explicitly recommend it for "bigger applications."
- Dependency injection via `Depends()` provides clean database session management: define `get_db()` once, inject it into every handler that needs it.
- This pattern enables testing: inject a test database session to run endpoints against a test DB.
- The migration is mechanical: cut each group of endpoints into its own file, add `router = APIRouter(prefix="/api/power", tags=["power"])`, and `include_router` in `main.py`.

**Proposed structure:**
```
backend/
  main.py              # App factory, lifespan, include_router calls
  core/
    config.py          # Settings via pydantic-settings
    database.py        # Engine, session factory, get_db dependency
  routers/
    power.py           # /api/power/* endpoints
    gpu.py             # /api/gpu/* endpoints
    permits.py         # /api/permits/*
    satellite.py       # /api/satellite/*
    filings.py         # /api/filings/* (EDGAR + curated)
    sources.py         # /api/sources/*
    health.py          # /health
  models/
    deal.py            # SQLModel table definitions
    company.py
    permit.py
    audit.py
  services/
    edgar_service.py   # Business logic (moved from agents/)
    permit_service.py
    entity_resolver.py
  agents/              # Scheduled ingestion agents
    edgar_agent.py
    permit_agent.py
```

**Migration difficulty: LOW**
- Purely structural refactor — no logic changes.
- Each router file is ~20 lines (decorator + handler + return).
- Estimated: 0.5 days for one engineer.

---

## Summary Decision Matrix

> **These choices are LOCKED per [00-DECISIONS-AND-CONSTRAINTS.md](00-DECISIONS-AND-CONSTRAINTS.md) §2.** Comparison tables above are retained for context; the recommendations below are final.

| Layer | Choice | Key Dependencies | Migration Effort | Priority |
|---|---|---|---|---|
| **Persistent Store** | PostgreSQL + SQLModel | `sqlmodel`, `asyncpg`, `alembic` | Medium (3-4 days) | P0 — blocks everything |
| **Task Queue** | APScheduler (in-process) | `apscheduler`, `fastapi-apscheduler` | Low (1 day) | P1 — enables automated ingestion |
| **HTTP Client** | httpx | `httpx`, `stamina` | Low (0.5 day) | P1 — unblocks async EDGAR |
| **Entity Resolution** | Mapping tables + rapidfuzz | `rapidfuzz` | Low (1 day) | P2 — needed for multi-source joins |
| **Data Lineage** | Custom columns + audit table | None (schema design) | Low (1 day, with DB) | P0 — built into initial schema |
| **Frontend State** | TanStack Query | `@tanstack/react-query` | Low-Medium (1-2 days) | P2 — improves UX reliability |
| **API Structure** | APIRouter + DI | None (FastAPI built-in) | Low (0.5 day) | P0 — do first, enables clean DB integration |

### Recommended Implementation Order

1. **API Structure refactor** (0.5 day) — reorganize files before adding complexity.
2. **PostgreSQL + SQLModel + Data Lineage columns** (3-4 days) — foundational; design schema with lineage built-in from day one.
3. **httpx migration** (0.5 day) — quick win, unblocks async.
4. **APScheduler integration** (1 day) — automate EDGAR, permits on schedules.
5. **Entity Resolution tables + rapidfuzz** (1 day) — normalize company data.
6. **TanStack Query migration** (1-2 days) — frontend reliability.

**Total estimated effort: ~8-10 engineering days** for one engineer, or ~4-5 days with two engineers working in parallel (frontend/backend split at step 6).

---

## Key References & Links

### Persistent Store
- [SQLModel documentation](https://sqlmodel.tiangolo.com/)
- [SQLModel async session support](https://github.com/fastapi/sqlmodel/blob/main/sqlmodel/ext/asyncio/session.py)
- [FastAPI + SQLModel + Alembic guide](https://testdriven.io/blog/fastapi-sqlmodel/)
- [DuckDB vs Postgres for embedded analytics](https://motherduck.com/learn/duckdb-vs-postgres-embedded-analytics/)
- [pg_duckdb — DuckDB-powered Postgres](https://github.com/duckdb/pg_duckdb)

### Task Queue / Scheduler
- [APScheduler on PyPI](https://pypi.org/project/APScheduler/)
- [FastAPI + APScheduler integration](https://rajansahu713.medium.com/implementing-background-job-scheduling-in-fastapi-with-apscheduler-6f5fdabf3186)
- [Dramatiq motivation and comparison](https://dramatiq.io/motivation.html)
- [Choosing the right Python task queue](https://judoscale.com/blog/choose-python-task-queue)

### Async HTTP Client
- [HTTPX vs Requests vs AIOHTTP comparison](https://oxylabs.io/blog/httpx-vs-requests-vs-aiohttp)
- [SEC EDGAR rate limits best practices](https://tldrfiling.com/blog/sec-edgar-api-rate-limits-best-practices)

### Entity Resolution
- [RapidFuzz GitHub](https://github.com/rapidfuzz/RapidFuzz)
- [RapidFuzz documentation](https://rapidfuzz.github.io/RapidFuzz/)

### Data Lineage
- [PostgreSQL audit trails with triggers](https://oneuptime.com/blog/post/2026-01-25-postgresql-audit-trails-triggers/view)
- [W3C PROV Python library](https://github.com/trungdong/prov)

### Frontend State
- [TanStack Query vs SWR 2025 comparison](https://refine.dev/blog/react-query-vs-tanstack-query-vs-swr-2025/)
- [TanStack Query official comparison table](https://tanstack.com/query/latest/docs/framework/react/comparison)

### API Structure
- [FastAPI Bigger Applications guide](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
- [FastAPI best practices repo](https://github.com/zhanymkanov/fastapi-best-practices)

---

## Warnings / Gotchas

1. **SQLModel maturity:** SQLModel is still at 0.0.x versioning. For complex queries (multi-table joins, CTEs), you may need to drop down to raw SQLAlchemy. This is supported — SQLModel models are SQLAlchemy models underneath.

2. **APScheduler persistence:** If the FastAPI process restarts, in-memory job state is lost. Use `SQLAlchemyJobStore` (backed by the same Postgres) to persist job schedules across restarts.

3. **SEC EDGAR rate limits are strict:** A 403 block lasts ~10 minutes and affects ALL requests from your IP. Always stay at 8 req/s or below. Never retry a 403. Cache aggressively.

4. **asyncpg requires `greenlet`:** The `greenlet` package is a compiled C extension. Ensure your Docker/CI images have build tools, or pin to a pre-built wheel.

5. **TanStack Query + React 19:** TanStack Query v5 is compatible with React 19. Verify you install v5 (not v4), as v4 has peer dependency issues with React 19.

6. **Alembic + SQLModel friction:** Alembic's `env.py` needs explicit configuration to discover SQLModel metadata. Follow the TestDriven.io guide linked above for the exact setup pattern.

7. **rapidfuzz threshold tuning:** Start with a threshold of 85 for company name matching. Below that, flag for human review. "Amazon" vs "AMAZON.COM INC" scores ~62 on simple ratio but ~91 on token_set_ratio — use `token_set_ratio` for corporate names.

---

## Conformance to 00-DECISIONS-AND-CONSTRAINTS.md

- **§2 Tech Stack:** All recommendations in the Summary Decision Matrix match the locked choices in §2.1 of the brief.
- **§4 EDGAR APIs:** Full endpoint set referenced.
- Comparison tables retained for historical context; recommendations are final.
