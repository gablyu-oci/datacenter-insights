# PRD Addendum: Phase 4 Frontend Rework + Supply/Demand-Gap Pattern

**Status:** Draft for review
**Owner:** PM (strategic-insights-tool)
**Primary stakeholder:** the user
**Date:** 2026-05-05
**Predecessors:**
- `01-prd.md` (original PRD; FR1-FR7, AC1-AC9)
- `03-architecture.md` (system design; §6 `/api/insights/latest`, §10 Decision Log)
- `04-ux.md` (UX spec; §1.2 default-load, §2.1 state table, §3.4 failed-run banner, §3.5 Run again)
- Phases 1-3 already shipped (hypothesizer wiring, schema migration 013, scheduler `insights_daily` 09:00 UTC, idempotency, wall-clock guard).

This addendum scopes the two remaining deliverables on top of the
already-shipped Phase 1-3 work.

---

## 1. Goals

### 1.1 Goal A — Phase 4: Frontend default-load and `GET /api/insights/latest`

The synthesis loop, the daily 09:00 UTC scheduler, and the schema for
auto-run sessions are all live, but the user still has to click "Generate
insights" to see the day's set. Goal A closes that gap by exposing a
single snapshot endpoint (`GET /api/insights/latest`) that returns the
most recent completed `ai_session` plus its persisted `ai_insight` rows
and any `agent_charts`, then rewires `AIInsightsTab.tsx` to default-load
that snapshot on mount with no click. The current primary-fill "Generate
insights" CTA becomes a secondary header-utility "Run again" button per
UX spec §3.5; manual runs use the existing SSE path and do not clobber
the previously rendered snapshot until the first new
`InsightCompleteEvent` arrives. Failed scheduled runs surface via the
UX spec §4 stale banner over the previous successful insights.

### 1.2 Goal B — Supply/demand-gap analytical pattern

the user's quote: *"I want it to be able to find out Oh XX
datacenter/provider is generating XX megawatts but only partially
consumed by some company, so we could potentially contract the rest
energy types of findings, not limited to this one question."* Today's
FactPack sections capture movers, permits, anomalies, EDGAR mentions
and coverage gaps, but none of them surface uncontracted or
under-contracted capacity that OCI could go after commercially. Goal B
adds four deterministic SQL-backed FactPack sections inside
`backend/agents/insights/hypothesizer.py` that expose those gaps, plus
one targeted bullet in `_SYSTEM_PROMPT`'s "Rules:" block telling the
synthesizer to call out supply/demand gaps as commercial opportunities
(without touching the wrapper rules around `_utcnow`, `_today_utc`,
`_coerce_insights`, or the rest of the prompt scaffolding). An ADR at
`docs/plans/ai-insights-automation/06-supply-demand-gap-adr.md` records
the decision and the row-count caps.

---

## 2. User Stories

the user is the primary user throughout. Stories are ordered A then B.

- **A-S1.** *As the user, I want the AI Insights tab to show today's
  insights the moment I open it, so that I do not need to remember to
  click "Generate" before a meeting.*
- **A-S2.** *As the user, when a manual "Run again" is in flight, I want
  yesterday's (or this morning's) insights to remain visible until the
  new run actually has results, so that I am not staring at a blank
  page during a stream.*
- **A-S3.** *As the user, when this morning's auto-run failed, I want a
  banner telling me so plus the most recent successful set still
  rendered, so that I am never left with a blank tab when the
  scheduler hiccups.*
- **B-S1.** *As the user, I want the tool to surface datacenter or power
  sites that have contracted MW but no named offtaker, so that OCI's
  commercial team can chase the uncontracted capacity.*
- **B-S2.** *As the user, I want the tool to flag sites where one
  hyperscaler took the entire offtake and another high-MW site sits
  with no known customer, so I can spot asymmetric concentration.*
- **B-S3.** *As the user, I want supply/demand-gap insights to appear in
  the daily set as commercial opportunities, not buried as raw rows,
  so that they are part of the morning narrative.*

---

## 3. Functional Requirements

### 3.1 Phase 4 — Frontend rework + `/latest` endpoint

#### FR-A1. `GET /api/insights/latest` endpoint

A new handler in `backend/routers/insights.py` returns the most recent
*completed* `ai_session` row, plus its persisted `ai_insight` rows and
associated `agent_charts`.

