# AI Insights v2 — Round 3 Cutover: Insight-First Reorder

**Status:** Architecture proposal. Round 1 + Round 2 of the Phase D fix landed
([`ai_insights_v2_phase_d_v2_path_fix.md`](./ai_insights_v2_phase_d_v2_path_fix.md)).
Round 3 reorders the agent's tool sequence so the **insight is persisted before
the chart**. The persistence path remains atomic on the high-value side; the
chart becomes an optional follow-up.

**Date:** 2026-05-08
**Scope:** Backend (synthesis prompt, two MCP tools, registry dispatch). No
frontend wire-format change. v1 path unchanged.

---

## 1. Why insight-first beats chart-first

Round 2 confirmed (via `mcp.invoke_start` log absence) that the LLM was reliably
calling `build_chart` and reliably *not* calling `persist_insight_v2` when the
prompt placed `build_chart` first. The empirical pattern: an LLM tool agent that
runs out of budget, reasoning turns, or attention will execute the **first**
tool in a sequence and skip the trailing one. Round 2 patched the prompt to
make the second step imperative ("PERSIST IMMEDIATELY"); Round 3 fixes the
underlying control-flow vulnerability by inverting the order.

Three properties of the new order:

1. **High-value tool fires first.** `persist_insight_v2` writes the
   `ai_insight` row plus the citation graph — the artefact the user actually
   sees in the UI. If the agent is interrupted (budget, model failure, network
   hiccup) after step 3, the insight ships.
2. **Low-value tool is the optional follow-up.** `build_chart` is an
   accompaniment. A chart-less insight degrades gracefully on the renderer
   side; an insight-less chart is a stranded SQL artefact with nowhere to live.
3. **Failure budget aligned with risk.** `build_chart` runs SQL through the
   gate and may legitimately fail (gate reject, empty result, encoding
   mismatch). Letting that failure void the insight is unacceptable. Letting
   it void only the chart is correct.

Karan's framing: *if the agent skips the chart, the insight still ships.*
That is the contract Round 3 codifies.

---

## 2. New tool sequencing — five steps

```
(1) read_workspace SCHEMA.md / FRESHNESS.md         once per session
(2) drill: query_database | search_documents |
    web_search + emit_citation per source           per insight
(3) persist_insight_v2(headline, body, citations,
    confidence, materiality)        WITHOUT chart_id
    -> capture insight_id                           per insight
(4) build_chart(insight_id, sql, encoding,
    chart_type, title)
    -> binds chart to insight at INSERT time        per insight (best-effort)
(5) loop 2-4 until max_insights or evidence
    exhausted; finalize_session                     once per session
```

The agent is permitted to skip step 4. The agent is **not** permitted to skip
step 3. The synthesis-rules prompt enforces this with a leading imperative on
step 3 ("PERSIST FIRST") and explicit graceful-degradation language on step 4.

---

## 3. Contract changes

| Tool | Parameter | Round 2 contract | Round 3 contract | Failure surfaces |
|---|---|---|---|---|
| `persist_insight_v2` | `chart_id` | Required string | **Optional**, default `None`. When `None`: skip `_resolve_chart`; insert `ai_insight` row with `chart_id IS NULL`. When provided: existing chart-bind path runs (validates `agent_chart` row + session match, then `agent_chart.insight_id := new insight.id`). | `chart_not_found`, `chart_session_mismatch` only when `chart_id` non-empty. |
| `build_chart` | `insight_id` | not present | **New optional `Optional[str] = None`.** When provided: `_resolve_insight` validates an `ai_insight` row exists for that id (`insight_not_found`) and its `session_id` matches `ctx.session_id` (`insight_session_mismatch`); the `agent_chart` row is then INSERTed with `insight_id=<resolved uuid>`. When `None` / empty: existing behaviour preserved (insert `agent_chart` row with `insight_id IS NULL`). | `insight_not_found`, `insight_session_mismatch`. Both return `{ok:false, error, detail}` and emit no `agent_chart` row. |
| MCP wrapper `build_chart` | `bind_insight_id` | n/a | New MCP-side parameter exposed as `bind_insight_id` to avoid collision with the existing OpenClaw memory-thread anchor `insight_id`. The wrapper forwards it as `insight_id` inside the tool args dict. | n/a (typing only). |
| Registry dispatch | `build_chart` | forwards `db` | also forwards `insight_id=args_dict.get("insight_id") or None`. | n/a. |
| Registry dispatch | `persist_insight_v2` | forwards `db`, `chart_id` required | maps missing/empty `chart_id` to `None`. | n/a. |

