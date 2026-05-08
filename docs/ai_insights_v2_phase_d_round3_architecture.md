# AI Insights v2 — Phase D, Round 3 Architecture

**Date:** 2026-05-08
**Predecessors:** Round 1 + Round 2 are described in
[`ai_insights_v2_phase_d_v2_path_fix.md`](./ai_insights_v2_phase_d_v2_path_fix.md).
**Status:** Architecture-only. Implementation, tests, and rollout deferred to
the engineering lane.
**Scope:** A single, additive reordering of the v2 agentic loop —
**persist first, chart second** — to remove the chart-id round-trip that
two prior rounds traced as the dominant failure surface.

---

## System Overview

The v2 synthesis path today couples two MCP tool calls in a strict order:

1. `build_chart(...)` — runs gated SQL, validates encoding, persists an
   `agent_chart` row with `insight_id = NULL`, returns `chart_id`.
2. `persist_insight_v2(chart_id=..., ...)` — re-resolves `chart_id`,
   asserts session match, inserts `ai_insight`, then patches
   `agent_chart.insight_id` to bind the chart back to the insight.

This ordering is the source of every Round 1 + Round 2 production
failure and most of the test fragility:

* The agent must thread a structured `chart_id` token across two tool
  calls. Round 2 demonstrated empirically that the LLM drops the
  second call ~one in three sessions even with a hard-imperative
  prompt.
* The handoff requires a successful intermediate DB commit. Round 1
  P4 was exactly this: the chart row was uncommitted on a different
  pool connection by the time `persist_insight_v2` re-read it.
* The error surface is asymmetric: a chart succeeds but the insight
  fails, or vice-versa, and the orchestrator's degraded-finalise path
  cannot disambiguate without a second SELECT (Round 2 R2-C).

**Round 3 inverts the order.** `persist_insight_v2` becomes the first
durable write of the loop and `build_chart` carries an `insight_id` it
binds to the chart inside the same `_invoke()` transaction. The
agent's contract simplifies to "persist, then chart" — the same
imperative shape Round 2's prompt rewrite already enforces, just with
the steps swapped.

This is **purely additive** at the data layer. Migration 018 already
made `agent_chart.insight_id` nullable; Round 3 reuses that nullability
for the inverse direction (`ai_insight.chart_id` is also nullable per
018). v1 control flow is untouched.

---

## Architecture Diagram (sequence — old vs new)

### OLD flow (chart-first; current main)

```
LLM                     MCP /invoke              registry             tool fn               DB
 |   build_chart(...)     |                        |                    |                    |
 |----------------------->|                        |                    |                    |
 |                        | dispatch("build_chart")|                    |                    |
 |                        |----------------------->| build_chart(db=..) |                    |
 |                        |                        |------------------->| INSERT agent_chart  |
 |                        |                        |                    |   insight_id=NULL  |
 |                        |                        |                    |------------------->|
 |                        |                        |                    |                    |
 |                        |                        |  {ok, chart_id}    |                    |
 |                        |                        |<-------------------|                    |
 |                        |  COMMIT (Round 1 fix)  |                    |                    |
 |                        |--------------------------------------------------- ------------->|
 | {ok, chart_id}         |                        |                    |                    |
 |<-----------------------|                        |                    |                    |
 |                        |                        |                    |                    |
 |  persist_insight_v2(chart_id=...)               |                    |                    |
 |----------------------->|                        |                    |                    |
 |                        | dispatch("persist...") |                    |                    |
 |                        |----------------------->| persist_insight_v2 |                    |
 |                        |                        |  _resolve_chart -- |--- SELECT --------->|
 |                        |                        |  INSERT ai_insight |--- INSERT --------->|
 |                        |                        |  UPDATE agent_chart|--- UPDATE --------->|
 |                        |                        |    .insight_id     |                    |
 |                        |  COMMIT                |                    |                    |
 |                        |--------------------------------------------------- ------------->|
 | {ok, insight_id}       |                        |                    |                    |
 |<-----------------------|                        |                    |                    |
```

Failure modes accreted on this path: chart-id drop (Round 2 H1),
cross-connection invisible row (Round 1 P4), session_closed mid-loop,
and `chart_session_mismatch` if the agent recycles a stale id.

### NEW flow (insight-first; Round 3)

```
LLM                     MCP /invoke              registry             tool fn               DB
 |  persist_insight_v2(...)         (no chart_id) |                    |                    |
 |----------------------->|                        |                    |                    |
 |                        | dispatch("persist...") |                    |                    |
 |                        |----------------------->| persist_insight_v2 |                    |
 |                        |                        |  chart_id=None  -- |  no chart guard    |
 |                        |                        |  INSERT ai_insight |--- INSERT --------->|
 |                        |                        |    chart_id=NULL   |                    |
 |                        |  COMMIT                |                    |                    |
 |                        |--------------------------------------------------- ------------->|
 | {ok, insight_id}       |                        |                    |                    |
 |<-----------------------|                        |                    |                    |
 |                        |                        |                    |                    |
 |  build_chart(insight_id=..., sql=..., encoding=...)                  |                    |
 |----------------------->|                        |                    |                    |
 |                        | dispatch("build_chart")|                    |                    |
 |                        |----------------------->| build_chart        |                    |
 |                        |                        |  resolve insight - |--- SELECT --------->|
 |                        |                        |  session match?    |                    |
 |                        |                        |  INSERT agent_chart|                    |
 |                        |                        |    insight_id=...  |--- INSERT --------->|
 |                        |  COMMIT                |                    |                    |
 |                        |--------------------------------------------------- ------------->|
 | {ok, chart_id}         |                        |                    |                    |
 |<-----------------------|                        |                    |                    |
```

