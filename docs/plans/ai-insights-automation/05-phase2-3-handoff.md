# Implementation Handoff: Phases 2 + 3 (AI Insights Automation)

**Status:** Ready for build
**Owner:** Engineering
**Date:** 2026-05-05
**Predecessors:**
- PRD: [`01-prd.md`](./01-prd.md)
- Architecture: [`03-architecture.md`](./03-architecture.md) (esp. §4, §5, §6, §10/D5, D7, D9, D11, D13)

> This is a tight handoff, not a re-statement of the PRD or architecture.
> Where the PRD/arch covers something, we link to it. The only authoritative
> divergences from the architecture decision log are recorded under
> "Decision overrides" below.

---

## 1. Scope

**In scope (Phase 2 — schema migration + dedup priming):**

- New Alembic migration that converts `ai_insight.headline_embedding` to
  `vector(3072)`, adds `ai_insight.ongoing_of_id`, adds
  `ai_insight.supporting_row_ids` (JSONB), adds `ai_session.token_estimate`,
  adds `ai_session.cron_run_date`. See arch §5.1.
- SQLModel updates in `backend/agents/insights/db/models.py` to match.
- `dedup.fetch_recent_embeddings(db, days=14)` for cross-day priming.
- Replace the Phase 1 stop-gap that wrote a `_Sources: row_ids=...` footer
  into `ai_insight.body`; write to the new JSONB column instead.

**In scope (Phase 3 — daily scheduler with retry override):**

- `JOB_CONFIG["insights_daily"]` entry in `backend/pipeline/runner.py`.
- `run_insights_daily_job` and `_invoke_insights_daily` per arch §6.2-§6.3.
- Idempotency guard keyed on `(created_by='scheduler', cron_run_date=today)`.
- Outer wall-clock guard `asyncio.wait_for(timeout=600)` per attempt.
- **Retry policy override** (see §3 below): up to 2 retries, 60s sleep.
- `_JOB_FUNCTIONS` registration so the scheduler dispatcher can find it.

**Out of scope:**

- No frontend changes. `AIInsightsTab.tsx`, `useInsightStream.ts`, SSE event
  shapes — none of it gets touched in Phase 2/3.
- No new API. `GET /api/insights/latest` is Phase 4 work, not this handoff.
- No Phase 1 changes. `hypothesizer.py`, `_phase_bootstrap_iter`,
  `_phase_hypothesize_iter`, `_phase_verify_and_synthesize_iter` already
  landed; do not re-touch.
- No HNSW/ivfflat vector index. Per arch D9, deferred to a future migration
  014 once `ai_insight` row count justifies it.
- No retention/pruning job (PRD OQ3) — separate workstream.

---

## 2. User Stories

**US-2.1 — Cross-day "ongoing" linkage (closes PRD AC8)**
> As an analyst, when I open the AI Insights tab the morning after a scheduled
> run, ongoing stories are linked back to their prior-day version so I can see
> a thread instead of a re-emitted headline.

Acceptance:
- A day-N+1 insight whose headline embedding has cosine >= 0.85 against any
  insight from a successful session in the last 14 days is persisted with
  `ai_insight.ongoing_of_id = <prior insight uuid>`.
- The duplicate is still persisted (FR7: ongoing insights still render);
  it is not dropped.
- The dedup priming source is `dedup.fetch_recent_embeddings(db, days=14)`.

**US-3.1 — Scheduled fire-time (closes PRD AC3)**
> As an operator, the APScheduler dispatcher fires `insights_daily` at
> 09:00 UTC daily.

Acceptance:
- `JOB_CONFIG["insights_daily"]["trigger"]` is `CronTrigger(hour=9, minute=0)`.
- `JOB_CONFIG["insights_daily"]["phase"]` is `2`.
- `_JOB_FUNCTIONS["insights_daily"]` resolves to `run_insights_daily_job`.
- `apscheduler.get_jobs()` includes a job with id `insights_daily` and a
  `next_run_time` matching the next 09:00 UTC.

