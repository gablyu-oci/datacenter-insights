# UX Flow Proposal — Architecture & Information Architecture

**Author:** System Architect (strategic-insights-tool)
**Date:** 2026-05-19
**Status:** Draft for review
**Scope:** Re-map the current tab-based UI onto the 5-layer datacenter knowledge framework
(see `docs/DataCenter Knowledge Layers/`). No code changes proposed here — only IA, route
contracts, and a phased migration plan.

Layer numbering used throughout (per `Framework - How to look at this industry.md`):

- **L1 — AI Demand**: application, model, inference, enterprise procurement
- **L2 — Computing Product**: token, API, GPU-hour, cloud AI service, managed platform, MW lease
- **L3 — Computing System**: chip, server, rack, network, storage, software
- **L4 — Physical**: electricity, cooling, land, engineering, operations
- **L5 — Capital & Timeline**: capex, financing, depreciation, utilization, payback

---

## 1. Existing IA Audit

Current top-nav (from `frontend/src/components/layout/TabNav.tsx` and `App.tsx`):
Data Centers Overview, AI Insights, Power Contracts, Supplier Insights {GPU, NICs/Optics,
Wafer/TSMC}, Country Permits, Companies, Triangulation, Data Sources, Earnings Calls.

| Tab | Primary Layer | Secondary Layer | Backend routes consumed | Data coverage class |
|---|---|---|---|---|
| Data Centers Overview | **L4** (site, land, power) | L5 (project timeline) | `/api/sites`, `/api/satellite`, `/api/events`, `/api/energy-projects`, `/api/permits` | real |
| AI Insights | cross-cutting | L1–L5 (LLM synth) | `/api/insights/*`, `/api/agent_tools/*`, `/api/qa/ask` | real (synth) |
| Power Contracts | **L4** (electricity) | L5 (capex commit), L1 (demand signal) | `/api/power`, `/api/press-releases`, `/api/events` | real |
| Supplier — GPU Supply | **L3** (chip) | L5 (vendor capex / backlog) | `/api/gpu`, `/api/edgar`, `/api/companies` | partial (EDGAR-only; no shipment data) |
| Supplier — NICs & Optics | **L3** (network) | L5 (vendor backlog) | `/api/supply-chain`, legacy `/api/nics`, `/api/edgar` | partial (Samsung/SK-Hynix non-EDGAR) |
| Supplier — Wafer / TSMC | **L3** (chip/HBM/foundry) | L5 (capex) | `/api/supply-chain`, legacy `/api/tsmc`, `/api/edgar` | partial (non-US filers) |
| Country Permits | **L4** (generator permits, land) | L5 (timeline) | `/api/permits` | real (US county-level) |
| Companies | cross-cutting | L1–L5 (player directory) | `/api/companies`, `/api/companies/{id}/earnings`, `/api/oci-share` | real |
| Triangulation | cross-cutting | L4×L5 reconciliation | `/api/triangulation/l1`, `/api/triangulation/l2` | partial (L1 only; L2–L4 stubbed) |
| Data Sources | cross-cutting (provenance) | n/a | `/api/sources`, `/api/coverage`, `/api/health` | real |
| Earnings Calls | **L1** (mgmt narrative on demand) | L3+L5 (capex commentary) | `/api/earnings`, `/api/earnings/{id}`, `/api/companies/{id}/earnings` | real (Alpha Vantage) |

Observed bias: the existing IA is **L4-heavy** (3 of 11 tabs are pure L4) and **L1-thin**
(only Earnings Calls speaks to demand, and only indirectly). L2 (computing product / pricing)
is **completely unrepresented** in the tab structure.

---

## 2. Backend Surface Audit

