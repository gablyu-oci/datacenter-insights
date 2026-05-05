# Demo Brief — Datacenter & Power Intelligence Platform
_Generated 2026-05-01 for the demo on 2026-05-02. Reflects live state of the prototype at https://localhost:5174 backed by FastAPI on :8002._

---

## 0. The 30-second pitch

A competitive-intelligence dashboard for OCI strategy. Three pillars:

1. **Power contracting** — who's locking up gigawatts where (vs. OCI).
2. **Hardware supply chain** — GPUs, NICs, optics, foundry/packaging — what's shipping and at what scale.
3. **Triangulation** — cross-reference contracted power vs. inferred GPU compute demand to surface *gaps* (the headline number Karan asked for).

Driven by **free public data** (SEC EDGAR, EPA ECHO, PJM ISO, state DEQs, IR press releases, county Socrata APIs, Aterio one-time CSV). LLM agents do the heavy lifting on extraction, classification, and Q&A. No paid data sources.

**Today: ~22% real data / 78% mock — but every Karan-priority pillar has live data behind it.**

---

## 1. Data sources — by tab → graph → endpoint → freshness

### Tab 1: Data Centers Overview (1108 LOC)
**Endpoint:** `GET /api/sites/?page_size=10000`

| Component | Data source | Rows | Update freq |
|---|---|---|---|
| Google-satellite map (Leaflet + react-leaflet-google-layer + MarkerCluster) | `sites` table — Aterio CSV one-time import | **6,973 sites** | one-shot 2026-04-28 (Aterio licensed feed deferred) |
| Pie/bar — by lifecycle stage | same | — | — |
| Pie/bar — by provider | same | — | — |
| Click → SiteDetail panel (milestones, address, source links) | `sites` + `site_milestones` | — | — |
| KPI tiles — total MW, total sites, top providers | aggregated client-side | 6,973 / ~270 GW | — |

**Demo talking points:** drag-zoom into Loudoun VA (Microsoft / AWS cluster). Click a Microsoft pin → SiteDetail panel pops with milestones + provider info. Stage colors: green=Active, amber=Construction, blue=Announced, red=Cancelled.

### Tab 2: Power Contracts (944 LOC)
**Endpoints:** `/api/power/announcements`, `/api/power/capacity`, `/api/power/gw-summary`, `/api/power/timeseries`

| Component | Data source | Rows | Update freq |
|---|---|---|---|
| **GW Side-by-side bar** (the marquee Karan visual) | `curated_deals` + EDGAR 8-Ks | 8 entities | curated_deals manual; EDGAR daily |
| Power capacity by provider | `sites` aggregated | 345 distinct providers | 1× Aterio import |
| Power timeseries (announcements over time) | `curated_deals` + 8-Ks | 23 deals | EDGAR daily 06:00 UTC |
| Deal-card list (clickable through to SEC) | `curated_deals` (curated 8-Ks) | 23 | manual |
| Power-relevant 10-K/10-Q extractions | `edgar_extractions` (pillar=`power_contract`) | 8 | EDGAR weekly |

**Live GW Summary numbers:**
| Company | GW Total | Deals | Nuclear | Renewable |
|---|---:|---:|---:|---:|
| Amazon | 17.90 | 5 | 15.70 | 0.00 |
| Constellation (acquirer side) | 16.00 | 1 | — | — |
| Google | 12.75 | 4 | 3.25 | 9.50 |
| **Oracle** | **11.60** | **2** | **1.60** | **10.00** |
| Microsoft | 10.47 | 4 | 1.67 | 5.80 |
| Meta | 7.00 | 2 | 1.00 | 6.00 |
| Talen | 2.57 | 1 | — | — |
| Vistra | 2.30 | 1 | — | — |

**Demo talking points:** Oracle is **#4 by total GW** (ahead of Microsoft and Meta), thanks to a 10 GW renewable PPA. Click any deal card → opens the SEC EDGAR 8-K source. The Amazon 200 M MWh disclosure (from FY25 10-K) implies **~1.43 GW continuous-equivalent** (200 TWh ÷ 16 yr ÷ 8,760 hr; ~3.6–4.8 GW nameplate at 30–40% CF). Earlier internal note of "~12.5 GW" was a unit error (treated TWh/yr as GW) — corrected 2026-05-04.

### Tab 3 — Supplier Insights → GPU Supply (239 LOC)
**Endpoint:** `/api/gpu/supply` (filters `pillar='vendor_supply'`)

