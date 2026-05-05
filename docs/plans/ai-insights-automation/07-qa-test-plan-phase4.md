# QA Test Plan — AI Insights Phase 4 + Supply/Demand-Gap Rollout

**Owner:** QA / Test Engineer
**Date:** 2026-05-05
**Predecessors:**
- `05-prd-addendum-phase4-and-supply-demand.md` (acceptance criteria source of truth)
- `06-supply-demand-gap-adr.md` (deterministic SQL specifications for the four new sections)
- `04a-ux-delta-phase4-implementation.md` (frontend rework details)

This test plan covers the QA verification artifact for Phase 4
(frontend default-load + `GET /api/insights/latest`) and the four new
supply/demand-gap FactPack sections plus the system-prompt bullet
addition.

---

## 1. Scope

### In scope

**Backend**
- `GET /api/insights/latest` endpoint in `backend/routers/insights.py`:
  selection rules, 200 vs 404, scheduler-vs-manual tiebreak,
  insight + chart attachment, payload shape.
- Four new section builders in `backend/agents/insights/hypothesizer.py`:
  `_section_uncontracted_capacity_top_sites`,
  `_section_concentrated_offtake_sites`,
  `_section_capacity_by_developer_with_low_offtake`,
  `_section_epa_echo_high_mw_no_known_customer`.
- Single new bullet in `_SYSTEM_PROMPT` mentioning "SUPPLY/DEMAND GAPS"
  and "potentially contractable".
- FactPack composition: `_SECTION_BUILDERS` is now 11 entries; the
  per-section row cap (12) and global cap (60) still hold.

**Frontend**
- `AIInsightsTab.tsx` default-load on mount via `useLatestInsightSession`
  hook, with skeleton state and no-flash-of-empty behavior.
- Demoted secondary "Run again" header button (replaces the prior
  primary-fill "Generate insights" CTA).
- "Auto-generated YYYY-MM-DD HH:mm UTC" badge when
  `session.created_by === 'scheduler'`.
- `SnapshotInsightFeed.tsx` new component for snapshot rendering.
- `FailedLatestBanner.tsx` scaffold (currently behind always-false prop;
  not user-visible until backend exposes a `?include_failed=true`
  variant).
- Run-again UX: prior insights remain visible until the first new
  `InsightCompleteEvent` of the new manual session.

### Out of scope

- Vitest / Jest frontend test coverage (project has no JS test runner
  configured at this time).
- E2E browser automation (Playwright / Cypress) — manual smoke only.
- The chat / V2 surface, citations, and unrelated routers.
- Any schema migration verification beyond "head is unchanged" (no
  Phase 4 / Deliverable B migration was authored).
- Performance benchmarking under production load — covered by NFR-A1
  in the PRD addendum but not exercised here.

---

## 2. Test Matrix

One row per acceptance criterion from the PRD addendum (AC-A1..A7
plus AC-B1..B3).

| AC ID  | Description                                                                                        | Automated test file                                                                                              | Manual smoke step                                                                       |
| ------ | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| AC-A1  | Schema is unchanged; `alembic upgrade head` lands on the same revision as before                    | n/a (verified by absence of new migration files; CI alembic check)                                               | `alembic current` matches prior known head; no new file in `alembic/versions/`          |
| AC-A2  | Pytest suite passes — 66 prior + new tests                                                          | `backend/tests/test_hypothesizer_supply_demand_sections.py` + `backend/tests/test_api_insights_latest.py` + modified `backend/tests/test_hypothesizer_factpack.py` | `pytest backend/tests/test_hypothesizer_supply_demand_sections.py backend/tests/test_api_insights_latest.py backend/tests/test_hypothesizer_factpack.py -v` |
| AC-A3  | `GET /api/insights/latest` returns 200 with insights+charts; tiebreak prefers scheduler; 404 when empty | `tests/test_api_insights_latest.py::test_latest_returns_completed_session_with_insights`, `..._prefers_scheduler_over_manual_same_day`, `..._returns_404_when_no_completed_session`, `..._falls_back_to_most_recent_when_today_empty`, `..._ignores_running_session` | `curl http://localhost:8002/api/insights/latest` — expect 200 with payload OR 404 with `{"detail":"no_completed_session"}` (or the equivalent literal currently emitted) |
| AC-A4  | Browser default-load with no click; primary-fill "Generate" gone; secondary "Run again" header     | n/a (no frontend test runner — manual only)                                                                      | Open AI Insights tab; insights render with no click; no center "Generate" button; "Run again" sits in header |
| AC-A5  | "Auto-generated YYYY-MM-DD HH:mm UTC" badge when `created_by='scheduler'`                          | n/a (frontend, no runner)                                                                                        | Backend test fixture or live scheduler row; verify badge reads `Auto-generated <UTC ts>` |
| AC-A6  | Run-again preserves prior insights until first new `InsightCompleteEvent`                          | n/a (frontend, no runner)                                                                                        | Click "Run again"; observe prior insights stay visible during streaming; swap on first new complete event |
| AC-A7  | Failure banner with last-successful fallback                                                       | n/a — scaffold only, behind always-false prop awaiting backend `?include_failed=true`                            | DEFERRED — see Known Gaps                                                               |
| AC-B1  | Four new FactPack sections present, each capped at 12, each defensive on SQL error                  | `tests/test_hypothesizer_supply_demand_sections.py::test_supply_demand_sections_present_in_factpack` (+ each `_empty` and `_populated` pair) | `python -c "from agents.insights.hypothesizer import _SECTION_BUILDERS; print([n for n,_,_ in _SECTION_BUILDERS])"` shows 11 entries with the 4 new names |
| AC-B2  | `_SYSTEM_PROMPT` Rules block has one new bullet mentioning SUPPLY/DEMAND GAPS                       | `tests/test_hypothesizer_supply_demand_sections.py::test_system_prompt_mentions_supply_demand_gaps`              | `python -c "from agents.insights.hypothesizer import _SYSTEM_PROMPT; print('SUPPLY/DEMAND GAPS' in _SYSTEM_PROMPT, 'potentially contractable' in _SYSTEM_PROMPT)"` prints `True True` |
| AC-B3  | ADR exists at `docs/plans/ai-insights-automation/06-supply-demand-gap-adr.md`                       | n/a — file existence                                                                                             | `ls docs/plans/ai-insights-automation/06-supply-demand-gap-adr.md`                      |

