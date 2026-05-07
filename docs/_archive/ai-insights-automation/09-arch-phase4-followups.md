# 09 — Architecture: Phase 4 follow-ups (`include_failed`, last-successful, FE wiring, Vitest)

**Owner:** System Architect
**Date:** 2026-05-05
**Predecessors:** `07-qa-test-plan-phase4.md` §3–§4, `04a-ux-delta-phase4-implementation.md` §4

This ADR closes the AC-A7 gap left open in `07-qa-test-plan-phase4.md` §4
("`FailedLatestBanner.tsx` is a scaffold behind an always-false prop").
It defines (1) the new `include_failed=true` selection branch on the
backend, (2) the response-schema delta, (3) the frontend wiring, and
(4) the Vitest test boundaries.

---

## 1. Backend `/latest` selection rules — `include_failed=true`

Source: `backend/routers/insights.py:527-664` (current handler).

### Pseudocode

```
GET /api/insights/latest?include_failed={false|true}

# --- shared helper (refactor) -------------------------------------
async def _build_session_payload(db, row: AISession) -> dict:
    insights = SELECT * FROM ai_insight WHERE session_id=row.id ORDER BY idx ASC
    charts   = SELECT * FROM agent_chart WHERE session_id=row.id   # LEFT JOIN
    return { "session": <session_payload as today, lines 644-657>,
             "insights": <insight rows, lines 614-642> }

# --- default branch (unchanged: include_failed in (None, "false")) -
recent = SELECT * FROM ai_session
         WHERE status = 'complete'
         ORDER BY started_at DESC
         LIMIT 5
if not recent: 404 "no completed session yet"
chosen = pick_today_scheduler_else_most_recent(recent)   # existing logic
payload = await _build_session_payload(db, chosen)
return { **payload,
         "started_at": payload["session"]["started_at"],
         "status":     chosen.status }
# NOTE: no `last_successful` key on this branch (back-compat).

# --- include_failed=true branch -----------------------------------
recent_any = SELECT * FROM ai_session
             ORDER BY started_at DESC
             LIMIT 5
if not recent_any: 404 "no session yet"
chosen = pick_today_scheduler_else_most_recent(recent_any)  # SAME tiebreak

last_successful = None
if chosen.status == "failed":
    last_done = (SELECT * FROM ai_session
                 WHERE status = 'complete'
                 ORDER BY started_at DESC
                 LIMIT 1).one_or_none()
    if last_done is not None:
        last_successful = await _build_session_payload(db, last_done)

payload = await _build_session_payload(db, chosen)
return { **payload,
         "started_at":      payload["session"]["started_at"],
         "status":          chosen.status,
         "last_successful": last_successful }   # may be None
```

### Failure-reason exposure (open question resolved)

`AISession` has no `failure_reason` column (see `backend/db/models.py`
schema; the only failure-adjacent field is `budget_status`). Adding a
column is out of scope for this follow-up. Resolution:

- The handler already returns `chosen.budget_status` and
  `chosen.duration_ms` in `session_payload` (insights.py:653-654).
  No schema change required.
- The banner sub-line uses only `failedAt` (HH:mm UTC) — no free-text
  reason rendered. If we later want a "View error" detail panel,
  the FE shall render `budget_status` verbatim if non-null/non-`"ok"`,
  else the literal `"unknown"`. This is documented but not implemented
  in this follow-up.

### 404 semantics

- Default branch: 404 iff zero `complete` rows.
- `include_failed=true` branch: 404 iff zero rows of any status.
  Detail: `"no session yet"` (distinct from default's
  `"no completed session yet"` — see QA plan §4 line 163).

---

## 2. Response schema (JSON)

```jsonc
// include_failed omitted or "false" — UNCHANGED, no last_successful key
{
  "session":    { ... },
  "insights":   [ ... ],
  "started_at": "...",
  "status":     "complete"
}

// include_failed=true
{
  "session":    { ... },           // the chosen row (any status)
  "insights":   [ ... ],           // chosen row's insights
  "started_at": "...",
  "status":     "complete | failed | running | cancelled",
  "last_successful":
       null                                       // when chosen.status != "failed"
    |  null                                       // when chosen.status == "failed" AND no prior complete
    | { "session": {...}, "insights": [ ... ] }   // when chosen.status == "failed" AND a prior complete exists
}
```

Back-compat invariant: clients that do not pass `include_failed` MUST
NOT see `last_successful` in the response. The current
`useLatestInsightSession` hook ignores unknown keys, but the schema
contract is tighter so future clients can assert presence.

---

## 3. Frontend wiring

Source files: `frontend/src/hooks/useLatestInsightSession.ts`,
`frontend/src/components/tabs/ai-insights/AIInsightsTab.tsx`,
`frontend/src/components/tabs/ai-insights/FailedLatestBanner.tsx`,
`frontend/src/components/tabs/ai-insights/SnapshotInsightFeed.tsx`.

### Hook signature delta

```ts
// useLatestInsightSession.ts
export interface LatestSessionResponseFull extends LatestSessionResponse {
  last_successful?: { session: LatestSessionRow; insights: LatestInsight[] } | null;
}
export function useLatestInsightSession(
  includeFailed: boolean = false,           // <-- new
): UseLatestResult /* now data: LatestSessionResponseFull | null */;
```