**US-3.2 — Idempotency across process restarts (closes PRD AC4, AC5)**
> As an operator, restarting the backend or manually re-firing the job within
> the same UTC day produces exactly one successful scheduler-created
> `AISession` for that date.

Acceptance:
- The guard at the top of `_invoke_insights_daily` performs
  `SELECT 1 FROM ai_session WHERE created_by='scheduler' AND cron_run_date=today
   AND status IN ('running','complete')` and returns
  `{"fetched":0,"stored":0,"skipped":1}` without touching the LLM if a row
  exists.
- `_persist_session_start` writes `created_by` and `cron_run_date` whenever
  `filters` contains a `"cron_run_date"` key (see §3 override clarification).
- A second invocation in the same day does not produce a second
  `status='complete'` row for that date.

**US-3.3 — Bounded retry on transient failure (overrides PRD OQ4 / arch D13)**
> As an operator, transient LLM/network failures during the daily run are
> retried up to 2 times with 60s sleep between attempts; persistent failures
> still produce a `status='failed'` AISession and fire APScheduler's
> `EVENT_JOB_ERROR` listener.

Acceptance:
- `_invoke_insights_daily` retries the inner orchestrator drain up to **2**
  times after the initial attempt (so up to **3 attempts total**).
- Sleep between attempts is `await asyncio.sleep(60)` (linear, not
  exponential).
- The outer `asyncio.wait_for(timeout=600)` guard applies **per attempt**,
  not across all attempts.
- After the 3rd consecutive failure, the most recent `AISession` row is left
  with `status='failed'` and the wrapper re-raises the underlying exception
  so APScheduler's `EVENT_JOB_ERROR` listener (added in arch §6.5) fires and
  logs `scheduler.job_error`.
- The idempotency guard is checked **once at the top**, before retries — a
  second daily fire on a process restart still skips, regardless of retry
  state on the first.

**US-2.2 — JSONB citations (cleanup of Phase 1 stop-gap)**
> As a developer, `supporting_row_ids` for each insight live in a typed
> JSONB column on `ai_insight`, not as an ad-hoc footer string baked into
> `body`.

Acceptance:
- `ai_insight.supporting_row_ids` is a JSONB column (nullable).
- `_persist_insight` writes to that column directly.
- `_persist_insight` no longer appends `\n\n_Sources: row_ids=[...]` to
  `body`. The Phase 1 footer is gone from new rows; existing rows are not
  back-migrated.
- `body` returned over the existing API does not contain the footer for any
  session created after migration 013 lands.

**US-2.3 — Round-trippable migration (PRD NFR5)**
> As a maintainer, the migration is reversible: `alembic upgrade head` then
> `alembic downgrade -1` then `alembic upgrade head` leaves the schema
> bit-identical to the pre-upgrade state at each step.

Acceptance:
- `013_ai_insight_embedding_vector.upgrade()` and `downgrade()` are both
  implemented.
- A round-trip test compares `pg_dump --schema-only` output before and after
  upgrade/downgrade/upgrade and asserts the diff is empty (modulo
  `alembic_version` row).
- Indices added in upgrade are dropped first in downgrade.

---

## 3. Decision overrides vs PRD / architecture

These are the points where this handoff intentionally diverges from the
architecture decision log or clarifies an ambiguity in the prompt. All
implementers should treat this section as authoritative.

### D13 RETRY (override of arch D13 "no retry")

- **Architecture said:** D13 = "No retry. PRD OQ4 + research §F.2: stochastic
  LLM cost compounding is worse than waiting until tomorrow."
- **User override (2026-05-05):** allow up to **2 retries with 60s linear
  sleep between attempts**, scoped strictly to `_invoke_insights_daily`.
- **Outer wall-clock guard:** `asyncio.wait_for(..., timeout=600)` continues
  to apply **per attempt** (arch D11 unchanged).