---

## 3. Manual Smoke Test Script

Run after every deploy. Each step must pass before a sign-off.

### Step 3.1 — `/latest` curl

```
curl -s -w '\nHTTP: %{http_code}\n' http://localhost:8002/api/insights/latest
```

**Expected:** HTTP 200 with `{"session": {...}, "insights": [...], "started_at": "...", "status": "complete"}`,
OR HTTP 404 with `{"detail":"no completed session yet"}`.
**Fail criteria:** any 5xx response, generic FastAPI 404 with no
`detail`, or HTML error page.

### Step 3.2 — Default-load in browser

Open `http://datacenter.oci-incubations.com` in a fresh browser
session. Click the AI Insights tab.

**Expected:** insights render automatically; no click required; no
flash-of-empty between mount and first paint.
**Fail criteria:** blank tab; visible "Generate insights" primary-fill
button in the page center; spinning skeleton that never resolves.

### Step 3.3 — Auto-generated badge

With the latest completed session having `created_by='scheduler'`
(use the live 09:00 UTC scheduler run, or seed via psql), reload the
AI Insights tab.

**Expected:** header shows a badge of the form `Auto-generated 2026-05-05 09:00 UTC`
(date + time match the chosen session's `started_at` formatted in
UTC).
**Fail criteria:** no badge, "Manual run" pill, or wrong timestamp /
non-UTC format.

### Step 3.4 — Run-again preserves prior insights

With insights visible from step 3.2, click the "Run again" button in
the header.

**Expected:** the previous insights remain on screen during the SSE
stream; once the first `InsightCompleteEvent` of the new session
arrives, the feed swaps to the new session's output. The button text
flips to "Running..." while the manual stream is in flight.
**Fail criteria:** screen blanks immediately on click; old insights
disappear before any new ones complete; or the swap happens before
`InsightCompleteEvent` (i.e. swaps on `session_started`).

### Step 3.5 — Console clean

Open DevTools console before step 3.2 and keep it open through 3.4.

**Expected:** no JS errors during default-load. Network 404s on
`/latest` (cold start, no completed session) are acceptable and must
not produce an unhandled rejection.
**Fail criteria:** any red-text uncaught exception in the console
during default load.

---

## 4. Known Gaps

- **Frontend has 3 pre-existing TypeScript errors blocking `npm run build`.**
  These are unrelated to this PR (live in unrelated tabs / hooks).
  They block CI's frontend build step but do not affect dev-server
  rendering. Tracked outside this rollout.
- **No Vitest / Jest configured in `frontend/`.** All AC-A4..A7
  acceptance is manual only. Frontend unit tests for
  `useLatestInsightSession`, `SnapshotInsightFeed`,
  `AutoGeneratedBadge`, and `utcFormat` are deferred until the
  project picks a test runner.
- **`FailedLatestBanner.tsx` is a scaffold behind an always-false
  prop.** AC-A7 (today's failed-run banner with last-successful
  fallback) is not user-visible yet. The component renders nothing
  until the backend ships a `?include_failed=true` variant of
  `/latest` (or an equivalent envelope field per OQ-A1 in the PRD
  addendum). The component, props shape, and message-mapping logic
  are in place for that follow-up; only the wiring and the API
  variant remain.
- **`/api/insights/latest` 404 detail string** is `"no completed session yet"`
  (see `backend/routers/insights.py:566`), not the
  `{"detail":"no_completed_session"}` snake-case literal called out
  in PRD §FR-A1. Both are acceptable per FastAPI's `HTTPException`
  conventions, but the wording mismatch is documented here so the
  frontend `useLatestInsightSession` hook does not pattern-match on
  the wrong literal.
- **Performance NFR-A1 (p95 < 300 ms on `/latest`)** is not measured in
  this plan. Live curl is sub-second on dev DB, but a load test
  belongs in a follow-up.

---

## 5. Sign-off Checklist

Before tagging this rollout shipped, all boxes must be checked:

- [ ] Backend unit tests pass: `pytest backend/tests/test_hypothesizer_supply_demand_sections.py backend/tests/test_api_insights_latest.py backend/tests/test_hypothesizer_factpack.py -v` (22 passing, 0 failing).
- [ ] `alembic current` shows the same head revision as before this
      PR; no new file in `backend/alembic/versions/` for Phase 4 /
      Deliverable B.
- [ ] `curl http://localhost:8002/api/insights/latest` returns 200 (or
      a JSON 404 with a `detail`), never a 5xx or HTML error.
- [ ] Browser default-load smoke (step 3.2) passes on
      `http://datacenter.oci-incubations.com`.
- [ ] ADR `docs/plans/ai-insights-automation/06-supply-demand-gap-adr.md`
      is present and committed alongside the code change.
- [ ] System-prompt verification one-liner prints `True True`.

---

*End of test plan.*
