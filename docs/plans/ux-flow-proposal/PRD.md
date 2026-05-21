# PRD — UX Flow Re-organized Around the 5-Layer AI Datacenter Model

Status: Draft for stakeholder review
Author: PM (strategic-insights-tool)
Date: 2026-05-19
Related framework: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/DataCenter Knowledge Layers/Framework - How to look at this industry.md`

---

## 1. Problem Statement

The strategic-insights-tool today is organized **by data source / pillar**, not by the analytical layer of the question the user is trying to answer. Today's top-level navigation (see `frontend/src/App.tsx` and `frontend/src/components/layout/TabNav.tsx`) is:

- Top tabs: `Data Centers Overview`, `AI Insights`, `Power Contracts`
- Supplier Insights dropdown: `GPU Supply`, `NICs & Optics Supply`, `Wafer Production (TSMC)`
- After-supplier tabs: `Country Permits`, `Companies`, `Triangulation (MOCK)`, `Data Sources`, `Earnings Calls`

The team has converged on a 5-layer mental model for the AI datacenter industry:

- **L1 — AI Demand**: application, model, inference, enterprise procurement
- **L2 — Computing Product**: token, API, GPU-hour, cloud service, reserved capacity, MW lease
- **L3 — Computing System**: chip, server, network, storage, software
- **L4 — Physical**: electricity, cooling, land, engineering, operations
- **L5 — Capital & Timeline**: capex, financing, depreciation, utilization, payback

When a PM, strategy lead, or exec asks a real OCI-vs-hyperscaler question, that question almost always pins to one layer (e.g., "Is AWS power-constrained in Northern Virginia?" is L4 / L5), but the UI forces the user to navigate by *data feed* (Aterio sites, EDGAR, Earnings, Press Releases). The friction shows up as:

1. **No single home for a layer-shaped question.** "Where does OCI sit on L4 power buildout vs. AWS?" requires hopping between `Data Centers Overview`, `Power Contracts`, `Country Permits`, and `Earnings Calls`, and then mentally joining them.
2. **L1 is essentially absent.** There is no view of AI demand (consumer vs. enterprise vs. model-lab, training vs. inference). The closest signal is earnings-mention sentiment in the `Earnings Calls` tab.
3. **L2 is missing entirely.** The tool tracks neither token pricing (OpenAI, Bedrock, Foundry, Vertex), GPU-hour pricing (CoreWeave, neoclouds, OCI), reserved-capacity contracts, nor MW-lease product structure. This is the layer where OCI's *commercial* differentiation lives, and it has zero UI surface.
4. **L3 is over-fragmented.** `GPU Supply`, `NICs & Optics Supply`, and `Wafer Production` each answer one slice of "what's in the rack." There is no consolidated chip → server → rack → cluster → network → storage view, even though the data exists.
5. **L4 is the strongest layer but is fragmented across three tabs** (`Data Centers Overview`, `Power Contracts`, `Country Permits`), with no cross-cut by hyperscaler, region, or time-to-power.
6. **L5 is partial and buried.** Site lifecycle dates, EDGAR capex, and earnings capex mentions exist (`backend/routers/edgar_frames.py`, `backend/routers/earnings.py`, `backend/routers/insights.py`), but there is no consolidated capex / depreciation / utilization / payback view per hyperscaler.
7. **Cross-layer triangulation is `MOCK`.** The `Triangulation` tab is the natural home for "L4 says X MW, L5 says $Y capex, L1 says demand Z — does it reconcile?" but it ships with placeholder data and is not wired to the same backend used by other tabs.

Net effect: the tool has **good raw coverage of L3 and L4, partial L5, and almost no L1/L2**, organized in a way that obscures the layer model rather than expressing it. This PRD proposes a re-organization of the UX so each layer is a first-class destination, and each cross-layer question has a defined surface.

---

## 2. Goals & Non-Goals

### Goals
- Re-organize the top-level UX around L1–L5 so any analytical question maps to a single primary tab.
- Make L1 and L2 first-class surfaces, even where data is initially thin, so the gaps are visible and prioritizable.
- Consolidate L3 (the current Supplier Insights dropdown plus parts of `Companies`) into a single "Computing System" surface.
- Preserve the strongest existing L4 surfaces (`Data Centers Overview`, `Power Contracts`, `Country Permits`) but expose them under an L4-shaped parent.
- Promote L5 from "buried in EDGAR/earnings" to a dedicated Capital & Timeline surface backed by `backend/routers/edgar_frames.py`, `backend/routers/earnings.py`, and the capex/lifecycle fields already on sites.
- Keep `AI Insights` (`backend/routers/insights.py`) as the **cross-layer narrative** surface — it should label every insight by the layer(s) it spans.
- Preserve all existing real-data routes; this is a UX re-org, not a data re-platforming.

### Non-Goals
- New data sources beyond what is already ingested or scheduled (Aterio, EDGAR, Alpha Vantage earnings, press releases, permits). New L1/L2 data ingestion is called out as future work.
- Backend schema migrations beyond surfacing existing fields. Layer tagging may require a thin `layer` field on insights but not on raw entities.
- Replacing the floating `ChatPanel` Q&A widget — it remains the cross-layer free-form entry point.
- Mobile / responsive redesign.
- A new auth model. This stays an OCI-internal tool.

---

## 3. Target Users & Top User Jobs

Primary users: OCI strategy PMs, competitive-intel analysts, and Cloud Infrastructure leadership (director-and-above).

### User stories (≥1 per layer, plus cross-layer)

1. **(L1) As a strategy PM**, I want to see whether hyperscaler AI demand is training-driven vs. inference-driven this quarter, so that I can tell our product team whether to prioritize OCI training clusters vs. inference SKUs.
2. **(L1) As a competitive-intel analyst**, I want to see enterprise AI adoption signals (mention counts, named-customer wins, model-lab GPU orders) from `backend/routers/earnings.py` and `backend/routers/press_releases.py`, so that I can quantify which segment of demand each hyperscaler is leaning into.
3. **(L2) As a strategy lead**, I want to compare OCI, AWS, Azure, GCP, and CoreWeave on token pricing, GPU-hour pricing, and reserved-capacity terms, so that I can answer "where is OCI commercially advantaged or disadvantaged?" in one screen.
4. **(L2) As an exec**, I want to see what fraction of each hyperscaler's revenue is sold as **MW lease / build-to-suit capacity** vs. **GPU-hour** vs. **managed model API**, so that I can interpret capex announcements in product-mix terms.
5. **(L3) As a competitive-intel analyst**, I want one Computing System surface that joins GPU supply (`backend/routers/gpu.py`), NICs & optics (`backend/routers/supply_chain.py`), and wafer production (TSMC), so that I can answer "what is the rack-scale bill of materials each hyperscaler is fielding this generation?" without three tab switches.
6. **(L4) As a PM**, I want to ask "where is OCI vs. AWS in L4 power buildout?" and get a side-by-side region map combining `backend/routers/sites.py`, `backend/routers/power.py`, and `backend/routers/permits.py`, so that I can answer the question in under 60 seconds.
7. **(L4) As a strategy lead**, I want to see permitted-but-not-energized MW by hyperscaler and country, so that I can identify where competitors will land capacity in the next 12–24 months.
8. **(L5) As an exec**, I want a per-hyperscaler Capital & Timeline view (capex from `backend/routers/edgar_frames.py`, capex commentary from `backend/routers/earnings.py`, site lifecycle dates from `backend/routers/sites.py`), so that I can answer "is Meta's 2026 $115–135B capex guide consistent with their announced MW pipeline?"
9. **(L5) As a strategy PM**, I want a depreciation / payback / utilization view per neocloud (CoreWeave, Nebius, IREN, Crusoe), so that I can size the risk to OCI from neocloud price competition.
10. **(Cross) As any user**, I want every AI Insight (`backend/routers/insights.py`) to be tagged with which layer(s) it spans, so that I can filter the feed by "show me only L4/L5 insights this week."

---

## 4. Success Metrics

### Quantitative
- **Time-to-answer for the canonical L4 question** ("Where is OCI vs. AWS in power buildout in Region X?"): median ≤ 60 seconds in moderated usability sessions, from app open to user-articulated answer. Baseline today (estimated): 4–6 minutes.
- **Tab-switches per analytical task**: median ≤ 2 across the 10 user stories above. Baseline today: 4–6.
- **Layer coverage of AI Insights**: ≥ 80% of insights emitted by the weekly cron carry a non-null `layer` tag within 30 days of layer-tagging shipping.
- **L1 and L2 surface usage**: ≥ 1 visit per active user per week within 60 days of launch (proves the layers are not dead UI).
- **AI Insights "Run again" / saved-session usage**: maintain or improve current rate (no regression from the re-org).

### Qualitative
- A user can describe the 5-layer model after 5 minutes in the app without prior briefing (tested with 3 non-team OCI PMs).
- Karan and the strategy stakeholders sign off that "the tab I'd open" matches "the layer my question is in" for ≥ 8 of 10 sampled real questions.
- Engineering reports that adding a new data feed maps cleanly to an existing layer surface rather than requiring a new top-level tab.

---

## 5. Functional Requirements

Requirements are grouped per layer plus a cross-cutting group. Each FR has acceptance criteria in §6.

### FR-L1 — AI Demand surface (new top-level tab: "L1 — AI Demand")
- **FR-L1.1** Show three demand-segment cards: Consumer AI, Enterprise AI, Model-Lab/Developer AI. Each card displays mention-count and sentiment-trend signals derived from `backend/routers/earnings.py` and `backend/routers/press_releases.py`.
- **FR-L1.2** Show a Training-vs-Inference split indicator per hyperscaler, sourced from earnings-transcript chunks already produced by `backend/ingestion/earnings_chunker.py`.
- **FR-L1.3** Show a "Named enterprise AI wins" table (customer, hyperscaler, quarter, source), populated from `press_releases` and earnings transcripts where the chunk classifier marks an enterprise-customer mention.
- **FR-L1.4** Mark fields with no real source as `MOCK` using the existing `BADGE` pattern in `TabNav.tsx`; do not invent data.

### FR-L2 — Computing Product surface (new top-level tab: "L2 — Computing Product")
- **FR-L2.1** Pricing comparator: OCI, AWS Bedrock, Azure AI Foundry, Google Vertex, CoreWeave — input token $/1M, output token $/1M, GPU-hour by SKU. Initial population may be manually curated and labeled `MOCK` per cell.
- **FR-L2.2** Capacity-product split per hyperscaler: % revenue / MW from (a) managed model API, (b) GPU-hour, (c) reserved capacity, (d) MW lease / BTS. Sourced from earnings commentary via `backend/routers/insights.py` until structured data exists.
- **FR-L2.3** Reserved-capacity / take-or-pay contract tracker: hyperscaler ↔ customer ↔ MW ↔ term ↔ source filing. Backed by EDGAR press releases already in `backend/data/cache/`.
- **FR-L2.4** A "Who bears utilization risk?" callout per contract (customer / hyperscaler / colo), informed by Layer 5 framework notes in `Layer 2 - Computing product.md`.

### FR-L3 — Computing System surface (replaces the Supplier Insights dropdown)
- **FR-L3.1** Single "L3 — Computing System" tab with internal sub-sections: Chip, Server/Rack, Network, Storage, Software. Each subsection consumes existing routes (`/api/gpu/*`, `/api/supply-chain/*`, `/api/tsmc/*` from `backend/routers/gpu.py` and `backend/routers/supply_chain.py`).
- **FR-L3.2** Per-hyperscaler rack BOM card (GPU model, NIC/DPU, switch fabric, optics generation), joining GPU supply and NICs/optics rows by hyperscaler.
- **FR-L3.3** TSMC wafer allocation view stays available but is framed as the upstream supply bottleneck for the L3 BOM, not a stand-alone pillar.
- **FR-L3.4** Cross-link from each rack-BOM card to relevant L4 site rows (e.g., "this BOM is deployed at <site>") via `backend/routers/sites.py`.

### FR-L4 — Physical surface (consolidates today's strongest tabs)
- **FR-L4.1** "L4 — Physical" parent with three sub-views, all real data today: **Sites & Map** (today's `Data Centers Overview`, `backend/routers/sites.py`), **Power Contracts** (`backend/routers/power.py`), **Permits** (`backend/routers/permits.py`).
- **FR-L4.2** Top-of-tab summary band: total announced MW, energized MW, under-construction MW, permitted-not-yet-energized MW, per hyperscaler, with a default filter set "OCI vs. AWS vs. Azure vs. GCP vs. Meta."
- **FR-L4.3** Region drilldown that shows the same MW band filtered to one country/state and pivots the map and contract table together.
- **FR-L4.4** Time-to-power overlay: median months from `permit_filed_date` → `energized_date` per hyperscaler, surfacing existing site-lifecycle dates.

### FR-L5 — Capital & Timeline surface (new top-level tab: "L5 — Capital & Timeline")
- **FR-L5.1** Per-hyperscaler capex card showing trailing 4-quarter capex from `backend/routers/edgar_frames.py`, FY guidance from earnings via `backend/routers/earnings.py`, and the most-recent capex-related insight from `backend/routers/insights.py`.
- **FR-L5.2** Depreciation-life view (e.g., Microsoft's 2–6 year useful-life disclosure) sourced from EDGAR filings already cached in `backend/data/cache/`.
- **FR-L5.3** Neocloud risk panel: CoreWeave, Nebius, IREN, Crusoe — capex, financing mix, customer concentration, contract term vs. depreciation term. Initial fields may be derived from cached 10-K JSON.
- **FR-L5.4** "Capex vs. MW pipeline" reconciliation chart per hyperscaler, joining L5 capex to L4 MW pipeline; flag when the implied $/MW falls outside an expected band.

### FR-Cross — Cross-layer & supporting surfaces
- **FR-Cross.1** `AI Insights` (`backend/routers/insights.py`) keeps its current behavior (weekly Mon 09:00 UTC cron, this-week-vs-prior-week deltas, saved / Run-again sessions) but **every emitted insight is tagged with one or more layer codes** (`L1`–`L5`). Tagging is produced during synthesis, persisted on the insight row, and rendered as a badge in `InsightCard`.
- **FR-Cross.2** `Companies` tab is repositioned as a cross-layer **entity directory**: each company row links to its L1/L2/L3/L4/L5 footprints (e.g., "Meta → L4 sites: 38; L5 capex FY26 guide: $115–135B; L3 rack BOM: GB200 NVL72; L1 demand segment: Consumer + Model-Lab; L2 product: managed model API + reserved capacity"). Backed by `backend/routers/companies.py`.
- **FR-Cross.3** `Triangulation` tab is either (a) promoted to a real surface that joins L4 MW × L5 capex × L1 demand into a single reconciliation table, or (b) removed. Until (a) ships, keep its `MOCK` badge.
- **FR-Cross.4** `Data Sources` (`backend/routers/sources.py`) stays but each source row is annotated with which layers it primarily feeds (e.g., Aterio → L4, EDGAR frames → L5, Alpha Vantage earnings → L1/L5, TSMC → L3).
- **FR-Cross.5** `Earnings Calls` (`backend/routers/earnings.py`) stays as a raw-transcript explorer; layer-level synthesis is the job of L1/L5 tabs and `AI Insights`.
- **FR-Cross.6** The floating `ChatPanel` Q&A widget remains the catch-all cross-layer free-form interface; no change required.

---

## 6. Acceptance Criteria

### FR-L1
- L1 tab loads in ≤ 1.5 s p50 against the staging dataset.
- All three demand-segment cards render with at least one real source citation (link to an earnings transcript chunk or press release row); cells with no source carry a `MOCK` badge.
- Training-vs-Inference indicator can be regenerated from the existing earnings-chunker output without a schema change.

### FR-L2
- Pricing comparator shows ≥ 5 hyperscaler/neocloud columns with non-null cells for OCI, AWS, Azure, GCP, CoreWeave.
- Each contract row in the reserved-capacity tracker links to an EDGAR or press-release source URL.
- "Who bears utilization risk?" callout is non-empty for ≥ 50% of contract rows.

### FR-L3
- The three legacy sub-tabs (`GPU Supply`, `NICs & Optics Supply`, `Wafer Production`) are reachable as sub-sections within one L3 tab. No data loss vs. today.
- Per-hyperscaler rack BOM card renders for at least Meta, Microsoft, Google, Amazon, Oracle.
- Each rack BOM card links to ≥ 1 L4 site row.

### FR-L4
- Summary band totals reconcile to the underlying `sites` table query within ±1 MW (rounding).
- "Time-to-power" overlay returns a numeric median for any hyperscaler with ≥ 3 energized sites.
- Region drilldown updates map and table in a single user action.
- Median time-to-answer for the canonical "OCI vs. AWS L4" question is ≤ 60 s in moderated usability test.

### FR-L5
- Capex card renders trailing 4-quarter capex for ≥ Microsoft, Meta, Alphabet, Amazon, Oracle, and CoreWeave.
- Depreciation-life view cites the source filing URL for each entry.
- "Capex vs. MW pipeline" flag fires when implied $/MW is outside a configurable band (default: $8M/MW–$25M/MW).

### FR-Cross
- ≥ 80% of insights emitted by the weekly cron within 30 days of launch carry a non-null layer tag.
- Companies directory links resolve to a non-empty section on each linked tab.
- Sources tab annotates every source row with at least one layer code.

---

## 7. Out of Scope / Future Work
- **New L1 data ingestion**: Stanford AI Index, McKinsey State of AI, IDC enterprise-AI surveys. Surfaced as a future workstream once the L1 tab is real estate.
- **New L2 data ingestion**: structured pricing scrapes for OpenAI / Bedrock / Foundry / Vertex / CoreWeave; structured reserved-capacity / MW-lease contract extraction. Today the FR-L2 surfaces ship with `MOCK`-flagged cells.
- **Model FLOPs Utilization (MFU) deep dive**: the file `Model FLOPs Utilization.md` exists in the Knowledge Layers folder but its surfacing is deferred until L1 and L2 stabilize.
- **Mobile / tablet layouts.**
- **Persisting per-user layer-filter preferences** (server-side). Local-storage-only acceptable for v1.
- **Auto-generated layer tagging on historical insights**: only forward-tag from launch; backfill is optional future work.
- **Re-platforming `Triangulation` from `MOCK` to real data** is scoped here as an "either-or" (FR-Cross.3); a separate PRD will be written if option (a) is chosen.

---

## 8. Open Questions

1. **Top-nav order**: should the canonical order be L1 → L2 → L3 → L4 → L5 (pedagogically clean) or L4 → L5 → L3 → L1 → L2 (data-coverage-strongest first)? Recommend L1→L5 for teach-ability; need Karan's call.
2. **Where does `AI Insights` live in the new nav?** Options: (a) keep as a top-level tab to the right of L5, (b) make it a right-hand rail across all layer tabs, (c) both. Recommend (a) for v1.
3. **Layer tagging vocabulary**: single dominant layer per insight, or multi-label set? Multi-label is more honest; single-label is easier to filter. Recommend multi-label with one "primary."
4. **Companies tab repositioning**: should the entity directory replace `Companies` outright, or live as a sub-section under each layer? Recommend the former.
5. **Do we sunset the `Triangulation` tab now, or keep `MOCK` for one more cycle** while option (a) of FR-Cross.3 is scoped?
6. **L2 pricing source policy**: is it acceptable to ship manually curated, dated pricing cells with explicit "as-of" labels until an automated scrape lands? Recommend yes.
7. **Naming**: do we use "L1 — AI Demand" literal labels, or business-friendly labels ("Demand", "Product", "System", "Physical", "Capital")? Recommend literal Lx labels in the nav with a tooltip on hover.
8. **Backward-compatible URLs**: do we keep `/tabs/datacenters`, `/tabs/power`, etc. as redirects to the new L4 sub-views? Recommend yes for 90 days.
9. **OCI-share / external-share surfaces**: `routers/oci_share.py` exposes per-tab share endpoints; the re-org must enumerate the new shareable surfaces. Track in a follow-up.
10. **Where does the `Earnings Calls` tab end and the L1/L5 synthesis tab begin?** Recommend: Earnings Calls stays a raw-transcript explorer; layer tabs own synthesis. Confirm with engineering that no duplication of charts is required.

---

## Appendix A — Current → Proposed mapping

| Today's tab | Proposed home | Notes |
|---|---|---|
| Data Centers Overview | L4 — Physical / Sites & Map | Unchanged backend (`routers/sites.py`) |
| AI Insights | Top-level (kept) | Adds layer tagging (FR-Cross.1) |
| Power Contracts | L4 — Physical / Power | Unchanged backend (`routers/power.py`) |
| GPU Supply | L3 — Computing System / Chip + Network | Unchanged backend (`routers/gpu.py`) |
| NICs & Optics Supply | L3 — Computing System / Network | Unchanged backend (`routers/supply_chain.py`) |
| Wafer Production (TSMC) | L3 — Computing System / Chip (upstream) | Unchanged backend |
| Country Permits | L4 — Physical / Permits | Unchanged backend (`routers/permits.py`) |
| Companies | Cross-layer entity directory | Repositioned, same backend (`routers/companies.py`) |
| Triangulation (MOCK) | Cross-layer reconciliation, OR removed | FR-Cross.3 decision |
| Data Sources | Stays; annotate each source with layer codes | `routers/sources.py` |
| Earnings Calls | Stays; raw transcript explorer only | `routers/earnings.py` |

---

End of PRD.