- **Selection:** the most recent `ai_session` with `status='complete'`
  ordered by `started_at DESC`. **Tiebreak:** if more than one
  completed session exists for *today's* UTC date, prefer the row with
  `created_by='scheduler'` over `created_by='manual'`.
- **Response payload:** session row + ordered `insights[]` (matching
  the existing `InsightSummary` shape used elsewhere in the router) +
  any `agent_charts` rows joined by `session_id` so the frontend can
  render charts without a second round-trip.
- **404:** if no completed session exists at all, return HTTP 404 with
  a JSON body `{ "detail": "no_completed_session" }`.
- **No new HTTP endpoints beyond `/latest`.** Past-session detail and
  manual-run kickoff already have endpoints; Phase 4 must not add a
  third.

#### FR-A2. Default-load on tab mount

`AIInsightsTab.tsx` calls `GET /api/insights/latest` on mount and
renders the resulting insights without any user click.

- Skeleton state per UX spec §2.1 while the request is in flight.
- On 200: hydrate header + feed from the response.
- On 404: render the cold-start empty state per UX spec §3.7.
- On 5xx: render the inline error per UX spec §1.2 step 5.

#### FR-A3. CTA demotion: "Generate insights" -> "Run again"

The primary-fill button currently at lines 154-169 of
`AIInsightsTab.tsx` is demoted to a secondary "Run again" button in
the top-right of the page header per UX spec §3.5.

- Visual treatment: secondary (border + neutral surface), not the
  current `c.brand.primary` fill.
- Label: "Run again" idle, "Running..." while a manual SSE stream is
  active.
- The button is the *only* place a user can manually re-trigger a run
  in v1.

#### FR-A4. Run-again preserves prior insights until first new result

Clicking "Run again" kicks off the existing manual session flow
(`POST /api/insights/sessions` then SSE attach). The previously
rendered insights remain on screen until the first
`InsightCompleteEvent` of the new session arrives, at which point the
feed swaps to the new session's stream.

- If the new manual run errors before any `InsightCompleteEvent`, the
  prior snapshot stays visible and an error toast appears per UX spec
  §5.7.
- The header source pill flips from "Auto-run" to "Manual run · just
  now" only after the new session reaches `done`.

#### FR-A5. Past-sessions rail reads persisted rows

The left rail in `AIInsightsTab.tsx` (currently fed an empty array
literal) is wired to whatever existing endpoint returns recent
sessions; rows reflect persisted `ai_session` rows including failed
ones. **No new HTTP endpoint** is added for this; if the existing
session-list path is sufficient, reuse it. If the rail is not
backed by an existing list endpoint at the time of implementation,
the rail is populated from a slice of `/latest`'s expanded response
or from another already-shipped endpoint per the architect's call —
this addendum does not authorize a new HTTP route.

#### FR-A6. Auto-run badge and failure banner

- If `latest.session.created_by == 'scheduler'`, the header renders a
  small badge `Auto-generated YYYY-MM-DD HH:mm UTC` (the existing
  source pill in UX spec §3.1 is the implementation point).
- If today's most recent auto-run is `status='failed'` and a prior
  successful session exists, the page renders the stale failure banner
  per UX spec §3.4.1 *plus* a `"Last successful run: <date>"`
  sub-line, with the prior successful session's insights rendered
  beneath. No partial / orphan insights from the failed run are
  surfaced.

### 3.2 Deliverable B — Supply/demand-gap pattern

#### FR-B1. New FactPack section `uncontracted_capacity_top_sites`

Top 12 `EnergyProject` rows where `tot_contracted_power_mw IS NOT
NULL` AND `customer_companies` is NULL or empty, ordered by
`tot_contracted_power_mw DESC`.

- Row dict keys mirror existing FactPack convention: `entity` =
  project name, `metric = "uncontracted_mw"`, `value =
  tot_contracted_power_mw`, `source_url` if available.
- Wrapped in `_safe_query`-style try/except per architecture §3.5;
  on error, the section returns with `rows=[]` and `error=<short>`.

#### FR-B2. New FactPack section `concentrated_offtake_sites`

`EnergyProject` rows with exactly one entry in `customer_companies`
AND `tot_contracted_power_mw` in the top quartile *for their state*.
Capped at 12 rows total, ordered by MW DESC.

- Row dict carries the single-customer name and the state's quartile
  cutoff used for the filter.

#### FR-B3. New FactPack section `capacity_by_developer_with_low_offtake`

