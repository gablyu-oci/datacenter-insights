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
    main.py              # FastAPI app, router registration, CORS, MCP mount
    mcp_server.py        # MCP server (mounted at /mcp; OpenClaw tool bridge)
    config.py            # pydantic-settings configuration
    cli.py               # `python cli.py ingest --source <name>` adapter runner
    entity_resolution.py # rapidfuzz-based company alias resolver
    db/
      models.py          # SQLModel ORM (sites, companies, events, etc.)
      session.py         # Async session factory + get_db() DI
    routers/             # 22 APIRouter modules (insights, qa, brief, sites,
                         #   companies, power, gpu, permits, triangulation, …)
    agents/
      edgar_agent.py, datacenter_qa.py, triangulation_qa.py, weekly_brief.py,
      anomaly_detector.py, edgar_extractor.py, edgar_buyer_validator.py,
      parent_resolver.py, vendor_supply_extractor.py
      insights/          # AI Insights subsystem
        orchestrator.py, agentic_synthesis.py, hypothesizer.py, dedup.py,
        llm_adapter.py, session_tools.py, skill_ctx_factory.py
        prompts/         # 5 system-prompt fragments (chat, brief, synthesis, qa, triangulation)
        skills/          # 15 skills (cohort, segmentation, time-series, …)
        specs/           # ChartSpec / SSE event / SkillContext schema contracts
        tools/           # run_skill, get_chart_data, query_database, web_search, …
        db/              # AI Insights persistence (insights, sessions, citations)
    openclaw/            # Forwarders (chat / synthesis / qa) + SSE translator + SOUL.md
    ingestion/           # 20 source adapters (edgar, epa_echo, aterio,
                         #   press_releases, pdf_parser, iso/, permits_state/,
                         #   permits_county/)
    pipeline/
      runner.py          # APScheduler — daily / weekly cron jobs
    schemas/
      common.py          # LineageEnvelope, CoverageEnvelope, PagedResponse
    seed/
      canonical_companies.py, coverage_seed.py
    data/
      mock_data.py       # Mock data (gated by MOCK_DATA=1)
    llm/
      client.py          # Llama Stack client (reasoning / extraction / vision / embedding)
    alembic/             # Database migrations (head: 013_*)
    alembic.ini
    pyproject.toml
    tests/               # pytest suite (~34 tests)
  frontend/
    src/
      App.tsx            # tab registry (10 tabs)
      components/
        tabs/            # PowerTab, DataCentersTab, GPUSupplyTab,
                         #   NICsOpticsTab, TSMCTab, PermitsTab, TriangulationTab,
                         #   CompaniesTab, SourcesTab, ai-insights/
        agentchat/       # streaming chat primitives (MessageList, SourcePill, …)
        layout/          # Header, TabNav
        shared/          # ErrorPanel, NoDataPanel, CitationFooter, CoverageBadge,
                         #   TabWrapper, SiteRoleBreakdown
        ChatPanel.tsx    # Q&A chat dock
      hooks/
        useApi.ts        # REST fetch + retry
        useInsightStream.ts, useLatestInsightSession.ts, useQA.ts
      styles/insightTokens.ts
  docs/
    PRD.md               # Product spec
    OPEN-TENSIONS.md     # Trade-offs deferred with revisit triggers
    planning/            # 00-DECISIONS, 02-TECH-STACK, 03-architecture-design,
                         #   03-PIPELINE-ARCHITECTURE, 04-ux-evolution-plan,
                         #   PHASE2_RESEARCH, SUPPLIER_VENDOR_SCOPE,
                         #   STAKEHOLDER_REQUIREMENTS_AUDIT, DEMO_BRIEF
                         # planning/ai-insights/SKILL_CONVERSION.md
    plans/ai-insights-automation/   # Synthesis automation + OpenClaw + MCP
    research/            # DATA_SOURCE_LANDSCAPE_REPORT, vitest-setup
    qa/                  # Phase QA reports
    _archive/            # Superseded historical docs
  .openclaw/             # OpenClaw runtime (gateway config + persona; runtime
                         # state is gitignored)
  datasets/              # Aterio / data-dictionary / energy-project samples
  start.sh               # Dev launcher (pg check + alembic + backend + frontend)
```

## API Health Check

```bash
curl http://localhost:8000/api/health
# {"status":"ok","version":"0.1.0","db":"connected","llama_stack":"..."}
```

## Phase Roadmap

- **Phase 0**: Infrastructure foundation — DB, migrations, routers, envelopes ✅
- **Phase 1**: Real data ingestion adapters (EIA, RCRA, ECHO, PJM queue, VA / TX / NY permits) ✅
- **Phase 1.5**: LLM extraction agents (EDGAR 8-K, weekly brief) ✅
- **Phase 2**: Multi-form EDGAR (10-K + 10-Q), expanded vendor coverage,
  IR press-release scraper, anomaly detection, bulk PDF parsing, ERCOT + MISO +
  Iowa + Ohio adapters, L1 triangulation UI ✅
- **AI Insights v1 + automation** (May 2026): daily synthesis from FactPack,
  per-insight chat, web-cited insights, supply-demand-gap pattern;
  `/api/insights/*` + scheduler `insights_daily` cron ✅
- **OpenClaw / MCP unification** (May 2026): all chat + synthesis + QA traffic
  routes through the OpenClaw gateway; tool calls dispatched via the in-process
  MCP server (`backend/mcp_server.py`) ✅
- **Phase 3** (planned): Paid-source integrations (Aterio licensed feed, NVIDIA
  shipments, Coherent/Lumentum order books, Shovels.ai, Planet/Maxar imagery,
  Bloomberg/NewsAPI)

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
