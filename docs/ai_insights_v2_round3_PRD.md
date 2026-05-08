# AI Insights v2 path — Round 3 PRD: insight-first reorder

**Date:** 2026-05-08
**Status:** Proposed. Follows Rounds 1 + 2 in
[`ai_insights_v2_phase_d_v2_path_fix.md`](./ai_insights_v2_phase_d_v2_path_fix.md).
**Owner (this round):** PM, then handed to backend.

---

## Problem

After Rounds 1 and 2, live `POST /api/insights/sessions {"version":"v2"}`
runs still terminate with `status='degraded'` and zero `ai_insight` rows
even though `agent_chart` rows commit cleanly. The Round 1 entry-log
(`mcp.invoke_start name="build_chart"`) fires repeatedly, but
`ai_insights.persist_insight_v2.entered` (Round 2) does not. The
diagnostic `ai_insights.v2_agent_skipped_persist` confirms the failure
mode: the agent reliably emits `build_chart` and never emits
`persist_insight_v2`. The chart-first 5-step workflow puts the
high-value, low-cost step (persist) AFTER the optional, expensive step
(chart) — and the LLM consistently drops the trailing imperative. No
amount of prompt strengthening on a chart-first ordering has changed
this in production.

## Goal

Round 3 inverts the workflow so the agent persists the insight FIRST,
without a chart_id, and then calls `build_chart` with the freshly
minted `insight_id` to bind the chart back. Persistence must precede
chart construction so the high-value step happens unconditionally; if
`build_chart` fails or is skipped, the insight still ships (charts
become a follow-up enrichment, not a precondition). This requires
relaxing two tool signatures (`chart_id` becomes optional on
`persist_insight_v2`, `insight_id` becomes optional on `build_chart`)
plus a prompt rewrite to match. v1 default lane stays untouched.

## Non-goals

- No changes to v1 tools, v1 prompt, or v1 control flow.
- No flip of `CreateSessionBody.version` default (stays `"v1"`
  through the soak window).
- No frontend or UI changes. `/api/insights/latest` shape unchanged;
  `chart_id` may now be null on a v2 insight and the existing
  ProvenanceFooter / SourcePill must already tolerate that.
- v1 tools (`persist_insight`, `emit_chart`, `get_chart_data`) are
  not removed, deprecated, or renamed.
- No new tools introduced. Round 3 is a reorder + signature
  relaxation, not a surface change.
- No streaming-nudge mechanism (deferred F7 in Round 2 follow-ups).

## User stories

1. **As an analyst running a v2 session,** I want every successful
   `build_chart` to be bound to a real `ai_insight` row so my
   dashboards never show orphan charts and every chart I see has
   provenance behind it.
2. **As an on-call engineer,** I want
   `ai_insights.persist_insight_v2.entered` log lines to fire at
   least once per intended insight so I can verify agent compliance
   from a single `tail -f` without cross-referencing
   `agent_chart` counts.
3. **As a backend developer,** I want `chart_id` to be optional on
   `persist_insight_v2` and `insight_id` to be optional on
   `build_chart` so the agent can call them in either order during
   the v1→v2 soak — and so a `build_chart` failure cannot block an
   insight from shipping.
4. **As a v1 user on the default lane,** I want a v1 session with
   default body to still produce 5–7 v1 insights with bar charts,
   byte-equivalent to pre-Round-3 output.
5. **As a future on-call engineer,** I want the
   `ai_insights.v2_agent_skipped_persist` warning to keep its current
   semantics so a regression to chart-first behaviour surfaces in one
   log line.

## Acceptance criteria

(Verbatim from request.)

a. A live `POST /api/insights/sessions {"version":"v2","max_insights":5}`
   produces 3–5 `ai_insight` rows with `version='v2'`, every row has
   at least one resolved `agent_citation`, and at least the majority
   (≥ ceil(N/2)) have a non-null `chart_id`.
b. `ai_insights.persist_insight_v2.entered` INFO log fires ≥ 1× per
   persisted insight, BEFORE any `build_chart` call for that insight.
c. `persist_insight_v2(chart_id=None, …)` succeeds end-to-end and
   returns a real `insight_id`.
d. `build_chart(insight_id="<from c>", …)` succeeds and the returned
   `chart_id` is written to `ai_insight.chart_id` for that row.
e. v1 default-body session still produces 5–7 v1 insights with bar
   charts; backend test suite stays ≥ 399 passing (Round 2 baseline)
   and adds focused regression tests for the new ordering.
f. The diagnostic `ai_insights.v2_agent_skipped_persist` is NOT
   emitted on a clean Round 3 v2 session.
g. The MCP `tools/list` count and registry surface are unchanged
   (still 16 tools); only the JSON schemas for `persist_insight_v2`
   and `build_chart` change to mark the cross-reference field
   optional.

