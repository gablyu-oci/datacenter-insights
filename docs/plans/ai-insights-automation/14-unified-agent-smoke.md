# Phase 2 Manual Smoke Runbook

Authoritative architecture: `docs/plans/ai-insights-automation/14-unified-agent-architecture.md` (esp. §11 test boundaries).

This runbook validates that Phase 2 (the agentic-synthesis lane via OpenClaw + MCP write-tools) works end-to-end against a live OpenClaw gateway and the in-process MCP mount. Run it after every Phase 2 deploy and before flipping `SYNTHESIS_MODE` from `legacy` to `agentic` in any new environment.

> Do NOT run this as part of automated CI. It depends on a live OpenClaw container plus model credentials.

---

## 1. Preconditions

Set the environment so the orchestrator picks the agentic lane and OpenClaw is reachable:

```bash
export OPENCLAW_ENABLED=1
export SYNTHESIS_MODE=agentic
export OPENCLAW_GATEWAY_URL="http://localhost:7474"
export OPENCLAW_GATEWAY_TOKEN="<gateway bearer>"
export AGENT_TOOLS_BEARER="<MCP bearer>"
```

Verify the two services are up:

```bash
curl -fsS "$OPENCLAW_GATEWAY_URL/healthz"     # OpenClaw on :7474
curl -fsS http://localhost:8002/healthz       # FastAPI parent on :8002
# MCP mount listens at :8002/mcp; smoke-check below.
curl -fsS -H "Authorization: Bearer $AGENT_TOOLS_BEARER" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  http://localhost:8002/mcp/ | jq '.result.tools | length'
# Expected: 10
```

If `tools | length` is not 10, halt: the MCP registry is missing Phase 2 write-tools.

---

## 2. Trigger a synthesis session

```bash
curl -fsS -X POST http://localhost:8002/api/insights/sessions \
     -H 'Content-Type: application/json' \
     -d '{}' \
     | jq .
```

Capture `session_id` from the response. The endpoint returns immediately and the SSE stream is consumed via `GET /api/insights/sessions/{id}/events` (or whichever streaming route the deployed build wires; see `routers/insights.py`).

---

## 3. Verify the SSE event sequence

Expected order on the SSE stream (event names, in order):

```
session_started
surveying        × N        # bootstrap survey, capped at 8
reasoning_step   × M        # agent thinking content
( insight_started -> chart -> insight_complete ) × 3
session_complete (status=complete)
```

Failure modes to flag (in this order of severity):

* `session_complete` not received -> client must surface a degraded close (timeout banner).
* `session_complete.budget_status == "clipped"` -> degraded run; check logs for `agentic_synthesis.outer_wall_timeout` or `tool_cap` reason.
* Fewer than 3 `insight_complete` events -> see STOP rule in section 6.

---

## 4. Verify ai_session row state

```sql
SELECT id, status, created_by, token_estimate, insights_emitted, finished_at, budget_status
FROM ai_session
WHERE id = '<session_id>';
```

Required:

* `created_by` = `"user"` (manual run).
* `status` = `"complete"`.
* `token_estimate` > 0 (populated by `finalize_session(token_estimate=...)`).
* `insights_emitted` = number of `persist_insight` calls observed on the wire (typically 3).
* `finished_at` is non-NULL.
* `budget_status` is `"ok"` (or `"clipped"` if degraded).

---

## 5. Verify ai_insight rows

```sql
SELECT id, idx, headline, supporting_row_ids
FROM ai_insight
WHERE session_id = '<session_id>'
ORDER BY idx;
```

Required:

* One row per `insight_complete` event from the SSE stream.
* `idx` is a contiguous 0-based sequence (`0, 1, 2, ...`).
* `supporting_row_ids` is non-empty (JSONB array). Hallucinated row_ids are filtered out server-side by the `persist_insight` MCP tool, so any value here is a real FactPack row.

If `supporting_row_ids IS NULL` for any row, halt: the FactPack-filter contract was violated.

---

## 6. STOP rule (regression gate)

If three consecutive smokes return fewer than 3 `insight_complete` events:

1. Halt smoke runs.
2. Open a regression note in `docs/plans/ai-insights-automation/14-unified-agent-architecture.md` §11 Test Evidence.
3. Capture: gateway version, model id, session_id of each failed run, OpenClaw access logs, and the first 200 lines of the SSE stream.
4. Do NOT roll forward; do NOT flip more environments to `SYNTHESIS_MODE=agentic` until the root cause is fixed.

The legacy V1 verify-loop is still wired and accessible via `SYNTHESIS_MODE=legacy` until Phase 5 deletes it; that is the immediate rollback.

---

## What this runbook does NOT cover

* Cron / scheduled mode (`mode="scheduled"`, sessionKey `daily-synthesis-YYYYMMDD-scheduled`). Add a separate runbook for the APScheduler path before Phase 4 GA.
* Weekly brief flow (`persist_brief`). Phase 4 work; today the tool returns `BRIEF_RUN_NOT_FOUND`.
* OpenClaw's own memory-store correctness. That is upstream's responsibility; we treat the gateway as a black box here.
