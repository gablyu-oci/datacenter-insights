# UX Gaps & Flow Proposal — Strategic Insights Tool

**Status:** Planning document (no code changes)
**Date:** 2026-05-19
**Authors:** pm → researcher → architect → designer (orchestrated)
**Framework reference:** `docs/DataCenter Knowledge Layers/` (Framework + L1–L5 + Model FLOPs Utilization)
**Source planning artifacts (read these for full detail):**
- `docs/plans/ux-flow-proposal/PRD.md`
- `docs/plans/ux-flow-proposal/RESEARCH.md`
- `docs/plans/ux-flow-proposal/ARCHITECTURE.md`
- `docs/plans/ux-flow-proposal/UX_FLOW.md`

---

## 0. Executive Summary

The Strategic Insights Tool is a FastAPI + React prototype that today exposes ~11 top-level tabs of competitive intelligence on hyperscaler datacenter and power buildout vs. OCI. The underlying knowledge model — captured in the six framework documents under `docs/DataCenter Knowledge Layers/` — is a **5-layer pipeline**: AI Demand (L1) → Computing Product (L2) → Computing System (L3) → Physical Infrastructure (L4) → Capital & Timeline (L5), with **Model FLOPs Utilization (MFU)** as the cross-cutting "efficiency" multiplier connecting demand to delivered tokens.

The current UI does **not** make this layered model visible to users. Navigation is organized around *data feeds we happen to have* (Aterio, EDGAR, NVIDIA earnings, curated power deals) rather than around the *strategic question being answered*. The result is:

- **L4 (Physical) is over-served** (3 of the top 6 tabs).
- **L3 (Computing System) is moderately served** but hidden behind a "Supplier Insights" dropdown.
- **L1 (AI Demand) is reduced to earnings-call sentiment** and lacks a dedicated landing page.
- **L2 (Computing Product) is effectively absent** — there is no pricing, no $/GPU-hour, no $/MW-lease, no product-tier comparison.
- **L5 (Capital & Timeline) is fragmented** across EDGAR frames, Aterio lifecycle dates, and Earnings, with no time-to-power or depreciation-cycle view.
- **MFU is not surfaced anywhere** in the UI, despite being the framework's central efficiency lever.

This document proposes a **hybrid Layer × Player information architecture** (recommended Option B from `ARCHITECTURE.md`) that makes the 5-layer framework the spine of the product, with two new top-level concepts ("Layer Explorer" and "Player Profile"), three new pages (L1 Demand Signals, L2 Pricing Compare, L5 Time-to-Power), a persistent AI Insights right-drawer, and a coverage/provenance UX that is honest about the ~78% mock data ratio.

The recommendation is sequenced into P0 / P1 / P2 bands so a single engineer can ship the P0 reframe in 2–3 weeks without breaking existing routes.

---

## 1. Summary of the 5-Layer Framework and Implications for OCI vs Hyperscaler CI UI

### 1.1 The framework in one paragraph

The framework models the AI compute economy as a **vertical stack of supply-demand markets** where the output of each layer becomes the input of the next:

| Layer | What it is | Core unit | Lead time |
|---|---|---|---|
| **L1 — AI Demand** | Tokens, model training runs, inference workloads, foundation-model roadmaps, enterprise/agent demand | tokens/day, training-FLOPs, model count | weeks–months |
| **L2 — Computing Product** | Productised compute: GPU-hours, dedicated clusters, MW-lease, colocation, AI cloud SKUs, sovereign offerings | $/GPU-hour, $/MW-month, contract TCV | 1–4 quarters |
| **L3 — Computing System** | Silicon + interconnect + memory + cooling: GPUs (NVIDIA/AMD/custom), NICs/optics, HBM, networking, foundry capacity (TSMC/Intel/GF), packaging (Amkor/ASE/ASML) | wafer-starts, GPU shipments, optics ports, HBM stacks | 2–6 quarters |
| **L4 — Physical Infrastructure** | Land, buildings, power contracts, substations, transformers, water, fiber, permits | MW contracted, MW energized, m² white-space, permit count | 18–60 months |
| **L5 — Capital & Timeline** | Capex flow, depreciation cycle, financing structures, time-to-power, project schedules | $B capex, depreciation years, months-to-energize | 1–10 years |

