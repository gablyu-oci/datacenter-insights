# PRD: MCP Tool-Routing Migration (sub-PRD of 11a)

**Status:** Active. Sub-PRD of `11a-openclaw-migration-prd.md`. Replaces the TypeScript-plugin tool-routing layer described in `11b §3-§4` and `11c §G` with a native Python MCP (Model Context Protocol) server mounted on the existing FastAPI process. Inherits all goals, NFRs, risks, and open questions from 11a unless explicitly overridden here.
**Owner:** PM (strategic-insights-tool)
**Primary stakeholder:** Karan
**Date:** 2026-05-06
**Predecessors:**
- `11a-openclaw-migration-prd.md` — chat-runtime PRD (R1-R9, OpenClaw lane). This sub-PRD is its tool-routing implementation.
- `11b-openclaw-migration-architecture.md` — **SUPERSEDED for the tool layer.** The TS-plugin design in §3 (FastAPI agent-tools router) and §4 (TypeScript plugins) is abandoned in favor of MCP. The forwarder (§5), SOUL.md (§8), feature flag (§7), and dual-store (§6) survive unchanged.
- `11c-openclaw-migration-addendum.md` — researcher reconciliation. The TS extension layer in §G is the artifact being replaced; the Docker (§A), REST API (§B), sessionKey (§C), agent (§D), SOUL.md location (§E), and provider config (§F) decisions stand.

---

## 1. Overview

The OpenClaw lane (11a) routes chat tool calls from the gateway back to FastAPI. 11b/11c specified that routing as a TypeScript extension under `.openclaw/extensions/insights-tools/` calling a Python `agent_tools` router via bearer-protected webhooks. That extension was scaffolded but never compiled, never loaded by the gateway, and is unused — chat turns currently produce assistant text like "I cannot access the platform Postgres" because no tool surface is registered with OpenClaw.

This sub-PRD migrates the tool surface to a **native Python MCP server** mounted on the same FastAPI process at `/mcp`, using the official `mcp` Python SDK with streamable-HTTP transport and bearer auth. The seven existing chat-tool implementations stay in Python and are exposed as MCP tools. The OpenClaw gateway is reconfigured to discover tools via MCP instead of the abandoned TS extension.

Everything else from 11a is unchanged: the synthesis pipeline is untouched (NG3), `SOUL.md` and the per-request grounding pattern are untouched (F4), the dual-store write-through is untouched (F6), the SSE event taxonomy is unchanged (F7), and the legacy `ToolLoopDriver` path remains the rollback target (F2 / R9).

---

## 2. Goals & Non-Goals

### 2.1 Goals

- **G1.** Replace the abandoned TS plugin layer with a single Python MCP server such that an OpenClaw-lane chat turn invokes the seven Python tool implementations directly via MCP and the assistant cites real DB rows (no more "I cannot access the platform Postgres").
- **G2.** Mount the MCP server in the same FastAPI process at `/mcp` over streamable-HTTP transport with bearer auth, so there is no extra container, sidecar, or build step.
- **G3.** Keep the seven tool **implementations** load-bearing in Python only. No TypeScript to compile, no node dependencies, no extension auto-discovery on the gateway side.
- **G4.** Preserve rollback: with `OPENCLAW_ENABLED=0` the legacy `ToolLoopDriver` path is bit-for-bit unchanged and never touches the MCP server.
- **G5.** Delete the unused `.openclaw/extensions/insights-tools/` scaffold so the repo reflects the chosen architecture.

### 2.2 Non-Goals

- **NG1.** No changes to the synthesis pipeline (cron, FactPack, mega-call, dedup). MCP is chat-only, mirroring 11a NG3.
- **NG2.** No changes to the persona, `SOUL.md` content, or its on-disk location (11c §E).
- **NG3.** No changes to the legacy `ToolLoopDriver` codepath, the seven tool function bodies under `backend/agents/insights/tools/`, or `sql_gate.validate_sql`.
- **NG4.** No new database schema. `agent_message`, `agent_tool_call`, `agent_chart`, `agent_citation`, `insight_thread` are unchanged.
- **NG5.** No frontend changes. `InsightChatDock.tsx`, the SSE event taxonomy, and the on-the-wire event names are unchanged.
- **NG6.** No new MCP tools beyond the existing seven. Tool surface is fixed.
- **NG7.** No support for MCP transports other than streamable-HTTP. No stdio, no SSE-only, no WebSocket.
- **NG8.** No public exposure. The `/mcp` mount is bearer-protected and intended for the co-located OpenClaw gateway only.