| Router prefix | Primary layer served | What it exposes | Gap relative to that layer |
|---|---|---|---|
| `/api/sites` | L4 | Site inventory, milestone dates, role, capacity | No PUE/WUE, no kW/rack, no cooling type |
| `/api/satellite` | L4 | Geocoded sites for map clustering | No imagery delta / build-progress signal |
| `/api/events` | L4 | Lifecycle events: announce → construct → activate → cancel | No supply-chain or financing events |
| `/api/energy-projects` | L4 | Developer × customer × state energy projects | No interconnection-queue depth or grid-LMP |
| `/api/permits` | L4 | Building permits + generator permits | US-only; no transmission/substation permits |
| `/api/power` | L4 | Power capacity timeseries + curated power deals | No tariff/PPA price; no utility-load curve |
| `/api/press-releases` | L4/L5 | IR press releases (Microsoft etc.) | Sentiment & event-extraction stubbed |
| `/api/gpu` | L3 (chip) | EDGAR vendor_supply rows: revenue, inventory, backlog, customer concentration | No GPU-hour pricing (L2); no shipment count (L3 unit); no roadmap |
| `/api/supply-chain` (+ legacy `/api/nics`, `/api/tsmc`) | L3 (network, foundry) | Vendor revenue/backlog from EDGAR | No wafer-start count, no HBM3e availability, no optics ASP |
| `/api/edgar` (frames) | L5 | XBRL frames proxy w/ 12h TTL | Capex/depreciation parsed only via downstream extractor; no normalized capex/MW |
| `/api/companies` | cross-cutting (player directory) | Company aggregate, aliases, CIK, ticker | No "layer of operation" tag per company |
| `/api/oci-share` | L5 (OCI competitive lens) | Per-tab OCI share-of-wallet | Only computed for L4 inputs (power, sites, permits) |
| `/api/earnings` | L1+L5 | Transcripts, sentiment per axis, BM25 passages | No structured capex guidance extraction; no demand-quality score |
| `/api/anomalies` | L5 | ±2σ deviations in capex/revenue timeseries | Limited dimensions; no peer-relative |
| `/api/triangulation` | L4×L5 | Contracted-GW reconciliation L1 (L2–L4 stubbed) | L2–L4 require paid data; no cross-layer reconciliation today |
| `/api/insights` | cross-cutting | SSE agent sessions, persisted insights, chat | Agnostic to layer taxonomy — does not tag insights by L1–L5 |
| `/api/qa` | cross-cutting | One-shot SSE QA stream | Same — no layer routing |
| `/api/agent`, `/api/agent_tools` | infra | OpenClaw tool plumbing | n/a |
| `/api/brief` | cross-cutting | Weekly markdown brief | Layer coverage is implicit, not structured |
| `/api/sources`, `/api/coverage`, `/api/health` | infra/provenance | Ingestion runs, coverage rows, health | n/a |

**Top gap**: there is no router whose primary purpose is **L1 (demand)** or **L2 (product /
pricing)**. Earnings transcripts come closest to L1, but they are stored as text+sentiment,
not as structured demand signals.

---

## 3. Layer Coverage Matrix

| Layer | Covered today by | Missing data fields | Gap type |
|---|---|---|---|
| **L1 — AI Demand** | Earnings Calls (mgmt narrative), AI Insights (synth) | Token volume per provider, API call volume, enterprise seat counts, agent/multimodal share, workflow penetration, demand-quality score | **backend + frontend** (no router exists; no tab) |
| **L2 — Computing Product** | nothing | GPU-hour list price by vendor, on-demand vs reserved discount curves, provisioned-throughput rates, MW lease $/kW-month, model API token pricing, DGX Cloud subscription terms | **backend + frontend** (largest gap in the system) |
| **L3 — Computing System** | Supplier Insights × 3 (GPU, NICs/Optics, Wafer/TSMC) via `/api/gpu`, `/api/supply-chain` | GPU shipment counts, HBM3e allocation, NVL72 rack count, switch ASIC mix (Tomahawk/Jericho), optical-module ASP, scale-up vs scale-out fabric split | **backend** (data sources exist but unpurchased) + partial frontend |
| **L4 — Physical** | Data Centers Overview, Power Contracts, Country Permits, Triangulation | PUE/WUE, kW/rack density, cooling type (air/liquid/immersion), grid-queue position, interconnection LMP, water rights | **backend** (deepest layer in the product; field gaps are the bottleneck, not UI) |
| **L5 — Capital & Timeline** | Embedded in Power, Supplier Insights, Companies, Earnings; surfaced via `/api/oci-share`, `/api/anomalies`, `/api/edgar` | Normalized capex/MW, depreciation schedule, utilization rate, payback period model, take-or-pay backlog | **frontend** mostly — backend has the EDGAR scaffolding but there is no L5 tab that pulls it together |

