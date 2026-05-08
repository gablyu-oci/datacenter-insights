# AI Insights v2 — Phase D, V2 Path Fix Plan

Status: PLAN ONLY (no code edits performed). The backend engineer agent
will execute these steps in order. The post-mortem / root cause document
(`ai_insights_v2_phase_d_v2_path_fix.md`) will be authored AFTER the work
lands.

Hard constraints (carry-forward from the user, non-negotiable):

- v1 demo path keeps working unchanged. Soak through 2026-05-21.
- `routers/insights.py CreateSessionBody.version` default stays `"v1"`.
- v1 tools (`persist_insight`, `emit_chart`, `get_chart_data`) and their
  `mcp_server.py` wrappers are NOT removed or renamed.
- All edits are additive or low-risk modifications.
- No frontend changes unless `build_chart`'s spec genuinely demands one
  (it does not in this plan).

---

## 1. Fix sequence (ordered)

The backend engineer SHOULD execute steps in this order. Each step is
self-contained and independently testable; running steps out of order
will leave the v2 path partially wired.

### Step 1 — Forward `version` from orchestrator to driver  (P1)

File: `backend/agents/insights/orchestrator.py`
Function: `Orchestrator._run_synthesis_inner._driver` (approx. lines
374-401, the `await run_agentic_synthesis(...)` call site at lines
382-390).

BEFORE (lines 382-390):

```python
await run_agentic_synthesis(
    session_id=self.session_id,
    fact_pack=self._fact_pack,
    max_insights=self.max_insights,
    db=self.db,
    sse_emit=_sse_emit,
    cron_run_date=cron_run_date,
    mode="manual",
)
```

AFTER:

```python
await run_agentic_synthesis(
    session_id=self.session_id,
    fact_pack=self._fact_pack,
    max_insights=self.max_insights,
    db=self.db,
    sse_emit=_sse_emit,
    cron_run_date=cron_run_date,
    mode="manual",
    version=self.version,
)
```

Rationale: `self.version` is already populated from the HTTP body and
the `ai_session.version` row (orchestrator.py:248,255). Without this
kwarg, `run_agentic_synthesis` falls back to its `version="v1"` default
(`agentic_synthesis.py:100`) and instructs the agent to call v1 tools.
This is the single largest cause of the user-visible failure.

V1 risk: NONE. v1 sessions arrive with `self.version == "v1"`, and the
driver default is also `"v1"`; the kwarg is now explicit but
behaviour-equivalent.

### Step 2 — Recognise v2 tool names in the SSE translator  (P2)

File: `backend/openclaw/sse_translator.py`
Function: `translate_synthesis_chunk` (approx. lines 486-735); branches
in scope: `started` emission (599-633), `completed` emission (666-735).

Add module-level constants near the top of the module (alongside the
existing imports / dataclass section, around line 65):

```python
# v2 persistence-class tools — agent emits these instead of
# `persist_insight` when ai_session.version == "v2". The translator
# treats them as semantically equivalent to `persist_insight` for the
# purposes of `total_insights_persisted` and InsightStarted/Complete
# event emission.
_V2_PERSIST_TOOL_NAMES = frozenset({"persist_insight_v2"})
_PERSIST_TOOL_NAMES = frozenset({"persist_insight"}) | _V2_PERSIST_TOOL_NAMES
```

(Optional, deferred unless tests demand: `_V2_AUX_TOOL_NAMES =
frozenset({"build_chart", "search_documents", "read_workspace"})`. These
remain in the generic `else` branch — they emit
`ToolCallStarted/Complete` events as today, which is correct for
tools that are NOT insight-class.)

#### 2a. Started branch (lines 599-633)

BEFORE (line 599 head):

```python
if pending.name == "persist_insight":
```

AFTER:

```python
if pending.name in _PERSIST_TOOL_NAMES:
```

Inside the same branch (lines 602-607), the headline-draft extraction
already calls `parsed_args.get("headline") or
parsed_args.get("insight", {}).get(...)`. `persist_insight_v2`'s
canonical schema has `headline` at the top level (see
`persist_insight_v2.py:158-189`), so the existing `parsed_args.get(
"headline")` works as-is. No further edits inside this block.

#### 2b. Completed branch (lines 666-691)

BEFORE (line 666 head):

```python
if pending.name == "persist_insight":
```

