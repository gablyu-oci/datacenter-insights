# PRD: Per-User Save Scoping + Collapsed-Count Fix

- **Owner:** PM (strategic-insights-tool) — stakeholder: Gabrielle
- **Status:** Draft
- **Date:** 2026-05-21
- **Surface:** AI Insights tab — `SavedInsightsSection`, `PastRunsSection`, and the `/api/insights/saved` route
- **Predecessor:** `docs/planning/save-and-history/01-PRD.md` (V1 — global, single-user save semantics)

---

## 1. Overview

V1 of Save & History shipped with intentionally global semantics: any logged-in user could save an insight and every other user would see that save in their "Saved" section. That was acceptable while the tool was effectively Karan-only. We now have multiple Oracle stakeholders (Karan, Gabrielle, plus a handful of others) hitting the same instance behind oauth2-proxy, and the global behavior has two visible problems we want to fix in one small follow-up release.

This PRD scopes a focused, low-risk change with two parts:

1. **Per-user scoping of saved insights** — the `insight_subscription` row becomes owned by a user, and `/api/insights/saved` only returns the caller's own rows.
2. **Sidebar count bug** — the collapsed "Saved" and "Past Runs" section headers currently show `(0)` until first expansion (because data is fetched lazily on expand). We want a section to never lie about being empty.

Nothing else changes. The daily AI-insight generation cron stays exactly as it is: one shared session per day, visible to everyone.

---

## 2. Problem Statement

### 2.1 Cross-user leakage of saved items

`insight_subscription` has no owner column today. `GET /api/insights/saved` returns every row where `enabled = true`. Concretely:

- When Gabrielle saves an insight, Karan sees it appear in his Saved section the next time he opens the tab.
- When Karan unsaves something, it disappears from Gabrielle's view.
- There is no audit trail of "who saved this."

This is not an adversarial security issue (everyone behind the oauth2-proxy is a logged-in Oracle employee). It is a *correctness and trust* problem — the Saved list is supposed to be a personal shortlist, and right now it is a shared mailbox.

### 2.2 Collapsed sections show a misleading "(0)"

`SavedInsightsSection` and `PastRunsSection` are collapsed by default and fetch their list lazily on expand. Until the user expands them, the header renders a count badge of `(0)` even when the underlying list has content. Users have reported this looks like the feature is broken (`"there's nothing saved"`), and they don't always click to discover otherwise.

We want the collapsed state to either show the real count or show no count at all — never a fake zero.

---

## 3. Goals & Non-Goals

### 3.1 Goals

- Scope `insight_subscription` to the user who created it.
- Filter `/api/insights/saved` (and the corresponding write endpoints) by the caller's identity, derived from the `X-Forwarded-Email` header set by oauth2-proxy.
- Backfill all existing `insight_subscription` rows to `gabrielle.lyu@oracle.com` so her current Saved list survives the migration.
- Eliminate the misleading "(0)" badge on collapsed Saved and Past Runs section headers.
- Ship as a single deploy: schema migration, backend filter change, and frontend count fix all in one release.

### 3.2 Non-Goals

| Item | Why not now |
|---|---|
| Per-user daily cron sessions / fanout | The shared daily session is the right model for a small-N internal tool. One run, one narrative; everyone sees the same source-of-truth insights. |
| Per-user scoping of `ai_session` or `ai_insight` | Sessions and insights remain shared artifacts. Only the *bookmark* (`insight_subscription`) is personal. |
| Per-user scoping of `Past Runs` | Past Runs lists shared sessions; it is already correct to show all of them to all users. Explicitly deferred. |
| Sharing saved items between users (e.g. "Karan shared his shortlist with me") | Future feature; not in scope. |
| Admin view of all users' saves | Not needed for current stakeholders. |
| New auth surface, login UI, role model, etc. | oauth2-proxy + IDCS already provides identity. We are *consuming* that identity, not building auth. |
| Email-change / account-merge tooling | See Open Questions. Defer until someone actually changes email. |

---

## 4. Users / Personas

The tool is internal to Oracle, behind HTTPS + oauth2-proxy against the OCI Default Identity Domain. The user population is small (single-digit) and consists of trusted Oracle employees viewing competitive intelligence on hyperscaler / datacenter / power buildout vs OCI.

