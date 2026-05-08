# AI Insights v2 — Phase D Round 3 PRD: Insight-First Tool Reorder

**Date:** 2026-05-08
**Author:** PM (strategic-insights-tool)
**Status:** Draft, awaiting eng kickoff
**Predecessors:** [`ai_insights_v2_phase_d_v2_path_fix.md`](./ai_insights_v2_phase_d_v2_path_fix.md) (Rounds 1 + 2)
**Hard date constraints:** v1 default until 2026-05-21 soak ends; this PRD ships under that constraint.

---

## 1. Problem Statement

The v2 synthesis lane persists zero insights on live runs even though the agent is reliably calling tools. Rounds 1 and 2 fixed five compounding backend bugs and rewrote the system prompt to demand `persist_insight_v2` immediately after `build_chart`. Live data from 2026-05-07/08 shows the LLM still skips `persist_insight_v2` whenever it is the **trailing** step of the per-insight loop.

### Evidence summarised from prior rounds

| Source | Signal |
|---|---|
| Round 1 §"What was broken" | Five backend bugs (P1-P4 + C5) all repaired; v2 e2e test green; 396 backend tests passing. |
| Round 2 §"Symptom (after Round 1)" | Live session `6336fdfe-…`: 3 `agent_chart` rows, **0 `ai_insight` rows**, **0** `mcp.invoke_start` log lines for `persist_insight_v2`. Agent built three charts in a row and was force-finalised at the budget. |
| Round 2 H1 verdict | Prompt rewrite confirmed as the primary lever; the previous workflow used a single bullet ending in "Finally call persist_insight_v2". |
| Round 2 R2-A | Workflow rewritten to a numbered 5-step imperative with a "PERSIST IMMEDIATELY" pseudo-call template. |
| Live verification 2026-05-08 | The agent **still** drops `persist_insight_v2` when it is the last step in the loop, despite the stronger prompt. |

### Root cause (Round 3 reframing)

Trailing-imperative drop is a known failure mode for analyst-trained tool-calling LLMs. No amount of prompt strengthening reliably fixes it; the structural fix is to move the persistence step **earlier in the loop** so it sits in front of the long tail (chart, citations, narrative), where models are most reliable. Rounds 1+2 treated the symptom (prompt). Round 3 treats the cause (sequence shape).

---

## 2. New Design — Insight-First Tool Order

### 2.1 Old order (Round 2)

```
drill (query_database / search_documents)
  -> build_chart(sql, encoding) -> chart_id
  -> emit_citation(...)
  -> persist_insight_v2(chart_id, citations, headline, ...)   <-- DROPPED in live
  -> finalize_session
```

### 2.2 New order (Round 3)

```
drill (query_database / search_documents)
  -> emit_citation(...)                              # one or more
  -> persist_insight_v2(citations, headline, ...)    # NO chart_id; returns insight_id
  -> build_chart(insight_id, sql, encoding)          # binds chart to known insight
  -> next insight or finalize_session
```

### 2.3 Why it works

* **Persist becomes the early "I have an opinion + ground truth" step** — the natural moment after evidence is gathered. LLMs trained on analyst transcripts emit "save the finding" calls reliably at that moment.
* **`build_chart` becomes the visualization follow-up** to a known insight, matching the "summarise then chart" pattern dominant in analyst-tool training data.
* **Migration `018_ai_insights_v2_columns.py` already made `agent_chart.insight_id` nullable**, so chart-first legacy callers (v1 demo path, ad-hoc tools) keep working unchanged. The v2 default flips to insight-first; v1 byte-equivalent.
* **Failure isolation**: if `build_chart` fails (SQL error, encoding mismatch, OCI palette miss), the insight has already landed. We ship a degraded session with findings rather than a degraded session with charts and no findings.

---

## 3. Goals & Non-Goals

### 3.1 Functional goals