## Hard constraints

(Verbatim from request.)

- Do not remove v1 tools (`persist_insight`, `emit_chart`,
  `get_chart_data`) from the registry or MCP surface.
- Do not change `CreateSessionBody.version` default from `'v1'`.
- Changes must be additive / low-risk only — no schema migrations,
  no breaking changes to existing tool envelopes, no edits to v1
  prompt or v1 dispatch wrappers.
- MUST be verified against a live v2 session against the production
  FastAPI + OpenClaw + Postgres stack before Round 3 is declared
  complete. Unit tests are necessary but not sufficient.

## Open questions / follow-ups

1. **Late-binding column semantics.** When `persist_insight_v2`
   commits with `chart_id=None`, what is the read-side contract for
   `/api/insights/latest`? Confirm the existing serializer returns
   `chart_id: null` rather than 404 / dropping the row, and confirm
   `ProvenanceFooter` renders a citation-only insight without
   layout breakage.
2. **Backfill on `build_chart` success.** Round 3 expects
   `build_chart(insight_id=...)` to UPDATE `ai_insight.chart_id`.
   Decide whether that update happens inside `build_chart`'s own
   transaction (single commit, simpler) or via a separate registry
   helper (matches Round 1's MCP commit pattern more closely). The
   former is preferred unless it introduces a new lock pattern.
2a. **Failure mode if the chart binds to the wrong insight.** Should
    `build_chart` validate that `insight_id` belongs to the same
    session as `ctx.session_id` before updating? Recommend yes,
    return `{ok: False, code: "insight_session_mismatch"}` on
    cross-session binding attempts.
3. **Idempotency on retry.** If the agent calls `build_chart` twice
   for the same `insight_id`, is the second call an UPDATE
   (overwrite) or a no-op (`chart_already_bound`)? Current Round 2
   behaviour is "create a new chart row each time"; Round 3 should
   pick one and document it.
4. **Force-finalise diagnostic update.** Round 2's
   `ai_insights.v2_agent_skipped_persist` warning fires on
   `agent_chart_count >= 1 AND ai_insight db_count == 0`. Under
   Round 3 the inverse symptom (`ai_insight count >= 1 AND
   agent_chart count == 0`) becomes possible and benign. Decide
   whether to add a complementary INFO line
   `ai_insights.v2_persisted_without_chart` for ops visibility, or
   leave silent.
5. **Prompt-tier verification.** The Round 2 retro showed that
   prompt changes alone moved the needle only partially. Round 3's
   prompt is already insert-first in `synthesis_rules_v2.md`; verify
   the round-trip equality test in
   `test_agentic_synthesis_v2.py` still asserts the file's bytes,
   and add a positive-string assertion that "PERSIST FIRST" appears
   before "build_chart" in the workflow numbering.
6. **F7 reconsidered.** If a live Round 3 session still skips persist
   despite insight-first ordering (low-probability — persist is now
   the FIRST imperative after drill), the streaming-nudge mechanism
   (Round 2 F7) becomes the next escalation. Round 3 does not
   implement it but should not make it harder.
7. **Documentation cleanup.** Update
   `AI_INSIGHTS_PLAYBOOK.md` and `AI_INSIGHTS_PREFLIGHT_CHECKLIST.md`
   so any chart-first language is replaced with the insight-first
   contract — these files are loaded into the workspace and read by
   the agent before the synthesis prompt.
8. **Soak-window exit.** Re-confirm that the 2026-05-21 soak end-date
   for the `version="v1"` default is still the target. Round 3
   should land well inside the soak so live v2 traffic stays opt-in
   while the inversion is observed.

---

## Files expected to change (informational, not authoritative)

```
backend/agents/insights/prompts/synthesis_rules_v2.md       (workflow re-numbered persist-first)
backend/agents/insights/tools/persist_insight_v2.py          (chart_id Optional; relax schema)
backend/agents/insights/tools/build_chart.py                 (insight_id Optional; UPDATE ai_insight.chart_id on bind)
backend/agents/insights/tools/registry.py                    (schema export updates only)
backend/agents/insights/agentic_synthesis.py                 (force-finalise diagnostic copy if Q4 yes)
backend/tests/test_v2_insights_e2e_regression.py             (new ordering assertions)
backend/tests/test_persist_insight_v2.py                     (chart_id=None path)
backend/tests/test_build_chart_tool.py                       (insight_id provided path + late bind)
.openclaw/workspace/AI_INSIGHTS_PLAYBOOK.md                  (Q7)
.openclaw/workspace/AI_INSIGHTS_PREFLIGHT_CHECKLIST.md       (Q7)
docs/ai_insights_v2_phase_d_v2_path_fix.md                   (append Round 3 section after merge)
```

No migrations. No v1 file in the list.