Group `EnergyProject` by `developer_companies`; surface developers
whose `SUM(tot_contracted_power_mw)` is in the top quartile of all
developers AND whose median `cardinality(customer_companies)` is at
or below 1. Capped at 12 rows, ordered by total MW DESC.

#### FR-B4. New FactPack section `epa_echo_high_mw_no_known_customer`

`GeneratorPermit` rows (or equivalent EPA ECHO surface) with
`rated_mw_total > 50` AND `resolved_company_id IS NOT NULL`,
LEFT JOINed against `EnergyProject` on resolved-company / site to find
permits that have no matching offtaker record. Top 12 by MW.

#### FR-B5. `_SYSTEM_PROMPT` "Rules:" addition

A single new bullet in the existing "Rules:" block of
`_SYSTEM_PROMPT` instructing the LLM to surface SUPPLY/DEMAND GAPS as
commercial opportunities, citing one or more rows from the four new
sections when present.

- **Out of scope inside this FR:** the wrapper rules in
  `_SYSTEM_PROMPT` around `_utcnow`, `_today_utc`,
  `_coerce_insights`, and the surrounding prompt scaffolding are
  not modified. Only one bullet is added under "Rules:".
- An ADR at `docs/plans/ai-insights-automation/06-supply-demand-gap-adr.md`
  records the four sections, their queries at intent level, the row
  caps (12 each, consistent with `FACT_PACK_MAX_ROWS_PER_SECTION`),
  and the prompt-bullet text.

---

## 4. Non-Functional Requirements

### NFR-A1. Latency

- `GET /api/insights/latest` p95 under 300 ms on the existing single
  Postgres instance (matches UX spec §1.2 expectation). The query is
  one `SELECT` against `ai_session` with `LIMIT 1` plus one filtered
  read of `ai_insight` and one of `agent_charts`, all by indexed
  `session_id`.
- Tab mount-to-first-paint of insights: under 2 seconds end-to-end on
  a warm cache, measured from `useEffect` fire to first
  `InsightCard` paint.

### NFR-B1. FactPack performance

- Each new section is bounded to 12 rows (consistent with
  `FACT_PACK_MAX_ROWS_PER_SECTION`). The four sections together add
  no more than 48 rows to the FactPack input; this stays inside the
  existing `FACT_PACK_MAX_TOTAL_ROWS = 60` only because the existing
  seven sections already draw from disjoint tables — the architect
  must verify the combined bound at implementation time and either
  trim a low-value section or raise the cap if total > 60.
- Each new section is wrapped in `_safe_query` so any single-section
  SQL failure (missing column, type cast, etc.) does not poison the
  whole pack.

### NFR-2. Observability

- Every emission of a supply/demand-gap-derived insight is logged
  with `extra={"pattern": "supply_demand_gap", "row_ids": [...]}` so
  we can grep for how often the new sections influence output.
- `GET /api/insights/latest` logs `session_id`, `created_by`,
  `is_today` and the count of returned insights, keyed by request id.

### NFR-3. Backward compatibility

- No SSE event-protocol changes.
- No new HTTP routes other than `GET /api/insights/latest`.
- No schema migrations. `alembic upgrade head` continues to land
  exactly on migration 013 (the most recent) post-implementation.

---

## 5. Acceptance Criteria

Each criterion is concrete and testable. Together they map back to
the user's acceptance bullets verbatim.

### AC-A1. Schema is unchanged

Running `alembic upgrade head` against a fresh database succeeds and
results in no new migration revision beyond what is already on `main`
at the start of this work. There is no Phase 4 / Deliverable B
migration file.

### AC-A2. Test suite passes

The pytest suite passes: the existing 66 tests plus all new tests
introduced for Phase 4 and the supply/demand sections (router test
for `/latest`, FactPack-section unit tests for the four B sections,
prompt-bullet inclusion test).

### AC-A3. `GET /api/insights/latest` works end to end

- With a completed `ai_session` present in the DB, an HTTP GET to
  `/api/insights/latest` returns 200 with the session, its insights
  ordered by `idx`, and any `agent_charts` rows for that session.
- If both a `scheduler` and a `manual` completed session exist for
  today's UTC date, the `scheduler` row is returned.
- With zero completed sessions, the endpoint returns HTTP 404.

### AC-A4. Browser default-load with no click

Loading `http://datacenter.oci-incubations.com` in a browser and
navigating to the AI Insights tab renders the latest session's
insights without the user clicking any button. The
"Generate insights" primary-fill button no longer appears in the
center of the page; a secondary "Run again" button appears in the
top-right header instead.