The agent's only stateful obligation is to remember the `insight_id`
returned in step 1 and pass it into step 2. That is the same
single-token forward-reference Round 2's prompt rewrite already
codifies — just attached to the persist step instead of the chart
step.

---

## Components & Responsibilities

| Component | Round 2 role | Round 3 role |
|---|---|---|
| `persist_insight_v2.py` | Final sink. Required `chart_id`. Bound chart back via UPDATE. | First sink. `chart_id: str \| None = None`. When None, skip chart-resolution; insert `ai_insight.chart_id = NULL`. Return shape unchanged. |
| `build_chart.py` | Independent producer. Wrote `agent_chart` with `insight_id = NULL`. | Insight-bound producer. New optional `insight_id` param. When provided, SELECT `ai_insight`, assert `session_id` match, then INSERT `agent_chart` with `insight_id = <that uuid>`. When None, current behaviour preserved. |
| `registry.py::dispatch` | Forwards `chart_id` to persist; nothing about insight_id to build_chart. | Forwards `insight_id` (when present) into `build_chart(...)`. `persist_insight_v2(chart_id=...)` continues to forward whatever the agent passed (now usually None/absent). |
| `mcp_server.py` build_chart wrapper | Required `insight_id` positional arg, but never forwarded it into the dispatch dict. | Adds `insight_id: Optional[str] = None` to the dict and forwards it through `_invoke`. |
| `mcp_server.py` persist_insight_v2 wrapper | `chart_id: str` (required). | `chart_id: Optional[str] = None`. |
| `synthesis_rules_v2.md` | Step 3 = chart, step 4 = persist. | Step 3 = persist (no `chart_id` needed), step 4 = chart with `insight_id`. |
| `sse_translator.py` | Emits `InsightStarted/Complete` on persist, `ToolCallStarted/Complete` on build_chart. | **Unchanged.** See §SSE Ordering Analysis. |

---

## Data Models

No DDL changes. The shape is fully expressed by migration 018:

* `agent_chart.insight_id UUID NULL` — added in 018.
* `ai_insight.chart_id TEXT NULL FK agent_chart.id ON DELETE SET NULL` — added in 018.
* `ai_insight.version TEXT NOT NULL DEFAULT 'v1'` — set to `'v2'` by `persist_insight_v2`.
* `ai_insight.citations JSONB NULL` — typed list `[{citation_id, kind}]`.

The two FKs are bidirectional and both nullable, which means insight-first
and chart-first orderings are both representable. Round 3 walks the
opposite edge from Round 2:

```
              build_chart writes this edge
ai_insight.id ---------------- agent_chart.insight_id        (Round 3)
ai_insight.chart_id ---------- agent_chart.id                (was Round 2)
              persist_insight_v2 binds this edge later -> NOT bound in Round 3 unless we choose to
```

In Round 3 the `ai_insight.chart_id` column **may stay NULL** for the
duration of the session. The frontend's `/api/insights/latest` route
joins via `agent_chart.insight_id`, not via `ai_insight.chart_id`, so
this is not a UX break. (See §SSE Ordering Analysis for the rationale,
and §Risks for the suggested follow-up to symmetrically populate
`ai_insight.chart_id` in `build_chart`.)

---

## API Contracts

### `persist_insight_v2` (registry / MCP)

```diff
 async def persist_insight_v2(
     *,
     headline: str,
     body: str | None,
     confidence: str,
     materiality: str,
-    chart_id: str,
+    chart_id: str | None = None,
     citations: list[Any],
     open_question_id: str | None = None,
     skills_run: list[str] | None = None,
     ctx: SkillContext | None = None,
     db: Any,
     session_id: uuid.UUID | str | None = None,
     idx: int | None = None,
 ) -> dict[str, Any]:
```

Return shape **unchanged**:

```json
{"ok": true, "insight_id": "<uuid>", "chart_id": "<id|null>", "citation_count": <int>, "version": "v2"}
```

When `chart_id` is None, the response carries `"chart_id": null`. Callers
already tolerate `chart_id: str | None` because the v1 schema declared the
column nullable.

### `build_chart` (registry / MCP)

```diff
 async def build_chart(
     sql: str,
     encoding: dict[str, Any],
     chart_type: str,
     title: str,
     subtitle: str | None = None,
     *,
+    insight_id: str | None = None,
     annotations: list[dict[str, Any]] | None = None,
     styling: dict[str, Any] | None = None,
     ctx: SkillContext | None = None,
     db: Any = None,
 ) -> dict[str, Any]:
```