---

## 3. User Stories

All stories are scoped to Karan (single analyst) plus the operator/engineer personas implied by the rollout.

### 3.1 Real tool calls in the OpenClaw lane

> **As Karan, when `OPENCLAW_ENABLED=1`, my chat turns invoke real Python tools via MCP and the assistant cites real DB rows — not "I cannot access the platform Postgres".**

- Acceptance: a turn that asks "what other Crusoe sites?" results in a `query_database` MCP tool invocation, rows return, the dock renders a `tool_call_complete` chip, and the assistant's text references concrete row values. An `agent_tool_call` row lands in Postgres with `ok=true`.

### 3.2 No extra container

> **As an operator, the MCP server is bearer-protected and runs in the same FastAPI process so there's no extra container to manage.**

- Acceptance: `/mcp` is reachable on the same host:port as the rest of the FastAPI app; an unauthenticated request returns 401; `docker ps` shows only the existing FastAPI and OpenClaw gateway processes (no new MCP sidecar).

### 3.3 Python-only tool surface

> **As an engineer, the seven tool implementations live ONLY in Python — there is no TypeScript to compile, no node toolchain, no extension auto-discovery on the gateway side.**

- Acceptance: `git grep -l "insights-tools"` returns no `.ts` files after the migration. `package.json` and `tsconfig.json` under `.openclaw/extensions/insights-tools/` no longer exist. `backend/mcp_server.py` is the single declaration site for the seven tools' MCP signatures, each delegating into the unchanged tool functions.

### 3.4 Rollback still works

> **As an engineer, rollback to the legacy `ToolLoopDriver` path still works when `OPENCLAW_ENABLED=0`.**

- Acceptance: with the flag off, a chat turn never reaches `/mcp`. The `ToolLoopDriver` path executes in-process as it did pre-11a, with identical SSE events and identical Postgres writes. Verified by an absent-from-access-log assertion on `/mcp` during a flag-off test.

### 3.5 Operator (informational)

- The bearer for `/mcp` is the same secret today's `agent_tools` design used (`AGENT_TOOLS_BEARER`); we do not introduce a new secret.
- The OpenClaw gateway's `openclaw.json` points at `http://host.docker.internal:8000/mcp` (Linux Docker bridge networking) per 11c §J.

---

## 4. Functional Requirements

The user-supplied requirements R1-R8 from the orchestrator brief map 1:1 to F-items below.

### F1. Add the `mcp` Python SDK (R1)

Add `mcp` (the official Anthropic Python MCP SDK) to `backend/requirements.txt`. Pin a known-good version. No other new top-level dependencies.

### F2. Build `backend/mcp_server.py` (R2)

A single Python module that:
- Instantiates an MCP server.
- Registers seven tools matching the 11a/11b roster: `query_database`, `call_api`, `get_chart_data`, `web_search`, `run_skill`, `emit_chart`, `emit_citation`.
- Each tool's MCP `parameters` schema mirrors the JSON schema documented in 11b §4.3-§4.7.
- Each tool's handler resolves a `SkillContext` (from MCP request metadata: `session_key`, `insight_id`, `thread_id`) and delegates into the existing function under `backend/agents/insights/tools/<tool_name>.py`. Tool function bodies are not edited (NG3).
- On exception, the handler returns the same `{error, code: "TOOL_FAILED"}` envelope the abandoned router was specified to return (11b §3.3) so OpenClaw-side parsing is uniform.
- `sql_gate.validate_sql` continues to run inside the `query_database` handler — MCP never sees raw SQL bypassed.