### AC-A5. Auto-generated badge

When the loaded session has `created_by='scheduler'`, the header
renders a visible badge / pill containing the literal text
`Auto-generated` followed by the session's `started_at` formatted as
`YYYY-MM-DD HH:mm UTC`.

### AC-A6. Run-again preserves prior insights

While a manual "Run again" SSE stream is in flight and before the
first `InsightCompleteEvent` of the new session arrives, the
previously rendered insight cards remain on screen. After the first
new `InsightCompleteEvent`, the feed swaps to the new session's
output.

### AC-A7. Failure banner with last-successful fallback

When today's most recent auto-run is `status='failed'` and a prior
succeeded session exists, the tab renders the stale banner from UX
spec §4 *and* a sub-line containing `Last successful run:` followed
by the prior session's date. The prior session's insights are
visible beneath the banner; no insights from the failed run are
surfaced.

### AC-B1. Four new FactPack sections exist

`build_fact_pack(db)` returns a `FactPack` whose `sections` list
includes, by name:
`uncontracted_capacity_top_sites`,
`concentrated_offtake_sites`,
`capacity_by_developer_with_low_offtake`,
`epa_echo_high_mw_no_known_customer`. Each section is capped at 12
rows; each is wrapped in `_safe_query` so a SQL exception sets
`error=<short>` and `rows=[]` rather than raising.

### AC-B2. `_SYSTEM_PROMPT` Rules block has one new bullet

A grep of `_SYSTEM_PROMPT` for the literal substring `SUPPLY/DEMAND
GAPS` matches exactly once, inside the "Rules:" block. The
surrounding wrapper rules (`_utcnow`, `_today_utc`,
`_coerce_insights`, and any other untouched scaffolding) are
byte-identical to their pre-change form, asserted by a unit test
that snapshots the relevant slice.

### AC-B3. ADR exists

`docs/plans/ai-insights-automation/06-supply-demand-gap-adr.md`
exists, contains the four section names, intent-level SQL for each,
the row cap, and the verbatim prompt-bullet text.

---

## 6. Out of Scope

Explicit, do not regress:

- **No new HTTP endpoints beyond `/api/insights/latest`.** Past-session
  list, manual run kickoff, SSE attach, cancel — all already exist
  and are reused as-is.
- **No edits to `_utcnow`, `_today_utc`, `_coerce_insights`, or the
  `_SYSTEM_PROMPT` wrapper rules** beyond the single new bullet under
  "Rules:".
- **No mobile layout work.** Desktop-first remains the only target.
- **No authentication / authorization changes.** This is an internal
  tool; no per-user gating in v1.
- **No localization.** UTC and English only, consistent with prior
  PRD and UX spec.
- **No schema migrations.** `alembic upgrade head` lands on the
  existing latest revision pre- and post-change.
- **No SSE event-protocol changes.**

---

## 7. Open Questions

Short list; intentionally narrow.

### OQ-A1. Today's failed-session metadata in the `/latest` envelope

The UX spec §4 stale banner needs to know that *today's* auto-run
failed even when `/latest` is returning *yesterday's* successful
session. Two implementations are viable without a new HTTP route:

1. `/latest` includes an optional `today_failed_session` field
   alongside the primary `session` payload (single round trip).
2. The frontend infers a stale state from the session's
   `cron_run_date` being earlier than today's UTC date and shows the
   banner without a structured failure reason.

**PM recommendation:** option 1 — include the today-failed metadata in
the `/latest` envelope so the friendly-failure mapping in UX spec §5.2
has a real `failure_reason` string to render. Architect to confirm.

### OQ-B1. Quartile cutoff for `concentrated_offtake_sites`

Top quartile *by state* requires a non-trivial window function. If
some states have fewer than four `EnergyProject` rows, the quartile
is ill-defined.

**PM recommendation:** fall back to "MW > state median" when a state
has fewer than 4 rows; the ADR formalizes this. Architect to confirm
or propose a simpler global cutoff (e.g. top quartile across all
states) if state-scoped windowing is too costly.

### OQ-B2. `customer_companies` and `developer_companies` data shape

These columns are referenced as if they are scalar arrays of company
names. If the actual schema stores them as JSONB, comma-delimited
text, or a join table, the `_safe_query` SQL must adapt. Architect
to verify against `backend/db/models.py` at implementation time and
encode the resolution in the ADR.

---

*End of addendum.*
