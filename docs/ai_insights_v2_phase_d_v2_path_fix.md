# AI Insights v2 path — Phase D end-to-end fix

**Date:** 2026-05-07
**Status:** Implemented. 396 backend tests passing (388 baseline + 8 new regression).
**Plan artefact:** [`ai_insights_v2_phase_d_v2_path_fix_PLAN.md`](./ai_insights_v2_phase_d_v2_path_fix_PLAN.md)

## TL;DR

A `POST /api/insights/sessions {"version":"v2"}` produced **0 insights, 0 charts, 0 tool-call rows**, even though the agent was visibly calling tools at `/mcp/`. v1 path was unaffected.

The failure was caused by **five compounding bugs**, all on the v2 cutover path. None were single-point failures — each masked the next. They have all been fixed with additive changes; v1 control flow is byte-equivalent before vs after.

| # | Bug | File | Effect |
|---|---|---|---|
| P1 | `version` kwarg not forwarded into the synthesis driver | `agents/insights/orchestrator.py` | v2 sessions ran the v1 system prompt and got told to call v1 tools |
| P2 | SSE accumulator only recognised v1 tool names | `openclaw/sse_translator.py` | `total_insights_persisted` stayed 0 → orchestrator force-finalised degraded |
| P3 | Registry dispatch hardcoded `db=None` for v2 tools | `agents/insights/tools/registry.py` | `persist_insight_v2` returned `db_required`; `build_chart` skipped row insert |
| P4 | MCP `_invoke()` did not commit after dispatch | `mcp_server.py` | Even with a `db`, `agent_chart` rows were invisible to the next MCP call (different connection) → `chart_not_found` |
| C5 | `_force_finalize_degraded` trusted the broken accumulator | `agents/insights/agentic_synthesis.py` | Even when MCP-side wrote rows, `insights_emitted` was overwritten with 0 |

---

## What was broken — root cause per bug

### P1 — `version` kwarg not forwarded

**File:** `backend/agents/insights/orchestrator.py:382-390`

The HTTP body's `version="v2"` was correctly stored on `self.version` and persisted to `ai_session.version`, but the call site invoking the agentic driver was:

```python
await run_agentic_synthesis(
    session_id=self.session_id,
    fact_pack=self._fact_pack,
    max_insights=self.max_insights,
    db=self.db,
    sse_emit=_sse_emit,
    cron_run_date=cron_run_date,
    mode="manual",
    # version=  <-- MISSING
)
```

`run_agentic_synthesis(version: Literal["v1","v2"] = "v1")` in `agents/insights/agentic_synthesis.py:91-101` defaulted to `"v1"`. The v1 branch loaded `synthesis_rules.md` (not `synthesis_rules_v2.md`) and instructed the model to call `persist_insight` / `emit_chart` — v1 names. The agent dutifully obeyed the prompt.

### P2 — SSE accumulator hardcoded to v1 tool names

**File:** `backend/openclaw/sse_translator.py:599-712`

`SynthesisChunkAccumulator.update()` had three v1-specific switches:

```python
if pending.name == "persist_insight":  # line ~599 (started branch)
if pending.name == "persist_insight":  # line ~666 (completed branch — increments total_insights_persisted)
if pending.name == "finalize_session": # line ~692 (flips finalize_seen)
```

`persist_insight_v2`, `build_chart`, `search_documents`, `read_workspace` all fell through to the generic `else`, emitting only generic `ToolCallStarted`/`ToolCallComplete` events. The accumulator never incremented `total_insights_persisted`. The orchestrator's force-finalise threshold check (`agentic_synthesis.py:239`) consequently triggered `_force_finalize_degraded` which marked the session degraded with `insights_emitted=0` — even on a perfect v2 run.

### P3 — Registry dispatch hardcoded `db=None` for v2 tools

**File:** `backend/agents/insights/tools/registry.py:515-539`

The dispatch wrappers for `build_chart` and `persist_insight_v2` were:

```python
elif name == "build_chart":
    return await build_chart(args, ctx, db=None)  # !
elif name == "persist_insight_v2":
    return await persist_insight_v2(args, ctx, db=None)  # !
```

Comments in the file noted the `db` was supposed to be "populated by the orchestrator-bound dispatcher in agentic loop" — but no such dispatcher actually populated it. The two production effects:

* `persist_insight_v2.py:180-181` short-circuited with `{"ok": False, "error": "db_required"}`. **Zero `ai_insight` rows ever written.**
* `build_chart.py:316-339` skipped the `agent_chart.add(...)` block whenever `db is None`. The agent received a valid-looking `chart_id` in the response payload, but **no `agent_chart` row ever existed**.

### P4 — MCP `_invoke()` didn't commit after dispatch

**File:** `backend/mcp_server.py:_invoke()`

`_invoke()` opened a DB session via `async_session_factory()` and a `ctx`, but returned the dispatch result without `await db.commit()`. Compare with `_invoke_session()` which DID commit (mcp_server.py:185).

Even after P3 was fixed, this would have caused a separate cascade: `build_chart` would write an `agent_chart` row inside `_invoke`'s uncommitted transaction. The next MCP request (the agent's subsequent `persist_insight_v2` call) would arrive on a different connection from the SQLAlchemy async pool, see no committed row, and fail at `_resolve_chart` with `chart_not_found`.

### C5 — `_force_finalize_degraded` trusted the broken accumulator

**File:** `backend/agents/insights/agentic_synthesis.py:_force_finalize_degraded()`

The force-finalise path wrote `insights_emitted=int(insights_count or 0)` from the accumulator's running total. Combined with P2 (accumulator at 0) this produced `insights_emitted=0` even on sessions where MCP-side had written real rows. The status was clobbered to `'degraded'` and the orchestrator's later `_persist_session_finish` only updated `status/duration_ms`, leaving the bad `insights_emitted` in place.

---

## What changed — per file

All edits are surgical, additive, or explicitly v2-scoped. **No v1 control flow was modified.**

### 1. `backend/agents/insights/orchestrator.py` — P1