New error codes returned by `build_chart`:

| Code | Meaning |
|---|---|
| `insight_not_found` | `insight_id` did not resolve in `ai_insight`. |
| `insight_session_mismatch` | `ai_insight.session_id` does not match `ctx.session_id`. |

Return shape (success) is unchanged:

```json
{"ok": true, "chart_id": "<id>", "chart_spec": {...}, "row_count": N, "truncated": bool, "executed_sql": "..."}
```

---

## Tech Stack Decisions

No stack changes. The reorder is a control-flow refactor over the
existing FastAPI / FastMCP / SQLAlchemy async / Llama-Stack agent loop.
The migration is already in place (018). No new dependencies. No
schema deltas.

---

## Per-File Diff Specs

These are exact, additive specifications. The implementing engineer
writes the code; this document fixes the contract.

### 1. `backend/agents/insights/tools/persist_insight_v2.py`

Two related edits inside one function.

**Edit A — signature.**

```diff
-    chart_id: str,
+    chart_id: str | None = None,
```

**Edit B — drop the chart-required guard and skip chart resolution
when `chart_id` is None or empty.** Currently lines 207-208 + 232-236:

```diff
-    if not chart_id or not isinstance(chart_id, str):
-        return _err("chart_id_required", "v2 insights must reference a built chart")
+    # chart_id is now optional. When provided, validate; when absent,
+    # the chart will arrive in a follow-up build_chart(insight_id=...).
+    chart_id_present = isinstance(chart_id, str) and bool(chart_id)
```

```diff
-    chart_row, chart_err = await _resolve_chart(db, chart_id, sid)
-    if chart_err is not None:
-        return _err(chart_err, f"chart guard failed: {chart_err}", chart_id=chart_id)
+    if chart_id_present:
+        chart_row, chart_err = await _resolve_chart(db, chart_id, sid)
+        if chart_err is not None:
+            return _err(chart_err, f"chart guard failed: {chart_err}", chart_id=chart_id)
+    else:
+        chart_row = None
```

**Edit C — guard the optional chart-bind UPDATE block (lines 298-310)
on `chart_id_present`.** When `chart_id` is None, skip the
`UPDATE agent_chart SET insight_id = ...` block; there is no chart row
to patch. This block is already inside a `try / except` that warns on
failure — make the outer condition the same `chart_id_present` flag.

**Edit D — return shape unchanged.** Continue returning the chart_id
field; when absent, set it to `None`:

```diff
     return {
         "ok": True,
         "insight_id": str(insight_id_uuid),
-        "chart_id": chart_id,
+        "chart_id": chart_id if chart_id_present else None,
         "citation_count": len(cit_rows),
         "version": "v2",
     }
```

**ai_insight.chart_id** column write at line 281 (`setattr(insight, "chart_id", chart_id)`) — when `chart_id` is None this writes `None`, which is the correct NULL semantics. No change required there.

### 2. `backend/agents/insights/tools/build_chart.py`

Three additive edits.

**Edit A — signature.**

```diff
 async def build_chart(
     sql: str,
     encoding: dict[str, Any],
     chart_type: str,
     title: str,
     subtitle: str | None = None,
     *,
+    insight_id: str | None = None,
     annotations: list[dict[str, Any]] | None = None,
     styling: dict[str, Any] | None = None,
     ctx: SkillContext | None = None,
     db: Any = None,
 ) -> dict[str, Any]:
```

**Edit B — resolve & validate `insight_id` immediately after argument
guards (line ~382), before the encoding shape pass.** New helper +
caller block:

```python
async def _resolve_insight(
    db: Any, insight_id: str, session_id: uuid.UUID
) -> tuple[Any | None, str | None]:
    """Return (insight_row, error_code). Mirrors _resolve_chart shape."""
    if db is None:
        # No db handle means we cannot look up the insight; surface as
        # a hard error so the agent retries with the insight_id elided
        # (current chart-with-NULL fk behaviour).
        return None, "insight_not_found"
    from ..db.models import AIInsight
    try:
        iid = uuid.UUID(str(insight_id))
    except Exception:
        return None, "insight_not_found"
    result = await db.execute(select(AIInsight).where(AIInsight.id == iid))
    row = result.scalars().first() if hasattr(result, "scalars") else None
    if row is None and hasattr(result, "first"):
        row = result.first()
    if row is None:
        return None, "insight_not_found"
    if _coerce_uuid(row.session_id) != session_id:
        return None, "insight_session_mismatch"
    return row, None
```

(Reuse the `_coerce_uuid` helper that already lives in
`persist_insight_v2.py`; either import it or copy the 5-line block —
both are fine, copying preserves module independence.)

The caller block sits at the entry of `build_chart` after the
`title`/`subtitle` length guards:

