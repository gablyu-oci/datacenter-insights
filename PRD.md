# PRD — Datacenter & Power Intelligence Platform
**Owner:** Strategic Insights team (OCI) · **Stakeholder:** Karan · **Status:** Draft v0.1 · **Date:** 2026-04-28

---

## 1. Background & Problem

OCI strategy lacks a single, source-cited view of where hyperscalers (Microsoft, AWS, GCP, Meta, and OCI itself) are securing **power** and **compute** capacity. Today's prototype is a weekly digest seeded mostly with mock data (~22% real / 78% mocked across 9 tabs), with credible-looking confidence scores that do not reflect ground truth. The team can't yet answer Karan's core question:

> *Is there enough power being contracted to actually run all the GPUs being shipped — and where is the gap?*

Karan wants the tool to **evolve from a digest into a data-driven intelligence platform** — every datapoint clickable to its primary source, every chart backed by filings/permits/earnings rather than randomized mocks.

---

## 2. Goals (v1)

1. **Power Pillar** — side-by-side GW view of MSFT / AWS / GCP / Meta / OCI sourced from public filings, utility agreements, and county permits. OCI is a full participant in every comparison, not a sidebar.
2. **GPU Supply Pillar** — quarterly NVIDIA / TSMC / Coherent / Lumentum signals: GPUs shipped, NICs shipped, optics shipped, packaging capacity.
3. **Triangulation Engine** — a 4-layer model that reconciles contracted power vs estimated deployed GPUs, validated by NIC/optics shipments and county permits.
4. **Source Integrity** — every metric in the UI links to a primary source (SEC URL, permit record ID, transcript timestamp). No headline number without a citation.
5. **Phase-1 Demo** — Power Map tab spanning all 50 US states + DC for 5 hyperscalers (MSFT/AWS/GCP/Meta/OCI), with state-API permit overlays where available (VA, NY, WA, CO, OR, TX) and explicit `<NoStateCoverage />` for the rest. Working triangulation per state, with per-layer coverage transparency.
6. **OCI %-share Views** — every category tab surfaces OCI percentage share relative to hyperscalers, enabling at-a-glance competitive positioning.

### Non-goals (v1)
- Global geographic coverage on day one.
- Predictive forecasting / ML demand models.
- Internal Oracle data sources beyond public OCI announcements.
- Replacing the weekly digest entirely (digest can remain as a downstream consumer of the same data layer).

---

## 3. Users & Use Cases

| Persona | Primary use case |
|---|---|
| **Karan (exec sponsor)** | "Where does OCI sit relative to hyperscalers in power/geographic coverage *this quarter*, and where's the inventory-vs-deployment gap?" — drill-down with sources. |
| **Strategy analyst** | Compose competitive briefings; cite SEC filings and permits directly from the dashboard. |
| **Capacity planning** | Identify constrained regions (county-level) where buildout is/isn't matching announcements. |

---

## 4. Functional Requirements

### 4.1 Pillar 1 — Power & Geographic Expansion
- Extract power contracts (MW/GW) from SEC EDGAR 8-K/10-K, utility filings, and PPAs.
- Ingest Aterio datasets as primary structured data: sites table (`data_center_inventory_20260428.csv`, 73 cols), Events sheet (957 rows, 48 cols), and Energy Project Inventory (1695 rows, 65 cols).
- Normalize company → site → county → state → country.
- Side-by-side competitive view (stacked bar / heatmap) with time-series.
- County-level US permit feed (weekly cadence) as ground-truth check on announced vs under-construction.
- Satellite tab: site coordinates + change detection over time (Planet Labs / Maxar — vendor + cadence + cost to be evaluated).

### 4.2 Pillar 2 — GPU Supply Chain
- NVIDIA datacenter-segment revenue → unit estimates (quarterly).
- TSMC packaging/CoWoS capacity as upstream constraint.
- NIC shipments (Broadcom, Mellanox/NVIDIA networking) as cluster-deployment proxy.
- Optical transceiver shipments (Coherent, Lumentum, Innolight) as deployment validator.
- Inventory gap = shipped − (deployed via power-draw inference).

