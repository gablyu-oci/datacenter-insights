# Open Tensions
**Date:** 2026-04-28 · **Status:** Living — revisit when escalating from MVP to scaled v1.

This file captures decisions that are **deliberately deferred**: trade-offs where the locked stack works for the MVP but may need to be re-litigated as scope grows. Each tension lists the locked choice, the alternative pulled in by a later requirement, and the trigger condition that should prompt escalation. Do not silently violate the locked stack; if a tension reaches its trigger, raise it and update `docs/planning/00-DECISIONS-AND-CONSTRAINTS.md`.

---

## 1. Orchestration: APScheduler vs Dagster

| | Locked | Alternative |
|---|---|---|
| Choice | **APScheduler** in-process (per `00-DECISIONS-AND-CONSTRAINTS.md` §2.1) | Dagster (recommended in the generator-permit pipeline plan) |
| Strength | Zero ops overhead, single-process, fits FastAPI's event loop, good for cron-style polling. | Dependency graphs between assets, asset materialization, human-review queue UIs, parallel runs across many sources, observability dashboards. |
| Cost | $0, no extra service. | Self-hosted Dagster needs Postgres (we have it) + a worker process + a UI. Operational complexity is real. |

**Use APScheduler for v1, including the generator-permit pipeline.** Cron-style polling of EPA ECHO, TCEQ, Socrata state portals, and a weekly LLC→parent resolver run all fit comfortably.

**Trigger to revisit:** any of the following — (a) we exceed ~10 distinct ingestion adapters, (b) human-review queues need a real UI rather than a spreadsheet, (c) we want true asset lineage (e.g. "regenerate just the permits for AZ for Q3 2025"), (d) we add backfill or replay as a first-class operation. **Migrate the generator-permit pipeline first** (it has the most independent assets); leave the rest of the project on APScheduler until the cost/benefit also flips.

---

## 2. Raw-blob storage: VM filesystem vs OCI Object Storage