AFTER:

```python
if pending.name in _PERSIST_TOOL_NAMES:
```

The body unconditionally bumps `acc.current_insight_idx` and
`acc.total_insights_persisted` — leave it untouched.

#### 2c. Finalize branch (lines 692-713)

No change required: `finalize_session` is the same tool name for both
versions. Confirm by inspection that `_V2_PERSIST_TOOL_NAMES` does NOT
contain `finalize_session` (it does not).

V1 risk: NONE for v1 sessions (the v1 tool name `persist_insight` is in
the new set; behaviour is identical). LOW for v2: a new tool name now
contributes to `total_insights_persisted`. This is the desired
behaviour and is exercised by the new accumulator unit test (see §8).

### Step 3 — Thread `db` through dispatch from `_invoke`  (P3 + C4)

This step has two coupled edits in two files. Apply both atomically.

#### 3a. `dispatch()` accepts an optional `db`

File: `backend/agents/insights/tools/registry.py`
Function: `dispatch` (lines 438-543).

BEFORE (lines 438-444):

```python
async def dispatch(
    name: str,
    args: dict[str, Any],
    ctx: SkillContext | None = None,
) -> Any:
    """Run the dispatcher for the named tool with the provided args."""
    fn = _DISPATCH.get(name)
```

AFTER:

```python
async def dispatch(
    name: str,
    args: dict[str, Any],
    ctx: SkillContext | None = None,
    *,
    db: Any | None = None,
) -> Any:
    """Run the dispatcher for the named tool with the provided args.

    `db` is forwarded only to v2 tools that need write-capable
    persistence (build_chart, persist_insight_v2). v1 tools receive
    their data via ctx and ignore this parameter.
    """
    fn = _DISPATCH.get(name)
```

Then, ONLY in the two v2 dispatch wrappers, replace the hardcoded
`db=None`.

BEFORE (lines 515-525, `build_chart` wrapper):

```python
if name == "build_chart":
    return await fn(
        sql=args_dict.get("sql", ""),
        encoding=args_dict.get("encoding") or {},
        chart_type=args_dict.get("chart_type", ""),
        title=args_dict.get("title", ""),
        subtitle=args_dict.get("subtitle"),
        annotations=args_dict.get("annotations"),
        styling=args_dict.get("styling"),
        ctx=ctx if accepts_ctx else None,
    )
```

AFTER:

```python
if name == "build_chart":
    return await fn(
        sql=args_dict.get("sql", ""),
        encoding=args_dict.get("encoding") or {},
        chart_type=args_dict.get("chart_type", ""),
        title=args_dict.get("title", ""),
        subtitle=args_dict.get("subtitle"),
        annotations=args_dict.get("annotations"),
        styling=args_dict.get("styling"),
        ctx=ctx if accepts_ctx else None,
        db=db,
    )
```

BEFORE (lines 527-539, `persist_insight_v2` wrapper):

```python
if name == "persist_insight_v2":
    return await fn(
        headline=args_dict.get("headline", ""),
        body=args_dict.get("body"),
        confidence=args_dict.get("confidence", "med"),
        materiality=args_dict.get("materiality", "med"),
        chart_id=args_dict.get("chart_id", ""),
        citations=args_dict.get("citations") or [],
        open_question_id=args_dict.get("open_question_id"),
        skills_run=args_dict.get("skills_run"),
        ctx=ctx if accepts_ctx else None,
        db=None,  # populated by the orchestrator-bound dispatcher in agentic loop
    )
```

AFTER:

```python
if name == "persist_insight_v2":
    return await fn(
        headline=args_dict.get("headline", ""),
        body=args_dict.get("body"),
        confidence=args_dict.get("confidence", "med"),
        materiality=args_dict.get("materiality", "med"),
        chart_id=args_dict.get("chart_id", ""),
        citations=args_dict.get("citations") or [],
        open_question_id=args_dict.get("open_question_id"),
        skills_run=args_dict.get("skills_run"),
        ctx=ctx if accepts_ctx else None,
        db=db,
    )
```

All other dispatch branches (lines 454-513, 541-542) are untouched and
ignore the new `db` kwarg, since they don't read it.

#### 3b. `_invoke` forwards its existing `db` to dispatch

File: `backend/mcp_server.py`
Function: `_invoke` (lines 205-262).

BEFORE (line 252):

