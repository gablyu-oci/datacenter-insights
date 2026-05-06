# Decisions & Constraints — Master Input
**Owner:** Strategic Insights team · **Date:** 2026-04-28 · **Status:** Locked (all docs must conform)

This file is the single source of truth for the open decisions, locked tech-stack choices, and dataset/API constraints that all PRD / architecture / pipeline / UX docs in this repo must conform to.

---

## 1. Resolved Open Decisions (from prior dev-team output)

| # | Decision | Resolution |
|---|---|---|
| 1 | **Postgres hosting** | **Self-hosted on this OCI VM.** No managed service. Local Postgres process; data dir under the project / OCI VM disk. |
| 2 | **SEC EDGAR API usage** | **Leverage the official `data.sec.gov` REST APIs** (no auth, no key, free, JSON, real-time). See section 4. |
| 3 | **OCI inclusion** | **Include OCI** in every pillar alongside MSFT/AWS/GCP/Meta. Every category view must surface **% share for OCI** (e.g. OCI's % of total tracked GW, % of GPU shipments inferred for OCI, % of permits, etc.). |
| 4 | **Deploy target** | **This OCI compute instance.** No Kubernetes, no managed deploy; run via systemd or `start.sh` for now. |
| 5 | **Auth** | **No auth in v1.** Skip login, sessions, RBAC. Internal-only, trusted-network. Defer to a later phase. |

---

## 2. Locked Tech Stack (no further debate)

Use **every** recommended choice from the two Summary Decision Matrices originally produced by the dev-team. The matrices are reproduced below and are the locked source of truth — the lowercase Architecture Evolution matrix file has been archived to `docs/_archive/02-tech-stack-research.md`; the Data Pipeline matrix lives in `02-TECH-STACK-RESEARCH.md`.

### 2.1 Architecture Evolution matrix (locked here; archived source `_archive/02-tech-stack-research.md` §8)

| Layer | Choice | Key dependencies |
|---|---|---|
| Persistent store | **PostgreSQL + SQLModel** (self-hosted on this VM) | `sqlmodel`, `asyncpg`, `alembic` |
| Task queue / scheduler | **APScheduler (in-process)** | `apscheduler`, `fastapi-apscheduler` |
| HTTP client | **httpx** | `httpx`, `stamina` |
| Entity resolution | **Mapping tables + rapidfuzz** | `rapidfuzz` |
| Data lineage | **Custom columns + audit table** | (schema-only) |
| Frontend state | **TanStack Query** | `@tanstack/react-query` |
| API structure | **FastAPI APIRouter + DI** | (built-in) |

### 2.2 From the Data Pipeline matrix (`02-TECH-STACK-RESEARCH.md` §8)

| Area | Choice | Cost | Notes |
|---|---|---|---|
| EDGAR ingestion | **edgartools + httpx + EFTS API** | $0 | Wrap edgartools sync in `asyncio.to_thread()`. Use `data.sec.gov` REST endpoints directly for company facts/frames (see §4). |
| Permits | **Shovels.ai (primary) + free state APIs (fallback)** | $599/mo | MVP uses 6 free state APIs (VA/NY/WA/CO/OR/TX); Shovels.ai deferred to Phase 2 for filling the other 44 states. |
| Earnings transcripts | **Free IR-page scraping + Llama Stack LLM extraction** (FMP deferred to Phase 2) | $0 (MVP) | OCI Llama Stack `oci/openai.gpt-5.4-mini` for unit-extraction from transcript text. See §4.2. |
| Satellite | **Sentinel-2 via Google Earth Engine** | $0 | 10 m resolution; sufficient for phase detection. Maxar deferred. |
| Storage | **PostgreSQL + JSONB + local filesystem** | $0 | Self-hosted on this VM (decision #1). |
| Entity resolution | **rapidfuzz + curated alias table + Census geocoder** | $0 | |
| Scheduling | **APScheduler (in-process)** | $0 | Single-process; fine for v1. |

### 2.3 Implementation order (do not reorder)
1. API structure refactor (APIRouter)
2. PostgreSQL + SQLModel + lineage columns
3. httpx migration (kill blocking `urllib`)
4. APScheduler integration
5. Entity resolution tables + rapidfuzz
6. TanStack Query frontend migration

---

## 3. Datasets in `datasets/` — Inventory & Schema

The `datasets/` folder is now a primary input. All four files must be ingested via dedicated adapters and folded into the canonical schema.

### 3.0 Aterio refresh cadence (MVP scope)

The four files in `datasets/` are a **one-time, point-in-time delivery for the MVP** (received 2026-04-28). There is no live Aterio API or scheduled refresh feed in v1. If we license Aterio in Phase 2, the expected cadence is **weekly or monthly** delivery of an updated CSV; the ingestion layer must be designed so that re-ingesting an updated CSV is idempotent (upsert on `ATERIO_*_UID` natural keys, lineage records preserve the snapshot timestamp). For now, the MVP treats the CSV as a static snapshot.

### 3.1 `data_center_inventory_20260428.csv` (8.2 MB) — **PRIMARY (one-time MVP snapshot)**
- Aterio expanded sample, **73 columns**. Equivalent schema to the xlsx sample but full inventory.
- **Identity:** `ATERIO_DATA_CENTER_UID`, `DATA_CENTER_BUILDING_NAME`, `ATERIO_DATA_CENTER_CAMPUS_UID`, `DATA_CENTER_CAMPUS_NAME`
- **Status:** `DATA_CENTER_STAGE` (Announcement / Construction / Activated / Cancelled / Withdrawn), `PCT_CONSTRUCTION_STATUS`
- **Provider (operator):** `PROVIDER_NAME`, `PROVIDER_TICKER_NAME`, `PROVIDER_BLOOMBERG_TICKER_NAME`, `PROVIDER_PUBLIC_PRIVATE`, `PROVIDER_BACKED_BY`, `PROVIDER_URL`
- **End user:** `END_USER_COMPANIES` (e.g. who is leasing the colo)
- **Equipment & financing:** `CONSTRUCTION_EQUIPMENT_PROVIDER_COMPANIES`, `PROJECT_FINANCING_COMPANIES`
- **Geography:** `FULL_ADDRESS`, `ZIP_CODE`, `COUNTY_FIPS_CODE`, `COUNTY_NAME`, `CITY_NAME`, `PLACE_FIPS_CODE`, `STATE_CODE`, `STATE_NAME`, `COUNTRY_CODE`, `COUNTRY_NAME`, `LOCATION_LATITUDE`, `LOCATION_LONGITUDE`
- **Physical:** `SITE_ACREAGE`, `TOT_FACILITY_SPACE_SQFT`, `TOT_DATACENTER_SPACE_SQFT`
- **Power capacity (MW):** `PROV_PUB_TOT_POWER_CAPACITY_MW` (provider-disclosed), `ATERIO_EST_TOT_POWER_CAPACITY_MW` + `_LOWER` + `_UPPER` (Aterio estimate with bounds), `SELECTED_POWER_CAPACITY_MW`
- **Economics:** `TOT_PROJECT_COST`, `AVG_MARKET_POWER_COST`, `YEARLY_PUE`, `TOT_NUM_GENERATORS`
- **Timeline:** `DATA_CENTER_ANNOUNCED_DATE`, `_CONSTRUCTION_START_DATE`, `_CONSTRUCTION_FINISHED_DATE`, `_ACTIVATION_DATE`, `ESTIMATED_ACTIVE_DATE_BY`, `_CANCELLED_DATE`, `_PROJECT_WITHDRAWN_DATE`, `LATEST_SATELLITE_PICTURE_DATE`
- **Utility / grid:** `UTILITY_NAME`, `UTILITY_PUBLIC_PRIVATE`, `UTILITY_TICKER_NAME`, `BAL_AUTH_ABBR`, `BAL_AUTH_NAME`, `BAL_AUTH_SUBREGION_CODE`, `BAL_AUTH_SUBREGION_NAME`
- **Source links (clickable per the user's rule):** `DATASHEET_URL`, `MAP_URL`, `PROJECT_PERMIT_URL`, `CAPEX_URL`
- **Confidence & flags:** `PROJECT_EXECUTION_LIKELIHOOD`, `FLG_AI_FACILITY`, `FLG_BTM_ONSITE_POWER_GENERATION`, `NOTES`
- **Lineage:** `RECORD_CREATED_DATE`, `RECORD_UPDATED_DATE`, `UPDATED_AT`

→ This single file covers Power, Satellite (lat/lon + last imagery date), Permits (project permit URL), and Triangulation L1 (contracted power) for ~all major US datacenters. **Use this as the canonical site/deal table seed for v1**, replacing `curated_deals.py` as the primary source while keeping `curated_deals.py` as a hand-verified overlay.

### 3.2 `Aterio expanded sample dataset april, 2026.xlsx` (248 rows × 73 cols)
- Same schema as the CSV but smaller, hand-curated sample (Meta Hyperion campus, etc.). Use as a fixture for tests + quick offline demo data; the CSV supersedes it for production ingest.

### 3.3 `Data Centers's Data Dictionary (Data Product).xlsx` — Schema reference + Events
- Sheet **`Data Centers Inventory`** (1022 rows × 61 cols): field-by-field data dictionary. Use to generate SQLModel column docstrings and OpenAPI field descriptions.
- Sheet **`Data Centers Events`** (957 rows × 48 cols): timestamped events at each site (announcement, permit filed, construction start, activation, expansion, etc.). **This is the primary feed for the Events / timeline view.** Schema must include an `events` table joined to sites.

### 3.4 `Energy Project Inventory Data Sample.xlsx` (1695 rows × 65 cols)
- Aterio's **energy supply** dataset — projects supplying power to/around datacenters: `PROJECT_NAME`, `FLG_BTM_PROJECT` (behind-the-meter), `DEVELOPER_COMPANIES`, `DEVELOPER_COMPANIES_TICKER`, `EIA_ENTITY_IDS`, `EIA_ENTITY_NAMES`, `CONSTRUCTION_EQUIPMENT_PROVIDER_COMPANIES`, `PROJECT_FINANCING_COMPANIES`, `CUSTOMER_COMPANIES`, `TOT_PROJECT_COST`, `PROJECT_FOOTPRINT_ACREAGE`, `SITE_BOUNDARY_ACREAGE`, `TOT_CONTRACTED_POWER_CAPACITY_MW`, plus 50+ more (sheet dictionary in same workbook).
- → Powers a new **Energy Supply** view that complements Power Demand. Joinable to datacenter sites via developer/customer/equipment-provider company linkage and EIA entity IDs.

---

## 4. SEC EDGAR APIs to Leverage (free, no auth, no key — just identifying User-Agent)

From https://www.sec.gov/search-filings/edgar-application-programming-interfaces (last reviewed 2025-04-08).

| Endpoint | Use |
|---|---|
| `https://data.sec.gov/submissions/CIK##########.json` | Filing history per company; current/former names, tickers, exchanges. **Use to drive 8-K/10-K/10-Q polling for power-deal extraction.** |
| `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` | All XBRL facts for a company in one call. **Use for NVIDIA datacenter-segment revenue, TSMC capex, Coherent / Lumentum / Broadcom revenue & inventory line items.** |
| `https://data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/<concept>.json` | Single concept time series (e.g. `Revenues`, `PropertyPlantAndEquipmentNet`, `CapitalExpenditures`). |
| `https://data.sec.gov/api/xbrl/frames/us-gaap/<concept>/USD/CY####Q#.json` (or `CY####Q#I`) | Cross-company snapshot of a concept for a calendar period. **Use to compare hyperscaler capex/PP&E side-by-side per quarter in one call.** |
| `https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip` | Nightly bulk archive of all company facts. **Use for backfill / cold-start; refresh nightly at 03:00 ET.** |
| `https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip` | Nightly bulk archive of all submissions. |
| `https://efts.sec.gov/LATEST/search-index?q=<term>&forms=8-K` | EFTS full-text search. **Use to surface PPA/power-purchase/datacenter keyword hits across 8-Ks regardless of CIK.** |

**Constraints:**
- Rate limit: **10 req/s** with an identifying `User-Agent: <product> <email>` header.
- **No CORS** on `data.sec.gov` — must call from backend, never from the browser.
- Keep the existing `edgartools` library wrapper for typed parsing of 10-K/10-Q/8-K bodies; use the raw REST endpoints above for fact-level XBRL aggregation and cross-company frames.

---

## 4.1 Other Free Sources (added 2026-04-28)

These free, no-auth sources broaden coverage beyond EDGAR and complement the Aterio MVP snapshot. They are the **only** external sources active in Phase 1 alongside the Aterio CSV.

| Source | Use | Notes |
|---|---|---|
| **EPA ECHO** (`echo.epa.gov/tools/web-services`) | National baseline of air-permitted facilities. Filter by NAICS 518210 + emergency-engine source classes. | JSON, no auth. Primary feed for the generator-permit pipeline (see `03-PIPELINE-ARCHITECTURE.md` §8). |
| **EPA Envirofacts** (`data.epa.gov/efservice/`) | NEI emissions data; FRS cross-reference; ICIS-AIR detail. | JSON. Use `FRS_ID` as the canonical facility key from federal sources. |
| **EPA CAMD** (`api.epa.gov/easey/`) | CEMS data for units that report it. | Reveals "emergency standby generators that actually run a lot." |
| **OpenCorporates** (free tier) | State business-registry aggregation. | Use to resolve permittee LLCs to officers/registered agents/principal addresses. Free tier limited; paid in Phase 2. |
| **County GIS portals** (Loudoun, Prince William, Fairfax, etc.) | Parcel ownership + APN lookups. | Per-county, mostly bulk download. |
| **Texas TCEQ Air Permits API** | Texas air permits + Central Registry. | DFW, Austin, Abilene, San Antonio. |
| **CARB / SCAQMD / BAAQMD** (CA regional APIs) | California air permits. | CEIDARS, CHAPIS. |
| **Socrata-style state portals** (NY DEC, WA Ecology, CO CDPHE, OR DEQ) | Open-data air permit feeds. | Use a generic Socrata adapter. |
| **VA Open Data** (`data.virginia.gov`) | Free fallback for Virginia building permits when Shovels.ai is not licensed. | Loudoun + Prince William coverage. |
| **ISO/RTO interconnection queues** (PJM, ERCOT, MISO, SPP, CAISO) | Public interconnection-request data. | Cross-check Aterio site IDs to grid-side capacity announcements. |
| **US Census Geocoder** | Free address → lat/lon. | Backfill geocodes when source data only has addresses. |
| **Sentinel-2 via Google Earth Engine** | 10 m satellite imagery for site change detection. | Free; sufficient for groundbreak / phase detection. |
| **Trade-press RSS** (Data Center Dynamics, Data Center Frontier) | Early-warning signal preceding permits by 6–18 months. | Free RSS feeds. Pair with permit data, do not rely on alone. |

**Phase-2 paid additions (deferred, not in MVP):** Shovels.ai ($599/mo, national permit API), Financial Modeling Prep ($29–99/mo, earnings transcripts), OpenCorporates Pro, Aterio licensed feed, Maxar sub-meter satellite.

---

## 4.2 AI / LLM Agents in MVP (Llama Stack on OCI)

**Provider:** OCI internal Llama Stack at `https://llama-stack.ai-apps-ord.oci-incubations.com`. OpenAI-compatible REST surface (`/v1/chat/completions`, `/v1/responses`, `/v1/conversations`, `/v1/tool-runtime/invoke`, `/v1/vector_stores`, `/v1/embeddings`, `/v1/moderations`, plus `/v1alpha/inference/rerank`). **Auth:** instance principal from this OCI VM — no API key, no rate-limit cost gating. Verified working `2026-04-28`. **No Anthropic / OpenAI direct integration** — all LLM traffic flows through Llama Stack.

**Locked model picks per role** (each agent specifies primary + fallback so we don't blanket-default):

| Role | Primary model | Fallback | Rationale |
|---|---|---|---|
| Tool-using reasoning agent (Q&A, LLC resolver) | `oci/openai.gpt-5.4` | `oci/xai.grok-4.20-reasoning` | Best tool-calling fidelity + reasoning depth. |
| Cheap structured extraction | `oci/openai.gpt-5.4-mini` | `oci/google.gemini-2.5-flash` | Fast JSON-mode; cost is internal but latency matters at high volume. |
| Vision (PDF / multimodal) | `oci/google.gemini-2.5-pro` | `oci/cohere.command-a-vision` | Strong layout-aware vision; pdfplumber/Tesseract handle the structured layer first. |
| Embeddings | `oci/openai.text-embedding-3-large` | `oci/cohere.embed-english-v3.0` | High-dim quality; Cohere fallback for cheaper bulk. |
| Reranker | `/v1alpha/inference/rerank` (Llama Stack default) | n/a | Single endpoint; no model choice exposed yet. |

### MVP agents — what's necessary, not nice-to-have

Five agents ship in MVP; nothing speculative. Each has a single owner, a defined input/output, and a fallback path when the LLM is unavailable.

| # | Agent | Phase | Type | Model | Why it's necessary |
|---|---|---|---|---|---|
| **A** | **EDGAR 8-K Extractor** | Phase 1 | Single-turn structured extraction | `gpt-5.4-mini` | Replaces brittle regex in `edgar_agent.py`. Filings vary wildly ("100 MW PPA" / "approximately 1.2 GW" / "200 MW with optional 50 MW expansion"); regex misses ~30% in our prior test set. Strict JSON schema gives reliable typed output with a `source_quote` field for citation. |
| **B** | **Permit PDF Extractor** | Phase 1.5 | Single-turn structured extraction (vision) | `gemini-2.5-pro` | Generator-permit detail (rated MW, fuel type, emissions tier, hours) lives in PDFs, often scanned. Combined pipeline: `pdfplumber` for tables → Tesseract for OCR fallback → vision LLM for narrative. Was previously planned as Anthropic Claude; now Llama Stack. |
| **C** | **LLC → Parent Resolver** | **Phase 1.5 (promoted from Phase-2 deferred)** | Multi-turn agent with tools | `gpt-5.4` | Was planned as deterministic-only weighted scorer (`03-PIPELINE-ARCHITECTURE.md` §7.5.4). With free internal LLM, the agent can *reason* across signals (SEC Exhibit 21 → OpenCorporates → parcel deed → ISO queue → web search) and produce attribution + evidence trail in one pass. The deterministic signals stay; the agent orchestrates them via tool-use and handles ambiguity. |
| **D** | **Triangulation Q&A Agent** | Phase 1 | Multi-turn conversational with tools | `gpt-5.4` | the user's "is there enough power for the GPUs being shipped in Texas?" question is naturally conversational. A chat agent with tool-use over `/api/sites`, `/api/{tab}/oci-share`, `/api/coverage`, vector search over permit narratives turns the dashboard into an actual *intelligence platform*, not a static digest. Streamed responses; conversation persisted via `/v1/conversations`. |
| **E** | **Weekly Brief Agent** | Phase 1 | Scheduled (APScheduler) tool-using | `gpt-5.4-mini` | Runs Sunday night; diffs current data against last week's snapshot via SQL tools, generates a 5–10 bullet Markdown briefing covering new permits, MW deltas by company, coverage changes, anomalies. Bridges the static dashboard to actionable insights. |

### Supporting LLM infrastructure (also MVP)

- **Vector store** for permit narratives + 8-K narratives + earnings transcript chunks. Llama Stack FAISS provider via `/v1/vector_stores`. Indexed by the EDGAR/Permit extractors at ingest time. Powers the Q&A agent's `vector_search_*` tools.
- **Web search tool** (`builtin::websearch`, Tavily, already registered) — used by the LLC resolver agent for trade-press cross-validation.
- **Conversations API** (`/v1/conversations`) — stores Q&A agent multi-turn history per user session.
- **Reranker** (`/v1alpha/inference/rerank`) — improves vector-search results before agent consumes them.

### What's deliberately NOT an agent (kept deterministic)

- Source ingestion adapters (Aterio CSV, EDGAR XBRL, EPA ECHO, Socrata APIs, PJM) — plain HTTP + structured parsing.
- Public-company entity resolution — `rapidfuzz` + ticker/CIK alias table. Trivially deterministic.
- Triangulation engine — pure-function SQL/Python over canonical store; not an agent.
- OCI %-share computation — SQL views; not an agent.
- Geographic joining — lat/lon math.

### Agent contracts (uniform)

Every agent emits a structured response with the same envelope so `data_lineage` records are consistent:

```json
{
  "result": { ... agent-specific output ... },
  "model": "oci/openai.gpt-5.4-mini",
  "prompt_version": "edgar_extractor.v3",
  "input_hash": "sha256:...",          // for caching + idempotency
  "tool_calls": [ ... evidence trail ... ],
  "confidence": 0.87,                  // self-assessed; calibrated against eval set
  "latency_ms": 1240,
  "tokens": { "prompt": 1820, "completion": 240 },
  "errors": []                         // structured fallback path on failure
}
```

Logged to a new `llm_extraction_runs` table (schema in `03-architecture-design.md` §6). All `confidence` values feed into the same lineage `confidence` column the rest of the pipeline uses — a the user-clickable source link plus an LLM confidence score is a single UI affordance.

### Fallback behavior when Llama Stack is unavailable

Every agent ships with a deterministic fallback:
- **EDGAR extractor:** falls back to existing regex (still resident in code, gated by env var).
- **Permit extractor:** falls back to pdfplumber-only (loses narrative fields; structured fields preserved).
- **LLC resolver:** falls back to deterministic weighted scoring (the original design from `03-PIPELINE-ARCHITECTURE.md` §7.5.4).
- **Q&A agent:** UI shows a "service degraded" banner; tabs continue to work without chat.
- **Weekly brief:** skip the run; surface the staleness in the brief card.

This is not theoretical robustness — Llama Stack is internal infra and will go down for maintenance. The deterministic paths must stay shippable.

---

## 5. UX Constraint (Hard Rule)

- **Do not change the visual look of any existing tab.**
- **Do not delete any existing component, page, function, or endpoint.**
- If a new page / component / function is needed, **add** it next to the existing one.
- **Fix all currently broken parts** (e.g. silent EDGAR exception handler, blocking sync `urllib` inside FastAPI, `useApi` swallowing errors with no error UI, mock confidence scores, hardcoded `http://localhost:8000` API base, CORS `*`, Google Maps key in committed `.env.local`, missing `requirements.txt`).
- New views needed (additive):
  - **OCI %-share view** on every category tab (Power, GPU, NICs/Optics, TSMC, Permits, Triangulation) — small KPI tile or stacked-bar segment showing OCI's % of the tracked total. **Role-parameterized** per §5.1.
  - **Energy Supply tab** sourced from §3.4 (new tab next to existing tabs; do not replace).
  - **Events timeline** sourced from §3.3 events sheet (additive sub-section on the relevant tabs).
  - **Companies tab + Company detail page** (additive) — list of all tracked companies with role distribution; per-company drilldown showing self-owned vs end-user-only vs financing/equipment/utility footprint.
  - **Site detail role-breakdown** — additive section on each site detail view showing which company fills each role on that site.

### 5.1 Role model (driving multi-role views)

A single company can fill multiple roles across the dataset, and sometimes multiple roles on the same site (e.g. self-built and self-occupied). Roles must be modeled explicitly, not collapsed:

| Role | Source field(s) | Meaning |
|---|---|---|
| `provider` | `PROVIDER_NAME`, `PROVIDER_TICKER_NAME` | Owns / operates the building |
| `provider_backer` | `PROVIDER_BACKED_BY` | Parent or strategic investor in the provider |
| `end_user` | `END_USER_COMPANIES` (split on comma) | Occupies the space, runs workloads |
| `financing` | `PROJECT_FINANCING_COMPANIES` (split) | Provides capital |
| `equipment` | `CONSTRUCTION_EQUIPMENT_PROVIDER_COMPANIES` (split) | Builds the facility / supplies gear |
| `utility` | `UTILITY_NAME`, `UTILITY_TICKER_NAME` | Delivers grid power |
| `developer` | `DEVELOPER_COMPANIES` (energy_projects) | Develops the energy project |
| `customer` | `CUSTOMER_COMPANIES` (energy_projects) | Buys the energy project's output |
| `permittee_llc` | EPA ECHO / state air permits | LLC named on the air permit |
| `permit_parent` | Resolved via SEC Exhibit 21 / OpenCorporates / parcel | Inferred ultimate parent of the LLC permittee |

Schema: a many-to-many `site_company_associations(site_id, company_id, role, source, confidence)` table — see `03-architecture-design.md` §3 and `03-PIPELINE-ARCHITECTURE.md` §4.

OCI %-share queries are **role-parameterized**: `/api/{tab}/oci-share?role=provider` for owned footprint, `?role=end_user` for total operational presence, `?role=any` for combined. Default role per tab is documented in `03-architecture-design.md` §4 (canonical OCI %-share section).

---

## 5.2 Phase-1 MVP scope and source set (locked)

**Geographic scope: all 50 US states + DC.** The MVP is national from day one — there is no NoVA-only carve-out. Coverage *quality* varies per pillar (see §5.3); the UI must surface this honestly via coverage badges. Outside the US is not in scope.

**Phase 1 uses ONLY these free sources (+ the Aterio one-time CSV):**
- Aterio one-time CSV (§3.1; ~10 K sites across all US states. §3.2/§3.3/§3.4 as supplementary fixtures.)
- SEC EDGAR free REST APIs (§4) — federal, all US public filers.
- EPA ECHO + EPA Envirofacts + EPA CAMD (§4.1) — federal, national air-permit baseline + emissions.
- **State permit APIs** (free, structured): VA Open Data, NY DEC (Socrata), WA Ecology (Socrata), CO CDPHE (Socrata), OR DEQ (Socrata), TX TCEQ Air Permits API.
- **Per-county GIS portals** for parcel/APN lookups in VA (Loudoun, Prince William, Fairfax) — additive, not required for v1 ship.
- US Census Geocoder (national).
- Sentinel-2 via Google Earth Engine (global).
- ISO/RTO interconnection queues — **PJM only in v1** (mid-Atlantic + Great Lakes); ERCOT/MISO/SPP/CAISO/NYISO/ISO-NE flagged as pending.
- Trade-press RSS (national best-effort signal).

**Not in Phase 1:** Shovels.ai, Financial Modeling Prep, OpenCorporates Pro, Maxar, Aterio licensed live feed, additional state permit scrapers beyond the 6 above. These are deferred to Phase 2 pending the user's procurement decisions.

**Implication of national scope on free sources:**
- Power, sites, and federal filings work *fully* for all 50 states from day one (Aterio + EDGAR + ECHO are already national).
- Building permits structurally cannot be national without paid Shovels.ai. The 6 state APIs above are the realistic free coverage; **all other states must render an explicit "no building-permit coverage" UI state**, never a silent empty chart.
- Generator/air permits have a national EPA ECHO baseline + state-level depth in TX/CA/NY/WA/CO/OR. Other states get the federal baseline only — flagged in the UI.
- Earnings transcripts work for all tracked public companies but availability varies (FMP would smooth this; deferred).
- Triangulation accuracy degrades in states without building-permit coverage; surface this in the per-state triangulation card.

---

## 5.3 Coverage Communication (Hard Rule)

Because MVP coverage varies significantly per pillar per state, every UI surface that visualizes data MUST tell the truth about its coverage. **Silent partial-coverage rendering is a defect.**

Concrete requirements:

1. **`<CoverageBadge />` on every tab** — a small chip/pill in the tab header showing coverage status: `Full national` (green) · `Partial (N states)` (yellow with state count + tooltip listing them) · `Federal-only baseline` (yellow) · `Single source / state` (orange) · `No data` (red). See `04-ux-evolution-plan.md`.
2. **Per-state empty states** on any geographic visualization (maps, choropleths, state filters): when the user selects a state with no coverage for that pillar, render an explicit message — *not* an empty chart. Example: "No building-permit coverage for Iowa yet. Federal air-permit baseline (EPA ECHO) is available — switch to that view, or see the Coverage roadmap."
3. **Triangulation per-state cards** must show which of L1/L2/L3/L4 are populated for that state and which are missing — never produce a number without showing what informed it.
4. **Coverage page** (additive to the existing Sources tab): a single page summarizing per-pillar per-state coverage with last-ingested timestamps, record counts, and a "what's missing and why" roadmap. Backed by the `data_coverage` table (`03-architecture-design.md`).
5. **API responses** for any endpoint that aggregates across states must include a `coverage` field in the response listing the states/sources contributing to the result. Same lineage envelope, with one extra key.

The `data_coverage` table and `/api/coverage` endpoints are the single source of truth — coverage badges read from there, and adapter ingestion runs write to it.

---

## 6. Documentation Consistency Goals

After updates, the doc set must:
- Reflect the 5 decisions above on every page that mentions an "open question."
- Reference exactly the locked stack from §2 (no alternatives presented as undecided).
- Treat §3 datasets as Phase-1 ingest sources alongside SEC EDGAR + permits + earnings.
- Treat §4 EDGAR endpoints as the primary EDGAR access pattern.
- Honor §5 UX rule (additive only; broken parts fixed).
- Eliminate redundancy between the two parallel `00`–`04` doc sets in `docs/planning/` (lowercase = architecture evolution; UPPERCASE = data pipeline) — keep both tracks distinct in scope but cross-link instead of restating.
- Surface OCI %-share as a first-class metric in PRD success criteria, DB schema (computed column or view), and API responses.

---

*This file is read-only context for the dev-team. Do not edit it during the consolidation pass — instead, update the downstream docs to conform.*