### 4.3 Cross-pillar — Triangulation Engine
| Layer | Signal | Source |
|---|---|---|
| L1 | Contracted power (GW) per company / geo | SEC, utility filings, PPAs |
| L2 | Estimated deployed GPUs × power-draw × utilization | NVIDIA filings + assumptions |
| L3 | NICs + optics shipped (validation) | Broadcom, Coherent, Lumentum filings |
| L4 | County permit data (ground truth) | Shovels.ai or equivalent |

Outputs: gap (power − compute demand), overbuild flag, underutilization flag — all explainable and source-linked.

### 4.4 Dashboard UX
- Multi-tab: **Power · Satellite · GPU Supply · NICs & Optics · TSMC · Permits · Triangulation · Sources · Energy Supply · Events Timeline · Companies**.
- **Companies tab + Company detail page** — directory and per-company drilldown showing role distribution (provider / end-user / financing / equipment / utility / permit-parent). Answers "what is OCI's owned vs end-user-only footprint?" and the inverse for any tracked company.
- **Site detail role-breakdown card** — companies grouped by role on each site (additive to the existing site detail view).
- **OCI %-share KPI tile** on every tab, **role-parameterized** (provider / end-user / any). A single number is meaningless because OCI plays multiple roles; per-tab default role documented in `docs/planning/03-architecture-design.md`.
- Every datapoint clickable → source.
- Time slider on each tab; cross-tab filter by company/geo.
- Loading + error states rendered (current `useApi` swallows errors).

### 4.5 Source Integrity & Lineage
- Every metric carries: source URL, retrieved-at timestamp, parser version, confidence score *backed by parsing certainty (not mocked)*.
- Versioned data lineage so re-runs are reproducible.

---

## 5. Phased Scope

### Phase 1 (4–6 weeks) — **National scope with honest coverage indicators**
**Geography: all 50 US states + DC.** Coverage varies by pillar — the UI must show a coverage badge on every tab so the user knows where data is dense vs sparse, never silently presents partial data as complete. **Source set: free APIs + Aterio one-time CSV only** — no paid vendors in MVP (Shovels.ai, FMP, Maxar, OpenCorporates Pro, Aterio licensed feed all deferred to Phase 2; see `docs/planning/00-DECISIONS-AND-CONSTRAINTS.md` §5.2 + §5.3 coverage-communication rule). Deliver:
- Seed from `data_center_inventory_20260428.csv` (Aterio, 73 cols, **one-time snapshot** for MVP — already national, ~10 K sites) as primary site data. Idempotent re-ingest design so a Phase-2 weekly/monthly Aterio feed drops in without rework.
- Power Map tab — **all US states**, 5 hyperscalers (MSFT/AWS/GCP/Meta/OCI) — sourced from Aterio CSV + live SEC EDGAR + EPA ECHO national baseline.
- Companies tab + Company detail page (role distribution per company, both aggregate and per-site).
- Site detail role-breakdown card.
- **Per-pillar coverage badges** so the UI is honest about partial data:
  - **Sites / Power capacity:** *all 50 states + DC* (Aterio canonical, national).
  - **SEC filings:** *all US public filers* (EDGAR is federal).
  - **Generator / air permits (federal):** *all 50 states baseline* (EPA ECHO + Envirofacts + CAMD).
  - **Building permits (state):** *VA + NY + WA + CO + OR + (TX air via TCEQ)* in MVP — other states render an explicit no-coverage state with the roadmap.
  - **Earnings transcripts:** *all tracked public companies* — best-effort IR-page scraping (FMP deferred); transcript availability varies.
  - **Satellite imagery:** *global* (Sentinel-2 via Earth Engine, 10 m, 5-day revisit).
  - **ISO/RTO interconnection queues:** *PJM only* in v1 — ERCOT/MISO/SPP/CAISO/NYISO/ISO-NE flagged as pending.