- **Failure path after retries exhausted:**
  1. `AISession.status` flipped to `'failed'`.
  2. Underlying exception re-raised so APScheduler's `EVENT_JOB_ERROR`
     listener (arch §6.5) fires.
- **Cost note:** worst-case cost is now ~3x a single run. Mitigated by the
  `token_estimate` post-flight log; see Risk #2.

### Migration number is 013 (not "010")

The original prompt referenced "010" but the codebase HEAD already has
migrations through `012_track_c_power_relevance.py`. Architecture §5.1 has
this right at 013. The new file is
**`backend/alembic/versions/013_ai_insight_embedding_vector.py`**.

### Models live under `agents/insights/db/`

`AISession` and `AIInsight` SQLModel classes are defined in
`backend/agents/insights/db/models.py`, **not** the project-wide
`backend/db/models.py`. Architecture §5.3 has this right; calling it out here
because the prompt mentioned `backend/db/models.py`.

### `cron_run_date` write trigger

`_persist_session_start` writes `cron_run_date=current_date` whenever
`filters` contains a `"cron_run_date"` key. This is more explicit than
"only when focus=daily-cron" and makes the idempotency contract testable
without coupling it to the `focus` string. The scheduler call passes
`filters={"focus": "daily-cron", "created_by": "scheduler",
"cron_run_date": today}` so both the existing focus-based code path and
the explicit-key code path remain coherent.

---

## 4. Acceptance criteria (consolidated)

Tied back to PRD AC# where applicable.

- **Migration round-trip:** `alembic upgrade head` -> `alembic downgrade -1`
  -> `alembic upgrade head` succeeds and leaves schema bit-identical. (PRD
  NFR5)
- **Job registered:** running
  `python -c "from pipeline.runner import JOB_CONFIG; print(JOB_CONFIG['insights_daily'])"`
  prints a dict with `CronTrigger(hour=9, minute=0)`, adapter
  `_insights_daily`, and `phase=2`. (PRD AC3)
- **Existing tests still pass:** the full backend test suite is green; no
  regression in tests that import `SURVEY_ENDPOINTS`.
- **New unit tests, all green:**
  - (a) Migration round-trip — schema-diff zero (PRD NFR5)
  - (b) `dedup.fetch_recent_embeddings` returns rows from the last 14 days
        only, ordered by recency, and excludes failed sessions (PRD AC8)
  - (c) Idempotency — second `_invoke_insights_daily` on the same UTC day
        returns `skipped:1` and does not call the LLM (PRD AC5)
  - (d) Success path drains exactly **7** `InsightCompleteEvent`s when the
        orchestrator stub yields 7 (PRD AC2 plumbing)
  - (e) Retry success — first attempt raises, second attempt succeeds; final
        result is `status='complete'` and `attempt_count=2` is logged
  - (f) Retry exhaustion — three consecutive failures leave the `AISession`
        with `status='failed'`, raise the exception out of
        `_invoke_insights_daily`, and trigger the `EVENT_JOB_ERROR`
        listener (PRD AC4)

---

## 5. File-touch list

### New files

