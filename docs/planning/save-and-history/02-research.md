# Save/Bookmark + Past Runs + Saved Insights — Technology & Pattern Research

**Date:** 2026-05-13
**Author:** Research Agent
**Status:** Draft for architect review
**Feature scope:** Save toggle on AI insights (POST/DELETE `/api/insights/insights/{id}/subscribe`), collapsible "Past runs" list, collapsible "Saved insights" list.

---

## Research Question

For an in-prototype feature that adds (a) a per-insight save toggle, (b) a paginated "Past runs" panel, and (c) a "Saved insights" panel, what patterns and libraries best match the **existing** strategic-insights-tool codebase? Goal: minimize new dependencies, mirror the conventions already in use, and avoid N+1 / consistency footguns.

---

## 1. Optimistic UI for the save toggle

### Existing repo pattern (load-bearing)

The existing data hook `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/src/hooks/useLatestInsightSession.ts` uses **plain `useState` + `useEffect` + `fetch`**, with a manual `cancelledRef` and a `refetch` trigger via a `tick` counter. There is **no React Query, no SWR, no Redux** in the data layer. Errors are surfaced as a `string | null`. This is the house style.

### Options

| Option | Pros | Cons |
|---|---|---|
| **Plain `useState` + manual rollback** (matches house style) | Zero new deps; identical mental model to `useLatestInsightSession`; trivial to test with `vi.fn()` fetch mock | Caller must hand-write the rollback branch on `catch`; concurrent clicks need a ref guard |
| **React Query `useMutation` with `onMutate`/`onError`/`onSettled`** | Built-in optimistic update + automatic rollback; cache invalidation handles "Saved insights" panel refresh for free | Adds a top-level `QueryClientProvider`, ~13 kB gz, and a second mental model alongside the existing fetch-hook style |
| **React 19 `useOptimistic`** | Built-in primitive; declarative; auto-rollback on Action failure | The repo's calls aren't form Actions; would force a stylistic split and the existing hooks haven't migrated |

### Recommendation

**Plain `useState` rollback inside a small custom hook `useInsightSubscription(insightId, initialSaved)`** that mirrors `useLatestInsightSession`'s shape. On click:

1. Flip local `saved` state.
2. Fire `POST` (save) or `DELETE` (unsave).
3. On non-2xx or thrown error, flip back and set an `error` string.
4. Use a `pendingRef` to coalesce rapid double-clicks.

This is the lowest-friction option, identical in spirit to the existing hook, and trivially mockable in tests.

**Reference:** existing code pattern at `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/src/hooks/useLatestInsightSession.ts`.

---

## 2. Lazy-loaded collapsible sections

### Existing repo pattern

`/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/src/components/tabs/ai-insights/` already contains the AI Insights tab components. The codebase ships **no third-party collapsible library** (no Radix, no Headless UI in package.json for this surface); collapsibles elsewhere in the tree are hand-rolled with a boolean `useState` and conditional render.

### Options

| Option | Pros | Cons |
|---|---|---|
| **Native `<details>`/`<summary>`** | Zero JS; accessible by default; browser handles open state | Hard to style consistently with the existing card aesthetic; no transition; styling `<summary>` markers requires CSS resets |
| **Custom `<Collapsible>` with `useState`** (matches house style) | Full control over chevron icon, styling, lazy children gate; trivially mounts/unmounts children on toggle to defer the network call | A few extra lines per consumer; must add an a11y `aria-expanded` + `aria-controls` pair |
| **Radix `Collapsible` primitive** | Battle-tested a11y; animation slots | New dep; this prototype has no other Radix usage in the AI insights tree |

### Recommendation

**Custom `<Collapsible title, defaultOpen, children>` component** with `useState`. Conditionally render `children` only when `open === true` (the laziness gate — this is what makes the "Past runs" list defer its paginated GET until the user expands). Add `aria-expanded` on the toggle button.

This matches the rest of the AI Insights tab, ships zero new dependencies, and the lazy-mount pattern is the single feature you actually need.

**Reference:** existing components in `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/src/components/tabs/ai-insights/`.

---

## 3. Pagination strategy for `GET /api/insights/sessions`

### Volume reality