**Model FLOPs Utilization (MFU)** sits orthogonal to all five layers: it is the efficiency factor that determines how much of L3's theoretical FLOPs actually convert into L1's tokens. A 30% → 50% MFU improvement is equivalent to 67% more L3 capacity without buying a single additional GPU.

### 1.2 Why this matters for an OCI-vs-hyperscaler CI tool

A competitive intelligence platform that ignores the layered structure will systematically mislead the user because **the constraint that decides who wins is rarely at the layer the user is looking at**:

1. **Bottlenecks migrate.** In 2023 the binding constraint was L3 (H100 allocation). In 2024 it was L4 (power, substations, transformer lead-times). In 2025 it has been L5 (project finance and time-to-power). A CI tool that only shows L4 (as the current UI mostly does) cannot explain why a competitor is winning deals on L2 pricing despite OCI having more L4 MW under contract.
2. **OCI's narrative requires cross-layer evidence.** "We are differentiated on time-to-power" is an L5 claim that must be substantiated with L4 (permits, lease lifecycle), L3 (GPU availability), and L2 (SKU GA dates). Today the user has to manually stitch this across 5+ tabs.
3. **Hyperscaler disclosure is layer-asymmetric.** Microsoft, Meta, and Google disclose L5 capex in 10-Qs, hint at L1 demand on earnings calls, are silent on L2 pricing, and leak L4 via permits and Aterio. A good UI separates "what they say" (L1, L5) from "what they do" (L3, L4) and prices the gap.
4. **MFU is the asymmetric lever.** OCI's strongest narrative against Azure/AWS/GCP may be efficiency per delivered token, not raw MW. MFU has to be a first-class metric in the UI, not a footnote.

### 1.3 Implications for the UI (design principles)

These five principles flow from the framework and are referenced throughout the rest of this document:

- **P1. Layer is a first-class navigation axis.** Users should always know which layer they are in and be able to drill across layers without losing context.
- **P2. Player (OCI vs MSFT/META/GOOG/AMZN/ORCL/CRWV…) is the second axis.** Every layer view supports a Player filter; every Player profile supports a Layer breakdown.
- **P3. Provenance and freshness are always visible.** With ~78% of values currently mock or stale, every chart must show source + as-of date + coverage %.
- **P4. MFU is surfaced wherever L1 and L3 meet.** Tokens-per-MW and tokens-per-dollar are headline metrics, not derived footnotes.
- **P5. AI Insights is contextual, not a tab.** Insights belong next to the data they explain (right-drawer), with a weekly digest as the only "destination" view.

---

## 2. Audit of Current UI Mapped to the 5 Layers

### 2.1 Current navigation (top-down read)

Source: `frontend/src/components/layout/TabNav.tsx`, `frontend/src/App.tsx` (`TAB_CONFIG`).

```
[Header: "Datacenter & Power Intelligence — OCI Strategic Platform"]
TOP_TABS:
  • Data Centers Overview        ← default tab
  • AI Insights
  • Power Contracts
SUPPLIER_TABS (dropdown "Supplier Insights"):
  • GPU
  • NICs/Optics
  • TSMC
AFTER_SUPPLIER:
  • Permits
  • Companies
  • Triangulation [MOCK]
  • Data Sources
  • Earnings
```

### 2.2 Tab-by-tab layer mapping