```python
insight_id_present = isinstance(insight_id, str) and bool(insight_id)
resolved_insight_uuid: uuid.UUID | None = None
if insight_id_present:
    sid_for_check = ctx.session_id if ctx is not None else None
    sid_uuid = _coerce_uuid(sid_for_check)
    if sid_uuid is None:
        return _err("session_id_required", "build_chart with insight_id requires ctx.session_id")
    insight_row, insight_err = await _resolve_insight(db, insight_id, sid_uuid)
    if insight_err is not None:
        return _err(insight_err, f"insight guard failed: {insight_err}", insight_id=insight_id)
    resolved_insight_uuid = _coerce_uuid(getattr(insight_row, "id", None))
```

**Edit C — pass the resolved UUID into `_persist_chart_row` instead of
the hardcoded `None`.** Today line 327 reads `insight_id=None`; new:

```python
async def _persist_chart_row(
    chart: ChartSpec,
    session_id: uuid.UUID | str,
    db: Any,
    insight_id: uuid.UUID | None = None,   # NEW kwarg
) -> None:
    ...
        row = AgentChart(
            id=chart.chart_id,
            session_id=sid,
-           insight_id=None,
+           insight_id=insight_id,
            spec=chart.model_dump(mode="json"),
            ...
        )
```

And the call site at line 494:

```diff
-    await _persist_chart_row(spec, session_id, db)
+    await _persist_chart_row(spec, session_id, db, insight_id=resolved_insight_uuid)
```

When `insight_id_present` is False the resolved UUID stays None and
`_persist_chart_row` writes a NULL fk — this preserves Round 2's
behaviour bit-for-bit for the legacy chart-first callsite (none in
production after Round 3, but the unit tests exercise it).

### 3. `backend/agents/insights/tools/registry.py`

Two surgical edits inside `dispatch()`.

**Edit A — `build_chart` branch (line 522-533).** Forward `insight_id`:

```diff
     if name == "build_chart":
         return await fn(
             sql=args_dict.get("sql", ""),
             encoding=args_dict.get("encoding") or {},
             chart_type=args_dict.get("chart_type", ""),
             title=args_dict.get("title", ""),
             subtitle=args_dict.get("subtitle"),
+            insight_id=args_dict.get("insight_id"),
             annotations=args_dict.get("annotations"),
             styling=args_dict.get("styling"),
             ctx=ctx if accepts_ctx else None,
             db=db,
         )
```

**Edit B — `persist_insight_v2` branch (line 535-547).** No code
change needed; `args_dict.get("chart_id", "")` already returns `""`
when the agent omits the field, and `persist_insight_v2` will treat
empty-string the same as None per Edit B above. The implementing
engineer must **verify** this by reading the new
`chart_id_present = isinstance(chart_id, str) and bool(chart_id)`
condition: `bool("") is False`, so the chart-resolution branch is
skipped. This is the right semantics; document it and add a unit
test (see §Test Strategy).

### 4. `backend/mcp_server.py`

Two additive edits in the FastMCP wrappers.

**Edit A — `build_chart` wrapper (lines 776-818).** Add `insight_id` in
the function signature and the forwarded dict:

```diff
 @mcp.tool()
 async def build_chart(
     insight_id: str,
     sql: str,
     encoding: dict[str, Any],
     chart_type: str = "",
     title: str = "",
     subtitle: Optional[str] = None,
     annotations: Optional[list[dict[str, Any]]] = None,
     styling: Optional[dict[str, Any]] = None,
     thread_id: Optional[str] = None,
     session_id: Optional[str] = None,
 ) -> dict[str, Any]:
     ...
     return await _invoke(
         "build_chart",
         insight_id,
         {
+            "insight_id": insight_id,
             "sql": sql,
             "encoding": encoding,
             ...
         },
         ...
     )
```

Note the existing signature already takes `insight_id` as the FastMCP
positional arg — but it is currently swallowed by `_invoke`'s second
positional (which the implementation uses as a hint, not as a tool
arg). The fix is to **also** put it inside the args dict so
`registry.py`'s dispatcher can read it via `args_dict.get("insight_id")`.

**Edit B — `persist_insight_v2` wrapper (lines 821-864).** Make
`chart_id` optional:

```diff
 @mcp.tool()
 async def persist_insight_v2(
     insight_id: str,
     headline: str,
-    chart_id: str,
+    chart_id: Optional[str] = None,
     citations: list[dict[str, Any]],
     ...
 ) -> dict[str, Any]:
```

Python forbids a positional non-default arg after a default arg — so
`citations` (which the existing wrapper requires positional) must
either move before `chart_id` or also gain a default. Recommended:
move `chart_id` to the keyword-only block by inserting `*,` before it,
and let `citations` stay as a required positional. The forwarded dict
remains unchanged; `_invoke` already passes `chart_id` through.

### 5. `backend/agents/insights/prompts/synthesis_rules_v2.md`

Full Workflow section rewrite. The Round 2 prompt's invariants stay
(numbered, imperative, forbid v1 names, hard rule against
intermediate calls between the chart and persist steps), but the
sequence inverts.