**Atomicity of bind direction.** Round 2 bound `agent_chart -> insight` via
`UPDATE agent_chart SET insight_id = :iid` *after* the chart row was already
committed in a prior MCP transaction. Round 3 binds via `INSERT agent_chart
(... insight_id=:iid)` in the same MCP transaction as the row creation. Either
the chart lands fully bound or it does not land at all — no orphan window.

**Headline length, body length, citations-required, session-must-be-open**
guards on `persist_insight_v2` are unchanged.

---

## 4. Failure mode matrix

| Step 3 outcome | Step 4 outcome | DB end state | User-visible result |
|---|---|---|---|
| `persist_insight_v2` ok | `build_chart(insight_id=X)` ok | `ai_insight.chart_id=NULL`, `agent_chart.insight_id=X`. Bidirectional graph by FK on the chart side. | Insight + chart render. (Frontend joins `agent_chart` ON `insight_id` — see §6 risk R-A.) |
| `persist_insight_v2` ok | `build_chart` fails (sql_gate_rejected, empty_result, encoding_field_missing, ...) | `ai_insight.chart_id=NULL`, no `agent_chart` row. | Insight ships chart-less. Renderer must tolerate `chart_id IS NULL` AND zero matching `agent_chart` rows. Acceptance criterion (b) is relaxed: every v2 insight has either a `chart_id` reference *or* a matching `agent_chart.insight_id` row *or* neither (chart-less). |
| `persist_insight_v2` ok | `build_chart` succeeds but `insight_id=None` (legacy chart-first style) | `ai_insight.chart_id=NULL`, `agent_chart.insight_id=NULL`. **Orphan chart** in the table. | OK during soak; the chart is discoverable by `session_id` but unbound. `persist_insight_v2` will not patch it (the agent has already returned). Counts in (c) stay sane. |
| `persist_insight_v2` fails (citation_unresolved, headline_too_long, session_closed, ...) | n/a — agent should not call `build_chart` | No `ai_insight` row, no `agent_chart` row. | The insight is dropped. The agent retries or moves to the next hypothesis. |

The third row is the **soak hazard**: a model that has been trained on the
old order or that ignores the prompt's leading "PERSIST FIRST" imperative
will produce orphan chart rows. The R2-C diagnostic
(`v2_agent_skipped_persist`) already detects the inverse symptom (chart count
without insight count). For Round 3 we add a symmetric structured WARN at
finalise: `v2_agent_skipped_chart_bind` when `agent_chart.insight_id IS NULL
AND session_id=:sid` count exceeds zero. This is observability only — no
status change.

---

## 5. Backwards compatibility

The chart-first flow still works. Both new parameters are optional:

* An agent that calls `build_chart(...)` first (no `insight_id`) gets an
  `agent_chart` row with `insight_id=NULL`, exactly as in Round 2.
* That same agent then calls `persist_insight_v2(chart_id=<chart_id>, ...)`,
  hits the existing `_resolve_chart` path, and patches `agent_chart.insight_id`
  via the post-insert UPDATE.

The v1 demo path is **byte-equivalent** to before:

* v1 prompt is `synthesis_rules.md`, not `synthesis_rules_v2.md`. Untouched.
* v1 default `version="v1"` on `CreateSessionBody`. Untouched.
* v1 dispatcher entries (`emit_chart`, `persist_insight`) do not take `db`
  or `insight_id`. Untouched.
* Round 3 changes only cross v2 code paths.

A snapshot test on the v1 prompt body (`test_agentic_synthesis_v2.py` already
asserts byte-equality of the v2 prompt; a parallel v1 prompt-byte test guards
the v1 path) catches any drift.

---

## 6. Risk register