| Component | Data source | Rows | Update freq |
|---|---|---|---|
| Per-vendor quarterly revenue line chart | `edgar_extractions` JSON-packed `excerpt` | 18 rows (NVIDIA 6 + AMD 6 + Intel-DCAI 6) | EDGAR quarterly weekly cron Wed 06:00 UTC |
| KPI tiles — latest revenue per vendor | same | — | — |
| Coverage gaps panel — Alphabet/Amazon/Microsoft (press-only) | `coverage` | — | — |

**Latest extracted figures:**
- NVIDIA Data Center: **$215.94B FY26** (10-K, period_end 2025-04-27)
- AMD Data Center: $9.25B Q3 2025
- Intel DCAI: $52.85B FY25 / Foundry segment $12.72B Q1 2025

**Demo talking points:** Click any data point → SEC EDGAR filing opens. NVIDIA's $215.94B FY-revenue is the input to the Triangulation L2 gap-analysis math (4.4 GW global compute demand inferred).

### Tab 4 — Supplier Insights → NICs & Optics (302 LOC)
**Endpoint:** `/api/nics`

| Component | Data source | Rows | Update freq |
|---|---|---|---|
| NIC-silicon line chart | `edgar_extractions` (Broadcom, Marvell, Astera Labs, Credo) | 24 rows | weekly Wed 06:00 |
| Optics line chart | `edgar_extractions` (Coherent, Lumentum, Fabrinet) | 18 rows | weekly Wed 06:00 |

**Live numbers (latest filings):** Broadcom $63.89B FY • Marvell Q4 FY25 ~$2B • Coherent $1.69B • Lumentum $670M • Credo $410M Q2 FY26 • Astera Labs $850M • Fabrinet $1.13B.

**Demo talking points:** Coherent CIK was wrong before (was actually Willis Towers Watson, found and fixed). Astera Labs has 70% customer-concentration warning surfaced inline.

### Tab 5 — Supplier Insights → Wafer Production & Supply (301 LOC)
**Endpoint:** `/api/tsmc`

| Component | Data source | Rows | Update freq |
|---|---|---|---|
| Foundry line chart (TSMC, Intel-Foundry, GF) | `edgar_extractions` (20-F + 6-K) | 8 rows | Wed weekly |
| OSAT/Packaging chart (Amkor, ASE) | same | 8 rows | weekly |
| Equipment chart (ASML, AMAT) | same | 9 rows | weekly |
| Coverage gaps — Samsung, SK Hynix flagged "non-EDGAR" | `coverage` | — | — |

**TSMC was empty until yesterday.** Now has 1 row from FY24 20-F (CHIPS-Act narrative). ASML reporting in EUR; TSMC + ASE TWD→USD currency normalization at read time (~NT$32 = $1).

**Demo talking points:** "We extract structured revenue / inventory / purchase commitments / customer concentration from the LLM-parsed segment tables. Samsung and SK Hynix are explicitly flagged as 'unreachable via SEC EDGAR' since they file with Korean DART — this is honest scope-keeping, not a bug."

### Tab 6: Country Permits (1496 LOC) — *just added building-permit toggle yesterday*
**Endpoints:** `/api/permits/?page_size=10000` (generator), `/api/permits/building?days=180` (building)

**Toggle: Generator | Building**

