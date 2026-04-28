# Data Source Landscape Report
# Datacenter & Power Intelligence Platform

**Date:** 2026-04-28 | **Author:** Strategic Insights Research Team | **Status:** Final Draft
**Scope:** Phase 1 -- **National (all 50 US states + DC)** with explicit per-state coverage indicators per `00-DECISIONS-AND-CONSTRAINTS.md` §5.2 + §5.3 | **Audience:** Karan, Strategy team, Engineering

> **Reading note (added 2026-04-28):** the per-source "NoVA coverage" cells throughout this report were the original framing when scope was Northern Virginia only. They remain useful as a *depth* indicator (NoVA is the heaviest datacenter market and sources that cover it well are likely high-value) but they are no longer a scope filter — the MVP runs nationally and any state with no covered source falls into the `<NoStateCoverage />` empty state per the coverage-honesty rule.

---

## Executive Summary

This report evaluates **24 data sources** across three intelligence pillars (Power & Geographic Expansion, GPU Supply Chain, Satellite Imagery) for the OCI Datacenter & Power Intelligence Platform. The platform must answer Karan's core question: *"Is there enough power being contracted to actually run all the GPUs being shipped -- and where is the gap?"*

**Key findings (national MVP):**
- A **national MVP can be built for $0/year** using free federal/state sources for the pillars that have national-scale free options (Aterio one-time CSV + SEC EDGAR + EPA ECHO + Sentinel-2). Building permits are partial: 6 states with free state APIs (VA + NY/WA/CO/OR via Socrata + TX TCEQ) cover the heaviest datacenter markets; the other 44 states render explicit no-coverage UI states.
- The **paid source stack** (Aterio licensed feed + Shovels.ai + Planet Labs + SemiAnalysis + FMP) would cost approximately $20K–60K/year and primarily fills the building-permit national gap and improves freshness on Aterio + earnings transcripts.
- **SEC EDGAR** is the single most important cross-pillar source (free, federal, structured, covers power and GPU supply chain).
- **PJM Interconnection Queue** is the best free leading indicator of power buildout in PJM territory (covers VA + 12 other states + DC). ERCOT/MISO/SPP/CAISO/NYISO/ISO-NE deferred — flagged in `<CoverageBadge />` as PJM-only in v1.
- All sources should be integrated via an **adapter interface pattern** with automatic free-tier fallback per pillar.

---

## Table of Contents

