# PRD: AI Insights Automation & Real-Data Synthesis

**Status:** Draft for review
**Owner:** PM (strategic-insights-tool)
**Primary stakeholder:** Karan
**Date:** 2026-05-04
**Target release:** v1 of automated insights (no new ingestion sources)

---

## 1. Overview

The strategic-insights-tool is a FastAPI + React competitive-intelligence
prototype that tracks hyperscaler datacenter and power buildout against
OCI. The "AI Insights" tab is the executive-facing surface that should
turn the underlying Postgres dataset (power deals, permits, EDGAR
filings, anomalies, etc.) into a small set of dated, dated-and-cited
narrative insights.

The plumbing for that tab is already in place end-to-end:

- An orchestrator runs at `backend/agents/insights/orchestrator.py`.
- It persists `AISession` and `AIInsight` rows.
- It streams SSE events to a working React tab.

Despite that, the feature is non-functional as an executive product
today, for two related reasons:

1. **The synthesis loop is not actually grounded in data.** It hardcodes
   the hypothesis string and passes `supporting_rows=[]` into the
   synthesis skill, which causes the LLM to emit canned generic copy
   (e.g. "Candidate insight #1 from session bootstrap.").
2. **The tab requires a manual click and never auto-runs.** There is no
   APScheduler entry for a daily insights job, and the React tab waits
   for a user to press "Generate insights" before showing anything.

This PRD scopes the v1 fix: real-data synthesis driven by a daily
schedule, with the AI Insights tab defaulting to today's auto-run
session on load.

---

## 2. Goals & Non-Goals

### 2.1 Goals

- **G1.** Replace the hardcoded "Candidate insight #N from session
  bootstrap" path with synthesis that consumes actual rows from the
  project Postgres tables.
- **G2.** Run the insight pipeline automatically once per day, after the
  morning ingest jobs (EDGAR, permits, EPA ECHO) have settled.
- **G3.** Make the AI Insights tab default to the latest auto-run
  session on page load, with no click required.
- **G4.** Make every emitted insight cite at least one concrete
  supporting row (deal id, filing accession, permit id, anomaly id,
  etc.) so a reader can trace the claim back to the source.
- **G5.** Surface failures: a failed daily run shows up as a
  `status=failed` session in the UI, not a silent gap.

### 2.2 Non-Goals

- **NG1.** No new ingestion sources. We use what's already in Postgres.
- **NG2.** No multi-tenant or per-user insights. One global daily run.
- **NG3.** No push notifications, email digests, or Slack delivery in
  v1. Tab-based consumption only.
- **NG4.** No schema changes to the underlying domain tables (deals,
  permits, filings, anomalies). Only `AISession` / `AIInsight` may
  evolve.
- **NG5.** No reworking of the SSE event protocol. The existing event
  shapes are sufficient and the frontend already handles them.

---

## 3. Background & Problem Statement

### 3.1 Why "canned insights" are useless to Karan

Karan is the primary stakeholder driving this tool. He uses it to
prepare for executive conversations about hyperscaler power buildout.
His expectation is that opening the tool in the morning gives him five
to seven *novel, dated, defensible* observations he can repeat in a
meeting.

A line like "Candidate insight #1 from session bootstrap." has the
opposite effect: it actively erodes trust in the rest of the tool.
There is no way to tell whether the other tabs are also placeholders.
Until insights are grounded in concrete rows with concrete citations,
the AI Insights tab is worse than not having it at all.

### 3.2 Why daily auto-run beats click-to-generate

A manual "Generate" button is the correct UX for a notebook or an
analyst tool. It is the wrong UX for an executive intelligence tool:

- The exec opens the tab once a day, typically before a meeting. They
  do not want to wait two to five minutes for a stream to finish.
- They cannot reason about *why* today's insights differ from
  yesterday's if the run timestamp is "30 seconds ago, on demand"
  instead of "this morning, scheduled".