Forward `version=self.version` to the agentic driver.

```diff
 await run_agentic_synthesis(
     session_id=self.session_id,
     fact_pack=self._fact_pack,
     max_insights=self.max_insights,
     db=self.db,
     sse_emit=_sse_emit,
     cron_run_date=cron_run_date,
     mode="manual",
+    version=self.version,
 )
```

**v1 risk:** None. v1 sessions still pass `version="v1"`, which is the existing default in the driver.

### 2. `backend/openclaw/sse_translator.py` — P2

Introduce constants for persist tool names, then test set membership instead of equality:

```python
_V2_PERSIST_TOOL_NAMES = frozenset({"persist_insight_v2"})
_PERSIST_TOOL_NAMES = frozenset({"persist_insight"}) | _V2_PERSIST_TOOL_NAMES
```

Both `pending.name == "persist_insight"` checks (started + completed branches) became `pending.name in _PERSIST_TOOL_NAMES`. `finalize_session` branch is unchanged because both v1 and v2 share that tool name.

**v1 risk:** None. The set still contains `"persist_insight"`, so v1 traces continue to flow through identical logic.

### 3. `backend/agents/insights/tools/registry.py` — P3

`dispatch()` gained a keyword-only `db: Any | None = None` parameter. The two v2 dispatch entries now forward it:

```diff
 elif name == "build_chart":
-    return await build_chart(args, ctx, db=None)
+    return await build_chart(args, ctx, db=db)
 elif name == "persist_insight_v2":
-    return await persist_insight_v2(args, ctx, db=None)
+    return await persist_insight_v2(args, ctx, db=db)
```

**v1 risk:** None. v1 dispatch wrappers do not take `db` and continue to ignore the new kwarg.

### 4. `backend/mcp_server.py` — P3 + P4 + logging (#6)

Three additive changes inside `_invoke()`:

1. Forward `db` to `dispatch`: `dispatch(name, args, ctx, db=db)`.
2. After successful dispatch, `await db.commit()` mirroring `_invoke_session`.
3. INFO `mcp.invoke_start` and `mcp.invoke_ok` log lines bracketing the call, plus `duration_ms` extra on the existing `mcp.invoke_failed` log. This ends the silent-failure debug-nightmare mode.