| Mode | Data source | Rows | Coverage | Update freq |
|---|---|---|---|---|
| **Generator** (default) | EPA ECHO (federal) + PJM interconnection queue + TCEQ (TX) + VA Open Data + NY DEC | **4,150 rows** (501 with lat/lon) | 51 states | daily (EPA 08:00, PJM/state daily 07:00) |
| **Building** (Karan's §1.4 ask) | Loudoun County VA Socrata + Mesa AZ Socrata | **345 rows** (271 + 74) | VA, AZ | weekly Mon 06:00 |

**Both modes:** Google-satellite map, MarkerCluster, MW-sized pins, click for source link.

**Sample building permit:** Mesa `PMT25-22348` — *"RED HAWK PH03 Foundation"* at 7232 E Elliot Rd, valuation **$36.75M**, 284,497 sqft, applicant JE Dunn — exactly the construction-ground-truth signal Karan asked for.

**Demo talking points:** Toggle to Building → 345 datacenter-keyword-matched permits from open-data portals. Grant County WA (Microsoft+AWS hub) doesn't have a free API; the adapter logs that gap weekly without failing. **No paid Shovels.ai used.**

### Tab 7: Companies (638 LOC)
**Endpoint:** `/api/companies/?order_by=site_count&page_size=50`

| Component | Data source | Rows | Update freq |
|---|---|---|---|
| Companies list — top 50 by site count | `companies` + `site_company_associations` | **1,247 companies** | derived from Aterio + EDGAR |
| Click → CompanyDetailPanel | `/api/companies/{id}`, `/role-summary`, `/sites?page_size=1000`, `/filings?limit=20` | — | — |
| Per-company sites map | join `sites` ↔ `site_company_associations` | — | — |
| Per-company role distribution (end_user / provider / financing) | `site_company_associations` | — | — |

**Live: 1,247 unique companies.** Top by site count: Amazon (706), Dominion (573), Microsoft (345), **Alphabet (276)**, Tract (230), Meta (208), QTS (203), Oncor (202), ComEd (182).

**Demo talking points:** Click Alphabet → see the 276 distinct sites split across `provider` (217), `end_user` (58), `financing` (3). Yesterday's bug-fix: count was 278 because two sites hold dual roles; now correctly de-duplicates to 276.

### Tab 8: Triangulation (706 LOC) — **THE KARAN HEADLINE**
**Endpoints:** `/api/triangulation/l1`, `/api/triangulation/l2`

| Component | Data source | Rows | Update freq |
|---|---|---|---|
| **L1 — Contracted Power by company × state** | `agents/triangulation.py::compute_l1` joins `sites + curated_deals + edgar_extractions(pillar=power_contract)` | **1,014 rows** | computed live on every request |
| **L2 — Compute Demand vs Contracted Power gap** (NEW yesterday) | `compute_l2` derives from NVIDIA Data Center revenue × ASP × power × utilization × overhead | computed live | live |
| L1 stacked bar — top company×state | same | — | — |
| L2 grouped bar — Contracted GW (blue) vs Implied GW (orange) per hyperscaler | same | 5 hyperscalers | live |
| Assumptions panel (expandable) — model inputs | constants in `triangulation.py` | — | — |
| L3/L4 banner — "blocked, paid-data" | `coverage` | — | — |

**THE HEADLINE NUMBERS for the demo (period 2026-01-26):**
- NVIDIA FY DC revenue: $215.94B
- Inferred global GPU units: 6.17M
- Inferred global compute demand: **4.4 GW**

| Hyperscaler | Contracted GW | Implied Compute GW | **Gap** | Status |
|---|---:|---:|---:|---|
| Amazon | 17.90 | 1.32 | **16.58** | overcontracted |
| Google | 12.75 | 0.94 | **11.81** | overcontracted |
| Oracle | 11.60 | 0.85 | **10.75** | overcontracted |
| Microsoft | 10.47 | 0.77 | **9.70** | overcontracted |
| Meta | 7.00 | 0.52 | **6.48** | overcontracted |

**Model assumptions (visible in expandable panel — Karan WILL push back):**
- Avg blended GPU power: 850 W (50/50 H100 700W / B200 1000W)
- Avg ASP: $35,000 / GPU
- Utilization: 60%
- Datacenter overhead multiplier: 1.4× (PUE + networking + cooling)
- Per-hyperscaler share: distributed proportional to contracted GW (no authoritative customer breakdown)

**Demo talking points:** "All five hyperscalers show as 'overcontracted' — they have **more contracted GW than current FY26 GPU shipments imply**. That's expected: contracted is forward-looking, implied is current. The *gap* is the headline. Tunable assumptions panel lets us update the model in seconds when Karan pushes back."

### Tab 9: Data Sources (527 LOC)
**Endpoints:** `/api/sources/`, `/api/coverage/`

| Component | Data source | Update freq |
|---|---|---|
| Data Coverage Matrix (collapsible) — pillar × state | `data_coverage` (280 rows) | hourly auto-refresh |
| Per-source ingestion ledger — name / version / total_records / run_count / last_run | `ingestion_runs` aggregated | hourly |
| Agent pipeline status cards | `ingestion_runs` | hourly |

**Live ingestion ledger (top 8 by stored rows):**

| Source | Version | Stored | Runs | Last run |
|---|---|---:|---:|---|
| aterio_csv | 1.0.0 | 40,722 | 2 | 2026-04-28 |
| pjm_iso | 1.1.0 | 3,631 | 1 | 2026-04-29 |
| epa_echo | 1.2.0 | 2,000 | 4 | 2026-04-30 |
| epa_echo | 1.0.0 | 1,000 | 2 | 2026-04-30 |
| ir_press_releases | 1.0.0 | 18 | 1 | 2026-04-30 |
| edgar | 2.0.0 | 15 | 5 | 2026-04-30 |
| tceq | 2.0.0 | 14 | 2 | 2026-04-29 |
| va_open_data | 2.0.0 | 12 | 4 | 2026-04-30 |

---

## 2. Cron schedule (live, APScheduler)

| Job | Adapter | Cron | Phase |
|---|---|---|---|
| **edgar_daily** | edgar 8-K fetcher | `0 6 * * *` (daily 06:00 UTC) | 1 |
| **quarterly_filings_weekly** | edgar_quarterly (10-K/10-Q/20-F/6-K) | `0 6 * * 3` (Wed) | 2 |
| **anomaly_detection_nightly** | anomaly_detector | `30 2 * * *` | 2 |
| **permits_state_daily** | TCEQ + VA + NY | `0 7 * * *` | 1 |
| **county_permits_weekly** *(new)* | Loudoun + Mesa Socrata | `0 6 * * 1` (Mon) | 2 |
| **permits_air_daily** | EPA ECHO | `0 8 * * *` | 1 |
| **coverage_refresh** | rebuild data_coverage matrix | `0 * * * *` (hourly) | 1 |
| **stale_check** | `0 */4 * * *` (every 4h) | 1 |
| **cache_cleanup** | `0 0 * * *` (daily) | 1 |
| **weekly_brief** | LLM-generated narrative | `0 23 * * 0` (Sun) | 1 |

Aterio is API-trigger only (no cron — one-time CSV import).

---

## 3. Agentic components (LLM-driven)

The **Llama Stack** instance at `https://llama-stack.ai-apps-ord.oci-incubations.com` (model: `oci/openai.gpt-5.4`) backs all of these:

| Agent | File | Purpose | When |
|---|---|---|---|
| **EDGAR power-contract extractor** (`llm-v4-multiform`) | `backend/agents/edgar_extractor.py` (532 LOC) | Two-step CLASSIFY+EXTRACT: gates 8-K/10-K/10-Q text for power-deal language (PPA, MW, nuclear restart, generator interconnect), produces structured rows. | EDGAR cron daily + weekly |
| **Vendor-supply extractor** (`vendor_supply_v1`) | `backend/agents/vendor_supply_extractor.py` (390 LOC) | Regex prefilter (37% pass rate) → LLM extract-only → structured payload (segment_revenue / inventory / purchase_commitments / customer_concentration). Drops chunks with power-deal markers (handed off to the power extractor). | EDGAR quarterly cron |
| **Anomaly detector** | `backend/agents/anomaly_detector.py` | Scans new EDGAR rows for unusually large MW figures or dollar-spend deltas; writes to `anomalies` table. | nightly 02:30 UTC |
| **Triangulation L1** | `backend/agents/triangulation.py::compute_l1` | Aggregates sites + deals + edgar_extractions to per-company × state GW totals; provenance + confidence per row. | live on /api/triangulation/l1 |
| **Triangulation L2** *(NEW)* | `backend/agents/triangulation.py::compute_l2` | Math model: NVIDIA DC revenue → units → power → utilization → overhead → expected GW per hyperscaler. | live on /api/triangulation/l2 |
| **Q&A agent (Datacenters)** | `backend/agents/datacenter_qa.py` (450 LOC) | Schema-aware natural-language → SQL → structured chart_spec. Floating ChatPanel widget. | on user query |
| **Q&A agent (Triangulation)** | `backend/agents/triangulation_qa.py` (450 LOC) | Cross-pillar Q&A; can answer "is there enough power for the GPUs being shipped in Texas?" | on user query |
| **Parent resolver** | `backend/agents/parent_resolver.py` (982 LOC) | LLC → public-parent canonicalization (e.g., "Vadata Inc." → Amazon). Backs `companies` table. | nightly |
| **Press-release scraper + classifier** | `backend/ingestion/press_releases.py` | Per-IR HTML scraper across 17 tracked vendors + LLM classification for datacenter-relevance. | daily |
| **Weekly brief writer** | `backend/agents/weekly_brief.py` | LLM narrative summary of last week's activity rendered as a card on the Triangulation tab. | Sunday 23:00 UTC |

**Q&A demo:** Click the floating chat icon → type *"What's Microsoft's largest power deal?"* → live SQL + chart-spec response with EDGAR source links.

---

## 4. What's NOT built (gaps and deferred-paid items)

### Not built (free, in-scope, just no-time-yet)
- **Satellite Imagery tab** — Karan asked for a separate tab with Sentinel-2 imagery + change detection over time. **Tab does not exist.** Free Sentinel-2 via ESA Copernicus is technically possible — pilot would be ~1 week.
- **Earnings transcript parsing** — Karan named NVIDIA / TSMC / hyperscaler earnings calls. We do **filings** (10-K/10-Q/20-F) but not call **transcripts**. FMP / Capital IQ are paid; SeekingAlpha has anti-bot. SEC's Inline XBRL gives us the structured data without needing transcripts for the headline numbers.
- **GPU unit shipments** — we extract NVIDIA Data Center revenue ($), not unit counts. The L2 model derives units via `revenue / $35K ASP` but that's a model assumption, not vendor disclosure. NVIDIA doesn't disclose units publicly.
- **Inventory gap calc** (Karan's "shipped but not deployed") — we have the pieces (NVIDIA inventory $, purchase commitments $, contracted GW) but no derived KPI tile yet.
- **Construction change detection** — Aterio milestones exist but no time-slider / before-after tile / diff view.
- **OCI footprint hero tile** — Oracle's 11.6 GW shows up in `/api/power/gw-summary` but no per-tab "where OCI sits" KPI.
- **Building permits beyond VA + AZ** — Grant County WA documented as no-free-API; LA County, Santa Clara CA, NoVa other counties not yet wired. Each is ~1 day if the county has a Socrata-style endpoint.

### Deferred-paid (blocked on procurement / explicit scope decision)
- **Shovels.ai** — county-permits-as-a-service. Karan named it; we built free Socrata adapters instead.
- **Planet Labs / Maxar** — high-res satellite imagery. Free Sentinel-2 is the alternative.
- **Aterio licensed feed** — we have the one-time CSV import (40,722 rows already loaded) but not the live feed.
- **CleanView** — power-deals API. Out of scope.
- **FMP / Capital IQ** — earnings transcripts. Replaced by SEC EDGAR filings.
- **datacenter.com / datacentermap.com / SemiAnalysis** — TOS-restricted; not scraped.

### Deliberately out of scope
- **Korean filers (Samsung, SK Hynix)** — file with Korean DART, not SEC EDGAR. Surfaced as explicit "non-EDGAR" coverage gaps in the UI so users know it's a scope decision, not a bug. SK Hynix is the HBM signal — meaningful gap, but not fillable for free.
- **Hyperscaler in-house silicon** (Alphabet TPU, Amazon Trainium, Microsoft Maia) — not broken out in 10-K segment tables. We track these via press-release scraping only; they appear in the GPU Supply tab as press-only coverage gaps.

---

## 5. Recommended demo flow (15 min)

1. **Open** at Data Centers Overview tab. Quick zoom into Loudoun VA → click Microsoft Quincy site → SiteDetail panel pops with milestones + provider info. *"6,973 sites mapped, color-coded by lifecycle stage."*

2. **Click Power Contracts.** Show GW side-by-side: *"Amazon 17.9, Microsoft 10.47, Oracle 11.60. Oracle is #4 by total GW, ahead of Microsoft and Meta on contracted power."* Click an Amazon deal card → 8-K opens on sec.gov.

3. **Click Triangulation.** Lead with L2: *"NVIDIA's $215.94B FY revenue implies 6.2 million GPUs × 850W × 60% utilization × 1.4 datacenter overhead = 4.4 GW of global compute demand. Microsoft has 10.47 GW contracted — that's a 9.7 GW overhang. The gap is the signal."* Open the assumptions panel — Karan will engage. Move to L1 stacked bar for company × state breakdown.

4. **Click GPU Supply.** Show NVIDIA / AMD / Intel-DCAI quarterly revenue line chart. Click NVIDIA's $215.94B point → SEC 10-K opens.

5. **Click Wafer Production & Supply.** Show ASML + Applied Materials timeseries. Skip the empty TSMC headline (1 row); explain the 20-F path landed yesterday and is filling in. *"Samsung + SK Hynix are flagged non-EDGAR — Korean DART, not SEC. Honest scope."*

6. **Click Country Permits → toggle to Building.** *"345 county-permitted datacenter shells from free Loudoun VA + Mesa AZ Socrata APIs. This is Karan's §1.4 ask: ground truth on construction starts vs. announcements."* Click a Mesa permit → opens the source.

7. **Click Companies.** Click Alphabet → 276 sites by role. *"1,247 unique companies, LLC→parent canonicalization done by an LLM agent."*

8. **Click Data Sources.** Show the ingestion ledger: 40,722 Aterio + 4,150 generator permits + 345 building permits + 88 EDGAR-extracted rows + 23 curated deals + 18 press releases. *"Every number on every chart traces back here."*

9. **Click the floating chat icon.** Type: *"What's Oracle's largest power deal?"* Live SQL + chart + source link. *"Same agent answers cross-pillar questions like 'is there enough power in Texas?'"*

10. **Land the close:** *"Today is 22% real / 78% mock. Karan's three pillars all have live data behind them. Top three things to ship next: satellite imagery tab, more county permit adapters, OCI hero tile."*

---

## 6. Numbers to memorize for Karan's questions

| If Karan asks… | Answer |
|---|---|
| "How many sites?" | 6,973 (Aterio one-time, 2026-04-28) |
| "Where does Oracle sit?" | #4 by GW (11.60), ahead of Microsoft, Meta |
| "How real is the data?" | ~22% real / 78% mock; all three pillars have live extraction |
| "What's the gap headline?" | Microsoft 9.7 GW overhang vs. inferred FY26 compute |
| "What's the assumption?" | $35K/GPU × 850W × 60% util × 1.4 PUE; expandable + tunable |
| "Why no Samsung?" | Files Korean DART, not SEC EDGAR. Surfaced as explicit scope gap |
| "Where's the Satellite tab?" | Not built. Sentinel-2 free pilot is ~1 week of work |
| "Why generator permits + building permits?" | Generator = EPA ECHO/PJM/state DEQs (501 with coords). Building = Loudoun + Mesa Socrata (345 with coords + valuations). Different signals. |
| "What's the LLM doing?" | 11 agentic components. EDGAR classify+extract, vendor-supply extract, parent resolver, anomaly detection, weekly brief, two Q&A agents |
| "Sources?" | 9 free public sources (SEC EDGAR, EPA ECHO, PJM, TCEQ, VA Open Data, NY DEC, Loudoun Socrata, Mesa Socrata, IR pages). Aterio one-time CSV. No paid feeds |

---

## 7. Known caveats — get ahead of these

1. **TSMC has only 1 row** of vendor_supply data — its 20-F was processed yesterday but only one chunk passed the regex+LLM gate (CHIPS-Act narrative). Acceptable; not a bug.
2. **Triangulation is mock-badged** in the nav (`real: false`) but L1 returns 1014 real rows + L2 is a live model. The badge is conservative; happy to flip to "real" if Karan asks.
3. **Permits map shows 501 of 4,150 pins** — only EPA ECHO has lat/lon; PJM + state-permits feed the table but not the map.
4. **Hyperscaler L2 shows all 5 as "overcontracted"** — that's expected: contracted GW is forward-looking, implied compute is current FY. The number that matters is the *trend* of the gap.
5. **Coherent CIK was wrong** before this week — pointed at Willis Towers Watson. Caught + fixed; new CIK is 0000820318.
6. **Q&A agent is best-effort** — it can hallucinate column names occasionally. We rate-limit and log to `llm_extraction_runs`. Don't lean on it as the demo headline.

---

## 8. If asked: what would the next 3 weeks look like?

1. **Week 1 — Satellite tab pilot.** 5-site Sentinel-2 before/after comparison (Microsoft Quincy, Amazon Loudoun, Google Council Bluffs, Meta Eagle Mountain, Oracle Las Vegas). Free ESA Copernicus.
2. **Week 2 — Building-permit county expansion.** Wire 5 more counties: Santa Clara CA, Loudoun VA depth, LA County, Phoenix metro, NoVa Loudoun expand to Prince William VA. Each is ~1 day.
3. **Week 3 — OCI hero tile + L2 refinement.** Per-tab "OCI position" KPI; refine L2 with H100/B200 mix per quarter; add inventory-gap KPI ("$21B NVIDIA inventory = ~600K GPUs warehoused").

_Generated by reading the codebase, running live curls, and counting DB rows. Anything in this brief can be re-derived by re-running the queries in `KARAN_REQUIREMENTS_AUDIT.md`._
