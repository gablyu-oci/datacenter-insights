# Save & History on the AI Insights Tab — Master Plan

**Date:** 2026-05-13
**Status:** Planning complete — awaiting user review before any coding starts
**Owner:** Orchestrator (Claude dev-team)

## Companion documents (read in order)

| # | Doc | Author | Purpose |
|---|---|---|---|
| 01 | [`01-PRD.md`](./01-PRD.md) | pm | Problem, goals, user stories, requirements, acceptance criteria |
| 02 | [`02-research.md`](./02-research.md) | researcher | Tech-stack / pattern recommendations grounded in existing code |
| 03 | [`03-architecture.md`](./03-architecture.md) | architect | API contracts, data access, components, hooks, 17-step build order |
| 04 | [`04-ux-design.md`](./04-ux-design.md) | designer | Wireframes, states, tokens, microcopy, a11y |

---

## 1. One-paragraph summary

Repurpose the dead `SubscribeButton` (today: shows a "V3 — coming soon" toast) into a real **Save toggle** that writes/clears an `insight_subscription` row (`enabled=true` means saved). Below the existing snapshot on the AI Insights tab, add two new collapsible sections — **Past runs (N)** lazy-loads `GET /api/insights/sessions` with offset/limit pagination and expands each row into the existing `InsightCard` view via `GET /sessions/{id}/insights`, and **Saved insights (N)** lazy-loads `GET /api/insights/saved`. Add an `is_saved` boolean to all insight payloads via a correlated `EXISTS` subquery so the Save button renders correct state on initial render. No schema migrations, no auth, no V3 cron.

## 2. Cross-doc consensus (what all four agents agree on)

- **Idempotent upsert in Python, no schema change.** `insight_subscription` has no `UNIQUE(insight_id)` index today, so `INSERT ... ON CONFLICT` will not compile. Use a soft upsert (SELECT-then-UPDATE-or-INSERT inside a transaction). DELETE flips `enabled=false`, not a physical row delete. Tech debt: add a unique index in a follow-up PR.
- **`is_saved` via correlated `EXISTS` subquery** as a labeled column on `select(AIInsight, …)`. No `GROUP BY`, single round-trip, uses the existing `insight_subscription.insight_id` index, robust against duplicate subscription rows.
- **Optimistic UI with plain `useState` + manual rollback.** Matches the house style in `useLatestInsightSession`. No React Query, no `useOptimistic`.
- **Collapsibles are hand-rolled** with `useState`, with children conditionally rendered so the network call only fires on first expand. No new dependency.
- **Pagination = offset/limit + "Load more"** for `GET /api/insights/sessions` (volume is ≤ a few hundred rows; cursor would be over-engineering).
- **Filename for `SubscribeButton.tsx` stays** to minimize blast radius; only the *visible label* and icon change (Save / Saved, bell outline / bell filled).
- **Tokens come from `frontend/src/styles/insightTokens.ts`** — no new tokens proposed.
- **Multiple past-run rows may be expanded at once.** Cached per-session-id in a `useState` map at the panel parent.
- **Backend + frontend ship in ONE PR.** Single-developer prototype, no public consumers; the feature is incoherent if split. (Fallback: split at the ~600-line diff seam.)

## 3. Implementation order (the build sheet)

This is the canonical sequence the implementation agents will follow. File paths are absolute under `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/`. See `03-architecture.md` §9 for full signature details.

### Phase A — Backend (FastAPI)

| # | Owner | File | Task |
|---|---|---|---|
| A1 | backend | `backend/routers/insights.py` | Add Pydantic response models: `SubscribeResponse`, `SessionRow`, `SessionsPage`, `SavedInsightRow`. Extend the existing `LatestInsight` shape with `is_saved: bool`. |
| A2 | backend | `backend/routers/insights.py` | `POST /api/insights/insights/{insight_id}/subscribe` — soft upsert. 404 if insight missing. Returns `{saved: true, id}`. Idempotent. |
| A3 | backend | `backend/routers/insights.py` | `DELETE /api/insights/insights/{insight_id}/subscribe` — set `enabled=false` (no row delete). Returns `{saved: false}`. |
| A4 | backend | `backend/routers/insights.py` | `GET /api/insights/saved?limit=100` — ORDER BY `subscription.created_at DESC`, cap 100. Reuse `LatestInsight` item shape + include `session_id` and subscription `created_at`. |
| A5 | backend | `backend/routers/insights.py` | `GET /api/insights/sessions?limit=20&offset=0&status=completed` — paginated past sessions, NO insights inline. Returns `{items, total, has_more}`. Server-side `limit ≤ 50`. |
| A6 | backend | `backend/routers/insights.py` | Modify `/latest` and `/sessions/{id}/insights` payloads to include `is_saved` via correlated `EXISTS` labeled column on `InsightSubscription` where `enabled=true`. |

