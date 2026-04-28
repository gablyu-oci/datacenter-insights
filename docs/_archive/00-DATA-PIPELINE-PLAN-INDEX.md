# Data-Source Pipeline -- Project Plan Index

**Date:** 2026-04-28 | **Status:** Complete (Planning Phase) | **Next:** Implementation

---

## Documents

| # | Document | Author | Lines | Purpose |
|---|----------|--------|-------|---------|
| 01 | [01-DATA-PIPELINE-PRD.md](01-DATA-PIPELINE-PRD.md) | PM Agent | 637 | Product requirements, user stories, acceptance criteria |
| 02 | [02-TECH-STACK-RESEARCH.md](02-TECH-STACK-RESEARCH.md) | Research Agent | 832 | Technology assessment for all 7 pipeline components |
| 03 | [03-PIPELINE-ARCHITECTURE.md](03-PIPELINE-ARCHITECTURE.md) | Architect Agent | 1520 | System architecture, schemas, adapter contracts, data flow |
| 04 | [04-UX-DATA-STATES.md](04-UX-DATA-STATES.md) | Designer Agent | 1331 | UX for data states, citations, empty states, transitions |

> **Canonical decisions & constraints:** [00-DECISIONS-AND-CONSTRAINTS.md](00-DECISIONS-AND-CONSTRAINTS.md) is the single source of truth for all resolved decisions, locked tech-stack choices, dataset specs, EDGAR API patterns, and UX rules. All documents in this track conform to it.

---

## Executive Summary

This plan replaces the current mock-data layer (`random.*` per-request across 7 of 9 dashboard tabs, ~78% fake) with a real data ingestion pipeline for the Datacenter & Power Intelligence Platform. Phase 1 focuses on **Northern Virginia only** (Loudoun + Prince William counties) for **3 hyperscalers** (Microsoft, AWS, Google).

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| EDGAR library | **edgartools** (free, MIT) | Replaces 100+ lines of custom urllib/regex; built-in XBRL |
| HTTP client | **httpx** (async) | Replace blocking `urllib.request`; already edgartools dep |
| Permits source | **Shovels.ai** ($599/mo) or VA Open Data (free fallback) | Standardized API across jurisdictions; verify coverage first |
| Transcripts | **Financial Modeling Prep** ($29-99/mo) + Claude LLM extraction | Speaker-tagged JSON; covers all 5 target tickers |
| Satellite | **Sentinel-2** (free) via Google Earth Engine | Proof-of-concept; upgrade to Planet Labs in Phase 2 |
| Database | **PostgreSQL + JSONB** | Mature; JSONB for semi-structured data; PostGIS-ready |
| Entity resolution | **rapidfuzz** + curated alias table + Census geocoder | MIT license; fast; explainable at our scale |
| Scheduling | **APScheduler** (in-process) | Zero infrastructure; perfect for small team prototype |
| Confidence scores | **Deterministic** (based on parsing certainty) | Never `random.uniform()` -- formula: base + MW_match + counterparty + source_type |
| No-data handling | **Explicit null + reason** | No silent empty arrays; no fake numbers; honest states |

> All decisions above are **locked** per [00-DECISIONS-AND-CONSTRAINTS.md](00-DECISIONS-AND-CONSTRAINTS.md). No further debate.

### Cost

| Item | Monthly |
|------|---------|
| Shovels.ai (permits) | $599 |
| Financial Modeling Prep (transcripts) | $29-99 |
| All other tools | $0 |
| **Total** | **$628-698/mo** |

### Development Effort

**14-21 engineering days** across all pipeline components.

### Phase 1 Scope (NoVA MVP)

| Component | Status in Phase 1 |
|-----------|-------------------|
| EDGAR 8-K/10-K (hardened) | Active -- MSFT, AWS, GOOG |
| Curated deals (migrated to DB) | Active -- 22 deals preserved |
| County permits (Loudoun + PWC) | Active -- weekly cadence |
| NVIDIA transcript extraction | Prototype -- quarterly |
| Satellite change detection | Deferred -- "Coming Soon" UI |
| NICs/Optics (Broadcom, Coherent, Lumentum) | Deferred -- explicit "no data" |
| TSMC packaging capacity | Deferred -- explicit "no data" |
| Aterio Excel datasets | **Active** -- primary site seed (CSV 73 cols), events (957 rows), energy projects (1695 rows). See §3 of 00-DECISIONS-AND-CONSTRAINTS.md. |

### Triangulation Layers

| Layer | Phase 1 State |
|-------|---------------|
| L1: Contracted GW | Real data (EDGAR + curated deals) |
| L2: GPU power-draw inference | Partial (NVIDIA only, with assumption sliders) |
| L3: NICs/optics validation | Explicit "no data yet" |
| L4: Permit ground truth | Real data (Loudoun + PWC) |

### Critical Path / Blockers

1. **Shovels.ai procurement** -- verify NoVA coverage with 250 free API calls before committing
2. **PostgreSQL setup** -- self-hosted PostgreSQL process on this OCI VM (Decision #1 + #4, no Docker), schema migration with Alembic
3. **edgar_agent.py hardening** -- eliminate 5 silent `except Exception` blocks, convert to async
4. **mock_data.py elimination** -- replace each function with real pipeline query or explicit no-data

---

## How to Read These Documents

1. **Start with 01-PRD** to understand what we're building and why
2. **Read 02-TECH-STACK** for the technology choices and tradeoffs
3. **Read 03-ARCHITECTURE** for the system design, database schema, and adapter contracts
4. **Read 04-UX-STATES** for how data states appear in the UI and the mock-to-real transition plan

---

## Conformance to 00-DECISIONS-AND-CONSTRAINTS.md

This index and all documents it references conform to `00-DECISIONS-AND-CONSTRAINTS.md` (locked 2026-04-28).
