# PRD: Save & History for AI Insights

- **Owner:** PM (strategic-insights-tool)
- **Status:** Draft v1
- **Date:** 2026-05-13
- **Target reviewer:** Karan (primary user)
- **Surface:** AI Insights tab (desktop web)

---

## 1. Context & Problem Statement

The strategic-insights-tool is a Karan-driven prototype for hyperscaler / datacenter / power competitive intelligence vs OCI. The AI Insights tab is the most-used surface: it runs an agentic synthesis pipeline that produces a small portfolio of insight cards (typically 3-7) for a given run.

Today, that tab is effectively **single-shot and amnesiac**:

- The frontend only renders `GET /api/insights/latest` — the most recent completed AI session.
- When the scheduler (or a manual "Run again") produces a new session, the previous run is invisible from the UI. The only way to revisit an older run is to query the database directly.
- The `SubscribeButton` on each `InsightCard` is a **no-op** that shows a `"V3 — coming soon"` toast. There is no way for Karan to flag insights he wants to come back to later.

This hurts the prototype's core value loop:

1. Karan cannot **compare** today's insights against yesterday's run to see what shifted.
2. Karan cannot **curate** a personal shortlist of insights worth showing to stakeholders.
3. Re-running the agent (or waiting for the next scheduled run) **silently destroys** the previous narrative from his view.

We have the data — `ai_session`, `ai_insight`, and an unused `insight_subscription` table already exist. We just don't expose them.

This PRD covers the minimum surface to fix both problems: a **past-sessions history list** and a **save/bookmark flow**.

---

## 2. Goals & Non-Goals

### 2.1 Goals

- Let Karan browse and expand previous completed AI Insight sessions inline, without leaving the AI Insights tab.
- Let Karan save (bookmark) individual insights from any session and revisit them in a dedicated "Saved" section.
- Repurpose the existing `SubscribeButton` real estate into a working save toggle — no new UI primitives, no new icons beyond a filled vs outline bell.
- Reuse `insight_subscription` as a global bookmark store with `enabled = true` semantics.
- Ship without schema migrations.

### 2.2 Non-Goals

| Item | Why not now |
|---|---|
| Authentication / per-user scoping | Prototype is single-user (Karan); bookmarks are global. |
| V3 cron-style subscriptions matching new insights against `criteria_json` | Out of scope; `criteria_json` stays `NULL` for this feature. |
| Mobile / responsive polish | Desktop-only tool. |
| New schema migrations or new tables | We will reuse `insight_subscription` as-is. |
| Cross-session diff / "what changed since yesterday" | Future work; this PRD only enables browsing, not diffing. |
| Pagination UI beyond limit/offset on the past-sessions list | Keep prototype-simple; 20 per page is enough. |
| Saved-insight export, share links, tagging, folders | Out of scope. |
| Search / filter within past sessions or saved insights | Out of scope. |

---

## 3. User Stories

1. **As a competitive-intel analyst (Karan)**, I want to see a list of my past AI Insight runs and expand any one of them inline, so that I can revisit the narrative I saw last Tuesday without re-running the agent.
2. **As a competitive-intel analyst**, I want to click a bell on any insight card to save it, so that I can build a personal shortlist of the most useful findings.
3. **As a competitive-intel analyst**, I want a dedicated "Saved" section at the top (or near the top) of the AI Insights tab, so that my shortlist is one click away.
4. **As a competitive-intel analyst**, I want unsaving an insight from the Saved section to remove it from that list immediately, so that the list stays curated and trustworthy.
5. **As a competitive-intel analyst**, I want both new sections to be collapsible and lazy-loaded, so that the page stays fast and uncluttered when I just want today's run.

---

## 4. Functional Requirements

### 4.1 Save / Bookmark Flow (repurpose `SubscribeButton`)

The existing `SubscribeButton` rendered inside each `InsightCard` is replaced by a real save toggle. No new component file is required; reuse the slot.

**Visual states**

| State | Icon | Label | Notes |
|---|---|---|---|
| Not saved | Outline bell | "Save" | Default state for any insight whose `is_saved = false`. |
| Saved | Filled bell | "Saved" | After a successful POST, or when `is_saved = true` on load. |
| In-flight (optimistic) | Show target state (filled when saving, outline when unsaving) | Same as target | Disabled / non-interactive for the ~150ms request window. |
| Error | Revert to previous state | Previous label | Toast: "Couldn't save insight. Try again." |