```python
result = await dispatch(name, args, ctx)
return {"ok": True, "result": result}
```

AFTER:

```python
result = await dispatch(name, args, ctx, db=db)
return {"ok": True, "result": result}
```

V1 risk:
- 3a: NONE for v1 dispatch wrappers (they don't accept `db`; the new
  kwarg is keyword-only, defaults to None, and is only referenced
  inside the two v2 branches).
- 3b: NONE for v1 tools (they ignore `db` even though it is now passed;
  see 3a).

### Step 4 — Commit `_invoke`'s DB session  (Q4/Q5)

See §2 below for the decision rationale. The chosen option is (i):
mirror `_invoke_session` and add `await db.commit()` after dispatch
succeeds.

File: `backend/mcp_server.py`
Function: `_invoke` (lines 205-262).

BEFORE (lines 250-257):

```python
from agents.insights.tools.registry import dispatch

result = await dispatch(name, args, ctx, db=db)
return {"ok": True, "result": result}
except Exception as exc:  # noqa: BLE001 — surface every failure mode
    logger.exception("mcp.invoke_failed", extra={"tool": name})
    await _safe_rollback(db)
    return {"ok": False, "error": str(exc), "code": "TOOL_FAILED"}
```

AFTER:

```python
from agents.insights.tools.registry import dispatch

result = await dispatch(name, args, ctx, db=db)
# Mirror _invoke_session: a single per-MCP-call commit so writes
# performed by v2 tools (build_chart's agent_chart row,
# persist_insight_v2's ai_insight + chart binding rows) become
# visible to the next MCP call. v1 tools do not write through `db`,
# so the commit is a no-op for them and adds no regression risk.
await db.commit()
return {"ok": True, "result": result}
except Exception as exc:  # noqa: BLE001 — surface every failure mode
    logger.exception("mcp.invoke_failed", extra={"tool": name})
    await _safe_rollback(db)
    return {"ok": False, "error": str(exc), "code": "TOOL_FAILED"}
```

V1 risk: LOW. v1 tools (query_database is read-only; emit_chart and
get_chart_data also do not call `db.add` against the `_invoke` session)
will see a commit on a transaction with no pending writes — a no-op at
PG level. Validate by running the existing v1 SSE-translator test
matrix (§8).

### Step 5 — Refresh `_force_finalize_degraded` from authoritative DB count  (C5)

File: `backend/agents/insights/agentic_synthesis.py`
Function: `_force_finalize_degraded` (lines 318-369).

BEFORE (lines 332-356):

```python
try:
    from .db.models import AISession

    # Don't clobber a row another path already finalized.
    from sqlalchemy import select

    existing = (
        await db.execute(select(AISession).where(AISession.id == session_id))
    ).scalar_one_or_none()
    if existing is None:
        return
    if existing.status in ("complete", "degraded", "failed", "cancelled"):
        return

    await db.execute(
        update(AISession)
        .where(AISession.id == session_id)
        .values(
            status="degraded",
            finished_at=datetime.utcnow(),
            insights_emitted=int(insights_count or 0),
            budget_status="clipped",
        )
    )
    await db.commit()
```

AFTER:

```python
try:
    from .db.models import AISession, AIInsight

    # Don't clobber a row another path already finalized.
    from sqlalchemy import func, select

    existing = (
        await db.execute(select(AISession).where(AISession.id == session_id))
    ).scalar_one_or_none()
    if existing is None:
        return
    if existing.status in ("complete", "degraded", "failed", "cancelled"):
        return

    # The accumulator-derived `insights_count` is unreliable when v2
    # tool names didn't propagate through the SSE translator (Phase D
    # bug). Resolve the authoritative number from the DB so the
    # session-row reflects what actually persisted.
    db_count_row = await db.execute(
        select(func.count(AIInsight.id)).where(AIInsight.session_id == session_id)
    )
    db_count = int(db_count_row.scalar() or 0)
    effective_count = max(int(insights_count or 0), db_count)

    await db.execute(
        update(AISession)
        .where(AISession.id == session_id)
        .values(
            status="degraded",
            finished_at=datetime.utcnow(),
            insights_emitted=effective_count,
            budget_status="clipped",
        )
    )
    await db.commit()
```