```markdown
## Workflow (follow in order)

1. Orient: call `read_workspace(file="SCHEMA.md")` then
   `read_workspace(file="FRESHNESS.md")`. Once per session.
2. Drill: `query_database` and/or `search_documents` to test one
   hypothesis. Optional `web_search` for one corroborating source;
   each external claim closes with `emit_citation`.
3. PERSIST FIRST: call
   `persist_insight_v2(headline="...", citations=[...],
   confidence="med", materiality="med")` WITHOUT `chart_id`.
   Capture the returned `insight_id`.
4. CHART: your VERY NEXT tool call after `persist_insight_v2`
   succeeds MUST be
   `build_chart(insight_id="<the insight_id from step 3>",
   sql="...", encoding={...}, chart_type="...", title="...")`.
   Do NOT call `persist_insight_v2` again before charting.
   Do NOT call any other tool between `persist_insight_v2` and
   `build_chart`.
5. Repeat steps 2-4 for the next hypothesis until you reach
   `max_insights` or evidence is exhausted, then call
   `finalize_session`.

`update_memory` is OPTIONAL and only allowed AFTER a successful
`build_chart`. Never substitute it for charting.
```

The "Hard Rules" / "OCI Lens" / "Chart Palette" / "Budget" /
"Analytical Method" sections stay byte-identical — they speak about
the *content* contract, which Round 3 does not touch. The forbidden-v1
list (`persist_insight`, `emit_chart`, `get_chart_data`) and the
"every insight MUST reference exactly one `chart_id`" guarantee are
unchanged; the chart simply binds to the insight one tool call later
in the loop.

The 4 KiB ceiling enforced by `test_agentic_synthesis_v2.py` is
respected; this rewrite is shorter than Round 2's by ~80 bytes.

---

## SSE Ordering Analysis

The SSE translator at `backend/openclaw/sse_translator.py:580-740`
emits two event families based on `pending.name`:

| Tool name match | Started event | Completed event | Side-effect on accumulator |
|---|---|---|---|
| `pending.name in _PERSIST_TOOL_NAMES` | `InsightStartedEvent` (line 608) | `InsightCompleteEvent` (line 675) | `total_insights_persisted += 1` (line 700) |
| `pending.name == "finalize_session"` | (generic ToolCallStarted) | `SessionCompleteEvent` (line 701-722) | `finalize_seen = True` |
| anything else (incl. `build_chart`) | `ToolCallStartedEvent` | `ToolCallCompleteEvent` | none |

`_PERSIST_TOOL_NAMES = frozenset({"persist_insight", "persist_insight_v2"})`
(Round 1 P2 fix).

### What changes ordering-wise under Round 3

In Round 2 (chart-first) the per-insight emit sequence is:

```
ToolCallStarted(build_chart) -> ToolCallComplete(build_chart)
  -> InsightStarted(persist_insight_v2) -> InsightComplete(persist_insight_v2)
```

Under Round 3 (insight-first) it becomes:

```
InsightStarted(persist_insight_v2) -> InsightComplete(persist_insight_v2)
  -> ToolCallStarted(build_chart) -> ToolCallComplete(build_chart)
```

The two `InsightStarted/InsightComplete` events now fire **before** the
`ToolCallStarted/ToolCallComplete` pair for `build_chart`.

### Why no translator change is required

1. **Frontend reads insights from `/api/insights/latest`, not from SSE
   tile state.** Round 1+2 docs (§Acceptance criteria (f)) confirm
   `/api/insights/latest` is the source of truth for the rendered
   tiles. That endpoint is a server-side SQL join against
   `ai_insight LEFT JOIN agent_chart ON agent_chart.insight_id = ai_insight.id`.
   The chart appears in the response on the next poll *after*
   `build_chart` commits — independent of SSE event ordering.
2. **The chart binds to the insight at MCP-commit time, inside
   `_invoke()` for `build_chart`.** Round 1 P4's commit fix means
   `build_chart`'s INSERT with `insight_id = <uuid>` is durable when
   `_invoke()` returns. Subsequent SELECT by the route sees it.
3. **`InsightCompleteEvent` does not promise a chart is bound at
   emit time.** It carries headline + confidence + materiality only
   (lines 685-697). It never carried a `chart_id` field. So the
   frontend cannot have been depending on the chart being persisted
   *before* the InsightComplete frame.
4. **`SessionCompleteEvent.insights_emitted` increments on
   persist_insight_v2, not on build_chart.** The terminal counter is
   chart-agnostic.
5. **Round 1 P2 already generalised the persist-name check to a
   frozenset.** The set still contains `persist_insight_v2`; Round 3
   does not change which tool fires the InsightStarted/Complete
   pair, only when in the loop it fires.

**Verdict: SSE translator stays byte-identical.**

The implementing engineer must still add a regression test that the
new ordering does not produce a duplicate `InsightStarted` for the
same `insight_id` (the `pending.started_emitted` flag protects this
already, but Round 3 is the first time the persist call runs without
a preceding build_chart in the same turn — verify).

---

## Failure Modes

