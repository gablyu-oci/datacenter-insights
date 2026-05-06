# 12 - OpenClaw Migration: Integration Test Plan & Smoke Runbook

**Status:** Active. Companion to PRD `11a` (acceptance criteria), ARCH `11b` §10 (test architecture), ADDENDUM `11c`, and DEPLOY `11`.
**Owner:** QA / Test Engineer.
**Date:** 2026-05-05.
**Predecessors:**
- `11a-openclaw-migration-prd.md` — AC1-AC11.
- `11b-openclaw-migration-architecture.md` §10 (test architecture).
- `11c-openclaw-migration-addendum.md` — bootstrap, session-key, override semantics.
- `11-openclaw-deployment.md` — gateway provisioning runbook (sidecar, env, ports).

**Scope.** This document is the manual smoke runbook the on-call engineer
walks through after a deploy / flag flip / OpenClaw upgrade. The unit test
counterpart lives in `backend/tests/test_agent_tools_router.py`,
`backend/tests/test_openclaw_forwarder.py`, and
`backend/tests/test_openclaw_persona_loaded.py`. The two together discharge
the AC1-AC11 contract.

**Out of scope.** Cron / synthesis path (PRD NG3). Multi-channel (NG1).
Slash commands (NG6).

---

## §1. Prereqs

Before running any smoke step:

1. **Gateway up.** Per `11-openclaw-deployment.md`, the OpenClaw sidecar
   must be running on `127.0.0.1:7474` (loopback, no TLS terminator).
   Verify with `curl -fsS http://127.0.0.1:7474/v1/health` (or equivalent
   per the deployment runbook).
2. **FastAPI running.** `uvicorn main:app --reload` against the dev
   Postgres. Confirm the chat router registered with
   `curl -fsS http://localhost:8000/api/health`.
3. **Flag on.** `OPENCLAW_ENABLED=1` in `backend/.env`. The dispatcher
   in `routers.insights.post_insight_chat` reads this at request time
   (no restart required), but a fresh shell is recommended.
4. **Secrets populated.** In `backend/.env`:
   - `AGENT_TOOLS_BEARER` — non-empty; the OpenClaw plugin layer
     presents this as `Authorization: Bearer <value>` to FastAPI.
   - `OPENCLAW_GATEWAY_TOKEN` — the token FastAPI presents to OpenClaw.
   - `LLAMA_STACK_API_KEY` — the OCI / Llama Stack key OpenClaw uses to
     reach `gpt-5.4`.
5. **Persona on disk.** `.openclaw/workspace/SOUL.md` exists and is
   non-empty. Unit-tested by `test_openclaw_persona_loaded.py`.
6. **DB seed.** A real insight UUID exists you can chat into. Get one
   with `psql -c "select id, headline from ai_insight order by created_at desc limit 1"`.
   Cache the UUID; every smoke step refers to it as `<INSIGHT_UUID>`.
7. **Browser tab.** AI Insights tab open at the chosen insight; the
   InsightChatDock visible. Devtools network tab open; filter by
   `chat`. The unit-test taxonomy (`assistant_message_token`,
   `tool_call_started`, `tool_call_complete`, `message_complete`,
   `error`) is what you should see on the EventStream lane.

---

## §2. Smoke 1 — Persona / identity check (AC4)

**Goal.** Confirm the OpenClaw agent boots with the persona from
`SOUL.md` and self-identifies as the Datacenter & Power Analyst.

**Steps.**
1. Open the chat dock on a fresh insight session (clear local-storage if
   needed so no prior turn primes the answer).
2. Send: `who are you?`
3. Observe the streamed response.

**Expected.**
- Reply names the role (e.g. `Datacenter & Power Analyst` or
  `Senior Datacenter and Power Analyst` per ARCH 11b §8).
- Voice: terse, two or three sentences, no corporate hedging
  ("happy to", "I would like to" must NOT appear).