| Persona | Description | Relevance |
|---|---|---|
| Karan | Primary driver of the tool; uses it daily; has been saving insights since V1 shipped. | Will get his own empty Saved list after the migration unless he is also backfilled (see Open Questions). |
| Gabrielle | Heavy user; owns the existing global Saved list de facto. | Backfill target: all existing `insight_subscription` rows are reassigned to her. |
| Other Oracle stakeholders (small N) | Occasional readers; may save the odd insight for a meeting. | Need per-user scoping so their saves are their own. |

**Trust boundary:** logged-in Oracle employee. We are not defending against an authenticated employee deliberately spoofing another employee's email — `X-Forwarded-Email` is set by oauth2-proxy on a trusted internal hop, and the request can only reach FastAPI through nginx. We *are* defending against the much more common case: a stakeholder seeing someone else's saves and getting confused.

---

## 5. User Stories

1. **As Gabrielle**, I want my Saved list to contain only the insights I personally saved, so that my shortlist reflects my own curation work.
2. **As Karan**, I want a fresh, empty Saved list after the migration (or my own backfilled rows if a personal subset is identifiable — see Open Questions), so that I am not looking at Gabrielle's bookmarks every time I open the tab.
3. **As any Oracle stakeholder**, I want a collapsed Saved section to show either a real count or no count at all, so that I am not misled into thinking my list is empty when it has 7 items in it.
4. **As any Oracle stakeholder**, I want the same correct-count behavior on the Past Runs section, so the two sidebar sections behave consistently.
5. **As a developer running the backend locally without oauth2-proxy**, I want a sane default identity so the Save flow still works when I am hitting FastAPI directly on `localhost`.

---

## 6. Functional Requirements

### FR-1 — `insight_subscription` gains a `user_email` column

Add a new column to the `insight_subscription` table:

- Name: `user_email`
- Type: `varchar(254)` (RFC 5321 max length)
- Nullable: `true` at migration time, `false` after backfill (see FR-5)
- Indexed: yes — a non-unique B-tree index on `user_email` (the list query filters by it on every Saved read)
- Stored as the lowercase form of the email (see FR-2 and Open Questions for case-handling)

The SQLModel in `backend/agents/insights/db/models.py` gains the matching field. No other tables change.

### FR-2 — Writes record the current user from `X-Forwarded-Email`

`POST /api/insights/insights/{insight_id}/subscribe` and `DELETE /api/insights/insights/{insight_id}/subscribe` must:

- Resolve the caller's email from the `X-Forwarded-Email` request header.
- Normalize it (`.strip().lower()`) before writing or matching.
- On POST: write the new (or flipped-back-to-enabled) row with `user_email = <caller>`.
- On DELETE: only flip / soft-delete rows where `user_email = <caller>` AND `insight_id = <param>`. A DELETE from user A on a row owned by user B is a no-op (200 OK, but no state change).
- Existing idempotency semantics in `_set_subscription_enabled` are preserved, just scoped to `(user_email, insight_id)` instead of `(insight_id)` alone.

### FR-3 — Reads filter to the current user

`GET /api/insights/saved` must:

- Resolve the caller's email from `X-Forwarded-Email` (same normalization as FR-2).
- Add `WHERE user_email = <caller>` to the existing query alongside `enabled = true`.
- Return the same payload shape — no new fields exposed to the frontend, no client-side changes required beyond the count fix in FR-6.

Additionally, the `is_saved` boolean computed on `/latest`, `/sessions/{id}/insights`, and `/insights/{id}` must be scoped to the caller — an insight Gabrielle saved should render with `is_saved = false` in Karan's view. The correlated EXISTS subquery built by `_build_is_saved_column()` and the equivalent inline EXISTS in `get_insight` both need the `user_email` predicate added.

### FR-4 — Local-dev fallback when the header is missing

In production (behind oauth2-proxy) the header is always present. In local dev (`uvicorn` against `localhost:8000`, no proxy) the header is absent. The backend must:

- If `X-Forwarded-Email` is missing AND `settings.environment != "production"` (or equivalent — defer to architect on the exact config flag), fall back to a deterministic dev identity (recommended: `dev@local`).
- If the header is missing AND we are in production, reject with `401 Unauthorized` and a clear error body. We never want a prod write with an unknown user.

This fallback should be implemented as a single FastAPI dependency (e.g. `Depends(current_user_email)`) reused across the three affected handlers, not inlined three times.

### FR-5 — Backfill migration

A new alembic migration that, in order:

1. Adds the `user_email` column as nullable.
2. `UPDATE insight_subscription SET user_email = 'gabrielle.lyu@oracle.com' WHERE user_email IS NULL` — backfill every existing row to Gabrielle.
3. Adds the index on `user_email`.
4. Alters the column to `NOT NULL`.

The migration must be reversible (down-migration drops the column and the index). The backfill value is hard-coded in this migration — we are not parameterizing it.

### FR-6 — Collapsed-section count fix

User-visible behavior, independent of implementation:

- A collapsed section header must **never** show `(0)` while its underlying list actually has content.
- Acceptable resolutions (architect's choice — both meet the user requirement):
  - **Option A (eager count fetch):** on tab mount, eagerly fetch a lightweight count for both Saved and Past Runs and render that count on the collapsed header. Counts may show a small skeleton (`(…)`) for the first ~150ms.
  - **Option B (defer the badge):** do not render any count badge until the section has been expanded at least once. Collapsed header shows the section label only, no `(N)` and no `(0)`. After first expand, the count is known and can be shown thereafter.

Whichever option is chosen, the rule is: the badge displays a true count or it displays nothing — it does not display `0` when content exists.

For Saved specifically, the count must reflect the *current user's* saved rows (consistent with FR-3), not the global count.

---

## 7. Non-Functional Requirements

- **Performance.** No measurable regression on tab mount. If Option A is chosen for FR-6, the count query must be a single indexed `SELECT count(*)` per section (Saved scoped by `user_email`; Past Runs scoped by `status='complete'`). Two extra small queries on mount is acceptable for a tool with <10 concurrent users.
- **Auth.** `X-Forwarded-Email` is required in production. The dev fallback (FR-4) must not be reachable in prod under any config.
- **Migration safety.** The deploy runs the alembic migration before the new backend code is serving traffic. There is no read of `user_email` from app code until the column exists and is backfilled.
- **Backward compatibility.** Response shapes are unchanged for all three affected GET endpoints. No frontend type changes required beyond the count-fix component.
- **Observability.** Log a single structured line on every subscribe/unsubscribe with `user_email`, `insight_id`, and the action, so we can see who is using the feature post-rollout.

---

## 8. Acceptance Criteria

### 8.1 Backend filter

- [ ] A backend test creates two `insight_subscription` rows for two different `user_email` values and verifies that `GET /api/insights/saved` with `X-Forwarded-Email: user-a@oracle.com` returns only user A's row.
- [ ] A backend test verifies that `POST /api/insights/insights/{id}/subscribe` with `X-Forwarded-Email: user-b@oracle.com` writes a row with `user_email = 'user-b@oracle.com'`.
- [ ] A backend test verifies that `DELETE /api/insights/insights/{id}/subscribe` from user A on a row owned by user B is a no-op (row remains, `enabled = true`).
- [ ] A backend test verifies that `is_saved` on `/latest` is `true` for user A on an insight A saved, and `false` for user B on that same insight.
- [ ] A backend test verifies that email normalization works: `GABRIELLE.LYU@ORACLE.COM` and `gabrielle.lyu@oracle.com` resolve to the same user.

### 8.2 Local-dev fallback

- [ ] A backend test with no `X-Forwarded-Email` header and `environment != production` succeeds and writes with `user_email = 'dev@local'`.
- [ ] A backend test with no `X-Forwarded-Email` header and `environment = production` returns 401.

### 8.3 Migration

- [ ] A migration test seeds N existing `insight_subscription` rows with `user_email = NULL`, runs the migration, and asserts that every row now has `user_email = 'gabrielle.lyu@oracle.com'`.
- [ ] The migration is reversible: `alembic downgrade` removes the column and the index without errors.
- [ ] The migration leaves the column `NOT NULL` after backfill completes.

### 8.4 Frontend collapsed-count fix

- [ ] A frontend test (component test on `SavedInsightsSection` and `PastRunsSection`) verifies that the collapsed header does not render `(0)` when the underlying data is non-empty.
- [ ] Manual QA: open the tab as Gabrielle, observe the Saved section collapsed header shows the correct count (Option A) or no count badge at all (Option B), but never `(0)`.
- [ ] Manual QA: same check for Past Runs.
- [ ] The Saved count, when shown, reflects the current user's rows only (not the global count).

---

## 9. Out of Scope

- Sharing or transferring saved items between users.
- An admin / superuser view of all users' Saved lists.
- Per-user daily-cron fanout, per-user generation budgets, or any change to how `ai_session` rows are created.
- Per-user scoping of `Past Runs`, `ai_session`, or `ai_insight`.
- An in-app account / settings UI for the logged-in user (we already added the `UserMenu` component in this branch; styling and content of that menu are not in this PRD's scope).
- Renaming or restructuring the `insight_subscription` table to better reflect "bookmark" semantics. Lives as future cleanup.
- Soft-delete vs hard-delete on unsubscribe — keep current behavior (soft-flip `enabled = false`).

---

## 10. Open Questions

1. **Email case-sensitivity.** Oracle SSO sometimes returns mixed-case emails (`Gabrielle.Lyu@oracle.com`). We propose normalizing to lowercase on both write and read. Confirm there are no IDCS-side accounts that legitimately differ only by case. *Tentative answer: lowercase everywhere.*
2. **Email change / account migration.** If a user's primary email changes (e.g. departmental migration `oracle.com` → `oraclecloud.com`), their existing saves will be orphaned. We propose handling this manually via a SQL update when/if it happens. Not worth tooling now.
3. **Karan's existing saves.** The backfill assigns all current rows to Gabrielle. If Karan has saves in the existing global pool that are demonstrably his (e.g. saved while only he was active), should we split them? *Default: no — we cannot reliably attribute past saves, and Karan can re-save anything important within minutes. Confirm with Karan before the migration runs.*
4. **Should Past Runs eventually be user-scoped too?** Sessions are shared today and we are not changing that. But conceptually a user might want to hide noise from sessions they didn't trigger. *Default: explicitly defer — out of scope for this PRD.*
5. **Option A vs Option B for the count fix.** Both meet the user requirement. Architect to pick based on implementation cost. *PM preference: Option A (eager fetch) — the count is a useful affordance, and "no badge at all" feels like a regression from today's UI.*
6. **Should the `X-Forwarded-Email` resolver also accept `X-Forwarded-User` as a fallback?** oauth2-proxy sets both. *Default: only read `X-Forwarded-Email` — single source of truth, less drift.*

---

## 11. Rollout Plan

**Single deploy. No feature flag. Same release for migration + backend + frontend.**

Justification:

- The user population is small (<10) and behind SSO. A staged rollout adds operational complexity with no risk reduction.
- The frontend count fix is independently safe to ship and has no backend dependency.
- The backend filter requires the migration to have run. Sequencing within the deploy:
  1. Alembic upgrade runs (adds column, backfills, indexes, sets NOT NULL).
  2. New backend code starts serving — it reads/writes `user_email` from the now-present column.
  3. Frontend bundle is published; clients pick it up on next page load.
- Rollback path: if something goes wrong, redeploy the prior backend image; the new column is harmless to leave in place. The DB stays forward-compatible.

**Communication.** A one-line Slack message to the stakeholder channel on deploy day: *"Saved insights are now per-user. Gabrielle's existing saves are preserved; everyone else starts with an empty Saved list."*

**Success check (T+1 day).** Confirm with Gabrielle that her Saved list is intact; confirm with Karan that his Saved list is empty (or backfilled if Open Question 3 resolves that way); confirm no error spike in backend logs filtered on the subscribe routes.

---

## 12. Appendix — Touchpoint Summary

| Area | Change |
|---|---|
| `backend/agents/insights/db/models.py` | `InsightSubscription` gains `user_email: str` field. |
| Alembic migrations | New migration: add column nullable, backfill Gabrielle, index, set NOT NULL. |
| `backend/routers/insights.py` | New `current_user_email` dependency; `_set_subscription_enabled`, `subscribe_insight`, `unsubscribe_insight`, `list_saved_insights`, `_build_is_saved_column`, and the inline EXISTS in `get_insight` all gain a `user_email` predicate. |
| `frontend/src/hooks/useSavedInsights.ts` | If Option A: expose a lightweight count fetch (or piggyback on the list fetch with `{limit: 0}` semantics if the API allows). |
| `frontend/src/hooks/useSessionHistory.ts` | Same as above for Past Runs. |
| `frontend/src/components/tabs/ai-insights/SavedInsightsSection.tsx` | Count badge logic: never render `(0)` when content exists. |
| `frontend/src/components/tabs/ai-insights/PastRunsSection.tsx` | Same. |
| Tests | New router tests for per-user scoping + dev fallback; new migration round-trip test; new frontend component tests for collapsed-count behavior. |

End of PRD.
