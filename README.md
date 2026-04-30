# Datacenter & Power Intelligence Platform

Strategic intelligence tool tracking hyperscaler datacenter buildout and power procurement across the US.

## Prerequisites

- **PostgreSQL 16** with PostGIS extension (self-hosted on OCI VM, no Docker)
- **Python 3.10+** with [uv](https://docs.astral.sh/uv/) package manager
- **Node.js 18+** (via nvm) for the React frontend

## Quick Start

```bash
# 1. Clone and cd into the project
cd strategic-insights-tool

# 2. Backend setup (first time only)
cd backend
cp .env.example .env          # edit DATABASE_URL, ALLOWED_ORIGINS as needed
uv sync                       # creates .venv + installs all deps
.venv/bin/alembic upgrade head # run migrations
cd ..

# 3. Frontend setup (first time only)
cd frontend
npm install
cp .env.example .env.local    # edit VITE_API_BASE_URL if needed
cd ..

# 4. Run everything
./start.sh
```

Backend: http://localhost:8000
Frontend: http://localhost:5173

## Environment Variables

### Backend (`backend/.env`)

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://sit_app:changeme@localhost:5432/strategic_insights` | Async DB connection string |
| `ALLOWED_ORIGINS` | `["http://localhost:5173"]` | JSON array of CORS origins |
| `MOCK_DATA` | `0` | Set to `1` to enable mock data endpoints |
| `EDGAR_USER_AGENT` | `Datacenter Intelligence Platform research@oracle.com` | SEC EDGAR API user agent |
| `LLAMA_STACK_URL` | `https://llama-stack.ai-apps-ord.oci-incubations.com` | Llama Stack LLM endpoint |

### Frontend (`frontend/.env.local`)

| Variable | Default | Description |
|---|---|---|
| `VITE_API_BASE_URL` | (empty) | Backend API URL; empty = relative (reverse proxy) |
| `VITE_GOOGLE_MAPS_API_KEY` | (empty) | Google Maps API key for satellite view |

## Database Migrations

```bash
cd backend

# Check current migration state
.venv/bin/alembic current

# Create a new migration after model changes
.venv/bin/alembic revision --autogenerate -m "description_of_change"

# Apply all pending migrations
.venv/bin/alembic upgrade head

# Roll back one migration
.venv/bin/alembic downgrade -1
```

## Project Structure

```
strategic-insights-tool/
  backend/
    main.py              # FastAPI app, router registration, CORS
    config.py            # pydantic-settings configuration
    db/
      models.py          # SQLModel ORM (15 tables)
      session.py         # Async session factory + get_db() DI
    routers/             # APIRouter modules (17 files)
    schemas/
      common.py          # LineageEnvelope, CoverageEnvelope, PagedResponse
    agents/
      edgar_agent.py     # SEC EDGAR 8-K fetcher (async httpx)
    data/
      curated_deals.py   # Verified power deal dataset
      mock_data.py       # Mock data (gated by MOCK_DATA=1)
    llm/
      client.py          # Llama Stack client wrapper (Phase 1C shell)
    alembic/             # Database migrations
    alembic.ini
    pyproject.toml
    requirements.txt
  frontend/
    src/
      components/
        shared/
          ErrorPanel.tsx  # Reusable error display component
      hooks/
        useApi.ts         # Fetch hook with retry + error classification
  docs/
    planning/            # Architecture, PRD, decision docs
  start.sh               # Dev launcher (pg check + alembic + backend + frontend)
```

## API Health Check

```bash
curl http://localhost:8000/api/health
# {"status":"ok","version":"0.1.0","db":"connected","llama_stack":"..."}
```

## Phase Roadmap

- **Phase 0**: Infrastructure foundation -- DB, migrations, routers, envelopes ✅
- **Phase 1**: Real data ingestion adapters (EIA, RCRA, ECHO, PJM queue, VA / TX / NY permits) ✅
- **Phase 1.5**: LLM extraction agents (EDGAR 8-K, weekly brief) ✅
- **Phase 2** (April 2026, current): Multi-form EDGAR (10-K + 10-Q), expanded vendor coverage,
  IR press-release scraper, anomaly detection, bulk PDF parsing, ERCOT + MISO + Iowa + Ohio
  adapters, L1 triangulation UI ✅
- **Phase 3** (planned): Paid-source integrations (Aterio, NVIDIA shipments, Coherent/Lumentum
  order books, Shovels.ai, Planet/Maxar imagery, Bloomberg/NewsAPI)

## Phase 2 — What's Ingested

See `docs/planning/PHASE2_RESEARCH.md` for the canonical endpoint catalog (URLs,
formats, env-var overrides). Highlights:

### SEC EDGAR (LLM extraction)
- **Forms**: 10-K and 10-Q (chunked on Item-section markers, `parser_version='llm-v4-multiform'`)
- **Filers tracked** (`TRACKED_FILERS`): Microsoft, Amazon, Alphabet, Meta, Oracle, Apple,
  Constellation, Talen, NuScale, Oklo, Vistra, NextEra, AES, Dominion, plus 5 vendor adds
  for Phase 2: Broadcom, Coherent, Lumentum, NVIDIA, TSMC
- **Cron**: weekly Wed 06:00 UTC (`quarterly_filings_weekly`)

### IR press releases (19 companies)
- RSS-first where available (Microsoft, Meta, Oracle, NVIDIA); Q4 Inc. / GCS-Web
  HTML scraping otherwise. See `backend/ingestion/press_releases.py::IR_TARGETS`.
- Filtered to releases matching `{datacenter, hyperscale, GW, MW, PPA, interconnect,
  nuclear, SMR, colo, GPU}` keyword regex.
- Endpoint: `GET /api/press-releases/recent?company=...&days=30&limit=50`
- Cron: nightly (registered in `pipeline/runner.py`)

### ISO / RTO interconnection queues
- **PJM** (Phase 1.5): bulk XML feed
- **ERCOT** (new): GIS Report — JSON listing → `doclookupId` → XLSX
- **MISO** (new): GI Queue landing-page scrape → CDN-hosted XLSX

### State permit feeds
- **VA / TX / NY** (Phase 1.5): CKAN, TCEQ, Socrata
- **IA** (new): Iowa SPARS Construction Permits, Socrata `8bwn-bk39`
- **OH** (new): placeholder Socrata adapter; production Ohio EPA path requires ArcGIS Hub
  or HTML scrape (see PHASE2_RESEARCH.md §B)

### Triangulation (L1 only)
- L1 = sites + curated_deals + edgar_extractions, computed live via `/api/triangulation/l1`
- L2 (NVIDIA shipments), L3 (Coherent/Lumentum order books), L4 (Shovels permits) shown
  as greyed-out "Paid data required" tiles in the UI — no fabricated numbers

### Anomaly detection
- 7 weekly time-series (PJM queue MW, per-state permits, EDGAR-extracted MW)
- Trailing-12-week mean ± 2σ flag
- Endpoint: `GET /api/anomalies/recent?days=30&limit=50`
- Cron: nightly 02:30 UTC (`anomaly_detection_nightly`)

### Bulk permit PDF parsing
- 3-stage cascade: pdfplumber → tesseract OCR → Claude vision
- 200 LLM-call cap per run, SHA-1 cache at `backend/data/cache/permit_pdf_*.json`
- CLI: `.venv/bin/python cli.py ingest --source parse_permits --limit 500 --llm-cap 200`

### Manual CLI sources
```bash
.venv/bin/python cli.py ingest --source <name>
# names: edgar_quarterly, ercot, miso, iowa_permits, ohio_permits,
#        press_releases, anomaly_detect, parse_permits
```

## Paid-source gaps (NOT in Phase 2)

These are blocked on commercial procurement; surfaced in the UI with explicit
"Paid data required" labeling rather than mock-filled:

| Gap | Source | Use case |
|---|---|---|
| L2 triangulation | NVIDIA GPU shipments | Site-level GPU density inference |
| L3 triangulation | Coherent / Lumentum order books | Optical interconnect demand signal |
| L4 triangulation | Shovels.ai county building permits | Site civil-works lead indicator |
| Licensed sites | Aterio | Authoritative datacenter inventory |
| Entity resolution | FMP / OpenCorporates | Company canonical IDs |
| Imagery | Planet / Maxar | Construction-progress detection |
| News | Bloomberg / NewsAPI | Structured deal/news feed |