- Mentions the scope (one insight at a time, Oracle / OCI).
- Total latency under p95 budget (~90s per NFR1).

**Pass criterion.** Reply matches the SOUL.md voice contract by eye-test.

**Fail handling.** If the agent uses a generic LLM voice, suspect the
persona didn't load. Check (a) gateway logs for `SOUL.md` loaded at
boot; (b) `.openclaw/workspace/SOUL.md` permissions; (c) the agent
config points at that workspace.

---

## §3. Smoke 2 — Memory across turns ("CO Bar Yes" check)

**Goal.** Acceptance check from the user's task spec — multi-turn memory
within the per-insight session (PRD AC5, R6, §4.3).

**Setup.**
- Pick an insight whose body or chart references the **CO Bar** energy
  project (or seed one: an `energy_projects` row with operator=Crusoe,
  project name containing "CO Bar"). The point is the agent should
  hypothesize a customer (e.g. xAI / Microsoft) and ask the user to
  confirm.

**Steps.**
1. **Turn 1.** Send: `What's the CO Bar customer?`
2. Observe the agent's response. It should either name a customer with
   a citation OR ask a clarifier ("are you asking about the offtake or
   the colo tenant?" / "did you see X confirm this?"). Either is OK —
   what we are testing is that **turn 2 carries the context.**
3. **Turn 2.** Send only: `Yes`
4. Observe the response.

**Expected.**
- Turn 2 resolves directly without re-asking the original question.
- The response either drills into the answer (if the agent had
  proposed a hypothesis) or executes whatever it offered to do.
- The `x-openclaw-session-key` header on both turns equals
  `agent:main:insight:<INSIGHT_UUID>` (R6).

**Pass criterion.** Turn 2 does not contain the literal phrase
"could you clarify" or "what do you mean by yes".

**Fail handling.** If the agent re-asks, the OpenClaw `sessionKey`
memory plumbing is broken. Diagnose:
- Verify both POSTs sent the same session-key header (browser network
  tab > request payload).
- `psql -c "select session_id, count(*) from agent_message where insight_id=<INSIGHT_UUID> group by 1"`
  — if multiple session_ids appear for the same insight, the forwarder
  is creating fresh sessions per turn (R6 violated).

---

## §4. Smoke 3 — Tool use round-trip (AC1, AC3)

**Goal.** Confirm OpenClaw -> FastAPI webhook -> Postgres path works
end-to-end and rows reach the LLM.

**Steps.**
1. **Turn 1.** Send: `what other Crusoe sites are there?`
2. While the response streams, watch:
   - The InsightChatDock for a tool-call chip labeled `query_database`.
   - FastAPI server logs for `POST /api/agent-tools/query_database`.
   - The `Authorization` header on that POST equals
     `Bearer <AGENT_TOOLS_BEARER>` (do NOT log the value, just
     verify it's present).
3. After the stream completes, query Postgres:
   ```sql
   SELECT id, role, content, tool_calls
   FROM agent_message
   WHERE insight_id = '<INSIGHT_UUID>'
   ORDER BY seq DESC
   LIMIT 4;
   ```

**Expected.**
- (a) Browser network tab shows an SSE event named
  `tool_call_started` with `tool_name="query_database"`, followed by
  `tool_call_complete` with `ok=true`.
- (b) FastAPI received the webhook with a valid bearer; the request
  body had `args.sql` containing a `SELECT ... FROM ... WHERE`
  filtered to Crusoe (case-insensitive).
- (c) The webhook returned `{"ok": true, "result": {...rows...}}`.
- (d) The final assistant turn's text mentions the rows the tool
  returned (site name, county, MW). Not "I don't know."
- (e) The assistant `agent_message` row has `tool_calls` JSONB
  populated with at least one entry whose `tool_name="query_database"`.

**Pass criterion.** All five sub-checks above hold.

**Fail handling.**
- 401 on the webhook -> bearer mismatch (env drift between OpenClaw
  and FastAPI). Rotate and redeploy.
- 422 -> envelope drift (OpenClaw plugin sending a payload that
  doesn't match `routers.agent_tools._ToolEnvelope`). Compare against
  `test_agent_tools_router.py::test_tool_success_envelope`.
- `ok=false` with `code=TOOL_FAILED` -> SQL gate or DB error. Inspect
  `error` field; cross-check `agents.insights.tools.sql_gate`.

---

## §5. Smoke 4 — Charts and citations still emit (AC7)

**Goal.** Confirm `emit_chart` and `emit_citation` keep the chart and
citation surface working through the OpenClaw lane.

**Steps.**
1. Send: `MW capacity by year for hyperscalers — chart it.`
2. Watch for `tool_call_started` event with `tool_name="emit_chart"`.
3. After the stream completes, verify in Postgres:
   ```sql
   SELECT id, insight_id, spec->>'title' AS title, data_source->>'kind' AS source
   FROM agent_chart
   WHERE insight_id = '<INSIGHT_UUID>'
   ORDER BY created_at DESC
   LIMIT 1;
   ```
4. In the InsightChatDock, scroll to where the chart should render
   inline.

**Expected.**
- A new `agent_chart` row landed.
- The chart renders inline in the dock with the title the agent chose,
  encoding axes match `MW` on Y, `year` on X.
- For an external claim, repeat with `look up the public press release
  on the latest Crusoe Stargate announcement and cite it`. Verify
  `emit_citation` fires; `agent_citation` row landed.

**Pass criterion.** The chart and citation each render in the dock and
are joinable from Postgres.

**Fail handling.** If the chart row is present but the dock does not
render it, the SSE `chart` event isn't being emitted by the forwarder
or the dock's `ChartEvent` handler is broken. Cross-check that the
forwarder eventually emits the `chart` event after `emit_chart` returns
ok (this is plugin-side; see ARCH 11b §4.6).

> **Known test gap (see §11).** The `chart` event today is emitted by
> the legacy lane through the in-process tool dispatcher. On the
> OpenClaw lane, it must be replayed from the webhook return value.
> The unit suite covers the agent-tools webhook envelope shape but
> NOT the OpenClaw plugin's emission of the SSE `chart` event. Smoke
> 4 is the only check that catches that drift.

---

## §6. Smoke 5 — Frontend regression (R5, AC1)

**Goal.** Confirm the InsightChatDock renders identically to the
legacy lane over a 3-turn multi-turn chat. R5 says zero on-the-wire
event-taxonomy diff.

**Steps.**
1. Start a fresh chat session. Conduct a 3-turn conversation that
   touches: a text-only turn, a `query_database` turn, and an
   `emit_chart` turn.
2. After each assistant turn, screenshot the dock state.
3. Repeat with `OPENCLAW_ENABLED=0` (Smoke 6) and screenshot the same
   sequence.
4. Compare side-by-side: token streaming behavior, tool-call chip
   shape and copy, chart card placement, citation pill style.

**Expected.**
- Visually identical (within minor model-text variation).
- No new "Powered by OpenClaw" affordances (PRD §4.1).
- No flicker / stuck spinner / orphaned tool-call chip.

**Pass criterion.** The screenshots line up.

**Fail handling.** Capture both sets of SSE event streams (browser
EventSource panel) and diff. Any new event names or any missing
`message_complete` terminators are bugs.

---

## §7. Smoke 6 — Rollback drill (AC9)

**Goal.** Confirm a flag flip restores the legacy `ToolLoopDriver`
lane in under 60 seconds with no redeploy.

**Steps.**
1. With OpenClaw enabled and a recent successful turn, edit
   `backend/.env`: `OPENCLAW_ENABLED=0`.
2. Restart FastAPI (or rely on the `Settings()` re-read if the deploy
   does config-reload — see PRD R-OC-7 caveat: rolling restart is
   safer).
3. Time the gap from flag-flip to first successful legacy-lane turn.
4. Repeat smoke 1, 2, 3 and verify the dock behaves identically.
5. Confirm zero traffic reached OpenClaw during step 4 (gateway logs).

**Expected.**
- Gap from flip to first legacy turn < 60s (AC9).
- `OPENCLAW_ENABLED` value logged at chat-handler entry (NFR3).
- Smoke 1/2/3 pass with the same answers.

**Pass criterion.** AC9 holds; legacy parity by eye-test.

**Fail handling.** If turns still hit OpenClaw, check (a) `Settings()`
field defaults; (b) worker count > 1 with stale env (PRD R-OC-7).
Rolling restart resolves both.

---

## §8. Smoke 7 — Resilience (R-OC-6)

**Goal.** A mid-stream OpenClaw crash surfaces an `error` SSE rather
than 500'ing the browser. Unit tested by
`test_openclaw_5xx_emits_error_event_not_500` for 5xx, this smoke
covers process-kill specifically.

**Steps.**
1. Start a chat turn that will produce a long stream (e.g. a chart
   request that takes >5s).
2. While streaming, kill the OpenClaw process (`docker kill <id>` or
   `pkill -9 openclaw`).
3. Observe the dock.
4. Restart the OpenClaw container.
5. Send another turn from the same insight session.

**Expected.**
- Step 3: the dock receives an `error` SSE event with code in
  `{openclaw_unavailable, openclaw_timeout, openclaw_error}` and
  re-renders as a failed turn (red chip / retry affordance — exact UX
  is out of this doc's scope).
- The HTTP response stays 200 (no 500); the assistant `agent_message`
  row may have `content=NULL` and partial `tool_calls`.
- Step 5: turn succeeds normally on the same `sessionKey`.

**Pass criterion.** No 500 reaches the browser; recovery is automatic.

**Fail handling.** If a 500 surfaces, the forwarder isn't catching the
exception class. Check `backend/openclaw/forwarder.py` `except`
clauses against `httpx.HTTPError` / `httpx.TimeoutException`.

---

## §9. Smoke 8 — Persistence audit (AC8)

**Goal.** Trace fidelity from Postgres alone (PRD R-OC-1 mitigation).
After 3 turns, the audit trail must be replayable.

**Steps.**
1. Fresh chat session. Conduct exactly 3 user turns, each with at
   least one tool call.
2. Run:
   ```sql
   SELECT m.seq, m.role, m.content IS NOT NULL AS has_content,
          jsonb_array_length(coalesce(m.tool_calls, '[]'::jsonb)) AS n_tools
   FROM agent_message m
   JOIN insight_thread t ON t.id = m.thread_id
   WHERE t.insight_id = '<INSIGHT_UUID>'
   ORDER BY m.seq;
   ```

**Expected.**
- Exactly 6 rows (3 user + 3 assistant), seq monotonically 1..6.
- All `role='user'` rows have `has_content=true`.
- At least 1 `role='assistant'` row has `n_tools >= 1` (the tool the
  agent used in that turn).
- Every row's `thread_id` is the same UUID; every row's `insight_id`
  is `<INSIGHT_UUID>`.

**Pass criterion.** Row count and shape match exactly.

**Fail handling.** Missing user rows -> the forwarder crashed before
the write-through (regression on `forward_chat` step 1). Missing
assistant rows -> step 4 persist crashed; check FastAPI logs for
`openclaw.forwarder.persist_failed`.

---

## §10. Per-Acceptance-Criterion mapping

Each AC from `11a-openclaw-migration-prd.md` is discharged by either a
unit test, a smoke step, or both.

| AC   | Description                              | Unit test                                                                | Smoke step       |
|------|------------------------------------------|--------------------------------------------------------------------------|------------------|
| AC1  | OpenClaw lane round-trip + `agent_message`| `test_openclaw_lane_streams_text_and_persists_messages` (forwarder)      | §4 Smoke 3       |
| AC2  | Legacy lane when flag=0                  | `test_openclaw_disabled_routes_to_legacy_handler` (forwarder)            | §7 Smoke 6       |
| AC3  | `query_database` SQL gate (both lanes)   | covered by existing `test_insights_sql_gate.py` (untouched here)         | §4 Smoke 3       |
| AC4  | Persona answers from SOUL.md             | `test_persona_signature_present`, `test_voice_rules_anchored` (persona)  | §2 Smoke 1       |
| AC5  | Per-insight scoping across turns         | `test_session_key_prefix_is_configurable` (forwarder; partial)           | §3 Smoke 2       |
| AC6  | Pre-loaded citations on first turn       | `test_insight_context_returns_build_chat_context_shape` (router)         | §5 Smoke 4       |
| AC7  | Charts as first-class artifacts          | `test_openclaw_lane_emits_tool_call_events` (forwarder; partial)         | §5 Smoke 4       |
| AC8  | Postgres-only trace replay               | `test_openclaw_lane_streams_text_and_persists_messages` (forwarder; seq)| §9 Smoke 8       |
| AC9  | Rollback < 60s                           | flag-flip behavior unit-tested via `test_openclaw_disabled_*`            | §7 Smoke 6 (timed)|
| AC10 | Synthesis pipeline unaffected            | covered by existing `test_runner_insights_daily.py` (no change required) | manual cron run  |
| AC11 | JSONL backup nightly                     | n/a — infra job                                                          | infra runbook    |

**Coverage notes.**
- **AC5 partial.** The forwarder unit test confirms the
  `x-openclaw-session-key` header has the right shape, but actual
  cross-turn memory is an OpenClaw runtime property; smoke §3 is the
  only end-to-end check.
- **AC7 partial.** The forwarder unit test exercises tool-call
  lifecycle events (`tool_call_started` / `tool_call_complete`) but
  not the eventual `chart` SSE event the dock renders. Smoke §5 is
  the only end-to-end check.
- **AC11.** The nightly JSONL backup job is infra (`11-openclaw-deployment.md`).
  No FastAPI surface to unit-test.

---

## §11. Pass / Fail criteria, and what to do when something fails

A smoke run is **pass** iff every section §2-§9 passes. A single fail
blocks the deploy / flag-flip and is filed as a defect with the
following template:

> **Defect.** \<title\>
> **Smoke step.** §X
> **AC mapping.** ACn
> **Expected.** \<copy from "Expected" block\>
> **Observed.** \<paste\>
> **Logs / SQL / screenshot.** \<links\>
> **Suspected component.** \<forwarder / agent_tools router / plugin / dock\>

### Known test gaps (file as future work)

These are deliberately not covered by the unit suite or this runbook;
they require hooks the backend doesn't currently expose. Filed here
per the QA constraint "do NOT modify backend code; flag gaps instead":

1. **`tests/test_v2_chat_isolation.py::test_tool_loop_driver_constructed_with_chat_caps`
   is failing on `main` after the OpenClaw migration landed.** With
   `settings.openclaw_enabled = 1` (the new default), the chat
   dispatcher routes through `_openclaw_chat_handler`, never
   constructing a `ToolLoopDriver`. The pre-existing test asserts the
   spy was called and pytest.fails when it wasn't. The fix is on the
   backend side: that test needs to monkeypatch
   `settings.openclaw_enabled = 0` (or `_legacy_chat_handler`) so it
   continues to exercise the legacy lane it was written for. Until
   then it is a **deterministic pre-existing failure** observable
   even before this QA scope was added. Do NOT mark it green by
   editing the assertion.

2. **OpenClaw plugin emits the `chart` SSE event.** The forwarder /
   sse_translator know how to translate `tool_call_*` events but the
   wire path that turns an `emit_chart` tool result into an SSE
   `chart` event lives in the OpenClaw plugin (TypeScript), which
   has no Python unit test. Today only smoke §5 catches a regression.
   Future work: contract test for the plugin.

3. **OpenClaw runtime memory across turns.** The forwarder test
   asserts the `sessionKey` header is correct; whether OpenClaw
   actually carries memory across two POSTs with the same key is a
   property of OpenClaw's session store, not of our code. Smoke §3
   is the only check.

4. **Citation pre-load on first turn (AC6 fully).** `_build_chat_context`
   returns the citation list (unit-asserted), and the OpenClaw plugin
   bootstrap (ADDENDUM 11c §G) is supposed to inject it as a
   per-request system-prompt override. The unit suite does not
   exercise the plugin's override-injection path. Future work: a
   smoke step that asserts the agent answers "list the citations" on
   turn 1 with no tool call (AC6).

5. **`AGENT_TOOLS_BEARER` rotation.** No unit test for hot-rotating
   the secret without a FastAPI restart. Today
   `routers.agent_tools._require_bearer` reads `os.environ` per
   request, so rotation should work as soon as both processes have
   the new value, but a dedicated runbook / test would harden this.

6. **Rollback timer (AC9).** The 60-second budget is asserted by
   stopwatch in smoke §7. No automation exists. Future work: an
   integration test that flips the flag and probes the next turn's
   path within a budget.

7. **JSONL <-> Postgres reconciliation drift (R-OC-3).** No nightly
   check exists today. PRD §R-OC-3 mitigation calls for a cron job
   that compares `(session_key, turn_count)` across the two stores.
   Future work.

If a smoke fails, **first** check if it is one of these known gaps —
if so, the failure may be expected. Otherwise file as above and block
the deploy.

---

## §12. Cleanup

After a smoke run:

1. **Rotate test secrets.** If `AGENT_TOOLS_BEARER` or
   `OPENCLAW_GATEWAY_TOKEN` were temporarily set to test values,
   rotate them back to the canonical secret-store values.
2. **Restore prod-default flag.** Per PRD §F2: "Defaults: 1 in dev,
   0 in prod". Confirm production `OPENCLAW_ENABLED` matches the
   target environment's policy.
3. **Drop test data.** If smoke runs created scratch insights /
   threads in dev Postgres, prune them:
   ```sql
   DELETE FROM agent_message WHERE thread_id IN (
     SELECT id FROM insight_thread WHERE insight_id IN ('<smoke_insight_1>', ...)
   );
   DELETE FROM insight_thread WHERE insight_id IN ('<smoke_insight_1>', ...);
   ```
4. **Archive screenshots.** Save §6 screenshots to the smoke-run
   ticket so future regressions have a baseline.
5. **Re-enable backups.** If the JSONL nightly backup was paused
   during smoke, re-enable per `11-openclaw-deployment.md`.

---

## Appendix A — Useful one-liners

```bash
# Watch the agent-tools router live
tail -f /var/log/sit/fastapi.log | grep "POST /api/agent-tools"

# Confirm the OpenClaw lane is in use
psql -c "SELECT count(*) FROM agent_message
         WHERE created_at > now() - interval '5 minutes'
         AND tool_calls IS NOT NULL"

# Probe persona is anchored
grep -c "Datacenter" .openclaw/workspace/SOUL.md
```

```python
# Quick replay-from-Postgres-only sanity check (AC8)
import psycopg, sys
ins_id = sys.argv[1]
with psycopg.connect("$DATABASE_URL") as cn:
    rows = cn.execute("""
      SELECT seq, role, content, tool_calls
      FROM agent_message
      WHERE insight_id = %s
      ORDER BY seq
    """, (ins_id,)).fetchall()
for seq, role, content, tools in rows:
    print(f"#{seq:02d} {role:9s} | content={'<text>' if content else 'NULL'} | "
          f"tools={len(tools or [])}")
```

---

*End of test plan.*
