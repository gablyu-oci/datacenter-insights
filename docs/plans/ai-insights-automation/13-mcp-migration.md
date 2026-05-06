# ADR-13 — Migrate Chat-Tool Routing from TypeScript Plugins to a Native Python MCP Server

**Status:** Accepted (2026-05-06)
**Decision drivers:** Karan (primary stakeholder), strategic-insights-tool team
**Supersedes (in part):** `11b-openclaw-migration-architecture.md` §3-§4 (TS plugin tool layer); `11c-openclaw-migration-addendum.md` §G (TS extension scaffold).
**Untouched:** `11a-openclaw-migration-prd.md` goals, `11b §5` forwarder, `11b §6` dual-store, `11b §7` feature flag, `11b §8` SOUL.md grounding pattern, the `ToolLoopDriver` legacy path, the seven tool function bodies, `sql_gate`, the synthesis pipeline.

---

## 1. Context

11a/11b/11c migrated the chat lane from `ToolLoopDriver` to OpenClaw and
specified that the seven existing chat tools (`query_database`,
`call_api`, `get_chart_data`, `web_search`, `run_skill`, `emit_chart`,
`emit_citation`) would be exposed to the gateway via a TypeScript
plugin under `.openclaw/extensions/insights-tools/`. That plugin was
scaffolded but never compiled, never loaded by the gateway, and never
exercised — chat turns produced text like "I cannot access the platform
Postgres" because no tool surface was registered with OpenClaw.

The bearer-auth Python webhook router at `backend/routers/agent_tools.py`
(11b §3) was always meant to be called *from* that TS plugin; on its
own it did nothing for the gateway.

We need a tool-routing mechanism that:

1. Surfaces the seven Python tools to OpenClaw without compiling
   TypeScript or running a separate Node service.
2. Reuses every existing tool implementation byte-for-byte (no
   reimplementation; no port to JS).
3. Mounts on the existing FastAPI process (no extra container).
4. Is auth-protected with the same bearer secret already in use.
5. Fits OpenClaw's existing tool-discovery surface.

OpenClaw natively speaks **Model Context Protocol (MCP)** to discover
remote tool servers — its `mcp.servers.<name>` config block accepts
either stdio, SSE, or streamable-HTTP transports. A native MCP server
in our FastAPI process is therefore a one-config-block change on the
gateway side.

---

## 2. Decision

Replace the abandoned TypeScript plugin with a **native Python MCP
server** mounted on the existing FastAPI process at `/mcp`, using:

- the official `mcp` Python SDK (≥ 1.27, < 2) and its `FastMCP` class,
- streamable-HTTP transport (JSON-RPC 2.0 over chunked POST),
- a Starlette `AuthenticationMiddleware` enforcing the same
  `AGENT_TOOLS_BEARER` secret as the legacy webhook router,
- FastMCP's `TransportSecuritySettings` allowlist to admit
  `host.docker.internal` (so the OpenClaw container can reach us),
- a shared `agents.insights.skill_ctx_factory.build_skill_ctx` helper
  so the MCP path and the HTTP webhook path build SkillContext
  identically.

Each MCP tool handler is a six-line wrapper that delegates to the
existing in-process `agents.insights.tools.registry.dispatch(name,
args, ctx)`; **no tool body is reimplemented**.

OpenClaw config (`.openclaw/openclaw.json`) is updated to add a single
`mcp.servers.oci-insights` block pointing at
`http://host.docker.internal:8002/mcp` with the bearer header.

The TypeScript scaffold under `.openclaw/extensions/insights-tools/`
is deleted.

---

## 3. Architecture (before / after)

### 3.1 Before (11b/11c plan, never executed)

```
┌──────────────┐  /v1/chat/completions  ┌────────────────────────┐
│ FastAPI      │ ─────────────────────▶ │ OpenClaw gateway       │
│ forwarder    │  ◀── SSE deltas ─────  │  (Node + TS extension) │
└──────┬───────┘                        └────────────┬───────────┘
       │                                             │  needs to load
       │ POST /api/agent-tools/<name>                ▼
       │  (bearer)                          ┌────────────────────┐
       └────────────────────────────────────│ TS plugin          │ ← scaffolded,
                                            │ insights-tools     │   never compiled
                                            └────────────────────┘
```

### 3.2 After (this ADR)

```
┌──────────────┐  /v1/chat/completions  ┌──────────────────────┐
│ FastAPI      │ ─────────────────────▶ │ OpenClaw gateway     │
│ forwarder    │  ◀── SSE deltas ─────  │ (Node, no extension) │
└──────────────┘                        └──────────┬───────────┘
                                                   │ MCP / streamable-HTTP
                                                   │ Bearer ${AGENT_TOOLS_BEARER}
                                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│ FastAPI (uvicorn :8002)                                         │
│                                                                 │
│  /mcp/  ── Starlette sub-app ──▶ FastMCP streamable_http_app    │
│  │                                  │                           │
│  │  AuthenticationMiddleware        │ @mcp.tool() x 7           │
│  │  (StaticBearer)                  ▼                           │
│  │                       agents.insights.tools.registry.dispatch│
│  │                                                              │
│  /api/agent-tools/<name>  (legacy bearer webhooks, retained)    │
└─────────────────────────────────────────────────────────────────┘
```