### Phase B — Backend tests (QA)

| # | Owner | File | Task |
|---|---|---|---|
| B1 | qa | `backend/tests/test_subscribe_router.py` | Subscribe POST happy path (200 + `{saved: true}`), idempotency (two POSTs → one row, `enabled=true`), 404 on unknown insight_id. Mirror harness in `test_agent_tools_router.py`. |
| B2 | qa | `backend/tests/test_subscribe_router.py` | Unsubscribe DELETE flips `enabled` to `false` (row still present). |
| B3 | qa | `backend/tests/test_subscribe_router.py` | `GET /saved` ordering by subscription `created_at DESC`, cap-at-100 behavior. Disabled subscriptions excluded. |
| B4 | qa | `backend/tests/test_subscribe_router.py` | `GET /sessions` pagination: default 20, custom limit/offset, `status=completed` default filter, ordering by `started_at DESC`. |
| B5 | qa | `backend/tests/test_insights_latest_is_saved.py` | `is_saved` is `true` when an enabled subscription exists, `false` when none, `false` when only a disabled subscription exists, `false` on missing data. |

### Phase C — Frontend hooks

| # | Owner | File | Task |
|---|---|---|---|
| C1 | frontend | `frontend/src/hooks/useSessionHistory.ts` | New hook. Returns `{items, total, hasMore, loading, error, loadMore, refetch}`. Lazy: only fires on first call. Mirrors `useLatestInsightSession` style (manual `cancelledRef`, no React Query). |
| C2 | frontend | `frontend/src/hooks/useSavedInsights.ts` | New hook. Returns `{items, loading, error, refetch}`. Lazy on first invocation. |
| C3 | frontend | `frontend/src/hooks/useInsightSubscription.ts` | New hook used by SubscribeButton. Takes `(insightId, initialSaved)`; returns `{saved, pending, error, toggle}`. Plain `useState` + manual rollback. `pendingRef` guards rapid double-click. |

### Phase D — Frontend components

