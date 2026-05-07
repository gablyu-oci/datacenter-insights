# PRD — AI Insights Phase 4 Follow-ups

Owner: PM
Status: Ready for development
Date: 2026-05-05
Related: `docs/plans/ai-insights-automation/07-qa-test-plan-phase4.md`

## Overview

Phases 1-4 of the AI Insights feature have shipped. Two gaps remain that
block a clean Phase 4 close-out: (1) when the most recent insight session
fails, the UI silently falls back to the empty state instead of surfacing
the failure plus the last good run, and (2) `npm run build` is currently
red due to 25 pre-existing TypeScript errors in unrelated tabs and there
is no JS test runner wired up at all (no `test` script, no Vitest, no
RTL). These three deliverables are bundled into one rollout because they
share the same frontend tooling state (build config, type surface,
AIInsightsTab component) and should land or revert together.

## Goals & Non-Goals

Goals:
- Surface failed-latest sessions in the UI with a fallback to the last
  successful run, end-to-end (API + tab).
- Make `npm run build` exit 0 without changing runtime behaviour.
- Establish a Vitest + RTL test harness and ship the three Phase 4
  AIInsightsTab test cases from the QA plan.

Non-Goals:
- No SSE event shape changes.
- No changes to `hypothesizer.py` or any backend agent logic beyond the
  `/api/insights/latest` query parameter handling.
- No schema migrations; no new alembic revisions.
- No new third-party deps beyond Vitest, @testing-library/react, jsdom.
- No E2E (Playwright/Cypress) coverage in this rollout.
- No chat/V2 surface changes.

## User Stories

### Story 1 — Failed-latest banner wiring

As an analyst loading the AI Insights tab, I want to see when the most
recent run failed and still see the last good insights, so that I am
never left staring at an empty tab when a failure has occurred.

Acceptance Criteria:
- `GET /api/insights/latest` accepts an optional `include_failed` query
  param (boolean, default false).
- Default behaviour (param absent or `false`) is unchanged: returns the
  latest COMPLETED session and its insights, or 404 with the existing
  detail string when none exists.
- With `?include_failed=true`:
  - Returns the most recent session of any status (running, complete,
    failed, cancelled).
  - When that session's status is `failed`, the response also includes a
    `last_successful` object containing the previous most-recent
    COMPLETED session and its insights, or `null` if none exists.
  - When the latest session is not failed, `last_successful` is `null`.
  - When zero sessions exist at all, still returns 404 with the existing
    detail string.
- Response shape (top-level):
  `{ session, insights, last_successful: { session, insights } | null, started_at, status }`.
- Frontend `AIInsightsTab.tsx` fetches with `?include_failed=true` on
  mount.
- When the latest session status is `failed`:
  - The existing `FailedLatestBanner` renders at the top of the tab with
    the failed-at timestamp.
  - Below the banner, the `last_successful.insights` render using the
    same components as the happy path so the user sees actionable
    content.
  - The Run-again button remains visible.
- When `last_successful` is null and the latest session is failed, the
  banner renders alone above the existing empty state.
- When both latest and `last_successful` are absent (404), the existing
  empty state renders unchanged.
- Backend test added covering: default path unchanged, include_failed
  with failed-latest + prior success, include_failed with failed-latest
  + no prior success, include_failed with running-latest, 404 when
  empty.

### Story 2 — TypeScript cleanup so `npm run build` exits 0

As a developer on this repo, I want `npm run build` to exit 0 on main,
so that CI gating, deploys, and local sanity checks are not blocked by
pre-existing type drift.

Acceptance Criteria:
- All 25 pre-existing TypeScript errors across the 8 affected tabs are
  resolved: PowerTab, PermitsTab, NICsOpticsTab, TSMCTab, GPUSupplyTab,
  DataCentersTab, ChatPanel, WeeklyBriefCard.
- No runtime behaviour changes; this is a type-only cleanup.
- `any` is avoided unless genuinely unavoidable; where used, a
  one-line comment explains why.
- No refactors beyond what is needed to clear the errors (no component
  redesigns, no prop renames that ripple).
