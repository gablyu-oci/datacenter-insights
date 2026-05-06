# Datacenter & Power Intelligence Platform — Master Architecture Plan

> **Date:** 2026-04-28 | **Owner:** Strategic Insights Team (OCI) | **Stakeholder:** the user
> **Status:** Planning Complete — Ready for Engineering Review

---

## Executive Summary

This document is the **master index** for the architecture evolution of the Datacenter & Power Intelligence Platform — from the current single-file FastAPI prototype (78% mock data) to a production-grade, source-cited intelligence platform.

Four planning documents were produced by specialist teams working in parallel:

| # | Document | Author | Purpose |
|---|----------|--------|---------|
| 01 | [Architecture Evolution PRD](01-architecture-evolution-prd.md) | Product Manager | Why we need to evolve, user stories, phased scope, success criteria |
| 02 | [Tech Stack Research](02-tech-stack-research.md) | Technology Researcher | Evaluated 2-3 options per layer, recommended stack with rationale |
| 03 | [Architecture Design](03-architecture-design.md) | System Architect | Component diagrams, data model, API contracts, migration path |
| 04 | [UX Evolution Plan](04-ux-evolution-plan.md) | Product Designer | Error states, data provenance, filters, triangulation redesign |

> **Canonical decisions & constraints:** [00-DECISIONS-AND-CONSTRAINTS.md](00-DECISIONS-AND-CONSTRAINTS.md) is the single source of truth for all resolved decisions, locked tech-stack choices, dataset specs, EDGAR API patterns, and UX rules. All documents in this track conform to it.

---

## Current State (Problem)

The prototype at `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/` has these critical issues:

| Issue | Location | Impact |
|-------|----------|--------|
| **78% mock data** | `backend/data/mock_data.py` — 7 functions using `random.*` | Numbers change on every page refresh; users may draw wrong conclusions |
| **Monolithic API** | `backend/main.py` — 12 GET endpoints in one file | Untestable, no separation of concerns |
| **No database** | Data in Python dicts + file cache | Nothing persists; no lineage, no audit trail |
| **Blocking sync I/O** | `backend/agents/edgar_agent.py` — `urllib.request` | Blocks the FastAPI async event loop for 10s+ |
| **Silent error swallowing** | 5 bare `except Exception` in `edgar_agent.py` | Failures invisible; no logging, no alerts |
| **Frontend error blindness** | `frontend/src/hooks/useApi.ts` sets `error` but no tab renders it | Users see infinite spinners on API failures |
| **Security debt** | CORS `*`, Google Maps key in `.env.local`, no `requirements.txt` | Open to abuse; key leakable; non-reproducible builds |

---

## Target Architecture (Summary)

```
                    ┌──────────────────────────────────────────────┐
                    │              External Sources                 │
                    │  SEC EDGAR · Permits · Earnings · Satellite   │
                    └──────────┬───────────────────────┬───────────┘
                               │                       │
                    ┌──────────▼───────────────────────▼───────────┐
                    │           Ingestion Layer                     │
                    │  SourceAdapter protocol per source            │
                    │  APScheduler (weekly/daily/quarterly cadence) │
                    │  httpx async client (replaces urllib)         │
                    └──────────┬───────────────────────────────────┘
                               │
                    ┌──────────▼───────────────────────────────────┐
                    │     Normalization + Entity Resolution         │
                    │  company → site → county → state → country   │
                    │  Mapping tables + rapidfuzz fallback          │
                    └──────────┬───────────────────────────────────┘
                               │
                    ┌──────────▼───────────────────────────────────┐
                    │        PostgreSQL + SQLModel                  │
                    │  6 tables: companies, sites, deals,           │
                    │  data_points, geo_hierarchy, ingestion_runs   │
                    │  Every row: source_url, retrieved_at,         │
                    │  parser_version, confidence, raw_snippet      │
                    └──────────┬───────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
   ┌──────────▼──────┐  ┌─────▼──────┐  ┌──────▼──────────┐
   │  8 APIRouters   │  │ Triangulat.│  │  Audit/Sources  │
   │  power, gpu,    │  │ Engine     │  │  API            │
   │  permits, sat,  │  │ (pure fn)  │  │                 │
   │  supply_chain,  │  │ L1→L2→L3→L4│  │                 │
   │  sources, health│  └─────┬──────┘  └──────┬──────────┘
   └────────┬────────┘        │                │
            └────────────┬────┘────────────────┘
                         │
              ┌──────────▼───────────────────────────────────┐
              │          React 19 + TanStack Query            │
              │  ErrorBoundary · DataProvenanceBanner         │
              │  ConfidenceBadge · SourceTooltip · Filters    │
              │  9 tabs + GlobalFilterContext                  │
              └──────────────────────────────────────────────┘
```

---

## Agreed Tech Stack

| Layer | Choice | Key Rationale |
|-------|--------|--------------|
| **Database** | PostgreSQL + SQLModel + Alembic | JSONB for citation metadata, async via asyncpg, same-author as FastAPI |
| **Scheduler** | APScheduler (in-process) | Zero extra processes; 5 jobs don't justify Celery/Redis |
| **HTTP Client** | httpx (async) | Drop-in urllib replacement; rate limiting for EDGAR's 10 req/s |
| **Entity Resolution** | Mapping tables + rapidfuzz | 100% accuracy for known entities; fuzzy fallback for new ones |
| **Data Lineage** | Custom columns + audit_log table | Every row carries source_url, retrieved_at, parser_version, confidence |
| **Frontend Data** | TanStack Query (React Query v5) | Stale-while-revalidate, retry, DevTools; replaces error-swallowing useApi |
| **API Structure** | FastAPI APIRouter + Depends() | 8 routers replacing monolithic main.py; injectable DB sessions |
| **Dependency Mgmt** | uv + pyproject.toml | Fast, lockfile-based; replaces missing requirements.txt |