The `/mcp` mount and the legacy `/api/agent-tools/*` router share
the **same** `build_skill_ctx` factory (extracted to
`agents.insights.skill_ctx_factory`), so monkeypatched tests that pin
the factory continue to work for both code paths.

---

## 4. Why this transport / framework / placement

### 4.1 Why MCP (not gRPC, not OpenAI tool spec over REST)

OpenClaw natively understands MCP and ships discovery glue for it.
Anything else would have required either custom gateway code or
re-implementing tool advertisement on top of the bearer webhook
router (which does not match how the gateway picks up tools).

### 4.2 Why the official `mcp` SDK (not third-party `fastmcp`)

The third-party `fastmcp` package is a separate project with a
different API surface and is not the upstream reference. The
official `mcp` SDK ships its own `FastMCP` class with streamable-HTTP
support and is what the protocol authors maintain.

### 4.3 Why streamable-HTTP (not stdio, not SSE)

- **stdio** would require running the MCP server as a child of the
  gateway, defeating the "stay on FastAPI" requirement.
- **SSE** is the older transport; streamable-HTTP is the current
  recommended default and is what OpenClaw uses for remote MCP
  servers.
- streamable-HTTP rides cleanly on top of FastAPI's existing
  uvicorn process and integrates with Starlette middleware for auth.

### 4.4 Why mounted on FastAPI (not a sidecar)

The seven tool implementations rely on the existing FastAPI app's
DB session factory, sql_gate, and skill registry. Hosting MCP in
the same process means we can `import` them directly — no IPC,
no duplicated configuration, no second deploy unit.

### 4.5 Why `AuthenticationMiddleware` (not FastMCP's built-in auth)

FastMCP's built-in OAuth flows are designed for human users.
We need a static service-to-service bearer matching what the legacy
webhook router already enforced. Starlette
`AuthenticationMiddleware` + a tiny `StaticBearer` backend is the
minimal idiomatic fit.

### 4.6 Why DNS-rebinding allowlist for `host.docker.internal`

FastMCP enables DNS-rebinding protection by default, which rejects
any `Host` header outside its allowlist. The OpenClaw container
reaches us as `host.docker.internal:8002`, so that hostname must be
explicit on the allowlist. `127.0.0.1` and `localhost` remain
allowlisted for in-process tests and operator probes.

---

## 5. Acceptance and verification

| Requirement | Where verified | Result |
|---|---|---|
| R1 `mcp` SDK installed and importable | `backend/pyproject.toml` + `uv lock`; smoke `python -c "from mcp.server.fastmcp import FastMCP"` | PASS |
| R2 Seven tools exposed without reimplementation | `mcp_server.py` (each `@mcp.tool()` is a wrapper around `dispatch`) | PASS |
| R3 Mounted at `/mcp` on :8002 with bearer + DNS allowlist | `backend/main.py` calls `mount_mcp(app)`; container probe returns 401 → 200 | PASS |
| R4 `.openclaw/openclaw.json` `mcp.servers.oci-insights` entry | Config diff in this commit | PASS |
| R5 `backend/tests/test_mcp_server.py` 8 tests green; full repo sweep green | `13-mcp-migration-test-evidence.md` §5 | PASS |
| R6 Live chat reaches MCP and returns real DB feedback | `13-mcp-migration-test-evidence.md` §3 | PASS (text); SSE `tool_call_*` events deferred — see §6 below |
| R7 TS scaffold removed; `agent_tools.py` retained | filesystem; `git status` | PASS |
| R8 ADR + addendum updates | this file + 11b/11c notes | PASS |

---

## 6. Follow-ups (deferred, out of this ADR's scope)

1. **Surface `tool_call_started` / `tool_call_complete` SSE events for
   the OpenClaw lane.** Today the gateway runs the MCP loop server-side
   and emits only assistant-text deltas to our forwarder, so the
   translator never sees `tool_calls` deltas. Either (a) confirm
   whether OpenClaw has a "passthrough tool deltas" mode and toggle
   it, or (b) add a server-side telemetry channel from
   `mcp_server._invoke` into the forwarder's per-thread queue. Both
   touch the forwarder, which is currently guarded by 11a NG3.