Decision (per §5 below): keep `status='degraded'` for transparency even
when `db_count > 0`. The session legitimately did NOT see
`finalize_session`, so flagging it as degraded preserves the operational
signal; we just stop lying about the row count.

V1 risk: LOW. v1 sessions also write rows to `ai_insight` via the MCP
`persist_insight` tool, so the same SELECT COUNT applies. If the v1
accumulator was correct (it was), `effective_count == insights_count`
and the visible row is unchanged.

### Step 6 — Add INFO logging in `_invoke`  (debuggability)

File: `backend/mcp_server.py`
Function: `_invoke` (lines 205-262).

BEFORE (function head, line 212):

```python
"""Resolve a SkillContext and dispatch to the named tool.

Mirrors ``backend/routers/agent_tools.py::_invoke_tool`` so the
OpenClaw lane and the curl-test lane share identical envelopes.
"""
```

AFTER (add a clock import at top of file if not already there, then):

```python
"""Resolve a SkillContext and dispatch to the named tool.

Mirrors ``backend/routers/agent_tools.py::_invoke_tool`` so the
OpenClaw lane and the curl-test lane share identical envelopes.
"""
import time
_t0 = time.monotonic()
logger.info(
    "mcp.invoke_start",
    extra={"tool": name, "thread_id": thread_id, "session_id": session_id},
)
```

And, inside the try-block at the success-return site, just before
`return {"ok": True, "result": result}` (right after `await
db.commit()`), add:

```python
logger.info(
    "mcp.invoke_ok",
    extra={
        "tool": name,
        "duration_ms": int((time.monotonic() - _t0) * 1000),
    },
)
```

The existing `logger.exception("mcp.invoke_failed", ...)` line at 255
already covers the error path; extend its `extra` dict to include
duration:

BEFORE:

```python
logger.exception("mcp.invoke_failed", extra={"tool": name})
```

AFTER:

```python
logger.exception(
    "mcp.invoke_failed",
    extra={
        "tool": name,
        "duration_ms": int((time.monotonic() - _t0) * 1000),
    },
)
```

(Style note: existing `logger.exception` calls in this file use a
positional message + `extra=` dict — this matches.)

V1 risk: NONE. Pure observability addition.

---

## 2. DB visibility decision for `_invoke`

**Choice: (i) — add `await db.commit()` after dispatch in `_invoke()`,
mirroring `_invoke_session`.**

Rationale:

- It is the smallest possible diff (one line), self-contained in
  `mcp_server.py`, and does not require touching every v2 tool.
- It restores symmetry with `_invoke_session` (mcp_server.py:185),
  which has been working correctly for session tools — we know the
  pattern is safe.
- Option (ii) would force v2 tools to call into a session-tool-shaped
  handler map; that's a bigger refactor and bleeds session-tool
  semantics (validation errors, etc.) into the v2 path.
- Option (iii) (each tool opens its own session) doubles the DB
  connection footprint per agent turn and re-creates the visibility
  problem for any future tool author who forgets the pattern.

Transaction-isolation risk:

- Each MCP call already runs in its own AsyncSession (`async_session_factory()`
  at line 238). Concurrent v2 sessions therefore use independent
  connections; `commit()` does not couple them.
- The known cross-call ordering inside ONE session (build_chart →
  persist_insight_v2) is serialised by the agent: the agent waits for
  build_chart's response before emitting persist_insight_v2. So the
  v2 dependency `chart_id` is committed before `persist_insight_v2`
  reads it.
- Concurrent runs that both insert into `agent_chart` use UUID-based
  `id` (see `_short_chart_id()` in build_chart.py:346), so PK collision
  is a non-issue.
- `ai_insight` rows are scoped by `session_id`, which is unique per
  orchestrator run.

Mitigation against `chart_id` mis-binding under concurrency: leave
`persist_insight_v2`'s existing chart-resolution check in place (it
filters by `session_id` already, per `persist_insight_v2.py:_resolve_chart`).
A chart from session A cannot be bound to session B even by mistake.

---

## 3. Registry signature change

Goals:

1. v2 tools receive a write-capable `db`.
2. v1 dispatch wrappers (which don't accept `db`) compile and run
   unchanged — the `db` kwarg goes into the dispatcher fn ONLY for
   build_chart and persist_insight_v2.

Proposed new signature (already shown in §1 step 3a):

```python
async def dispatch(
    name: str,
    args: dict[str, Any],
    ctx: SkillContext | None = None,
    *,
    db: Any | None = None,
) -> Any:
```

`db` is keyword-only and defaults to `None` — every existing caller
that does `await dispatch(name, args, ctx)` continues to work
byte-equivalently.

Forwarding from `_invoke` (mcp_server.py:252):

BEFORE: `result = await dispatch(name, args, ctx)`
AFTER:  `result = await dispatch(name, args, ctx, db=db)`

`_invoke_session` (mcp_server.py:184) does NOT call `dispatch` — it
calls a session-tool handler from `session_tools.HANDLERS`. No edit
required there.

Per-tool entries (BEFORE/AFTER):

- v1 (no change): `query_database`, `call_api`, `get_chart_data`,
  `run_skill`, `emit_chart`, `web_search`, `read_workspace`,
  `search_documents`, `emit_citation`. Each call site continues to
  pass only `ctx if accepts_ctx else None` and never reads `db`.
- v2 build_chart: replace omitted `db` with `db=db`. (See diff in
  §1 step 3a.)
- v2 persist_insight_v2: replace `db=None` with `db=db`. (See diff in
  §1 step 3a.)

---

## 4. Translator extension

Already enumerated in §1 step 2. Summary diff shape:

New constants block (near top of `sse_translator.py`, ~line 65):

```python
_V2_PERSIST_TOOL_NAMES = frozenset({"persist_insight_v2"})
_PERSIST_TOOL_NAMES = frozenset({"persist_insight"}) | _V2_PERSIST_TOOL_NAMES
```

Started branch — line 599:
- BEFORE: `if pending.name == "persist_insight":`
- AFTER:  `if pending.name in _PERSIST_TOOL_NAMES:`

Completed branch — line 666:
- BEFORE: `if pending.name == "persist_insight":`
- AFTER:  `if pending.name in _PERSIST_TOOL_NAMES:`

Finalize branch — line 692: NO CHANGE.

`build_chart`, `search_documents`, `read_workspace` correctly fall
through the generic else and emit `ToolCallStarted/Complete` events.
They are NOT insight-class and must not bump
`total_insights_persisted`.

---

## 5. Force-finalize hardening (C5)

Decision: keep `status='degraded'` for transparency, populate
`insights_emitted` from `max(accumulator, db_count)`. Do NOT upgrade to
`'complete'` even if `db_count >= max_insights`.

Rationale:

- The whole point of `_force_finalize_degraded` is the safety net for
  "agent never called finalize_session". That fact alone is the signal
  ops cares about; lying about it would mask real agent-driver
  problems.
- `insights_emitted` is what the UI shows on the session card. Setting
  it to the actual row count fixes the user-visible "0 insights"
  symptom while preserving the degraded flag for operator review.
- `budget_status='clipped'` stays — it's the same accuracy story.

Diff shown in §1 step 5.

---

## 6. Logging additions

Already shown in §1 step 6. Restated for ease of review:

`mcp.invoke_start` (INFO) — fires on entry, includes `tool`,
`thread_id`, `session_id`.
`mcp.invoke_ok` (INFO) — fires on success, includes `tool`,
`duration_ms`.
`mcp.invoke_failed` (EXCEPTION, existing) — extend `extra` to include
`duration_ms`.

Style: matches the existing `logger.exception("mcp.session_invoke_failed",
extra={"tool": name})` shape (mcp_server.py:195).

---

## 7. v1 regression risk per change

| Step | Risk   | Justification |
|------|--------|---------------|
| 1    | NONE   | v1 sessions arrive with `self.version == "v1"` and the driver default is also `"v1"`; the kwarg is now explicit but byte-equivalent. |
| 2    | NONE   | v1's `persist_insight` is in the new `_PERSIST_TOOL_NAMES` set. Behaviour for v1 tool names is unchanged. v2-only names (`persist_insight_v2`) flow through the same path that v1 already exercises. |
| 3a   | NONE   | `db` is keyword-only with default `None`. v1 dispatch wrappers do not read it. |
| 3b   | NONE   | v1 tools ignore the now-passed `db` (no `db.add` calls in v1 wrappers). |
| 4    | LOW    | Adds `await db.commit()` to v1 calls too; v1 tools have no pending writes so commit is a PG no-op. Validate by re-running v1 SSE-translator tests. |
| 5    | LOW    | New SELECT COUNT(*) runs for v1 force-finalize too, but v1 accumulator is correct so `effective_count` equals `insights_count`. Visible behaviour for v1 is unchanged. |
| 6    | NONE   | Pure observability. |

---

## 8. Test strategy

All commands assume the venv at
`/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/.venv` and
`SKIP_SCHEMA_DOC_REFRESH=1`.

### 8.1 Unit — accumulator recognises persist_insight_v2

New file: `backend/tests/test_sse_translator_v2_persist.py`

Assert: feed a synthetic OpenClaw chunk with `tool_calls[0].function.name
== "persist_insight_v2"` plus a `finish_reason="tool_calls"` follow-up
into `translate_synthesis_chunk` against a fresh `SynthesisChunkAccumulator`,
then verify `acc.total_insights_persisted == 1` AND `acc.current_insight_idx
== 1`. Mirror the existing v1 `persist_insight` test for byte-equivalent
shape.

### 8.2 Unit — `dispatch("build_chart", ..., db=async_session)` writes a row

New file: `backend/tests/test_dispatch_build_chart_persists.py`

Use the existing pytest async session fixture. Build a minimal
`SkillContext` and call
`await dispatch("build_chart", {...valid args...}, ctx, db=session)`.
Assert: a row exists in `agent_chart` with the returned `chart_id`,
`session_id == ctx.session_id`, and a non-null `spec` JSON.

### 8.3 Unit — `dispatch("persist_insight_v2", ..., db=async_session, chart_id=cid)` writes a row

New file: `backend/tests/test_dispatch_persist_insight_v2.py`

Pre-seed an `agent_chart` row scoped to a known `session_id`. Call
`dispatch("persist_insight_v2", {... headline, body, chart_id=cid ...},
ctx, db=session)`. Assert:
- `ai_insight` row exists with `version == "v2"` and `chart_id == cid`.
- The dispatch returned `{"ok": True, ...}`.

### 8.4 Integration — mocked OpenClaw end-to-end

New file: `backend/tests/test_v2_synthesis_e2e_mocked_openclaw.py`

Stand up the real orchestrator + driver but stub `_drive_openclaw_stream`
to feed a deterministic transcript:

  build_chart(args=...) -> ok
  persist_insight_v2(args={..., chart_id: <from prev>}) -> ok
  finalize_session(status="complete") -> ok

Assert (acceptance criteria a-d):
- `ai_session.status == 'complete'`,
  `ai_session.insights_emitted == 1`,
  `ai_session.version == 'v2'`.
- `ai_insight` has 1 row with `version='v2'` and a non-null `chart_id`.
- `agent_chart` has 1 row keyed to that session.
- The SSE event sequence contains exactly one `InsightStartedEvent`
  and one `InsightCompleteEvent`.

### 8.5 v1 regression

Re-run existing tests:

```
cd /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend && \
SKIP_SCHEMA_DOC_REFRESH=1 .venv/bin/pytest \
  tests/test_insights_sql_gate.py \
  tests/test_agentic_synthesis_v2.py \
  tests/test_phase_d_router_cutover.py \
  -q
```

Existing v1 SSE-translator tests must produce byte-equivalent SSE
traces — diff against the golden traces in `backend/tests/golden/` if
present.

---

## 9. Rollout / verification checklist

Pre-flight:

```
cd /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend
git status                  # confirm clean working tree on a feature branch
git checkout -b phase-d/v2-path-fix
```

Run the full unit + integration matrix:

```
SKIP_SCHEMA_DOC_REFRESH=1 .venv/bin/pytest -q
```

Boot the dev stack, then trigger a v2 synthesis run via curl (criterion
e):

```
curl -sS -X POST http://localhost:8000/v1/insights/sessions \
  -H 'Content-Type: application/json' \
  -d '{"version": "v2", "max_insights": 3, "filters": {}}'
```

Capture the returned `session_id`. Stream the SSE feed (criterion f):

```
curl -N http://localhost:8000/v1/insights/sessions/<SESSION_ID>/stream \
  -H 'Accept: text/event-stream'
```

Expect to see (in order): `tool_call_started` for build_chart,
`tool_call_complete` for build_chart, `insight_started`,
`insight_complete`, `session_complete` with `insights_emitted >= 1`.

DB acceptance (criteria a-d), via psql:

```
psql -h <host> -U <user> -d strategic_insights -c "
SELECT id, status, version, insights_emitted, budget_status, finished_at
FROM ai_session WHERE id = '<SESSION_ID>';"
-- Expect: status='complete', version='v2', insights_emitted=N>0.

psql -h <host> -U <user> -d strategic_insights -c "
SELECT id, session_id, version, chart_id, headline
FROM ai_insight WHERE session_id = '<SESSION_ID>';"
-- Expect: N rows, all with version='v2', chart_id non-null.

psql -h <host> -U <user> -d strategic_insights -c "
SELECT id, session_id, insight_id, row_hash
FROM agent_chart WHERE session_id = '<SESSION_ID>';"
-- Expect: >=N rows, insight_id back-bound (non-null) on at least N.

psql -h <host> -U <user> -d strategic_insights -c "
SELECT count(*) FROM ai_insight
WHERE session_id = '<SESSION_ID>' AND chart_id IS NULL;"
-- Expect: 0.
```

v1 soak validation (criterion g): trigger a v1 synthesis run with a
`POST` body of `{"version": "v1", ...}` (or omit `version` to take the
default) and confirm a row appears in `ai_insight` with `version='v1'`,
the SSE feed contains `persist_insight`-shaped events, and
`ai_session.status='complete'`. Diff the SSE trace against the golden
v1 trace if available.

Logging validation (criterion h): tail the FastAPI logs while running
the v2 curl above; confirm `mcp.invoke_start` / `mcp.invoke_ok` lines
fire for `build_chart` and `persist_insight_v2` with non-zero
`duration_ms`.

---

## 10. Open questions resolved + new ones

Resolved by this plan:

- P1: orchestrator forwards `version`. Step 1.
- P2: SSE translator recognises v2 persist tool. Step 2.
- P3 + C4: registry plumbs `db`, `_invoke` forwards it. Step 3.
- Q4/Q5: `_invoke` commits. Step 4.
- C5: force-finalize uses authoritative DB count. Step 5.

Out of scope (explicitly noted, NOT touched):

- C6: `agent_tool_call` table never populated by synthesis lane. Same
  defect exists for v1; not a regression introduced by v2 path. File a
  follow-up ticket; do not bundle.

New issues discovered while planning:

- N1 (informational, no fix needed now): `emit_citation` already routes
  through `dispatch` (registry.py:503-513) and uses `ctx` for DB writes
  (citations are persisted via the ctx's `record_citation` skill, not via
  a direct `db.add`). Therefore N1 does NOT need the same `db=` plumbing
  as build_chart/persist_insight_v2. Verify during implementation by
  searching `emit_citation.py` for `db.add` / `session.add` to confirm
  no direct writes; if found, add it to the plumbing list.
- N2: `build_chart`'s `_persist_chart_row` swallows persistence errors
  with a warning (build_chart.py:334-338). After Step 3 lands, a silent
  failure here will reproduce `chart_not_found` symptoms even though
  `_invoke` returned ok. Recommend a follow-up: surface the persistence
  failure as `{"ok": False, "code": "chart_persist_failed"}` so the
  agent can retry. NOT in scope for this fix to keep the diff small.
- N3: `_force_finalize_degraded`'s SELECT COUNT(*) is best-effort. If
  the import of `AIInsight` fails in some legacy environment (model
  rename), the whole try-block's existing `except` swallows the error.
  Acceptable for this surgical fix; flag in the post-mortem.

---

## Appendix — files touched

- `backend/agents/insights/orchestrator.py` (1 line, step 1)
- `backend/openclaw/sse_translator.py` (3 lines + new constants block, step 2)
- `backend/agents/insights/tools/registry.py` (signature + 2 wrappers, step 3a)
- `backend/mcp_server.py` (3 lines for db forwarding + commit + logging, steps 3b, 4, 6)
- `backend/agents/insights/agentic_synthesis.py` (~10 lines in
  `_force_finalize_degraded`, step 5)

Test files added (new, no edits to existing tests):

- `backend/tests/test_sse_translator_v2_persist.py`
- `backend/tests/test_dispatch_build_chart_persists.py`
- `backend/tests/test_dispatch_persist_insight_v2.py`
- `backend/tests/test_v2_synthesis_e2e_mocked_openclaw.py`

Total production diff target: under 60 lines.