| Current tab | Primary file | Layer(s) it serves | Coverage quality |
|---|---|---|---|
| Data Centers Overview | `frontend/src/components/tabs/DataCentersTab.tsx` | **L4** (sites, MW, lifecycle) | Real (Aterio) — strong |
| Power Contracts | `frontend/src/components/tabs/PowerTab.tsx` | **L4** (buyer/seller/energy_source/MW) | Curated — strong but small N |
| Permits | `frontend/src/components/tabs/PermitsTab.tsx` | **L4** (construction permits) | Partial — strong where covered |
| GPU | `frontend/src/components/tabs/GPUSupplyTab.tsx` | **L3** (NVIDIA/AMD/Intel revenue) | Real (vendor financials) — strong |
| NICs/Optics | `frontend/src/components/tabs/NICsOpticsTab.tsx` | **L3** (network silicon) | Mock-heavy |
| TSMC | `frontend/src/components/tabs/TSMCTab.tsx` | **L3** (foundry + packaging: TSMC, Intel-Foundry, GF, Amkor, ASE, ASML) | Real — strong |
| Earnings | `frontend/src/components/tabs/EarningsTab.tsx` | **L1** (ai_demand/power_constraints/datacenter_capex/overall sentiment) + **L5** (capex mentions) | Real (NLP on transcripts) — moderate |
| Triangulation | `frontend/src/components/tabs/TriangulationTab.tsx` | **Cross-cutting** (L1 contracted-power GW × company×state, L2 compute demand vs power) | Marked **[MOCK]** |
| Companies | `frontend/src/components/tabs/CompaniesTab.tsx` | **Cross-cutting** (player directory) | Partial |
| Data Sources | `frontend/src/components/tabs/SourcesTab.tsx` | **Meta** (provenance directory) | Real — strong |
| AI Insights | `frontend/src/components/tabs/AIInsightsTab.tsx` | **Cross-cutting** (narrative generation) | Real (Llama Stack weekly cron) — strong |

### 2.3 Coverage matrix (current state)

```
                  | Dedicated  | Real data | Mock-free | First-class |
Layer             | landing?   | available?| in UI?    | in nav?     | Verdict
------------------+------------+-----------+-----------+-------------+-------------
L1 AI Demand      |     No     | Partial   | Partial   |     No      | WEAK
L2 Comp. Product  |     No     |    No     |    No     |     No      | MISSING
L3 Comp. System   | Yes (×3)   |   Yes     |  Mostly   |  Dropdown   | MODERATE
L4 Physical       | Yes (×3)   |   Yes     |   Yes     |     Yes     | STRONG
L5 Capital/Time   |     No     | Partial   | Partial   |     No      | WEAK
MFU (cross)       |     No     |    No     |    No     |     No      | MISSING
```

### 2.4 Backend surface vs UI surface

The FastAPI backend (`backend/app/routers/`) exposes considerably more than the UI surfaces. Routers enumerated: `brief`, `gpu`, `agent`, `anomalies`, `energy_projects`, `satellite`, `supply_chain`, `press_releases`, `oci_share`, `edgar_frames`, `coverage`, `health`, `qa`, `triangulation`, `permits`, `power`, `agent_tools`, `earnings`, `companies`, `sources`, `insights`, `sites`, `events`.

Notable **backend capabilities not exposed in the UI**:
- `anomalies` — change-detection signal that should drive an "Alerts" surface.
- `oci_share` — OCI vs. competitor share calc; should be the headline metric on a "Player Profile: OCI" page.
- `edgar_frames` — capex/PP&E XBRL frames; should power an L5 view.
- `satellite` + `energy_projects` — L4 enrichment not shown.
- `brief` — pre-built executive brief; not linked from the homepage.
- `coverage` — explicit coverage % endpoint; not surfaced in any chart's "source" badge.

This is a substantive UI debt: at least 6 production backend endpoints have no UI consumers.

---

## 3. Specific Gaps and Confusing Flows (with File References)

### 3.1 Navigation order does not match the framework

`frontend/src/components/layout/TabNav.tsx` orders the top-level tabs as:

```
L4 → cross (AI Insights) → L4 → [dropdown: L3, L3, L3] → L4 → cross → cross(MOCK) → meta → L1+L5
```

