# 02 -- Technology Stack Research: Data-Source Pipeline

**Author:** Research Agent | **Date:** 2026-04-28 | **Status:** Draft v1.0
**Scope:** Technology assessment for replacing mock data with real ingestion pipelines across all pillars of the Datacenter & Power Intelligence Platform.

---

## Table of Contents

1. [SEC EDGAR Ingestion](#1-sec-edgar-ingestion)
2. [County Building Permits](#2-county-building-permits)
3. [Earnings Transcripts](#3-earnings-transcripts)
4. [Satellite Imagery](#4-satellite-imagery)
5. [Data Storage & Lineage](#5-data-storage--lineage)
6. [Entity Resolution](#6-entity-resolution)
7. [Scheduling & Orchestration](#7-scheduling--orchestration)
8. [Summary Decision Matrix](#8-summary-decision-matrix)

---

## 1. SEC EDGAR Ingestion

### Current State

The existing `backend/agents/edgar_agent.py` has significant technical debt:
- **Blocking sync I/O**: Uses `urllib.request` inside a FastAPI async app, blocking the event loop on every SEC request.
- **Regex-only parsing**: Extracts MW/GW figures with a single regex; no structured XBRL parsing.
- **Silent exception swallowing**: `except Exception: return []` / `continue` with no logging. Failures are invisible.
- **12-hour file cache**: JSON files on disk with mtime-based TTL. No cache invalidation, no concurrency safety.
- **Hardcoded company lists**: CIK numbers inline; no config-driven entity management.

### Options Considered

#### Option A: edgartools (Recommended)

**What it is:** The most popular Python library for SEC EDGAR (2.3M+ downloads, 1,800+ GitHub stars). Provides typed Python objects for 17+ filing types including 10-K, 10-Q, and 8-K. Built-in XBRL parsing via `filing.xbrl()` that returns structured financial statements as pandas DataFrames.

| Attribute | Detail |
|-----------|--------|
| License | MIT |
| Cost | Free, no API key required |
| XBRL support | Yes -- `xb.statements.balance_sheet()`, income statement, cash flow, multi-period via `XBRLS` |
| Filing search | By company, form type, date range; full-text search via EFTS |
| Rate limiting | Respects SEC 10 req/s automatically |
| Async | No native async, but lightweight enough to run in `asyncio.to_thread()` |
| Active dev | Yes, accepted into Anthropic's Claude for Open Source program |

**Pros:**
- Replaces 100+ lines of our custom urllib/regex code with a few method calls.
- XBRL parsing built in -- no separate library needed for structured financial data.
- Returns Python objects, not raw HTML; e.g., `filing.items` gives 8-K item codes directly.
- Multi-period analysis: compare financials across quarters with `XBRLS.from_filings()`.
- Well-documented: https://edgartools.readthedocs.io/

**Cons:**
- Synchronous internally (wraps `httpx` sync client). Must wrap in `asyncio.to_thread()` for FastAPI.
- Adds a dependency (~15 transitive packages including pandas).
- For niche parsing (e.g., extracting MW from 8-K narrative text), we still need our own keyword/regex logic on top.

**Docs:** https://edgartools.readthedocs.io/en/latest/ | https://github.com/dgunning/edgartools

#### Option B: sec-api.io (Commercial)

**What it is:** Hosted SaaS API providing 500+ EDGAR form types, full-text search, XBRL-to-JSON converter, real-time streaming, and 8-K/10-K/10-Q section extractors.

| Plan | Cost | Rate Limits | Notes |
|------|------|-------------|-------|
| Free | $0 | 100 calls total (lifetime) | Evaluation only |
| Personal | $49/mo ($55 monthly) | 20 req/s query, 10 req/s extractor | 50 GB/mo |
| Business | $199/mo ($239 monthly) | 40 req/s query, 20 req/s extractor | 100 GB/mo |
| Enterprise | Custom | Custom | Negotiated |

**Pros:**
- Fully managed; no parsing code to maintain.
- 8-K section extractor returns clean text for specific items (e.g., Item 1.01 Material Agreements).
- Real-time WebSocket stream for new filings -- useful for alerting.
- XBRL-to-JSON endpoint eliminates need for any XBRL library.

**Cons:**
- Ongoing cost: $588-$2,388/year for the team.
- External dependency; outage = our pipeline stops.
- 100-call lifetime free tier is useless for development.
- Vendor lock-in on a core data source that SEC provides free.

**Docs:** https://sec-api.io/docs

#### Option C: Direct SEC EDGAR APIs + Custom Parsing

**What it is:** Use SEC's free public APIs directly:
- **Submissions API:** `https://data.sec.gov/submissions/CIK{cik}.json` (what we do today)
- **EFTS Full-Text Search:** `https://efts.sec.gov/LATEST/search-index` -- search all filings since 2001 by keyword, exact phrase, form type, date range. Free, no auth, JSON response.
- **XBRL Companion API:** `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` -- all XBRL facts for a company as JSON.

**Pros:**
- Zero cost, zero vendor dependency.
- EFTS is powerful: search for `"power purchase agreement"` across all 8-K filings instantly.
- XBRL companion API returns structured facts without parsing XML.

**Cons:**
- Rate limited to 10 req/s (shared across all SEC APIs). Must implement throttling.
- No section extraction; get raw HTML, must parse ourselves.
- XBRL companion API only has standardized GAAP concepts, not narrative text.
- Significant development effort to build what edgartools already provides.

**Docs:** https://www.sec.gov/search-filings/edgar-application-programming-interfaces

### Async HTTP Client Decision

For any HTTP calls we make ourselves (SEC or otherwise):

| Library | Async | HTTP/2 | Sync+Async | Performance | Verdict |
|---------|-------|--------|------------|-------------|---------|
| **httpx** | Yes | Yes | Both modes | Good | **Recommended** -- already a transitive dep of edgartools; familiar requests-like API |
| aiohttp | Yes | No | Async only | Faster at high concurrency | Overkill for SEC's 10 req/s limit |
| urllib (current) | No | No | Sync only | N/A | Must replace |

**Decision:** Use `httpx.AsyncClient` for all new HTTP calls. For edgartools calls (which are sync internally), wrap in `asyncio.to_thread()`.

### Recommendation for Phase 1

**Use edgartools as primary EDGAR library.** It eliminates the need for custom submission fetching, XBRL parsing, and filing search. Supplement with:
- SEC EFTS API for full-text keyword search (e.g., find all 8-Ks mentioning "data center" + "power purchase").
- Our existing regex logic (refined) for extracting MW/GW from narrative 8-K text, since that is domain-specific and no library handles it.
- `httpx.AsyncClient` for any direct HTTP calls.
- Structured logging (`structlog`) to replace all silent `except` blocks.

**Estimated effort:** 3-4 days to replace `edgar_agent.py` with edgartools-based implementation.

> **Full EDGAR endpoint set (§4 of 00-DECISIONS-AND-CONSTRAINTS.md):** `data.sec.gov/submissions/CIK##########.json` (filing history), `data.sec.gov/api/xbrl/companyfacts/CIK##########.json` (all XBRL facts), `data.sec.gov/api/xbrl/companyconcept/` (single concept time series), `data.sec.gov/api/xbrl/frames/us-gaap/<concept>/USD/CY####Q#.json` (cross-company quarterly -- use for hyperscaler capex/PP&E side-by-side), `efts.sec.gov/LATEST/search-index` (full-text PPA/datacenter keyword search across 8-Ks), nightly bulk ZIPs (`companyfacts.zip`, `submissions.zip`) for cold-start backfill at 03:00 ET. Rate limit: 10 req/s. No CORS -- backend-only. User-Agent required.

---

## 2. County Building Permits

### Target Geography

**Phase 1 is national** (all 50 US states + DC) per `00-DECISIONS-AND-CONSTRAINTS.md` §5.2. Free state-API coverage in v1: **VA, NY, WA, CO, OR, TX** (datacenter NAICS / keyword-filtered). Other 44 states render `<NoStateCoverage />` per §5.3 until either Shovels.ai is licensed (Phase 2) or per-state Socrata adapters are added.

**Highest-density datacenter counties** the team should validate ingest against (in the covered states):
- **Loudoun County, VA** -- the heart of "Data Center Alley"; AWS, Equinix, Microsoft, Google, Oracle.
- **Prince William County, VA** -- rapidly growing corridor south of Loudoun.
- **Fairfax County, VA** -- adjacent; primarily colocation.
- **Hillsboro / Washington County, OR** -- Intel-anchored corridor; AWS expansion.
- **Quincy, WA** -- Microsoft Azure region.
- **Dallas-Fort Worth, TX** -- multi-hyperscaler.
- **Manhattan / Westchester / Long Island, NY** -- legacy + new builds.
- **Denver / Boulder, CO** -- growing.

### Options Considered

#### Option A: Shovels.ai (Recommended for Phase 1)

**What it is:** AI-enriched building permit and contractor database covering 1,800+ US jurisdictions, 180M+ permits, 85% of US population.

| Attribute | Detail |
|-----------|--------|
| Coverage | 1,800+ jurisdictions; ~85% US population. Virginia counties likely covered given population density. Must verify Loudoun/PWC/Fairfax coverage via their geo endpoint. |
| Data freshness | Updated 1st and 15th of each month (bi-monthly). Meets our weekly target with 1-2 week lag. |
| API capabilities | Search by address, zip, city, county, jurisdiction via `geo_id` system. Filter by permit type, date, contractor. Returns standardized JSON. |
| Pricing | Starts at **$599/mo** for API access (~$7,200/yr). Free tier: 250 API calls. Enterprise: custom. |
| Rate limits | 10K+ calls/month on standard plan |
| Enrichment | AI-classified permit types, contractor quality scores, inspection pass rates |

**Pros:**
- Standardized data across jurisdictions -- no need to parse each county's unique portal format.
- AI enrichment classifies permit types (construction, electrical, grading, HVAC) which aligns with our needs.
- REST API with JSON responses; straightforward integration.
- Contractor profiles could help identify which firms are building for which hyperscalers.

**Cons:**
- $599/mo is real money for a prototype; requires procurement approval (open question from PRD).
- Bi-monthly refresh may miss permits filed in the last 1-2 weeks.
- Coverage of specific NoVA counties must be verified before committing. Loudoun is likely covered; smaller jurisdictions may have gaps.
- No real-time streaming; must poll.

**Verification needed before procurement:** Call Shovels API geography endpoint to confirm Loudoun County (FIPS 51107), Prince William County (FIPS 51153), and Fairfax County (FIPS 51059) are in their coverage. The 250 free API calls should be sufficient for this test.

**Docs:** https://docs.shovels.ai/ | https://shovels.redoc.ly/

#### Option B: Direct County Portal Scraping (Fallback)

Each NoVA county has its own permit portal:

| County | Portal | Format | Scrapability |
|--------|--------|--------|-------------|
| **Loudoun** | LandMARC system (`loudoun.gov/5823`) + issued permit PDF reports (`loudoun.gov/1164`) + Virginia Open Data Portal CSV (`data.virginia.gov`) | HTML portal + PDF monthly reports + CSV on state portal | Medium. LandMARC is a web app (likely Accela-based). Monthly PDFs are scrapable. State open data CSV is the easiest path. |
| **Prince William** | ePortal (`eservice.pwcgov.org`) integrated with GIS | HTML web app (Accela-based) | Medium. Accela Citizen Access portals are searchable but paginated; no public API. |
| **Fairfax** | PLUS Portal (`plus.fairfaxcounty.gov/CitizenAccess`) | Accela Citizen Access | Medium. Same Accela platform as PWC. Searchable by address/permit number. |
| **Statewide** | Virginia Permit Transparency (`permits.virginia.gov/Permit/Search`) | HTML search, updated daily by agencies | Best single source; aggregates across all VA localities. |

**Pros:**
- Free. No vendor cost.
- Virginia Permit Transparency aggregates daily updates from all VA localities.
- Direct access to raw permit records; no intermediary.

**Cons:**
- Each portal has different structure; must build and maintain 3-4 scrapers.
- Accela portals are anti-scraping (session tokens, pagination, CAPTCHA possible).
- No standardized permit classification; must parse free-text descriptions.
- Virginia Permit Transparency is the most promising single source but may not have all permit types.
- Ongoing maintenance burden as portals change.

**Docs:**
- Loudoun: https://www.loudoun.gov/5823/LandMARC-Land-Management-Applications-Re
- Loudoun issued reports: https://www.loudoun.gov/1164/Issued-Building-Permit-Reports
- VA Open Data: https://data.virginia.gov/dataset/building-permits-applications-2024
- PWC ePortal: https://www.pwcva.gov/department/development-services/eportal-access
- Fairfax PLUS: https://plus.fairfaxcounty.gov/CitizenAccess/Cap/CapHome.aspx?module=Building
- VA Permit Transparency: https://permits.virginia.gov/Permit/Search

#### Option C: Hybrid (Shovels + State Open Data)

Use Shovels for standardized, enriched data as primary source. Supplement with Virginia Open Data Portal CSVs (free, published by the state) for cross-validation and gap-filling. This gives us vendor data quality with a free fallback.

### Recommendation for Phase 1

**Start with Shovels.ai** if procurement approves ($599/mo). It provides the fastest path to structured permit data across all three target counties. Before committing:

1. Use 250 free API calls to verify Loudoun/PWC/Fairfax coverage.
2. Check that their permit type taxonomy captures datacenter-relevant categories (commercial construction, electrical, grading).
3. Confirm data freshness for these specific counties.

**If Shovels is not approved or coverage is insufficient:** Fall back to Virginia Permit Transparency (`permits.virginia.gov`) as primary source + Loudoun's monthly issued permit PDF reports. This is free but requires building a scraper (estimate: 2-3 days for VA Permit Transparency, 1 day per county portal).

**Cadence:** Weekly ingestion job. Shovels data refreshes bi-monthly; we poll weekly and diff against stored records.

---

## 3. Earnings Transcripts

### Target Companies

| Company | Relevance | Filing entity |
|---------|-----------|---------------|
| NVIDIA | GPU shipments, datacenter revenue, supply constraints | NVDA (10-K, 10-Q, earnings calls) |
| TSMC | CoWoS packaging capacity, utilization rates, capex guidance | TSM (20-F, 6-K; listed on NYSE as ADR) |
| Broadcom | NIC shipments (networking segment), AI revenue | AVGO |
| Coherent | Optical transceiver shipments (800G/400G) | COHR |
| Lumentum | Optical transceiver shipments | LITE |

### Options Considered

#### Option A: Financial Modeling Prep (FMP) (Recommended)

**What it is:** REST API providing earnings call transcripts, financial statements, and market data for 17,000+ tickers with 30+ years of history.

| Attribute | Detail |
|-----------|--------|
| Transcript coverage | Full earnings call transcripts; searchable by ticker + quarter |
| Pricing | Starter: ~$29/mo (300 calls/min, 5yr history). Ultimate: ~$99/mo (3,000 calls/min, global, full transcripts). Exact 2026 prices require checking site. |
| Format | JSON with full transcript text, speaker labels, Q&A sections |
| Python SDK | Available; simple REST calls with API key |
| Freshness | Transcripts available within hours of earnings call |

**Pros:**
- Clean JSON API with speaker-tagged transcript segments.
- Covers all five target companies including TSMC (NYSE ADR).
- Affordable for a prototype ($29-$99/mo).
- Also provides financial statements, reducing need for separate XBRL parsing for some use cases.
- Straightforward: `GET /api/v3/earning_call_transcript/NVDA?quarter=1&year=2026`

**Cons:**
- Third-party data; transcripts may have minor transcription errors.
- Rate limits on lower tiers may slow batch processing.
- Not free; ongoing cost.

**Docs:** https://site.financialmodelingprep.com/developer/docs/stable/earnings-transcript-list

#### Option B: SEC EDGAR Direct (10-Q/10-K only)

**What it is:** Extract quantitative data from SEC filings (10-K, 10-Q) using edgartools XBRL parsing. Does NOT include earnings call transcripts (which are not filed with the SEC), but captures the structured financial data.

**Pros:**
- Free. Already planned for EDGAR integration (Section 1).
- XBRL data is machine-readable and authoritative.
- Revenue by segment, capex, inventory -- all available in structured form.

**Cons:**
- No earnings call transcripts. Management commentary, forward guidance, and color on supply constraints only appear in transcripts.
- 10-Q filings lag 30-45 days after quarter end. Earnings calls happen within weeks.
- TSMC files 20-F/6-K with different XBRL taxonomy.

#### Option C: FinancialDatasets.ai

**What it is:** Primary-source SEC data provider with REST API covering 17,000+ tickers. Offers financial statements, earnings data, and transcripts.

| Attribute | Detail |
|-----------|--------|
| Coverage | US tickers; 30+ years history |
| Pricing | Not fully public; appears to have free and paid tiers |
| Unique feature | MCP server for Claude integration |
| Format | Structured JSON |

**Pros:**
- Clean REST API; MCP integration for AI analysis.
- Primary-source SEC data (parsed, not scraped).

**Cons:**
- Less established than FMP; smaller community.
- Pricing transparency unclear.
- Transcript coverage breadth unconfirmed for our specific tickers.

**Docs:** https://docs.financialdatasets.ai/introduction

#### Option D: Alpha Vantage

**What it is:** Financial data API with an "Alpha Intelligence" suite including earnings transcripts.

| Attribute | Detail |
|-----------|--------|
| Free tier | 25 requests/day |
| Premium | From $49.99/mo |
| Transcripts | Part of Alpha Intelligence (likely premium only) |

**Cons:** Free tier too limited. Transcript access may require premium. Less focused on transcripts than FMP.

### NLP Extraction from Transcripts

Regardless of source, we need to extract structured metrics from free-text transcripts. Approaches:

| Approach | Tool | Effort | Accuracy |
|----------|------|--------|----------|
| **Regex + keyword** | Python `re` | Low (1-2 days) | Medium -- brittle on phrasing variations |
| **LLM extraction** | OCI Llama Stack (`gpt-5.4-mini`) with structured JSON output | Low (1 day) | High -- handles paraphrasing, context; no API key needed (instance principal). |
| **spaCy NER + rules** | spaCy with custom NER model | High (1-2 weeks training) | High once trained, but expensive to build |

**Recommendation:** Use **LLM-based extraction via OCI Llama Stack** (`oci/openai.gpt-5.4-mini`, structured JSON output, see `00-DECISIONS-AND-CONSTRAINTS.md` §4.2). Provide the transcript text with a prompt specifying the exact metrics to extract (datacenter revenue, GPU units shipped, capex guidance, capacity MW, CoWoS wafer starts, etc.). Fast to implement, handles the diversity of how executives describe these metrics, no API key or cost since Llama Stack is internal infra.

### Recommendation for Phase 1

**Use Financial Modeling Prep** for earnings transcripts (~$29-$99/mo). Combine with:
- **edgartools XBRL parsing** for structured financial statement data from 10-K/10-Q filings (free).
- **LLM extraction** via OCI Llama Stack (`oci/openai.gpt-5.4-mini`) to pull structured metrics from transcript text.

**Cadence:** Event-driven. Trigger ingestion within 72 hours of each company's earnings call (5 companies x 4 quarters = 20 ingestion events per year).

---

## 4. Satellite Imagery

### Use Case

Monitor ~20 datacenter construction sites for progress. Detect: ground clearing, foundation work, steel erection, roof completion, parking lot paving. Compare against permit timelines and announced schedules.

### Options Considered

#### Option A: Planet Labs PlanetScope Monitoring

**What it is:** Daily 3m resolution optical imagery from 200+ satellites. Covers the entire Earth's landmass daily.

| Attribute | Detail |
|-----------|--------|
| Resolution | 3m (PlanetScope), 50cm (SkySat on-demand) |
| Revisit | Daily (PlanetScope); on-demand (SkySat) |
| Coverage | Global; NoVA fully covered |
| API | RESTful; search, order, download. Basemaps API for time-series mosaics. |
| Pricing (PlanetScope) | Monitoring subscriptions in 50/150/300 km2 packages; price not public, must contact sales. Estimated $5,000-$15,000/yr for monitoring 20 sites. |
| Pricing (SkySat) | Archive: $6/km2; Flexible Tasking: $12/km2; Assured Tasking: $40/km2 |
| Change detection | Planet Analytics (Basemaps change detection) available as add-on |
| Minimum AOI | 0.01 km2 (1 hectare) per subscription |

**Pros:**
- Daily imagery means we can detect changes within days of occurrence.
- 3m resolution adequate for large-scale construction phases (clearing, structure erection).
- Basemaps provide pre-processed, analysis-ready mosaics.
- Well-documented API with Python SDK.

**Cons:**
- 3m resolution may not distinguish fine-grained construction phases (e.g., MEP fit-out).
- Pricing requires sales contact; likely $5K-$15K/yr.
- Cloud cover can block optical imagery (relevant for NoVA in winter).

**Docs:** https://www.planet.com/products/ | https://developers.planet.com/docs/apis/

#### Option B: Maxar (MGP Pro, formerly SecureWatch)

**What it is:** 30cm resolution satellite imagery from WorldView constellation. 125+ petabytes of archive imagery. FedRAMP authorized.

| Attribute | Detail |
|-----------|--------|
| Resolution | 30cm (highest commercial resolution available) |
| Archive | 125+ PB; global coverage at 50cm or better |
| Revisit | Not daily; depends on tasking and constellation geometry |
| API | RESTful; OGC WMS/WMTS standards |
| Pricing | GB-based annual subscription; not public. Estimated $10,000-$50,000/yr for commercial use. |
| New collection | 3.8M km2/day of new imagery globally |

**Pros:**
- 30cm resolution can distinguish individual buildings, equipment staging, parking lots.
- Massive archive for historical change analysis.
- FedRAMP authorized (relevant if this grows into a classified program).

**Cons:**
- Significantly more expensive than Planet.
- Not daily revisit; may miss rapid construction changes.
- Enterprise-grade tool; complex procurement.
- Overkill for Phase 1 where we need change detection, not building-level detail.

**Docs:** https://www.maxar.com/products/securewatch

#### Option C: Sentinel-2 (Free)

**What it is:** ESA's Copernicus program. Free, open-access multispectral imagery at 10m resolution with 5-day revisit.

| Attribute | Detail |
|-----------|--------|
| Resolution | 10m (bands 2,3,4,8); 20m (other bands) |
| Revisit | 5 days (2 satellites combined) |
| Cost | Free |
| API | Copernicus Data Space Ecosystem; also available via Google Earth Engine |
| Cloud cover | Optical; same limitation as Planet |

**Research findings on 10m for construction detection:**
- Academic studies show 10m resolution can detect large-scale construction events (land clearing, major structural changes) with ~90% spatial accuracy.
- Start/end date detection accuracy is lower: 68.8% for start, 54.9% for end.
- Super-resolution techniques can enhance to ~5m effective resolution using multiple passes.
- Cannot distinguish individual buildings or fine-grained construction phases.

**Pros:**
- Free. Zero cost.
- 5-day revisit is adequate for weekly monitoring cadence.
- Google Earth Engine provides free processing and analysis tools.
- Adequate for detecting "is this a large construction site or not" -- binary signal.

**Cons:**
- 10m resolution too coarse for distinguishing construction phases.
- Cannot see individual buildings at datacenter scale (a 100-acre site is visible, but not which building is under construction).
- No commercial API support or SLA.
- Requires own change detection pipeline (or Earth Engine scripts).

**Docs:** https://dataspace.copernicus.eu/ | https://earthengine.google.com/

### Cost Comparison: Monitoring ~20 Sites

| Provider | Resolution | Revisit | Estimated Annual Cost | Phase 1 Fit |
|----------|------------|---------|----------------------|-------------|
| Sentinel-2 | 10m | 5 days | **$0** | Adequate for binary change detection |
| Planet PlanetScope | 3m | Daily | **$5,000-$15,000** | Good for construction phase tracking |
| Planet SkySat (archive) | 50cm | On-demand | **$1,200-$6,000** (based on ~200-1000 km2 of archive pulls) | Good for spot-checks |
| Maxar MGP Pro | 30cm | Variable | **$10,000-$50,000** | Overkill for Phase 1 |

### Recommendation for Phase 1

**Start with Sentinel-2 (free) for proof of concept.** Use Google Earth Engine to set up a change detection pipeline over the 20 known sites. This gives us a binary "construction activity detected" signal at zero cost.

**Phase 2 upgrade path:** Add Planet Labs PlanetScope monitoring for the top 5-10 highest-priority sites where we need construction phase granularity. Use SkySat archive pulls ($6/km2) for periodic high-resolution spot-checks.

**Do not pursue Maxar in Phase 1.** The cost and complexity are not justified until the platform is proven.

---

## 5. Data Storage & Lineage

### Requirements

- Store ingested data from 5+ sources (EDGAR, permits, transcripts, satellite, curated deals).
- Every record carries: source URL, retrieved-at timestamp, parser version, confidence score.
- Support lineage queries: "where did this number come from?"
- Store raw artifacts (HTML filings, transcript JSON, satellite GeoTIFFs).
- Team of 2-3 engineers; minimize ops overhead.

### Options Considered

#### Option A: PostgreSQL + JSONB (Recommended)

**What it is:** PostgreSQL with JSONB columns for semi-structured data, plus standard relational tables for structured entities.

| Attribute | Detail |
|-----------|--------|
| Structured data | Relational tables: `companies`, `filings`, `permits`, `transcripts`, `metrics` |
| Semi-structured | JSONB columns for raw parsed data, variable-schema source records |
| Lineage | Dedicated `data_lineage` table: `(metric_id, source_type, source_url, retrieved_at, parser_version, confidence, raw_artifact_path)` |
| Blob storage | Raw artifacts (HTML, JSON, GeoTIFF) on local filesystem or OCI Object Storage; path stored in DB |
| Hosting | Single PostgreSQL instance (local Docker for dev, OCI DB for prod) |

**Pros:**
- Mature, battle-tested. Team likely already knows it.
- JSONB gives NoSQL flexibility within a relational DB; supports GIN indexes for fast queries.
- PostGIS extension available if we need geospatial queries later.
- Rich ecosystem: Alembic for migrations, SQLAlchemy for ORM, `asyncpg` for async access from FastAPI.
- Single database for both OLTP (writes from ingestion) and simple OLAP (dashboard queries).

**Cons:**
- Requires running/managing a PostgreSQL instance (Docker Compose for dev, managed service for prod).
- Not optimized for analytical queries over large datasets (millions of rows). Adequate for Phase 1 scale.
- JSONB queries can be slower than dedicated document stores for complex nested queries.

#### Option B: SQLite (Simplest)

**What it is:** Embedded file-based SQL database. Zero configuration, zero server.

**Pros:**
- Zero ops. Single file. Ships with Python.
- Fast for small datasets (<100K rows).
- Easy to version control (copy the file).

**Cons:**
- Single writer at a time; concurrent ingestion jobs will conflict.
- No JSONB (has JSON functions, but limited indexing).
- No PostGIS equivalent for geospatial.
- Will need to migrate to PostgreSQL eventually; doing it now avoids the migration cost later.
- Not suitable if multiple FastAPI workers need to write simultaneously.

#### Option C: DuckDB (Analytics-Optimized)

**What it is:** Embedded columnar OLAP database. Excellent for analytical queries, Parquet/CSV ingestion, and pandas integration.

**Pros:**
- Blazing fast for analytical queries (aggregations, joins over time-series data).
- Reads Parquet, CSV, JSON natively; great for batch ingestion pipelines.
- Embedded; no server to manage.
- Can query PostgreSQL tables directly via `postgres` extension.

**Cons:**
- Not designed for concurrent writes (single writer).
- Not a good fit for OLTP workloads (serving API requests with frequent small reads/writes).
- Weaker JSONB support compared to PostgreSQL.
- Better as an analytics layer on top of PostgreSQL, not as a replacement.

### Data Lineage Approach

| Approach | Complexity | Phase 1 Fit |
|----------|-----------|-------------|
| **Simple metadata table** | Low | Yes -- `data_lineage` table with FK to source record, source URL, timestamp, parser version, confidence. Every API response includes lineage fields. |
| **Dedicated lineage tool** (e.g., OpenLineage, Marquez, DataHub) | High | No -- massive overkill for a small team. These are designed for enterprise data lakes with 100+ pipelines. |
| **Embedded in record** | Lowest | Partial -- store lineage fields directly on each record. Simpler but harder to query across sources. |

### Blob/Artifact Storage

| Option | Phase 1 Cost | Notes |
|--------|-------------|-------|
| **Local filesystem** (`/data/raw/`) | $0 | Fine for dev. Organize by `{source}/{date}/{filename}`. |
| **OCI Object Storage** | ~$0.02/GB/mo | Use for prod. Durable, versioned, accessible from anywhere. Estimated <$5/mo for Phase 1 volume. |
| **S3** | ~$0.023/GB/mo | If not on OCI infra. |

### Recommendation for Phase 1

**PostgreSQL + JSONB** with a simple `data_lineage` metadata table. Schema:

- `companies` -- canonical company entities with CIK, ticker, aliases
- `filings` -- EDGAR filings with parsed metrics + JSONB for raw parsed data
- `permits` -- building permits with standardized fields
- `transcript_metrics` -- structured metrics extracted from earnings calls
- `satellite_observations` -- change detection results per site
- `data_lineage` -- links any metric to its source URL, retrieval timestamp, parser version, confidence
- `raw_artifacts` -- path to stored raw files (local FS for dev, OCI Object Storage for prod)

Use `asyncpg` + SQLAlchemy async for FastAPI integration. Use Alembic for schema migrations from day one.

**Skip SQLite** -- the concurrent write limitation will bite us immediately with multiple ingestion jobs. **Consider DuckDB** as an optional analytics layer in Phase 2 for dashboard queries, querying the PostgreSQL tables directly via the `postgres` extension.

---

## 6. Entity Resolution

### Problem

The same company appears differently across sources:
- EDGAR: "MICROSOFT CORPORATION" (CIK 0000789019)
- Permits: "Microsoft Data Center Holdings LLC", "Microsoft Real Estate Holdings"
- Transcripts: "Microsoft", "MSFT"
- Satellite: coordinates only, no company name

We need to map all of these to a canonical company entity.

### Options Considered

#### Option A: rapidfuzz + Manual Alias Table (Recommended)

**What it is:** Use rapidfuzz (MIT-licensed, C++ backend) for fuzzy string matching against a manually curated alias table.

| Attribute | Detail |
|-----------|--------|
| Library | rapidfuzz (MIT license, drop-in replacement for thefuzz/fuzzywuzzy) |
| Performance | Written in C++; orders of magnitude faster than thefuzz (pure Python, GPL) |
| Approach | Maintain a `company_aliases` table: `(alias_text, canonical_company_id, source_context)`. On ingestion, check exact match first, then fuzzy match with threshold (e.g., ratio > 85). |
| Scale | ~50-100 aliases for our 10-15 target companies. Manual curation is feasible. |

**Pros:**
- MIT license (thefuzz is GPL -- problematic for corporate use).
- API-compatible with thefuzz; same `fuzz.ratio()`, `process.extractOne()`.
- For our scale (~15 companies, ~100 aliases), a manual alias table + fuzzy matching is robust and explainable.
- No ML model to train or maintain.
- Fast: handles thousands of comparisons per second.

**Cons:**
- Manual alias table requires curation as new sources are added.
- Fuzzy matching alone cannot resolve ambiguous cases (e.g., "Dominion" -- energy company or datacenter?). Needs context.

**Docs:** https://github.com/rapidfuzz/RapidFuzz | https://rapidfuzz.github.io/RapidFuzz/

#### Option B: spaCy NER + Entity Linking

**What it is:** Use spaCy's named entity recognition to extract company names from text, then link to canonical entities.

**Pros:**
- Handles entity extraction from unstructured text (transcripts, filing narratives).
- Can recognize companies not in our alias table.

**Cons:**
- Overkill for Phase 1 where sources are semi-structured (SEC JSON, permit records).
- NER models need fine-tuning for financial/datacenter domain.
- Adds significant dependency (spaCy models are 50-500MB).

#### Option C: LLM-Based Entity Resolution

**What it is:** Use Claude/GPT to resolve entity names to canonical IDs.

**Pros:**
- Handles any ambiguity; understands context.
- Zero training data needed.

**Cons:**
- API cost per resolution. Unnecessary for structured sources where exact/fuzzy match works.
- Latency: 500ms+ per API call.
- Better reserved for truly ambiguous cases, not routine matching.

### Geo Normalization

For mapping locations to canonical geographic identifiers:

| Approach | Tool | Cost | FIPS Support |
|----------|------|------|-------------|
| **US Census Geocoder** | `censusgeocode` Python library | Free | Yes -- returns state/county/tract FIPS codes |
| Google Maps Geocoding API | `googlemaps` Python library | $5/1000 requests | No native FIPS; must cross-reference |
| Nominatim (OpenStreetMap) | `geopy` Python library | Free (self-hosted or limited public) | No FIPS |

**Recommendation:** Use the **US Census Geocoder** (`censusgeocode` library) for address-to-FIPS resolution. It is free, returns county FIPS codes directly, and handles batch geocoding. For coordinates-to-county lookup (satellite sites), use the Census TIGERweb API which takes lat/lon and returns FIPS codes.

### Recommendation for Phase 1

1. **rapidfuzz** for fuzzy company name matching against a curated alias table.
2. **`company_aliases` table** in PostgreSQL: `(id, alias_text, canonical_company_id, source_type, match_type)`.
3. **US Census Geocoder** (`censusgeocode`) for address-to-FIPS county code resolution.
4. **Manual seed**: Pre-populate aliases for all 15 target companies and their known subsidiaries/LLCs.
5. **Escalation path**: Unresolved entities logged to a review queue for manual curation.

**Estimated effort:** 1-2 days for alias table + matching logic + geocoding integration.

---

## 7. Scheduling & Orchestration

### Requirements

- Run EDGAR ingestion daily (check for new filings).
- Run permit ingestion weekly.
- Run transcript ingestion on-demand (triggered by earnings calendar).
- Run satellite change detection weekly.
- Small team; 2-3 engineers. Must not become an ops burden.
- Single-machine deployment for Phase 1.

### Options Considered

#### Option A: APScheduler (Recommended)

**What it is:** Lightweight in-process Python scheduler. Supports cron, interval, and date triggers. Can persist jobs to a database.

| Attribute | Detail |
|-----------|--------|
| Dependencies | None beyond Python stdlib (optional: SQLAlchemy for job persistence) |
| Broker required | No |
| Worker process | Runs in the FastAPI process or as a separate lightweight process |
| Job persistence | Optional; via SQLAlchemy, Redis, MongoDB, or ZooKeeper |
| Monitoring | Basic; logging-based. No built-in dashboard. |

**Pros:**
- Zero infrastructure. No Redis, no RabbitMQ, no separate worker process needed.
- Can run inside the FastAPI app itself (using `BackgroundScheduler` or `AsyncIOScheduler`).
- Supports cron expressions: `trigger='cron', day_of_week='mon', hour=6` for weekly Monday 6am.
- Job persistence via SQLAlchemy means jobs survive app restarts.
- Perfect for single-machine, small-team prototype.

**Cons:**
- Single process; no distributed execution.
- No built-in retry with exponential backoff (must implement manually).
- No dashboard for monitoring job status (build a simple `/api/jobs/status` endpoint instead).
- If the FastAPI process dies, scheduled jobs stop until restart.

**Docs:** https://pypi.org/project/APScheduler/ | https://apscheduler.readthedocs.io/

#### Option B: Celery + Celery Beat

**What it is:** Distributed task queue with a built-in periodic scheduler (Celery Beat).

**Pros:**
- Distributed; scales to multiple workers.
- Built-in retry, rate limiting, result backend.
- Mature ecosystem; well-documented.
- Celery Beat for periodic tasks, plus ad-hoc task submission.

**Cons:**
- Requires a message broker (Redis or RabbitMQ). That is an additional service to deploy and maintain.
- Significant complexity for a 2-3 person team running a prototype.
- Worker processes, beat process, broker process -- 3 extra processes minimum.
- Configuration-heavy; easy to misconfigure.

**When to adopt:** If Phase 2 requires distributed workers (e.g., processing 100+ companies across multiple machines). Not justified for Phase 1.

#### Option C: Prefect

**What it is:** Modern workflow orchestration platform. DAG-based task definitions with a cloud dashboard.

**Pros:**
- Beautiful dashboard for monitoring flows and tasks.
- Built-in retry, caching, parameter passing.
- Prefect Cloud free tier available.

**Cons:**
- Heavyweight for our use case. Designed for data engineering teams with complex DAGs.
- Learning curve for flow/task decorator patterns.
- Cloud dependency for dashboard (or self-host Prefect server).
- Adds significant abstraction over what is fundamentally "run this function on a schedule."

#### Option D: Simple cron (OS-level)

**Pros:**
- Zero dependencies. Battle-tested for decades.
- Easy to set up: `0 6 * * 1 /usr/bin/python3 /app/scripts/ingest_permits.py`

**Cons:**
- No integration with FastAPI; must run as separate scripts.
- No job history, no retry, no monitoring.
- Hard to manage as job count grows.
- Not portable (Linux-specific).

### Recommendation for Phase 1

**APScheduler with `AsyncIOScheduler`** running inside the FastAPI process. Configuration:

| Job | Schedule | Trigger |
|-----|----------|---------|
| EDGAR filing check | Daily 6:00 AM ET | Cron |
| Permit ingestion | Weekly Monday 7:00 AM ET | Cron |
| Satellite change detection | Weekly Wednesday 6:00 AM ET | Cron |
| Transcript ingestion | On-demand (API trigger) | Date/manual |
| Cache cleanup | Daily midnight | Cron |

Add a `/api/admin/jobs` endpoint that lists scheduled jobs, last run time, last status, and allows manual trigger. Persist job run history to the PostgreSQL `job_runs` table.

**Upgrade path:** If Phase 2 requires distributed workers, migrate to Celery. The ingestion functions themselves are source-agnostic; only the scheduling mechanism changes.

**Estimated effort:** 1 day to integrate APScheduler into FastAPI with job status endpoint.

---

## 8. Summary Decision Matrix

> **These choices are LOCKED per [00-DECISIONS-AND-CONSTRAINTS.md](00-DECISIONS-AND-CONSTRAINTS.md) §2.2.** Comparison tables above are retained for context; the recommendations below are final.

| Area | Phase 1 Choice | Cost | Effort | Key Risk |
|------|---------------|------|--------|----------|
| **EDGAR Ingestion** | edgartools + httpx + EFTS API + **Llama Stack agent for 8-K extraction** (replaces regex) | $0 | 3-4 days | edgartools sync internals; wrap in `to_thread()` |
| **Permits (building)** | 6 free state APIs (VA / NY / WA / CO / OR / TX); Shovels.ai deferred to Phase 2 | $0 | 3-4 days | 44 states render `<NoStateCoverage />`; honest by design |
| **Permits (generator/air)** | EPA ECHO national + state air APIs + **Llama Stack vision agent for PDF narrative extraction** | $0 | 5-7 days | LLM extraction accuracy on scanned PDFs; pdfplumber + Tesseract handle structured layer first |
| **Transcripts** | Free IR-page scraping + **Llama Stack LLM extraction**; FMP deferred to Phase 2 | $0 | 2-3 days | Transcript availability is flaky (FMP would smooth); extraction quality is no longer the bottleneck since LLM is internal |
| **LLM provider** | **OCI Llama Stack** (`https://llama-stack.ai-apps-ord.oci-incubations.com`); 95 models incl. GPT-5.4 family, Grok-4.20, Gemini 2.5, Llama 4. OpenAI-compatible. No API key (instance principal). | $0 (internal) | 1 day adapter | Single-region (us-chicago-1); fallback to deterministic paths if down. See `00-DECISIONS-AND-CONSTRAINTS.md` §4.2. |
| **Vector store / embeddings** | Llama Stack FAISS provider + `text-embedding-3-large` | $0 | 1 day | Faiss is in-memory; persistence config validated. Alternative: pgvector when scale demands it. |
| **Satellite** | Sentinel-2 via Earth Engine (free) | $0 | 3-5 days | 10m resolution limits phase detection |
| **Storage** | PostgreSQL + JSONB + local filesystem | $0 (dev) | 2-3 days | Schema design; migration discipline |
| **Entity Resolution** | rapidfuzz + curated alias table + Census geocoder for public companies; **Llama Stack agent with tool-use** for LLC→parent | $0 | 4-6 days | Calibrate confidence threshold; human-review queue for low-confidence cases |
| **Scheduling** | APScheduler (in-process) | $0 | 1 day | Single-process; no distributed execution |

### Total Estimated Phase 1 Cost

| Item | Monthly | Annual | Phase |
|------|---------|--------|---|
| OCI Llama Stack | $0 | $0 | Phase 1 (internal infra) |
| All Phase-1 free sources | $0 | $0 | Phase 1 |
| Shovels.ai (deferred) | $599 | $7,188 | Phase 2 |
| Financial Modeling Prep (deferred) | $29-99 | $348-1,188 | Phase 2 |
| **Phase-1 total** | **$0** | **$0** | |
| Phase-2 add-on | $628-698 | $7,536-8,376 | |

### Total Estimated Phase 1 Development Effort

**14-21 engineering days** to build the complete ingestion pipeline across all sources, replacing mock data with real data.

---

## Key References & Links

### EDGAR
- [edgartools GitHub](https://github.com/dgunning/edgartools)
- [edgartools Documentation](https://edgartools.readthedocs.io/en/latest/)
- [edgartools XBRL Guide](https://edgartools.readthedocs.io/en/latest/getting-xbrl/)
- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [SEC EFTS Full-Text Search](https://efts.sec.gov/LATEST/search-index)
- [sec-api.io Documentation](https://sec-api.io/docs)
- [sec-api.io Pricing](https://sec-api.io/pricing)

### Permits
- [Shovels.ai](https://www.shovels.ai/)
- [Shovels API Docs](https://docs.shovels.ai/)
- [Shovels API Reference](https://shovels.redoc.ly/)
- [Virginia Permit Transparency](https://permits.virginia.gov/Permit/Search)
- [Virginia Open Data Portal - Building Permits 2024](https://data.virginia.gov/dataset/building-permits-applications-2024)
- [Loudoun County LandMARC](https://www.loudoun.gov/5823/LandMARC-Land-Management-Applications-Re)
- [Loudoun County Issued Permit Reports](https://www.loudoun.gov/1164/Issued-Building-Permit-Reports)
- [Prince William County ePortal](https://www.pwcva.gov/department/development-services/eportal-access)
- [Fairfax County PLUS Portal](https://plus.fairfaxcounty.gov/CitizenAccess/Cap/CapHome.aspx?module=Building)

### Transcripts
- [Financial Modeling Prep - Earnings Transcripts](https://site.financialmodelingprep.com/developer/docs/stable/earnings-transcript-list)
- [Financial Modeling Prep Pricing](https://site.financialmodelingprep.com/pricing-plans)
- [FinancialDatasets.ai Docs](https://docs.financialdatasets.ai/introduction)
- [Alpha Vantage Documentation](https://www.alphavantage.co/documentation/)

### Satellite
- [Planet Labs Pricing](https://www.planet.com/pricing/)
- [Planet Labs Products](https://www.planet.com/products/)
- [Planet Developer Docs](https://developers.planet.com/docs/apis/)
- [Maxar SecureWatch / MGP Pro](https://www.maxar.com/products/securewatch)
- [Copernicus Data Space (Sentinel-2)](https://dataspace.copernicus.eu/)
- [Google Earth Engine](https://earthengine.google.com/)

### Libraries & Tools
- [httpx](https://www.python-httpx.org/)
- [rapidfuzz GitHub](https://github.com/rapidfuzz/RapidFuzz)
- [rapidfuzz Documentation](https://rapidfuzz.github.io/RapidFuzz/)
- [censusgeocode PyPI](https://pypi.org/project/censusgeocode/)
- [US Census Geocoder](https://geocoding.geo.census.gov/geocoder/)
- [APScheduler Documentation](https://apscheduler.readthedocs.io/)
- [asyncpg](https://github.com/MagicStack/asyncpg)

---

## Warnings / Gotchas

1. **SEC EDGAR rate limit is shared.** All SEC APIs (submissions, EFTS, XBRL companion) share the same 10 req/s limit per IP. If edgartools and our direct EFTS calls run simultaneously, we will hit the limit. Implement a shared rate limiter (e.g., `asyncio.Semaphore` or a token bucket).

2. **edgartools is sync internally.** It uses `httpx` sync client. In FastAPI, every edgartools call MUST be wrapped in `asyncio.to_thread()` or it will block the event loop and cause request timeouts under load.

3. **Shovels.ai coverage is not guaranteed for NoVA.** The 85% US population coverage statistic does not confirm individual county coverage. TEST BEFORE PROCUREMENT using the 250 free API calls to query Loudoun County permits.

4. **TSMC files as a foreign private issuer.** TSMC uses 20-F (annual) and 6-K (current) forms, not 10-K/10-Q. edgartools handles these, but XBRL taxonomy differs from US GAAP. Financial Modeling Prep transcripts are the more reliable source for TSMC data.

5. **Earnings transcript timing.** Transcripts from third-party providers may be delayed 1-48 hours after the call. For Phase 1, this is acceptable. Do not build real-time alerting on transcript availability.

6. **Sentinel-2 cloud cover.** Northern Virginia has significant cloud cover in winter months (Nov-Feb). Expect 30-50% of revisit passes to be unusable. Weekly monitoring cadence should still yield 1-2 usable images per month even in winter.

7. **PostgreSQL JSONB vs. structured columns.** Resist the temptation to dump everything into JSONB. Use JSONB for genuinely variable-schema data (raw source records). Use typed columns for metrics you will query and aggregate (MW, revenue, unit counts). This avoids the "JSON swamp" antipattern.

8. **rapidfuzz threshold tuning.** A fuzzy match threshold of 85 works for "Microsoft Corporation" vs "Microsoft Corp" but will false-match "Meta Platforms" with "Metaverse Holdings." Use context (source type, geography) as secondary discriminators, not fuzzy score alone.

9. **APScheduler in-process risk.** If the FastAPI process crashes, all scheduled jobs stop. Mitigate by: (a) running FastAPI under a process manager (systemd, supervisord) with auto-restart, and (b) persisting job run history to PostgreSQL so missed runs are detected on startup and re-triggered.

10. **The mock data hangover.** Seven of nine tabs currently return `random.*` on every request. Users may already be drawing conclusions from this data. As each real source comes online, explicitly mark remaining mock tabs with a visual "MOCK DATA" watermark. Do not silently mix real and mock data in the same view.

---

## Conformance to 00-DECISIONS-AND-CONSTRAINTS.md

- **§2.2 Tech Stack:** All recommendations in the Summary Decision Matrix match the locked choices.
- **§4 EDGAR APIs:** Full endpoint set referenced including frames API for cross-company comparison.
- Comparison tables retained for historical context; recommendations are final.
