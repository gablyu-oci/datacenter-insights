# 03 — Architecture: Per-User `insight_subscription` + Collapsed-Count Fix

- **Owner:** Architecture
- **Status:** Approved for implementation
- **Date:** 2026-05-21
- **Inputs:**
  - `docs/planning/save-and-history-per-user/01-PRD.md`
  - `docs/planning/save-and-history-per-user/02-research.md`

---

## 1. Overview

This change ships in a single deploy and addresses two distinct problems on the AI-Insights tab. **Problem 1:** `insight_subscription` is a globally shared bookmark table — every logged-in Oracle user sees every other user's saves. We add a `user_email` owner column, scope `GET /api/insights/saved` (and the matching `is_saved` predicates) to the caller, and resolve identity from the `X-Forwarded-Email` header set by oauth2-proxy. **Problem 2:** The collapsed `Saved` and `Past Runs` section headers render a misleading `(0)` because the underlying lists are fetched lazily on first expand. We add a tiny eager-count endpoint `GET /api/insights/counts` and a new `useInsightCounts` hook that drives the existing `Collapsible` `count`/`countPending` props. The architecture adopts the research doc's Strategy-1 + Option-2 recommendations verbatim — no new dependencies (no TanStack Query), no new middleware, and the shared daily AI-insights cron and `ai_session` / `ai_insight` semantics are unchanged.

---

## 2. ADRs (Architecture Decisions)

### ADR-1: Identity from `X-Forwarded-Email` via a single FastAPI dependency

- **Context.** PRD §FR-4 requires identity resolution to live in one place, not be inlined across three handlers. The repo already has precedent for a per-router header dependency (`_require_bearer` in `backend/routers/agent_tools.py:73-94`). The research doc's Option A (§1) recommends a `Depends(current_user_email)` function returning a normalized `str`.
- **Decision.** Define a single dependency `current_user_email(x_forwarded_email: Optional[str] = Header(default=None, alias="X-Forwarded-Email")) -> str` that returns `value.strip().lower()` if present, the dev-fallback string `"dev@local"` when `settings.environment != "production"` and the header is absent, and raises `HTTPException(401, "missing_x_forwarded_email")` otherwise. Every handler that needs identity declares `user_email: str = Depends(current_user_email)`.
- **Consequences.** Single point of normalization (lowercase, trim). Helpers that cannot use `Depends` directly (`_build_is_saved_column`, `_set_subscription_enabled`) accept `user_email: str` as an argument and the calling handler threads it through. Matches the existing per-route DI style used everywhere else in `backend/routers/insights.py`.

### ADR-2: `environment` config field for dev fallback

- **Context.** `backend/config.py` does not currently expose an `environment` flag. The dev fallback must be config-driven, not request-driven (research §2), so that header manipulation in production cannot enable it.
- **Decision.** Add `environment: str = Field(default="development", ...)` to `Settings`. Production deploys set `ENVIRONMENT=production` in the host env. The `current_user_email` dependency reads `settings.environment` to decide whether to permit the `dev@local` fallback.
- **Consequences.** One new env var on the prod host. The fallback path is unreachable in prod because the env-var name (`ENVIRONMENT`) is one a deploy operator will already have to set correctly for other reasons. Tests can `monkeypatch.setattr(settings, "environment", "production")` to exercise the 401 path.

### ADR-3: Backfill inside the same Alembic migration that adds the column

- **Context.** PRD §FR-5 prescribes a single migration that adds the column, backfills, indexes, and sets `NOT NULL` in order. The backfill value is hard-coded (`gabrielle.lyu@oracle.com`).
- **Decision.** New migration `019_insight_subscription_user_email.py`, modeled on `backend/alembic/versions/018_ai_insights_v2_columns.py`. Upgrade sequence: ADD COLUMN nullable → `UPDATE insight_subscription SET user_email = 'gabrielle.lyu@oracle.com' WHERE user_email IS NULL` → CREATE INDEX → ALTER COLUMN NOT NULL (Postgres only).
- **Consequences.** Single transaction on Postgres; SQLite test-harness still works because we keep the `NOT NULL` flip Postgres-only (the SQLModel-level constraint enforces non-null at the application layer). Downgrade drops the column + index cleanly. No separate data-migration script.

### ADR-4: Single-column index, no new UNIQUE constraint