---

## 4. Proposed Target IA — Two Options

### Option A — Pure Layered Top-Nav

Top navigation is exactly five sections (L1…L5) plus a small cross-cutting tray. Every
tab in the current product is reshaped into one of those five.

```
+---------------------------------------------------------------------------------+
| Strategic Insights Tool                                          [chat][user]   |
+---------------------------------------------------------------------------------+
| L1 Demand | L2 Product | L3 System | L4 Physical | L5 Capital  ||  ... tray ... |
+---------------------------------------------------------------------------------+
| Demand   | Pricing &  | Chips /   | Sites /     | Capex /      ||  Companies   |
| signals  | Capacity   | Network / | Power /     | Backlog /    ||  AI Insights |
| -------- | ---------- | Wafer     | Permits     | OCI Share    ||  Sources     |
| earnings | (NEW)      | (GPU,     | (DC Over-   | (NEW roll-   ||  Triangulate |
| sentiment| GPU-hour,  | NICs,     | view,       | up + earn-   ||              |
| token    | MW-lease,  | TSMC)     | Power,      | ings capex   ||              |
| growth   | API price) |           | Permits)    | guidance)    ||              |
+---------------------------------------------------------------------------------+
```

Reshape mapping:

- **L1 Demand** ← Earnings Calls (re-framed: extract structured demand signals, not just
  transcripts) + new tiles for token/seat trends.
- **L2 Product** ← NEW. Pricing observations (GPU-hour, MW lease, token API). Currently
  no tab; new section.
- **L3 System** ← Supplier Insights group: GPU, NICs/Optics, Wafer/TSMC become
  sub-views inside one L3 page.
- **L4 Physical** ← Data Centers Overview + Power Contracts + Country Permits merged into
  one L4 page with sub-tabs (Sites / Power / Permits).
- **L5 Capital** ← NEW landing that aggregates capex/depreciation from existing
  `/api/edgar`, `/api/oci-share`, `/api/anomalies`, plus earnings capex guidance.
- **Cross-cutting tray**: Companies (player directory cuts across all 5), AI Insights
  (synth across 5), Data Sources (provenance), Triangulation (cross-layer reconciliation).

Pros:
- Mirrors the intellectual framework Karan/team uses to think.
- Forces us to surface the L1/L2 gaps as visible blank sections rather than burying them.
- Easy story for new viewers ("we cover the whole stack").
- Companies, Insights, Sources, Triangulation stay where the user expects.

Cons:
- L4 becomes a dense, multi-sub-tab page; users coming for "sites" must learn one extra
  click.
- The L1 and L2 sections are visibly thin on day one — risk of looking unfinished.
- Loses the strong "Data Centers Overview = home" landing that drives current demos.

Migration cost: **medium**.
Risk to existing user mental models: **medium-high** (Data Centers Overview is the
current home page; demoting it into "L4 / Sites" requires user re-training).

### Option B — Hybrid Layer × Player

Top-nav is still Layer (L1…L5), but a persistent left rail filters by hyperscaler /
neocloud / supplier player. Every layer-page respects the active player filter.

