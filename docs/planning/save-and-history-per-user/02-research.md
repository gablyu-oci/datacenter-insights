# 02 — Research: Per-User insight_subscription + Collapsed-Count Fix

- **Owner:** Research
- **Status:** Draft for architect review
- **Date:** 2026-05-21
- **Inputs:** `docs/planning/save-and-history-per-user/01-PRD.md`

The stack is fixed (FastAPI + SQLModel + Alembic + Postgres/SQLite + React with
plain `fetch`; **no** TanStack Query is in use today — see
`frontend/src/hooks/useSavedInsights.ts:46-149` and
`frontend/src/hooks/useSessionHistory.ts:72-211`, both of which use a hand-rolled
`useEffect` + `cancelledRef` pattern). The point of this doc is to enumerate
the in-stack options for each subproblem and recommend the lowest-friction one.

---

## 1. Reading the user identity from `X-Forwarded-Email`

### Option A — FastAPI `Depends(get_current_user_email)` returning a normalized string

```python
async def current_user_email(
    x_forwarded_email: Optional[str] = Header(default=None, alias="X-Forwarded-Email"),
) -> str:
    ...  # normalize, fallback, or 401
```

- **Testability:** Highest. `TestClient(...).get(url, headers={"X-Forwarded-Email": "..."})` flows straight through the dependency. The dependency function itself is unit-testable without HTTP.
- **Ergonomics in routers:** One added parameter per handler (`user_email: str = Depends(current_user_email)`). Matches the existing per-route DI style used everywhere in `backend/routers/insights.py` (e.g. `db: AsyncSession = Depends(get_db)` at line 499, 543, 581, etc.).
- **Header-missing behavior:** Easy to express as "401 in prod, fallback to `dev@local` in dev" inside one function (FR-4).
- **Interaction with existing DI patterns:** Same shape as the bearer check in `backend/routers/agent_tools.py:73-80`, which uses `Header(default=None)` inside a dependency named `_require_bearer`. **Strong precedent — copy that idiom.**

### Option B — Starlette middleware that stashes email in `request.state`

- **Testability:** Lower. Pytest must instantiate the middleware stack; mocking gets awkward. Starlette guidance is to store data in `scope` which adds an indirection (`request.scope["user_email"]`) callers have to remember.
- **Ergonomics:** Global side effect. Handlers must reach into `request.state.user_email`, which is **not** the established pattern in this repo (no middleware in `backend/main.py:117-122` does this today; the only middleware is `CORSMiddleware`).
- **Header-missing behavior:** Middleware can early-return a 401, but then it applies to **every** route, which is over-broad — `/api/health` and the public read-only routers must keep working without identity. We'd need a path allowlist, which is more code.
- **Verdict:** Over-engineered for a 3-handler change.

### Option C — Per-route `Header(...)` parameter

- **Testability:** Equivalent to A.
- **Ergonomics:** Inline normalization + fallback + 401 logic repeated in three handlers (`subscribe_insight`, `unsubscribe_insight`, `list_saved_insights`, plus the `is_saved` callsites inside `list_session_insights` / `get_insight` / `get_latest_insights`). The PRD explicitly calls out "implemented as a single FastAPI dependency … not inlined three times" (PRD §FR-4).
- **Verdict:** Violates PRD §FR-4 by construction.

### Recommendation: **Option A**

A dedicated `current_user_email` dependency in (proposed) `backend/routers/_deps.py` or inlined at the top of `backend/routers/insights.py`. Mirrors the structure of `_require_bearer` in `backend/routers/agent_tools.py:73-80`. The `_build_is_saved_column()` helper (`backend/routers/insights.py:229-243`) and the inline EXISTS at `backend/routers/insights.py:606-615` cannot use a Depends directly — they will accept `user_email: str` as a function argument and the callers (which **do** Depends) will pass it through.

---

## 2. Local-dev fallback strategy

### Options