- **Context.** Every `GET /api/insights/saved` and every `is_saved` EXISTS query filters by `user_email = ?`. The existing ADR against UNIQUE on `insight_id` (preserved in the comment at `backend/routers/insights.py:259-261`) was made because `_set_subscription_enabled` defensively uses `ORDER BY created_at DESC LIMIT 1` to tolerate duplicates; we should not regress that posture by introducing a different UNIQUE shape now.
- **Decision.** Create exactly one new index: `ix_insight_subscription_user_email` on `(user_email)`. Do **not** add UNIQUE on `(user_email, insight_id)`. The defensive ordering in `_set_subscription_enabled` remains the duplicate-tolerance mechanism; it just gains a `WHERE user_email = ?` predicate.
- **Consequences.** Cardinality of `user_email` is single-digit today, low double-digits long-term — a single-column B-tree is selective enough. Future migration can add a composite or UNIQUE if row counts grow into the millions; not warranted now.

### ADR-5: Combined counts endpoint, eager-fetched on tab mount

- **Context.** Research §4 evaluates three strategies for the collapsed-`(0)` bug. The PM preference (PRD §10 Q5) is Option A: real counts visible while collapsed. A single combined endpoint halves the mount-time round-trips vs two siblings.
- **Decision.** Add `GET /api/insights/counts` returning `{"saved": int, "sessions": int}`. The frontend gains `useInsightCounts(autoload=true)` which fetches on mount and exposes `{ saved, sessions, loading, error, refetch }`. `SavedInsightsSection` and `PastRunsSection` pass `count={counts.saved}` / `count={counts.sessions}` and `countPending={counts.loading}` to `Collapsible`. The hook is `refetch()`-ed alongside `saved.refetch()` on subscribe/unsubscribe, and on `sessions.refetch()` after a new run.
- **Consequences.** Two extra small SELECT count(*)s per tab mount. Both are indexed (Saved by the new `ix_insight_subscription_user_email`; Sessions by `ai_session.status` which is already indexed via `Field(index=True)` at `backend/agents/insights/db/models.py:46`). The combined endpoint can be split into two later if it ever becomes the wrong shape; trivial change.

### ADR-6: Only `insight_subscription` becomes per-user. Cron / `ai_session` / `ai_insight` stay shared.

- **Context.** PRD §3.2 explicitly lists per-user cron fanout, per-user session scoping, and per-user past-runs filtering as non-goals. The shared daily session is the right model for a small-N internal tool — one run, one narrative, one source of truth.
- **Decision.** This change touches **only** `insight_subscription` and the `is_saved` derived column. The daily cron continues to write one `ai_session` + N `ai_insight` rows visible to everyone. `GET /api/insights/sessions` and `GET /api/insights/sessions/{id}/insights` are not filtered by user. The `sessions` count in `/api/insights/counts` is a global count, not a per-user count.
- **Consequences.** The architecture has one — and only one — per-user table. Future per-user scoping (Past Runs filtering, admin-view-all, sharing) is a separate future PRD and is explicitly out of scope here.

---

## 3. Data Model Change

### 3.1 New column on `insight_subscription`

| Attribute | Value |
|---|---|
| Column name | `user_email` |
| SQL type | `VARCHAR(254)` (RFC 5321 max) |
| Nullable (post-migration) | NO (Postgres); enforced at SQLModel layer on SQLite |
| Stored case | lowercase (normalized in `current_user_email`) |
| Index | `ix_insight_subscription_user_email` — single-column B-tree |

### 3.2 SQLModel touchpoint

`backend/agents/insights/db/models.py` — class `InsightSubscription` (lines 367-386). Add a new field after `enabled`:

```
user_email: str = Field(max_length=254, index=True)
```