**Behavioral rules**

- Drop the existing `"V3 — coming soon"` toast entirely.
- Clicks are optimistic: flip the visual state immediately, fire the request, revert + toast on failure.
- Toggling off on an insight that lives inside the **Saved** section removes that row from the section (see 4.3).
- Toggling on/off on an insight inside the **Past Runs** expansion updates the bell visually but does **not** rearrange the past-runs list.
- Toggling on/off on an insight in the "latest" section just updates the bell.

### 4.2 Past Runs Section

A new collapsible section in the AI Insights tab labeled **"Past Runs"**. It sits below the current "latest" insights block.

**Initial state**

- Collapsed by default.
- Header shows the section title and a chevron.
- Expanding triggers a lazy fetch of `GET /api/insights/sessions?limit=20&offset=0`.

**Row layout (one per session)**

Each row is a compact summary, not a full insight render:

| Column | Source | Format |
|---|---|---|
| Date | `started_at` | `Mon May 11, 09:14 UTC` (desktop-only, no relative time needed) |
| # Insights | `insights_count` | e.g. `5 insights` |
| Focus | `focus` or first 80 chars of session title/criteria | Truncated with ellipsis |
| Trigger badge (optional) | `created_by` | `scheduler` / `probe` / `manual` — small pill |

Clicking a row expands it inline and lazy-loads `GET /api/insights/sessions/{id}/insights`, rendering the existing `InsightCard` component for each insight. A second click collapses the row. Only one row needs to be expandable at a time (multi-expand is allowed but not required — implementer's call).

**Pagination**

- 20 sessions per page.
- "Load more" button at the bottom that bumps `offset` by `limit`. No infinite scroll.
- Hide "Load more" when the server returns fewer than `limit` rows.

**Empty state**

- "No past runs yet. Run the agent to populate history."

### 4.3 Saved Insights Section

A new collapsible section in the AI Insights tab labeled **"Saved"**, positioned **above Past Runs** (and below the "latest" block) so the curated shortlist is the first thing Karan sees on scroll.

**Behavior**

- Collapsed by default. Expanding lazy-loads `GET /api/insights/saved`.
- Renders each saved insight using the existing `InsightCard` component (with bell in the "Saved" state).
- Sorted by `subscription.created_at DESC` (newest save first).
- Capped at 100 items (server-side); no pagination UI in v1.
- When a user clicks the bell on a card inside this section to unsave it, the row animates/fades out and is removed from the list. Re-saving from elsewhere will reappear on next expand/refresh.

**Empty state**

- "No saved insights. Click the bell on any insight card to save it here."

---

## 5. API Contract Summary

All endpoints live under the existing `/api/insights` router, follow current FastAPI async patterns, and return JSON unless noted. Responses are illustrative shapes, not implementation contracts.

### 5.1 POST `/api/insights/insights/{insight_id}/subscribe`

Idempotent save.

- 200 on success (including when already saved).
- 404 if `insight_id` does not exist.
- Inserts a row into `insight_subscription` with `enabled = true`, `criteria_json = NULL`. If a row already exists with `enabled = false`, flips it to `true`.

Response:

```
{ "insight_id": "uuid", "is_saved": true, "saved_at": "2026-05-13T14:02:11Z" }
```

### 5.2 DELETE `/api/insights/insights/{insight_id}/subscribe`

Idempotent unsave.

- 200 on success (including when not currently saved).
- 404 if `insight_id` does not exist.
- Either deletes the row or flips `enabled = false` — implementer's choice; recommend hard delete for simplicity since `criteria_json` is unused.

Response:

```
{ "insight_id": "uuid", "is_saved": false }
```

### 5.3 GET `/api/insights/saved`

List bookmarked insights.

- Returns full `InsightCard`-ready payloads (same shape as `/latest` returns).
- Ordered by `subscription.created_at DESC`.
- Server-side cap: 100.
- Each payload includes `is_saved: true`.

Response:

```
{
  "items": [ { "id": "...", "title": "...", "is_saved": true, ... } ],
  "count": 12
}
```

### 5.4 GET `/api/insights/sessions`

Paginated list of past AI sessions.

- Query params: `limit` (default 20, max 50), `offset` (default 0), `status` (default `completed`).
- Ordered by `started_at DESC`.
- Returns lightweight session metadata only — no insights inlined.

Response:

```
{
  "items": [
    {
      "id": "uuid",
      "started_at": "2026-05-13T09:14:00Z",
      "completed_at": "2026-05-13T09:14:32Z",
      "status": "completed",
      "created_by": "scheduler",
      "focus": "Datacenter power buildout — week of May 11",
      "insights_count": 5
    }
  ],
  "limit": 20,
  "offset": 0,
  "has_more": true
}
```

### 5.5 Existing endpoints — add `is_saved`

Augment the insight payload returned by:

- `GET /api/insights/latest`
- `GET /api/insights/sessions/{session_id}/insights`
- `GET /api/insights/insights/{insight_id}` (detail)

Each insight gains a top-level boolean field `is_saved`, derived from a single JOIN/EXISTS against `insight_subscription` where `enabled = true`. No backfill required — defaults to `false`.

---

## 6. Data Model Usage

Reuse the existing `insight_subscription` table. **No new tables, no migrations.**

| Column | Type | Usage in this feature |
|---|---|---|
| `id` | UUID PK | Auto. |
| `insight_id` | FK -> `ai_insight.id` | The saved insight. |
| `criteria_json` | JSONB nullable | Always `NULL` for this feature (reserved for V3). |
| `enabled` | bool | `true` = saved. `false` = unsaved (or row absent). |
| `created_at` | timestamptz | Sort key for the Saved section. |

**Uniqueness:** treat `(insight_id)` as effectively unique for the global-bookmark use case. If a unique constraint does not exist in the DB, the POST handler must do a select-then-insert/update inside a single transaction to keep idempotency safe under concurrent clicks. A future migration can add a partial unique index; not in scope here.

---

## 7. Acceptance Criteria

### 7.1 Save toggle on InsightCard

- [ ] The V3 `"coming soon"` toast no longer appears anywhere in the app.
- [ ] Bell renders as outline + label "Save" when `is_saved = false`.
- [ ] Bell renders as filled + label "Saved" when `is_saved = true`.
- [ ] Clicking the bell flips visual state immediately (optimistic).
- [ ] A successful POST persists the save and a page refresh shows the same saved state.
- [ ] A failed POST/DELETE reverts the bell and shows a non-blocking toast.
- [ ] Double-clicking the bell rapidly never produces duplicate rows in `insight_subscription`.

### 7.2 Past Runs section

- [ ] Section is collapsed on first render and shows zero network calls until expanded.
- [ ] Expanding triggers exactly one `GET /api/insights/sessions` call (with default params).
- [ ] Each row shows date, insights count, and focus/title.
- [ ] Clicking a row lazy-loads that session's insights and renders them via `InsightCard`.
- [ ] Each rendered `InsightCard` shows the correct `is_saved` state.
- [ ] "Load more" appears only when `has_more = true` and increments `offset` correctly.
- [ ] Empty state copy renders when the API returns `items: []`.

### 7.3 Saved section

- [ ] Section is collapsed on first render; expanding fires exactly one `GET /api/insights/saved`.
- [ ] Items are ordered by `subscription.created_at DESC`.
- [ ] Clicking the bell on a card in this section removes it from the list within ~300ms.
- [ ] Empty state copy renders when there are no saved insights.
- [ ] The list never shows more than 100 entries.

### 7.4 API behavior

- [ ] POST and DELETE subscribe endpoints are idempotent (verified via repeated calls).
- [ ] POST/DELETE on a nonexistent `insight_id` returns 404 with a clean error body.
- [ ] `/latest`, `/sessions/{id}/insights`, and `/insights/{id}` all include `is_saved` on every insight.
- [ ] `/saved` returns at most 100 items.
- [ ] `/sessions` defaults to `status=completed` and rejects `limit > 50` with 422.

---

## 8. Edge Cases

| # | Scenario | Expected behavior |
|---|---|---|
| E1 | Save a nonexistent insight ID | 404 from API; frontend shows error toast and does not flip the bell. |
| E2 | Save the same insight twice in quick succession | Server is idempotent; only one effective `enabled=true` row exists. UI shows "Saved" once. |
| E3 | Unsave from the Saved section | Row disappears from Saved; if that same insight is visible elsewhere on the page (latest or an expanded past run), its bell updates to outline. |
| E4 | Re-save an insight after unsaving | New `created_at` (or flipped `enabled=true`); it appears at the top of Saved on next expand. |
| E5 | Network error on save | Optimistic state reverts; toast shown; no DB write. |
| E6 | Concurrent click on bell while previous request is in-flight | Disable button until the request resolves, OR debounce to the latest intent. Implementer's call; whichever is simpler. |
| E7 | A past session has zero insights | Row still renders; expanding shows an empty "(no insights for this run)" state. |
| E8 | A saved insight belongs to a session that has since been re-run | The saved insight remains visible (insights are immutable per session). See Open Questions Q1. |
| E9 | `/saved` returns 100 items (cap hit) | Show a small "Showing most recent 100 saved" footer. No pagination in v1. |
| E10 | Past Runs expanded row, then collapsed and re-expanded | Cache the response in component state to avoid refetching unless the user reloads the page. |

---

## 9. Success Metrics

Prototype-grade and qualitative:

- Karan can open the AI Insights tab and locate yesterday's run in under 10 seconds without engineering help.
- Karan accumulates >= 5 saved insights within the first week of the feature being live, indicating the shortlist habit is sticking.
- Zero regressions reported on the existing "latest" insights flow.
- No "V3 — coming soon" toast appears in any session of dogfooding.

A lightweight follow-up: when Karan opens a stakeholder review, he can pull up his Saved list as the agenda instead of re-running the agent live.

---

## 10. Open Questions

1. **Stale-session saved insights** — when a session is re-run (especially manual "Run again"), should Saved continue to show insights from the older session? **Default position: yes.** `ai_insight` rows are immutable per session, so a saved insight is a stable artifact, not a pointer to "current narrative." If we ever want "saved → always shows the most recent equivalent," that requires a similarity match and is out of scope.
2. **Trigger badge in Past Runs rows** — do we want to surface `created_by` (scheduler / probe / manual) as a pill? Useful for debugging but visually noisy. Default: include it, small and muted.
3. **Cap on Saved** — 100 feels generous for a single-user prototype. Confirm with Karan; if he wants more, we revisit before adding pagination.
4. **Hard-delete vs soft-delete on unsave** — recommend hard delete since `criteria_json` is unused. Confirm before implementation.
5. **Sort within an expanded past-run** — preserve the original insight ordering from the session (i.e. agent's portfolio ranking), not by `created_at`. Confirm.
6. **What counts as "completed" for `/sessions`** — assume the existing `AISession.status` enum value. Need to verify the exact string used in the codebase before wiring the filter.

---

## 11. Rollout Note

**Recommendation: ship as a single PR (backend + frontend together).**

Justification:

- The feature is small (no migrations, two new endpoints + one field addition on three existing endpoints, two new collapsible UI sections, one component repurpose).
- The frontend is meaningfully testable only once the backend returns `is_saved` and the new lists. Splitting would create an awkward intermediate state where the frontend mocks the API.
- This is a single-user prototype with no staged rollout, no feature flags, and no production traffic to protect.
- Risk is contained: the existing `/latest` path is unchanged except for an additive `is_saved` field.

If the PR grows beyond ~600 lines of diff, split along this seam:

1. **PR-1 (backend):** new endpoints, `is_saved` field on existing responses, tests.
2. **PR-2 (frontend):** SubscribeButton repurpose + Saved + Past Runs sections.

Both PRs target `main`. No feature flag.

---

## 12. Out of Scope (recap)

- Auth, per-user scoping
- V3 cron / `criteria_json` matching
- Mobile / responsive layout
- Schema migrations or new tables
- Diff / compare across sessions
- Search, filter, tagging, folders, export, share links

---

## 13. Appendix: Touchpoint Summary

| Area | Change |
|---|---|
| `backend/routers/insights.py` | +4 routes, +`is_saved` on 3 existing payloads |
| `backend/db/models.py` / `agents/insights/db/models.py` | No change (reuse `insight_subscription`) |
| `frontend/src/components/insights/SubscribeButton.tsx` (or equivalent) | Repurpose: bell toggle, drop V3 toast |
| `frontend/src/components/insights/InsightCard.tsx` | Read `is_saved`, wire toggle handler |
| AI Insights tab container | +2 collapsible sections (Saved, Past Runs) |
| `frontend/src/styles/insightTokens.ts` | Reuse existing tokens; add bell-filled color if not present |
| Tests | New router tests for subscribe/unsave/saved/sessions; frontend smoke tests for toggle + lazy-load |

End of PRD.
