# Counterparty Pies Feature — Infra Review

**Date:** 2026-05-08
**Scope:** Confirm whether the new `GET /api/companies/{id}/counterparties` endpoint
and the two new React components (`CounterpartyPies.tsx`, `CounterpartyPieCard.tsx`)
require any Docker / CI / deployment changes.

## Verdict: No changes required.

## Evidence

1. **docker-compose.openclaw.yml** (only compose file in the repo) provisions
   `openclaw-gateway` + `ollama` + `ollama-pull` only. No backend or frontend
   service is built or COPYed here, so no volume/COPY edits apply.
2. **No Dockerfile** exists for backend or frontend (`Glob **/Dockerfile*` returns
   only `node_modules` hits). Nothing to update.
3. **No CI configured.** `.github/workflows/` does not exist. No pytest /
   `npm run build` / `tsc --noEmit` job to wire up.
4. **`start.sh`** runs `uvicorn main:app --reload` and `npm run dev` (Vite).
   - Backend: `backend/main.py:29` already imports `routers.companies` and
     `main.py:136` calls `app.include_router(companies_router)`, so the new
     `GET /api/companies/{id}/counterparties` route is registered automatically
     when `companies.py` is edited.
   - Frontend: Vite resolves `src/components/tabs/companies/Counterparty*.tsx`
     transitively from `CompaniesTab.tsx`. New files are picked up on the next
     reload with no config change. Recharts is already in `package.json`.
5. **No new dependencies, env vars, or migrations** per the task description —
   confirmed against `backend/requirements.txt` and `alembic/versions/` (no new
   revision needed).

## Action: none. Feature ships with the application code change alone.