1. Every successful v2 session writes one `ai_insight` row per intended insight before any `agent_chart` row for that insight is attempted.
2. `persist_insight_v2` accepts a payload with no `chart_id` and writes a row that satisfies the existing `/api/insights/latest` schema contract.
3. `build_chart` accepts an optional `insight_id` and, when present, validates and binds the chart to that insight in the same session.
4. Frontend `/api/insights/latest` response shape is unchanged.
5. Live FastAPI verification on 2026-05-08 (or 2026-05-09 latest) confirms ≥3 `ai_insight` rows for a fresh v2 POST and ≥1 `persist_insight_v2.entered` INFO log line per insight.

### 3.2 Non-functional goals

1. v1 default path stays byte-equivalent. v1 prompts, v1 tools, v1 dispatch wrappers must not be touched.
2. No schema migration. `agent_chart.insight_id` is already nullable from migration 018.
3. Backend test suite stays ≥399 passing (Round 2 baseline). Round 3 adds at least 4 new tests, target ≥403 passing.
4. No frontend code changes required for the cutover. SSE event ordering changes are absorbed by `/api/insights/latest` being the source of truth.

### 3.3 Non-goals

1. Removing or hiding `build_chart`'s legacy chart-first path. Other callers depend on `chart_id` returns without an `insight_id`.
2. Switching the default `version` to `v2`. Soak ends 2026-05-21; this PRD respects that.
3. F4 (`agent_tool_call` audit trail), F7 (streaming nudge), F8 (precise tool-call counters). Out of scope; tracked as Round 2 follow-ups.
4. Any LLM model change.
5. Any change to `synthesis_rules.md` (v1).

---

## 4. Code Changes — three concrete edits + two wrapper updates

### 4.1 `backend/agents/insights/tools/persist_insight_v2.py`

* `chart_id`: change from required to `Optional[str] = None`.
* `citations`: stay required, `len(citations) >= 1`. Reject with `{ok: False, code: "citations_required"}` when empty.
* When `chart_id is None`, write the row with `chart_id = NULL` (column is already nullable from migration 018).
* When `chart_id` is provided (legacy chart-first callers), keep the current `_resolve_chart` validation path verbatim.
* Return value gains nothing new on the surface, but **`insight_id` is already in the response payload today** — confirm and leave as-is. The agent uses this to feed `build_chart`.
* Keep the `ai_insights.persist_insight_v2.entered` INFO log from Round 2 R2-B unchanged. It is the contract for live verification.

### 4.2 `backend/agents/insights/tools/build_chart.py`

* Add optional `insight_id: Optional[str] = None` to the input schema (registry + MCP tool schema both updated).
* Validation when `insight_id` is provided:
  1. `SELECT id, session_id FROM ai_insight WHERE id = :insight_id`.
  2. If no row, return `{ok: False, code: "insight_not_found", insight_id}`.
  3. If `ai_insight.session_id != ctx.session_id`, return `{ok: False, code: "insight_session_mismatch", expected: ctx.session_id, got: row.session_id}`.
  4. On success, write `agent_chart` with `insight_id` populated and return `{ok: True, chart_id, chart_spec, insight_id}`.
* When `insight_id` is `None` or empty string, **keep the existing chart-first behavior unchanged**: write `agent_chart` with `insight_id = NULL`, return `chart_id` as today.
* Preserve all current chart-spec, palette, and SQL-gate behaviour — Round 3 is a sequencing change, not a chart change.

### 4.3 `backend/agents/insights/prompts/synthesis_rules_v2.md`

Rewrite the **Workflow** section so the per-insight loop is:

```
## Workflow (follow in order)

1. Orient: read_workspace(file="SCHEMA.md"), then read_workspace(file="FRESHNESS.md").
   Once per session.
2. Drill: query_database and/or search_documents to test one hypothesis.
   Optional web_search for one corroborating source. Each external claim
   ends with emit_citation. Collect 1+ citations before step 3.
3. Persist the insight: call persist_insight_v2(headline=..., citations=[...],
   confidence=..., materiality=...). DO NOT pass chart_id. Capture the
   returned insight_id.
4. Chart it: call build_chart(insight_id="<from step 3>", sql=..., encoding=...).
   If build_chart fails, do NOT retry persist_insight_v2; the insight is
   already saved. Move on.
5. Repeat steps 2-4 for the next hypothesis until max_insights or evidence
   is exhausted, then call finalize_session.
```