```
+---------------------------------------------------------------------------------+
| Strategic Insights Tool                                          [chat][user]   |
+---------------------------------------------------------------------------------+
| L1 Demand | L2 Product | L3 System | L4 Physical | L5 Capital  ||  Tray        |
+-----------+---------------------------------------------------------------------+
| Filter:   |                                                                     |
| () All    |   <Layer page content respects the active player filter>            |
| () MSFT   |                                                                     |
| () AMZN   |   e.g. on L4 with MSFT selected: only Microsoft sites, only MSFT    |
| () GOOG   |   power contracts, only MSFT-linked permits. With "All" selected,   |
| () META   |   shows the portfolio view.                                         |
| () ORCL   |                                                                     |
| () CRWV   |                                                                     |
| () NBIS   |                                                                     |
| () ...    |                                                                     |
+-----------+---------------------------------------------------------------------+
```

Reshape mapping: same layer split as Option A, but every layer page reads the active
player from a global store and applies it as a query parameter to all layer endpoints.

Pros:
- Matches how analysts actually think: "What is Microsoft doing across L1–L5?"
- Makes the Companies tab partially redundant — the player filter is always visible.
- Strong story for OCI-vs-competitor narratives: select ORCL, walk left-to-right
  across layers, then re-select MSFT and compare.
- Natural place to surface `/api/oci-share` (it lives in the player rail header).