2. **Bind `insight_id` from session context.** The MCP SDK at this
   version generates tool schemas from Python signatures, so
   `insight_id` is presented to the model as an explicit argument.
   A future iteration should use the MCP `Context` parameter and a
   request-scoped header (set by the gateway from
   `x-openclaw-session-key`) to recover the binding implicitly.
3. **Remove the empty `.openclaw/extensions/` directory.** The
   contents were deleted but the parent dir remains due to a
   filesystem permission that requires operator action. Harmless
   but cosmetically untidy.
4. **Telemetry parity.** The legacy webhook router logs per-tool
   latency at HTTP layer. Add an equivalent log line at
   `mcp_server._invoke` exit so operators can compare both paths.

---

## 7. Operational runbook

### 7.1 Verifying the MCP mount is up

In-process:
```
curl -s -H "Authorization: Bearer $AGENT_TOOLS_BEARER" \
     -H "Content-Type: application/json" \
     -H "Accept: application/json, text/event-stream" \
     -X POST http://127.0.0.1:8002/mcp/ \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```
Expect HTTP 200 and a JSON body whose `result.tools[]` has length 7.

From the OpenClaw container:
```
docker exec -i openclaw curl -sS \
     -H "Authorization: Bearer $AGENT_TOOLS_BEARER" \
     -H "Content-Type: application/json" \
     -H "Accept: application/json, text/event-stream" \
     -X POST http://host.docker.internal:8002/mcp/ \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```
Same 200 + 7 tools.

### 7.2 Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `connection refused` from container | iptables INPUT chain blocking docker bridge → :8002 | reapply the narrow `iptables -I INPUT 5 -p tcp -s 172.19.0.0/16 --dport 8002 -j ACCEPT` rule |
| `Invalid Host header` in OpenClaw bundle log | `host.docker.internal` not in `allowed_hosts` | confirm `mcp_server.py` `TransportSecuritySettings.allowed_hosts` still lists it |
| 401 with valid bearer | `AGENT_TOOLS_BEARER` mismatched between FastAPI env and `${AGENT_TOOLS_BEARER}` substitution in `.openclaw/openclaw.json` | redeploy with matching value |
| 503 `agent_tools_bearer_not_configured` | env var unset | set `AGENT_TOOLS_BEARER` and restart uvicorn |
| OpenClaw startup log shows TS extension warning | residue from old scaffold | confirm `.openclaw/extensions/insights-tools/` is gone (rm contents) and restart gateway |

### 7.3 Rollback

`OPENCLAW_ENABLED=0` reverts the chat lane to the legacy
`ToolLoopDriver`. The MCP mount stays up but is unused — it is
inert without OpenClaw because nothing else dials it. To remove
the mount entirely, comment out `mount_mcp(app)` in `backend/main.py`
and revert the `mcp.servers` block in `.openclaw/openclaw.json`.

---

## 8. Files touched by this ADR

| File | Change |
|---|---|
| `backend/pyproject.toml` | Added `"mcp>=1.27,<2"` |
| `backend/uv.lock` | Regenerated via `uv lock` |
| `backend/mcp_server.py` | **NEW** — FastMCP app, 7 tool wrappers, bearer auth, DNS allowlist, `mount_mcp(app)` |
| `backend/main.py` | Imports and calls `mount_mcp(app)` after router registration |
| `backend/agents/insights/skill_ctx_factory.py` | **NEW** — extracted from `routers/agent_tools.py` for reuse |
| `backend/routers/agent_tools.py` | Re-exports `build_skill_ctx` from the factory; behavior unchanged |
| `backend/tests/test_mcp_server.py` | **NEW** — 8 unit tests (auth, tools/list, tools/call success + error, DNS-rebinding, lifespan composition) |
| `.openclaw/openclaw.json` | Added `mcp.servers.oci-insights` block at `http://host.docker.internal:8002/mcp` |
| `.openclaw/extensions/insights-tools/` | **DELETED** (TS scaffold) |
| `docs/plans/ai-insights-automation/13-mcp-migration-prd.md` | Already created by PM |
| `docs/plans/ai-insights-automation/13-mcp-migration-research.md` | Already created from researcher findings |
| `docs/plans/ai-insights-automation/13-mcp-migration-architecture.md` | Already created by architect |
| `docs/plans/ai-insights-automation/13-mcp-migration-test-evidence.md` | **NEW** — live smoke evidence |
| `docs/plans/ai-insights-automation/13-mcp-migration.md` | **NEW** — this ADR |
| `docs/plans/ai-insights-automation/11-openclaw-deployment.md` | Appended `## MCP Server (added 2026-05-06)` runbook section |
| `docs/plans/ai-insights-automation/11b-openclaw-migration-architecture.md` | Header note: §3-§4 superseded by ADR-13 |
| `docs/plans/ai-insights-automation/11c-openclaw-migration-addendum.md` | Header note: §G TS extension path abandoned, see ADR-13 |