Hard rule, in bold in the doc:

> The chart is graceful-degradation follow-up. It is **not** a precondition for persistence. If `build_chart` fails, the insight has already landed in the database; ship the degraded session and continue.

The existing `AI_INSIGHTS_PLAYBOOK.md` and `AI_INSIGHTS_PREFLIGHT_CHECKLIST.md` references stay. The 4,096-byte ceiling enforced by `test_agentic_synthesis_v2.py` must continue to pass.

### 4.4 `backend/agents/insights/tools/registry.py`

* Update the JSON tool schema for `build_chart` to include the new optional `insight_id` field (string, nullable, default null) with a one-line description: `"Bind this chart to an existing ai_insight row. Required for v2 insight-first flow."`.
* Update the JSON tool schema for `persist_insight_v2` so `chart_id` is no longer required; keep `citations` required and `minItems: 1`.
* No dispatch wiring changes — `dispatch()` already forwards `db` to both tools after Round 1 P3 fix.

### 4.5 `backend/mcp_server.py`

* The `@mcp.tool()` registrations for `build_chart` (line ~776) and `persist_insight_v2` (line ~821) advertise their argument shapes via the registry schema. Confirm the FastMCP wrapper re-reads the schema (or update the inline schema if it is duplicated). Verify with `tools/list` after change.
* No changes to `_invoke()` itself — the Round 1 P4 commit is still correct.
* Add one new INFO log inside `build_chart`'s wrapper (or inside the tool body) only when `insight_id` is provided: `ai_insights.build_chart.bound_to_insight` with `extra={session_id, insight_id, chart_id}`. This gives ops a one-line confirmation that the new path is live.

---

## 5. Acceptance Criteria (verbatim)

1. **(a)** `count(*) FROM ai_insight WHERE session_id=<sid> AND version='v2'` is in `[3,5]` for a fresh v2 POST with `max_insights=5`.
2. **(b)** Every v2 `ai_insight` row has at least one `agent_citation` row resolving to it (`citations_count >= 1`).
3. **(c)** Every v2 `ai_insight` row that has a chart has `agent_chart.insight_id = ai_insight.id`. Insights without a chart are permitted (graceful degradation) and have `chart_id IS NULL`.
4. **(d)** `count(*) FROM agent_chart WHERE session_id=<sid>` ≤ count from (a). (Equality is the happy path; less-than means at least one chart failed but its insight still landed.)
5. **(e)** v1 default path still produces 5–7 insights with bar charts. v1 SQL acceptance queries unchanged from Round 1.
6. **(f)** `/api/insights/latest` consumed by the existing frontend without code changes. Response schema byte-equivalent.
7. **(g)** Backend test suite ≥403 passing (Round 2 baseline 399 + ≥4 new tests). New tests must include: persist_insight_v2 accepts no chart_id; build_chart rejects insight_session_mismatch; build_chart rejects insight_not_found; v2 e2e regression updated for new sequence.
8. **(h)** Live FastAPI verification: a fresh v2 POST emits `ai_insights.persist_insight_v2.entered` ≥3× and `ai_insights.build_chart.bound_to_insight` ≥3× in the FastAPI stderr log within the session window.

---

## 6. User Stories

### 6.1 As an AI insights operator, I want every v2 insight to persist even when the chart fails so a degraded session still ships findings.

**Acceptance:** When `build_chart` returns `{ok: False}` for any reason after a successful `persist_insight_v2`, the corresponding `ai_insight` row is present, `chart_id IS NULL`, and the session terminal status reflects the chart failure separately (e.g. `degraded` if any chart failed, `complete` only when all succeeded). The agent does not retry `persist_insight_v2`.

### 6.2 As the v2 agent, I want a tool sequence aligned to how I emit calls so I don't drop the persist step.

**Acceptance:** `synthesis_rules_v2.md` Workflow lists `persist_insight_v2` as step 3 of 5 and `build_chart` as step 4. The persist step is in the leading-imperative position of the per-insight loop. The 4,096-byte ceiling is preserved.