### F3. Mount on FastAPI at `/mcp` via streamable-HTTP transport with bearer auth (R3)

In `backend/main.py`, mount the MCP server's ASGI/FastAPI sub-app at path `/mcp`. The mount is wrapped by a bearer-auth dependency that compares against `AGENT_TOOLS_BEARER` (existing env var; same secret OpenClaw plugins were already configured to present). Loopback / bridge-network bind only; not publicly routed.

### F4. Update `.openclaw/openclaw.json` to point at the MCP server (R4)

The provider/tool-server section of `.openclaw/openclaw.json` (the JSON5 config in 11c §F) gains an MCP server entry referencing `http://host.docker.internal:8000/mcp` with the `AGENT_TOOLS_BEARER` token. The existing Llama Stack provider block, gateway auth block, and SOUL.md discovery (workspace-rooted per 11c §E) are unchanged.

### F5. Tests (R5)

New pytest module `backend/tests/test_mcp_server.py` covering, at minimum:
- **Bearer enforcement.** Missing header → 401. Wrong token → 401. Unset env var → 503 (fail-closed).
- **Tool registration.** The MCP `list_tools` reply enumerates exactly the seven tool names and their schemas match the 11b table.
- **Per-tool happy path.** Each of the seven tools invoked via the MCP client returns the same dict shape its underlying Python function returns today (mock the underlying tool module bodies so DB / Brave / external systems are not touched).
- **Exception envelope.** A tool that raises returns `{error, code: "TOOL_FAILED"}` over MCP, not an HTTP 5xx.
- **`sql_gate` enforcement.** A `query_database` call with a non-SELECT statement is rejected with the existing gate error message.

### F6. Live smoke against running gateway (R6)

A scripted smoke test (or documented manual runbook step) that, against a live FastAPI on `localhost:8000` with `OPENCLAW_ENABLED=1` and the OpenClaw gateway running on `localhost:7474`:
- Posts one chat turn that should provoke a `query_database` call.
- Asserts the gateway log shows an MCP tool invocation.
- Asserts the dock-side SSE stream emits `tool_call_started` and `tool_call_complete` for `query_database`.
- Asserts an `agent_tool_call` row lands in Postgres.

### F7. Remove the unused TS scaffold (R7)

Delete the `.openclaw/extensions/insights-tools/` directory and any references to it from `openclaw.json`, docs, or runbooks. Update `11b` and `11c` references in any new doc to call out that §G's TS layer is replaced by the MCP server.

### F8. ADR-style doc (R8)

Author `docs/plans/ai-insights-automation/13-mcp-migration.md` (architecture / decision record) capturing: why MCP over the TS plugin layer, the `/mcp` mount design, the bearer model, the streamable-HTTP transport choice, and the rollback contract. Cross-link from this PRD.

---

## 5. Non-Functional Requirements

NFR1-NFR5 from 11a §6 carry over verbatim. Sub-PRD-specific addenda:

- **NFR-MCP-1. Latency.** An MCP tool round-trip (gateway → `/mcp` → tool body → reply) on loopback / bridge-network must be no slower than the abandoned TS-plugin → `/api/agent-tools/<name>` design would have been. The in-process function call is now traversed via MCP framing instead of TS-fetch + FastAPI router; net change is expected within ±10ms.
- **NFR-MCP-2. Single process.** The MCP server runs in the FastAPI worker. No new systemd unit, no new container.
- **NFR-MCP-3. Auth surface.** `AGENT_TOOLS_BEARER` is the only secret consulted by `/mcp`. No additional credentials.

---

## 6. Acceptance Criteria

Each row mirrors the orchestrator's ACCEPTANCE list and is independently testable.

### AC1. `mcp` SDK is a declared dependency

- `backend/requirements.txt` lists `mcp` at a pinned version. `pip install -r backend/requirements.txt` in a clean venv succeeds.

### AC2. `backend/mcp_server.py` exposes exactly seven MCP tools