- Triangulation math validated offline before wiring into UI; surface error bars rather than single numbers (L2 GPU inference and L3 NIC/optics inference compound uncertainty). Triangulation accuracy degrades outside states with building-permit coverage — UI shows this explicitly.
- Earnings-transcript ingestion for NVIDIA + TSMC — best-effort using free IR-page scraping (FMP deferred). Quarterly cadence.
- Replace `random.*` mocks with either real data or explicit "no data" state.
- Source-link every chart in delivered tabs.
- A new **Coverage / Sources page** (additive, builds on the existing Sources tab) summarizing per-pillar per-state coverage with last-ingested timestamps and a "what's missing and why" roadmap.
- **AI agents** (5 in MVP, all on OCI Llama Stack — no API key, no cost) per `docs/planning/00-DECISIONS-AND-CONSTRAINTS.md` §4.2:
  - **EDGAR 8-K extractor** replaces brittle regex with structured LLM extraction (Phase 1).
  - **Permit-PDF vision extractor** for generator-permit narratives (Phase 1.5).
  - **LLC → Parent resolver agent** with tool-use over SEC Exhibit 21 / OpenCorporates / parcel deeds / ISO queues / web search (Phase 1.5; promoted from Phase-2 deferred).
  - **Triangulation Q&A agent** — conversational chat panel docked on the dashboard answering questions like "is there enough power for the GPUs being shipped in Texas?" with tool-use over the data layer (Phase 1).
  - **Weekly Brief agent** — Sunday-night scheduled job producing a 5–10 bullet Markdown briefing on what changed this week, surfaced as a dashboard card (Phase 1).

### Phase 1.5 (parallel track, weeks 1–12) — **Generator-permit pipeline**
Runs in parallel with the national MVP, doesn't block Phase 1 delivery. National air-permit baseline from EPA ECHO + state APIs (TCEQ, CA regional, NY/WA/CO Socrata) + standing public-records requests for VA/IA/AZ/OR. PDF parser (pdfplumber + Tesseract + Claude). Multi-signal LLC→parent resolver (SEC Exhibit 21 + OpenCorporates free + parcel deeds + ISO/RTO queues). Outputs feed the Permits (generator/air) tab and the `permit_parent` role on the Companies/Site views. See `docs/planning/03-PIPELINE-ARCHITECTURE.md` §7.5.

### Phase 2 — Scale pillars and license paid sources
- Aterio licensed feed (weekly/monthly cadence) — replaces one-time CSV.
- Shovels.ai national permit API — replaces VA-only fallback.
- Financial Modeling Prep transcripts — replaces best-effort IR scraping.
- OpenCorporates Pro for entity resolution at scale.
- NIC + optics ingestion (Coherent, Lumentum).
- Satellite imagery integration (Planet Labs trial; Maxar deferred to Phase 3).
- Expand building-permit coverage beyond the 6 free state APIs (VA/NY/WA/CO/OR/TX) — primarily via Shovels.ai, plus standing-records requests for IA/AZ/GA/LA/MS/TN/NE/OH/NC/SC/NV/NM (filed during Phase 1.5; deliveries arrive over Phase 2).

### Phase 3 — Intelligence layer
- Anomaly detection (week-over-week permit/filing deltas).
- Auto-generated weekly briefing pulled from same data layer.
- Optional global expansion (UK, Ireland, Singapore, Japan).

---

## 6. Data Sources (initial inventory)

| Source | Type | Status | Notes |
|---|---|---|---|
| SEC EDGAR | Filings (8-K/10-K) | Live (`agents/edgar_agent.py`) | Has silent `except`, blocking sync IO — must harden. |
| `data/curated_deals.py` | Hand-verified deals | Live | 22 deals; SEC URLs + lat/lon + MW + confidence. |
| Shovels.ai | County permits | **Procurement TBD** | Karan's named source; $599/mo; vendor approval status unknown. |
| Aterio | Datacenter dataset | **Primary** — CSV (8.2 MB, 73 cols) + Events (957 rows) + Energy Projects (1695 rows) | Canonical site seed + events + energy project inventory. |
| CleanView | Power/PPA tracking | Not evaluated | Karan-named. |
| datacentermap.com | Site inventory | Not evaluated | Karan-named. |
| SemiAnalysis | Industry research | Not evaluated | Karan-named; paywalled. |
| Planet Labs / Maxar | Satellite imagery | Not evaluated | Cost + cadence to assess. |
| NVIDIA / TSMC / Coherent / Lumentum | Earnings + 10-Q/10-K | Not built | Need transcript-parsing pipeline. |
| Financial Modeling Prep (FMP) | Financial data API | Not evaluated | $29–99/mo depending on tier. |