1. [Pillar 1: Power & Geographic Expansion](#pillar-1-power--geographic-expansion)
2. [Pillar 2: GPU Supply Chain](#pillar-2-gpu-supply-chain)
3. [Pillar 3: Satellite Imagery](#pillar-3-satellite-imagery)
4. [Free Alternatives & Fallbacks](#free-alternatives--fallbacks)
5. [Summary Comparison Table](#summary-comparison-table)
6. [Ranked Recommendations by Pillar](#ranked-recommendations-by-pillar)
7. [Phase-1 Minimum Source Set (National)](#phase-1-minimum-source-set-northern-virginia)
8. [Architectural Recommendations](#architectural-recommendations)
9. [Procurement Actions](#procurement-actions)
10. [Appendix: Source Details](#appendix-source-details)

---

## Pillar 1: Power & Geographic Expansion

### 1.1 SEC EDGAR (EFTS Full-Text Search + XBRL)

| Attribute | Detail |
|-----------|--------|
| **Data provided** | Full text of all electronic SEC filings (8-K, 10-K, 10-Q). XBRL structured financials. Keyword-searchable for "power purchase agreement", "data center", "megawatt", "capacity" |
| **Access method** | REST API (JSON). Full endpoint set per §4 of 00-DECISIONS-AND-CONSTRAINTS.md: **Submissions** (`data.sec.gov/submissions/CIK##########.json`), **CompanyFacts** (`data.sec.gov/api/xbrl/companyfacts/CIK##########.json`), **CompanyConcept** (`data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/<concept>.json`), **Frames** (`data.sec.gov/api/xbrl/frames/us-gaap/<concept>/USD/CY####Q#.json`) for cross-company quarterly comparison, **EFTS** (`efts.sec.gov/LATEST/search-index?q=<term>&forms=8-K`), **Nightly bulk ZIPs** (`companyfacts.zip`, `submissions.zip`) for cold-start backfill at 03:00 ET |
| **Auth** | No auth. Must include `User-Agent: YourName your@email.com` header |
| **Cadence** | Filings available within hours of submission. XBRL refreshed daily |
| **Cost** | **Free**. Rate limit: 10 req/sec |
| **Pillar(s)** | Power (PPA disclosures), GPU Supply (NVIDIA/TSMC/Broadcom financials) |
| **Strengths** | Free, structured, authoritative, covers all public companies. EFTS enables full-corpus keyword search |
| **Weaknesses** | PPA details buried in exhibit text requiring NLP. Not all power contracts appear in filings. Rate limiting requires throttling |
| **NoVA coverage** | Covers all public hyperscaler filings mentioning Virginia |

### 1.2 PJM Interconnection Queue

| Attribute | Detail |
|-----------|--------|
| **Data provided** | All generation interconnection requests in PJM territory (covers all of Northern Virginia). Fields: project name, fuel type, capacity (MW), county, state, queue position, status, in-service date |
| **Access method** | Data Miner 2: `https://dataminer2.pjm.com/` (CSV export). API Portal: `https://apiportal.pjm.com/` (JSON). Third-party: `https://www.interconnection.fyi/?market=PJM`. Python: `pip install gridstatus` |
| **Auth** | Free PJM Tools account for API |
| **Cadence** | Updated daily |
| **Cost** | **Free** |
| **Pillar(s)** | Power |
| **Strengths** | Best leading indicator for new power generation in NoVA. Structured, API-accessible, daily updates |
| **Weaknesses** | Queue entries are speculative (many never reach COD). Shows supply side only, not datacenter demand |
| **NoVA coverage** | Excellent -- PJM is the grid operator for all of Virginia |

### 1.3 County Building Permits (Loudoun, Prince William, Fairfax)

| Attribute | Detail |
|-----------|--------|
| **Data provided** | Permit applications, status, plan reviews for datacenter-related construction |
| **Access method** | Web portals only (no API). Loudoun: LandMARC (`loudoun.gov/5823/LandMARC`). Prince William: ePortal (`eservice.pwcgov.org`). Fairfax: PLUS (`plus.fairfaxcounty.gov/CitizenAccess/`). Virginia aggregator: `permits.virginia.gov/Permit/Search` |
| **Auth** | None (public records) |
| **Cadence** | Real-time as permits are filed |
| **Cost** | **Free** (requires scraping investment) |
| **Pillar(s)** | Power (construction ground truth) |
| **Strengths** | Ground truth for actual construction activity. Leading indicator (permits filed before construction) |
| **Weaknesses** | No API -- requires scraping 3 separate systems. Permits may not explicitly say "data center". High volume, manual filtering needed |
| **NoVA coverage** | Direct coverage of the three key counties |

### 1.4 Shovels.ai

| Attribute | Detail |
|-----------|--------|
| **Data provided** | Building permits + contractor data from 1,800+ jurisdictions (~85% US population). Fields: permit status, address, description (text-searchable), property type, contractor info |
| **Access method** | REST API: `https://api.shovels.ai/v2/` (JSON). Docs: `https://docs.shovels.ai` |
| **Auth** | API key (paid subscription) |
| **Cadence** | Weekly-monthly lag (varies by jurisdiction) |
| **Cost** | **$599/month** minimum. Free tier exists but limited. **Procurement TBD** (named by Karan) |
| **Pillar(s)** | Power (datacenter construction tracking) |
| **Strengths** | Aggregates multi-county permits into one API. Structured JSON, filterable by property type, keyword, geography |
| **Weaknesses** | $7.2K/year. Coverage of specific Loudoun County LandMARC data needs verification. Description-based filtering may miss unlabeled permits |
| **NoVA coverage** | Covers Virginia, but individual jurisdiction coverage should be confirmed before procurement |

### 1.5 Aterio

| Attribute | Detail |
|-----------|--------|
| **Data provided** | Comprehensive US datacenter inventory with **89 fields**: facility ID, campus, project stage (announcement/construction/active/cancelled), construction % complete, power capacity (MW, with Aterio estimates + upper/lower bounds), provider ticker, lat/long, county FIPS, utility/grid details, latest satellite picture date |
| **Access method** | Bulk download (Excel/CSV/JSON). API available: `https://knowledge.aterio.io/data-integrations/general-api-guide/introduction`. Also on Databricks Marketplace |
| **Auth** | Subscription required |
| **Cadence** | Regular updates (RECORD_UPDATED_DATE field) |
| **Cost** | **Enterprise pricing** (estimated $10K-50K/year). Contact sales |
| **Pillar(s)** | Power (primary), Satellite (secondary -- includes satellite-verified construction status) |
| **Strengths** | **Best-in-class structured datacenter inventory.** 89 fields including power capacity, construction status, utility mapping, satellite verification. Tracks hyperscalers by ticker. Sample dataset already on disk in `datasets/` directory |
| **Weaknesses** | Pricing unknown. Vendor approval required. Bulk download may not be real-time |
| **NoVA coverage** | Expected to be comprehensive for NoVA (major datacenter market) |
| **On-disk datasets** | **On-disk datasets (§3 of 00-DECISIONS-AND-CONSTRAINTS.md):** `data_center_inventory_20260428.csv` (73 cols, primary site seed), Aterio expanded sample xlsx (248 rows, test fixture), Data Dictionary xlsx (inventory fields + 957 Events rows), Energy Project Inventory xlsx (1695 rows × 65 cols for Energy Supply view). |

### 1.6 CleanView

| Attribute | Detail |
|-----------|--------|
| **Data provided** | 10,000+ clean energy AND datacenter projects across US. EIA 860M records, interconnection queue data from 7 ISOs (including PJM), unified project database, US datacenter map |
| **Access method** | REST API: `https://api.cleanview.co/api/v1` (JSON, sub-500ms). Free public Project Explorer at `https://cleanview.co/public/data-centers/us` |
| **Auth** | API key (manual approval, v1 Beta) |
| **Cadence** | Real-time queue data; EIA data per EIA schedule |
| **Cost** | **TBD** (beta product). Free public explorer available |
| **Pillar(s)** | Power (clean energy + datacenter project tracking) |
| **Strengths** | Unique combination of clean energy tracking + datacenter mapping + PJM queue data. API-first. Free explorer for Phase 1 demo |
| **Weaknesses** | Beta product -- may have gaps. Manual approval process |
| **NoVA coverage** | Includes PJM queue data (covers NoVA) |

### 1.7 datacentermap.com

| Attribute | Detail |
|-----------|--------|
| **Data provided** | 10,575 datacenters across 174 countries. Fields: address, coordinates, building size, whitespace, power capacity, tier rating, year operational, PUE |
| **Access method** | Research Explorer with export (KMZ, KML, SHP, CSV, GeoJSON). No public API |
| **Cadence** | Daily updates (provider-submitted + automated) |
| **Cost** | Free to browse; research/data export likely paywalled |
| **Pillar(s)** | Power (inventory) |
| **Strengths** | Broad global coverage, multiple export formats |
| **Weaknesses** | Voluntary submission means incomplete. No API. Less detailed than Aterio |

### 1.8 datacenterwatch.org

| Attribute | Detail |
|-----------|--------|
| **Data provided** | Regulatory/community opposition tracking. 142 advocacy organizations across 28 states. Reports on $64B of blocked/delayed projects |
| **Access method** | Website + Substack newsletter. Quarterly reports |
| **Cadence** | Weekly newsletter, quarterly reports |
| **Cost** | **Free** |
| **Pillar(s)** | Power (regulatory risk) |
| **Strengths** | Unique dataset on political/regulatory risk. Directly relevant to NoVA where community opposition is significant |
| **Weaknesses** | Editorial, not structured data. No API |

### 1.9 DatacenterDynamics (DCD)

| Attribute | Detail |
|-----------|--------|
| **Data provided** | Industry news, analysis, research reports on datacenter construction/capacity |
| **Access method** | Free news; research reports behind paywall |
| **Cadence** | Daily news; periodic research |
| **Cost** | Subscription (contact sales) |
| **Pillar(s)** | Power (industry intelligence) |
| **Strengths** | Deep industry expertise |
| **Weaknesses** | News/reports, not structured data. Not directly ingestible |

### 1.10 Virginia SCC + Dominion Energy IRP

| Attribute | Detail |
|-----------|--------|
| **Data provided** | Utility rate cases, Dominion IRP filings (15-year load forecasts, datacenter load projections), generation buildout plans |
| **Access method** | Docket search at `scc.virginia.gov/docketsearch`. PDFs only, no API |
| **Cadence** | IRPs every 3 years. Rate cases continuous |
| **Cost** | **Free** |
| **Pillar(s)** | Power |
| **Strengths** | Authoritative source for Dominion's datacenter load forecasts. 15-20 year buildout projections |
| **Weaknesses** | All PDFs. Infrequent IRP updates |

---

## Pillar 2: GPU Supply Chain

### 2.1 NVIDIA 10-K/10-Q (EDGAR)

| Attribute | Detail |
|-----------|--------|
| **Data provided** | Datacenter segment revenue (reported separately). CIK: 1045810. FY2026: $215.9B total revenue. XBRL: `data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json` |
| **Access method** | Free via EDGAR XBRL API (JSON) |
| **Cadence** | 10-K annual (~Feb), 10-Q quarterly (~Aug, Nov, May), 8-K event-driven |
| **Cost** | **Free** |
| **Pillar(s)** | GPU Supply Chain |
| **Strengths** | Definitive source for NVIDIA datacenter revenue. Machine-readable XBRL. Free |
| **Weaknesses** | Revenue only -- no unit shipments, no customer breakdown, no SKU detail. Quarterly granularity. Revenue lags shipments |

### 2.2 TSMC Earnings + CoWoS Capacity

| Attribute | Detail |
|-----------|--------|
| **Data provided** | CIK: 1046179 (ADR, 20-F). Q1 2026: $35.9B quarterly revenue (+40.6% YoY). CoWoS capacity: ~127K wafers/month. CapEx: $40.9B |
| **Access method** | 20-F on EDGAR. Earnings transcripts at `investor.tsmc.com/english`. CoWoS details from earnings calls (unstructured) |
| **Cadence** | 20-F annual. Earnings quarterly |
| **Cost** | **Free** |
| **Pillar(s)** | GPU Supply Chain (packaging bottleneck) |
| **Strengths** | TSMC is THE bottleneck for AI chip production. 20-F on EDGAR is machine-readable |
| **Weaknesses** | CoWoS specifics only from earnings calls (requires NLP parsing). No customer-level data |

### 2.3 Coherent Corp (formerly II-VI)

| Attribute | Detail |
|-----------|--------|
| **Data provided** | CIK: 820318. Datacenter & Communications: 46% of revenue. 800G shipping, 1.6T sampling. Projected 2030 datacenter SAM: $32B |
| **Access method** | EDGAR XBRL: `data.sec.gov/api/xbrl/companyfacts/CIK0000820318.json` |
| **Cadence** | Quarterly |
| **Cost** | **Free** |
| **Pillar(s)** | GPU Supply Chain (optical interconnects) |
| **Strengths** | Proxy for datacenter optical buildout. Transceiver speed mix indicates infra generation |
| **Weaknesses** | Revenue only, no unit counts. Multiple segments dilute signal |

### 2.4 Lumentum

| Attribute | Detail |
|-----------|--------|
| **Data provided** | CIK: 1633978. Cloud & Networking: $1,410.8M FY2025 (+30% YoY), ~90% of revenue |
| **Access method** | EDGAR XBRL: `data.sec.gov/api/xbrl/companyfacts/CIK0001633978.json` |
| **Cadence** | Quarterly |
| **Cost** | **Free** |
| **Pillar(s)** | GPU Supply Chain (optical components) |
| **Strengths** | Near-pure-play datacenter optical exposure. Strong leading indicator |
| **Weaknesses** | Revenue only |

### 2.5 Innolight (Zhongji Innolight)

| Attribute | Detail |
|-----------|--------|
| **Data provided** | Ticker: 300308.SZ (Shenzhen). World's largest optical transceiver producer. 2025 revenue: 38.24B yuan (+60.25% YoY) |
| **Access method** | Chinese exchange filings (Mandarin). Financial summaries via Yahoo Finance, MarketScreener. Filing for Hong Kong IPO |
| **Cadence** | Quarterly (Chinese calendar) |
| **Cost** | **Free** (summaries) |
| **Pillar(s)** | GPU Supply Chain |
| **Strengths** | Largest transceiver maker globally. Essential signal |
| **Weaknesses** | Chinese filings only. Language barrier. No EDGAR. No structured API |

### 2.6 Broadcom

| Attribute | Detail |
|-----------|--------|
| **Data provided** | CIK: 1730168. Networking segment: Ethernet switching/routing, NIC/SmartNIC for AI datacenters |
| **Access method** | EDGAR XBRL: `data.sec.gov/api/xbrl/companyfacts/CIK0001730168.json` |
| **Cadence** | Quarterly |
| **Cost** | **Free** |
| **Pillar(s)** | GPU Supply Chain (networking silicon) |
| **Strengths** | Dominant in datacenter switching. Networking buildout correlates with GPU deployment |
| **Weaknesses** | Post-VMware acquisition, networking is bundled with broader semiconductor segment |

### 2.7 SemiAnalysis

| Attribute | Detail |
|-----------|--------|
| **Data provided** | AI accelerator market model (shipments, ASPs, revenue by SKU/company/customer). H100 rental price index. CoWoS capacity tracking. Cloud GPU availability. Memory + foundry models |
| **Access method** | Newsletter (Substack). Institutional data products (reports, not self-serve API) |
| **Cadence** | Weekly newsletter. Models updated periodically |
| **Cost** | Newsletter: **$500/year**. Institutional: estimated **$25K-100K+/year** |
| **Pillar(s)** | GPU Supply Chain (primary, best-in-class) |
| **Strengths** | **Single best source for GPU supply chain intelligence.** SKU-level shipment estimates by customer unavailable anywhere else |
| **Weaknesses** | Expensive for institutional data. No self-serve API. Redistribution likely prohibited |

---

## Pillar 3: Satellite Imagery

### 3.1 Planet Labs

| Attribute | Detail |
|-----------|--------|
| **Data provided** | PlanetScope: 3m resolution, daily, global. SkySat: 50cm resolution, tasking or archive |
| **Access method** | REST APIs: Data API, Orders API, Subscriptions API. JSON metadata, GeoTIFF imagery |
| **Cadence** | PlanetScope: daily. SkySat: on-demand |
| **Cost** | SkySat Archive: **$6/km2**. Flexible Tasking: **$12/km2**. Assured Tasking: **$40/km2**. Packages: 50/150/300 km2 minimums |
| **Pillar(s)** | Satellite |
| **Strengths** | Daily PlanetScope for change detection. SkySat 50cm identifies buildings/equipment. API-first |
| **Weaknesses** | 3m PlanetScope may be too coarse for individual buildings. SkySat tasking is expensive. NoVA cloud cover reduces usable imagery |

### 3.2 Maxar (WorldView Legion)

| Attribute | Detail |
|-----------|--------|
| **Data provided** | Sub-30cm resolution. 6-satellite constellation. Up to 15 revisits/day. SecureWatch platform |
| **Access method** | SecureWatch (web + API). ~10 min delivery for high priority |
| **Cadence** | Up to 15x/day |
| **Cost** | GB-based pricing. Enterprise: estimated **$50K+/year** |
| **Pillar(s)** | Satellite |
| **Strengths** | Highest commercial resolution (<30cm). Can distinguish construction phases |
| **Weaknesses** | Very expensive. Government gets priority. Not practical for Phase 1 |

### 3.3 Google Earth Engine + Sentinel-2

| Attribute | Detail |
|-----------|--------|
| **Data provided** | GEE: 90+ PB of imagery (Sentinel-2, Landsat, MODIS, NAIP). Sentinel-2: 10m visible, 13 spectral bands |
| **Access method** | GEE: Python/JS APIs + web Code Editor. Sentinel-2: Copernicus Data Space (`dataspace.copernicus.eu`). Sentinel Hub API |
| **Cadence** | Sentinel-2: 5-day revisit (2-3 days at NoVA latitude). NAIP: annual |
| **Cost** | **Free** (GEE noncommercial; Sentinel-2 open) |
| **Pillar(s)** | Satellite |
| **Strengths** | Free. 5-day revisit. Built-in GEE change detection tools. Cloud compute included |
| **Weaknesses** | 10m resolution detects large-area changes only ("something changed"), not individual buildings. Cloud cover in NoVA reduces usable passes |

---

## Free Alternatives & Fallbacks

### OpenStreetMap (Overpass API)

| Attribute | Detail |
|-----------|--------|
| **Data** | Community-mapped datacenter POIs |
| **Access** | Overpass API: `https://overpass-api.de/api/interpreter`. Query: `node["building"="data_centre"](38.8,-77.6,39.1,-77.0);out;` |
| **Cost** | **Free** |
| **Use** | Starting point for known facility locations. Supplement, not primary |

### FERC eLibrary + EQR

| Attribute | Detail |
|-----------|--------|
| **Data** | All FERC filings (PPA approvals, rate cases). EQR: quarterly wholesale electricity transactions. PUDL (Catalyst Cooperative) provides cleaned Parquet data |
| **Access** | eLibrary: `ferc.gov/ferc-online/elibrary` (PDF). EQR: bulk download (FoxPro) or `eqronline.ferc.gov`. PUDL: `catalystcoop-pudl.readthedocs.io` (free Parquet on cloud) |
| **Cost** | **Free** |
| **Use** | Federal power transaction data, PPA terms |

### EIA (Energy Information Administration)

| Attribute | Detail |
|-----------|--------|
| **Data** | Form 860: all US power plants >=1MW. Form 861: utility-level data. 860M: monthly updates. API v2: `https://api.eia.gov/v2/` |
| **Access** | Free API key at `eia.gov/opendata/`. JSON responses. Virginia filter: `facets[state][]=VA` |
| **Cost** | **Free** |
| **Use** | Definitive federal data on US power generation capacity in Virginia |

---

## Summary Comparison Table

| # | Source | Pillar | Access | Format | Cadence | Cost | NoVA Coverage | Phase-1 Priority |
|---|--------|--------|--------|--------|---------|------|---------------|-----------------|
| 1 | SEC EDGAR EFTS+XBRL | Power+GPU | API | JSON | Hours | Free | All public cos | **MUST HAVE** |
| 2 | PJM Interconnection Queue | Power | API | JSON/CSV | Daily | Free | Excellent | **MUST HAVE** |
| 3 | County Permits (direct) | Power | Scrape | HTML | Real-time | Free (dev cost) | Direct | **SHOULD HAVE** |
| 4 | Shovels.ai | Power | API | JSON | Weekly | $599/mo | TBD (verify) | **NICE TO HAVE** |
| 5 | Aterio | Power+Sat | API+Bulk | JSON/CSV | Regular | $10-50K/yr | Expected good | **SHOULD HAVE** |
| 6 | CleanView | Power | API | JSON | Real-time | TBD (beta) | PJM included | **SHOULD HAVE** |
| 7 | datacentermap.com | Power | Export | CSV/GeoJSON | Daily | Paid (research) | Global | Low |
| 8 | datacenterwatch.org | Power | Manual | Newsletter | Weekly | Free | US-wide | Low |
| 9 | DCD | Power | Manual | Reports | Daily | Paid | Global | Low |
| 10 | VA SCC / Dominion IRP | Power | Manual | PDF | 3 years | Free | Excellent | Low (infrequent) |
| 11 | NVIDIA (EDGAR) | GPU | API | JSON | Quarterly | Free | N/A | **MUST HAVE** |
| 12 | TSMC (EDGAR) | GPU | API+NLP | JSON+PDF | Quarterly | Free | N/A | **MUST HAVE** |
| 13 | Coherent (EDGAR) | GPU | API | JSON | Quarterly | Free | N/A | **MUST HAVE** |
| 14 | Lumentum (EDGAR) | GPU | API | JSON | Quarterly | Free | N/A | **MUST HAVE** |
| 15 | Innolight | GPU | Manual | Mandarin | Quarterly | Free (summaries) | N/A | Low |
| 16 | Broadcom (EDGAR) | GPU | API | JSON | Quarterly | Free | N/A | **MUST HAVE** |
| 17 | SemiAnalysis | GPU | Newsletter | Reports | Weekly | $500/yr+ | N/A | **SHOULD HAVE** |
| 18 | Planet Labs | Satellite | API | GeoTIFF | Daily | $6-40/km2 | Available | **Phase 2** |
| 19 | Maxar | Satellite | API | GeoTIFF | 15x/day | $50K+/yr | Available | **Phase 3** |
| 20 | GEE + Sentinel-2 | Satellite | API | GeoTIFF | 5-day | Free | Available | **MUST HAVE** |
| 21 | OpenStreetMap | Power | API | GeoJSON | Irregular | Free | Partial | **MUST HAVE** |
| 22 | FERC eLibrary + PUDL | Power | Download | Parquet | Quarterly | Free | National | **SHOULD HAVE** |
| 23 | EIA API | Power | API | JSON | Monthly | Free | Virginia | **MUST HAVE** |

---

## Ranked Recommendations by Pillar

### Pillar 1: Power & Geographic Expansion

| Rank | Source | Justification |
|------|--------|---------------|
| **1** | **Aterio** | Best-in-class structured datacenter inventory (89 fields). Power capacity, construction status, utility mapping, satellite verification. Worth the procurement investment |
| **2** | **PJM Interconnection Queue** | Free, API-accessible, daily-updated pipeline of all new generation projects in NoVA. Best leading indicator of power supply |
| **3** | **CleanView** | Unique datacenter + clean energy tracking with PJM queue integration. Free explorer for demo; API for production |
| *Free fallback* | **PJM Queue (gridstatus) + EIA API + EDGAR EFTS + OSM** | Generation pipeline + existing capacity + PPA keyword alerts + facility map -- all free |

### Pillar 2: GPU Supply Chain

| Rank | Source | Justification |
|------|--------|---------------|
| **1** | **NVIDIA 10-K/10-Q (EDGAR XBRL)** | Definitive datacenter revenue. Machine-readable, free. The foundation |
| **2** | **TSMC 20-F + Earnings Transcripts** | CoWoS packaging = the bottleneck. 20-F on EDGAR; earnings calls need NLP parsing |
| **3** | **SemiAnalysis (Newsletter tier)** | At $500/yr: SKU-level analysis and demand signals unavailable anywhere else |
| *Free fallback* | **NVIDIA + TSMC + Coherent + Lumentum + Broadcom via EDGAR XBRL** | Quarterly revenue trends for all major supply chain nodes, fully automated |

### Pillar 3: Satellite Imagery

| Rank | Source | Justification |
|------|--------|---------------|
| **1** | **Planet Labs (SkySat)** | 50cm at $6/km2 archive. API-first. Best balance of resolution, cost, programmability |
| **2** | **Google Earth Engine + Sentinel-2** | Free. 10m, 5-day revisit. Sufficient for large-scale change detection. Ideal for Phase 1 |
| **3** | **Maxar WorldView Legion** | Best resolution (<30cm) but expensive. Reserve for Phase 3 high-confidence validation |
| *Free fallback* | **GEE + Sentinel-2** | Change detection for large construction sites. "Something is being built" signals |

---

## Phase-1 Minimum Source Set (Northern Virginia)

The following **7 sources** deliver an end-to-end demo for **$0-500/year**:

```
+-------------------------------------------------------+
|           PHASE-1 MINIMUM SOURCE SET ($0-500/yr)       |
+-------------------------------------------------------+
|                                                         |
|  POWER PILLAR                 GPU SUPPLY CHAIN          |
|  ~~~~~~~~~~~~                 ~~~~~~~~~~~~~~~~          |
|  1. SEC EDGAR EFTS+XBRL      5. NVIDIA XBRL  (free)   |
|     (PPA keyword monitor)     6. TSMC XBRL    (free)   |
|     (free)                    + Coherent, Lumentum,     |
|  2. PJM Queue via gridstatus    Broadcom XBRL (free)   |
|     (free, daily API)                                   |
|  3. EIA API (Form 860/860M)  7. SemiAnalysis Newsletter |
|     (free, monthly)             ($500/yr)               |
|  4. OpenStreetMap Overpass                              |
|     (free, facility locations)                          |
|                                                         |
|  SATELLITE                                              |
|  ~~~~~~~~~                                              |
|  8. Google Earth Engine                                 |
|     + Sentinel-2 (free,                                 |
|       10m, 5-day revisit)                               |
|                                                         |
+-------------------------------------------------------+
```

> **Updated cost per 00-DECISIONS-AND-CONSTRAINTS.md:** Phase 1 operational cost = Shovels.ai $599/mo + Financial Modeling Prep $29-99/mo = **$628-698/mo**. All other sources $0.

### What Phase-1 Delivers

| Triangulation Layer | Signal | Phase-1 Source | Confidence |
|---------------------|--------|----------------|------------|
| **L1** Contracted power | GW per company/geo | EDGAR EFTS keyword search + curated_deals.py | Medium (NLP extraction from filings) |
| **L2** Estimated GPUs | Power-draw inference | NVIDIA XBRL datacenter revenue -> unit estimates | Medium (revenue-to-unit assumptions) |
| **L3** NIC+optics validation | Deployment proxy | Coherent + Lumentum + Broadcom XBRL | Low-Medium (revenue only, no units) |
| **L4** County permits | Construction ground truth | PJM Queue + EIA + OSM | Medium (supply-side, not permit-specific) |

### Phase-1 Gaps (resolved by paid sources)

| Gap | Resolved by | Est. Cost |
|-----|-------------|-----------|
| No direct datacenter permit data | Shovels.ai | $599/mo |
| No structured datacenter inventory | Aterio | $10-50K/yr |
| No high-res satellite imagery | Planet Labs SkySat | $1-10K (area-dependent) |
| No SKU-level GPU shipment data | SemiAnalysis institutional | $25-100K/yr |

---

## Architectural Recommendations

The architect agent has produced detailed specifications (see `docs/planning/03-PIPELINE-ARCHITECTURE.md`; the earlier draft `DATA_INGESTION_ARCHITECTURE.md` is archived under `docs/_archive/`). Key decisions:

### Adapter Interface Pattern

Every data source implements a `DataSourceAdapter` with four async methods:

```python
class DataSourceAdapter(ABC):
    @abstractmethod
    async def get_metadata(self) -> SourceMetadata:
        """Static registration info: name, pillar, cadence, cost tier"""

    @abstractmethod
    async def fetch(self, since: datetime | None = None) -> list[RawRecord]:
        """Pull raw data incrementally (only new since last run)"""

    @abstractmethod
    async def normalize(self, raw: list[RawRecord]) -> list[IngestedRecord]:
        """Transform to canonical IngestedRecord with SourceLineage attached"""

    @abstractmethod
    async def validate(self, records: list[IngestedRecord]) -> list[IngestedRecord]:
        """Deduplicate and filter low-confidence records"""
```

Every `IngestedRecord` carries a `SourceLineage`:
```python
class SourceLineage(BaseModel):
    source_url: str
    retrieved_at: datetime
    parser_version: str
    confidence: float       # 0.0-1.0, backed by parsing certainty
    raw_hash: str           # SHA-256 of raw response
```

### Source Registry (YAML-driven)

```yaml
pillars:
  power:
    sources:
      - name: pjm_queue
        adapter: PJMQueueAdapter
        active: true
        tier: free
        cron: "0 6 * * *"          # daily 6 AM
      - name: shovels
        adapter: ShovelsAdapter
        active: false               # activate after procurement
        tier: paid
        cron: "0 0 * * 1"          # weekly Monday midnight
        fallback_for: county_permits
  gpu_supply:
    sources:
      - name: nvidia_xbrl
        adapter: EdgarXBRLAdapter
        active: true
        tier: free
        config:
          cik: "0001045810"
          segments: ["Datacenter"]
```

Swapping sources is a YAML change, not a code change. If a paid source fails, the registry automatically falls back to the first registered free-tier source for that pillar.

### Cadence Management

| Source Type | Schedule | Mechanism |
|-------------|----------|-----------|
| Permits | Weekly (Monday 00:00) | APScheduler cron |
| EDGAR filings | Poll RSS every 15 min | APScheduler interval |
| Earnings transcripts | Daily calendar check | APScheduler cron |
| Satellite imagery | Weekly (Sunday 00:00) | APScheduler cron |
| NVIDIA/TSMC/etc XBRL | Quarterly (post-filing trigger) | Event from EDGAR RSS |

### Phase-1 Database (PostgreSQL)

Three tables: `data_sources`, `ingestion_runs`, `ingested_records` with lineage fields denormalized for query performance. Payload is JSONB. Phase 1 uses **PostgreSQL + SQLModel** (self-hosted on this OCI VM per Decision #1). No SQLite phase.

### Cost Optimization

- **Incremental fetch:** Only new data since last `ingestion_run`
- **SHA-256 dedup:** Never store identical raw content twice
- **Immutable caching:** Earnings transcripts fetched once per quarter
- **EDGAR RSS polling:** Avoids scanning all CIKs on every run
- Phase 1 operates at **$0 API cost** (all free sources)

---

## Procurement Actions

### Immediate (This Week -- No Approvals Needed)

| Action | Source | Timeline | Cost |
|--------|--------|----------|------|
| Register PJM Tools account | PJM | 1 day | Free |
| Register EIA API key | EIA | Immediate | Free |
| Set up Google Earth Engine project | GEE | 1 day | Free |
| Configure EDGAR EFTS polling for PPA keywords | EDGAR | 1 day | Free |
| Run Overpass query for NoVA datacenters | OSM | 1 hour | Free |

### This Month (Team Budget)

| Action | Source | Timeline | Est. Cost | Approval |
|--------|--------|----------|-----------|----------|
| Subscribe SemiAnalysis newsletter | SemiAnalysis | 1 day | $500/yr | Team budget |
| Request CleanView API beta access | CleanView | 1-2 weeks | TBD (beta) | None |
| Request Aterio demo + pricing | Aterio | 2 weeks | $10-50K/yr | Budget + vendor |
| Request Shovels.ai trial | Shovels.ai | 1 week | $599/mo | Team budget |
| Get Planet Labs quote for NoVA AOI | Planet Labs | 2 weeks | $1-10K | Budget |

### Phase 2 (Director+ Approval)

| Action | Source | Timeline | Est. Cost | Approval |
|--------|--------|----------|-----------|----------|
| SemiAnalysis institutional subscription | SemiAnalysis | 2 weeks | $25-100K/yr | Director |
| Maxar SecureWatch evaluation | Maxar | 4 weeks | $50K+/yr | VP |

---

## Appendix: Key API Endpoints Reference

```
# SEC EDGAR EFTS (Full-Text Search)
GET https://efts.sec.gov/LATEST/search-index?q="power+purchase+agreement"&forms=8-K,10-K&startdt=2025-01-01
Header: User-Agent: OCI-StratInsights contact@oracle.com

# SEC EDGAR XBRL (Company Financials)
GET https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json   # NVIDIA
GET https://data.sec.gov/api/xbrl/companyfacts/CIK0001046179.json   # TSMC
GET https://data.sec.gov/api/xbrl/companyfacts/CIK0000820318.json   # Coherent
GET https://data.sec.gov/api/xbrl/companyfacts/CIK0001633978.json   # Lumentum
GET https://data.sec.gov/api/xbrl/companyfacts/CIK0001730168.json   # Broadcom

# PJM Interconnection Queue
GET https://apiportal.pjm.com/api/interconnection-queue?state=VA
# or: pip install gridstatus && gridstatus.PJM().get_interconnection_queue()

# EIA API v2
GET https://api.eia.gov/v2/electricity/facility-fuel/data?api_key=KEY&facets[state][]=VA

# OpenStreetMap Overpass (NoVA bounding box)
POST https://overpass-api.de/api/interpreter
body: [out:json];node["building"="data_centre"](38.8,-77.6,39.1,-77.0);out;

# Shovels.ai (after procurement)
GET https://api.shovels.ai/v2/permits/search?state=VA&county=loudoun&description=data+center

# Sentinel-2 via Copernicus
https://dataspace.copernicus.eu/

# Google Earth Engine
https://code.earthengine.google.com/
```

---

*This report should be reviewed with Karan to prioritize procurement decisions. The Phase-1 free stack is sufficient for a working demo; the paid stack is required for production-grade intelligence.*

---

## Conformance to 00-DECISIONS-AND-CONSTRAINTS.md

- **§1 Decisions:** Postgres self-hosted (not SQLite), SEC EDGAR REST APIs per §4, OCI included, deploy on OCI VM, no auth v1.
- **§3 Datasets:** Aterio CSV/xlsx files referenced in §1.5 and Phase-1 scope.
- **§4 EDGAR APIs:** Full endpoint set (submissions, companyfacts, companyconcept, frames, bulk ZIPs, EFTS) referenced in §1.1.
- **§5 UX Rule:** Additive only — not directly applicable to this research doc.