- An `mcp list_tools` against the running server returns the seven names: `query_database`, `call_api`, `get_chart_data`, `web_search`, `run_skill`, `emit_chart`, `emit_citation`. No others.
- Each tool's parameter schema matches the 11b §4 schema rows.

### AC3. `/mcp` is mounted on FastAPI with bearer auth

- A request to `/mcp` without `Authorization: Bearer <AGENT_TOOLS_BEARER>` returns 401.
- A request with the correct bearer succeeds.
- `AGENT_TOOLS_BEARER` unset → 503.

### AC4. `.openclaw/openclaw.json` references the MCP server

- The JSON5 config contains an MCP server block pointing at `http://host.docker.internal:8000/mcp` with the bearer token sourced from env.
- Booting the OpenClaw gateway with this config produces a log line confirming MCP tool discovery returned seven tools.

### AC5. Tests pass

- `pytest backend/tests/test_mcp_server.py` is green and exercises F5's five cases.
- Existing test suites (`test_openclaw_forwarder.py`, `test_openclaw_persona_loaded.py`, legacy chat tests) continue to pass unchanged.

### AC6. Live smoke against `localhost:7474` succeeds

- With `OPENCLAW_ENABLED=1` and the gateway up on `localhost:7474`, a chat turn that asks "what other Crusoe sites?" produces:
  - a gateway log line for an MCP `query_database` call,
  - a `tool_call_started` and a `tool_call_complete` SSE event in the dock stream,
  - real DB rows in the assistant's reply (no "I cannot access the platform Postgres" string),
  - an `agent_tool_call` Postgres row with `ok=true`.

### AC7. The TS scaffold is gone

- `.openclaw/extensions/insights-tools/` does not exist on disk.
- `git grep -l "insights-tools"` shows no remaining references in source code or active config (docs may reference it historically).

### AC8. Rollback path is unaffected

- With `OPENCLAW_ENABLED=0`, a chat turn flows through `ToolLoopDriver`. Access logs show zero `/mcp` traffic during the turn. SSE events and Postgres writes are identical to pre-11a behavior.

### AC9. ADR doc lands

- `docs/plans/ai-insights-automation/13-mcp-migration.md` exists, records the decision, and is cross-linked from this PRD's References section.

---

## 7. Out of Scope

Mirrors §2.2 plus the explicit non-goals from the orchestrator:

- No changes to the synthesis pipeline, persona text, `SOUL.md`, or the legacy `ToolLoopDriver` path.
- No new database schema or new Postgres tables/columns.
- No frontend changes (no edits to `InsightChatDock.tsx`, no new SSE events).
- No new tool implementations and no expansion of the seven-tool surface.
- No MCP transports other than streamable-HTTP.
- No public exposure of `/mcp`; loopback / bridge-network only.
- No new secrets; reuse `AGENT_TOOLS_BEARER`.
- No ClawHub marketplace, slash-command UI, or multi-channel adapters (already excluded by 11a NG1, NG5, NG6).

---

## 8. Risks

R-OC-1 through R-OC-7 from 11a §9 still apply. Sub-PRD-specific risks:

### R-MCP-1. MCP SDK churn

The Python `mcp` SDK is young and may ship breaking changes between minor versions.
**Mitigation:** pin the SDK version in `requirements.txt`; CI smoke runs F6's live test on every PR touching `backend/mcp_server.py`.

### R-MCP-2. Streamable-HTTP transport gaps in OpenClaw

OpenClaw's MCP-client side may not fully implement streamable-HTTP semantics that the SDK assumes.
**Mitigation:** AC4 includes a boot-time discovery assertion; if discovery fails, the addendum/ADR documents the workaround (likely transport-shape negotiation or an SDK pin at a known-compatible version).

### R-MCP-3. Bearer leakage via shared secret

`AGENT_TOOLS_BEARER` is now consulted by both the (deleted) old router design and the new MCP mount. Re-using the secret keeps surface small but a leak compromises both paths.
**Mitigation:** loopback / bridge-network bind only; rotate quarterly; never log the bearer value.

### R-MCP-4. Tool-call context plumbing