### 6.3 As an on-call engineer, I want logs to confirm `persist_insight_v2.entered` fires per insight.

**Acceptance:** A live v2 POST with `max_insights=N` produces ≥`N` `ai_insights.persist_insight_v2.entered` INFO lines in FastAPI stderr, each with a distinct `session_id_hint` and incrementing `headline_len`. If the line count is `<N`, the on-call is empowered to declare an LLM-tier regression rather than a backend regression in one log glance.

### 6.4 As a frontend dev, I want `/api/insights/latest` schema unchanged.

**Acceptance:** The response payload for `/api/insights/latest` is byte-equivalent before and after Round 3 for both v1 and v2 sessions. SSE event ordering may differ (InsightStarted now precedes ChartBuilt) but the frontend treats `/api/insights/latest` as the source of truth and renders correctly without code changes. Verified with the existing Vitest snapshot for `AIInsightsTab.tsx`.

### 6.5 As the v1 demo owner, I want v1 default + v1 tools/prompts byte-equivalent.

**Acceptance:** `CreateSessionBody.version` default remains `"v1"`. `synthesis_rules.md` is unmodified. `persist_insight` (v1) and `emit_chart` (v1) registry/dispatch entries are unmodified. The Round 1 e2e test `test_v1_session_end_to_end_still_works` continues to pass without amendment.

---

## 7. Hard Constraints (verbatim from brief)

1. **No v1 removal.** Every v1 file, route, prompt, tool, schema, and test stays byte-equivalent unless explicitly itemised in §4.
2. **Default version stays v1.** `CreateSessionBody.version` default does not change in this round. The 2026-05-21 soak end gates the v2 default flip.
3. **Additive edits only.** No refactors, no renames, no v1-shape rewrites that could be perceived as cleanup. Each diff must be reviewable in isolation as "added behaviour, did not remove behaviour".
4. **Live FastAPI verification mandatory.** Unit tests pass is necessary but not sufficient. The PR description must include the stderr excerpt from a fresh v2 POST showing `persist_insight_v2.entered` ≥3× and the SQL acceptance block from Round 1 §"Acceptance-criteria status" filled in.

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Chart never built (LLM skips `build_chart` after persist) | Med | Low — insights still land | Graceful degradation by design. `ai_insight.chart_id` is nullable; `/api/insights/latest` already handles null charts (rendered as a headline-only card by Phase B/C frontend work). Frontend snapshot test confirms render path. |
| Legacy chart-first callers (v1 demo, ad-hoc Power tab triggers) regress | Low | High | Keep the `insight_id is None` branch in `build_chart` byte-equivalent. Add an explicit unit test `test_build_chart_legacy_chart_first_path_unchanged` that calls without `insight_id` and asserts the response shape and `agent_chart.insight_id IS NULL`. |
| SSE event ordering changes confuse the frontend | Low | Med | `InsightStarted` now fires before `ChartBuilt`. Frontend's `AIInsightsTab` already reconciles by `insight_id` and treats `/api/insights/latest` as canonical. No code change required, but a Vitest snapshot regen may be needed; track as a small follow-up if the snapshot diff appears. |
| `persist_insight_v2` schema change (chart_id Optional) breaks an existing caller passing `chart_id=""` | Low | Low | Treat empty string as None at the top of `persist_insight_v2` and `build_chart`. Existing v2 e2e test continues to pass; add one parametrised test for the empty-string case. |
| Prompt change pushes the agent past the 4,096-byte ceiling | Low | Med | `test_synthesis_rules_v2_prompt_length` already asserts the ceiling. Author the new Workflow to fit; if it doesn't, trim the AI_INSIGHTS_PLAYBOOK preamble (it duplicates content available via `read_workspace`). |
| Migration 018's nullable `agent_chart.insight_id` was not actually applied to the live DB | Very low | High | Pre-flight: `\d+ agent_chart` on the production DB and confirm `insight_id` column has `is_nullable = YES`. Block the cutover if not. |
| Round 3 doesn't fix the live skip (model is the bug, not the order) | Low | High | If post-deploy live verification shows `persist_insight_v2.entered = 0` again, declare an LLM-tier regression (not a backend regression) and revisit Round 2 F7 (streaming nudge). The R2-C diagnostic warning still fires and gives ops a one-line signal. |