Sessions accumulate at roughly one per day (scheduler) plus occasional manual "Run again" sessions. Over a year that is order-of-magnitude **a few hundred rows total**, with the vast majority of user interest in the last 10–20.

### Options

| Option | Pros | Cons |
|---|---|---|
| **Offset/limit + "Load more" button** | Trivial to implement (`LIMIT ? OFFSET ?`); deterministic page numbers; easy to test; user controls bandwidth | Offset drift if a new session lands mid-browse (rare here — sessions are append-only and almost never deleted) |
| **Cursor-based** (`created_at < ?`) | Stable under inserts; future-proof for high volume | Overkill for ~hundreds of rows; needs cursor encoding/decoding logic |
| **Infinite scroll** | Smooth UX | Inside a collapsible panel it's awkward; requires `IntersectionObserver`; harder to test |

### Recommendation

**Offset/limit with a "Load more" button.** `GET /api/insights/sessions?limit=10&offset=0`, returns `{ items, total, has_more }`. Frontend appends results on click. For this scale and this UI (collapsible panel, not a primary view) it is exactly right; cursor pagination is a premature optimization.

Add a sensible cap server-side (`limit <= 50`) and an `ORDER BY started_at DESC` index — `ai_session.started_at` does not appear indexed in the model; the architect should confirm whether to add one in the same migration as `insight_subscription`'s unique constraint (see §5).

---

## 4. SQLAlchemy LEFT JOIN for `is_saved`

### Model context

`InsightSubscription` (defined at `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/db/models.py` lines 368–387) has columns `insight_id` (FK → `ai_insight.id`, indexed), `enabled: bool`, and `created_at`. No unique constraint on `insight_id`. The "saved" predicate is therefore: **"a row exists with this `insight_id` AND `enabled = true`"**.

The repo uses **SQLAlchemy 2.x `select()`** with `AsyncSession` (see `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/routers/insights.py` imports — `from sqlalchemy import select` + `AsyncSession`).

### Options

| Option | Pros | Cons |
|---|---|---|
| **LEFT JOIN + `func.coalesce(bool_or(sub.enabled), false)`** with `GROUP BY ai_insight.id` | Single query; correct even with duplicate subscription rows (the missing unique constraint); naturally handles "0 rows = not saved" | Slightly more SQL; needs `GROUP BY` of every `ai_insight` column you select |
| **Correlated `EXISTS (...)` subquery** as a labeled column | No `GROUP BY`; reads cleanly: `select(AIInsight, exists().where(...).label("is_saved"))`; index on `insight_subscription.insight_id` already exists | Two index lookups conceptually, though planner often inlines them; still one round-trip |
| **Batch fetch + merge in Python** | Simplest SQL; works fine for small N | Two round-trips; couples ORM and presentation; easy to forget when adding new endpoints |

### Recommendation

**Correlated `EXISTS` subquery as a labeled column.** Example shape (illustrative, not for paste):

```python
saved_expr = (
    select(1)
    .where(InsightSubscription.insight_id == AIInsight.id)
    .where(InsightSubscription.enabled.is_(True))
    .exists()
    .label("is_saved")
)
stmt = select(AIInsight, saved_expr).where(...)
```

This avoids `GROUP BY` entirely, is correct under the current "no unique constraint" reality, uses the existing `insight_subscription(insight_id)` index, and reads obviously. Plumb `is_saved` into the existing `LatestInsight` shape returned by `/api/insights/latest`.