---

## 7. Success Metrics

- **Source coverage:** ≥95% of dashboard datapoints in delivered tabs link to primary source.
- **Real-data ratio:** Phase-1 ratio ≥80% real (vs current ~22%).
- **Geographic coverage (national MVP):**
  - Sites / Power: 50 states + DC ≥95% from Aterio.
  - Federal air-permit baseline (EPA ECHO): 50 states + DC.
  - Building permits: ≥6 states with structured API ingest (VA, NY, WA, CO, OR, plus TX air via TCEQ); remaining states render explicit no-coverage UI state.
- **Coverage honesty:** every tab displays a `<CoverageBadge />` summarizing where data is dense / sparse / missing — no silent partial coverage.
- **Freshness:** EDGAR ≤24 h after release; EPA ECHO ≤7 days; state APIs ≤7 days where available; earnings ≤72 h after call (best-effort given free transcript sources).
- **Triangulation explainability:** every gap number traceable to L1–L4 inputs in UI; triangulation degrades outside states with building-permit coverage and UI says so.
- **Karan acceptance:** he can answer his core power-vs-GPU question **at national, regional, and state level**, with explicit visibility into which states have full vs partial data.
- **OCI %-share visible on every category tab** as a role-parameterized KPI tile.

---

## 8. Resolved Decisions

All decisions below are codified in `docs/planning/00-DECISIONS-AND-CONSTRAINTS.md`.

1. **Postgres hosting:** Self-hosted on this OCI VM. No managed service.
2. **SEC EDGAR:** Leverage official `data.sec.gov` REST APIs (no auth, no key, free, JSON).
3. **OCI inclusion:** Include OCI in every pillar alongside MSFT/AWS/GCP/Meta. Every category view must surface % share for OCI.
4. **Deploy target:** This OCI compute instance. No Kubernetes, no managed deploy; run via systemd or `start.sh`.
5. **Auth:** No auth in v1. Skip login, sessions, RBAC. Internal-only, trusted-network.

---

## 9. Risks

- **Mock-data hangover:** seven of nine current tabs return `random.*` per request; users may already be drawing wrong conclusions. Mitigation: tag tabs as "preview / mock" until backed by real data.
- **EDGAR brittleness:** silent `except Exception` and blocking sync `urllib` inside FastAPI; 10 s+ cold-cache requests. Plan: migrate to official `data.sec.gov` REST endpoints + frames API (async httpx, 10 req/s rate limit, required User-Agent header). Mitigation: convert to async + structured logging in Phase 1.
- **Vendor lock-in:** premium sources (Shovels, SemiAnalysis, Maxar) gate the v1 thesis. Mitigation: design ingestion behind adapter interfaces; have one free fallback per pillar.
- **Inference assumptions:** L2 GPU-power-draw calc compounds uncertainty (revenue → units → kW). Mitigation: surface assumption sliders + show error bars, never a single number.
- **Security/ops debt:** CORS `*`, Google Maps key in `.env.local`, no `requirements.txt`. Mitigation: address before any external demo.

---

## 10. Out of Scope (v1)

- Internal Oracle financial / sales data.
- Customer-facing exposure of this dashboard.
- ML-based demand forecasting beyond explicit triangulation math.
- Automated trading / alerting on signals.

---

## Conformance to 00-DECISIONS-AND-CONSTRAINTS.md

- **S1 Decisions 1-5:** All resolved and reflected in Section 8 above (Postgres self-hosted, SEC EDGAR REST APIs, OCI inclusion in every pillar, deploy on OCI VM, no auth in v1).
- **S3 Datasets:** `data_center_inventory_20260428.csv`, Aterio expanded sample, Data Centers Data Dictionary, and Energy Project Inventory referenced in Sections 4.1, 5 (Phase 1), and 6.
- **S4 EDGAR APIs:** submissions, companyfacts, companyconcept, frames, nightly bulk ZIPs, EFTS full-text noted in Section 9 (risk mitigation) and Section 4.1.
- **S5 UX Rule:** Additive only acknowledged -- no visual changes to existing tabs, no deletions. New additions: OCI %-share KPI tile on every tab, Energy Supply tab, Events Timeline section (Section 4.4).