| ID | Risk | Probability | Detection | Test that catches it |
|---|---|---|---|---|
| R-A | Frontend renderer reads `ai_insight.chart_id` only and never queries `agent_chart WHERE insight_id=:iid`, so insight-first charts never paint. | High if not audited | Visual: insights render with empty chart slots. SQL: `count(ai_insight.chart_id IS NOT NULL) < count(agent_chart.insight_id IS NOT NULL)` for the same session. | Acceptance (a) + (b) — extend (b) to: every v2 insight row joins to >=0 charts, where the join is on `agent_chart.insight_id = ai_insight.id` OR `ai_insight.chart_id = agent_chart.id`. |
| R-B | `build_chart(insight_id=X)` validates session match against `ctx.session_id`, but `ctx.session_id` is None in MCP path under some failure modes -> silent `insight_session_mismatch` returned, agent retries forever. | Low (Round 1 fixed `_invoke` ctx plumbing) | `mcp.invoke_failed` with `error="session_id_required"`. | Existing `test_dispatch_forwards_db_to_v2_tools` plus a new `test_build_chart_insight_id_requires_ctx_session_id`. Acceptance (g). |
| R-C | Agent ignores prompt and reverts to chart-first, producing orphan `agent_chart` rows that accumulate over the soak window. | Medium (LLM behaviour drift) | `v2_agent_skipped_chart_bind` WARN at finalise; SQL: `agent_chart WHERE session_id=:sid AND insight_id IS NULL`. | New unit `test_force_finalize_logs_v2_skipped_chart_bind`. Acceptance (g) extended. |
| R-D | `persist_insight_v2` with `chart_id=None` regresses the existing chart-bind happy path. | Low | E2E test asserts `ai_insight.chart_id IS NOT NULL` when chart_id is supplied. | Existing `test_v2_session_end_to_end_with_mocked_openclaw` + a new variant where the agent passes `chart_id`. Acceptance (a)+(b)+(c). |
| R-E | Two transaction boundaries in flight: `persist_insight_v2` commits (MCP `_invoke` commit, Round 1 fix), then `build_chart(insight_id=X)` runs in a separate connection, sees the just-committed `ai_insight` row, INSERTs the bound `agent_chart`. If the second commit fails, we have an insight without chart — but that is the documented degraded-OK state. | Low | Tail `mcp.invoke_failed` with `name=build_chart`. | Existing Round 1 commit test, plus E2E. |
| R-F | `idx` collision: two parallel inserts (impossible today — single agent loop) would duplicate `(session_id, idx)`. | Negligible at single-agent scope | Constraint violation on insert. | Out of scope — single-loop agent. |
| R-G | `build_chart` Pydantic discriminated-union rejects encoding because of `extra=forbid` after a future schema field is added. | Schema drift | `encoding_shape_invalid`. | Existing `test_build_chart_tool` covers shape-validation. |

**Acceptance criteria for Round 3 (a)-(g):**

(a) `count(*) FROM ai_insight WHERE session_id=:sid AND version='v2'` in [3,5].
(b) for each v2 insight, EITHER `chart_id IS NOT NULL` OR there exists an
`agent_chart` row with `insight_id = ai_insight.id` OR neither (chart-less,
acceptable).
(c) `count(*) FROM agent_chart WHERE session_id=:sid AND insight_id IS NOT NULL`
>= count of non-chart-less insights.
(d) every v2 insight has >=1 resolved citation.
(e) v1 default path still produces 5-7 insights with bar charts.
(f) `/api/insights/latest` consumed by frontend handles all three states in (b).
(g) new e2e test in `test_v2_insights_e2e_regression.py` exercises (i) full
insight-first happy path, (ii) insight-first with `build_chart` failure
(chart-less insight ships), (iii) chart-first backward-compat path.

---

## 7. Sequence diagrams

### Old (chart-first, Round 2)

