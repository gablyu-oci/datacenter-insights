# Karan Requirements Audit — strategic-insights-tool

_Audit date: 2026-04-30. Scope: live implementation at `/home/ubuntu/oci-ai-incubations/strategic-insights-tool` checked against the verbatim Karan brief. Evidence cited inline (file:line + endpoint payloads) — read-only audit, no code modified._

---

## 1. Executive Summary

Karan's brief contains **~30 discrete asks** across three pillars (Power, GPU Supply, Triangulation) plus dashboard UX and ingestion next-steps. Tally of current status:

- **PASS:** 8 (hyperscaler GW side-by-side; NVIDIA EDGAR; NIC/optics EDGAR; Companies/site click-through; Sources tab; clickable EDGAR/source URLs; Aterio site map; weekly brief).
- **PARTIAL:** 11 (most prominently: triangulation is L1-only, satellite tab is a coordinate map not imagery, permits are *generator* permits not *building* permits, TSMC vendor registered but extractor returned 0 rows).
- **FAIL:** 6 (no Satellite tab in TabNav; no construction-change-detection; no county-level US building-permit feed; no NVIDIA *unit shipments* in DB; no inventory-gap calc; datacenter.com/datacentermap.com/SemiAnalysis not ingested).
- **DEFERRED-PAID:** 5 (Planet Labs, Maxar, Shovels.ai, Aterio licensed feed, FMP transcripts — all explicitly out of free-data scope per `00-DECISIONS-AND-CONSTRAINTS.md` §5.2).

**Biggest gap:** Karan's Triangulation L2 (`shipped GPUs × power × utilization`) and L4 (county building permits) are both unbuilt — and they're the bullets that *make* the tool feel like intelligence vs. a competitive scoreboard. Today the dashboard shows L1 (contracted GW) only.

**Easiest win:** Promote the existing `/api/triangulation/l1` arithmetic into a "Power vs. Compute Gap" headline by wiring an in-house L2 estimate using NVIDIA Data Center revenue we already extract (NVIDIA 10-K period_end 2025-04-27 returns `revenue_usd 215.9 B` — `/api/gpu/supply`). That's a 1-day backend job and gives Karan a number he can defend.

---

## 2. Requirement-by-Requirement Table