| | Locked | Alternative |
|---|---|---|
| Choice | **VM local filesystem** under `data/raw/{source}/{yyyy-mm-dd}/` (per Decision #1 + #4: self-hosted on this OCI compute instance, no Docker, no managed services) | OCI Object Storage / S3-compatible (recommended in the generator-permit pipeline plan for raw PDFs) |
| Strength | Zero setup, atomic with the Postgres lineage rows on the same disk. | Durable, virtually unlimited capacity, easier to share between processes / hosts, cheaper at scale. |

**Use VM filesystem for v1.** Raw PDFs from generator permits, EDGAR filings (`edgartools` already caches locally), Aterio CSV snapshots — all small, all fine on local disk.

**Trigger to revisit:** local `data/raw/` exceeds ~50 GB, OR we move to multi-host deployment, OR we need to share raw blobs with another OCI service. At that point, swap the storage adapter to OCI Object Storage; only the upload/download functions change because lineage records hold the URL not the path.

---

## 3. Entity resolution: layered approach (resolved 2026-04-28)

**Updated:** what was a tension is now a layered design with three stages, all in MVP:

| Stage | Mechanism | Where used |
|---|---|---|
| 1 | **rapidfuzz + curated alias table + ticker/CIK exact match** | Public hyperscalers via Aterio's `PROVIDER_TICKER_NAME` (`MSFT`, `META`, `GOOG`, `AMZN`, `ORCL`). Fast, deterministic, free. Catches ~95% of Aterio-driven cases. |
| 2 | **SEC Exhibit 21 deterministic lookup** | LLC names that appear directly in a public hyperscaler's 10-K Exhibit 21 subsidiaries list. Pre-ingested DB lookup; no LLM. Catches the easy LLC cases. |
| 3 | **Llama Stack agent with tool-use** (`oci/openai.gpt-5.4`, see `00-DECISIONS-AND-CONSTRAINTS.md` §4.2 Agent C) | Ambiguous LLC permittees that pass through stages 1–2. Agent runs deterministic tools (OpenCorporates, parcel deeds, ISO queues, web search) and weighs evidence. Confidence ≥ 0.7 auto-publishes; below threshold goes to `permit_parent_review_queue`. |

**No tension remaining** — the three stages are complementary, all ship in Phase 1 / 1.5, and the agent is on internal Llama Stack so cost is not a blocker.

**Trigger to revisit:** if the agent's auto-publish rate (above-threshold matches as fraction of total queued candidates) drops below ~50% for a quarter sustained, recalibrate the threshold or upgrade to a stronger reasoning model (`oci/xai.grok-4.20-reasoning` or `oci/openai.o3`). If labeled-data quality is the issue, build the human-review-queue → labeled-training-set flywheel (currently out of scope).

---

## 4. Satellite resolution: Sentinel-2 vs Maxar

| | Locked | Alternative |
|---|---|---|
| Choice | **Sentinel-2 via Google Earth Engine** (10 m, free) | Planet Labs PlanetScope (~3 m, paid) or Maxar (sub-meter, paid) |
| Strength | Free, near-global, 5-day revisit. Sufficient to detect "is this site under construction" / "has the slab been poured" / "are there generators on the pad now" at building-scale. | Sub-meter detail. Counts visible cooling units, individual transformer pads, individual GPU container modules, etc. |

**Sentinel-2 for v1.** Phase-detection is what Karan asked for — announcement → groundbreak → completion. 10 m resolution clears that bar.

**Trigger to revisit:** Karan or analyst feedback that we need to count individual buildings within a campus, count visible cooling units (often a leading indicator of MW commit), or detect equipment-level changes between weekly captures. At that point, Planet Labs is the cheaper next step; Maxar only if sub-meter is genuinely required.

---

## 5. Aterio: one-time CSV vs licensed feed

| | MVP | Phase 2 |
|---|---|---|
| Choice | **One-time `data_center_inventory_20260428.csv` snapshot** (received 2026-04-28; static for MVP per `00-DECISIONS-AND-CONSTRAINTS.md` §3.0). The CSV is **already national** — covers all 50 US states; no scope expansion needed in Phase 2 from a coverage perspective, only freshness. | Licensed Aterio feed at weekly or monthly cadence |
| Implication | Aterio data is frozen. New sites announced after 2026-04-28 must come from EDGAR / EPA ECHO / trade-press until refresh. | Ingestion must be idempotent (upsert on `ATERIO_*_UID`) so a refreshed CSV drops in cleanly. |

**Design now for Phase 2.** All Aterio ingestion code uses upsert semantics on `ATERIO_DATA_CENTER_UID` and `ATERIO_DATA_CENTER_CAMPUS_UID`. Lineage records preserve the snapshot date so we can diff between two CSVs. No code changes required at refresh time — only re-running the ingest.

**Trigger to revisit:** when Aterio is licensed. Procurement decision pending with Karan.

---

## 6. National permit coverage: free state-by-state vs paid Shovels.ai

| | MVP | Phase 2 |
|---|---|---|
| Choice | **6 states with structured free APIs** (VA Open Data, NY DEC Socrata, WA Ecology, CO CDPHE, OR DEQ, TX TCEQ) — covers a fraction of US datacenter permit volume but is honest about it via `<CoverageBadge />` and per-state empty states (per `00-DECISIONS-AND-CONSTRAINTS.md` §5.3). | Shovels.ai national permit API ($599/mo) — fills the 44+ states currently rendering "no coverage". |
| Strength | $0; verifiable; API-first where structure already exists. | Single integration, near-national coverage, normalized schema. |

The PRD calls for **national scope from day one**. Aterio + EDGAR + EPA ECHO already deliver national for sites/filings/federal-baseline air permits. **Building permits are the single pillar that structurally cannot be national for free** — every additional state would require either a custom scraper per county (high build + maintenance cost) or filing standing public-records requests (slow ramp; covered by the generator-permit pipeline §7.5 of `03-PIPELINE-ARCHITECTURE.md`).

**MVP behavior:** the Building Permits pillar shows `Partial (6 states)` coverage; clicking any of the other 44 states surfaces the per-state empty state with the roadmap message.

**Trigger to revisit:** when Karan or analysts repeatedly ask "what about \<state X>" for X outside the 6 covered states, OR when the generator-permit pipeline reaches state-level coverage parity with Shovels.ai (in which case Shovels becomes redundant for many use-cases and we may skip it entirely).

---

## 7. EDGAR transcript-grade GPU inference: revenue ÷ ASP precision

This is a **data-quality** tension, not a stack tension, but worth flagging.

EDGAR's free `companyfacts` API gives quarterly NVIDIA datacenter-segment revenue but **no unit volumes**. To convert revenue → GPU units we need the average selling price (ASP) per generation, which lives in earnings-call transcripts ($/GPU commentary from Jensen). Free transcript access (IR pages, occasional Seeking Alpha) is flaky. Financial Modeling Prep at $29–99/mo would solve transcript *availability*; **transcript extraction quality is no longer the bottleneck since OCI Llama Stack is internal/free** (per `00-DECISIONS-AND-CONSTRAINTS.md` §4.2).

**MVP behavior:** publish quarterly directional indicators with explicit error bars and an "ASP assumption" slider (default range $25K–$45K per Hopper-class GPU). Surface the assumption in the UI rather than hide it.

**Trigger to revisit:** when Karan asks for "the inventory gap number" as a single value. At that point, license FMP (Phase 2 already-deferred decision) — we cannot be precise without reliable transcript inputs, even with a perfect extractor.

---

## 8. Llama Stack model selection per agent (resolved 2026-04-28)

**Locked picks** (mirrors `00-DECISIONS-AND-CONSTRAINTS.md` §4.2 model-pick table):

| Agent | Primary | Fallback | Why this pair |
|---|---|---|---|
| EDGAR 8-K extractor | `oci/openai.gpt-5.4-mini` | `oci/google.gemini-2.5-flash` | Cheap, fast, JSON-mode; high-volume single-turn extraction. |
| Permit PDF extractor | `oci/google.gemini-2.5-pro` | `oci/cohere.command-a-vision` | Vision-capable; layout-aware; pdfplumber/Tesseract handle structured layer first. |
| LLC → Parent resolver | `oci/openai.gpt-5.4` | `oci/xai.grok-4.20-reasoning` | Best tool-calling fidelity; reasoning across mixed signals. |
| Triangulation Q&A | `oci/openai.gpt-5.4` | `oci/xai.grok-4.20-reasoning` | Same; conversational + tool-using. |
| Weekly Brief | `oci/openai.gpt-5.4-mini` | `oci/google.gemini-2.5-flash` | Scheduled, batched; cost-conscious within internal budget. |
| Embeddings | `oci/openai.text-embedding-3-large` | `oci/cohere.embed-english-v3.0` | Quality first; Cohere fallback for bulk. |

**Trigger to revisit per agent:**
- **EDGAR / Permit extractors:** if extraction accuracy on the eval set drops below 85%, swap primary to `oci/openai.gpt-5.4` (more capable, slower).
- **LLC resolver / Q&A:** if tool-calling failure rate exceeds 5% (agent picks wrong tool, or fails to terminate), swap primary to `oci/openai.o3` (deeper reasoning, slower) or `oci/xai.grok-4.20-multi-agent` (multi-agent variant).
- **Embeddings:** if vector-search recall on permit narratives drops below acceptable, switch to `oci/cohere.embed-v4.0` (latest Cohere) and re-index.

**Out of scope for MVP:**
- Per-agent fine-tuning (Llama Stack supports it; we don't have the labeled data yet).
- Routing across providers based on task (e.g. always-Grok for reasoning, always-GPT for extraction). MVP picks one per agent and sticks with it.
- Multi-agent orchestration (`oci/xai.grok-4.20-multi-agent`) — interesting but unnecessary for v1.

---

## How to use this document

When implementing, if you're about to violate one of the locked choices listed here, **stop**: either the trigger condition has been met (in which case update `00-DECISIONS-AND-CONSTRAINTS.md` first, then proceed), or it hasn't and the locked choice is still right. Don't quietly add a Dagster dep, don't quietly point at S3, don't quietly bypass rapidfuzz with a custom resolver — surface the trade-off here first.