A user reading left-to-right learns nothing about the layered model. The two layers most relevant to OCI's strategic narrative (L1 demand and L5 capital/timeline) are dead last. There is no L2 surface at all.

**Files involved:**
- `frontend/src/components/layout/TabNav.tsx` (TAB_CONFIG, TOP_TABS, SUPPLIER_TABS, AFTER_SUPPLIER constants)
- `frontend/src/App.tsx` (`TAB_CONFIG`, default tab `"datacenters"`)

### 3.2 "Data Centers Overview" is the default landing — wrong layer to start in

Default tab is `datacenters` (`App.tsx`). For a CI tool whose value proposition is *strategic* (where is the bottleneck moving, which competitor is winning what), the right default is an **executive landing page** that summarises L1 → L5 movement over the past week. The `brief` router in the backend already produces this content; it is not wired into the UI.

**Files involved:**
- `frontend/src/App.tsx` (initial tab state)
- `backend/app/routers/brief.py` (unused executive brief endpoint)

### 3.3 "Supplier Insights" hides L3 behind a dropdown

GPU, NICs/Optics, and TSMC are three **distinct sub-layers of L3** (compute silicon, network silicon, foundry+packaging) buried under a single dropdown labeled "Supplier Insights." A user looking for "what's happening with HBM supply" or "is the optics bottleneck easing" has no obvious entry point.

**Files involved:** `frontend/src/components/layout/TabNav.tsx` (`SUPPLIER_TABS`).

### 3.4 Triangulation is labelled `[MOCK]` but is the *only* cross-layer view

`TriangulationTab.tsx` is the single tab today that explicitly tries to combine L1 (compute demand) with L4 (contracted power) — i.e., it answers the framework's central question. But it is marked `[MOCK]` and parked after Companies, signalling to the user that the cross-layer story is the *least* trustworthy part of the product, exactly inverting the desired hierarchy.

**Files involved:** `frontend/src/components/tabs/TriangulationTab.tsx`, `backend/app/routers/triangulation.py`.

### 3.5 L1 is reduced to earnings-call sentiment

Today the only L1 surface is `EarningsTab.tsx`, which scores transcripts on four sentiment axes. There is no:
- Token-demand projection
- Frontier model release timeline (GPT-5, Claude 4.x, Gemini 3, Llama 5, Grok-4, DeepSeek-Vx)
- Foundation-lab capex commitment view (OpenAI/Anthropic/xAI/Mistral)
- Enterprise + agent demand proxy (API call volume, inference share)

The framework's L1 (`docs/DataCenter Knowledge Layers/Layer 1 - AI Demand.md`) covers all of these; the UI covers ~10% of it.

### 3.6 L2 (Computing Product) has no UI at all

No tab today shows:
- $/GPU-hour by vendor & SKU (CoreWeave vs Azure vs OCI vs Lambda vs Crusoe)
- $/MW-month colocation rates (QTS, Digital Realty, Equinix, Iron Mountain, Aligned, Compass, EdgeConneX, Stack)
- AI cloud SKU GA timelines (B200 availability, GB200 NVL72, H200, MI300X, Trainium2)
- Sovereign/regional offerings (G42, Lambda Sovereign, OCI Dedicated Region)

This is the layer where pricing pressure actually shows up. Its absence makes the product *quietly biased* toward an infrastructure-only narrative.

### 3.7 L5 is fragmented and incomplete

L5 signals are scattered across three tabs:
- Lifecycle dates in Aterio sites (`DataCentersTab`)
- Capex mentions in `EarningsTab`
- EDGAR XBRL capex frames — *via backend `edgar_frames` router that has no UI consumer*

There is no consolidated **time-to-power** view, no **months-from-announce-to-energize** chart, no **depreciation-cycle** comparison (the framework explicitly calls out that hyperscalers have extended GPU depreciation from 4 → 5 → 6 years, materially affecting reported margins).

### 3.8 Model FLOPs Utilization is invisible