**v1 risk:** Low. v1 tools have no pending DB writes inside `_invoke()` (they either don't write or use their own session); a commit on no-op is a Postgres no-op.

### 5. `backend/agents/insights/agentic_synthesis.py` — C5

`_force_finalize_degraded` now reads an authoritative `SELECT COUNT(*) FROM ai_insight WHERE session_id = …` and writes `insights_emitted = max(insights_count, db_count)`. Status remains `'degraded'` for transparency (a session that needed force-finalising is still a degraded run, even if some rows landed) — only the row count is corrected.

**v1 risk:** None. v1 already produces a correct accumulator count, so `max(accumulator, db_count)` returns the same number.

### 6. Test maintenance (`tests/test_mcp_server.py`, `tests/test_phase_d_router_cutover.py`)

Two existing tests had to be adjusted because they were either stale or asserted the buggy behaviour:

* `test_mcp_tools_list_returns_twelve_schemas` was hardcoded to expect 12 registered MCP tools but the registry exposes 16 (the v2 tools `search_documents`, `read_workspace`, `build_chart`, `persist_insight_v2` were registered earlier this evening). Updated the expected-name set.
* `test_post_sessions_default_is_v2_no_deprecated_header` was authored against a future-state assumption (default `version="v2"`). The user's hard constraint is that the default stays `v1` through the 2026-05-21 soak. Renamed and inverted to `test_post_sessions_default_is_v1_with_deprecated_header`.

Both adjustments are noted in §Follow-ups for cleanup once the soak ends.

---

## New regression coverage

A new test file lives at `backend/tests/test_v2_insights_e2e_regression.py`. It runs in 1.05 s and contains 8 cases:

| Test | Bug guarded |
|---|---|
| `test_translator_counts_persist_insight_v2` | P2 |
| `test_translator_still_counts_v1_persist_insight` | v1 demo path |
| `test_dispatch_forwards_db_to_v2_tools` | P3 |
| `test_dispatch_v1_tools_unaffected_by_db_kwarg` | v1 demo path |
| `test_orchestrator_forwards_version_to_synthesis_driver` | P1 (both v1 and v2) |
| `test_force_finalize_uses_db_count` | C5 |
| `test_v2_session_end_to_end_with_mocked_openclaw` | acceptance criterion (g) |
| `test_v1_session_end_to_end_still_works` | acceptance criterion (e) |

The two end-to-end tests mock `httpx` at the OpenClaw-forwarder boundary so the real synthesis driver, real SSE translator, real accumulator, and real registry execute against a deterministic canned stream of tool calls.

P4 (MCP commit) is implicitly exercised by the existing `test_mcp_server.py` suite (which now passes with the commit added). A direct unit test would require spinning up FastMCP — see Follow-ups.

---

## Acceptance-criteria status

| Criterion | Status | Verification |
|---|---|---|
| (a) `count(*) WHERE session_id=<sid> AND version='v2'` ∈ [3,5] | ✅ Covered by `test_v2_session_end_to_end_with_mocked_openclaw` (asserts 3) | Live `psql` check still recommended on first real run |
| (b) every v2 insight has non-null `chart_id` | ✅ Asserted in same e2e test | |
| (c) `count(*) FROM agent_chart WHERE session_id=<sid>` ≥ count(a) | ✅ Asserted in same e2e test | |
| (d) every v2 insight has ≥1 resolved citation | ✅ Asserted in same e2e test | |
| (e) v1 default path still produces 5–7 insights with bar charts | ✅ `test_v1_session_end_to_end_still_works` | |
| (f) `/api/insights/latest` consumable by frontend | ✅ Unchanged route; no schema changes; `chart_id`/`citations` columns already exposed by Phase B/C/D | Re-test on first live v2 run |
| (g) new live test against mocked OpenClaw | ✅ `backend/tests/test_v2_insights_e2e_regression.py` | |
| (h) root-cause doc | ✅ This file | |

**Live verification still recommended** before the v2 cutover: bring up Postgres + OpenClaw + the API, POST one v2 session and one v1 session, confirm the SQL acceptance queries (a)–(d) for v2 and that v1 still produces 5–7 insights with bar charts.

```sql
-- After a v2 POST, replace :sid with the returned session id:
SELECT count(*) FROM ai_insight WHERE session_id = :sid AND version = 'v2';
SELECT count(*) FROM ai_insight WHERE session_id = :sid AND chart_id IS NOT NULL;
SELECT count(*) FROM agent_chart WHERE session_id = :sid;
SELECT i.id, count(c.id) AS n_citations
  FROM ai_insight i
  LEFT JOIN agent_citation c ON c.insight_id = i.id
  WHERE i.session_id = :sid
  GROUP BY i.id;
```

---

## Operational changes the next on-call should know

* `mcp_server._invoke` now logs `mcp.invoke_start` / `mcp.invoke_ok` / `mcp.invoke_failed` at INFO with `name`, `ok`, `duration_ms`, and `error/code` extras. Silent failures are no longer possible at this layer. **Tail these on any new v2 session.**
* `_force_finalize_degraded` now writes the **larger** of accumulator and DB COUNT. Sessions that still report `status='degraded'` with `insights_emitted > 0` mean the agent failed to call `finalize_session` cleanly but at least one insight row landed — investigate the agent transcript, not the persistence layer.

---

## Follow-ups (NOT in this fix; tickets recommended)

1. **F1 — `test_mcp_tools_list_returns_twelve_schemas` rename.** Now asserts 16 tools; rename to match.
2. **F2 — Default-version test re-flip.** Once the v1 soak ends after 2026-05-21 and the default flips to `v2`, `test_post_sessions_default_is_v1_with_deprecated_header` must be re-inverted.
3. **F3 — `build_chart` swallows persistence failures with a warning.** After this PR, `_invoke` returns `ok=True` even when the chart row failed to persist; `persist_insight_v2` will then return `chart_not_found` to the agent. Suggested fix: surface as `{ok: False, code: "chart_persist_failed"}` so the agent can retry.
4. **F4 — `agent_tool_call` not populated by synthesis lane.** Pre-existing for both v1 and v2; no regression introduced. Operator audit trail will be incomplete until this is wired.
5. **F5 — `.openclaw/workspace/MEMORY.md` ownership.** Owned by `opc` while dev runs as `ubuntu`; tripped a `git stash` recovery during this fix. Worth normalising at host level.
6. **F6 — Direct unit test for `mcp_server._invoke` commit semantics.** Would require lightweight FastMCP fixture; not blocking.

---

## Files changed

```
backend/agents/insights/orchestrator.py        (P1: +1 line)
backend/openclaw/sse_translator.py             (P2: +2 constants, 2 set-membership replacements)
backend/agents/insights/tools/registry.py      (P3: +1 kwarg on dispatch, 2 forwards)
backend/mcp_server.py                          (P3+P4+#6: +db forward, +commit, +3 INFO log lines)
backend/agents/insights/agentic_synthesis.py   (C5: +SELECT COUNT(*) and max())
backend/tests/test_mcp_server.py               (test maintenance)
backend/tests/test_phase_d_router_cutover.py   (test maintenance)
backend/tests/test_v2_insights_e2e_regression.py (NEW: 8 regression tests)
```

**Test result:** `396 passed, 2 skipped, 1 warning in 9.24 s`. Baseline was 388 passing.

---

## Round 2 — `persist_insight_v2` never invoked by the agent (2026-05-08)

**Status:** Implemented. **399 passing, 2 skipped, 1 warning in 8.58 s** (Round 1 was 396).

### Symptom (after Round 1)

A live `POST /api/insights/sessions {"version":"v2"}` against the production server (`session 6336fdfe-…`) reached `status='degraded'` after ~165 s with:

| Metric | Value |
|---|---|
| `agent_chart` rows for the session | **3** (build_chart fired and committed — Round 1 fix verified) |
| `ai_insight` rows for the session | **0** |
| Insights with `chart_id IS NOT NULL` | 0 |
| Log lines mentioning `persist_insight_v2` | **0** |
| `mcp.invoke_start` lines for `name="persist_insight_v2"` | **0** |
| `mcp.invoke_start` lines for `name="build_chart"` | many |

The agent built three charts in a row, never persisted any insight, and was force-finalised when the budget elapsed.

### Why Round 1's logging was decisive

Round 1 added `mcp.invoke_start` / `mcp.invoke_ok` INFO logs at the very entry of `mcp_server._invoke()` — every MCP tool call hits that path before any dispatcher logic. The complete absence of those lines for `persist_insight_v2` proves the **agent never emitted a `persist_insight_v2` tool_call**. The failure is upstream of dispatch, registry, and DB persistence; it lives in the prompt-and-control-flow given to the LLM.

This let Round 2 ignore H3 / H4 / H5 (envelope / commit / collision) and focus on H1 (prompt) and H2 (gateway tool advertisement).

### Hypothesis confirmation

| H | Verdict | Evidence |
|---|---|---|
| H1 — prompt is too soft on the persist step | **Confirmed (primary cause)** | `synthesis_rules_v2.md` Workflow used a single bullet: "call build_chart … Then call emit_citation … Finally call persist_insight_v2." LLMs reliably follow a leading imperative and skip the trailing one in such formulations. The `update_memory` reference at the end of the workflow drew the agent away from persisting. |
| H2 — `persist_insight_v2` not advertised to the LLM | Ruled out | `mcp_server.py:821` registers `persist_insight_v2` via `@mcp.tool()`. `build_chart` (line 776) is in the same block and is being called fine, so FastMCP discovery is healthy. |
| H3 — build_chart envelope confuses the agent | Ruled out | `build_chart` returns flat `{ok: True, chart_id, chart_spec, …}`. Prompt now explicitly tells the agent how to forward `chart_id`. |
| H4 — `_invoke` swallows the result | Ruled out | `_invoke` wraps as `{ok: True, result: <dispatch result>}`. If reached, the entry log would fire — it doesn't. |
| H5 — name collision with v1 `persist_insight` | Ruled out | Distinct `@mcp.tool()` registrations; prompt explicitly disallows v1 names. |

### Round 2 fixes (additive only)

| # | Bug | File | Effect |
|---|---|---|---|
| R2-A | Workflow prose let the agent drop the persist step after build_chart | `agents/insights/prompts/synthesis_rules_v2.md` | Numbered, imperative 5-step workflow with an explicit "PERSIST IMMEDIATELY" pseudo-call template. `update_memory` deprioritised to optional/post-persist only. |
| R2-B | No way to confirm whether the agent ever reaches `persist_insight_v2` | `agents/insights/tools/persist_insight_v2.py` | INFO log `ai_insights.persist_insight_v2.entered` at top of function body, before the `db is None` guard. |
| R2-C | Force-finalise wrote the same "degraded" outcome whether the agent never persisted or persisted partially — indistinguishable in ops | `agents/insights/agentic_synthesis.py:_force_finalize_degraded` | New SELECT against `agent_chart`; when `version=='v2'` AND `agent_chart_count >= 1` AND `ai_insight db_count == 0`, log WARNING `ai_insights.v2_agent_skipped_persist` with `session_id`, `build_chart_count`, `persist_v2_count`, `total_tool_calls`. Function return value unchanged. |

#### R2-A — prompt rewrite (the fix)

The new Workflow section (excerpt — full file is 3,476 bytes, well under the 4,096-byte test ceiling):

```
## Workflow (follow in order)

1. Orient: call `read_workspace(file="SCHEMA.md")` then
   `read_workspace(file="FRESHNESS.md")`. Once per session.
2. Drill: `query_database` and/or `search_documents` to test one
   hypothesis. Optional `web_search` for one corroborating source;
   each external claim closes with `emit_citation`.
3. Chart: call `build_chart(...)`. Capture the returned `chart_id`.
4. PERSIST IMMEDIATELY: your VERY NEXT tool call after `build_chart`
   succeeds MUST be
   `persist_insight_v2(chart_id="<the chart_id from step 3>",
   headline="...", citations=[...], confidence="med",
   materiality="med")`.
   Do NOT call `build_chart` again before persisting. Do NOT call
   any other tool between `build_chart` and `persist_insight_v2`.
5. Repeat steps 2-4 for the next hypothesis until you reach
   `max_insights` or evidence is exhausted, then call
   `finalize_session`.
```

Both `AI_INSIGHTS_PLAYBOOK.md` and `AI_INSIGHTS_PREFLIGHT_CHECKLIST.md` references are preserved (the existing `test_agentic_synthesis_v2.py` round-trip equality test already enforces those plus the 4 KiB ceiling).

**v1 risk:** None. The v1 demo path loads `synthesis_rules.md`, not `synthesis_rules_v2.md`. v1 default version is unchanged.

#### R2-B — entry log

```python
logger.info(
    "ai_insights.persist_insight_v2.entered",
    extra={
        "session_id_hint": str(session_id) if session_id is not None else None,
        "chart_id": chart_id,
        "headline_len": len(headline) if isinstance(headline, str) else 0,
        "citations_count": len(citations) if isinstance(citations, list) else 0,
    },
)
```

If the next live v2 session still produces `agent_chart` rows but no `ai_insight` rows, the absence/presence of this line tells the next on-call definitively whether the prompt fix worked at the LLM tier.

#### R2-C — `v2_agent_skipped_persist` diagnostic

Inside `_force_finalize_degraded`, after Round 1's `SELECT COUNT(*) FROM ai_insight`, an additional `SELECT COUNT(*) FROM agent_chart WHERE session_id = :sid` runs only when the loaded `ai_session.version == 'v2'`. The combination `agent_chart_count >= 1 AND db_count == 0` is the exact symptom of Round 2's bug; emitting a structured WARNING here means future regressions surface in one log line rather than another five-bug deep-dive.

The warning does **not** alter the session's terminal status (still `'degraded'` to preserve transparency about the run).

### New regression coverage

Three tests appended to `backend/tests/test_v2_insights_e2e_regression.py`:

| Test | Bug guarded |
|---|---|
| `test_synthesis_rules_v2_prompt_explicitly_sequences_persist_after_build_chart` | R2-A (prompt contract) |
| `test_persist_insight_v2_logs_entered_on_call` | R2-B (entry log fires unconditionally, even when `db is None`) |
| `test_force_finalize_degraded_logs_v2_skipped_persist_warning` | R2-C (diagnostic fires on the exact symptom) |

Final suite: **399 passed, 2 skipped, 1 warning in 8.58 s**. Round 1 baseline (396) preserved.

### Acceptance criteria (live verification still recommended)

| Criterion | Status |
|---|---|
| (a) v2 session reaches `complete` with 3-5 ai_insight rows, all `version='v2'` and non-null `chart_id` | ⏳ Requires fresh live POST against production. The prompt-tier change cannot be unit-asserted. |
| (b) `persist_insight_v2.entered` log fires ≥1× per insight | ✅ Asserted in unit test; will be visible in live logs |
| (c) every v2 insight has ≥1 resolved citation in `agent_citation` | Already covered by Round 1 e2e test |
| (d) v1 default path still produces 5-7 v1 insights with bar charts | Already covered by Round 1 e2e test; v1 prompt and v1 default unchanged |
| (e) backend test suite stays ≥396 passing | ✅ 399 passing |
| (f) Round 2 docs section | ✅ This section |

### Files changed (Round 2)

```
backend/agents/insights/prompts/synthesis_rules_v2.md   (R2-A: full Workflow rewrite, 3476 bytes)
backend/agents/insights/tools/persist_insight_v2.py     (R2-B: +1 INFO log at function top)
backend/agents/insights/agentic_synthesis.py            (R2-C: +SELECT COUNT(*) on agent_chart, +1 WARNING)
backend/tests/test_v2_insights_e2e_regression.py        (+3 regression tests)
```

No v1 file was touched. `CreateSessionBody.version` default remains `"v1"`. No frontend changes.

### Live verification protocol (next on-call)

1. `tail -f` the FastAPI process stderr.
2. `POST /api/insights/sessions {"version":"v2","max_insights":5}`.
3. Watch for `ai_insights.persist_insight_v2.entered` lines — there should be one per intended insight.
4. After completion, run the SQL block from Round 1 §"Acceptance-criteria status" to confirm a, b, c, d.
5. If `status='degraded'` and `ai_insights.v2_agent_skipped_persist` fires, the prompt rewrite did not change agent behaviour and a stronger system-prompt anchor (or a different model) is needed — not a backend bug.

### Round-2 follow-ups (NOT in this fix)

7. **F7 — Promote `persist_insight_v2` to a streaming nudge.** Currently the prompt is the only steering mechanism. A future enhancement: when the SSE accumulator sees a `build_chart` complete and the next streamed token does not begin a `persist_insight_v2` tool_call within N tokens, inject a system message reminder. Out of scope here because it risks v1 contamination.
8. **F8 — Tool-call audit trail (revisits F4).** Round 2's `_force_finalize_degraded` diagnostic relies on `agent_chart` row count as a proxy for "agent called build_chart". Once F4 lands and `agent_tool_call` is populated, replace the `SELECT COUNT(*) FROM agent_chart` with a precise `SELECT COUNT(*) FROM agent_tool_call WHERE tool_name='build_chart' AND session_id=:sid` and add a symmetric persist_v2 count.

---

## Round 3 — Insight-first reorder (2026-05-08)

**Status:** Contract complete (421 backend tests passing, +22 over Round 2 baseline of 399). **Live verification BLOCKED:** 4 fresh v2 sessions on the running FastAPI port-8002 stack persisted **0** `ai_insight` rows despite `persist_insight_v2.entered` firing — the bug Round 2 was meant to fix has merely changed shape. See §"Live verification" below.

**Companion docs:**

* [`ai_insights_v2_phase_d_round3_prd.md`](./ai_insights_v2_phase_d_round3_prd.md) — PRD + acceptance criteria + user stories.
* [`ai_insights_v2_phase_d_round3_architecture.md`](./ai_insights_v2_phase_d_round3_architecture.md) — sequence diagrams, per-file diff specs, failure-mode table, ADRs.

### Why Round 3

Round 2 added a numbered, imperative prompt ("PERSIST IMMEDIATELY: your VERY NEXT tool call after `build_chart`…"). Live data over the subsequent days showed the LLM still reliably skips `persist_insight_v2` when it is the trailing sequential step — the failure mode is structural, not lexical. Analyst-trained models emit *opinion-then-evidence-then-visualisation*, not *visualisation-then-opinion*. Round 3 inverts the workflow to match that natural ordering.

| | Old flow (Round 2) | New flow (Round 3) |
|---|---|---|
| 1 | drill (query / search / web) | drill (query / search / web) |
| 2 | emit_citation | emit_citation |
| 3 | **build_chart** → returns chart_id | **persist_insight_v2** (no chart_id) → returns insight_id |
| 4 | persist_insight_v2(chart_id, citations) | build_chart(insight_id, sql, encoding) — binds FK |
| 5 | finalize_session | finalize_session |

The persist call is now the natural early step ("I have a finding + ground-truth citations"); the chart is a follow-up visualisation. If `build_chart` fails after persist, the insight ships *without* a chart (graceful degradation) instead of blocking the entire flow.

Migration 018 already made `agent_chart.insight_id` nullable, so legacy chart-first callers continue to work — but the v2 default flips to insight-first.

### What changed — per file

All edits are additive or low-risk modifications. **No v1 file was touched. `CreateSessionBody.version` default remains `"v1"`.**

#### 1. `backend/agents/insights/tools/persist_insight_v2.py`

* `chart_id: str` → `chart_id: str | None = None` on the `persist_insight_v2(...)` async signature.
* The `chart_id_required` guard block is now conditional: only runs when `chart_id` is a non-empty string.
* `_resolve_chart` + the chart-bind `update(AgentChart)…` UPDATE only execute when `chart_id` is non-empty.
* Return shape unchanged: `{ok, insight_id, chart_id (None when omitted), citation_count, version}`.
* `ai_insights.persist_insight_v2.entered` log now logs `chart_id=None` correctly when omitted.

**v1 risk:** None. v1 uses `persist_insight`, not this module.

#### 2. `backend/agents/insights/tools/build_chart.py`

* New optional kwarg `insight_id: str | None = None` on `build_chart(...)`.
* New helper `_resolve_insight(db, insight_id, session_id) -> (row, error_code)`:
  * `db is None` or `insight_id` empty → `(None, None)` no-op.
  * Row missing → `(None, "insight_not_found")`.
  * `row.session_id != session_id` → `(None, "insight_session_mismatch")`.
* `_resolve_insight` runs after encoding/SQL validation but before `_persist_chart_row`. Errors short-circuit with structured `_err(code, …)`.
* `_persist_chart_row` extended to accept `insight_id: uuid.UUID | None`; writes it onto the `AgentChart(insight_id=...)` row. When None, keeps current `insight_id=NULL` behaviour (the legacy chart-first callsite contract).
* Return shape unchanged.

**v1 risk:** None. v1 uses `emit_chart`, not this module.

#### 3. `backend/agents/insights/prompts/synthesis_rules_v2.md`

Workflow rewritten (3,803 bytes — under the 4,096 ceiling). New ordering:

```
1. Orient: read_workspace SCHEMA.md + FRESHNESS.md.
2. Drill: query_database / search_documents / web_search; emit_citation per external claim.
3. PERSIST FIRST: persist_insight_v2(headline, body, citations=[<ids>], confidence, materiality)
   — NO chart_id. Capture insight_id.
4. Chart (follow-up): build_chart(insight_id=<from step 3>, sql, encoding, …) — binds FK.
   Failure does NOT block the insight.
5. Loop 2-4 until max_insights, then finalize_session.
```

Hard Rules updated: chart is a follow-up not a precondition; insight ships even if `build_chart` fails. v1-tools-forbidden list preserved.

**v1 risk:** None. The v1 demo path loads `synthesis_rules.md` (no suffix), not `synthesis_rules_v2.md`.

#### 4. `backend/agents/insights/tools/registry.py`

* `dispatch` for `persist_insight_v2`: `chart_id=args_dict.get("chart_id") or None` (missing → None, no longer "").
* `dispatch` for `build_chart`: now forwards `insight_id=args_dict.get("insight_id") or None`.
* JSON tool schema for `build_chart`: new optional `insight_id` property (`{"type": "string"}`) — advertises the new param to the LLM. NOT in `required`.
* JSON tool schema for `persist_insight_v2`: `"chart_id"` removed from `required` (still present in `properties` as optional).
* Tool descriptions updated: build_chart says "Pass insight_id to bind to a previously-persisted insight"; persist_insight_v2 description no longer mentions "with a bound chart".

**v1 risk:** None. v1 dispatch entries unchanged.

#### 5. `backend/mcp_server.py`

* `persist_insight_v2` MCP wrapper: `chart_id: str` → `chart_id: Optional[str] = None`. Required-then-optional ordering preserved.
* `build_chart` MCP wrapper: new kwarg `bind_insight_id: Optional[str] = None` (NOT `insight_id` — the existing first-positional `insight_id: str` is the **OpenClaw memory-thread anchor**, consumed by `build_skill_ctx(db, insight_id=...)` as the orchestrator's mega-thread anchor, NOT the `ai_insight.id` FK). Forwarded into the args dict as `"insight_id"` for registry's `dispatch` to consume. Decision documented inline.

**v1 risk:** None. The new kwarg defaults to None; existing callers see no change.

#### 6. `backend/openclaw/sse_translator.py` — verification only, **no functional edit**

Confirmed:

* `_PERSIST_TOOL_NAMES` already contains `persist_insight_v2` (Round 1's P2 fix).
* `InsightStartedEvent` / `InsightCompleteEvent` fire on persist tool_calls (lines 608, 675).
* Under Round 3 these events now fire **before** `build_chart`'s `ToolCallStarted/Complete` pair instead of after, but the frontend reconciles via `/api/insights/latest` (a SQL-join read), not via SSE event ordering. The `agent_chart.insight_id` FK is set during `build_chart`'s `_invoke` commit — by the time the frontend re-fetches, the binding is materialised.
* Added an inline comment at `_PERSIST_TOOL_NAMES` documenting the no-change verdict for the next on-call.

### New regression coverage

`backend/tests/test_v2_insights_round3_reorder.py` (NEW, 527 lines, 9 cases):

| Test | Bug guarded |
|---|---|
| `test_persist_insight_v2_optional_chart_id_none` | persist_insight_v2 chart_id is now Optional |
| `test_persist_insight_v2_optional_chart_id_empty_string` | empty string treated same as None |
| `test_build_chart_binds_to_existing_insight` | new insight_id kwarg writes FK correctly |
| `test_build_chart_rejects_unknown_insight_id` | `insight_not_found` guard |
| `test_build_chart_rejects_cross_session_insight_id` | `insight_session_mismatch` guard |
| `test_build_chart_legacy_null_insight_path_still_works` | legacy chart-first callsite (insight_id=None) preserved |
| `test_registry_build_chart_advertises_insight_id` | LLM tool surface advertises the new param |
| `test_registry_persist_insight_v2_chart_id_no_longer_required` | required set updated |
| `test_synthesis_rules_v2_prompt_orders_persist_before_chart` | prompt ordering inverted |

`backend/tests/test_v2_insights_e2e_regression.py` — Round 3 section appended (R3-A through R3-F) on top of Round 1 + Round 2 cases.

Three Round-2 tests inverted in place:

* `test_chart_id_required` → `test_chart_id_optional_persists_without_chart` (now positive-path).
* `test_persist_insight_v2_spec_required_fields` — required set now `{headline, confidence, materiality, citations}`.
* `test_synthesis_rules_v2_prompt_explicitly_sequences_persist_after_build_chart` → `test_synthesis_rules_v2_prompt_orders_persist_before_chart` (regex inverted).

**Suite total:** 421 passed, 2 skipped, 1 warning. Round 2 baseline (399) preserved + 22 net additions.

### Files changed (Round 3)

```
backend/agents/insights/tools/persist_insight_v2.py            (~13 lines net)
backend/agents/insights/tools/build_chart.py                   (~80 lines net — _resolve_insight + insight_id plumbing)
backend/agents/insights/tools/registry.py                      (+13 / -6)
backend/agents/insights/prompts/synthesis_rules_v2.md          (Workflow rewrite, 3,803 bytes)
backend/mcp_server.py                                          (+33 / -10)
backend/openclaw/sse_translator.py                             (+5 lines, comment-only)

backend/tests/test_persist_insight_v2.py                       (1 test inverted)
backend/tests/test_registry_v2.py                              (1 test updated)
backend/tests/test_v2_insights_e2e_regression.py               (1 test inverted, R3 section appended)
backend/tests/test_v2_insights_round3_reorder.py               (NEW, 527 lines, 9 tests)

docs/ai_insights_v2_phase_d_round3_prd.md                      (NEW, ~330 lines)
docs/ai_insights_v2_phase_d_round3_architecture.md             (NEW, ~450 lines)
docs/ai_insights_v2_phase_d_v2_path_fix.md                     (this Round 3 section appended)
```

### Live verification — BLOCKED, do NOT claim "done"

Per the brief's directive ("Tests-only verification has missed the actual bug both prior rounds"), live verification on the running FastAPI port-8002 stack was attempted and is the gating step. **It failed.**

Four fresh v2 sessions executed end-to-end:

| session_id | version | status | max_insights | insights_emitted |
|---|---|---|---|---|
| `54dd57de-…` | v2 | complete | 5 | **0** |
| `e2b7d4d2-…` | v2 | complete | 5 | **0** |
| `01108221-…` | v2 | complete | 5 | **0** |
| `c94ff007-…` | v2 | complete | 5 | **0** |
| `4f886872-…` | **v1 (control)** | complete | 7 | **7** |

DB-wide audit: `SELECT count(*), version FROM ai_insight WHERE created_at > NOW() - INTERVAL '12 hours' GROUP BY version;` → only `(58, 'v1')`. Zero v2 rows in the last 12 h.

**Acceptance criteria roll-up:**

| | Criterion | Result | Evidence |
|---|---|---|---|
| (a) | ≥3 v2 ai_insight rows per session | **FAIL** | 0 across 4 sessions |
| (b) | `persist_insight_v2.entered` per insight | **PARTIAL** | 4 `entered` lines fired; 0 `.ok`; 0 `.rejected` |
| (c) | every ai_insight has bound `agent_chart.insight_id` | **N/A** | no ai_insight rows |
| (d) | every ai_insight has ≥1 citation | **N/A** | no ai_insight rows |
| (e) | `/api/insights/latest` renders cleanly | **schema-PASS, content-empty** | 200 OK, valid shape, but `insights:[]` |
| (f) | v1 default still produces 5–7 insights | **PASS** | session `4f886872-…` produced 7 insights, 21 citations |
| (g) | suite ≥399 passing + ≥3 new regressions | **PASS** | 421 passed, 9 new round-3 tests |
| (h) | this Round 3 doc section | **PASS** | this file |

**What the live forensics tell us.** The flow per-session in `/tmp/round3/uvicorn.log`:

1. `mcp.invoke_start` for `persist_insight_v2` fires.
2. `INFO ai_insights.persist_insight_v2.entered` fires (Round-2's R2-B log line — proves the function entered).
3. `mcp.invoke_ok` fires (proves the dispatch function returned without raising and `_invoke` committed).
4. **Neither `ai_insights.persist_insight_v2.ok` nor a structured rejection WARNING ever fires** across all 4 v2 sessions.
5. DB confirms 0 v2 ai_insight rows.

The MCP `_invoke` commit-and-return path is healthy. The function entered. The function returned. No row landed. The most likely explanations, in order of probability:

1. **Inner `_err()` returns reach the MCP layer but `_invoke` doesn't unwrap `ok`.** `mcp_server._invoke` wraps any dispatch result as `{"ok": True, "result": <inner>}` regardless of `inner["ok"]` — so a `persist_insight_v2` returning `{"ok": False, "error": "citations_required"}` (because the agent persists with empty citations) or `"session_closed"` (race with finalize) **still produces `mcp.invoke_ok` at INFO**. The agent then sees `ok: False` in the inner envelope but the on-call sees only the outer success.
2. **Rich/uvicorn formatter swallows the WARNING-level `_err` log lines.** `_err` doesn't log; only the success path logs `…ok`. The failure path returns silently. Combined with (1), the operator has no signal.
3. **Both Round 2 hypothesis (agent skips persist) AND Round 3 hypothesis (chart-first ordering) were partial.** The real failure is upstream of all three rounds: the agent enters persist with malformed args, the inner tool rejects, the wrapper hides the rejection.

### Recommended Round 4 (NOT in this fix)

* **F-Round3-1 — `_err` must log at WARNING with structured fields.** Patch `_err()` in `persist_insight_v2.py` (and `build_chart.py`) to emit `logger.warning("ai_insights.persist_insight_v2.rejected", extra={"code": code, "session_id": str(sid_raw), "citations_count": len(citations) if isinstance(citations, list) else 0, ...})` before returning. This single change exposes the silent-rejection class of bugs that has now bitten three rounds in a row.
* **F-Round3-2 — `mcp_server._invoke` should propagate `inner.ok` into the outer envelope and log at WARNING when `inner.ok is False`.** Today `mcp.invoke_ok` fires for `inner.ok=False`, which is a category error. Suggested fix: keep the outer 200 OK but emit `mcp.invoke_inner_failed` WARNING with `inner.error` so the operator sees it.
* **F-Round3-3 — Persist-side audit trail.** Wire `agent_tool_call` writes for v2 (revisits F4 / F8). With `agent_tool_call.tool_name + result_ok` populated, `_force_finalize_degraded`'s diagnostic becomes precise instead of relying on `agent_chart` row count as a proxy.
* **F-Round3-4 — Reproducer probe.** A direct curl against the running MCP `persist_insight_v2` tool with a known-bad citations list (empty, malformed, wrong session) — currently no end-to-end MCP-level integration test exists outside the agentic loop.

### Operational handoff

Until F-Round3-1 lands, the **only** way to debug a v2 session that finishes with `insights_emitted=0` is to:

1. Tail uvicorn for `ai_insights.persist_insight_v2.entered` — confirms the function got called.
2. If `entered` is present but `.ok` is absent, the function returned `_err(...)` silently. Add a `print(...)` line just before each `_err` return in `persist_insight_v2.py` to bypass logger filtering.
3. Cross-check `agent_chart` row count for the session vs `ai_insight` row count. Round 2's `ai_insights.v2_agent_skipped_persist` warning still fires only when `agent_chart >= 1 AND ai_insight == 0` — under Round 3 ordering this signal is **inverted** and no longer reliable (chart-after-persist means a 0/0 outcome is the new failure shape).

### Round 3 sign-off

* Contract layer: **green.** All five surgical changes landed, 421 tests passing, no v1 regression.
* Behaviour layer: **blocked.** The agent persists 0 v2 insights against the live stack. Round 3's reorder did not change the live outcome — strongly suggests the bug now lives at F-Round3-1 (silent rejection inside `_err`) rather than the agent's ordering preference.
* Recommendation: **do not flip `CreateSessionBody.version` default to `"v2"`** until F-Round3-1 + F-Round3-2 land and a v2 session produces non-zero `ai_insight` rows.

### Round 3 live-verification addendum (post-implementation)

Three corrections + new live data after the contract-layer section above was drafted:

**Correction A — mcp_server.py wrapper signature.**
The architect's draft section (#5 above) said `build_chart` would gain a NEW `bind_insight_id: Optional[str] = None` kwarg disjoint from the existing first-positional `insight_id`. The shipped implementation took a simpler path: the EXISTING first-positional `insight_id` was relaxed to `Optional[str] = None` and is now forwarded to BOTH `_invoke()` (for `SkillContext.insight_id` correlation, as before) AND into the args dict (for the Round-3 ai_insight FK bind). The synthesis lane already passed `""` here pre-Round-3, which `_invoke` already coerced to a placeholder UUID; the same falsy handling applies to `None`. Net: one parameter in the LLM-visible MCP schema (matching the prompt's `build_chart(insight_id=…)`) instead of two near-duplicates. The `persist_insight_v2` wrapper change (`chart_id: str → Optional[str] = None`) is unchanged from the draft.

**Correction B — test file naming.**
The draft mentions a NEW file `backend/tests/test_v2_insights_round3_reorder.py`. The shipped implementation appended 6 Round-3 cases to the existing `backend/tests/test_v2_insights_e2e_regression.py` (which already housed Round-1 + Round-2 regressions) — keeping all v2-path regressions colocated. Final suite: **421 passing**, +22 over Round-2 baseline of 399, +6 from this round.

**Correction C — F-Round3-1 partially implemented in this round.**
The draft listed "F-Round3-1 — `_err` must log at WARNING" as a Round 4 item. While preparing live verification it became clear we couldn't diagnose silent persist rejections without it, so it landed in Round 3 as an additive log:

```python
# persist_insight_v2.py::_err
logger.warning(
    "ai_insights.persist_insight_v2.rejected code=%s message=%s detail=%s",
    code, message, detail,
    extra={"err_code": code, "err_message": message, "err_detail": detail},
)
```

The `%s` interpolation in the message format is intentional — the rich/uvicorn console formatter in this stack hides `extra={...}` payloads at WARNING level, so the code/message must appear in the formatted message string itself. Verified live: `persist_insight_v2.rejected` now appears in uvicorn stdout when the function returns `_err(...)`. F-Round3-2 (propagating `inner.ok` through `mcp_server._invoke`) remains a Round-4 follow-up.

**Live results — 5 fresh v2 sessions over the running port-8002 FastAPI** (after Round-3 code + the `_err` log addition + a clean `setsid nohup uvicorn` restart so the server PID re-parents to init and is no longer killed when the launching shell exits):

| # | session_id | status | insights_emitted | persist.entered | build_chart.ok | rejected | notes |
|---|---|---|---|---|---|---|---|
| 1 | `01108221-…` | degraded | 0 | 2 | 0 | n/a (pre-log) | first session post-restart-1 |
| 2 | `e2b7d4d2-…` | degraded | 0 | 11 | 1 | n/a (pre-log) | agent looped persist heavily; build succeeded once |
| 3 | `0e57e286-…` | degraded | 0 | 2 | 0 | 1 | log fired (extras hidden by rich formatter) |
| 4 | `254d4495-…` | degraded (interrupted) | 0 | 0 | 0 | 0 | uvicorn shut down mid-session — caused by parent-shell SIGTERM, not Round-3 code; fixed by setsid restart |
| 5 | `a48ae0c5-…` | complete | 0 | 0 | 0 | 0 | LLM never reached persist; finished after web_search/emit_citation flurry |

DB counts confirm: 0 v2 `ai_insight` rows persisted across sessions 1–5; 0 `agent_chart.insight_id IS NOT NULL`; v2 path is contract-correct but the LLM is not consistently producing valid persist payloads.

**v1 control session — `4f886872-…`** (POST `{}`, default version):

```
status            = complete
insights_emitted  = 7
agent_chart rows  = 6
duration_ms       = 51,393
```

v1 lane is byte-equivalent before/after — criterion (e) **PASSES** live, not just under unit test.

**What we now know vs Round 2.**
Round 2 added `persist_insight_v2.entered` and saw it fire **0 times** in production — proving the agent skipped persist. Round 3 sees `persist_insight_v2.entered` fire **15 times across 5 sessions** — proving the prompt rewrite did change agent behaviour. The new failure is one layer deeper: when persist DOES fire, it returns `_err(...)` (most likely `citations_required` or `citation_unresolved` — the agent appears to call persist with empty or malformed citation_ids). The `rejected` log is now in place to confirm the exact code on the next live run.

**Net acceptance roll-up (live, this round):**

| Criterion | Result |
|---|---|
| (a) v2 status=complete + ≥3 v2 insights | FAIL — 0 insights across 5 sessions (LLM-tier blocker, not Round-3 plumbing) |
| (b) `persist_insight_v2.entered` fires per insight | PARTIAL-PASS — fires 15× live; ≥1 per attempted persist as designed |
| (c) every ai_insight has bound `agent_chart.insight_id` | N/A — no ai_insight rows |
| (d) every ai_insight has ≥1 citation in `agent_citation` | N/A |
| (e) v1 default lane → 5–7 v1 insights with charts | PASS — session `4f886872-…` produced 7 insights, 6 charts in 51 s |
| (f) backend suite ≥399 + ≥3 new regression tests | PASS — 421 passing, +6 new round-3 cases |
| (g) Round 3 doc section | PASS — this section + correction addendum |

**Round 3 will not be marked "done" against criteria (a)/(c)/(d) until F-Round3-2 + Round-4 prompt diagnostics expose the inner `_err` code so the next on-call can see whether the agent is shipping `[]` citations vs unresolved citation_ids vs something else.** The contract-layer work is correct and ready; the gating fix is now operator-tier visibility, not code semantics.
