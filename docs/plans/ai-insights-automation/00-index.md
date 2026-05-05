# AI Insights Automation & Real-Data Synthesis — Plan Index

**Status:** Planning complete, awaiting user review.
**Date:** 2026-05-04
**Owner (product):** Karan (primary stakeholder)
**Scope:** Make the AI Insights tab generate real, data-grounded insights from Postgres on a daily auto-schedule, instead of canned text behind a manual button.

---

## What this folder contains

| # | Doc | Author | Purpose |
|---|---|---|---|
| 00 | `00-index.md` (this file) | orchestrator | One-page synthesis + reading order |
| 01 | `01-prd.md` | pm | Goals, FRs (FR1–FR7), NFRs, acceptance criteria, open questions |
| 02 | `02-research.md` | researcher | 4-question tech-stack investigation; final recommendations table in §G |
| 03 | `03-architecture.md` | architect | Component diagram, hypothesizer module, schema migrations, scheduler wiring, /api/insights/latest, phased rollout, decision log |
| 04 | `04-ux.md` | designer | IA, 8 visual states, InsightCard variants, copy deck, a11y, ASCII wireframes |

**Reading order for a new engineer:** 01 → 03 → 02 (deep-dive) → 04 (frontend handoff). Each doc is self-contained.

---

## The three-line summary of the plan

1. **Brain:** add `backend/agents/insights/hypothesizer.py` that runs ~7 deterministic SQL queries to build a `FactPack`, feed that pack into a single mega LLM synthesis call, and replace the hardcoded `"Candidate insight #N from session bootstrap"` string in `orchestrator.py:395-403` with real hypotheses + supporting rows.
2. **Scheduler:** add one `insights_daily` entry to `JOB_CONFIG` in `backend/pipeline/runner.py` firing at **09:00 UTC** (after the 06:00/06:30/07:00/08:00 ingest cascade), with a headless `_invoke_insights_daily` that drains the orchestrator iterator and counts `InsightCompleteEvent`s.
3. **Frontend:** new `GET /api/insights/latest` endpoint; `AIInsightsTab.tsx` defaults to rendering that snapshot on mount; the "Generate insights" primary CTA at lines 154-169 is demoted to a secondary "Run again" button in the top-right.

---

## Top architectural decisions (consolidated)

Sourced from `02-research.md` §G and finalized in `03-architecture.md` decision log:

| # | Question | Decision | Doc |
|---|---|---|---|
| D1 | Synthesis pipeline | **A1 deterministic FactPack → single mega-call**, not full agentic ToolLoopDriver | research §A.2 |
| D2 | Migration target | A3 hybrid (one bounded `drill_down` per insight) deferred to V1.1 | research §A.2 |
| D3 | Scheduler | APScheduler `JOB_CONFIG` entry, no Celery/k8s | research §B.2 |
| D4 | Cron time | `CronTrigger(hour=9, minute=0)` UTC | research §B.3 |
| D5 | Idempotency | Top-of-job guard on `(created_by='scheduler', cron_run_date=today, status IN running/complete)` | research §B.4 |
| D6 | LLM call shape | One mega call with JSON-schema list output; SSE events fan out from parsed result | research §C.3 |
| D7 | Daily token budget | Hard ceiling 30 K / soft ~12 K; ~$0.07/day at gpt-5.4 list pricing | research §C.4 |
| D8 | Cross-day dedup | pgvector cosine vs last 14 days, threshold 0.85 (already ratified) | research §D.3 |
| D9 | Schema migration | Migration 010: `headline_embedding TYPE vector(3072)`, add `ongoing_of_id`, `token_estimate`, `cron_run_date` | architecture §4 |
| D10 | Wall-clock guard | `asyncio.wait_for(orch.run_session(...), timeout=600)` outside the orchestrator | research §F.2 |
| D11 | Failure persistence | APScheduler `EVENT_JOB_ERROR` + `EVENT_JOB_MISSED` listeners; explicit failed-status write on iterator-raise | research §F.1 |
| D12 | Default-load mechanism | New `GET /api/insights/latest` snapshot endpoint (NOT SSE re-attach) | architecture §6 |
| D13 | Manual button | Demote, do not remove — secondary "Run again" top-right | UX §3 |
| D14 | "Ongoing" treatment | Cyan accent + pill, NOT de-emphasized | UX §3 |
| D15 | Supporting rows surface | Inline expand inside InsightCard, NOT drawer/modal | UX §3 |

---

## Phased rollout (from architecture §10)