MCP requests carry tool args but not necessarily our `session_key` / `insight_id` / `thread_id` triplet. If the gateway-side hook from 11c §G that stuffed those into request metadata was the only carrier, the MCP path needs an equivalent.
**Mitigation:** carry the triplet via MCP `meta` / per-request headers set by the OpenClaw MCP client config; document the field name in the ADR; the `insight_context_preload` `agent:bootstrap` hook still front-loads the context bundle so tools can also extract `insight_id` from the `sessionKey` string as a fallback.

---

## 9. Success Metrics

- **Primary:** Karan opens an insight chat dock with `OPENCLAW_ENABLED=1` and gets a response that cites a concrete DB row on the first prompt that warrants `query_database`. The "I cannot access the platform Postgres" string is absent from the next 10 consecutive turns.
- **Reliability:** ≥ 99% of MCP tool invocations from the gateway succeed (HTTP 200 + valid MCP envelope) over a rolling 7-day window.
- **Latency:** p95 MCP tool round-trip ≤ 200 ms on loopback / bridge-network for non-DB tools; ≤ 1.5 s for `query_database` (DB-bound, matches today's in-process baseline + framing overhead).
- **Surface reduction:** the deleted TS scaffold (~1500 lines across 11+ files) is no longer in `git ls-files`.
- **Rollback drilled:** at least one `OPENCLAW_ENABLED=0` flip during the rollout window flows through `ToolLoopDriver` cleanly.

---

## 10. Rollout Plan (informational)

Three phases, each independently shippable behind `OPENCLAW_ENABLED=0`.

1. **Phase A — MCP server in process.** Add the SDK, build `backend/mcp_server.py`, mount on `/mcp` with bearer auth, ship F5 unit tests. Flag stays off; no behavior change for users.
2. **Phase B — Gateway points at MCP.** Update `.openclaw/openclaw.json`, restart the gateway, verify discovery (AC4), run the F6 smoke. Flip `OPENCLAW_ENABLED=1` in dev.
3. **Phase C — Cleanup.** Delete `.openclaw/extensions/insights-tools/`, land `13-mcp-migration.md`, close out documentation references.

Acceptance subset per phase: A → AC1, AC2, AC3, AC5; B → AC4, AC6; C → AC7, AC9. AC8 is exercised continuously across all three phases.

---

## 11. Open Questions

OQ1-OQ7 from 11a §10 still apply. Sub-PRD additions:

### OQ-MCP-1. MCP `meta` field name for the session triplet

The exact MCP request-metadata field used to carry `session_key` / `insight_id` / `thread_id` from the OpenClaw gateway down to the Python tool handler depends on the OpenClaw MCP client's implementation.
**Decision needed at integration time:** confirm the field name and document it in the ADR (F8).

### OQ-MCP-2. Sunset of the abandoned TS scaffold in docs

11b §3-§4 and 11c §G are now historical. Sunset note in those docs vs. leave-as-is for context.
**Proposal:** add a one-line "Superseded by 13-mcp-migration-prd.md" banner at the top of 11b and 11c. Confirm with stakeholder.

---

## 12. References

- `11a-openclaw-migration-prd.md` — parent PRD; this sub-PRD inherits its goals, NFRs, risks, and rollback contract.
- `11b-openclaw-migration-architecture.md` — superseded for the tool layer (§3-§4); forwarder (§5), SOUL.md (§8), feature flag (§7), dual-store (§6) remain authoritative.
- `11c-openclaw-migration-addendum.md` — superseded for §G (TS extension); §A-§F and §H-§K remain authoritative.
- `13-mcp-migration.md` (to be authored, F8) — companion ADR/architecture doc.
- Backend touch-points (informational, names current at 2026-05-06):
  - `backend/mcp_server.py` — new, the MCP server.
  - `backend/main.py` — new mount registration at `/mcp`.
  - `backend/config.py` — existing `agent_tools_bearer` field is reused.
  - `backend/agents/insights/tools/*.py` — unchanged tool bodies.
  - `.openclaw/openclaw.json` — updated provider/tool-server config.

---

*End of PRD.*