`docs/DataCenter Knowledge Layers/Model FLOPs Utilization.md` defines MFU as the cross-cutting efficiency multiplier. No UI surface today references MFU, tokens/MW, tokens/$, or any efficiency metric. This is the single largest framework-to-UI gap.

### 3.9 Provenance and freshness UX is inconsistent

Charts in `DataCentersTab`, `PowerTab`, `TSMCTab`, etc., do not consistently display:
- Underlying source name (Aterio / EDGAR / NVIDIA 10-Q / curated)
- As-of date
- Coverage % (e.g., "covers 73% of declared Tier-1 hyperscaler MW")
- Mock vs real flag

`backend/app/routers/coverage.py` exists but is not consumed by any chart wrapper.

### 3.10 AI Insights is a destination tab instead of a contextual drawer

`AIInsightsTab.tsx` requires the user to leave whatever data they were looking at and read insights divorced from the underlying charts. The weekly cron + SSE streaming infrastructure (recorded in user memory) is well-built, but the surfacing is wrong: insights should appear **adjacent to** the L1/L3/L4 chart they reference, with deep-links back.

### 3.11 No "Player Profile" entry point

`CompaniesTab.tsx` is a flat directory, not a profile. A user who wants "show me Meta across L1–L5" has to manually filter five different tabs. The framework is inherently a 2-D matrix (Layer × Player); the UI exposes only the Layer axis (and poorly).

### 3.12 Health/Status of backend is not visible

`Header.tsx` polls `/api/health` but does not show coverage, freshness, or cron-job last-run status. A CI tool's credibility hinges on knowing when data was last refreshed.

---

## 4. Proposed New Information Architecture / User Flow

### 4.1 Recommendation: Hybrid Layer × Player (Option B from ARCHITECTURE.md)

After comparing two options in the architecture doc — (A) Pure-layered nav vs (B) Layer × Player matrix — we recommend **Option B**. Rationale:

- Aligns 1:1 with the framework, making the model legible.
- Matches how peer platforms (SemiAnalysis Core, DC Byte, Synergy, Dell'Oro) organise their content (see `RESEARCH.md` §3).
- Lets the same data drive two views (Layer-first for analysts, Player-first for execs) without duplicating routes.
- Backwards-compatible: every current tab maps to a layer node, so existing URLs can be 301-redirected.

### 4.2 New top-level navigation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  STRATEGIC INSIGHTS — Datacenter & Power Competitive Intelligence           │
│                                                                             │
│  [⌘K Command bar: "Jump to layer / player / metric"]    [Coverage: 73% ▾]  │
├─────────────────────────────────────────────────────────────────────────────┤
│  EXECUTIVE  │  LAYERS ▾   │  PLAYERS ▾   │  ALERTS  │  INSIGHTS  │  DATA   │
│  BRIEF      │             │              │          │            │         │
└─────────────────────────────────────────────────────────────────────────────┘
                  │             │
                  ▼             ▼
     ┌──────────────────┐  ┌──────────────────────┐
     │ L1 AI Demand     │  │ OCI                  │
     │ L2 Pricing       │  │ Microsoft / Azure    │
     │ L3 Systems  ▸    │  │ Meta                 │
     │   – GPU          │  │ Google / GCP         │
     │   – NICs/Optics  │  │ Amazon / AWS         │
     │   – Foundry      │  │ Oracle (parent)      │
     │ L4 Physical ▸    │  │ CoreWeave            │
     │   – Sites        │  │ xAI                  │
     │   – Power deals  │  │ Anthropic / OpenAI   │
     │   – Permits      │  │ Sovereign (G42…)     │
     │ L5 Capital&Time  │  │ Custom watchlist…    │
     │ ── MFU & Effncy  │  └──────────────────────┘
     └──────────────────┘
```

Persistent right-edge: **AI Insights drawer** (collapsible), context-aware to whatever Layer/Player view is open.

### 4.3 The "layer ladder" — a persistent visual spine

Every page in the product carries a 5-step ladder in the page header showing the user where they are and offering one-click drill-down:

```
L1 Demand → L2 Product → L3 System → L4 Physical → L5 Capital   |   ✕ MFU
   ▲                       (you are here)
```

Clicking any rung re-applies the current Player/timeframe filter at the new layer. This is the single mechanism that makes the framework legible to non-expert users.

### 4.4 Three canonical user journeys

1. **Executive Monday-morning (10 min):** Brief → top 3 anomalies → drill into one → AI Insights drawer → forward to stakeholder.
2. **Analyst deep-dive (45 min):** Layer Explorer → L3 GPU → filter Player=MSFT → cross-link to L4 Power Deals (same player) → cross-link to L5 Capex frame → export.
3. **Strategy review (workshop):** Player Profile: OCI → side-by-side with Player Profile: MSFT → toggle each layer → MFU comparison → snapshot to PDF.

Full journey scripts with screen states are in `UX_FLOW.md` §3.

### 4.5 Provenance & coverage UX (cross-cutting)

Every chart card carries a standard footer:

```
┌─────────────────────────────────────────────────────────┐
│  <chart>                                                │
│                                                         │
│  Source: Aterio  •  As-of: 2026-05-12  •  Coverage: 73% │
│  [● Real] [○ Mock]   ▸ View methodology                 │
└─────────────────────────────────────────────────────────┘
```

Wired to `backend/app/routers/coverage.py`. Mock data is never hidden — it is labelled and explained.

### 4.6 AI Insights as a drawer, not a tab

The existing `/insights` infra (Llama Stack weekly cron, embeddings via `persist_insight`, 4-week recent-headlines dedup — see user memory) is retained but the surfacing changes:

- **Right-edge drawer** opens on any page; the active Layer/Player filters scope the insight feed.
- **Insight card** links into the exact chart that generated the signal.
- **Weekly digest** remains as a dedicated email-style "Insights" route for archival reading.

### 4.7 URL & route migration (no breakage)

Mapping is in `ARCHITECTURE.md` §6. Examples:

```
/?tab=datacenters    → /layers/l4/sites
/?tab=power          → /layers/l4/power
/?tab=gpu            → /layers/l3/gpu
/?tab=tsmc           → /layers/l3/foundry
/?tab=earnings       → /layers/l1/sentiment
/?tab=triangulation  → /layers/cross/triangulation
/?tab=ai_insights    → /insights (digest)  + drawer everywhere
```

All old query-string URLs 301-redirect.

---

## 5. Page-by-Page Recommendations (P0 / P1 / P2)

Priority bands:
- **P0** — ship in the next 2–3 week increment; blockers to the layered narrative.
- **P1** — ship in the following 4–6 weeks; high-leverage but not blocking.
- **P2** — backlog; nice-to-have or speculative.

### 5.1 P0 — Reframe the spine (ship first)

| # | Page / change | What | Why | Files (no-edit; reference only) |
|---|---|---|---|---|
| P0-1 | **Executive Brief landing page** | Replace `datacenters` default with a Brief landing that summarises L1→L5 weekly delta + top 3 anomalies + 1 OCI-vs-hyperscaler call-out. Powered by existing `backend/app/routers/brief.py` + `anomalies.py`. | Current default starts at L4 — wrong layer to anchor a strategic story. | `frontend/src/App.tsx`, `backend/app/routers/brief.py`, `backend/app/routers/anomalies.py` |
| P0-2 | **Top-nav restructure: Layers / Players / Insights / Data** | Replace TOP_TABS + SUPPLIER_TABS + AFTER_SUPPLIER with 5-item top nav. Existing tabs become children. URLs 301 to new paths. | The framework's first principle (layered model) must be the first thing the user sees. | `frontend/src/components/layout/TabNav.tsx`, `App.tsx` |
| P0-3 | **Layer Ladder header component** | Persistent 5-step ladder on every page; click any rung to drill across layers with filters preserved. | Single mechanism that teaches the model. | (new) `frontend/src/components/layout/LayerLadder.tsx` |
| P0-4 | **AI Insights right-drawer** | Move `AIInsightsTab` content into a context-aware drawer; keep a `/insights` digest route. Drawer is scoped by the active Layer/Player. | Insights must sit next to the data they explain. | `frontend/src/components/tabs/AIInsightsTab.tsx`, new `InsightsDrawer.tsx` |
| P0-5 | **Provenance footer on every chart card** | Standard footer: source, as-of date, coverage %, Real/Mock badge. Wire to `coverage` router. | Honesty about ~78% mock ratio is non-negotiable. | All `frontend/src/components/tabs/*Tab.tsx`, `backend/app/routers/coverage.py` |
| P0-6 | **Promote Triangulation off `[MOCK]` label or remove from top-level** | Either backfill with real data or move to "Lab" section until real. | Today the only cross-layer view is signposted as the least trustworthy. | `frontend/src/components/tabs/TriangulationTab.tsx` |
| P0-7 | **Header status: last cron run + coverage %** | Header shows AI Insights cron last-run (Mon 09:00 UTC), data-feed freshness, overall coverage. | Trust signal; existing `health` + `coverage` endpoints. | `frontend/src/components/layout/Header.tsx` |

**P0 outcome:** the layered model is visible everywhere; provenance is honest; the default landing answers "what should I care about this week?".

### 5.2 P1 — Fill the layer gaps

| # | Page / change | What | Why | New backend? |
|---|---|---|---|---|
| P1-1 | **NEW: L1 Demand Signals page** | Frontier model release tracker, foundation-lab capex commitments, token-volume proxies, enterprise/agent demand indicators. | L1 today is just earnings sentiment — under-served. | Yes — new `routers/demand.py` (can start with curated CSV) |
| P1-2 | **NEW: L2 Pricing Compare page** | $/GPU-hour by vendor & SKU, $/MW-month colocation rates, AI cloud SKU GA timelines, sovereign offerings. | L2 is entirely missing. Pricing is where competitive pressure actually shows up. | Yes — new `routers/pricing.py` |
| P1-3 | **NEW: L5 Time-to-Power page** | Months-from-announce-to-energize, depreciation-cycle comparison (4/5/6 years), EDGAR capex frames consolidation, project schedule slip. | L5 is fragmented across three tabs and EDGAR data is unused. | Wire existing `edgar_frames` + Aterio lifecycle |
| P1-4 | **MFU & Efficiency cross-cut view** | Tokens-per-MW, tokens-per-$, MFU benchmarks by model family, hyperscaler MFU estimates (where disclosable). | Framework's central efficiency lever, currently invisible. | Yes — new `routers/efficiency.py` (curated benchmarks) |
| P1-5 | **Player Profile pages** (OCI first, then MSFT/META/GOOG/AMZN) | Single page per player showing all 5 layers + MFU; powered by `oci_share` router for OCI's headline metric. | Second axis of the matrix; how execs actually think. | Reuses existing routers; new aggregation endpoint |
| P1-6 | **Surface `anomalies` router as "Alerts" tab** | List of detected step-changes in any layer; click-through to the chart that triggered it. | High-leverage existing backend with zero UI today. | None — wire existing router |
| P1-7 | **L3 sub-layer split** | Replace "Supplier Insights" dropdown with three top-level L3 children: Compute Silicon, Network Silicon, Foundry & Packaging. | The current dropdown obscures that these are different sub-layers. | None — pure FE re-org |
| P1-8 | **Command bar (⌘K)** | Fuzzy jump to any Layer / Player / metric. Bloomberg-style. | Power-user efficiency; analyst journey needs it. | None — FE only |
| P1-9 | **Methodology / Data Sources expansion** | `SourcesTab.tsx` becomes a full transparency page: per-feed cadence, last-refresh, coverage, mock-vs-real status. | Trust + auditability. | Extend `sources` router |

### 5.3 P2 — Differentiation & polish

| # | Page / change | What | Why |
|---|---|---|---|
| P2-1 | Satellite + energy-projects map enrichment | Wire unused `satellite` and `energy_projects` routers into the L4 Sites view. | Free differentiation; data is already there. |
| P2-2 | Press-release & supply-chain ticker | Surface `press_releases` + `supply_chain` routers as a live feed on the Brief. | Adds "now" tempo to the executive view. |
| P2-3 | Snapshot/export to PDF for strategy reviews | One-click "snapshot this view" for offline review. | Workshop journey #3 requires this. |
| P2-4 | Player watchlist + diff alerts | User-defined set of players with daily delta email. | Stickiness. |
| P2-5 | OCI narrative builder | Pre-baked OCI-vs-hyperscaler comparison slides with current data injected. | Sales/strategy enablement. |
| P2-6 | MFU sensitivity model | "If OCI MFU is 5pp higher than Azure, what's the implied $/token differential?" | Quantifies the central framework lever. |
| P2-7 | QA + agent-tools surface | Expose `qa` and `agent_tools` routers as a guided Q&A interface. | Optional Llama Stack value-add. |

### 5.4 Suggested sequencing

```
Week 1–2 (P0):  P0-1, P0-2, P0-3, P0-7
Week 2–3 (P0):  P0-4, P0-5, P0-6
Week 3–6 (P1):  P1-6 (alerts), P1-7 (L3 split), P1-3 (L5 time-to-power)
Week 6–10 (P1): P1-1 (L1), P1-2 (L2), P1-4 (MFU), P1-5 (Profiles), P1-8 (⌘K), P1-9 (sources)
Week 10+ (P2): selective based on user feedback
```

### 5.5 Acceptance criteria (lifted from PRD)

The P0 block is "done" when:
- Default landing answers "what changed this week across L1–L5?" in ≤15s of read time.
- A first-time user can name the 5 layers after one session.
- Every chart shows source + as-of + coverage.
- AI Insights drawer is reachable from any page and is scoped to the current view.
- No existing URL 404s; all redirect to the new layer-based routes.

Full AC list is in `PRD.md` §7.

---

## 6. Risks & Open Questions

Carried forward from `PRD.md` §8 and `ARCHITECTURE.md` §9:

1. **L2 pricing data sourcing.** $/GPU-hour and $/MW-month are not freely available; we will need to curate (research bills) or partner.
2. **MFU estimates for competitors.** Hyperscalers do not disclose MFU; we will need a defensible estimation methodology before publishing the metric.
3. **Coverage % calculation.** The current `coverage` router returns per-feed coverage; rolling that up to a single global % needs a documented method.
4. **OCI proprietary data.** Some Player Profile fields (OCI's own capex, MFU, time-to-power) may be sensitive; need a clear "what is shareable" line.
5. **Llama Stack quota.** Moving Insights to a context-aware drawer may multiply call volume; quota and caching strategy needed.
6. **Aterio licensing.** Re-exposing Aterio data in new views is fine; redistributing in exports may not be — clarify with vendor.

---

## 7. Where to Read More

- **PRD (product requirements, user stories, AC):** `docs/plans/ux-flow-proposal/PRD.md`
- **Research (peer-platform IA, viz patterns, ~25 external refs):** `docs/plans/ux-flow-proposal/RESEARCH.md`
- **Architecture (IA options A vs B, API contracts, route migration, NFRs):** `docs/plans/ux-flow-proposal/ARCHITECTURE.md`
- **UX Flow (personas, journeys, ASCII wireframes, page-by-page):** `docs/plans/ux-flow-proposal/UX_FLOW.md`
- **Framework primary sources:** `docs/DataCenter Knowledge Layers/` (Framework + L1–L5 + MFU)

---

*End of UX Gaps & Flow Proposal — no code modified; this is a planning document only.*