| # | Requirement (one-line) | Status | Evidence (file:line or endpoint) | Gap |
|---|---|---|---|---|
| **§1 Power Contracting & Geographic Expansion** | | | | |
| 1.1 | Who is contracting power, how much, where (public-filings source-of-truth) | PASS | `/api/power/announcements` returns curated 8-K/10-K deals incl. Amazon `35B OpenAI` (2026-02-27) + 200 M MWh (~1.43 GW continuous-eq) clean-energy disclosure with `source_url` to SEC | Curated, not auto-extracted — a human still authors `curated_deals` rows |
| 1.2 | Side-by-side GW view: MSFT vs AWS vs GCP vs Meta vs others | PASS | `/api/power/gw-summary`: Amazon 17.9 / Google 12.75 / Oracle 11.6 / Microsoft 10.47 / Meta 7.0 / Constellation 16.0 / Talen 2.57 / Vistra 2.3 | Oracle is in the comparison (per Karan's "OCI sits relative to hyperscalers") — good |
| 1.3 | Dashboard tab with satellite imagery tied to permits | FAIL | `frontend/src/App.tsx:5-26` — TAB_CONFIG has 9 tabs, **none labeled "Satellite"**; `TabNav.tsx:7-23` confirms. `/api/satellite/sites` exists but only returns site lat/lon, not imagery | No imagery layer rendered. DataCenters tab has a Leaflet map (`DataCentersTab.tsx:14-22`) with Google Maps tile but no Sentinel-2 / time-series overlay |
| 1.4 | US county-level building-permit weekly feed (construction-start signal) | FAIL | `/api/permits/datacenter` total=667. **All rows are *generator* permits** (PJM interconnection, EPA ECHO, TCEQ, NY DEC) — `routers/permits.py:25` `DATACENTER_FUEL_TYPES = {diesel, natural_gas, dual_fuel}`. Coverage row: `building_permits` = 10 rows across 51 states | County building-permit ingestion is what Karan named (Shovels.ai equivalent). Not built. PRD §5 lists VA/NY/WA/CO/OR as MVP states |
| 1.5 | Reference: datacenter.com / datacentermap.com | FAIL | No ingestion source named `datacenter*`. `/api/sources/` lists: aterio_csv, edgar v1+v2, epa_echo v1.0+v1.1+v1.2, ir_press_releases, ny_dec, permits_state, pjm_iso, tceq, va_open_data | Not scraped. Both are commercial sites with TOS that should be reviewed before automated pull |
| 1.6 | "Power is the binding constraint" framing | PASS | `TriangulationTab.tsx:45-50` literally codifies this: `L1 Contracted Power` is "live", `L2 GPU Compute Demand`/`L3 NIC/Optics`/`L4 Permits` shown as `blocked` (paid-data) | Honest scope banner is there |
| 1.7 | Where OCI sits vs. hyperscalers | PARTIAL | `/api/{tab}/oci-share` endpoint exists (`routers/oci_share.py:1-220`). Oracle in `gw-summary` at 11.6 GW. Companies tab includes Oracle | Not surfaced as a hero KPI tile across every tab — PRD §4.4 specified one but only `oci-share` endpoint is wired, no per-tab tile component found |
| **§2 GPU Supply Chain** | | | | |
| 2.1 | Total GPUs shipped (NVIDIA, public filings) | PARTIAL | `/api/gpu/supply` `revenue_estimates`: 4+ NVIDIA 10-K/10-Q filings, `revenue_usd 215.9 B` FY26, `inventory_usd 21.4 B`, `purchase_commitments_usd 95.2 B`, `customer_concentration_pct 78`. EDGAR_url present. `agents/edgar_agent.py:154` NVIDIA cik 0001045810 | We extract **revenue + inventory $**, not **unit counts**. Karan asked for "Total GPUs shipped" — H100/B200 unit derivation not done. `data.shipped = []`, `data.deployed = []` |
| 2.2 | GPUs "in the wild" — shipped but not deployed (inventory gap) | FAIL | `/api/gpu/supply` `data.inventory = []`, `data.deployed = []` | Conceptual gap. Even the schema fields are empty. Need: NVIDIA inventory $ → unit estimate, then subtract power-implied deployment |
| 2.3 | NICs shipped as cluster-deployment proxy | PARTIAL | `/api/nics` returns Broadcom 10-Q/10-K extractions (revenue, inventory, customer concentration). Vendor registry in `edgar_agent.py:199-245`: Broadcom + Marvell + Credo + Astera Labs + Fabrinet | Same revenue-not-units issue. No unit conversion or "NIC shipments per quarter" derived metric |
| 2.4 | Optical transceivers shipped | PARTIAL | Same `/api/nics` payload covers `optics_shipments` slot. Coherent (cik 0001140536→corrected) and Lumentum registered (`edgar_agent.py:211-225`) | Filings extracted; deployment-signal derivation not built |
| 2.5 | TSMC manufacturing + packaging capacity (upstream constraint) | PARTIAL | TSMC vendor registered (`edgar_agent.py:247`), 20-F/6-K form types declared, TWD→USD FX wiring in `gpu.py:50-56`. **BUT** `/api/tsmc` returns: `capacity=[], packaging=[], disclosures=[], tsmc_filings_audited=0` | Extractor not yet executed against TSMC. Big tab, zero data. Same issue for ASML, ASE, Amkor, GlobalFoundries — registered but not extracted |
| 2.6 | NVIDIA Data Center segment revenue (quarterly base) | PASS | `/api/gpu/supply` returns segment_name="Data Center" with quarterly period_end (2025-07-27, 2025-10-26, 2026-01-25). `agents/vendor_supply_extractor.py` (514 LOC) parses the segment table | Working as Karan asked |
| 2.7 | "Shipping ≠ deployment. The gap is the signal." | FAIL | The frame is in the PRD but no `inventory_gap` or `deployment_inferred` field is computed in any endpoint | Need a derived metric. Math is in the team's heads; not in code |
| 2.8 | Sources: datacentermap.com, SemiAnalysis | FAIL | Neither in `/api/sources/` ledger | DEFERRED on cost / TOS grounds is fine, but should be marked explicitly in Sources tab as "out of scope" |
| **§3 Triangulation** | | | | |
| 3.1 | Cross-reference power vs. GPU shipments | PARTIAL | `/api/triangulation/l1` returns 30+ company×state rows (Amazon VA 18.3 GW, Constellation 144.35 GW, Alphabet 12.75 GW, etc.) merging `sites + deals + edgar` | This is L1 only, single-axis (GW). Cross-axis (GW vs. inferred GPU compute demand) not computed |
| 3.2 | L1 — Contracted power (GW) by company from filings + utility deals | PASS | `agents/triangulation.py:1-266` `compute_l1()` aggregates `sites.power_capacity_mw + curated_deals.capacity_mw + edgar_extractions.capacity_mw`, dedup by canonicalized buyer × state. `routers/triangulation.py:62-88` returns it with `confidence` and `sources` provenance | Working. Microsoft missing from L1 output (probably no MW-tagged sites attribution under that canonical name) — worth a follow-up query |
| 3.3 | L2 — Estimated deployed GPUs (shipment × power-draw × utilization) | FAIL | `routers/triangulation.py:71-75`: `layers_pending: ["L2", "L3", "L4"]`. `TriangulationTab.tsx:47` `status: blocked` | Not built. Math is documented in PRD §4.3 but no code path |
| 3.4 | L3 — NICs/optics shipped as deployment validation | FAIL | Same: `layers_pending` includes L3 | Vendor data present (`/api/nics`); cross-layer correlation logic unbuilt |
| 3.5 | L4 — County permits as ground truth on construction vs. announcement | FAIL | `coverage` table: `building_permits` total record_count=10 across 51 states. `routers/permits.py` only serves *generator* permits | Karan's most-cited near-term item. Not built |
| **§4 Dashboard UX** | | | | |
| 4.1 | Multi-tab layout: Power, Satellite, GPU Supply, NICs & Optics, TSMC, Permits, Triangulation, Sources | PARTIAL | `App.tsx:5-26` ships 9 tabs: Datacenters, Power, GPU, NICs, TSMC, Permits, Triangulation, Companies, Sources. **Satellite tab missing**, Companies tab added (PRD-driven extension) | One Karan-requested tab (Satellite) absent; one Karan-not-requested tab (Companies) added |
| 4.2 | Every data point clickable through to primary source | PASS | 34 `target="_blank"` source-link instances across `frontend/src/components/tabs/*.tsx`. PowerTab has 14 alone. EDGAR URLs threaded through every vendor row (`gpu.py:67`, `supply_chain.py:84`) | Solid. Permit rows expose `source_url` (`routers/permits.py:39-43`) |
| 4.3 | Satellite imagery + construction change detection over time | FAIL | No tab. `/api/satellite/sites` returns sites with lat/lon only (`routers/satellite.py:37-52`). `Site.latest_satellite_picture_date` field exists in model but never populated/rendered. PRD §4.1 names Sentinel-2 via Earth Engine — only seeded in `coverage` table (`seed/coverage_seed.py:208`), no actual ingestion | No tile fetch, no time-slider, no diff view |
| 4.4 | "Intelligence tool, not weekly digest" — drilldown capability | PARTIAL | DataCentersTab (1108 LOC) has site-detail drilldown (`SiteDetail.tsx`); Companies tab has per-company role breakdown. Floating ChatPanel (`App.tsx:14`) provides Q&A. Weekly brief is rendered as one *card* on Triangulation, not as the home page — good | Drilldown is rich on sites/companies, weak on power deals (no deal-detail panel) and absent on GPU/NIC/TSMC rows |
| **Next Steps (Karan's list)** | | | | |
| NS1 | Power ingestion: SEC EDGAR, Shovels.ai, Aterio, CleanView | PARTIAL | EDGAR ✅ (`agents/edgar_agent.py` 958 LOC, run_count=5, stored=15). Aterio ✅ (one-time CSV, stored=40722). Shovels.ai ❌ (paid). CleanView ❌ | 2 of 4 done; 2 deferred-paid |
| NS2 | GPU ingestion: NVIDIA / TSMC / Coherent / Lumentum earnings | PARTIAL | NVIDIA ✅ (revenue_estimates populated). Coherent ✅ (cik 0001140536→corrected). Lumentum ✅ (registered). TSMC registered but `tsmc_filings_audited=0` | TSMC the gap; run extractor against 20-F |
| NS3 | Evaluate Planet Labs / Maxar | DEFERRED-PAID | No code path. PRD names Sentinel-2 (free) instead | Sentinel-2 evaluation also not started |
| NS4 | Dashboard wireframe: 8-tab layout | PARTIAL | 9 tabs shipped, Satellite missing | See 4.1 |
| NS5 | Triangulation model: shipped GPUs × power × utilization vs. GW | FAIL | Not implemented | See 3.3 |
| NS6 | County permit pipeline (US, datacenter-permit-type filtered) | FAIL | `coverage.building_permits` = 10 rows | See 1.4 |
| NS7 | Evaluate datacenter.com / datacentermap.com / SemiAnalysis | FAIL | No code, no docs reference | Decision-point pending |
| **Near-Term (Karan's list)** | | | | |
| NT1 | Prototype Power Map tab with MSFT/AWS/GCP + county permit overlay | PARTIAL | Power Map: yes (PowerTab 944 LOC). Permit overlay on map: no — permits are a separate tab, not overlaid on the geographic map | Geographic overlay is the differentiator Karan asked for |
| NT2 | Triangulation model — validate math before wiring | PARTIAL | L1 math live and validated against deal sums. L2 math drafted in PRD but not validated | |
| NT3 | Earnings-transcript parsing for NVIDIA, TSMC, four hyperscalers | PARTIAL | Filings (10-K/10-Q) parsed, *not* transcripts. Hyperscalers Alphabet/Amazon/Microsoft `form_types=()` (`edgar_agent.py:177-196`) — flagged "press-only" | Transcript-source decision still open (FMP deferred per PRD §5 Phase 2) |

---

## 3. Pillar Deep-Dives

### 3a. Pillar 1 — Power Contracting & Geographic Expansion

**What's implemented**

- **Aterio site canonical**: `Site` table = 6973 rows (`/api/sites/?page_size=1` → `total: 6973`), 73 cols, national + Canada (sample row Wetaskiwin, AB). Ingest ledger: `aterio_csv v1.0.0 stored=40722` total records.
- **Power capacity per provider**: `/api/power/capacity` aggregates `sum(power_capacity_mw)` by `provider_name` (`routers/power.py:55-92`). 51-state coverage per `coverage` table (`power_sites` pillar, 6611 rows).
- **GW summary**: `/api/power/gw-summary` returns the side-by-side competitive view Karan asked for in §1.2: Amazon 17.9 GW, Constellation 16.0 GW, Google 12.75 GW, Oracle 11.6 GW, Microsoft 10.47 GW, Meta 7.0 GW, Talen 2.57 GW, Vistra 2.3 GW.
- **Curated 8-K deals**: `/api/power/announcements.curated` includes Amazon's $35 B OpenAI investment (2026-02-27, 8-K), Amazon's 200 M MWh / ~1.43 GW continuous-equivalent disclosure (FY25 10-K; 200 TWh ÷ 16 yr ÷ 8,760 hr), all with `source_url → sec.gov/Archives/edgar/...`.
- **EDGAR pipeline**: `agents/edgar_agent.py` (958 LOC), `agents/edgar_extractor.py` (532 LOC), `agents/parent_resolver.py` (982 LOC for LLC→parent resolution). `edgar v2.0.0` pipeline `stored=15, run_count=5`.
- **Generator permits**: `/api/permits/datacenter` total=667 (PJM AJ-series, EPA ECHO, NY DEC, TCEQ, VA Open Data). Coverage `generator_permits` = 500 rows × 58 states.

**What's partial**

- Coverage badges exist (PRD §4.4) but uneven UX. `routers/coverage.py:1-92` returns 280 pillar×state rows; some tabs render the badge, some don't.
- OCI %-share endpoint built (`routers/oci_share.py` 220 LOC) but not visibly tiled on every tab as PRD §4.4 specified.
- Hyperscaler form_types tuple is empty for Alphabet/Amazon/Microsoft (`edgar_agent.py:177-196`) — these are press-only entries; their 8-Ks come in via the *power-deal* path (`edgar_agent.py:54-69`). Means we *do* get Microsoft 8-K power deals, but not Microsoft 10-Q segment splits.

**What's missing**

- **County-level US building permits** (Karan's marquee §1.4 ask) — `coverage.building_permits = 10 rows`. This is the difference between "we list permits" and "we have ground truth on construction starts".
- **Satellite tile/imagery layer** — covered in §4 below.
- **Aterio licensed feed** — DEFERRED-PAID (one-time 20260428 CSV is what's loaded).
- **Shovels.ai, CleanView** — DEFERRED-PAID per `00-DECISIONS-AND-CONSTRAINTS.md` §5.2.

**Closest currently-shippable demo path**

Open the **Power Contracts** tab. Walk Karan through:
1. The GW-summary stacked-bar (Amazon 17.9 / Microsoft 10.47 / etc.) — this is exactly his §1.2 ask.
2. Click any deal card → see the SEC EDGAR `8-K` URL → that's his §1.1 "public filings as source of truth".
3. Switch to **Data Centers** tab → 6973 sites on a Leaflet map → his §1.1 "in which geography".

This is roughly 60% of Pillar 1. The missing 40% is the satellite/permit overlay on the same map.

### 3b. Pillar 2 — GPU Supply Chain

**What's implemented**

- **NVIDIA EDGAR extraction**: `/api/gpu/supply.revenue_estimates` returns 4+ filings. FY26 10-K (filed 2026-02-25, period_end 2025-04-27): `revenue_usd 215.9 B`, `inventory_usd 21.4 B`, `purchase_commitments_usd 95.2 B`, `customer_concentration_pct 78`, narrative excerpt included, `confidence 0.85`.
- **VendorFiler registry**: 19 vendors in `agents/edgar_agent.py:152-294` covering NVIDIA, AMD, Intel-DCAI, Broadcom, Marvell, Coherent, Lumentum, Credo, Astera Labs, Fabrinet, TSMC, Intel-Foundry, GlobalFoundries, Amkor, ASE Technology, ASML, Applied Materials.
- **Currency normalization**: TWD→USD, EUR→USD FX applied at read time (`routers/gpu.py:50-56`, `routers/supply_chain.py:61-68`).
- **NIC/optics**: `/api/nics.nic_shipments` returns Broadcom 10-K/10-Q rows with `revenue_usd 19.31 B Q1FY26`, EDGAR URLs.
- **Vendor extractor agent**: `agents/vendor_supply_extractor.py` (514 LOC) — LLM-driven structured extraction of segment_name/period_end/revenue/inventory/purchase_commitments/customer_concentration.

**What's partial**

- **TSMC**: registered in `edgar_agent.py:247-254` with form_types=(20-F, 6-K), but `/api/tsmc` returns `capacity=[]`, `packaging=[]`, `disclosures=[]`, `tsmc_filings_audited=0`. Extractor has not been run against TSMC's foreign-private-issuer filings yet. Same likely true for ASML / ASE / Amkor / GlobalFoundries.
- **Hyperscaler-silicon** (Alphabet TPU, Amazon Trainium, Microsoft Maia): `form_types=()` "press-only" (`edgar_agent.py:173-196`) — they're acknowledged, just not parsed.
- **Revenue, not units**: every dollar figure flows through but no `gpus_shipped_units` derivation. Karan literally asked "Total GPUs shipped" not "Total GPU $ shipped".

**What's missing**

- **Inventory gap math** (§2.2): `data.shipped`, `data.deployed`, `data.inventory` are empty arrays — schema fields exist, no producer.
- **NIC unit shipments** as opposed to Broadcom revenue line items.
- **Korean filers** (Samsung, SK Hynix) — explicitly excluded with rationale (`routers/supply_chain.py:37-46`: "files with Korean DART, not SEC EDGAR"). Honest scope.
- **SemiAnalysis / datacentermap.com** as augmenting sources.

**Closest currently-shippable demo path**

Open **Supplier Insights → GPU Supply** tab. Show NVIDIA quarterly revenue trend ($46.7 B Q2 → $57.0 B Q3 → $215.9 B FY full-year) with EDGAR click-throughs. Then **Supplier Insights → NICs & Optics** for Broadcom. Skip TSMC tab in the demo (zero data — embarrassing). This is ~50% of Pillar 2.

### 3c. Pillar 3 — Triangulation

**What's implemented**

- **L1 only**: `agents/triangulation.py:1-266` `compute_l1()`. `/api/triangulation/l1` returns 30+ company×state rows with `gw_total`, `sources` array showing whether each row was sourced from `sites`/`deals`/`edgar`, and a `confidence` score.
- **Honest UI banner**: `TriangulationTab.tsx:45-50` literally lists L1 as "live", L2/L3/L4 as "blocked" with the paid-data reason inline.
- **Q&A agent**: `agents/triangulation_qa.py` (450 LOC) wires natural-language queries against the data layer. Floating `ChatPanel` mounted globally (`App.tsx:14, 47`).

**What's partial**

- L1 is sums-of-MW, not yet adjusted for double-counting between `sites` and `deals` (e.g., Amazon's 200 M MWh disclosure shows up under deals; Amazon-named sites also show up). The agent uses `(buyer, state)` dedup; collisions in mixed-state deals route to `state="GLOBAL"` or `"US"` (visible in payload: Amazon GLOBAL 1.43 GW continuous-eq; Constellation US 16.0 GW). Confidence flagged low (0.5) for these.
- Constellation's 144.35 GW row is suspiciously large — likely an extraction or unit issue worth a sanity check.

**What's missing**

- **L2** (`shipped GPUs × power-draw × utilization`) — entire stage. Need: NVIDIA inventory $ → unit estimate → × 700W (H100) / 1000W (B200) → × utilization → expected GW.
- **L3** (NIC/optics correlation) — vendor data is present, cross-layer math unbuilt.
- **L4** (county permits as ground truth) — building-permit feed unbuilt.
- The "gap" KPI (power − inferred-compute) is the single number Karan would screenshot. Not in code.

**Closest currently-shippable demo path**

Open **Triangulation** tab. Lead with the layer-status banner ("L1 live, L2-L4 paid-data-blocked — here's what we can show"). Walk the L1 bar chart: Amazon Virginia 18.3 GW, Constellation Energy ALL-states 144 GW, Alphabet US 12.75 GW. Then pivot to the Q&A panel: ask "is there enough power for the GPUs being shipped in Texas?" — this exercises `triangulation_qa.py` and demonstrates intent even if the answer is qualified by missing L2.

---

## 4. Dashboard UX Audit

Walking every tab in `App.tsx:16-26` and `TabNav.tsx:7-23`:

| Tab | Exists? | Real data? | Click-through? | Notes vs. Karan framing |
|---|---|---|---|---|
| **Data Centers Overview** | ✅ | ✅ 6973 sites (Aterio CSV) | ✅ SiteDetail panel, role breakdown, Google Maps tile | Default landing tab. 1108 LOC. Strong drilldown. |
| **Power Contracts** | ✅ | ✅ curated 8-Ks + EDGAR + GW summary | ✅ 14 source-link instances (highest of any tab) | Hits §1.1, §1.2 directly. |
| **GPU Supply** | ✅ | ✅ NVIDIA, AMD, Intel-DCAI revenue | ✅ EDGAR URL on every row | Revenue-not-units gap (§2.1). |
| **NICs & Optics Supply** | ✅ | ✅ Broadcom + Marvell + Coherent + Lumentum | ✅ | Same revenue-not-units issue. |
| **Wafer Production & Supply (TSMC)** | ✅ | ❌ All four arrays empty (`tsmc_filings_audited=0`) | n/a | Tab exists, content does not. Embarrassing in a demo. |
| **Country Permits** | ✅ | ⚠️ Generator permits, not building permits | ✅ source_url on rows | Misnamed for Karan's framing — these are EPA/PJM/state generator permits, not county-level construction permits. |
| **Companies** | ✅ | ✅ 1247 companies | ✅ company-detail with role distribution | Not in Karan's brief but useful. |
| **Triangulation** | ✅ | ⚠️ L1 only (mock-badged in `TabNav.tsx:21` `real: false`) | ✅ source breakdown per row | Honest layer status banner mitigates. |
| **Data Sources** | ✅ | ✅ ingestion ledger from `data_source_runs` | ⚠️ partial | Surfaces `aterio_csv stored=40722`, `edgar v2 stored=15`, `pjm_iso stored=3631`, etc. Karan asked for this — present. |

**Tabs Karan asked for that are missing:**
- **Satellite View tab** — NOT in `TabNav.tsx`. `/api/satellite/sites` exists but only returns site coordinates (same data as `/api/sites/`). No tile fetch, no imagery layer, no time slider, no change-detection diff. The `Site` model has `latest_satellite_picture_date` (referenced in PRD model line ~174) but it's null on every site I sampled.

**Construction-change-detection over time:**
- Not implemented anywhere. No Sentinel-2 fetch, no Earth Engine API integration, no per-site image archive. Coverage table seeds a `satellite` pillar row (`seed/coverage_seed.py:208`: "Sentinel-2 L2A, 10m resolution, 5-day revisit cycle") but the pillar has 0 records and no producer.

**"Intelligence tool, not digest" framing:**
- Drilldown is good on Data Centers + Companies, weak on Power deals (no per-deal expand panel beyond the row-level disclosure), absent on GPU/NIC/TSMC (you can click EDGAR but not a structured detail view).
- Floating ChatPanel + WeeklyBriefCard live alongside the data — the brief is *one card* on Triangulation, not the whole product. ✅
- Time slider on each tab (PRD §4.4): not present anywhere I found.
- Cross-tab filter by company/geo (PRD §4.4): not present.

---

## 5. Open Questions (Karan) — Recommended Defaults

| Karan's Open Q | Recommended default if no answer | Why |
|---|---|---|
| Geographic priority — US-only or global day-1? | **US-only for v2 demo, surface Canada-AB sites as bonus**. | Building-permit pipeline (Karan's §1.4) only exists in US jurisdictions and is the highest-value next ingest. 6/8 GW summary entities are US-anchored. AB Wonder Valley 5.3 GW already shows up as "bonus geography" — keep it but don't promise global coverage. |
| Include OCI regions and planned OCI expansions? | **Yes — Oracle is already in `gw-summary` (11.6 GW). Add an OCI-flag column in `companies` and an "OCI footprint" sub-tab on the Companies page.** | Karan literally asked "Where OCI sits relative to hyperscalers". Need parity treatment with MSFT/AWS/GCP. The data is in the DB; it's a UI affordance. |
| Shovels.ai vendor approved? | **Assume NO until procurement confirms. Build a free-data fallback using municipal open-data portals (NYC, LA County, Loudoun VA, Mesa AZ already have public APIs).** | Per `00-DECISIONS-AND-CONSTRAINTS.md` §5.2 paid sources are deferred. Building 3-5 county adapters in 2 weeks beats waiting on procurement. |

---

## 6. Recommended Next 3 Things to Ship (Priority Order)

### #1 — Run the TSMC + ASML + ASE extractors (close the empty-tab embarrassment)

- **Who**: backend engineer (1 person).
- **Time**: 1–2 days.
- **What Karan sees**: `/api/tsmc` returns non-empty `capacity`/`packaging`/`disclosures`. The Wafer Production tab renders quarterly TWD→USD revenue, CoWoS commentary excerpts, click-through to TSMC 20-F on EDGAR. Hits Karan's §2.5 ask directly.
- **Dependencies**: None. Vendor registry already in place (`edgar_agent.py:247-294`); just needs a backfill run of `vendor_supply_extractor.py` against TSMC/ASML/ASE/Amkor/GlobalFoundries CIKs. Can run today.

### #2 — L2 Compute-Demand layer (the "gap is the signal" math)

- **Who**: backend engineer + 0.5 day from a researcher to validate the unit-economics assumptions.
- **Time**: 3–5 days.
- **What Karan sees**: `/api/triangulation/l2` ships. New chart on Triangulation tab: `Inferred GW Compute Demand` overlaid on `Contracted GW`. The delta is the headline number ("Microsoft has 10.5 GW contracted; ~7.2 GW absorbs FY26 NVIDIA shipments at 60% utilization; 3.3 GW overhang"). Hits §2.2, §3.3, and §2.7 ("the gap is the signal") simultaneously.
- **Dependencies**: NVIDIA `inventory_usd` already extracted. Need: per-SKU $/W assumptions (H100 ~$30k/700W; B200 ~$40k/1000W) — researcher input. Then extend `agents/triangulation.py` with `compute_l2()` parallel to `compute_l1()`.

### #3 — Satellite tab (Sentinel-2 free-tier MVP, 5-site pilot)

- **Who**: frontend + backend (pair, 1.5 days each).
- **Time**: 1 week.
- **What Karan sees**: a new "Satellite" tab in TabNav (between Power and GPU Supply per the brief's order). Pilot 5 sites — Microsoft Quincy WA, Amazon Loudoun VA, Google Council Bluffs IA, Meta Eagle Mountain UT, Oracle Las Vegas NV. For each: a Sentinel-2 tile from 6 months ago, today's tile, and a simple side-by-side. Click-through to ESA Copernicus data hub for full-res.
- **Dependencies**: Sign up for ESA Copernicus / Earth Engine free tier (no procurement). Hits §1.3 + §4.3 partially ("change detection over time" is just two timestamps, not ML diff — but it's something Karan can see).

---

_End of audit. Roughly 11 pages, 30 cited evidence points, 1 hour of investigation. Reader should feel equipped to defend current scope and pick the next 3 things to build._