(The `index=True` is informational; the canonical index is created by the migration. `max_length=254` matches the migration's `sa.String(length=254)`.)

### 3.3 Schema diagram

```
BEFORE                                       AFTER
+----------------------+                     +----------------------+
| insight_subscription |                     | insight_subscription |
+----------------------+                     +----------------------+
| id           UUID PK |                     | id           UUID PK |
| insight_id   UUID FK |                     | insight_id   UUID FK |
| criteria_json JSONB  |                     | criteria_json JSONB  |
| created_at   TS      |                     | created_at   TS      |
| enabled      BOOL    |                     | enabled      BOOL    |
+----------------------+                     | user_email   VARCHAR(254) NOT NULL |
                                             +------------------------------------+
                                             INDEX ix_insight_subscription_user_email (user_email)
```

No other tables change. No FK to a users table — `user_email` is a free-form RFC-5321-shaped string sourced from oauth2-proxy.

---

## 4. Alembic Migration Spec

**Filename:** `backend/alembic/versions/019_insight_subscription_user_email.py`
**Revision ID:** `019_insight_subscription_user_email`
**Down-revision:** `018_ai_insights_v2_columns`
**Mirror template:** `backend/alembic/versions/018_ai_insights_v2_columns.py` (`_is_postgres(bind)` idiom, Postgres-only `alter_column` for nullability).

### 4.1 `upgrade()` — steps in order

1. `op.add_column("insight_subscription", sa.Column("user_email", sa.String(length=254), nullable=True))`
2. Backfill — exact SQL string:
   ```
   UPDATE insight_subscription SET user_email = 'gabrielle.lyu@oracle.com' WHERE user_email IS NULL
   ```
   Issued via `op.execute(sa.text("..."))`.
3. `op.create_index("ix_insight_subscription_user_email", "insight_subscription", ["user_email"])`
4. **Postgres only:** `op.alter_column("insight_subscription", "user_email", existing_type=sa.String(length=254), nullable=False)`. Under SQLite this step is skipped (the column stays `NULL`-able at the DB level; the SQLModel field's non-Optional annotation provides app-level enforcement). Pattern matches `018_ai_insights_v2_columns.py:59-67`.

### 4.2 `downgrade()` — steps in order

1. `op.drop_index("ix_insight_subscription_user_email", table_name="insight_subscription")`
2. `op.drop_column("insight_subscription", "user_email")`

No need to revert the NOT NULL flip — the column is dropped wholesale.

### 4.3 Cross-dialect notes

- Postgres path: full sequence including step 4 NOT NULL flip.
- SQLite path: steps 1, 2, 3 only. The migration's docstring should explicitly call out the SQLite caveat (mirror `018_ai_insights_v2_columns.py:28-32`).
- The migration must include the `_is_postgres(bind)` helper inline (private to the migration file), per the established pattern.

### 4.4 Test plan for the migration

Seed N `insight_subscription` rows with `user_email IS NULL` against an in-process SQLite engine (per `backend/agents/insights/db/models.py:18-32`), run `command.upgrade(cfg, "019_insight_subscription_user_email")`, assert every row now has `user_email = 'gabrielle.lyu@oracle.com'`, then `command.downgrade(cfg, "-1")` and assert the column is gone.

---

## 5. Backend API Contracts

### 5.1 Modified endpoints (require `X-Forwarded-Email` in production)

| Endpoint | Behavior change |
|---|---|
| `POST /api/insights/insights/{insight_id}/subscribe` | Writes a new row (or flips back to `enabled=true`) with `user_email = <caller>`. Idempotent per `(user_email, insight_id)`. Response shape unchanged: `SubscribeResponse{saved: true, id: <uuid>}`. |
| `DELETE /api/insights/insights/{insight_id}/subscribe` | Only flips `enabled=false` on rows where `user_email = <caller>`. A DELETE from user A targeting a row owned by user B is a no-op (HTTP 200, no state change). Response shape unchanged. |
| `GET /api/insights/saved` | Adds `WHERE user_email = <caller>` to the SELECT. Response shape unchanged (`SavedInsightsResponse`). |
| `GET /api/insights/latest` | The `is_saved` boolean per insight is computed via `_build_is_saved_column(user_email)` and is now caller-scoped. |
| `GET /api/insights/sessions/{id}/insights` | Same as above — caller-scoped `is_saved`. |
| `GET /api/insights/insights/{id}` | The inline EXISTS at lines 606-615 gains the `user_email` predicate. |

### 5.2 New endpoint

```
GET /api/insights/counts
Auth:    requires current_user_email dependency (per-user for `saved`, global for `sessions`)
Body:    none
Query:   none
Response 200 application/json:
  {
    "saved":    <int>,   // COUNT(*) FROM insight_subscription WHERE enabled AND user_email = :u
    "sessions": <int>    // COUNT(*) FROM ai_session WHERE status = 'complete'
  }
Response 401: when running with environment=production and X-Forwarded-Email absent.
```

The `sessions` count is intentionally **global** (no `user_email` filter) because `ai_session` remains shared — see ADR-6. The dependency is still required because we want a single auth gate on the route; treating the saved count as identity-bearing while sessions are not would create a confusing two-tier auth posture.

### 5.3 EXISTS predicate shape change

Both `_build_is_saved_column()` (at `backend/routers/insights.py:229-243`) and the inline EXISTS in `get_insight` (lines 606-615) accept `user_email: str` and add a `WHERE` clause. Conceptual SQL:

```
EXISTS (
  SELECT 1 FROM insight_subscription s
  WHERE s.insight_id = ai_insight.id
    AND s.enabled = true
    AND s.user_email = :user_email
)
```

Both call sites also bind `:user_email` from the handler-scoped `Depends(current_user_email)` result.

### 5.4 401 contract for missing header in prod

```
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{"detail": "missing_x_forwarded_email"}
```

No `WWW-Authenticate` header — this is not an HTTP-auth scheme, it's an upstream-proxy-set identity that has gone missing.

---

## 6. Dependency Wiring

### 6.1 `current_user_email` dependency — file location

**Location:** inline at the top of `backend/routers/insights.py`, just below the existing imports and above `_build_is_saved_column()`.

**Rationale:** Only `insights.py` consumes per-user identity today. The `agent_tools.py` `_require_bearer` (lines 73-94) is the precedent — a per-router header dependency that lives inline in the router file. If/when a second router needs `current_user_email`, relocate to a new `backend/routers/_deps.py` module in a separate refactor PR.

**Skeleton (architecture only, not implementation):**

```
async def current_user_email(
    x_forwarded_email: Optional[str] = Header(default=None, alias="X-Forwarded-Email"),
) -> str:
    # 1) header present -> normalize -> return
    # 2) header absent + settings.environment != "production" -> return "dev@local"
    # 3) header absent + settings.environment == "production" -> raise 401
```

### 6.2 Settings change in `backend/config.py`

Add inside `class Settings(BaseSettings)`:

```
environment: str = Field(default="development")
```

Read by `current_user_email` from the imported `settings` singleton (`from backend.config import settings`). Production `.env` sets `ENVIRONMENT=production`.

### 6.3 Touchpoint table — handlers/helpers that thread `user_email` through

| File | Symbol | Line(s) | Change |
|---|---|---|---|
| `backend/routers/insights.py` | `_build_is_saved_column()` | 229-243 | Accept `user_email: str`; add `.where(InsightSubscription.user_email == user_email)`. |
| `backend/routers/insights.py` | `_set_subscription_enabled()` | 246-292 | Accept `user_email: str`; add the predicate to the SELECT (line 264-271); set `user_email=user_email` on the `InsightSubscription(...)` constructor (line 277-281); preserve `ORDER BY created_at DESC LIMIT 1`. |
| `backend/routers/insights.py` | `list_session_insights()` | 541 | Add `user_email: str = Depends(current_user_email)`; pass to `_build_is_saved_column(user_email)` at line 551. |
| `backend/routers/insights.py` | `get_insight()` | 579-615 | Add the dependency; add `.where(InsightSubscription.user_email == user_email)` to the inline EXISTS at lines 606-615. |
| `backend/routers/insights.py` | `subscribe_insight()` | 655-670 | Add the dependency; pass `user_email` into `_set_subscription_enabled`. |
| `backend/routers/insights.py` | `unsubscribe_insight()` | 677-690 | Same as subscribe. |
| `backend/routers/insights.py` | `list_saved_insights()` | 697-794 | Add the dependency; add `.where(InsightSubscription.user_email == user_email)` to the JOIN query at lines 703-711. |
| `backend/routers/insights.py` | `get_latest_insights()` | 873 | Add the dependency; pass to `_build_is_saved_column(user_email)` wherever the helper is invoked in `_build_session_payload`. |
| `backend/routers/insights.py` | **NEW** `get_insight_counts()` | (new) | New handler `@router.get("/counts")`. Two COUNT queries, one filtered by `user_email`, one global. |
| `backend/config.py` | `Settings` | 20-72 | Add `environment` field. |
| `backend/agents/insights/db/models.py` | `InsightSubscription` | 367-386 | Add `user_email` field. |

---

## 7. Frontend Architecture

### 7.1 New hook: `useInsightCounts`

**File:** `frontend/src/hooks/useInsightCounts.ts`

**Shape:** matches the hand-rolled pattern in `useSavedInsights.ts:46-149` and `useSessionHistory.ts:72-211` — `useEffect` + `cancelledRef` + `loadingRef` + `hasFetchedOnceRef`. No TanStack Query, no SWR, no new dependencies (research §4).

**Public API:**

```
interface UseInsightCountsOptions { autoload?: boolean }  // default true
interface UseInsightCountsResult {
  saved: number | null
  sessions: number | null
  loading: boolean
  error: string | null
  refetch: () => void
}
```

`saved` and `sessions` are `null` until the first successful fetch (so `Collapsible` can render `(…)` via `countPending` rather than a stale zero).

### 7.2 Section component wiring

**`SavedInsightsSection.tsx`** (currently line 57: `count={saved.total || saved.items.length}`):
- Add `const counts = useInsightCounts();` at the top alongside `const saved = useSavedInsights();`.
- Change the `Collapsible` props to:
  - `count={counts.saved}` (null hides the badge until the first fetch resolves)
  - `countPending={counts.loading && counts.saved === null}`
- In the `onSaveToggle` handler (line 94-98), call both `saved.refetch()` and `counts.refetch()` after an unsave.

**`PastRunsSection.tsx`** (currently line 146):
- Add `const counts = useInsightCounts();` (can be the same hook instance hoisted up to a shared parent; for now each section calls it independently — the request is cheap and the in-flight de-dup in `loadingRef` prevents double-firing within a hook instance).
- Change `Collapsible` props to `count={counts.sessions}` and `countPending={counts.loading && counts.sessions === null}`.
- After `sessions.refetch()` triggers (e.g. on a new "Run again" success), also call `counts.refetch()`.

**Note on hook sharing:** if both sections mount on the same tab render (they do, inside the AI-Insights tab), each invokes `useInsightCounts()` and each fires its own fetch. That's two requests instead of one. For a <10-user tool this is acceptable; if it becomes a measurable cost, hoist the hook one level up into the AI-Insights tab container and pass `counts` down as props. Architect's call to leave this as a deferred optimization.

### 7.3 Invalidation rules

| Event | Side effect |
|---|---|
| `POST /subscribe` success (from `InsightCard`) | `saved.refetch()` (already exists); add `counts.refetch()`. |
| `DELETE /subscribe` success | Same as above. |
| `sessions.refetch()` (new run / Run-again / first expand) | Add `counts.refetch()` after the sessions refetch resolves. |
| Tab unmount / remount | Both hooks naturally re-fetch on mount via `autoload=true`. |

### 7.4 No new frontend dependencies

The research doc explicitly checked: there is no TanStack Query / SWR in this repo (research §4 / §1 note). All hooks use raw `fetch` + manual cancellation. The new hook matches that shape exactly — no library addition, no shared cache config, no provider wiring.

---

## 8. Trust / Auth Boundary

The deployed topology is:

```
Internet → nginx (TLS termination)
         → oauth2-proxy (IDCS OIDC, sets X-Forwarded-Email)
         → FastAPI (loopback)
```

FastAPI does **not** listen on a public interface — there is no path that reaches it without traversing nginx and oauth2-proxy. `X-Forwarded-Email` is trusted because the only thing on the trusted side of that hop is oauth2-proxy itself, and it sets the header from a verified IDCS JWT. This is the same trust model the existing `_require_bearer` check uses for OpenClaw plugin callbacks (`backend/routers/agent_tools.py:73-94`) and is documented in the user's memory note on the HTTPS + Oracle SSO setup.

In development (`settings.environment != "production"`), the dependency short-circuits to a deterministic `"dev@local"`. The fallback is gated on a deploy-time config value — not a request-time signal — so a misconfigured production cannot fall through to the dev identity by accident. We do **not** soften the prod 401 under any circumstances.

We are not defending against an authenticated Oracle employee deliberately spoofing another Oracle employee's email. The header is fundamentally trusted-by-topology. We are defending against accidental cross-user visibility of saved items, which was the actual PRD problem.

---

## 9. Observability

The existing logger pattern in `backend/routers/insights.py` (the module-level `logger = logging.getLogger(__name__)` if present, else `structlog.get_logger()` — match whatever the file already uses) is reused. On every **write** to `insight_subscription`, emit one structured line with at minimum:

```
{
  "event": "insight_subscription_write",
  "action": "subscribe" | "unsubscribe",
  "user_email": "<resolved>",
  "insight_id": "<uuid>",
  "subscription_id": "<uuid or null>"
}
```

Reads (`/saved`, `/counts`, the EXISTS-bearing GETs) MAY log at DEBUG level with `user_email` for trace correlation, but are not required to. Do not log the raw `X-Forwarded-Email` header — log only the post-normalization `user_email` value to avoid casing-noise in the log corpus.

---

## 10. Risks & Mitigations

- **Risk:** A user logs in with mixed-case SSO email (`Gabrielle.Lyu@oracle.com`) and creates an orphan row that does not match her lowercase saves.
  **Mitigation:** `current_user_email` lowercases on read and write; the migration's backfill literal is already lowercase. Add a normalization test (PRD §8.1 acceptance criterion).

- **Risk:** Migration runs on a deployment where `ai_session` is mid-write or the backend is mid-restart.
  **Mitigation:** ADD COLUMN nullable is an online-safe DDL on Postgres for tables of this size. The backfill is a single `UPDATE` against a small table (current row count is dozens). The NOT NULL flip is the only step that takes an ACCESS EXCLUSIVE lock and it runs after backfill, in milliseconds.

- **Risk:** A future refactor exposes FastAPI to the public internet without oauth2-proxy in front. `X-Forwarded-Email` becomes a forgeable header.
  **Mitigation:** Keep the prod-mode 401 strict — never log-and-allow, never default to anonymous. The dev fallback is gated on `settings.environment != "production"`, which means a production deploy that loses its oauth2-proxy will start 401-ing rather than silently authenticate-as-anonymous. That's the loud-failure mode we want.

- **Risk:** Count drift — a `POST /subscribe` races a `GET /counts` and the badge briefly shows the pre-mutation count.
  **Mitigation:** Acceptable for a <10-user tool. The `counts.refetch()` invalidation on subscribe/unsubscribe success means the next render is correct. We are not introducing optimistic counts; the on-disk count is the source of truth, eventually consistent within one round-trip.

- **Risk:** Two `useInsightCounts()` instances (one per section) fire two requests on tab mount.
  **Mitigation:** Acceptable today; hoist the hook to the AI-Insights tab container if cost becomes measurable. See §7.2 note.

- **Risk:** Postgres COUNT(*) on a growing `ai_session` table degrades the `/counts` endpoint over time.
  **Mitigation:** `ai_session.status` is already indexed (`backend/agents/insights/db/models.py:46`); the filtered count is index-only on Postgres. Re-evaluate at >100k sessions, which is years away for this tool.

---

## 11. Rollout Plan

**Single deploy, no feature flag.** Justified by the small user population (<10 SSO'd Oracle employees) and the absence of any backwards-incompatible response-shape change.

**Sequencing within the deploy:**

1. Alembic upgrade runs (`019_insight_subscription_user_email`). Adds the column, backfills Gabrielle, indexes, sets NOT NULL.
2. New backend image starts — handlers begin reading/writing `user_email`.
3. Frontend bundle is published; clients pick it up on next page load. Old clients gracefully degrade (they don't send `X-Forwarded-Email` but oauth2-proxy injects it on every request).

**Smoke check (T+0):**
- Log in as Gabrielle (or curl with `X-Forwarded-Email: gabrielle.lyu@oracle.com` against the prod backend). Confirm her Saved list shows her backfilled rows.
- Log in as a second user (e.g. Karan). Confirm his Saved list is empty.
- With both sections collapsed, confirm the badges show real counts (not `(0)`) within ~200ms of tab mount.
- Subscribe an insight as user B; confirm user A does not see it appear in their Saved list on next refetch.

**Rollback:** redeploy the prior backend image. The new column is harmless to leave in place — the old code never reads it. If a deeper rollback is needed, `alembic downgrade -1` drops the column and index.

**Comms:** one-line Slack message to the stakeholder channel: *"Saved insights are now per-user. Gabrielle's existing saves are preserved; everyone else starts with an empty Saved list."*

---

## 12. Out of Scope

Mirroring PRD §3.2 and §9 explicitly:

- Per-user scoping of `Past Runs` (the sessions list itself stays shared).
- Sharing saved items between users.
- Admin / superuser view of all users' Saved lists.
- Per-user daily-cron fanout, per-user generation budgets, or any change to how `ai_session` rows are created.
- Per-user scoping of `ai_session` or `ai_insight`.
- An in-app account / settings UI for the logged-in user (the `UserMenu` component in this branch is styling-only; not in this doc's scope).
- Renaming `insight_subscription` to better reflect "bookmark" semantics. Future cleanup.
- Soft-delete vs hard-delete on unsubscribe — keep the current `enabled = false` soft-flip.
- Email-change / account-merge tooling. Handle manually via SQL update if/when it happens.

End of architecture doc.