Cons:
- Requires every layer endpoint to accept a `company` / `cik` filter consistently
  (today, `/api/permits`, `/api/sites`, `/api/power` accept it but `/api/gpu`,
  `/api/supply-chain` use vendor groupings that don't map 1:1 to hyperscaler).
- Doubles the test-matrix per layer (player × layer).
- Left rail eats horizontal real-estate on the L4 map.

Migration cost: **high**.
Risk to existing user mental models: **medium** — adds a new persistent control rather
than changing what tabs exist.

### Reshape table (both options)

| Today's tab | Option A landing | Option B landing |
|---|---|---|
| Data Centers Overview | L4 / Sites | L4 / Sites (filtered) |
| AI Insights | Tray | Tray |
| Power Contracts | L4 / Power | L4 / Power (filtered) |
| GPU Supply | L3 / Chips | L3 / Chips (filtered) |
| NICs & Optics | L3 / Network | L3 / Network (filtered) |
| Wafer / TSMC | L3 / Foundry | L3 / Foundry (filtered) |
| Country Permits | L4 / Permits | L4 / Permits (filtered) |
| Companies | Tray | Replaced by player rail; details page lives in tray |
| Triangulation | Tray | Tray |
| Data Sources | Tray | Tray |
| Earnings Calls | L1 / Demand | L1 / Demand (filtered) |

---

## 5. Recommended Option: **Option A**

Rationale:

1. The biggest IA problem today is not "user can't filter by player" (the Companies tab
   already does that). It is "the product has no L1 and no L2 surface at all." Option A
   makes those gaps visible and fillable; Option B hides them behind a filter that the
   user has to discover.
2. Option B requires every layer router to accept a consistent player parameter. Our L3
   routers (`/api/gpu`, `/api/supply-chain`) group by vendor (NVIDIA, AMD, Broadcom),
   not by hyperscaler. Forcing them to also filter by customer requires data we have
   not yet acquired (shipment routing data). That is a P2 question, not a P0 question.
3. Option A maps cleanly to the Layer-numbered language already used in the playbook,
   the synthesis prompts, and the QA rules (`docs/DataCenter Knowledge Layers/*.md`).
   Engineering, prompt-writing, and product can share the same vocabulary.
4. We can adopt Option B's player rail later as a P2 enhancement on top of an
   already-layered IA. The reverse is harder.

Recommendation: ship Option A in P0/P1, and treat the player rail as a P2 add-on.

---

## 6. API Contracts to Add to Fully Serve the Layered IA

These are route names + JSON payload sketches only. No implementation, no SQL.

### L1 — AI Demand

```
GET /api/demand/signals?company=&period_start=&period_end=
  -> {
       items: [
         {
           company_canon: "Microsoft",
           period_end: "2026-06-30",
           signal_kind: "ai_revenue_run_rate" | "ai_capex_share" | "ai_seat_count" |
                        "token_volume" | "workflow_penetration_score",
           value: 13.0,
           unit: "USD_B" | "count" | "pct" | "tokens_per_day",
           source_ref: { router: "earnings", id: 5512 },
           confidence: 0.82
         }
       ],
       lineage: {...}, coverage: {...}
     }

GET /api/demand/quality-score?company=
  -> { company, score: 0..1, breakdown: { frequency, paid_intent, workflow_embed,
                                          complexity, sla, ... }, period_end }

GET /api/demand/types?company=
  -> { frontier_training_pct, inference_pct, enterprise_pct, agent_pct }
```

### L2 — Computing Product

```
GET /api/pricing/observations?provider=&unit=
  -> {
       items: [
         {
           provider: "OpenAI" | "AWS_Bedrock" | "Azure_Foundry" | "GCP_Vertex" |
                     "CoreWeave" | "OCI" | "Equinix" | ...,
           sku: "gpt-5.5-input" | "H100-on-demand" | "MW-lease-Loudoun",
           price: 5.0,
           unit: "USD_per_1M_tokens" | "USD_per_GPU_hour" |
                 "USD_per_kW_month" | "USD_per_MW_year",
           tier: "on_demand" | "reserved_1y" | "reserved_3y" | "batch" | "priority",
           observed_at: "2026-05-12",
           source_url: "...",
           confidence: 0.9
         }
       ]
     }

GET /api/pricing/curves?sku=
  -> timeseries of price observations for one SKU

GET /api/pricing/coverage
  -> { providers_covered: [...], gaps: [...] }
```

### L3 — Computing System

(Some of these augment the existing `/api/gpu` and `/api/supply-chain`, which today only
return EDGAR-derived revenue/backlog.)

```
GET /api/systems/shipments?vendor=&period_start=&period_end=
  -> per-vendor shipment count (GPU, NIC, switch ASIC) — backed by future paid data;
     return an explicit `coverage.gap_reason` when data is unavailable.

GET /api/systems/roadmap?vendor=
  -> next-gen part name, expected GA date, source (vendor IR, conference)

GET /api/systems/fabric-mix
  -> { scale_up: { NVLink_pct, UALink_pct, proprietary_pct },
       scale_out: { InfiniBand_pct, Ethernet_RoCE_pct, UEC_pct } }
```

### L4 — Physical

```
GET /api/physical/density?site_uid=
  -> { kW_per_rack, total_kW, rack_count, cooling_type }

GET /api/physical/pue?company=&site_uid=
  -> { PUE, WUE, period_end, source: "company_report"|"estimated" }

GET /api/physical/interconnection?state=&utility=
  -> { queue_position, queue_depth_MW, est_in_service_date }
```

### L5 — Capital & Timeline

```
GET /api/capital/capex?company=&period_start=&period_end=
  -> normalized capex by company / quarter; from existing EDGAR scaffolding

GET /api/capital/capex-per-mw?company=
  -> { capex_usd, mw_added, capex_per_mw }

GET /api/capital/utilization?company=
  -> { reported_utilization_pct, source, method }

GET /api/capital/payback?company=&site_uid=
  -> { payback_years, assumptions: {...} }

GET /api/capital/oci-share/rollup
  -> roll-up of existing per-tab /api/oci-share responses into one L5 dashboard tile
```

### Cross-cutting (no change, just retained)

`/api/insights/*`, `/api/qa/ask`, `/api/agent_tools/*`, `/api/companies/*`,
`/api/sources/*`, `/api/coverage/*`, `/api/triangulation/*`.

---

## 7. Data-Model Implications

New entities (table names indicative only — no DDL):

- **`demand_signals`** — one row per (company, period_end, signal_kind). Backs L1.
  Sourced from earnings extractor + AI Insights agents + manual annotation.
  Provenance: `source_router`, `source_row_id`, `confidence`.
- **`pricing_observations`** — one row per (provider, sku, observed_at, tier). Backs L2.
  Sourced from a new scraper layer (OpenAI/Anthropic/Azure/AWS/GCP/CoreWeave pricing
  pages + colo lease comps).
- **`pricing_skus`** — controlled vocabulary for SKUs so charts can group correctly
  (e.g., `H100-on-demand` vs `H100-reserved-1y`).
- **`system_shipments`** (gated) — vendor × period shipment count; until paid data is
  procured, table stays empty and `/api/systems/shipments` returns a coverage envelope
  with a `gap_reason`.
- **`physical_metrics`** — one row per (site_uid, period_end). Holds PUE, WUE,
  kW/rack, cooling_type, water_source. Backs L4 density endpoints.
- **`interconnection_queue`** — per-utility queue snapshots (state, utility,
  queue_depth_MW, snapshot_at). Backs L4 interconnection endpoint.
- **`capex_normalized`** — derived view over `edgar_extractions` keyed by
  (company_id, period_end), with `capex_usd`, `mw_added`, `capex_per_mw_usd`. Backs
  L5 capex endpoints.
- **`insight_layer_tags`** — many-to-many between `ai_insights.id` and a layer enum
  (L1…L5). Lets the AI Insights tray slice synth insights by layer so the L1/L2 pages
  can show "AI-generated commentary for this layer."

Existing tables that get a new column:

- **`companies`** gains `primary_layer` (enum L1…L5, nullable) so the player rail in
  Option B (future P2) can group by layer of operation.
- **`ai_insights`** gains an optional `layer` discriminator (L1…L5) so the synth agent
  can self-tag.

No tables are dropped. The `events`, `sites`, `generator_permits`, `power_*` tables
all stay where they are and just feed the new L4 page.

---

## 8. Migration Plan (P0 / P1 / P2)

### P0 — Repackage existing surfaces under L-numbered nav (no new data)

Goal: ship the new IA shell with **no backend changes**. Existing tabs simply move under
L-numbered sections. The empty L1/L2 sections show a clearly worded "coverage gap" panel.

Milestones:
- M0.1 Add `L1…L5` top-nav scaffold next to the current TabNav (feature-flagged).
- M0.2 Move Data Centers Overview, Power Contracts, Country Permits under **L4** as
  sub-tabs. Keep existing routes.
- M0.3 Move GPU, NICs/Optics, Wafer/TSMC under **L3** as sub-tabs.
- M0.4 Move Earnings Calls under **L1**, with an explicit "more demand signals coming"
  panel.
- M0.5 Add empty **L2** landing with a list of pricing SKUs we plan to track + "data
  not yet ingested" coverage envelope.
- M0.6 Add **L5** landing that aggregates existing `/api/oci-share`, `/api/anomalies`,
  `/api/edgar`-derived capex from the same EDGAR scaffolding already used by L3.
- M0.7 Keep Companies, AI Insights, Sources, Triangulation in the cross-cutting tray.
- M0.8 Retire the "Supplier Insights" dropdown — its three children move to L3.

Dependencies: none (UI-only).
Renamed: "Data Centers Overview" → "L4 / Sites". "Power Contracts" → "L4 / Power".
"Country Permits" → "L4 / Permits". "GPU Supply" → "L3 / Chips". "NICs & Optics" →
"L3 / Network". "Wafer / TSMC" → "L3 / Foundry". "Earnings Calls" → "L1 / Earnings".
Merged: nothing physically merged in P0; sub-tabs only.
Retired: the Supplier Insights dropdown wrapper (its children survive).

### P1 — Fill the L5 roll-up and start L2

Goal: make L5 a real page (not just a re-arrangement of L4 widgets) and stand up the
first real L2 dataset.

Milestones:
- M1.1 Build `capex_normalized` view and `/api/capital/capex` + `/capex-per-mw` +
  `/oci-share/rollup`.
- M1.2 Add `pricing_observations` + `pricing_skus` schema and a minimal scraper for
  3 providers (OpenAI token, CoreWeave GPU-hour, one colo MW-lease comp).
- M1.3 Build `/api/pricing/observations` + `/api/pricing/curves`.
- M1.4 First L2 page: GPU-hour curve (CoreWeave) + token API curve (OpenAI) +
  MW-lease comp (Loudoun/Phoenix/Dublin).
- M1.5 Tag existing AI Insights with their `layer` so each L-page can surface "synth
  commentary for this layer."
- M1.6 Move the in-process tools (`/api/agent_tools/*`) to also self-report which
  layer they served, so Triangulation can show cross-layer chains.

Dependencies: P0 nav shell shipped; scraper infra (which we already have for
press-releases).
Renamed: none new.
Merged: AI Insights tray rows gain a layer chip (L1/L2/L3/L4/L5).
Retired: none.

### P2 — Add demand signals (L1) and optional player rail (Option B)

Goal: turn L1 from "Earnings Calls passages" into a structured demand surface, and
optionally layer Option B's player filter on top of the layered nav.

Milestones:
- M2.1 Build `demand_signals` schema. Wire the earnings extractor to write structured
  signals (ai_revenue_run_rate, ai_capex_share, ai_seat_count) in addition to text.
- M2.2 Build `/api/demand/signals`, `/api/demand/types`, `/api/demand/quality-score`.
- M2.3 First L1 page: hyperscaler AI run-rate timeseries + capex-share + demand-type
  mix (frontier / inference / enterprise / agent).
- M2.4 (Optional) Add a persistent player rail on the left edge for **L1, L4, L5**
  only — these are the layers where the player filter is cheap. L3 stays vendor-
  grouped (it's a supplier view); L2 stays SKU-grouped (it's a product view).
- M2.5 Add `companies.primary_layer` and let Companies tray re-list by layer.
- M2.6 Add `system_shipments` table behind a feature flag — populates only after paid
  data source is procured.

Dependencies: P1 (so the layer tagging and pricing scaffolding already exist).
Renamed: "Earnings Calls" → "L1 / Demand" once the page is no longer transcript-first.
Merged: Companies stays in tray but may add a layer-grouped view.
Retired: the original flat top-nav is removed once P2 ships; `TabNav.tsx` is replaced by
the L-section nav as the sole entry point.

---

## 9. Non-Functional Requirements

### Performance budget (server response, p95)

| Surface | p95 budget | Reason |
|---|---|---|
| L1 landing (demand signals) | 500 ms | Mostly aggregations over `demand_signals` |
| L2 landing (pricing curves) | 600 ms | Joins pricing_observations × skus; small tables |
| L3 sub-tab (chips/network/foundry) | 800 ms | Existing EDGAR aggregations |
| L4 / Sites map (Data Centers Overview) | 1500 ms | Large geo payload; cluster on client |
| L4 / Power, L4 / Permits | 800 ms | Existing |
| L5 landing | 700 ms | Capex roll-up over EDGAR extracts |
| AI Insights SSE first byte | < 1500 ms | Already enforced (PRD §5.4) |
| AI Insights SSE complete | p50 ≤ 20 s, p95 ≤ 45 s | Already enforced |

Client TTI budget: layered nav must add **≤ 50 ms** of overhead vs the current TabNav.

### Freshness expectations per layer

| Layer | Freshness target | Why |
|---|---|---|
| L1 — Demand | quarterly + within 24 h of new earnings call | Bound by 10-Q cadence |
| L2 — Product (pricing) | weekly | Pricing pages change slowly; weekly diff is plenty |
| L3 — System | quarterly (EDGAR) | Bound by vendor filings |
| L4 — Physical | weekly (Aterio inventory + events delta) | Already weekly cron |
| L5 — Capital | quarterly (EDGAR) | Bound by 10-Q cadence |
| Cross-cutting AI Insights | weekly (Mon 09:00 UTC) | Per existing cadence (see MEMORY) |

### Citation & provenance requirements

Every value returned by every layer endpoint must carry the existing `LineageMeta`
envelope (`source_url`, `retrieved_at`, `parser_version`, `confidence`). New L1 and L2
endpoints must additionally include:

- `source_router` + `source_row_id` so the UI can deep-link back to the raw row
  (earnings passage, pricing snapshot, EDGAR extraction).
- `confidence` in `[0, 1]` — the AI Insights synth layer reads this to weight signals.
- For derived metrics (e.g., capex_per_mw, demand_quality_score), an `assumptions`
  block listing the input fields and any defaults.

The AI Insights tray must render a citation chip for every claim it makes that maps
back to an L1–L5 source row. Claims without a row-level citation must be marked
`unsourced` and downranked in the synth ordering (already enforced by
`synthesis_rules.md`).

### Coverage envelope discipline

Empty L1 and L2 sections during P0 must use the existing `CoverageEnvelope` pattern
(see `/api/triangulation/l1` for the canonical example): an empty `items` array, a
populated `coverage` block explaining the gap, and a populated `lineage` block. The
UI renders this as a "we don't have this data yet, here's why" panel — not a 404, not
a blank state.

### Security / auth (unchanged)

`/api/agent_tools/*` keeps its Bearer-token gate (`AGENT_TOOLS_BEARER`). All new L1/L2
endpoints are read-only and require no auth at the API layer (the React app is the
only consumer today). When/if we open the API beyond the internal team, the same
bearer pattern applies.

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| L1/L2 sections look empty on launch and undermine confidence | Use `CoverageEnvelope` with a clear roadmap message; P0 explicitly sets the expectation that empty = scoped, not = broken. |
| Renaming "Data Centers Overview" hurts daily users (it's the current home page) | Keep it as the default landing of L4, and route the bare `/` URL to `L4 / Sites` for P0–P1 to preserve muscle memory. |
| Pricing scrapers (L2) break when vendor pages restructure | Use the same scraper pattern as `ingestion/press_releases` (per-vendor adapter + golden fixture + alert on parse-failure rate). |
| The 5-layer model is itself a hypothesis | Keep the cross-cutting tray (Companies, AI Insights, Sources, Triangulation) so a user who rejects the layer model still has a usable product. |
| AI Insights synth produces a claim that crosses layers but cites only one | Add a `layer` array (not scalar) to `insight_layer_tags` so a single insight can be tagged L3+L4 (e.g., "GPU shipments will outpace power buildout"). |
| Option B is later judged "we want it now after all" | P2 is structured so the player rail can be bolted on without re-doing the layered nav. |

---

## Appendix A — Glossary alignment with playbook

The layer names in this document match the section headers in
`docs/DataCenter Knowledge Layers/Framework - How to look at this industry.md` and the
demand-quality + product-type tables in `Layer 1` and `Layer 2`. The AI Insights
playbook (`.openclaw/workspace/AI_INSIGHTS_PLAYBOOK.md`) and the QA global rules
(`backend/agents/insights/prompts/qa_global_rules.md`) should be updated in P1 (M1.5)
to use the same L1…L5 vocabulary verbatim, so prompts, UI, and engineering all share
the same taxonomy.

## Appendix B — What this doc deliberately does not decide

- Which specific pricing sources to scrape first in P1 (M1.2) — that is a P1 PRD
  question.
- Whether `demand_signals` should also accept manually-typed analyst entries in
  addition to extractor output — defer until P2 scoping.
- Whether the L4 sub-tabs become a single map with overlays or remain three pages —
  UX-only call, defer to design partner.
- How the chat panel (`ChatPanel.tsx`) reshapes — assumed unchanged; it floats on top
  of every layer page.