- `npm run build` exits 0 from a clean checkout.
- No new lint warnings introduced relative to baseline.

### Story 3 — Vitest configuration + Phase 4 frontend tests

As a developer extending the AI Insights tab, I want a working JS test
runner with three Phase 4 tests, so that future regressions in the
failed-latest fallback and run-again flows are caught locally and in
CI.

Acceptance Criteria:
- Vitest, `@testing-library/react`, and `jsdom` are added as dev
  dependencies in `frontend/package.json`. No other new third-party
  deps.
- `frontend/package.json` exposes `"test": "vitest run"` and
  `"test:watch": "vitest"`.
- Vitest is configured with the jsdom environment and resolves the
  same path aliases as the Vite app.
- New test file at
  `frontend/src/components/tabs/ai-insights/__tests__/AIInsightsTab.latest.test.tsx`
  implements the three cases from
  `docs/plans/ai-insights-automation/07-qa-test-plan-phase4.md` §4:
  - (a) Default-load happy path renders the latest insights snapshot.
  - (b) Run-again triggers a fresh session without a flash of the
    empty state between the old and new content.
  - (c) Failed-latest renders `FailedLatestBanner` plus the
    `last_successful` insights below it.
- Network calls (`/api/insights/latest`, SSE) are mocked at the fetch
  / EventSource boundary; no real backend required.
- `npm run test` exits 0 with all three tests passing.

## Acceptance Gates

A change is mergeable only when all of the following hold:

1. Backend pytest: 218 existing tests still pass and at least 1 new
   test for the `include_failed` query parameter passes (target: 219+
   passed, 0 failed).
2. Alembic remains clean: `alembic upgrade head` and
   `alembic check` succeed; no new migration files added.
3. `npm run build` exits 0 from `frontend/`.
4. `npm run test` exits 0 from `frontend/` with the three new Vitest
   tests passing.
5. Manual smoke against `https://datacenter.oci-incubations.com`:
   - Default load of AI Insights tab still renders the latest
     completed session.
   - Forcing a failed latest (or pointing at a fixture) shows the
     banner plus last-successful content.
   - Run-again button still starts a new session and streams
     normally.

## Out of Scope

- No E2E test suite (Playwright/Cypress) added in this rollout.
- No changes to chat, V2 cohort matrix, or peer-review surfaces.
- No database schema migrations; `include_failed` is a read-side query
  parameter only.
- No SSE event shape changes; streaming contract is untouched.
- No edits to `hypothesizer.py` or any backend agent prompts.
- No bulk lint rule changes; only the type errors needed to unblock
  the build are addressed.
- No design changes to `FailedLatestBanner`; reuse as-is.

## Open Questions

- Should `include_failed=true` also return `last_successful` when the
  latest session is `cancelled` (not just `failed`)? Current spec says
  failed-only; flagging in case product wants symmetric behaviour.
- Do we want a feature flag around the frontend fetch change, or is
  the additive query param safe enough to ship unflagged? Default
  assumption: unflagged, since the default API behaviour is unchanged.
- For the no-flash-of-empty test (Story 3, case b), do we assert via
  DOM presence across renders, or via a stable test id on the
  insights container? Recommend the latter for stability.

## Risks

- TS cleanup risk: a "type-only" change accidentally alters runtime
  behaviour (e.g., narrowing that changes a branch). Mitigation:
  reviewer sanity-checks each tab in the manual smoke pass.
- Vitest config drift from Vite config (aliases, env vars) causing
  tests to pass locally but fail in CI. Mitigation: import the shared
  Vite config into `vitest.config.ts` rather than duplicating.
- `include_failed` shape change breaks an unknown consumer. Mitigation:
  default behaviour is byte-identical; new fields only appear when the
  param is explicitly set.

## Rollout

Single PR, single deploy. Order of work inside the PR:
1. Backend `/api/insights/latest` query param + test.
2. Frontend fetch + AIInsightsTab wiring against the new shape.
3. TS cleanup across the 8 tabs until `npm run build` is green.
4. Vitest config + three tests until `npm run test` is green.

Revert plan: revert the single PR; no migrations to roll back.