---

## Phased Rollout

### Phase 1 — One Vertical, End-to-End Real (Weeks 1-6)

**Scope:** Northern Virginia | MSFT / AWS / GCP | Real data only

| Week | Backend | Frontend |
|------|---------|----------|
| **1** | Split main.py into 8 APIRouters; add pyproject.toml via uv; restrict CORS | Add ErrorBoundary + error states to all tabs; mock data banners |
| **2** | PostgreSQL + SQLModel schema (6 tables); Alembic init; seed curated_deals into DB | Install TanStack Query; replace useApi across all 12 call sites |
| **3** | Convert edgar_agent to async httpx; add structlog; eliminate bare except | Add ConfidenceBadge + SourceTooltip to Power tab charts |
| **4** | APScheduler: EDGAR hourly, permits weekly; ingestion_runs audit trail | GlobalFilterContext (company + geography); persist across tabs |
| **5** | Entity resolution tables; wire Power + Triangulation endpoints to DB | Triangulation tab redesign: L1-L4 flow, assumption sliders |
| **6** | Triangulation engine as pure function over DB; end-to-end testing | Loading skeletons; CitationFooter; polish and integration test |

**Phase 1 Exit Criteria:**
- >=80% real data ratio in delivered tabs (Power, Triangulation, Sources)
- >=95% of displayed metrics link to primary source
- Zero bare `except` clauses
- All API errors render in the UI (no more infinite spinners)
- the user can answer "where does OCI sit vs hyperscalers in NoVA?" without leaving the dashboard

### Phase 2 — Scale Pillars (Weeks 7-14)
- Add Meta + OCI to power tracking
- NIC + optics ingestion (Coherent, Lumentum earnings)
- Expand permits beyond NoVA (TX, AZ, OR, IA)
- GPU Supply tab wired to real NVIDIA/TSMC earnings data

### Phase 3 — Intelligence Layer (Weeks 15-20)
- Satellite imagery integration (Planet Labs trial)
- Anomaly detection (week-over-week permit/filing deltas)
- Auto-generated weekly briefing from the same data layer

---

## Risk Register

| # | Risk | Severity | Mitigation | Owner |
|---|------|----------|------------|-------|
| R1 | Mock-data hangover — users trust fake numbers | **High** | Tag tabs as "PREVIEW - SIMULATED DATA" banner immediately; replace with "no data" state | Designer / Frontend |
| R2 | EDGAR brittleness — silent except + sync urllib | **High** | Async httpx + structlog + circuit breaker; never retry 403 | Backend |
| R3 | Vendor lock-in — Shovels.ai, SemiAnalysis gating | **Medium** | SourceAdapter interface; one free fallback per pillar | Architect |
| R4 | Security debt — CORS *, Maps key in .env.local | **Medium** | Restrict CORS to localhost + deploy origin; restrict API key to referrer | Backend / Infra |
| R5 | useApi error swallowing | **High** | TanStack Query + ErrorBoundary; per-section error rendering | Frontend |
| R6 | Entity resolution complexity | **Low** | Start with hand-coded mapping + rapidfuzz; flag unknowns for review | Backend |
| R7 | Inference assumptions compound uncertainty | **Medium** | Expose assumption sliders; show error bars, never single numbers | Designer / Frontend |
| R8 | No requirements.txt — non-reproducible builds | **Medium** | uv + pyproject.toml + lockfile in Week 1 | Backend |
| R9 | Curated deals staleness | **Low** | Move to DB; add `stale_after` field; highlight age in UI | Backend / Frontend |

---

## Estimated Effort

| Work Stream | Effort | Parallelizable? |
|-------------|--------|----------------|
| Backend restructure (routers, DB, async, scheduler) | ~8 engineering days | Yes — independent of frontend |
| Frontend evolution (TanStack Query, error states, provenance, filters) | ~6 engineering days | Yes — independent of backend |
| Triangulation engine + end-to-end integration | ~3 engineering days | After backend DB is ready |
| **Total** | **~17 engineering days** | **~10 calendar days with 2 engineers** |

---

## Resolved Decisions

All open decisions are now resolved. See [00-DECISIONS-AND-CONSTRAINTS.md](00-DECISIONS-AND-CONSTRAINTS.md) §1 for the authoritative table.

| # | Decision | Resolution |
|---|---|---|
| 1 | Postgres hosting | Self-hosted on this OCI VM |
| 2 | SEC EDGAR API usage | Official `data.sec.gov` REST APIs |
| 3 | OCI inclusion | Full participant in every pillar with %-share |
| 4 | Deploy target | This OCI compute instance |
| 5 | Auth | No auth in v1 |

---

## How to Read These Documents

**Start here** (this document) for the high-level picture. Then dive into specifics:

- **"Why are we doing this?"** → [01-architecture-evolution-prd.md](01-architecture-evolution-prd.md) — problem statement, user stories, success metrics
- **"What tech should we use?"** → [02-tech-stack-research.md](02-tech-stack-research.md) — comparison tables, pros/cons, gotchas
- **"How does the system fit together?"** → [03-architecture-design.md](03-architecture-design.md) — Mermaid diagrams, data model, API contracts, migration steps
- **"What does the user see?"** → [04-ux-evolution-plan.md](04-ux-evolution-plan.md) — error states, provenance UX, filters, triangulation redesign, component specs

---

*Generated 2026-04-28 by the Strategic Insights architecture planning team.*

---

## Conformance to 00-DECISIONS-AND-CONSTRAINTS.md

This index and all documents it references conform to `00-DECISIONS-AND-CONSTRAINTS.md` (locked 2026-04-28).