| # | Scenario | What the agent sees | What lands in DB | Recovery |
|---|---|---|---|---|
| 1 | persist OK + chart OK | `{ok: true, insight_id}` then `{ok: true, chart_id}` | `ai_insight` row with `chart_id NULL`; `agent_chart` row with `insight_id = <uuid>`. `/api/insights/latest` join surfaces the bound pair. | n/a — happy path |
| 2 | persist OK + chart fails (sql_gate / encoding / query error) | `{ok: true, insight_id}` then `{ok: false, error: "sql_gate_rejected"\|"encoding_field_missing"\|...}` | `ai_insight` row with `chart_id NULL`. No `agent_chart` row. | **Graceful degradation:** the insight is shipped without a chart. Frontend tile renders headline + citations and shows a "chart unavailable" placeholder. The agent MAY retry `build_chart(insight_id=<same uuid>)` with a corrected payload; succeeds idempotently if it does. |
| 3 | persist OK + `build_chart(insight_id=..., session_X)` but ctx.session is Y | `{ok: false, error: "insight_session_mismatch"}` | `ai_insight` row with `chart_id NULL`. No `agent_chart` row. | Agent treats this as a hard reject; should not retry with the same insight_id from a different session. In practice this only triggers if the agent fabricates an insight_id, since the orchestrator pins ctx.session_id per turn. |
| 4 | persist OK + `build_chart(insight_id="<bad uuid>")` | `{ok: false, error: "insight_not_found"}` | `ai_insight` row with `chart_id NULL`. No `agent_chart` row. | Agent treats as hard reject; the insight is still shipped. Same UX as case 2. |
| 5 | persist fails (citation_unresolved / session_closed / headline_too_long / etc.) | `{ok: false, error: "<code>", message, detail}` | Nothing. | Agent gets no `insight_id` to forward. Must retry `persist_insight_v2` after correcting the error. The Round 2 prompt's "PERSIST IMMEDIATELY" imperative still applies; the prompt must explicitly say "if persist fails, fix the input and retry persist before attempting any other tool". |
| 6 | persist OK + agent forgets to call `build_chart` (loop ends or budget hits) | `{ok: true, insight_id}` from persist, no follow-up. | `ai_insight` row with `chart_id NULL`. | Force-finalise path detects `version='v2' AND chart_id IS NULL AND db_count >= 1` and logs a new WARNING `ai_insights.v2_agent_skipped_chart` (mirror of Round 2's `v2_agent_skipped_persist`). Insight is shipped chartless. UX equivalent to case 2. |
| 7 | persist OK + chart OK + the bind UPDATE on `ai_insight.chart_id` fails | (depends on whether this round populates that edge) | `ai_insight` row with `chart_id NULL` (if Round 3 leaves this column unwritten by build_chart) | See §Risks — Round 3 deliberately does **not** populate `ai_insight.chart_id` from `build_chart`. F-Round3-1 proposes a follow-up to do so for symmetry. The frontend join uses the other edge so case 7 cannot present today. |

---

## Test Strategy Outline

To be expanded by QA in a separate test plan; this is the irreducible
core.

### New regression tests

* **`test_persist_insight_v2_optional_chart_id_persists_without_chart`**
  — Drives `persist_insight_v2(chart_id=None, ...)` against a fake DB.
  Asserts `{ok: true, chart_id: None}`, asserts an `ai_insight` row
  with `chart_id IS NULL`, asserts no `_resolve_chart` SELECT was
  issued (use a query-counting fake or spy).
* **`test_persist_insight_v2_optional_chart_id_persists_without_chart_when_empty_string`**
  — Same as above but `chart_id=""`. Guards the
  `chart_id_present = bool(chart_id)` semantics.
* **`test_build_chart_with_insight_id_binds_fk_when_session_matches`**
  — Seed an `ai_insight` row with `session_id = S`. Call
  `build_chart(insight_id=<that uuid>, ctx=SkillContext(session_id=S), ...)`
  with valid SQL/encoding. Assert the resulting `agent_chart` row has
  `insight_id = <that uuid>`.
* **`test_build_chart_rejects_insight_id_for_other_session`** — Seed
  insight with `session_id = S1`. Call `build_chart` with `ctx.session_id = S2`.
  Assert `{ok: false, error: "insight_session_mismatch"}`. Assert no
  `agent_chart` row was inserted.
* **`test_build_chart_rejects_unknown_insight_id`** — Call with a
  random UUID that does not resolve. Assert
  `{ok: false, error: "insight_not_found"}`.
* **`test_build_chart_with_no_insight_id_writes_null_fk`** — Confirms
  back-compat: `insight_id=None` produces an `agent_chart` row with
  `insight_id IS NULL`, identical to Round 2 behaviour. Pin against
  any future drift.
* **`test_v2_session_end_to_end_round3_ordering`** — End-to-end with
  the existing OpenClaw-mocked harness. Canned tool stream is now
  `read_workspace -> query_database -> persist_insight_v2 -> build_chart -> ... -> finalize_session`.
  Assert SSE event order: `InsightStarted -> InsightComplete -> ToolCallStarted(build_chart) -> ToolCallComplete(build_chart)`.
  Assert one `ai_insight` row per intended insight, all with `version='v2'`,
  with the bound `agent_chart.insight_id` join populated.

### Existing tests requiring updates

* **`test_persist_insight_v2.py` (`backend/tests/test_persist_insight_v2.py`)** — every
  case that asserts `{ok: false, error: "chart_id_required"}` for
  empty `chart_id`. Rewrite those to assert success with `chart_id: None`,
  or move them under a new "chart_id was provided but invalid"
  banner.
* **`test_phase_d_router_cutover.py`** — the canned v2 stream may
  hardcode the old order. Update the fixture stream and the assertion
  on event ordering.
* **`test_v2_insights_e2e_regression.py`** —
  `test_v2_session_end_to_end_with_mocked_openclaw` similarly. Round
  3 splits this into "old order still works" (kept as a
  backwards-compat smoke test) and "new order is the recommended
  path".
* **`test_agentic_synthesis_v2.py`** — the synthesis_rules_v2.md
  round-trip equality assertion will need its expected text updated to
  the new Workflow.
* **`test_mcp_server.py`** — the build_chart wrapper call signature
  test (if any) needs the new optional `insight_id` field; the
  persist_insight_v2 wrapper test similarly accepts `chart_id=None`.

---

## ADRs (key decisions)

### ADR-R3-01: Persist before chart

**Status:** Accepted (this round).

**Context:** Round 2 confirmed empirically that the LLM drops the
trailing `persist_insight_v2` call after a successful `build_chart` in
~30% of v2 sessions even with imperative numbered prompts. The
chart-first ordering forces the agent to thread a `chart_id` token
across two tool turns; the persist call is structurally fragile.

**Decision:** Reverse the order. `persist_insight_v2` runs first with
no `chart_id`. `build_chart` runs second with the returned
`insight_id`. The first durable write of every insight is now the
insight itself.

**Consequences:**

* **Positive:** The agent's contract collapses to "persist, optionally
  chart". An insight without a chart still ships; this is the
  graceful-degradation property Round 1+2 lacked.
* **Positive:** The most common Round 1+2 failure mode (chart row
  succeeds, insight row never lands) becomes structurally impossible
  — the insight is the first row written.
* **Positive:** The chart is bound to the insight in the same
  transaction that creates the chart row (single-INSERT FK), removing
  Round 1 P4's cross-connection invisible-row class entirely.
* **Negative:** New failure mode: persist OK + chart fails leaves a
  chartless insight visible in `/api/insights/latest`. Mitigated by
  rendering "chart unavailable" rather than hiding the tile, which
  matches Round 1's degraded-session UX.
* **Neutral:** SSE event ordering changes but no consumer is
  order-coupled (see §SSE Ordering Analysis).

### ADR-R3-02: `agent_chart.insight_id` is the binding edge; `ai_insight.chart_id` may stay NULL

**Status:** Accepted with follow-up F-Round3-1 to revisit.

**Context:** Migration 018 added both edges. Round 2 wrote both
(`build_chart` set NULL, `persist_insight_v2` patched both
`agent_chart.insight_id` and `ai_insight.chart_id`). Round 3 only
naturally populates one (`agent_chart.insight_id`, written at
chart-INSERT time).

**Decision:** Leave `ai_insight.chart_id` NULL in the Round 3 hot
path. The frontend's `/api/insights/latest` route already joins on
`agent_chart.insight_id = ai_insight.id`, so the bound pair surfaces
correctly. F-Round3-1 proposes a symmetric UPDATE inside `build_chart`
to populate both edges; defer until we see if any consumer
materialises the `ai_insight.chart_id` column directly.

**Consequences:**

* **Positive:** Single INSERT in `build_chart`, no second UPDATE.
* **Negative:** Asymmetric graph: querying "what chart belongs to
  this insight?" via `ai_insight.chart_id` returns NULL. Any code
  path doing this must switch to the
  `agent_chart WHERE insight_id = :iid` lookup. Verify with
  `rg "ai_insight\\.chart_id" backend/` before merging.

### ADR-R3-03: SSE translator stays byte-identical

**Status:** Accepted (this round).

**Context:** The translator's persist-name check fires on
`persist_insight_v2`. Round 3 does not change that tool name nor add
new ones; it only changes when in the per-insight micro-loop the
persist call lands.

**Decision:** No edits to `sse_translator.py`. Document the new
ordering in this file and add an end-to-end test (above) that pins
it.

**Consequences:** Zero translator drift between Round 2 and Round 3
runs, simplifying any incident triage that compares SSE traces across
rounds.

---

## Risks & Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| **R1.** Migration 018 must already be applied in every environment we run against. If `agent_chart.insight_id` is still NOT NULL, every `build_chart` call without `insight_id` will INSERT-fail. | High | Pre-deploy SQL inspection step. The deploy runbook for Round 3 must include `\d agent_chart` in psql and confirm `insight_id | uuid |` (no `not null`). For SQLite test environments the migration no-ops the alter and the model-layer column already permits NULL — verified in `018_ai_insights_v2_columns.py:54-67`. |
| **R2.** `ai_insight.chart_id` stays NULL on the Round 3 path; any consumer that joined on it instead of `agent_chart.insight_id` regresses. | Med | Pre-merge `rg "ai_insight\\.chart_id" backend/ frontend/` and audit each hit. Prior surveys (Round 1 §f) confirm `/api/insights/latest` uses the other edge; the surveying engineer should re-run the same grep on the current main. |
| **R3.** Legacy chart-first call sites (any place that calls `persist_insight_v2` *with* a `chart_id`) might break if we tighten the optional. | Low | Round 3 keeps `chart_id` accepted-when-provided. The chart-resolution branch still runs for non-empty values; it is only skipped on None/empty. The only known production call site is the agentic loop itself (driven by the prompt). The MCP wrapper now defaults to None; existing callers that pass `chart_id` continue to work. |
| **R4.** The agent may get confused by two different forward-reference patterns in the prompt (Round 2 had chart_id forward; Round 3 has insight_id forward) and call build_chart twice. | Med | Prompt rewrite (§5) keeps the strict "your VERY NEXT tool call" imperative. Add Round 2's `R2-C` symmetric diagnostic for the new failure (case 6 in §Failure Modes) — `ai_insights.v2_agent_skipped_chart` WARNING in `_force_finalize_degraded`. Mirror the existing `v2_agent_skipped_persist` shape. |
| **R5.** Tests written against Round 2 ordering will fail. | Low (mechanical) | §Test Strategy explicitly enumerates the impacted tests. Update is an afternoon; no algorithmic test changes. |
| **R6.** `persist_insight_v2` now returns `chart_id: null` when called without one. Frontend / `/api/insights/latest` consumers must tolerate null in this field. | Low | The `ai_insight.chart_id` column has been NULLABLE since migration 018; the route's response model has tolerated NULL since Phase B. Spot-check `routers/insights.py` once before merge. |
| **R7.** SSE InsightStartedEvent now fires *before* the agent has built the chart, so users see the tile pop in slightly earlier than today. | Cosmetic | Acceptable. The headline + citations appear immediately; the chart slot fills on the next `/api/insights/latest` poll once `build_chart` completes — same render path as Round 1+2 already uses. |
| **R8.** Round 3 implements ADR-R3-02's asymmetric-binding choice. Querying patterns in any new analytics dashboard that does not exist yet might assume both edges populated. | Low | Documented in ADR-R3-02; F-Round3-1 follow-up exists. |

---

## Pre-implementation Checklist (handed to the engineer)

1. `\d agent_chart` against the prod-shaped DB — confirm
   `insight_id` is NULLABLE (migration 018 applied).
2. `\d ai_insight` — confirm `chart_id`, `citations`,
   `open_question_id`, `version` columns exist (migration 018).
3. `rg "ai_insight\\.chart_id" backend/ frontend/` — audit consumers
   of the column that Round 3 leaves NULL on the hot path.
4. `rg "chart_id_required" backend/tests/` — enumerate tests that
   will need their assertion flipped.
5. `rg "persist_insight_v2\\(" backend/` — confirm the only callsites
   are the registry dispatcher, the MCP wrapper, and the v2
   regression tests; no business logic is mid-flight.
6. Run the full backend suite at HEAD and capture the baseline pass
   count to compare against post-merge.

---

## Files Touched (planned)

```
backend/agents/insights/tools/persist_insight_v2.py        (signature + 2 guard edits + return)
backend/agents/insights/tools/build_chart.py               (new param + new helper + persist call)
backend/agents/insights/tools/registry.py                  (1 dispatch line for build_chart insight_id)
backend/mcp_server.py                                      (2 wrapper signatures + 1 dict forward)
backend/agents/insights/prompts/synthesis_rules_v2.md      (Workflow rewrite, swap order, ~80 bytes shorter)
backend/agents/insights/agentic_synthesis.py               (NEW WARNING `v2_agent_skipped_chart` mirroring R2-C)

backend/tests/test_persist_insight_v2.py                   (chart_id-required cases removed/inverted)
backend/tests/test_build_chart_tool.py                     (new insight_id branch tests)
backend/tests/test_phase_d_router_cutover.py               (new ordering)
backend/tests/test_v2_insights_e2e_regression.py           (Round 3 e2e + retain Round 2 smoke)
backend/tests/test_agentic_synthesis_v2.py                 (prompt round-trip text update)
```

No frontend changes. No DDL. No new dependencies. v1 path untouched.

---

## Open Questions for Round 3 implementation

1. **Should `build_chart` also UPDATE `ai_insight.chart_id` for graph
   symmetry?** ADR-R3-02 defers; F-Round3-1 owns it.
2. **Should the prompt allow the agent to ship an insight without ever
   attempting a chart?** Today step 4 is mandatory after step 3.
   Round 3 makes chartless insights structurally legal at the DB
   layer; the prompt should still mandate the attempt for UX
   consistency, but explicitly allow proceeding to the next insight
   if chart fails twice. Out of scope for this doc.
3. **Should `persist_insight_v2` accept a `chart_spec` object inline
   for one-shot insights?** Would collapse the two calls back into
   one; rejected here because it bloats `persist_insight_v2`'s
   surface and re-introduces the chart-validation failure modes that
   `build_chart` was carved out to isolate. Park.