| Phase | Deliverable | Closes PRD AC# | Visible to user? |
|---|---|---|---|
| 1 | Hypothesizer + orchestrator wiring + unit tests | AC1 (no "Candidate insight #N"), AC2 (citations) | Yes — manual button now produces real insights |
| 2 | Schema migration 010 + cross-day dedup priming | AC7 (ongoing dedup) | Subtle — duplicates labeled instead of dropped |
| 3 | `insights_daily` scheduler job + idempotency + wall-clock guard | AC4 (scheduler shows next-fire ~09:00 UTC), AC5 (idempotency) | No — runs server-side at 09:00 UTC |
| 4 | `/api/insights/latest` + frontend default-load + button demotion | AC3 (default-load), AC8 (past sessions populated) | Yes — tab now opens with content |
| 5 | Failed-run banner, token accounting column, scheduler event listeners | AC6 (failed runs surfaced, not hidden) | Yes — failure UX visible |

Phase 1 alone closes the most painful problem (canned text) without any schema or scheduler risk. It can ship independently.

---

## Critical files (single list with line refs, current as of 2026-05-04)

Backend:
- `backend/agents/insights/orchestrator.py` — line **167** (`_emitted_headlines = []`), **269** (top try/except), **279** (`_phase_bootstrap_iter`), **339** (`_phase_hypothesize_iter` stub), **395-403** (hardcoded hypothesis), **405** (per-insight error path), **468** (dedup call), **563** (persist helpers)
- `backend/agents/insights/dedup.py` — Jaccard + cosine module; needs `fetch_recent_embeddings()`
- `backend/agents/insights/hypothesizer.py` — **NEW MODULE**
- `backend/agents/weekly_brief.py` — A1 precedent to clone
- `backend/pipeline/runner.py` — `JOB_CONFIG`, `_run_adapter_job` (line **177**), `_invoke_anomaly_detection` (line **235**), `_invoke_weekly_brief` (line **344**)
- `backend/routers/insights.py` — add `GET /latest` endpoint
- `backend/alembic/versions/009_ai_insights.py` — current schema reference (esp. line **54** for pgvector extension, line **93** for `headline_embedding Text`)
- `backend/alembic/versions/010_ai_insight_embedding_vector.py` — **NEW MIGRATION**
- `backend/db/models/` — `AISession`, `AIInsight`, `IngestionRun`

Frontend:
- `frontend/src/components/tabs/ai-insights/AIInsightsTab.tsx` — line **154-169** (button to demote), default-load to add
- `frontend/src/components/tabs/ai-insights/InsightCard.tsx` (or sibling) — add Ongoing variant + supporting-rows expand
- `frontend/src/styles/insightTokens.ts` — 4 new tokens per UX §7

---

## Open questions for the user before implementation kicks off

From `01-prd.md` §9 — these need a yes/no/decision before Phase 1 starts:

1. **Cron time:** confirm 09:00 UTC (PM recommends; research validates).
2. **Manual button:** demote (recommended) vs remove entirely.
3. **Retention:** keep AISessions forever, 90 days, or other?
4. **Auto-retry on fail:** retry once after 1h vs wait until tomorrow (PM recommends "wait until tomorrow" + visible failed-state UI).
5. **OCI billing reality-check:** validate the §C.2 cost estimate against actual OCI line-items after the first week of runs.
6. **`statement_timeout` rollout:** is it safe to set `30s` on the app role, or does some existing UI query need longer? (Architecture §8 risk register flags this.)

---

## Risks at a glance (top 5)

From PRD §11 + architecture §8:

1. **Vector-column migration on a hot DB.** Mitigation: `ai_insight` is empty enough today that `ALTER COLUMN ... TYPE vector(3072) USING NULL` is fast and safe.
2. **Mega-call JSON-schema parse failure.** Mitigation: one-shot reissue of failed indices; on second failure, mark session failed and surface to UI.
3. **Cron firing while ingest backfill is in progress.** Mitigation: 09:00 is well after 08:00 ingest jobs; if a backfill ever exceeds an hour, the FactPack just sees stale data — no crash, just a staler insight.
4. **`statement_timeout` collateral on UI queries.** Mitigation: set per-role for the cron, not globally; or audit existing queries first.
5. **LLM cost surprise.** Mitigation: hard 30K-token ceiling per run + post-flight `token_estimate` column + daily aggregate guard at 3× rolling 14-day mean.

---

## Out of scope (explicit, do not regress)

- No new ingest sources (use what's in Postgres).
- No multi-tenant / per-user insights.
- No email digests / push notifications.
- No mobile layout.
- No changes to underlying data tables.
- No localization or theming beyond reuse of existing tokens.

---

## Next step

User reviews this index → opens 01/02/03/04 as needed → answers the 6 open questions in §"Open questions" above → implementation team picks up at Phase 1 (hypothesizer + orchestrator wiring), which can ship without any schema or scheduler change and immediately removes the "Candidate insight #N" embarrassment.