**Reference:** [SQLAlchemy 2.x ORM Querying Guide](https://docs.sqlalchemy.org/en/20/orm/queryguide/), existing async pattern in `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/routers/insights.py`.

---

## 5. Idempotent upsert for `insight_subscription`

### The schema reality

There is **no unique constraint on `insight_subscription.insight_id`**. Therefore `INSERT ... ON CONFLICT (insight_id) DO UPDATE` will fail at parse/plan time — Postgres requires the conflict target to be backed by a unique index or constraint.

### Options

| Option | Pros | Cons |
|---|---|---|
| **Add a unique index migration, then `ON CONFLICT (insight_id) DO UPDATE SET enabled = true`** | Cleanest long-term; one statement; race-safe under concurrent saves | Requires a new migration; must first clean up any duplicate rows that already exist (probably none in this dev DB but verify) |
| **Soft upsert: `SELECT` for `(insight_id)` then `UPDATE enabled=true` or `INSERT`** (no schema change) | Zero migration; preserves prototype velocity | Race window between SELECT and INSERT; for single-user dogfood that's irrelevant; for tests it's deterministic |
| **`session.merge()`** | One ORM call | Requires PK match, not natural-key match; doesn't fit this case cleanly |

### Recommendation

**Soft upsert in a transaction**, no schema change, with the understanding that a follow-up migration adds `UNIQUE (insight_id)` once the design stabilizes.

Pseudocode shape:

1. `SELECT * FROM insight_subscription WHERE insight_id = :id LIMIT 1 FOR UPDATE`.
2. If row exists → `UPDATE ... SET enabled = true`.
3. Else → `INSERT ... (insight_id, enabled=true, criteria_json=null)`.
4. Wrap in the existing `AsyncSession` transaction.

For DELETE (`/subscribe` DELETE), set `enabled = false` rather than physically removing — this preserves an audit trail and aligns with the existing `enabled: bool` column semantics. `is_saved` already keys off `enabled = true` per §4, so behavior is identical.

**Defer** the unique-constraint migration until after the feature ships and the schema settles. Note this as tech debt.

**Reference:** [PostgreSQL INSERT documentation](https://www.postgresql.org/docs/current/sql-insert.html) — confirms `ON CONFLICT DO UPDATE` requires a unique index/constraint as arbiter.

---

## 6. Component state caching for expanded past-run sessions

### Use case

When a user expands a row in "Past runs," the UI shows that session's insights. If they collapse and re-expand, should the second fetch re-fire?

### Options

| Option | Pros | Cons |
|---|---|---|
| **`useState<Record<string, SessionDetail>>` map** keyed by `session_id`, lifted into the panel parent | Zero deps; matches the existing fetch-hook style; trivial to invalidate | Cache lives only as long as the parent component is mounted (fine — collapsing the entire panel discards it, which is probably desirable for memory) |
| **React Query cache** | Free dedup; stale-while-revalidate | Pulls in the whole library for one cache map |
| **React Context** | Cross-component sharing | Overkill — no other component reads this state |

### Recommendation

**`useState` map in the panel parent**, keyed by `session_id`, populated on first expand. On collapse leave the entry in place so re-expand is instant. No TTL (sessions are immutable once finished — `status` transitions to `complete` or `failed` and stays there).

If a session is still `running`, you may want to skip the cache for that one row, or invalidate on `refetch`. Easy enough with a `cache.delete(id)` call.

---

## 7. Existing test patterns

### Backend (pytest + async)

The repo uses straight `pytest` with **monkeypatching** rather than dependency-injection harnesses. From `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/tests/test_agent_tools_router.py`:

- Tests **inject `sys.path`** to `BACKEND_ROOT` so `import routers.x` works at collection time.
- They **monkeypatch lazy imports** in the module under test (e.g. `_build_skill_ctx`, `dispatch`) to avoid touching Postgres or external services.
- Routers are mounted on a fresh `FastAPI()` app inside `TestClient`, not the real `main.py` app graph.
- Auth: tests set the bearer env var directly via `os.environ`.
- Contract assertions are explicit and surface-level: status code + envelope shape.

For async-database paths, `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/tests/test_agentic_synthesis.py` and `test_persist_insight_v2.py` use `pytest.mark.asyncio` (or a project equivalent) and **stub the LLM/HTTP boundary**, not the SQLAlchemy boundary — they exercise the real ORM against an in-memory or test DB.

**QA agent guidance for this feature:**
- Add `backend/tests/test_subscribe_router.py` that mounts the router on a fresh `FastAPI()`, monkeypatches `get_db` to a fixture-built async session, and asserts: 200 + idempotent on double-POST; DELETE flips `enabled` to false; GET `/api/insights/sessions?limit=...&offset=...` returns the expected page shape.
- Add `backend/tests/test_insights_latest_is_saved.py` covering the `EXISTS`-labeled column: insight with no subscription → `is_saved=false`; with `enabled=true` → `true`; with `enabled=false` row → `false`.

### Frontend (Vitest + React Testing Library)

`/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/src/components/tabs/__tests__/AIInsightsTab.latest.test.tsx` is the canonical example:

- Mocks `global.fetch` via `vi.fn()` returning `Response`-shaped objects.
- Renders the component with RTL `render`, then `await screen.findBy...` for the async path.
- Uses `act()` implicitly via `findBy*` queries.

**QA guidance:** mirror this exactly. For the save toggle, write `Save.test.tsx` that:
1. Mocks `fetch` to resolve with 200.
2. Asserts the button immediately reflects the optimistic state (before the promise resolves) using `findByRole`.
3. A second test mocks `fetch` to reject; asserts the button rolls back and an error is announced.

---

## Summary recommendations (drop-in for design doc)

Match house style throughout: plain `useState` + `fetch` + manual rollback for the save toggle (no React Query, no `useOptimistic`); a hand-rolled `<Collapsible>` component with lazy-mounted children for both new panels; **offset/limit pagination with a "Load more" button** on `GET /api/insights/sessions` (volume is sub-thousand). On the backend, expose `is_saved` via a **correlated `EXISTS` labeled column** in the existing `select(AIInsight, ...)` queries — no `GROUP BY`, single round-trip, leverages the existing `insight_subscription.insight_id` index. Implement save/unsave as a **soft upsert inside a transaction** (`SELECT FOR UPDATE` then UPDATE-or-INSERT, with DELETE flipping `enabled` to false rather than removing the row) since `insight_subscription` has no unique constraint today; record adding `UNIQUE(insight_id)` as deferred schema debt. Cache expanded past-run details in a `useState<Record<string, …>>` map at the panel parent. Tests follow the existing patterns: backend routes mounted on a fresh `FastAPI()` with monkeypatched lazy imports (per `test_agent_tools_router.py`); frontend with `vi.fn()` fetch mocks and RTL `findBy*` queries (per `AIInsightsTab.latest.test.tsx`).

---

## Key references & links

- Existing code: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/src/hooks/useLatestInsightSession.ts` (fetch-hook style of record)
- Existing code: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/db/models.py` (lines 368–387: `InsightSubscription`)
- Existing code: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/routers/insights.py` (async `select()` style)
- Existing code: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/tests/test_agent_tools_router.py` (router test harness)
- [SQLAlchemy 2.0 ORM Querying Guide](https://docs.sqlalchemy.org/en/20/orm/queryguide/)
- [PostgreSQL — INSERT ... ON CONFLICT](https://www.postgresql.org/docs/current/sql-insert.html)
- [React useOptimistic](https://react.dev/reference/react/useOptimistic) (considered and rejected for style consistency)

## Warnings / gotchas

1. **`ON CONFLICT` will not compile** without a unique constraint on `insight_subscription.insight_id`. Use soft upsert until/unless you add the constraint.
2. **Duplicate `InsightSubscription` rows are possible today.** The `EXISTS` predicate handles this correctly (one match suffices); a `JOIN` without `DISTINCT` would multiply parent rows. Prefer `EXISTS`.
3. **Offset drift** is technically possible if a new session is inserted between "Load more" presses. For this prototype's volume and append-only sessions, the worst case is one row appearing twice — acceptable. Document it.
4. **`useEffect` race conditions** — the existing pattern uses a `cancelledRef`. The save-toggle hook should adopt the same guard against unmount-during-fetch.
5. **DELETE semantics** — the proposed soft-delete (set `enabled=false`) means rows accumulate. Add a periodic cleanup job *later*; not blocking.
6. **`is_saved` on cold start** — when `/api/insights/latest` returns `{ session: null, insights: [] }`, there is nothing to join against; the new column simply doesn't appear. Frontend should treat missing `is_saved` as `false`.
7. **Authorization** — the existing `/subscribe` endpoint must apply the same bearer/auth check pattern used elsewhere in `routers/insights.py`. Confirm before shipping.

---

## Files referenced (absolute paths)

- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/src/hooks/useLatestInsightSession.ts`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/src/components/tabs/ai-insights/` (directory)
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/db/models.py`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/routers/insights.py`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/tests/test_agent_tools_router.py`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/tests/test_agentic_synthesis.py`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/src/components/tabs/__tests__/AIInsightsTab.latest.test.tsx`