- **NEW** `backend/alembic/versions/013_ai_insight_embedding_vector.py`
  - Drops `ai_insight.headline_embedding` (Text), re-adds as `vector(3072)`.
  - Adds `ai_insight.ongoing_of_id` (UUID FK to `ai_insight.id`,
    ondelete SET NULL) + `ix_ai_insight_ongoing_of_id`.
  - Adds `ai_insight.supporting_row_ids` (JSONB, nullable).
  - Adds `ai_session.token_estimate` (Integer, nullable).
  - Adds `ai_session.cron_run_date` (Date, nullable) +
    `ix_ai_session_created_by_cron_run_date`.
  - Pre-flight: log `SELECT COUNT(*) FROM ai_insight` so a non-empty table
    is loud (Risk #1 mitigation).
- **NEW** `backend/tests/test_dedup_cross_day.py`
- **NEW** `backend/tests/test_orchestrator_supporting_row_ids.py`
- **NEW** `backend/tests/test_runner_insights_daily.py` — covers ACs (c),
  (d), (e), (f).
- **NEW** `backend/tests/test_migration_013_round_trip.py` — covers AC (a).

### Edits

- **EDIT** `backend/agents/insights/db/models.py`
  - On `AIInsight`: add 3 columns (`headline_embedding` switches to
    `pgvector.sqlalchemy.Vector(3072)` where the optional dep is present,
    falling back to typed-Any with raw-SQL writer; `ongoing_of_id` UUID;
    `supporting_row_ids` JSONB).
  - On `AISession`: add 2 columns (`token_estimate` Integer,
    `cron_run_date` Date).

- **EDIT** `backend/agents/insights/orchestrator.py`
  - `_persist_session_start` (lines 679-697): when `filters` contains a
    `"cron_run_date"` key, write `created_by` and `cron_run_date` onto the
    new `AISession` row. Additive; no existing call site breaks.
  - `_persist_insight` (lines 743-783): drop the
    `\n\n_Sources: row_ids=[...]` footer concatenation onto `body`; write
    `supporting_row_ids` directly into the new JSONB column instead.

- **EDIT** `backend/agents/insights/dedup.py`
  - Add `async def fetch_recent_embeddings(db: AsyncSession, days: int = 14)
    -> list[tuple[str, list[float]]]:` that selects
    `(headline, headline_embedding)` from `ai_insight` joined to successful
    `ai_session` rows in the last `days` days. Existing `is_duplicate`
    signature unchanged.

- **EDIT** `backend/pipeline/runner.py`
  - Add `JOB_CONFIG["insights_daily"]` entry per arch §6.1
    (`CronTrigger(hour=9, minute=0)`, adapter `_insights_daily`, phase 2,
    enabled True).
  - Add `run_insights_daily_job` near the other `run_*_job` functions.
  - Add `_invoke_insights_daily(session)` with the retry loop described in
    §3 above (max 2 retries, 60s sleep, per-attempt 600s wait_for).
  - Add `_JOB_FUNCTIONS["insights_daily"] = run_insights_daily_job`.

---

## 6. Risks / open items

1. **Vector-cast migration requires empty column.** `ALTER TABLE ai_insight
   DROP COLUMN headline_embedding; ADD COLUMN ... vector(3072) NULL;`
   destroys any existing values. Per arch R6 / PRD R6 the column is empty in
   production today. Mitigation: emit a pre-flight log line with
   `SELECT COUNT(*) FROM ai_insight WHERE headline_embedding IS NOT NULL` so
   a non-empty migration is loud, not silent.

2. **Retry policy compounds LLM cost.** Worst case is 3x the single-run
   token bill (~30K x 3 = 90K tokens). Mitigated by the post-flight
   `ai_session.token_estimate` write; alert thresholds: log a warning if
   per-day total `SUM(token_estimate)` for `created_by='scheduler'` exceeds
   60K tokens.

3. **`SURVEY_ENDPOINTS` is still imported by tests.** Per arch D16, keep the
   constant in `orchestrator.py` even though Phase 1 stopped calling it.
   Removing it cascades into multiple test files. Do not delete.

4. **`_persist_session_start` previously only stored `focus`.** Adding
   `created_by` and `cron_run_date` writes is additive; no existing call
   site breaks because both new fields are nullable and only written when
   the filter keys are present.

5. **Multi-worker race.** The application-level idempotency guard is a
   non-atomic `SELECT then INSERT`. Two simultaneous workers firing the
   same cron *could* both pass the guard. v1 deploys a single worker, so
   this is acceptable; arch §5.2 (migration 014) provides the partial
   unique index defense-in-depth for v1.1 multi-worker.

---

*End of handoff.*