```
Agent                MCP wrapper           build_chart            persist_insight_v2     DB
  | read_workspace ---->|                                                                   |
  |<--- SCHEMA.md ------|                                                                   |
  | query_database ---->| run gate + execute -------------------------------------------->  |
  |<--- rows -----------|                                                                   |
  | emit_citation ----->|----------------------------> agent_citation INSERT (unbound) ---> |
  |<--- citation_id ----|                                                                   |
  | build_chart  ------>| validate, execute SQL, persist agent_chart (insight_id NULL) -->  |
  |<--- chart_id -------|                                                                   |
  | persist_insight_v2->| validate session, chart, citations                                |
  |                     | INSERT ai_insight ---------------------------------------------> |
  |                     | UPDATE agent_chart SET insight_id=...   <-- second xn, bind ----> |
  |                     | UPDATE agent_citation SET insight_id=...                        > |
  |<--- insight_id -----|                                                                   |
  | (loop x3)
  | finalize_session -->|
```

Failure mode if interrupted between `build_chart` and `persist_insight_v2`:
**zero insights ship**, `agent_chart` rows orphaned. This is the Round 2
production failure.

### New (insight-first, Round 3)

```
Agent                MCP wrapper          persist_insight_v2     build_chart        DB
  | read_workspace ---->|                                                              |
  |<--- SCHEMA.md ------|                                                              |
  | query_database ---->| -------------------------------------------------------> run |
  |<--- rows -----------|                                                              |
  | emit_citation ----->|------------------------> agent_citation INSERT (unbound) --> |
  |<--- citation_id ----|                                                              |
  | persist_insight_v2->| validate session + citations (no chart guard)                |
  |    (chart_id=None)  | INSERT ai_insight (chart_id=NULL, version='v2') -----------> |
  |                     | UPDATE agent_citation SET insight_id=...                  -> |
  |<--- insight_id -----|                                                              |
  | build_chart -------->| validate encoding, gate+exec SQL                            |
  |  (insight_id=I)     | _resolve_insight(I)  ------------------------------------ -> |
  |                     | INSERT agent_chart (insight_id=I) in SAME xn   -----------> |
  |<--- chart_id -------|                                                              |
  |   (or chart_error -> insight already shipped, agent moves on)                      |
  | (loop x3)
  | finalize_session -->|
```

Failure mode if interrupted between `persist_insight_v2` and `build_chart`:
**insight ships chart-less**. Renderer paints headline + citations; chart slot
is empty. Acceptance (b) holds via the OR clause.

Failure mode if `build_chart` itself rejects (gate, empty, encoding):
identical — insight already in the DB, structured `tool_error` returned to the
loop, agent advances to the next hypothesis. No retry of persist.

---

## 8. Files touched (planned)

```
backend/agents/insights/prompts/synthesis_rules_v2.md   (Round 3: reorder workflow steps 3 and 4)
backend/agents/insights/tools/persist_insight_v2.py     (chart_id Required -> Optional)
backend/agents/insights/tools/build_chart.py            (+insight_id param, +_resolve_insight, FK at INSERT)
backend/agents/insights/tools/registry.py               (forward insight_id; map empty chart_id to None)
backend/mcp_server.py                                   (expose bind_insight_id on build_chart MCP wrapper)
backend/tests/test_v2_insights_e2e_regression.py        (+3 cases: insight-first happy, chart-fail-graceful, backcompat)
backend/tests/test_persist_insight_v2.py                (+chart_id None path)
backend/tests/test_build_chart_tool.py                  (+insight_id resolution, +session mismatch)
docs/ai_insights_v2_round3_ARCH.md                      (this document)
```

No frontend changes required if the renderer already left-joins `agent_chart`
by `insight_id`. R-A is the audit gate before merge.

---

## 9. Rollout

1. Land code + tests on a feature branch. Confirm `pytest -q backend/tests`
   stays at 399+ passing.
2. Live POST one v2 session. Verify `mcp.invoke_start name=persist_insight_v2`
   precedes `mcp.invoke_start name=build_chart` in the log.
3. Run the SQL acceptance block. Verify (a)-(d).
4. Inject a deliberate `build_chart` failure (e.g. encoding mismatch in a
   canned synthesis stream) on a smoke session. Verify the insight still ships
   and the structured tool_error reaches the agent.
5. Soak for 72 h. Watch for `v2_agent_skipped_chart_bind` and
   `v2_agent_skipped_persist` WARN frequency. Either should be near zero.
6. Decision point at end of soak: flip `CreateSessionBody.version` default
   from `"v1"` to `"v2"` (Follow-up F2 from Round 1).
