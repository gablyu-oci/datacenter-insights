# Company Directory Search/Filter/Pagination — Infra Impact

Scope of change:
- Backend: `backend/routers/companies.py` — extend `list_companies` with `q`
  (ILIKE), `public_private`, `direction`; widen `order_by` regex. No new
  endpoints, no new tables/migrations, no new env vars.
- Frontend: `frontend/src/components/tabs/CompaniesTab.tsx` — state-driven
  server fetch, 250ms debounced search, pagination. No new dependencies.

## Verdict: no infra changes needed.

| Area        | Justification (one line)                                                                                       |
|-------------|----------------------------------------------------------------------------------------------------------------|
| Docker      | `docker-compose.openclaw.yml` provisions only the OpenClaw gateway + Ollama; it does not reference the FastAPI `/api/companies` endpoint, query params, or fetch caching. |
| Postgres    | README confirms PostgreSQL 16 is host-managed (not containerized); no schema change, no migration, no new index required for an additive query-param surface on an existing route. |
| CI          | No `.github/workflows/` directory exists in the repo — no pytest or vitest pipeline to update; new `test_*.py` files are picked up by pytest's default rootdir discovery and `frontend/package.json`'s `vitest run` scans by its default glob. |
| Env vars    | README env-var table (`DATABASE_URL`, `ALLOWED_ORIGINS`, `MOCK_DATA`, `EDGAR_USER_AGENT`, `LLAMA_STACK_URL`, `VITE_API_BASE_URL`, `VITE_GOOGLE_MAPS_API_KEY`) is unchanged; no new secrets to add to `backend/.env` or `frontend/.env.local`. |
| nginx       | No reverse proxy config is committed to the repo; `start.sh` runs uvicorn on :8000 and Vite on :5173 directly, and `VITE_API_BASE_URL` documents the relative-path / reverse-proxy contract — extending an existing path with query params requires no proxy rule change. |

## Observations (informational, no action)

- `start.sh` runs `alembic upgrade head` on every launch; since this change
  adds no migration, the boot path is unaffected.
- The new `q` ILIKE filter on `companies.name` is unindexed today. At the
  current row count (low hundreds) this is fine; revisit only if the table
  grows past ~50k rows or p95 latency degrades.
- Frontend debounce (250ms) bounds request rate per keystroke; no rate-limit
  or caching middleware change required.
