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

- **Phase 0** (current): Infrastructure foundation -- DB, migrations, routers, envelopes
- **Phase 1**: Real data ingestion adapters (Aterio, EIA, RCRA, ECHO)
- **Phase 2**: Company resolution + entity linking
- **Phase 3**: LLM extraction agents (EDGAR, transcripts)
- **Phase 4**: Triangulation engine + executive brief