| # | Owner | File | Task |
|---|---|---|---|
| D1 | frontend | `frontend/src/components/tabs/ai-insights/SubscribeButton.tsx` | Rewrite. Drop the V3 toast. Read `isSaved` from prop, render bell outline → bell filled via `lucide-react`'s `Bell`. Label `Save` / `Saved`. Use `useInsightSubscription`. `aria-pressed` on the button. Tokens per `04-ux-design.md` §3. |
| D2 | frontend | `frontend/src/components/tabs/ai-insights/Collapsible.tsx` *(new, shared)* | Generic collapsible: `{title, count, defaultOpen, onFirstExpand, children}`. Lazy-mounts children. Chevron rotates 0 → 90° in 150ms. `aria-expanded` on the toggle. |
| D3 | frontend | `frontend/src/components/tabs/ai-insights/PastRunsSection.tsx` | Uses `Collapsible`. On first expand fires `useSessionHistory.refetch()`. Renders one row per session (date • #insights badge • focus tag). Click a row → fetch `/api/insights/sessions/{id}/insights`, cache in a local `Record<sessionId, …>` map, render with `InsightCard`. Multi-expand allowed. "Load more" button when `hasMore`. |
| D4 | frontend | `frontend/src/components/tabs/ai-insights/SavedInsightsSection.tsx` | Uses `Collapsible`. On first expand fires `useSavedInsights.refetch()`. Renders each saved insight with `InsightCard`. When a SubscribeButton inside this section toggles off, call `refetch()` to remove the row. |
| D5 | frontend | `frontend/src/components/tabs/ai-insights/AIInsightsTab.tsx` | Wire `PastRunsSection` and `SavedInsightsSection` below the existing `SnapshotInsightFeed`. Use `tokens.spacing.s7` between blocks. |

### Phase E — Frontend tests (QA)

| # | Owner | File | Task |
|---|---|---|---|
| E1 | qa | `frontend/src/components/tabs/ai-insights/__tests__/SubscribeButton.test.tsx` | Optimistic toggle: click flips state before fetch resolves (use `findByRole`). Failure path: fetch rejects → state rolls back, toast is announced. Mirror `AIInsightsTab.latest.test.tsx` mocking style. |
| E2 | qa | `frontend/src/components/tabs/ai-insights/__tests__/PastRunsSection.test.tsx` | First expand triggers `GET /sessions` and renders rows. Clicking a row triggers `GET /sessions/{id}/insights` and renders `InsightCard`s. Re-expand the same row does NOT re-fire fetch (cache hit). |
| E3 | qa | `frontend/src/components/tabs/ai-insights/__tests__/SavedInsightsSection.test.tsx` | Lazy load on expand. Un-saving inside the section refetches and removes the row. |

## 4. Rollout decision: one PR

**Recommendation: land backend + frontend in a single PR.**

Rationale:

- Single-developer prototype, no public API consumers — no contract risk to external clients.
- The frontend is meaningless without `is_saved` plumbed through `/latest`; splitting forces a temporary state where the Save button shows the wrong icon on initial render.
- The PRD's acceptance criteria are mostly end-to-end (e.g. "click Save → reload page → bell is still filled") — a half-split PR can't satisfy them.
- Total diff estimate: ~400–700 lines added across ~10 files. Reviewable in one sitting.

**Fallback split-seam** (if diff balloons past ~700 lines or review feedback warrants it):

1. PR #1: backend routes + tests + the additive `is_saved` field on `/latest` and `/sessions/{id}/insights`. This is non-breaking — clients that don't read the field ignore it.
2. PR #2: frontend components, hooks, and tests, plus the rewritten SubscribeButton.

The seam is clean: backend can ship and sit idle for hours/days; frontend lights it up.

## 5. Risks & follow-ups (tracked, not blocking)

| Risk | Severity | Mitigation now | Follow-up |
|---|---|---|---|
| No `UNIQUE(insight_id)` on `insight_subscription` — soft upsert has a race window | Low (single-user prototype) | `SELECT FOR UPDATE` inside the txn | Add `UNIQUE(insight_id)` migration in a separate PR; once present, swap soft-upsert for `ON CONFLICT DO UPDATE` |
| Soft-delete leaves rows with `enabled=false` accumulating | Low | None — schema already supports it | Add a periodic cleanup later if it matters |
| `ai_session.started_at` may not have a descending index | Low | None — ~hundreds of rows | Add index if `EXPLAIN` shows a seq scan |
| Offset drift on "Load more" if a session is inserted mid-browse | Trivial | Document it; sessions are append-only | Cursor pagination if volume grows |
| `is_saved` absent from cold-start `/latest` (`session=null`) | Trivial | Frontend treats missing as `false` | None |
| Auth on the new `/subscribe` routes must match the bearer pattern used elsewhere in `routers/insights.py` | Medium | Backend agent must confirm and mirror | None |

## 6. Out of scope (explicit)

- Authentication / per-user scoping. All bookmarks are global to the prototype instance. Acceptable.
- V3 cron matching against `criteria_json`. `criteria_json` stays NULL on every row this feature writes.
- Mobile / responsive polish. Desktop only.
- Schema migrations of any kind.
- Bulk save / unsave operations, sorting controls beyond default order, search inside past runs.

## 7. Open questions (defaults proposed, awaiting confirmation)

These come from the PRD §10. Default positions are listed; user can override.

1. **Should Saved insights show insights from a re-run / superseded session?** → Default **yes**. `ai_insight` rows are immutable per session; saving an insight saves that exact row, not "whatever the latest version is."
2. **Should Past runs default to expanded or collapsed on first tab visit?** → Default **collapsed**. Avoids a network request the user didn't ask for, and the count badge still gives them the signal.
3. **Should we cap the Saved list more aggressively than 100?** → Default **100**, no pagination v1. Re-evaluate when a user actually has > 50 saves.
4. **Should the Save button be visible on every InsightCard or only in the snapshot section?** → Default **every InsightCard regardless of which section it's in** (snapshot, past run, saved). Saving from inside a past-run expansion should work.
5. **Should we display a count of saved insights anywhere outside the section header?** → Default **no**. The collapsible header "Saved insights (N)" is enough.
6. **Toast library?** → Use whatever the existing tab already uses; do not introduce a new one. Designer confirmed copy in `04-ux-design.md` §6.

## 8. Hand-off checklist

When the user approves this plan, the orchestrator will dispatch in this order:

1. `backend` agent → Phase A (steps A1–A6). Must finish before C runs against a live server, but can start in parallel with C0 against a stub.
2. `qa` agent → Phase B, immediately after A.
3. `frontend` agent → Phase C (hooks), then Phase D (components).
4. `qa` agent → Phase E.
5. Final review: orchestrator confirms acceptance criteria from `01-PRD.md` §7, runs both test suites, drafts the PR description, and reminds the human to omit the Claude co-author trailer per project memory.

---

*End of plan. Review the four companion docs and respond with approve / change-requests before any code is written.*