The fetch URL becomes
`` `${API_BASE}/api/insights/latest${includeFailed ? "?include_failed=true" : ""}` ``.
Default `false` preserves every other call-site.

### `AIInsightsTab` callsite

Replace `useLatestInsightSession()` (line 73) with
`useLatestInsightSession(true)`. Then:

```ts
const failed     = latest.data?.session?.status === "failed";
const lastOk     = latest.data?.last_successful ?? null;
const showFailedBanner = failed;                       // replaces line 299

const snapshotForRender =
  failed && lastOk ? lastOk.insights : snapshotInsights;
const totalForRender =
  failed && lastOk
    ? (lastOk.session.max_insights ?? lastOk.insights.length)
    : (latest.data?.session?.max_insights ?? snapshotInsights.length);
```

Render order in the failed-with-fallback case:

1. `<FailedLatestBanner failedAt={session.started_at}
                          lastSuccessfulAt={lastOk.session.started_at}
                          onRetry={() => startSession()} />`
2. `<SnapshotInsightFeed insights={lastOk.insights} total={...} />`
3. Past-sessions rail (lines 486–553) still includes the failed row
   (the existing `pastSessions` memo at line 118 already maps
   non-`complete`/non-`cancelled` to `"failed"` — no change needed).

Failed-with-no-fallback case (`failed && lastOk === null`):

1. `<FailedLatestBanner failedAt={...} lastSuccessfulAt={null} />`
   (banner already handles null — see FailedLatestBanner.tsx:43, 109).
2. `<EmptyState onRun={() => startSession()} />`.

When `status !== "failed"`: existing complete/running/cold-start paths
(AIInsightsTab.tsx:556-587) are untouched.

---

## 4. Vitest test boundaries

Three cases from QA plan §4 ("AC-A4..A7 deferred"):

| # | Case                                  | Mock surface                          |
|---|---------------------------------------|---------------------------------------|
| 1 | failed + last_successful present      | `fetch` returns `{status:"failed", last_successful:{...}}` |
| 2 | failed + last_successful null         | `fetch` returns `{status:"failed", last_successful:null}`  |
| 3 | no flash-of-empty during Run-again    | `fetch` returns complete payload; `EventSource` stub never emits |

### Recommended setup

```ts
// vitest.setup.ts (or top of each test file)
class NoopEventSource {
  url: string;
  withCredentials = false;
  readyState = 0;
  onopen: any = null; onmessage: any = null; onerror: any = null;
  constructor(url: string) { this.url = url; }
  close() { this.readyState = 2; }
  addEventListener() {} removeEventListener() {} dispatchEvent() { return true; }
}
vi.stubGlobal("EventSource", NoopEventSource);

// per case:
vi.stubGlobal("fetch", vi.fn(async (url: string) => {
  if (url.endsWith("/api/insights/latest?include_failed=true")) {
    return new Response(JSON.stringify(FIXTURE), { status: 200 });
  }
  return new Response("{}", { status: 200 });
}));
```

Rationale:

- `fetch` is the only network hop on the snapshot path; per-case
  `vi.stubGlobal('fetch', ...)` keeps cases isolated.
- `SessionRunner` (rendered in case 3) constructs an `EventSource` in
  its mount effect. Stubbing the constructor at module-init time
  means the test never opens a real connection and never needs to
  drive SSE events (case 3 only checks that `snapshotInsights`
  remains rendered until `firstCompleteSeen` flips, which is
  state-driven, not SSE-driven).
- Cases 1+2 don't reach `SessionRunner` (the failed-banner branch
  renders `SnapshotInsightFeed` or `EmptyState`); the EventSource
  stub is harmless dead weight there.

---

## ADRs (key decisions)

- **ADR-09a:** Use a query param (`?include_failed=true`), not a new
  endpoint. Keeps a single canonical path; back-compat is preserved
  by omitting `last_successful` on the default branch.
- **ADR-09b:** Do not add `failure_reason` to `ai_session`. Surface
  `budget_status` only; banner sub-line stays free of free-text
  reasons. Schema migration deferred until product asks for it.
- **ADR-09c:** Reuse the same today/scheduler tiebreak across both
  branches (symmetry > minimal divergence). A failed scheduler row
  today still wins over a manual row today, which matches user
  intent ("show me what auto-ran").
- **ADR-09d:** Refactor the payload builder to a single inner helper
  before adding the new branch — avoids drift between the chosen
  payload and the `last_successful` payload.

## Risks & mitigations

- **R1 — API drift between branches.** Mitigation: ADR-09d helper.
- **R2 — Frontend assumes `last_successful` exists when calling with
  `includeFailed=false`.** Mitigation: hook param defaults to false;
  `LatestSessionResponseFull.last_successful` is optional; back-compat
  invariant in §2.
- **R3 — `EventSource` stub leaks across tests.** Mitigation:
  `vi.unstubAllGlobals()` in `afterEach`.
- **R4 — Tiebreak surprises (failed scheduler today beats complete
  manual today).** Acceptable per ADR-09c; documented here so
  reviewers don't treat it as a bug.
