# Save & History — Architecture & Implementation Design

Status: Draft v1
Author: System Architect agent
Date: 2026-05-13
Scope: AI Insights tab — Save/bookmark flow + Past-sessions history
Dependency note: This design references `docs/planning/save-and-history/02-research.md`
(researcher's memo). At authoring time that file does not yet exist on disk; the
design is structured so that any concrete recommendations from the memo (storage
keying, optimistic-update timing, etc.) can be folded in as marginal edits without
restructuring the doc. The reviewer should reconcile this design with the memo
before implementation kicks off.

---

## 1. System Overview

We are adding two user-visible capabilities to the AI Insights tab:

1. **Save / bookmark** — a per-insight toggle. Saved insights survive future
   `ai_session` runs and surface in a dedicated "Saved insights" collapsible
   section. The toggle reuses the existing `insight_subscription` table; the
   `enabled` boolean is the source of truth (`true` = saved).
2. **Past runs history** — a "Past runs" collapsible list below the current
   snapshot, showing prior completed `ai_session` rows. Clicking a row
   expands it inline and lazy-loads that session's insights via the existing
   `GET /api/insights/sessions/{id}/insights` endpoint.

Neither feature requires schema changes. Both are additive on the existing
FastAPI + Postgres + React surface. The "no auth, all bookmarks global" stance
already in production carries over; nothing in this design assumes a user
identity column.

### Component diagram

```text
+-----------------------------------------------------------------------+
|                         React frontend (Vite)                         |
|                                                                       |
|  AIInsightsTab.tsx (existing)                                         |
|    |                                                                  |
|    +-- SnapshotInsightFeed (existing) --> InsightCard (existing)      |
|    |                                         |                        |
|    |                                         +-- SubscribeButton      |
|    |                                             (rewritten — now     |
|    |                                              real Save toggle)   |
|    |                                                                  |
|    +-- SavedInsightsSection.tsx        [NEW]                          |
|    |     uses useSavedInsights         [NEW hook]                     |
|    |                                                                  |
|    +-- PastRunsSection.tsx             [NEW]                          |
|          uses useSessionHistory        [NEW hook]                     |
|          (calls loadSessionInsights on row expand)                    |
+-----------------------------------------------------------------------+
                                  |
                                  | HTTP (fetch)
                                  v
+-----------------------------------------------------------------------+
|                          FastAPI backend                              |
|                                                                       |
|  backend/routers/insights.py (existing)                               |
|    GET    /api/insights/latest                  (MODIFIED: +is_saved) |
|    GET    /api/insights/sessions/{id}/insights  (MODIFIED: +is_saved) |
|    POST   /api/insights/insights/{id}/subscribe (REWRITTEN)           |
|    DELETE /api/insights/insights/{id}/subscribe [NEW]                 |
|    GET    /api/insights/saved                   [NEW]                 |
|    GET    /api/insights/sessions                [NEW]                 |
+-----------------------------------------------------------------------+
                                  |
                                  | SQLAlchemy async
                                  v
+-----------------------------------------------------------------------+
|                         Postgres (existing)                           |
|   ai_session        — completed runs                                  |
|   ai_insight        — per-run insights                                |
|   insight_subscription  — already exists; (enabled=true) = "saved"    |
|   agent_chart, agent_citation — read for snapshot payload (existing)  |
+-----------------------------------------------------------------------+
```

---

## 2. Components & Responsibilities

### Backend
- **`backend/routers/insights.py`** — owns all new endpoints. Same module as
  `/latest` so import surface stays tight; the file is already ~1000 lines but
  conceptually cohesive (one HTTP surface per feature area).
- **`backend/agents/insights/db/models.py`** — `InsightSubscription` SQLModel
  already exists. No changes; we re-use `id`, `insight_id`, `enabled`,
  `created_at`.

### Frontend (paths under `frontend/src/`)
- **`hooks/useSessionHistory.ts`** [NEW] — fetches paginated session list and
  exposes a `loadSessionInsights(sessionId)` helper that caches by id.
- **`hooks/useSavedInsights.ts`** [NEW] — fetches `/api/insights/saved` and
  exposes a `refetch()`.
- **`components/tabs/ai-insights/PastRunsSection.tsx`** [NEW] — collapsible
  container; renders a list of session rows; on expand, lazy-loads insights
  via the hook's helper.
- **`components/tabs/ai-insights/SavedInsightsSection.tsx`** [NEW] —
  collapsible container; renders saved insights as `InsightCard`s; reacts to
  un-save toggles to drop rows.
- **`components/tabs/ai-insights/SubscribeButton.tsx`** [REWRITTEN, same path]
  — real Save toggle. UI label changes from "Subscribe" to "Save"; the
  component filename is kept to minimise blast radius across imports, test
  files, and the design system docs. **Recommendation: keep the filename;
  rename only the user-visible label and `aria-label`.** A future cleanup
  rename can be its own PR if desired.
- **`components/tabs/ai-insights/AIInsightsTab.tsx`** [MODIFIED] — wires in
  the two new sections and threads the `is_saved` state down to InsightCard.

---

## 3. Data Models

### Existing (no schema changes)
- `ai_session(id, status, started_at, finished_at, model, focus, max_insights,
  insights_emitted, duration_ms, budget_status, created_by, ...)`.
- `ai_insight(id, session_id, idx, headline, body, confidence, materiality,
  skills_run, low_external_support, created_at, ...)`.
- `insight_subscription(id, insight_id, criteria_json, created_at, enabled)`.
  - `enabled = true` means "saved".
  - `criteria_json` reserved for a future V3 cron evaluator; we do not write
    to it in this PR.
  - **No unique index on `insight_id`** — see §4 and §8.

### New Pydantic response models (live in `backend/routers/insights.py`)

```python
# Subscribe
class SubscribeResponse(BaseModel):
    saved: bool
    id: Optional[int]                 # subscription row id; None on DELETE

# Saved-list item — extends InsightSummary with session_id + saved_at
class SavedInsightItem(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    idx: int
    headline: str
    body: Optional[str]
    confidence: str
    materiality: str
    skills_run: list[str]
    low_external_support: Optional[bool]
    created_at: Optional[datetime]
    chart: Optional[dict[str, Any]]
    citations: Optional[list[dict[str, Any]]]
    is_saved: bool                    # always True in this payload
    saved_at: datetime                # insight_subscription.created_at

class SavedInsightsResponse(BaseModel):
    items: list[SavedInsightItem]
    total: int

# Session-history row
class SessionHistoryRow(BaseModel):
    id: uuid.UUID
    status: str
    started_at: datetime
    finished_at: Optional[datetime]
    model: Optional[str]
    focus: Optional[str]
    insights_emitted: int
    duration_ms: Optional[int]

class SessionHistoryResponse(BaseModel):
    items: list[SessionHistoryRow]
    total: int                        # cardinality of the filtered set,
                                      # NOT just len(items); needed for paging
```

### Modified payloads
- `GET /api/insights/latest` — every entry in `insights[]` gains
  `"is_saved": bool`.
- `GET /api/insights/sessions/{id}/insights` — every entry in `items[]` gains
  `"is_saved": bool`. This means `InsightSummary` gets a new field; we add it
  as `Optional[bool] = None` if backward-compat is a concern, but for an
  in-house tool with a single frontend we can make it required.

---

## 4. API Contracts

All endpoints live under the existing `/api/insights` router prefix.

### 4.1 `POST /api/insights/insights/{insight_id}/subscribe`

| Aspect | Value |
|---|---|
| Path param | `insight_id: uuid.UUID` |
| Body | none (`{}` allowed and ignored for forward-compat) |
| Response (200) | `SubscribeResponse(saved=True, id=<subscription_row_id>)` |
| 404 | `{"detail": "insight not found"}` if no `ai_insight.id` match |
| 5xx | DB or commit failure |
| Idempotency | Calling twice is a no-op: returns the same row id |

**SQL behavior** (soft upsert; no unique constraint exists today):
1. `SELECT id, enabled FROM insight_subscription WHERE insight_id = :id ORDER BY created_at DESC LIMIT 1`.
2. If row exists and `enabled = true` → return that id, `saved=True`. No write.
3. If row exists and `enabled = false` → `UPDATE insight_subscription SET enabled = true WHERE id = :row_id`, return that id.
4. If no row → `INSERT (insight_id, enabled=true, created_at=now())`, return new id.

The whole sequence runs inside a single `AsyncSession` transaction and commits at
the end. A double-click race is bounded: two concurrent INSERTs could both land
because there is no unique index, but both produce `enabled=true` rows and the
LEFT JOIN's `is_saved` boolean stays correct. Cleanup of duplicate rows is a
follow-up (see §8).

### 4.2 `DELETE /api/insights/insights/{insight_id}/subscribe`

| Aspect | Value |
|---|---|
| Path param | `insight_id: uuid.UUID` |
| Response (200) | `SubscribeResponse(saved=False, id=None)` |
| 404 | `{"detail": "insight not found"}` |
| Idempotency | Yes — already-deleted is also a 200 |

**SQL behavior**:
- `UPDATE insight_subscription SET enabled = false WHERE insight_id = :id AND enabled = true`.
- If 0 rows match (never saved, or already un-saved) → still 200; the response
  shape is `saved=False`.

Soft-delete (flipping `enabled`) is preferred over a hard `DELETE` so we keep
the `created_at` history available for any future "previously saved" UX.

### 4.3 `GET /api/insights/saved?limit=100`

| Aspect | Value |
|---|---|
| Query | `limit: int = 100, ge=1, le=100` |
| Response (200) | `SavedInsightsResponse` |
| Ordering | `insight_subscription.created_at DESC` |
| Cap | Hard-capped at 100 in the Pydantic validator |

**SQL sketch**:
```sql
SELECT ai_insight.*, insight_subscription.id AS sub_id,
       insight_subscription.created_at AS saved_at
FROM insight_subscription
JOIN ai_insight ON ai_insight.id = insight_subscription.insight_id
WHERE insight_subscription.enabled = true
ORDER BY insight_subscription.created_at DESC
LIMIT :limit;
```

The handler then issues a follow-up query for `agent_chart` and
`agent_citation` rows scoped to the collected insight ids, mirroring how
`/latest` assembles its `insights[]` payload (see lines 569-644 of the
existing handler). This avoids N+1 fetches.

### 4.4 `GET /api/insights/sessions?limit=20&offset=0&status=completed`

| Aspect | Value |
|---|---|
| Query | `limit: int = 20, ge=1, le=100` |
| Query | `offset: int = 0, ge=0` |
| Query | `status: str = "completed"` — accepts `complete`, `cancelled`, `failed`, `all` |
| Response (200) | `SessionHistoryResponse` |
| Ordering | `started_at DESC` |
| Default behavior | `status=completed` returns only `ai_session.status = 'complete'` rows |

Note: the existing schema stores the status as `'complete'` (singular). The
query value `"completed"` is the request-side alias for user-friendliness; the
handler maps `"completed" -> "complete"` before issuing SQL. `"all"` skips the
status filter.

**SQL sketch**:
```sql
SELECT id, status, started_at, finished_at, model, focus,
       insights_emitted, duration_ms
FROM ai_session
WHERE status = :status                 -- or no WHERE if status='all'
ORDER BY started_at DESC
LIMIT :limit OFFSET :offset;

-- separately, for total:
SELECT count(*) FROM ai_session WHERE status = :status;
```

Insights are NOT inlined — clients call
`GET /api/insights/sessions/{id}/insights` lazily.

### 4.5 Modified: `GET /api/insights/latest`

Each entry of `insights[]` gains `"is_saved": bool`. Computation:

```sql
SELECT ai_insight.*,
       (sub.id IS NOT NULL) AS is_saved
FROM ai_insight
LEFT JOIN insight_subscription AS sub
       ON sub.insight_id = ai_insight.id
      AND sub.enabled = true
WHERE ai_insight.session_id = :session_id
ORDER BY ai_insight.idx ASC;
```

If the LEFT JOIN matches multiple rows for one insight (the duplicate-row
risk from §4.1), the `IS NOT NULL` collapses them to a single `true`; the
final per-insight output is still one record because we collect into a
Python dict keyed by `ai_insight.id`. As a defensive measure, the handler
can use `DISTINCT ON (ai_insight.id)` or process duplicates in Python.

### 4.6 Modified: `GET /api/insights/sessions/{id}/insights`

Same `is_saved` augmentation as 4.5. Backward compat: existing callers ignore
unknown fields; the new boolean is purely additive.

### Error response shape (all endpoints)
Standard FastAPI: `{"detail": "<message>"}` with appropriate status code.
- 400 — bad query params (Pydantic validation handles this automatically).
- 404 — insight or session not found.
- 500 — DB failure; logged via existing `logger.exception` pattern.

---

## 5. Data Access Layer

### 5.1 Async session usage

All new handlers use `db: AsyncSession = Depends(get_db)` exactly like the
existing `get_session` and `list_session_insights` handlers (lines 373-454).
Commits happen at the end of each write handler; reads do not commit. The
existing `async_session_factory` is only needed inside the SSE handlers that
own their session lifetime — not here.

### 5.2 Idempotent upsert for subscribe

Function signature:

```python
async def _set_subscription_enabled(
    db: AsyncSession,
    *,
    insight_id: uuid.UUID,
    enabled: bool,
) -> Optional[uuid.UUID]:
    """Soft-upsert the insight_subscription row.

    Returns the subscription row id if a row exists after the call, or None
    when `enabled=False` and no row was created (i.e. user un-saves an
    insight that was never saved).

    Idempotency: calling repeatedly with the same `enabled` value yields the
    same row id and no extra rows are inserted on the second+ call (assuming
    a single thread; see §8 for the multi-thread race note).
    """
```

Pseudocode (no implementation, signature + behavior only):

1. `existing = SELECT * FROM insight_subscription WHERE insight_id = :id ORDER BY created_at DESC LIMIT 1`.
2. If `existing` is None and `enabled is True`: INSERT new row, return its id.
3. If `existing` is None and `enabled is False`: return None (no-op).
4. If `existing.enabled == enabled`: return `existing.id` (no write).
5. Else: `existing.enabled = enabled`; flush; return `existing.id`.

The `ORDER BY created_at DESC LIMIT 1` clause is defensive against the
race-window duplicates from the missing unique index — we always look at the
most recent row.

### 5.3 Schema follow-up call-out

Adding `UNIQUE (insight_id)` on `insight_subscription` would eliminate the
duplicate-row risk and let us use `ON CONFLICT (insight_id) DO UPDATE`.
**Schema migrations are out of scope for this PR**, but this is filed as
tech debt; see §8.

### 5.4 `is_saved` LEFT JOIN pattern

Reusable shape across `/latest`, `/sessions/{id}/insights`, and `/saved`:

```python
stmt = (
    select(AIInsight, InsightSubscription.id.label("sub_id"))
    .join(
        InsightSubscription,
        (InsightSubscription.insight_id == AIInsight.id)
        & (InsightSubscription.enabled.is_(True)),
        isouter=True,
    )
    .where(AIInsight.session_id == session_id)
    .order_by(AIInsight.idx.asc())
)
rows = (await db.execute(stmt)).all()
# Then build payload: is_saved = (sub_id is not None)
```

Helper:

```python
async def _fetch_insights_with_saved_flag(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Mirror of the existing /latest insight assembly, but with is_saved.

    Returns the same dict shape used by the existing /latest handler, with
    an added 'is_saved' boolean key on each entry.
    """
```

---

## 6. Frontend Component & Hook Design

### 6.1 `useSessionHistory` (path: `frontend/src/hooks/useSessionHistory.ts`)

```ts
export interface SessionHistoryRow {
  id: string;
  status: "complete" | "cancelled" | "failed";
  startedAt: string;
  finishedAt: string | null;
  model: string | null;
  focus: string | null;
  insightsEmitted: number;
  durationMs: number | null;
}

export interface UseSessionHistoryOptions {
  limit?: number;        // default 20, capped 100
  offset?: number;       // default 0
  status?: "completed" | "all" | "cancelled" | "failed";
}

export interface UseSessionHistoryResult {
  rows: SessionHistoryRow[];
  total: number;
  loading: boolean;
  error: string | null;
  refetch: () => void;
  // Lazy per-session insights cache, keyed by session id.
  loadSessionInsights: (sessionId: string) => Promise<LatestInsight[]>;
  sessionInsights: Record<string, LatestInsight[] | undefined>;
}

export function useSessionHistory(
  opts?: UseSessionHistoryOptions,
): UseSessionHistoryResult;
```

`loadSessionInsights(id)`:
- If `sessionInsights[id]` is already populated, returns it without a fetch.
- Otherwise calls `GET /api/insights/sessions/{id}/insights`, stores the
  array in state keyed by id, and returns it.
- On 404 returns `[]` (the session was deleted between list and expand —
  not possible today, but treated defensively).

### 6.2 `useSavedInsights` (path: `frontend/src/hooks/useSavedInsights.ts`)

```ts
export interface SavedInsightRow extends LatestInsight {
  // Inherits LatestInsight from useLatestInsightSession.ts so InsightCard
  // can render either shape.
  is_saved: true;        // always true in this payload
  saved_at: string;      // ISO timestamp from insight_subscription.created_at
}

export interface UseSavedInsightsResult {
  rows: SavedInsightRow[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useSavedInsights(): UseSavedInsightsResult;
```

The hook fires once on mount, then re-fires when its consumer calls
`refetch()` (e.g. after a successful un-save toggle from inside the section).

### 6.3 Rewritten `SubscribeButton.tsx`

Same path: `frontend/src/components/tabs/ai-insights/SubscribeButton.tsx`.

```ts
export interface SubscribeButtonProps {
  insightId: string;
  initialSaved: boolean;                    // seeded from is_saved in payload
  onToggle?: (next: boolean) => void;       // notifies parent for state lift
}

export default function SubscribeButton(props: SubscribeButtonProps): JSX.Element;
```

**Optimistic update flow** (pseudocode, no real code):

```
onClick:
  if busy: return
  next = !saved
  saved = next                       # optimistic flip
  busy = true
  onToggle(next)                     # tell parent immediately
  try:
    if next:
      res = await fetch POST .../subscribe
    else:
      res = await fetch DELETE .../subscribe
    if !res.ok and res.status != 404:
      throw
  catch err:
    saved = !next                    # revert
    onToggle(!next)
    showToast("Could not update saved state — try again")
  finally:
    busy = false
```

The button is disabled while `busy = true`, which prevents the double-click
race at the UI layer. Even if the user manages to dispatch two rapid clicks
(e.g. via keyboard), the backend's idempotent upsert in §5.2 keeps state
consistent.

### 6.4 `SavedInsightsSection.tsx`

Path: `frontend/src/components/tabs/ai-insights/SavedInsightsSection.tsx`.

```ts
export interface SavedInsightsSectionProps {
  // Allows the parent to push a freshly-saved insight in without forcing a
  // round-trip. Optional; the section also runs its own initial fetch.
  optimisticAdditions?: SavedInsightRow[];
}

export default function SavedInsightsSection(
  props: SavedInsightsSectionProps,
): JSX.Element;
```

Responsibilities:
- Owns its own collapsed/expanded state (defaults to expanded if `rows.length > 0`).
- Uses `useSavedInsights()` for data; re-runs `refetch()` whenever an
  un-save toggle inside the section flips `is_saved=false`, so that row
  disappears from the list.
- Renders each row using the existing `InsightCard` component (which already
  hosts `SubscribeButton`). The button receives `initialSaved=true` and an
  `onToggle` callback that triggers `refetch()`.

### 6.5 `PastRunsSection.tsx`

Path: `frontend/src/components/tabs/ai-insights/PastRunsSection.tsx`.

```ts
export interface PastRunsSectionProps {
  // Optional id of the currently-visible "latest" session, so we can omit
  // it from the past-runs list to avoid duplicate rendering above and below.
  currentSessionId?: string | null;
}

export default function PastRunsSection(props: PastRunsSectionProps): JSX.Element;
```

Responsibilities:
- Uses `useSessionHistory({ limit: 20, status: "completed" })`.
- Renders a collapsible list. Each row shows `started_at` (relative + UTC),
  `insights_emitted`, `duration_ms`, and `focus` (truncated).
- Clicking a row toggles its expanded state. On first expand, calls
  `loadSessionInsights(row.id)` and renders the returned insights inline
  using the same `InsightCard` component.
- Cached insights stay in component-tree state (the hook) for as long as
  the tab is mounted; remounting the tab forces a re-fetch.

### 6.6 State ownership for `is_saved`

**Recommendation**: keep `is_saved` close to the insight it belongs to but
lift the change notification to the immediate parent of `InsightCard`.

- `useLatestInsightSession` already returns the snapshot insights; we extend
  its row type to include `is_saved: boolean`.
- `SnapshotInsightFeed` (parent of `InsightCard`) holds a local override map
  `Record<insightId, boolean>` so that an in-tab toggle updates the visible
  state without a `latest.refetch()`. The override is merged at render time:
  `effectiveIsSaved = overrides[id] ?? row.is_saved`.
- The same pattern applies inside `PastRunsSection` (per-session insight
  arrays from the hook) and `SavedInsightsSection` (the saved-list itself).
- We deliberately avoid a global Context for this — three sections, all
  rendered on the same tab, and prop-drilling depth is at most 2.

If three sections becomes five later, we revisit a small `SavedStateContext`
that holds the override map plus a `setSaved(id, value)` action.

### 6.7 Cache behavior

- `PastRunsSection`: per-session insight arrays are memoised in the hook's
  state, keyed by session_id. Re-clicking an already-expanded session is
  free; collapsing and re-expanding does not refetch.
- `SavedInsightsSection`: re-fetches on any un-save toggle inside itself.
  A save toggle that originates outside (e.g. the user saves an insight from
  the live snapshot) is reflected via `optimisticAdditions` from the parent
  OR via the next mount; we don't need real-time cross-section sync for v1.

---

## 7. Error Handling & Edge Cases

| Case | Behavior |
|---|---|
| POST subscribe on unknown `insight_id` | 404; button reverts; toast "Insight not found". |
| DELETE on unknown `insight_id` | 404; same as above. |
| DELETE on never-saved insight | 200 with `saved=False`; no-op SQL. |
| Network error (any endpoint) | Hook surfaces `error`; section renders inline error + retry button. |
| 5xx on POST subscribe | Optimistic flip reverts; toast. |
| Double-click Save fast | Button `busy=true` blocks UI; backend upsert collapses to a single row in practice (race window is ~ms; if a duplicate row lands, `is_saved` derived via LEFT JOIN still returns true). |
| Session being expanded was deleted | Not possible today (no DELETE on `ai_session`), but `loadSessionInsights` catches 404 and renders an inline "session no longer available" note. |
| Saved list returns 0 rows | Section renders an empty-state copy ("Nothing saved yet — click Save on any insight to bookmark it") and stays collapsible. |
| Past-runs list returns 0 rows | Section header shows "0 past runs"; collapsed by default. |
| `is_saved` field missing in older payload | Frontend treats `undefined` as `false`. |

---

## 8. Risks & Follow-ups

1. **Missing unique index on `insight_subscription.insight_id`** — current
   schema allows duplicate rows. Soft upsert + LEFT JOIN `IS NOT NULL`
   contains the visible damage, but the table can grow stale rows. Filed as
   tech debt; recommend a follow-up migration that:
   - Adds `UNIQUE (insight_id)`.
   - Cleans up duplicates first (`DELETE FROM insight_subscription a USING
     insight_subscription b WHERE a.insight_id = b.insight_id AND a.created_at
     < b.created_at`).
   - Switches the upsert to `ON CONFLICT (insight_id) DO UPDATE SET enabled = excluded.enabled`.
2. **No auth → bookmarks are global**. Already accepted by the team; the
   product is a single-tenant prototype. Re-evaluate when auth lands.
3. **V3 cron will eventually consume `criteria_json`**. Not used here;
   `enabled=true` is enough for the Saved-list semantics.
4. **LEFT JOIN performance**. At prototype scale (<1k insights, <1k
   subscriptions) the join is negligible. If subscription counts grow past
   ~100k we should add a composite index `(insight_id, enabled)`. Not now.
5. **No SSE for save-toggle broadcasts**. Two browser tabs open on the same
   user will not see each other's saves until refresh. Acceptable for a
   single-user prototype.
6. **`SubscribeButton.tsx` filename mismatch with new "Save" semantics** —
   we keep the filename for blast-radius reasons but a future rename to
   `SaveButton.tsx` would clarify the codebase. One-PR rename is cheap once
   imports are stable.

---

## 9. Step-by-Step Implementation Order

Each step lists the owning role (`backend` / `frontend` / `qa`) and the
absolute file paths involved.

1. **[backend] Pydantic models**
   - Path: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/routers/insights.py`
   - Add `SubscribeResponse`, `SavedInsightItem`, `SavedInsightsResponse`,
     `SessionHistoryRow`, `SessionHistoryResponse` near the existing
     `InsightSummary` block (line ~136).

2. **[backend] Helper: idempotent upsert**
   - Path: same file (`backend/routers/insights.py`).
   - Add `_set_subscription_enabled(db, *, insight_id, enabled) -> Optional[uuid.UUID]`.

3. **[backend] Helper: insights with `is_saved`**
   - Path: same file.
   - Add `_fetch_insights_with_saved_flag(db, *, session_id) -> list[dict]`.
     Replaces the inline insight-assembly block in `/latest` and
     `/sessions/{id}/insights`.

4. **[backend] `POST /api/insights/insights/{insight_id}/subscribe`**
   - Path: same file.
   - Validates the insight exists (404 path), calls the upsert helper,
     returns `SubscribeResponse(saved=True, id=row_id)`.

5. **[backend] `DELETE /api/insights/insights/{insight_id}/subscribe`**
   - Path: same file.
   - Validates the insight exists, calls the upsert helper with
     `enabled=False`, returns `SubscribeResponse(saved=False, id=None)`.

6. **[backend] `GET /api/insights/saved`**
   - Path: same file.
   - JOIN query in §4.3; bulk-fetch charts + citations as `/latest` does.

7. **[backend] `GET /api/insights/sessions`**
   - Path: same file.
   - Two queries: paged list + count(*). Status alias map handled in the
     handler.

8. **[backend] Modify `/latest`**
   - Path: same file, function `get_latest_insights` (line ~524).
   - Replace inline insight assembly with `_fetch_insights_with_saved_flag`.
   - Verify the `last_successful` branch also picks up `is_saved`.

9. **[backend] Modify `/sessions/{id}/insights`**
   - Path: same file, function `list_session_insights` (line ~418).
   - Same helper swap. `InsightSummary` gets `is_saved: Optional[bool] = None`.

10. **[qa] Backend tests**
    - Path: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/tests/`
    - New files:
      - `test_subscribe_endpoint.py` — POST then GET asserts saved=true;
        POST twice asserts idempotency (single row, same id); DELETE clears;
        404 on unknown id.
      - `test_saved_endpoint.py` — empty state returns `items=[], total=0`;
        ordering by `created_at DESC`; cap at 100; chart/citation fields
        present.
      - `test_sessions_history_endpoint.py` — paging, status filter
        (`completed` alias → `complete`), ordering, total count.
    - Modify existing:
      - `test_api_insights_latest.py` — assert each insight has `is_saved`
        boolean.

11. **[frontend] `useSessionHistory`**
    - Path: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/src/hooks/useSessionHistory.ts`
    - Implements §6.1 contract. Mirror the cancellation pattern from
      `useLatestInsightSession`.

12. **[frontend] `useSavedInsights`**
    - Path: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/src/hooks/useSavedInsights.ts`
    - Implements §6.2 contract.

13. **[frontend] Rewrite `SubscribeButton`**
    - Path: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/src/components/tabs/ai-insights/SubscribeButton.tsx`
    - New props in §6.3; optimistic toggle flow; revert-on-error toast.
    - Keep filename, change label to "Save"/"Saved".

14. **[frontend] `PastRunsSection`**
    - Path: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/src/components/tabs/ai-insights/PastRunsSection.tsx`
    - Implements §6.5.

15. **[frontend] `SavedInsightsSection`**
    - Path: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/src/components/tabs/ai-insights/SavedInsightsSection.tsx`
    - Implements §6.4.

16. **[frontend] Wire into `AIInsightsTab`**
    - Path: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/src/components/tabs/ai-insights/AIInsightsTab.tsx`
    - Below the existing snapshot grid (post `<main>` block, before the
      closing `</div>`), render:
      ```
      <SavedInsightsSection />
      <PastRunsSection currentSessionId={latest.data?.session?.id ?? null} />
      ```
    - Remove the stub `pastSessions` `useMemo` + the inline `<aside>` rail
      that today renders a single "Past sessions" placeholder (lines
      ~127-144 and ~572-639 in the current file). The new
      `PastRunsSection` supersedes it.

17. **[qa] Frontend tests**
    - Path: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/src/components/tabs/ai-insights/__tests__/`
    - New files:
      - `SubscribeButton.test.tsx` — optimistic flip + revert-on-error.
      - `PastRunsSection.test.tsx` — collapsed default; expand triggers
        single fetch; second expand is cached.
      - `SavedInsightsSection.test.tsx` — empty state; un-save inside
        section removes the row after `refetch`.
    - Update `AIInsightsTab.latest.test.tsx` to ignore the new sections
      (mock the new hooks) so the existing snapshot assertions stay green.

---

## 10. Rollout Strategy

**Recommendation: single PR.** Justification:

- Single developer working the prototype; no parallel team to gate on.
- No public consumers of the API; the frontend in this repo is the only
  client. Adding `is_saved` to `/latest` is technically a non-breaking
  additive change, so even a split rollout has no compatibility risk.
- The backend half on its own delivers zero user value — the toggle and
  sections are the user-visible outcome. Splitting just doubles the PR
  ceremony without buying review safety.
- Tests in steps 10 and 17 sit naturally inside the same PR as their
  feature code, which is the project's existing style.

Branch name suggestion: `feat/save-and-history`. The PR description should
link this design doc and call out the §8 tech-debt items for follow-up.

If the implementer feels the PR is getting too large to review (>1000 line
diff), the natural split is **backend in PR A**, **frontend + qa in PR B**.
PR A is safe to merge on its own because the new endpoints are additive
and the modified payloads only gain a field. PR B does not need backend
changes beyond what A introduces.

---

## 11. ADRs (key decisions)

### ADR-1: Re-use `insight_subscription.enabled` rather than a new `insight_save` table
- **Decision**: `enabled = true` is the source of truth for "saved".
- **Why**: the table exists, the migration history is stable, V3 cron will
  consume the same rows (`criteria_json` becomes meaningful later). A new
  table would force two writes per save and a join across both.
- **Trade-off**: the column name `enabled` is less obvious than `saved`.
  Mitigated by helper functions named `_set_subscription_enabled` so the
  semantics surface at call sites.

### ADR-2: Soft upsert in Python, no unique index in this PR
- **Decision**: SELECT-then-INSERT/UPDATE inside one transaction. Defer the
  `UNIQUE (insight_id)` migration.
- **Why**: schema migrations are out of scope per the PR brief, and the
  prototype scale plus the LEFT JOIN's `IS NOT NULL` reduction mean
  duplicates are visible-state-safe.
- **Trade-off**: duplicate rows can accumulate during fast double-clicks.
  Tracked in §8.

### ADR-3: Soft un-save (flip `enabled=false`) instead of `DELETE`
- **Decision**: DELETE endpoint sets `enabled=false`.
- **Why**: preserves `created_at` history; future UX could surface
  "previously saved" or analytics around save churn.
- **Trade-off**: table grows monotonically. Negligible at prototype scale.

### ADR-4: Keep `SubscribeButton.tsx` filename
- **Decision**: rewrite contents, keep path.
- **Why**: minimises diff blast radius across imports and tests.
- **Trade-off**: filename no longer matches UI label. Cheap follow-up rename
  if the team wants it.

### ADR-5: Single PR rollout
- See §10.

### ADR-6: Component-local override map for `is_saved`, no global context
- **Decision**: each section that hosts `SubscribeButton` keeps its own
  `Record<insightId, boolean>` override map.
- **Why**: prop-drilling depth is at most 2; three sections; introducing a
  Provider is over-engineering at this scale.
- **Trade-off**: future cross-section live sync would require a small
  `SavedStateContext`. Easy to add later when warranted.

---

## 12. Open Questions for the Researcher's Memo

If `docs/planning/save-and-history/02-research.md` lands before
implementation starts, the implementer should confirm or adjust:

1. Whether the saved-list should include cancelled/failed-session insights
   (today's design says yes — saving is per-insight, independent of session
   status).
2. Whether un-save should hard-delete the row instead (this design says
   soft-delete; ADR-3).
3. Default `limit` for `/saved` (this design says 100; cap matches).
4. Default `status` for `/sessions` (this design says `completed`).
5. Whether the past-runs section should hide sessions with
   `insights_emitted = 0` (this design surfaces them and lets the user see
   the empty body on expand).

If the memo lands after implementation has started, any divergence becomes
a follow-up ticket rather than rework — none of the above is structural.