1. **Env-var-driven fallback (`DEV_FAKE_EMAIL`)** — read an env var; if set and header absent, use it. Default `dev@local`.
2. **`settings.environment != "production"` short-circuit** — when not prod, fall back to a hard-coded `dev@local`.
3. **Always 401**, force devs to inject the header via `curl -H` / a browser extension / an httpie alias.

### Comparison

| | Option 1 | Option 2 | Option 3 |
|---|---|---|---|
| Onboarding friction | low (set once) | zero | high |
| Prod safety | good (only enabled if env var set) | excellent (`environment` is config, not header) | excellent |
| Footgun risk | medium — someone deploys with the env var set | low | n/a |
| Today's `config.py` support | no `environment` field exists yet (see `backend/config.py:20-72`) | no — needs new setting | n/a |

`backend/config.py` does **not** currently expose an `environment` / `env` flag. Option 2 requires adding one, which is a clean addition but a separate change.

### Recommendation: **Option 2** (with a tiny config addition)

Add `environment: str = "development"` to `Settings` in `backend/config.py`. In prod the deploy sets `ENVIRONMENT=production` (we already template `.env` for the host, per the project's HTTPS+SSO setup memory). The dependency becomes:

```
if header_value: return header_value.strip().lower()
if settings.environment != "production": return "dev@local"
raise HTTPException(401, "missing X-Forwarded-Email")
```

Rationale:
- Configuration-driven, not data-driven (the request body / header can never accidentally enable the fallback in prod).
- No new env var name to remember; piggybacks on the deployment's existing env-injection.
- Matches the PRD wording exactly (§FR-4: "AND `settings.environment != 'production'`").
- Survives the audit question "could a forgotten env var unsafely disable auth?" — no, because the variable is `environment`, which has many other reasons to be set correctly in prod.

If the architect dislikes adding an `environment` field, the runner-up is Option 1 with the explicit env var name **`SIT_DEV_FAKE_EMAIL`** (project-prefixed so it can't collide with anything generic).

---

## 3. Alembic backfill pattern

### Migration shape comparison

**Single-migration (preferred):** ADD COLUMN nullable → backfill → ADD INDEX → ALTER NOT NULL, all in one `upgrade()`. This is what the PRD prescribes in §FR-5.

**Separate data-migration:** Schema migration adds the column; a second migration (or a one-shot script) backfills, then a third sets NOT NULL. More steps, more rollback surface, and no benefit here because the backfill value is hard-coded (Gabrielle's email — PRD §FR-5 step 2).

### SQLite + Postgres compatibility

Looking at `backend/alembic/versions/018_ai_insights_v2_columns.py:50-104`, the repo's established pattern is:

- Branch on `bind.dialect.name == "postgresql"` via a private `_is_postgres(bind)` helper.
- Use `JSONB` only on Postgres; substitute `sa.Text()` / `sa.JSON()` for SQLite.
- For `NOT NULL` ADD COLUMN, pass `server_default=sa.text("'v1'")` — this works on both backends because SQLite's `ALTER TABLE ADD COLUMN` accepts NOT NULL **only when a DEFAULT is supplied**. Migration 018 uses exactly that trick (line 96-104).

For our migration the safest cross-dialect sequence is:

1. `op.add_column("insight_subscription", sa.Column("user_email", sa.String(length=254), nullable=True))`
2. `op.execute("UPDATE insight_subscription SET user_email = 'gabrielle.lyu@oracle.com' WHERE user_email IS NULL")`
3. `op.create_index("ix_insight_subscription_user_email", "insight_subscription", ["user_email"])`
4. `op.alter_column("insight_subscription", "user_email", nullable=False)` — **Postgres only**; under SQLite this is either a no-op (rely on the SQLModel-level constraint) or implemented via `with op.batch_alter_table(...)` (Alembic's table-rebuild helper). Migration 018:61-67 already adopts the "Postgres only" no-op pattern for `alter_column` and notes "SQLite lacks ALTER COLUMN for nullability" (line 29-31 in its docstring).

### Index strategy

- **Single-column index on `user_email`.** Every `GET /api/insights/saved` query filters by `user_email = ? AND enabled = true ORDER BY created_at DESC LIMIT 100`. A B-tree on `user_email` alone is selective enough (cardinality ~= number of distinct users, single-digit today, low double digits long-term).
- **Composite `(user_email, enabled)`** is marginally better for the saved-list query but is overkill for <100k rows total. Skip.
- **Composite `(user_email, insight_id)`** would also be a candidate to enforce per-user uniqueness, but ADR-2 (per the existing comment in `_set_subscription_enabled` at `backend/routers/insights.py:259-261`) explicitly chose **not** to add a UNIQUE constraint on `insight_id` — that decision should carry forward to `(user_email, insight_id)` too. The router's defensive `ORDER BY created_at DESC LIMIT 1` (line 267-270) handles duplicates.

### Recommendation

**Single migration, single-column index, Postgres-only `NOT NULL` flip.** Mirror migration 018's structure (it's the freshest example and is the one the architect should copy).

Migration test coverage: seed N rows with `user_email IS NULL` → run `upgrade()` → assert all rows have `gabrielle.lyu@oracle.com`. The repo has prior art for round-trip alembic tests against SQLite (per the comment in `backend/agents/insights/db/models.py:18-32` referencing "the round-trip alembic test runs against SQLite without pgvector installed").

---

## 4. Collapsed-count fix — strategy comparison

### Today's bug

In `frontend/src/components/tabs/ai-insights/SavedInsightsSection.tsx:57`:

```tsx
count={saved.total || saved.items.length}
```

Because `useSavedInsights` is lazy (`autoload` defaults to `false` per
`useSavedInsights.ts:49`), `saved.total === 0` and `saved.items.length === 0`
until the user first expands the section, so the Collapsible renders `(0)` —
exactly the misleading state the PRD wants gone.

The `Collapsible` component already supports the inputs needed for either
strategy (`count = null` hides the badge entirely, `countPending = true`
renders "(…)" — see `Collapsible.tsx:30-41`).

### Strategy 1 — Eager count-only fetch on mount

- Backend: add `GET /api/insights/saved/count` and `GET /api/insights/sessions/count` (or a combined `/api/insights/counts` returning `{saved: N, sessions: N}`). Implementation is a single indexed `SELECT count(*)` per section — see NFR in PRD §7.
- Frontend: a `useCounts()` hook (autoload=true) fires on tab mount and threads `count` + `countPending` into both Collapsibles.
- **Pros:** Real number visible while collapsed; matches PRD-author's preference (§Open Question 5: "PM preference: Option A"); cheap query (<2ms with the new `user_email` index).
- **Cons:** Two extra requests on every AI-Insights tab mount. Tiny cost for a <10-user tool.

### Strategy 2 — Hide the badge until expansion

- Backend: no change.
- Frontend: change `SavedInsightsSection` and `PastRunsSection` to pass `count={hasFetchedOnce ? saved.total : null}` and `countPending={saved.loading}`. The hook would need to expose a `hasFetchedOnce` flag (it already tracks one internally — `useSavedInsights.ts:58, 72`).
- **Pros:** Zero backend cost; smallest patch.
- **Cons:** Collapsed pill loses the count badge entirely until first expand. PM explicitly calls this out as "feels like a regression from today's UI" (PRD §10 Q5).

### Strategy 3 — `?limit=0` / HEAD on the list endpoint

- Backend: extend `GET /api/insights/saved` to accept `limit=0` and return `{items: [], total: N}` cheaply.
- Frontend: same as Strategy 1 but reuses the existing route.
- **Pros:** No new route.
- **Cons:** The current `list_saved_insights` (lines 697-794) does a JOIN + bulk-load of charts and citations; making it conditional on `limit > 0` is more conditional code than just adding a dedicated count endpoint. The `Query(default=100, ge=1, le=100)` validator at line 698 already rejects `limit=0`, so the API surface has to change anyway. Not cleaner than Strategy 1.

### Interaction with the existing data layer

There is **no TanStack Query / SWR in this repo today** — both hooks use a hand-rolled `useEffect` + `cancelledRef` + `loadingRef` shape. That means:

- Strategy 1 needs a new sibling hook (e.g. `useInsightCounts`) using the same shape. No cache library to configure.
- Strategy 2 is purely a UI tweak inside the two section components and a one-line hook export (`hasFetchedOnce`).
- Either strategy is independently mockable in Vitest: just `vi.spyOn(global, "fetch")`.

### Recommendation: **Strategy 1 (eager count fetch)**, with a single combined endpoint `GET /api/insights/counts`.

Rationale:
- PM expressed preference (PRD §10 Q5).
- "User reported it looks broken" was the original bug — Strategy 2 cures the lie but leaves a UI affordance gap; Strategy 1 cures the lie *and* preserves the affordance.
- One combined endpoint instead of two halves the network round-trips on tab mount (1 request, 2 numbers).
- Cost is dominated by FastAPI handler overhead, not the SQL — both counts together remain well under 10ms on Postgres at our row counts.
- The new `useInsightCounts` hook can be auto-invalidated by the existing subscribe/unsubscribe call sites with a `refetch()` after mutation (the pattern is already familiar — see `SavedInsightsSection.tsx:60` calling `saved.refetch()`).

---

## 5. Auth header trust model

### Why trusting `X-Forwarded-Email` is acceptable here

Per the memory note "HTTPS + Oracle SSO on datacenter.oci-incubations.com":
- Ingress is **only** through nginx, which terminates TLS and forwards to oauth2-proxy.
- oauth2-proxy authenticates against the OCI Default Identity Domain (IDCS) and sets `X-Forwarded-Email` to the verified email from the JWT.
- FastAPI listens on a local socket; it is **not** reachable from the public internet — there is no path that bypasses oauth2-proxy.
- The user population is "logged-in Oracle employee" (PRD §4); we are not defending against an authenticated employee deliberately spoofing another, just preventing accidental cross-user visibility.

This is the same trust model the existing per-route bearer check uses in `backend/routers/agent_tools.py:73-80` for OpenClaw plugin callbacks (a header-set-by-trusted-hop check).

### Defensive recommendation

- In **production** (`settings.environment == "production"`), absent header **must** return 401. No silent fallback to a default like `"unknown@local"` — that creates a phantom user that pools across requests.
- The dev fallback (§2 Recommendation) is the *only* way the header check can be skipped; gating it on a deploy-time config flag (not a request-time signal) means a misconfigured prod cannot accidentally enter dev mode.
- Optional hardening (not in PRD scope, but cheap): also reject if `X-Forwarded-Email` is set on a request whose `X-Forwarded-For` chain doesn't terminate at oauth2-proxy. This is **belt-and-suspenders** and the architect should defer it unless the threat model expands.

---

## 6. Test-strategy notes

### Backend (pytest)

- `httpx.AsyncClient` / FastAPI `TestClient` accept `headers={"X-Forwarded-Email": "user-a@oracle.com"}` on every method. No fixture needed; pass it inline per test.
- For the "no header in prod → 401" test (PRD §8.2): monkeypatch `settings.environment` to `"production"` for the duration of the test, then call without headers.
- For the dev-fallback test: leave `settings.environment` at the default (`"development"`), call without headers, assert the row is written with `dev@local`.
- For the normalization test (PRD §8.1): post with `X-Forwarded-Email: GABRIELLE.LYU@ORACLE.COM` and a separate post with the lowercase form; assert both target the same subscription row.
- Migration round-trip: follow the established harness implied by `backend/agents/insights/db/models.py:18-32` — seed via SQLAlchemy, run `command.upgrade(cfg, "head")`, assert via raw `SELECT`. Then `command.downgrade(cfg, "-1")` and assert column dropped.

### Frontend (Vitest)

- Strategy-1 path: mock the **count** endpoint (`/api/insights/counts`) in the component tests for `SavedInsightsSection` and `PastRunsSection`. The list endpoint can stay mocked-empty unless the test exercises expanded state.
- Strategy-2 path (not recommended): just mock the list endpoint and assert `count` prop is absent until the test simulates expansion.
- Use `vi.spyOn(global, "fetch")` — that's the existing fetch surface; both hooks call `fetch` directly (`useSavedInsights.ts:82`, `useSessionHistory.ts:117`). No MSW setup required.

---

## Recommendations Summary (architect can lift directly)

| # | Decision | Rationale |
|---|---|---|
| 1 | **Identity:** single FastAPI dependency `current_user_email` returning a normalized `str`. Live in `backend/routers/insights.py` (or factor to `_deps.py` if the architect prefers). | Matches existing `_require_bearer` precedent (`backend/routers/agent_tools.py:73-80`). Single point of normalization + 401 + dev fallback. Satisfies PRD §FR-4. |
| 2 | **Dev fallback:** new `environment: str = "development"` field on `Settings`. If header missing AND `settings.environment != "production"`, return `"dev@local"`. Else 401. | Config-driven, not request-driven; can't be tricked by header manipulation. Matches PRD §FR-4 wording exactly. |
| 3 | **Migration:** single revision, modeled on `backend/alembic/versions/018_ai_insights_v2_columns.py`. Sequence: ADD COLUMN nullable → `UPDATE … WHERE user_email IS NULL` → CREATE INDEX `ix_insight_subscription_user_email` → ALTER COLUMN NOT NULL (Postgres only, no-op on SQLite). | Reuses the repo's `_is_postgres(bind)` idiom. Cross-dialect-safe. PRD §FR-5 compliant. |
| 4 | **No new UNIQUE constraint** on `(user_email, insight_id)`. | Preserves the existing ADR-2 stance against UNIQUE on `insight_subscription`; the defensive `ORDER BY created_at DESC LIMIT 1` in `_set_subscription_enabled` (`backend/routers/insights.py:267-270`) already handles duplicates. |
| 5 | **Counts:** add `GET /api/insights/counts` returning `{saved: int, sessions: int}`. Add a `useInsightCounts` hook (autoload=true) and pass `count` + `countPending` into both Collapsibles. | Strategy 1 wins on PM preference + UX continuity. One combined endpoint keeps mount-time requests to a minimum. Strategy 2 is the fallback if backend churn must be zero. |
| 6 | **Refresh counts** on subscribe/unsubscribe success and on Past-Runs refetch. | Keeps the collapsed badge truthful after mutation. Mirrors the existing `saved.refetch()` call pattern. |
| 7 | **Routers to touch:** `_build_is_saved_column()` (`backend/routers/insights.py:229-243`), the inline EXISTS at line 606-615, `_set_subscription_enabled` (line 246-292), `subscribe_insight` (655), `unsubscribe_insight` (677), `list_saved_insights` (697), and the EXISTS calls inside `list_session_insights` (541) and `get_latest_insights` (873). All gain a `user_email` predicate. | Per PRD §12 touchpoint table. |
| 8 | **Tests:** TestClient with explicit `X-Forwarded-Email` per test; monkeypatch `settings.environment` for the prod-401 case; Vitest `vi.spyOn(global, "fetch")` for the count endpoint. | Smallest harness changes; matches existing test idioms. |

### Open items deferred to the architect (not blockers)

- Exact file location for the dependency (`routers/_deps.py` vs inline in `routers/insights.py`). Inline is fine for three handlers; factor out only if a second router needs the same identity.
- Whether the counts endpoint should be one combined route or two siblings. Combined is recommended; trivial to split later if needed.
- Whether to log the resolved `user_email` on every read (PRD §7 Observability says yes on writes; reads are optional).