---

## 9. Test Plan (high-level)

| Test | Layer | Asserts |
|---|---|---|
| `test_persist_insight_v2_accepts_no_chart_id` | unit | Returns `{ok: True, insight_id}`; row has `chart_id IS NULL`. |
| `test_persist_insight_v2_still_rejects_zero_citations` | unit | `{ok: False, code: "citations_required"}`. |
| `test_build_chart_with_insight_id_happy_path` | unit | Resolves insight, writes `agent_chart` with `insight_id` populated, returns `chart_id` and `insight_id`. |
| `test_build_chart_rejects_insight_not_found` | unit | `{ok: False, code: "insight_not_found"}`. |
| `test_build_chart_rejects_insight_session_mismatch` | unit | `{ok: False, code: "insight_session_mismatch"}`. |
| `test_build_chart_legacy_chart_first_path_unchanged` | unit | When `insight_id` is None or "", behaviour identical to today. |
| `test_synthesis_rules_v2_workflow_persist_is_step_3_of_5` | prompt-contract | Regex/string match; persist appears before chart in Workflow section. |
| `test_synthesis_rules_v2_under_4kib` | existing | Continues to pass. |
| `test_v2_e2e_regression_insight_first_sequence` | e2e (mocked OpenClaw) | Mocks an LLM stream that emits `persist_insight_v2` then `build_chart`; asserts (a)-(d) from acceptance. |
| `test_v1_session_end_to_end_still_works` | existing | Continues to pass byte-equivalent. |

Target: ≥403 passing (399 baseline + 4-6 new).

---

## 10. Rollout

1. PR merges to `main` behind the existing `version` flag (default still `v1`).
2. Live verification on staging FastAPI + staging Postgres + staging OpenClaw with one v2 POST and one v1 POST.
3. Operator captures the SQL acceptance block + stderr excerpt and pastes into the PR description.
4. If acceptance (a)-(h) pass, the PR is approved and merged. The v2 default flip remains gated on the 2026-05-21 soak.

---

## 11. Open Questions

1. Should `persist_insight_v2` accept an inline citation list and create `agent_citation` rows itself, or continue requiring the agent to call `emit_citation` separately first? (Today: separate. Round 3 keeps it separate to avoid scope creep, but step 2 of the Workflow becomes load-bearing.)
2. If `build_chart` fails after a successful persist, do we want a structured `degraded_charts` count surfaced on the session terminal payload? (Pre-existing F3 follow-up; tracked.)
3. Frontend currently renders an insight card without a chart as headline-only. Do we want a placeholder "chart unavailable" affordance for v2 graceful-degradation cases? (Out of scope; design ticket if needed.)
4. Does the `read_workspace` schema-orientation step (step 1) still need to be once-per-session, or can it be cached across sessions for the same workspace snapshot? (Out of scope; perf follow-up.)

---

## 12. Files Expected to Change

```
backend/agents/insights/tools/persist_insight_v2.py        (chart_id Optional)
backend/agents/insights/tools/build_chart.py               (insight_id Optional + validation)
backend/agents/insights/prompts/synthesis_rules_v2.md      (Workflow rewrite, persist=step 3)
backend/agents/insights/tools/registry.py                  (schema updates for both tools)
backend/mcp_server.py                                      (schema re-advert if duplicated; one new log)
backend/tests/test_persist_insight_v2.py                   (new cases)
backend/tests/test_build_chart_tool.py                     (new cases)
backend/tests/test_agentic_synthesis_v2.py                 (workflow assertion + ceiling)
backend/tests/test_v2_insights_e2e_regression.py           (insight-first e2e)
docs/ai_insights_v2_phase_d_round3_prd.md                  (this file)
```

No frontend changes. No alembic migration. No v1 file changes.