- A daily cadence creates a stable, citeable artifact ("the 2026-05-04
  insight set says X").

A scheduled run also lets us bound and observe daily LLM cost in a way
on-demand runs cannot.

### 3.3 The four critical code locations

The architect should look at these directly. They are the load-bearing
spots for v1.

1. `backend/agents/insights/orchestrator.py:395-403` — synthesis call
   site that hardcodes hypothesis and passes `supporting_rows=[]`.
2. `backend/agents/insights/orchestrator.py:279` — `_phase_bootstrap_iter`
   hits eight survey endpoints but only counts rows; it does not retain
   them.
3. `backend/agents/insights/orchestrator.py:339` — `_phase_hypothesize_iter`
   is an admitted stub; it emits a single reasoning event and no real
   hypotheses.
4. `backend/pipeline/runner.py:53-110` — APScheduler job table; eleven
   jobs run today (edgar_daily 06:00, permits_state 07:00, EPA echo
   08:00, anomaly_detection_nightly, weekly_brief, etc.), but no
   `insights_daily`.

---

## 4. Personas & User Stories

### 4.1 Karan (primary executive viewer)

- **As Karan, I want to open the AI Insights tab in the morning and
  immediately see today's five-to-seven insights, so that I can prepare
  for a meeting without waiting for a stream to complete.**
- **As Karan, I want every insight to point at the concrete rows it is
  based on, so that I can defend the claim if asked.**
- **As Karan, I want to know when the insights were generated, so that
  I am not quoting stale data in a meeting.**

### 4.2 Internal viewer (analyst / engineer)

- **As an internal viewer, I want the same default-loaded behavior, so
  that I do not have to remember a workflow.**
- **As an internal viewer, I want a "Run again" affordance, so that if
  data was reingested mid-day I can force a fresh run without waiting
  for tomorrow.**
- **As an internal viewer, I want to browse prior days' insight
  sessions, so that I can see how the narrative is evolving.**

### 4.3 Operator (whoever is on call for the prototype)

- **As an operator, I want a failed daily run to show up as a
  `status=failed` session in the UI and in logs, so that I notice
  before Karan does.**
- **As an operator, I want each run to log phase timings and token
  usage, so that I can keep daily LLM spend under a defined ceiling.**

---

## 5. Functional Requirements

### FR1. Daily auto-run

The pipeline runs the AI Insights orchestrator on a daily schedule
without any user action.

- A new APScheduler job `insights_daily` is added to the
  `backend/pipeline/runner.py` job table.
- Proposed fire time: 09:00 UTC, after `edgar_daily` (06:00),
  `permits_state` (07:00), and `epa_echo` (08:00) so the underlying
  data is fresh.
- The job invokes the same orchestrator entrypoint a manual run uses,
  with `max_insights=7` and the production model
  (`oci/openai.gpt-5.4`).
- Job exit status is recorded; uncaught exceptions are logged but do
  not crash the scheduler.

### FR2. Real-data citations

Every emitted insight cites at least one concrete supporting row.

- The bootstrap phase retains the rows it pulls (not just counts) so
  downstream phases have something to ground on.
- The hypothesize phase produces typed hypotheses tied to the rows it
  drew them from.
- The synthesis call passes `supporting_rows=[<concrete row refs>]`
  rather than `[]`.
- Each `AIInsight` row persists the list of source row identifiers
  (table + primary key, or accession + section, or anomaly id) it
  cites.
- The frontend renders those citations next to each insight (the SSE
  citation event shape already supports this; see
  `frontend/src/types/sseEvents.ts`).

### FR3. Default to latest auto-run on tab load

When the user navigates to the AI Insights tab, the tab loads the most
recent `status=succeeded` `AISession` automatically and renders its
insights.

- No "Generate insights" click required for the default path.
- If no session exists yet (cold start, first day), the tab shows a
  clear empty state ("No insights yet. The next scheduled run is at
  09:00 UTC.") rather than a stuck spinner.
- If the most recent session is `status=failed`, the tab shows that
  session with its failure reason and offers "Run again".

### FR4. Past sessions browser

The tab exposes a way to see prior days' runs.

- A "Past sessions" affordance (dropdown, sidebar, or list — UX
  decision is downstream) lists previous `AISession` rows by date.
- Selecting a past session loads that session's insights into the main
  view in read-only mode.
- Past-session view clearly labels itself as historical (e.g. "Insights
  from 2026-05-03").

### FR5. Manual "Run again" demoted, not removed

- The current primary "Generate insights" CTA is demoted to a secondary
  action labeled "Run again" or "Refresh now".
- It triggers an ad-hoc run that creates a new `AISession` and streams
  via SSE in the same way today's manual flow does.
- Recommendation: keep the affordance, but place it as a header
  utility (icon + tooltip) rather than a center-of-page CTA.

### FR6. Failed runs are first-class

- A run that fails for any reason (LLM error, DB error, timeout, killed
  process) leaves an `AISession` row with `status=failed` and a
  human-readable failure reason.
- The tab surfaces failed sessions in the past-sessions list and on
  default load if the most recent session is failed.
- No partial / orphan insights are visible to the user from a failed
  run; either the run produced its insights atomically before the
  failure, or those insights are hidden behind the session status.

### FR7. Deduplication across days

If today's candidate insight is materially identical to one emitted on
a recent prior day, we do not double-publish it.

- "Materially identical" is defined as: same headline cluster (cosine
  similarity above a configurable threshold) **and** overlapping
  citation set (at least one shared supporting row).
- A duplicated insight is marked `ongoing` (or similar status flag) on
  the new day's session, with a back-reference to the prior insight.
- Ongoing insights still render on today's tab so the daily set feels
  complete, but they are visually distinguished from net-new ones.

---

## 6. Non-Functional Requirements

### NFR1. Cost ceiling

- Daily run is bounded by `max_insights=7` and the existing tool-call
  cap in the orchestrator.
- A configurable per-run token budget (input + output) is enforced; if
  the budget is exhausted, the run terminates gracefully and emits
  whatever insights it had, marking the session as
  `status=succeeded_partial` (or equivalent).
- Target: under a small dollar amount per day at production model
  rates. Exact ceiling to be set by the architect based on a dry-run
  measurement.

### NFR2. Wall-clock budget

- Target end-to-end runtime under five minutes for the daily job.
- The existing `_wall_clock_exceeded()` mechanism in the orchestrator
  is the enforcement point.

### NFR3. Idempotency

- If `insights_daily` is retried (manual rerun of the scheduler, pod
  restart, etc.) within the same UTC day, it must not produce two
  succeeded `AISession` rows for that date.
- Implementation guidance (architect's call): a unique constraint on
  `(date, source='scheduled')`, or a check at job start, or an advisory
  lock. Manual "Run again" is exempt — those are explicitly ad-hoc and
  can coexist with the day's scheduled run.

### NFR4. Observability

- Each run emits structured logs for: phase entered, phase duration,
  rows retrieved, LLM calls made, tokens in / out, total wall clock.
- Logs are keyed by `session_id` so a single run is greppable.
- Log keys follow the existing
  `ai_insights.orchestrator.<event>` pattern already used in
  `orchestrator.py`.

### NFR5. Backward compatibility

- The SSE event protocol does not change. Existing frontend handlers
  continue to work for both manual and scheduled runs.
- The `AISession` and `AIInsight` schemas may evolve, but only
  additively (new nullable columns); no destructive migrations.

---

## 7. Acceptance Criteria

These are concrete and testable. Each is a pass/fail check.

### AC1. No canned strings

- Open the AI Insights tab. Inspect the rendered text and the rows in
  `ai_insight` for the most recent session.
- The string `"Candidate insight #"` does not appear anywhere in
  insight headlines, bodies, or hypotheses for that session, nor in any
  session created after this feature ships.

### AC2. Default load shows fresh, cited insights

- Open the AI Insights tab cold (clear local state).
- Within two seconds the tab shows a session that was generated within
  the last 24 hours.
- That session has between five and seven insights.
- Each insight has at least one citation that links to a concrete
  underlying row (deal, permit, filing, anomaly, etc.).

### AC3. Scheduled job is registered

- Run the scheduler introspection (`apscheduler` `get_jobs()`).
- The list contains a job with id `insights_daily`.
- Its `next_run_time` is the next 09:00 UTC (or whatever final cron
  time is decided in section 9).

### AC4. Failed run surfaced, no orphan partials

- Kill the scheduled job mid-run (e.g. `kill -9` the worker, or inject
  a synthetic exception after two insights have been emitted).
- The corresponding `AISession` row has `status=failed` and a non-null
  failure reason.
- The tab, on load, does not show partial insights as if the run
  succeeded. Either it shows the prior succeeded session as the
  default, or it shows the failed session with a clear error UI — but
  it does not silently render two insights as "today's set".

### AC5. Idempotent retries

- Run `insights_daily` twice in succession on the same UTC day (manual
  trigger of the scheduled job, not the "Run again" button).
- Exactly one `succeeded` scheduled `AISession` exists for that date.

### AC6. Past sessions browsable

- After at least two daily runs have happened, open the tab.
- The past-sessions affordance lists both, dated.
- Selecting yesterday's session renders yesterday's insights in
  read-only mode.

### AC7. Manual "Run again" still works

- With a fresh scheduled session loaded, click "Run again".
- A new SSE-streamed `AISession` is created (distinct id, distinct
  timestamp), tagged as ad-hoc / manual.
- The previous scheduled session is preserved.

### AC8. Deduplication marks ongoing

- Construct a scenario where day N+1 would emit an insight whose
  headline and at least one citation overlap with one from day N.
- On day N+1 the duplicated insight is marked `ongoing` and links back
  to the day-N insight.
- It still renders, but is visually distinguished from net-new
  insights.

### AC9. Observability

- Tail logs during a run.
- Each phase boundary is logged with a duration.
- Total tokens in / out are logged once at session end.
- All log lines for the run share the same `session_id`.

---

## 8. Out of Scope (Explicit)

- New ingestion sources. The pipeline draws only from data already
  present in Postgres at run time.
- Schema changes to domain tables (deals, permits, filings,
  anomalies). Only AI-side tables (`AISession`, `AIInsight`, and
  related) may evolve, additively.
- Multi-tenant insights (per-user, per-team, per-region). One global
  daily run.
- Push delivery: no email digest, no Slack post, no webhook in v1.
- Re-architecting the SSE event protocol or the React tab structure.
- LLM provider changes. We ship on the configured `oci/openai.gpt-5.4`
  model.
- Authoring tools for analysts to hand-curate insights. Out of v1.
- Advanced analytics on the insights themselves (which insights got
  read, dwell time, etc.). Out of v1.

---

## 9. Open Questions

These need a decision from the user (or designated owner) before the
architect kicks off implementation.

### OQ1. Cron time

**Proposal:** 09:00 UTC.

Rationale: morning ingest jobs run at 06:00 (`edgar_daily`), 07:00
(`permits_state`), and 08:00 (`epa_echo`). 09:00 UTC gives all three an
hour of slack and lands the result well before the US East Coast
workday begins.

Alternatives: 10:00 UTC (more slack at the cost of later read-time);
12:00 UTC (post-EU lunch, pre-US morning).

**Decision needed:** Confirm 09:00 UTC or pick an alternative.

### OQ2. Manual button: remove or demote?

**Proposal (PM recommendation):** Demote, do not remove.

Rationale: removing the button entirely closes off a useful internal
debugging path and forces analysts to wait until tomorrow if they
ingest a corrected dataset mid-day. Demoting it (header utility, not
center-of-page CTA) preserves the workflow without competing with the
default-load experience.

**Decision needed:** Confirm demote, or commit to remove.

### OQ3. Retention for old AISessions

**Proposal:** Keep 90 days of full sessions and insights; older
sessions get their per-insight body text and tool-call traces pruned
but their headlines and citations retained for cross-day dedup.

Alternatives: keep forever (simplest, grows unbounded); keep 30 days
(matches typical exec memory window); keep 365 days (annual review).

**Decision needed:** Pick a retention number and a pruning strategy.

### OQ4. Auto-retry on failure?

**Proposal:** No auto-retry in v1. A failed run waits until the next
day's scheduled fire. The "Run again" button is the manual escape
hatch.

Rationale: auto-retry on a stochastic LLM pipeline can compound cost
and produce confusing duplicate sessions. We would rather see the
failure and fix it than mask it.

Alternatives: one retry after 30 minutes; retry up to three times with
exponential backoff.

**Decision needed:** Confirm no auto-retry, or pick a retry policy.

### OQ5. Dedup similarity threshold

The deduplication rule in FR7 hinges on a similarity threshold. The PM
recommendation is to start with a conservative threshold (high
similarity required to mark `ongoing`) and tune from real data after
two weeks of daily runs.

**Decision needed:** Architect to propose a starting threshold; PM and
stakeholder to sign off after first week of production runs.

### OQ6. What counts as a "supporting row"?

For citation purposes, we need an unambiguous answer to: when an
insight is grounded in a derived metric (e.g. an aggregate over the
deals table), is the citation the metric, the underlying rows, or
both?

**PM recommendation:** Both. The insight cites the metric (with the
SQL-equivalent provenance already captured in the orchestrator's tool
trace) and the top-N underlying rows that drove it.

**Decision needed:** Architect to formalize the citation schema in the
design doc.

---

## 10. Success Metrics

- **Primary:** Karan opens the tab on N consecutive mornings without
  pressing any button and gets fresh, cited, novel insights N times.
  Target: 5 of 5 in the first business week post-launch.
- **Quality:** Zero "Candidate insight #N from session bootstrap"
  strings emitted post-launch. Tracked via log scan.
- **Reliability:** At least 90 percent of scheduled daily runs land in
  `status=succeeded` over a rolling 30-day window.
- **Latency:** Median scheduled-run wall clock under five minutes.
- **Cost:** Daily LLM spend stays under the ceiling set in NFR1
  (architect to populate after dry run).
- **Citation coverage:** 100 percent of emitted insights have at least
  one citation. Tracked via DB query on `ai_insight`.

---

## 11. Risks

### R1. Synthesis still produces low-quality insights even with real rows

Even when grounded, an LLM may emit shallow or repetitive insights.
**Mitigation:** the dedup rule (FR7) catches near-duplicates; the
seven-insight cap bounds noise; we plan a one-week tuning window post
launch (OQ5).

### R2. Daily LLM cost grows unexpectedly

Tool-call expansion under real data may push tokens up.
**Mitigation:** NFR1 token budget; observability in NFR4; ceiling
enforced at run termination, not after the fact.

### R3. Dedup is too aggressive and hides genuine repeated stories

A real ongoing trend (e.g. "Meta keeps signing nuclear PPAs") legitimately
appears multiple days running. Marking it `ongoing` is the right call,
but if it is hidden entirely the tab feels stale.
**Mitigation:** FR7 explicitly says ongoing insights still render, just
visually differentiated.

### R4. Scheduled and manual runs collide

A user clicks "Run again" while the 09:00 scheduled run is still
streaming.
**Mitigation:** the orchestrator already supports concurrent sessions;
each session has its own id. Idempotency in NFR3 only applies within
the scheduled-run lane.

### R5. Empty-data days

If for some reason ingest jobs all fail on a given morning, the daily
run might emit zero insights or low-confidence insights.
**Mitigation:** the orchestrator should detect this and either emit a
`status=succeeded_empty` session with a clear "no new data today"
message, or a `status=failed` session with the underlying ingest
failure as the reason. Architect to choose.

---

## 12. Rollout Plan (informational)

This section is informational only; the architect will turn it into a
sequenced build plan.

1. **Phase A — synthesis grounding.** Fix the orchestrator so bootstrap
   retains rows, hypothesize produces typed hypotheses, and synthesis
   receives non-empty `supporting_rows`. Validated via manual "Generate
   insights" before any scheduling change.
2. **Phase B — schedule and idempotency.** Add `insights_daily` to the
   APScheduler job table; enforce one-scheduled-session-per-day.
3. **Phase C — frontend default load.** Switch the AI Insights tab to
   load the latest succeeded session on mount; demote the manual CTA.
4. **Phase D — failure surfacing and past sessions.** Render failed
   sessions; build the past-sessions browser.
5. **Phase E — dedup.** Implement the cross-day similarity rule; mark
   `ongoing` insights and surface them visually.
6. **Phase F — observability and cost ceiling.** Phase timings, token
   accounting, budget enforcement at termination.

Each phase is independently shippable behind the existing tab.

---

## 13. References

The architect should pick up directly from these. The first three are
load-bearing for FR2 (real-data synthesis); the fourth is load-bearing
for FR1 (daily auto-run).

- `backend/agents/insights/orchestrator.py:395-403` — synthesis call
  site that hardcodes the hypothesis and passes `supporting_rows=[]`.
  This is the line that produces the "Candidate insight #N from session
  bootstrap" string. Real-data synthesis must replace this call's
  arguments.
- `backend/agents/insights/orchestrator.py:279` —
  `_phase_bootstrap_iter`. Today it iterates the eight survey
  endpoints, counts rows for the `SurveyingEvent`, and discards them.
  It must retain rows so downstream phases can ground on them.
- `backend/agents/insights/orchestrator.py:339` —
  `_phase_hypothesize_iter`. Today it is an admitted stub that emits a
  single `reasoning_step="hypothesize"` event and returns. It must be
  replaced by real hypothesis generation tied to the bootstrap rows.
- `backend/pipeline/runner.py:53-110` — the APScheduler job table.
  Eleven jobs registered today, no `insights_daily`. This is where the
  new daily entry lives.

Frontend touch-points (informational):

- `frontend/src/components/tabs/ai-insights/` — the AI Insights tab
  components. The default-load behavior in FR3 lives here.
- `frontend/src/hooks/useInsightStream.ts` — the SSE client hook.
  Should not need protocol changes.
- `frontend/src/types/sseEvents.ts` — the typed SSE event shapes;
  already supports citation events.

Domain-data touch-points (informational, read-only for v1):

- The Postgres tables backing power deals, permits, EDGAR filings,
  anomalies, and the survey endpoints reachable via the existing
  `call_api` tool. Source list of survey endpoints lives in the
  orchestrator module under `SURVEY_ENDPOINTS`.

---

*End of PRD.*
