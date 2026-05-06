# 11b - OpenClaw Migration: Implementation Architecture

> **§3 (FastAPI agent-tools router) and §4 (TypeScript plugin tool layer)
> are SUPERSEDED by ADR-13 (`13-mcp-migration.md`, 2026-05-06).** Tool
> routing now flows through a native Python MCP server mounted at `/mcp`
> on the existing FastAPI process; the TS extension under
> `.openclaw/extensions/insights-tools/` has been deleted. The bearer
> webhook router from §3 is retained as a fallback / test surface but
> is no longer the primary tool transport. All other sections (§5
> forwarder, §6 dual-store, §7 feature flag, §8 SOUL.md grounding)
> stand unchanged.

**Status:** Implementation spec (user-ratified override of ADR-010 SKIP).
**Date:** 2026-05-05
**Owner (architecture):** AI Insights team
**Predecessors:**
- `10-openclaw-integration-evaluation.md` (ADR-010 §4 component-by-component map; this doc operationalizes that map under the user override)
- `03-architecture.md` (current chat path SSE + ToolLoopDriver)
- `08-v1.1-agentic-plan.md` (the agentic path partially subsumed by this migration)
- `11-openclaw-migration-prd.md` (R1-R9 requirements)

**Scope.** This document specifies the implementation architecture for
forwarding the per-insight chat path (`POST /api/insights/insights/{id}/chat`)
through a self-hosted OpenClaw Gateway, while preserving:
- the existing browser SSE event taxonomy (R5),
- the `agent_message` Postgres write-through audit trail (R7),
- the `_build_chat_context` and `_chat_system_prompt` rollback path (R9),
- and the seven existing chat tools as HTTP-callable wrappers (R4).

**Non-goals.** This doc does NOT cover insight-discovery
(`POST /api/insights/sessions`) — that path stays on `ToolLoopDriver`.
This doc does NOT relitigate ADR-010 §1-§3, §6, §7. Reasoning is in
ADR-010; the user override is recorded in PRD 11.

This document IS the contract the backend agent will implement against,
the QA agent will write tests against (`12-openclaw-test-plan.md`), and
the infra agent will provision against. Where the upstream OpenClaw
docs are unverified at the time of writing, items are marked
`// VERIFY` for the backend agent to confirm at implementation time.

---

## Table of contents

- §1. Deployment topology
- §2. Agent configuration (one shared agent, sessionKey scheme, SOUL.md)
- §3. FastAPI tool-wrapper router (`backend/routers/agent_tools.py`)
- §4. OpenClaw TypeScript plugins (per-tool + insight context preload)
- §5. Forwarder rewrite (`backend/routers/insights.py` chat endpoint)
- §6. Persistence dual-store
- §7. Feature flag and rollback drill
- §8. SOUL.md draft content
- §9. File-path manifest
- §10. Test architecture

---

## §1. Deployment topology

### 1.1 Container

The OpenClaw Gateway runs as a single Docker container co-located with
the FastAPI process on the same host. Co-location matters: tool calls
land back on FastAPI via webhook, so a same-host loopback path
minimises tool-call latency (ADR-010 §4.8).

| Field | Value |
|---|---|
| Image | `ghcr.io/openclaw/openclaw:stable` (// VERIFY exact tag — researcher's §2 quoted "stable / beta / dev release channels") |
| Container name | `openclaw` |
| Network mode | `host` (single-host dev/dogfood) |
| Container port | `7474` (OpenClaw default Gateway HTTP port — // VERIFY against `docs.openclaw.ai`) |
| Host port | `18789` (chosen to stay clear of typical app-dev ranges; FastAPI = 8000) |
| Restart policy | `unless-stopped` |
| Health check | `curl -fsS http://127.0.0.1:7474/api/status \|\| exit 1`, interval 30 s |

The forwarder in §5 dials `http://localhost:18789/api/sessions/...` from
inside the FastAPI process.

The plugins in §4 dial back via `http://host.docker.internal:8000` —
which on Linux requires the `extra_hosts:` mapping recorded in the
compose file below. (// VERIFY: on host networking mode this may
become `http://127.0.0.1:8000` instead; the infra agent will pick
the correct value at provisioning time.)

### 1.2 Volumes

OpenClaw stores its state on a host-mounted volume so a container
restart does not lose the agent definition, sessions, or JSONL
transcripts.

| Mount | Container path | Purpose |
|---|---|---|
| `./.openclaw/data` | `/home/node/.openclaw` | Agents, sessions, JSONL transcripts, SQLite session-store with WAL (researcher §2.5). Path verified by ADR-010 §2.5; // VERIFY against `docs.openclaw.ai/storage`. |
| `./backend/openclaw/SOUL.md` | `/home/node/.openclaw/agents/datacenter-power-analyst/SOUL.md` | Bind-mounted persona file (read-only) so persona edits land in git. |
| `./backend/openclaw/plugins` | `/home/node/.openclaw/plugins` | Compiled plugin bundle (TS -> JS via tsc; // VERIFY that OpenClaw expects `.js` here vs raw `.ts`). |
| `./backend/openclaw/agents.json` | `/home/node/.openclaw/agents.json` | File-bootstrapped agent manifest (see §2.2). |

The `.openclaw` host directory is added to `.gitignore` (it contains
runtime-mutable JSONL transcripts and the SQLite store).

### 1.3 Environment variables

The container reads the following at boot. Names are best-effort guesses
based on conventional naming and the researcher dossier; the infra
agent will verify against the live container at provisioning.

| Var | Required | Purpose | Notes |
|---|---|---|---|
| `OPENCLAW_GATEWAY_TOKEN` | Yes | Bearer token the FastAPI forwarder presents on `POST /api/sessions/.../messages`. | Generate one 32-byte hex string per environment. The same value is read by `backend/routers/insights.py` from the FastAPI side. |
| `OPENCLAW_AGENT_ID` | Yes (or via agents.json) | Default agent for sessions whose key does not pin an agent explicitly. | Set to `datacenter-power-analyst`. |
| `OPENAI_API_BASE` | Yes | LLM endpoint. | Points at OCI-fronted OpenAI-compatible shim or directly at OCI Generative AI's OpenAI-compat surface. |
| `OPENAI_API_KEY` | Yes | LLM credential. | OCI key or shim key depending on §1.5. |
| `OPENAI_MODEL` | Yes | Model name. | `oci/openai.gpt-5.4` or whatever the OCI OpenAI-compat layer accepts. // VERIFY exact string. |
| `AGENT_TOOLS_BEARER` | Yes | Bearer the OpenClaw plugins present on calls back to `http://host.docker.internal:8000/api/agent-tools/*`. | Same value as the FastAPI side reads (§3.2). |
| `AGENT_TOOLS_BASE_URL` | Yes | Base URL the plugins use. | `http://host.docker.internal:8000` on Linux Docker; `http://127.0.0.1:8000` if host networking is used. |
| `OPENCLAW_LOG_LEVEL` | No | Container log verbosity. | `info` in dev, `warn` in prod. |
| `TZ` | No | Container TZ. | `UTC`. |

**Secrets handling.** `OPENCLAW_GATEWAY_TOKEN`, `OPENAI_API_KEY`, and
`AGENT_TOOLS_BEARER` are NOT committed. They live in
`backend/.env.openclaw` (added to `.gitignore`) and are loaded by
docker-compose's `env_file:` directive. The same three are read on the
FastAPI side via the existing `python-dotenv` `load_dotenv` call in
`backend/config.py` (see §7).

### 1.4 docker-compose

Concrete compose file at
`/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/docker-compose.yml`:

```yaml
services:
  openclaw:
    image: ghcr.io/openclaw/openclaw:stable   # // VERIFY tag
    container_name: openclaw
    network_mode: host                         # single-host dev/dogfood
    restart: unless-stopped
    env_file:
      - ../.env.openclaw
    environment:
      OPENCLAW_AGENT_ID: datacenter-power-analyst
      AGENT_TOOLS_BASE_URL: http://127.0.0.1:8000
      OPENCLAW_LOG_LEVEL: info
      TZ: UTC
    volumes:
      - ./data:/home/node/.openclaw
      - ./SOUL.md:/home/node/.openclaw/agents/datacenter-power-analyst/SOUL.md:ro
      - ./plugins:/home/node/.openclaw/plugins:ro
      - ./agents.json:/home/node/.openclaw/agents.json:ro
    healthcheck:
      test: ["CMD-SHELL", "curl -fsS http://127.0.0.1:7474/api/status || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
```

Boot persistence: `restart: unless-stopped` plus a Docker daemon that
itself starts on boot is sufficient. No systemd unit file is required
on hosts where docker.service is enabled — the compose project comes
back up automatically. If the host's Docker is not enabled at boot
(rare on this team's OCI VMs), the infra agent will add a lightweight
oneshot systemd unit that runs `docker compose -f .../docker-compose.yml
up -d`; this is documented in the runbook but not part of the
backend implementation.

### 1.5 LLM provider wiring

OpenClaw advertises an "OpenAI-compatible" provider (researcher §2.6).
We point this at our existing `oci/openai.gpt-5.4` model surface via
the OpenAI-compat shim. Two options:

- **A.** Re-use OCI's first-party OpenAI-compat endpoint if available
  in our region. Set `OPENAI_API_BASE` to the OCI URL.
- **B.** Run a tiny in-tree OpenAI-compat proxy that adapts to OCI
  Generative AI's native shape and points at it.

This document assumes (A) is workable; the infra agent will confirm at
provisioning. If only (B) is feasible, that proxy is a separate piece
of work tracked outside this spec.

The model name (`OPENAI_MODEL`) MUST match what
`backend/llm/client.py` calls today (`MODELS["reasoning"]` = the
OCI-fronted GPT-5.4 alias) so reply quality is held constant per R8.

---

## §2. Agent configuration

### 2.1 One shared agent

Per R6, we provision exactly **one** OpenClaw agent for the entire
product, named `datacenter-power-analyst`. All chat sessions for all
insights map onto this single agent. We deliberately do NOT create
one agent per insight (ADR-010 §4.3 enumerates why this would be
pathological at our scale).

Per-insight scope is achieved purely via the **sessionKey naming
convention**:

```
sessionKey  ::=  "insight:" UUID-of-insight
                  e.g. "insight:7e2c1c0a-9f4e-4b9c-9a91-aa7f5d4f1e22"
```

OpenClaw's `POST /api/sessions/{sessionKey}/messages` endpoint
auto-creates a session under that key if one does not exist. The
session's transcript and any per-session model-written notes
(SOUL-style notes) live under that key on disk.

The per-insight system prompt is NOT carried via the agent's
SOUL.md (which is static). Instead, the **first turn** for any
sessionKey of the form `insight:<id>` triggers the
`insight_context_preload` pre-hook plugin (§4.8) which fetches the
insight's full context bundle from FastAPI and pushes it into the
conversation as a system note. This is the load-bearing pattern that
preserves the per-insight grounding the existing
`_chat_system_prompt(context)` provides today.

### 2.2 Agent provisioning: file-bootstrapped

OpenClaw supports defining agents via either an admin REST call or a
file at `~/.openclaw/agents.json`. We use the **file-bootstrapped**
approach because it is:
1. declarative (lives in git),
2. idempotent (container restart re-applies),
3. atomic (no admin-API state drift between dev and prod).

The bootstrap config lives at
`/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/agents.json`:

```json
{
  "agents": [
    {
      "id": "datacenter-power-analyst",
      "displayName": "Datacenter & Power Analyst",
      "soulFile": "/home/node/.openclaw/agents/datacenter-power-analyst/SOUL.md",
      "model": {
        "provider": "openai-compatible",
        "model": "${OPENAI_MODEL}",
        "baseUrl": "${OPENAI_API_BASE}",
        "apiKeyEnv": "OPENAI_API_KEY"
      },
      "plugins": [
        "agent_tool_query_database",
        "agent_tool_call_api",
        "agent_tool_get_chart_data",
        "agent_tool_web_search",
        "agent_tool_run_skill",
        "agent_tool_emit_chart",
        "agent_tool_emit_citation",
        "insight_context_preload"
      ],
      "tools": [
        "query_database",
        "call_api",
        "get_chart_data",
        "web_search",
        "run_skill",
        "emit_chart",
        "emit_citation"
      ],
      "channels": ["webchat", "rest"],
      "session": {
        "keyPattern": "insight:*",
        "compactPolicy": { "maxTurns": 24, "summariseAfter": 12 }
      }
    }
  ]
}
```

(// VERIFY field names against `docs.openclaw.ai/agents-spec`. The
backend agent should treat this as a working sketch and align it to
the literal schema OpenClaw publishes; if a key name is wrong, the
correction is a 1-line config change, not a re-architecture.)

### 2.3 SOUL.md location

The persona file is bind-mounted from
`backend/openclaw/SOUL.md` into the container. Editing the persona
is a git operation followed by a container restart (or a soft reload
if OpenClaw exposes one — // VERIFY).

The full persona content is in §8.

### 2.4 SOUL.md section layout

The SOUL.md content (full draft in §8) is structured into the
following labelled sections so the persona is auditable and
diff-friendly:

1. **Identity** — who the agent is, who its user is, what product it
   serves.
2. **Voice** — the deterministic-analyst voice; rules from R3.
3. **Schema knowledge** — names of the tables and columns the agent is
   expected to know about, plus the fact that authoritative data is
   reached via tools, not from prior knowledge.
4. **Tool palette** — the seven tools (`query_database`, `call_api`,
   `get_chart_data`, `web_search`, `run_skill`, `emit_chart`,
   `emit_citation`) and when to reach for each.
5. **Citation rules** — how to cite a row from a tool result; what to
   do when sources disagree (use `agree_or_disagree` in `emit_citation`).
6. **Safety rules** — read-only against the DB; no SQL outside the
   `sql_gate`; no fabrication of row IDs or numeric values.
7. **Out-of-scope redirect** — how to short-circuit off-insight chatter
   (one polite line, then stop).
8. **Per-insight grounding contract** — the agent is told that the
   first system note in any `insight:*` session contains the
   pre-loaded insight context (headline, body, chart spec, citations,
   skills_run, confidence, materiality) and must treat that as
   ground truth for the duration of the session.

---

## §3. FastAPI tool-wrapper router (R4)

### 3.1 File location and registration

Create `backend/routers/agent_tools.py`. Wire it into FastAPI in
`backend/main.py` alongside the other routers:

```python
# backend/main.py — add to the import block (line ~39)
from routers.agent_tools import router as agent_tools_router
# ... and to the registration block lower in the file:
app.include_router(agent_tools_router)
```

The router prefix is `/api/agent-tools`; it co-exists with the existing
`/api/insights/...` routes.

### 3.2 Bearer authentication dependency

Every endpoint on this router requires a static Bearer token read from
the env var `AGENT_TOOLS_BEARER`. The exact same value is set on the
OpenClaw container so its plugins can authenticate back.

```python
# backend/routers/agent_tools.py
import os
from fastapi import Header, HTTPException

def _require_agent_bearer(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("AGENT_TOOLS_BEARER", "")
    if not expected:
        # Fail closed: if the env var is not set the router is disabled.
        raise HTTPException(status_code=503, detail="agent-tools bearer not configured")
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="invalid bearer")
```

Each endpoint adds `dependencies=[Depends(_require_agent_bearer)]`.

### 3.3 Wire format (request body)

Every tool endpoint accepts the same envelope:

```json
{
  "args":    { "<tool-specific keys>": "..." },
  "context": {
    "insight_id": "<uuid str>",
    "session_id": "<parent ai_session uuid str>",
    "thread_id":  "<insight_thread uuid str>"
  }
}
```

The plugin layer (§4) is responsible for filling `context` from the
OpenClaw sessionKey. The handler builds a `SkillContext` from
`context` and forwards `args` to the existing tool function. The
result is returned as a JSON object identical to what the in-process
`dispatch(name, args, ctx)` returns today.

On exception the handler returns:

```json
{ "error": "<repr of exc>", "code": "TOOL_FAILED" }
```

with HTTP 200 (not 500) — OpenClaw plugins are simpler if they can
treat all webhook responses as JSON to forward to the LLM. The
`error` payload is the on-the-wire signal of failure.

### 3.4 The seven endpoints

All endpoints are `POST` with the envelope above. Path = tool name.

| Endpoint | Underlying function | Module |
|---|---|---|
| `POST /api/agent-tools/query_database` | `query_database(sql, ctx, max_rows)` | `agents.insights.tools.query_database` |
| `POST /api/agent-tools/call_api` | `call_api(endpoint, params, ctx)` | `agents.insights.tools.call_api` |
| `POST /api/agent-tools/get_chart_data` | `get_chart_data(tab, chart_id, ctx)` | `agents.insights.tools.get_chart_data` |
| `POST /api/agent-tools/web_search` | `web_search(query, n, ctx)` | `agents.insights.tools.web_search` |
| `POST /api/agent-tools/run_skill` | `run_skill(skill_name, inputs, ctx)` | `agents.insights.tools.run_skill` |
| `POST /api/agent-tools/emit_chart` | `emit_chart(spec_dict, ctx)` | `agents.insights.tools.emit_chart` |
| `POST /api/agent-tools/emit_citation` | `emit_citation(...kwargs, ctx)` | `agents.insights.tools.emit_citation` |

Each endpoint:

1. Pulls `args` and `context` out of the body.
2. Builds a `SkillContext` (see `agents.insights.specs.skill_context`)
   with:
   - `session_id` = `context["session_id"]`,
   - `turn_id` = `f"oc_{uuid.uuid4().hex[:8]}"`,
   - `correlation_id` = `f"oc_{context['insight_id']}_{uuid.uuid4().hex[:8]}"`,
   - `model` = `MODELS["reasoning"]`,
   - `budget_seconds_remaining` = `45.0` (chat budget),
   - `capabilities` = full chat-mode `Capabilities(...)` set (mirrors
     the values used today in `post_insight_chat`),
   - `thread_id` = `context["thread_id"]`,
   - `insight_id` = `context["insight_id"]`,
   - `emit_event` = a no-op async lambda (the OpenClaw forwarder
     synthesises tool-call SSE events from its own event stream;
     in-tool `emit_event` calls would not propagate cleanly).
3. Awaits the tool function with the right positional/keyword shape
   (mirror the dispatch logic in
   `agents.insights.tools.registry.dispatch`).
4. Returns the result dict as JSON.
5. On exception, returns `{"error": str(exc), "code": "TOOL_FAILED"}`.

### 3.5 Insight-context preload endpoint

In addition to the seven tool endpoints, add:

```
GET /api/agent-tools/insight-context?insight_id=<uuid>
```

- Bearer-protected (same dependency).
- Reads `_build_chat_context(db, insight_id)` (the existing function
  from `backend/routers/insights.py` — re-export it from there or move
  it to a shared `agents/insights/chat_context.py` so both routers can
  import it without a cycle).
- Returns the dict as JSON.
- Used by the `insight_context_preload` plugin in §4.8.

This is the seam that lets the system prompt stay per-agent (static
SOUL.md) while injecting per-insight grounding on the first turn of
each session.

### 3.6 Concurrency and DB sessions

Each tool endpoint opens a fresh `async_session_factory()` per request
(mirroring `post_insight_chat`'s pattern in today's
`backend/routers/insights.py`). On a successful return the session is
committed; on exception it is rolled back; in `finally` the session
is closed. This isolates webhook tool calls from each other and
avoids carrying connection state across LLM tool dispatch boundaries.

### 3.7 Latency budget

A tool webhook should complete in well under the per-turn 45 s wall
budget. We set a server-side soft timeout of 30 s on each tool
(`asyncio.wait_for`); if the inner tool body exceeds that, the handler
returns `{"error": "tool_timeout", "code": "TOOL_FAILED"}` so the LLM
can react.

---

## §4. OpenClaw TypeScript plugins

### 4.1 Directory and build layout

```
backend/openclaw/
  docker-compose.yml
  agents.json
  SOUL.md
  package.json
  tsconfig.json
  plugins/
    agent_tool_query_database.ts
    agent_tool_call_api.ts
    agent_tool_get_chart_data.ts
    agent_tool_web_search.ts
    agent_tool_run_skill.ts
    agent_tool_emit_chart.ts
    agent_tool_emit_citation.ts
    insight_context_preload.ts
    _shared/
      bearer_fetch.ts        # tiny helper around fetch() with bearer + JSON
      types.ts               # ContextBlock, ToolEnvelope shape
```

The `package.json` declares a `tsc` build that emits compiled `.js`
files into `plugins-dist/` (or wherever OpenClaw expects, // VERIFY).
The `docker-compose.yml` then mounts the build output, not the .ts
sources.

### 4.2 Plugin shape (pseudocode — // VERIFY against OpenClaw plugin SDK)

The researcher's report describes a "TypeScript Plugin SDK"
(researcher §2.4) without a complete public schema. The pseudocode
below uses the shape we expect; the backend agent will replace the
imports and registration calls with the literal SDK API once the
researcher's §5 confirms exact names.

```typescript
// agent_tool_query_database.ts
import { definePlugin, registerTool } from "@openclaw/plugin-sdk";  // // VERIFY
import { bearerFetchJson } from "./_shared/bearer_fetch";

const SCHEMA = {
  type: "object",
  properties: {
    sql: { type: "string", description: "Single Postgres-dialect SELECT." },
    max_rows: { type: "integer", default: 10000, maximum: 10000 }
  },
  required: ["sql"],
  additionalProperties: false
};

export default definePlugin({
  id: "agent_tool_query_database",
  setup({ on }) {
    registerTool({
      name: "query_database",
      description: "Run a single read-only SELECT against the strategic-insights Postgres. Returns rows + row_hash + executed_sql. Max 10000 rows.",
      schema: SCHEMA,

      async invoke({ args, session }) {
        // session.key looks like "insight:<uuid>".
        // OpenClaw's session object should expose the key plus
        // any auxiliary attributes the gateway has stored.
        const insight_id = parseInsightIdFromKey(session.key);
        const baseUrl = process.env.AGENT_TOOLS_BASE_URL!;
        const bearer  = process.env.AGENT_TOOLS_BEARER!;
        return await bearerFetchJson(
          `${baseUrl}/api/agent-tools/query_database`,
          bearer,
          {
            args,
            context: {
              insight_id,
              session_id: session.attributes?.parent_session_id ?? null,
              thread_id:  session.attributes?.thread_id ?? null
            }
          }
        );
      }
    });
  }
});

function parseInsightIdFromKey(key: string): string {
  const m = /^insight:([0-9a-f-]{36})$/.exec(key);
  if (!m) throw new Error(`expected sessionKey of form insight:<uuid>, got ${key}`);
  return m[1];
}
```

`session.attributes` is populated by the `insight_context_preload`
plugin (§4.8) on the first turn of a new session, so the tool plugins
have `parent_session_id` and `thread_id` available without re-fetching
them every turn.

### 4.3 Plugin: `agent_tool_call_api.ts`

JSON schema:

```json
{
  "type": "object",
  "properties": {
    "endpoint": { "type": "string" },
    "params":   { "type": "object", "additionalProperties": true, "default": {} }
  },
  "required": ["endpoint"],
  "additionalProperties": false
}
```

Plugin body identical to §4.2 but POSTs to
`/api/agent-tools/call_api`.

### 4.4 Plugin: `agent_tool_get_chart_data.ts`

Schema:

```json
{
  "type": "object",
  "properties": {
    "tab":      { "type": "string" },
    "chart_id": { "type": "string" }
  },
  "required": ["tab", "chart_id"],
  "additionalProperties": false
}
```

POSTs to `/api/agent-tools/get_chart_data`.

### 4.5 Plugin: `agent_tool_web_search.ts`

Schema:

```json
{
  "type": "object",
  "properties": {
    "query": { "type": "string" },
    "n":     { "type": "integer", "default": 5, "minimum": 1, "maximum": 5 }
  },
  "required": ["query"],
  "additionalProperties": false
}
```

POSTs to `/api/agent-tools/web_search`.

### 4.6 Plugin: `agent_tool_run_skill.ts`

Schema:

```json
{
  "type": "object",
  "properties": {
    "skill_name": { "type": "string" },
    "inputs":     { "type": "object", "additionalProperties": true }
  },
  "required": ["skill_name", "inputs"],
  "additionalProperties": false
}
```

(The skill_name enum is enforced server-side in the existing
`run_skill` body — we do not duplicate the list here so we are not
forced to redeploy the plugin every time a new skill ships.)

POSTs to `/api/agent-tools/run_skill`.

### 4.7 Plugins: `agent_tool_emit_chart.ts` and `agent_tool_emit_citation.ts`

`emit_chart` schema is `{}` with `additionalProperties: true` (the
caller passes a full ChartSpec inline). Server-side validation lives
in the existing `agents.insights.tools.emit_chart` body.

`emit_citation` schema:

```json
{
  "type": "object",
  "properties": {
    "url": { "type": "string" },
    "title": { "type": "string" },
    "snippet": { "type": "string", "maxLength": 280 },
    "agree_or_disagree": { "type": "string", "enum": ["agree","disagree","context"] },
    "rationale": { "type": "string" },
    "search_query": { "type": "string" }
  },
  "required": ["url","title","snippet","agree_or_disagree","rationale","search_query"],
  "additionalProperties": false
}
```

Both POST to their respective `/api/agent-tools/<name>` endpoints.

### 4.8 Pre-hook plugin: `insight_context_preload.ts`

This is the plugin that solves the per-insight grounding problem
without polluting the user-visible transcript. It runs on the **first
turn** of any session whose key matches `insight:*`.

```typescript
import { definePlugin } from "@openclaw/plugin-sdk";  // // VERIFY
import { bearerFetchJson } from "./_shared/bearer_fetch";

export default definePlugin({
  id: "insight_context_preload",
  setup({ on }) {
    on("session.beforeFirstTurn", async ({ session, conversation }) => {
      // // VERIFY exact lifecycle hook name. Common candidates:
      //   - "session.beforeFirstTurn"
      //   - "turn.before"  (filtered by session.turnCount === 0)
      //   - "session.created"
      // The backend agent should pick whichever the SDK actually
      // exposes that fires exactly once per session, before the LLM
      // sees any user input.
      const m = /^insight:([0-9a-f-]{36})$/.exec(session.key);
      if (!m) return;  // not an insight-scoped session, leave alone
      const insight_id = m[1];

      const baseUrl = process.env.AGENT_TOOLS_BASE_URL!;
      const bearer  = process.env.AGENT_TOOLS_BEARER!;

      const ctx = await bearerFetchJson(
        `${baseUrl}/api/agent-tools/insight-context?insight_id=${insight_id}`,
        bearer,
        null  // GET
      );

      // Push as a system note so the user transcript stays clean.
      conversation.appendSystemNote(JSON.stringify({
        kind: "insight_context",
        insight_id,
        ...ctx
      }, null, 0).slice(0, 8000));   // mirror the today-side 8000-char cap

      // Stash session-attributes so per-tool plugins can read
      // parent_session_id / thread_id without re-fetching.
      session.attributes = {
        ...(session.attributes ?? {}),
        parent_session_id: ctx.parent_session_id ?? null,
        thread_id:         ctx.thread_id ?? null,
        insight_id
      };
    });
  }
});
```

The backend `GET /api/agent-tools/insight-context` endpoint (§3.5)
must be extended to also return `parent_session_id` (the parent
`ai_session.id` of the insight) and `thread_id` (the
`insight_thread.id`, creating one if missing — re-using
`_get_or_create_thread` from `backend/routers/insights.py`).

### 4.9 Why one plugin per tool (rather than a single multi-tool plugin)

OpenClaw's plugin reload story is per-plugin (// VERIFY). One file per
tool means a regression in `web_search` cannot break `query_database`.
It also makes tool-level disable trivial: drop the plugin name from
`agents.json -> agents[0].plugins` and restart.

---

## §5. Forwarder rewrite (R7)

### 5.1 Surface unchanged, internals split

The endpoint stays at `POST /api/insights/insights/{insight_id}/chat`,
preserving R5 (frontend SSE event names unchanged) and R7 (audit
guarantees). Only the function body changes.

The current body (the legacy implementation that uses
`ToolLoopDriver`) is renamed `_legacy_chat_handler` and kept verbatim
in `backend/routers/insights.py`. It is the rollback path per R9 and
must NOT be deleted.

The new top-level `post_insight_chat` becomes a thin dispatcher:

```python
@router.post(
    "/insights/{insight_id}/chat",
    responses={ 200: {"content": {"text/event-stream": {}}}, 404: {"description": "Insight not found"} },
)
async def post_insight_chat(
    insight_id: uuid.UUID,
    request: Request,
    body: ChatTurnBody = Body(...),
):
    if settings.openclaw_enabled:
        return await _openclaw_chat_handler(insight_id, request, body)
    return await _legacy_chat_handler(insight_id, request, body)
```

`settings.openclaw_enabled` is the feature flag (§7).

### 5.2 `_openclaw_chat_handler` flow

The new handler steps, in order:

1. **Acquire context.** Reuse `_build_chat_context(db_session,
   insight_id)` and `_get_or_create_thread(db_session, insight_id=...)`
   to mint or fetch the `insight_thread` row. Resolve
   `parent_session_id` from the insight row. Commit. (This is identical
   prelude to the legacy handler.)
2. **Persist user message (write-through, R7 audit guarantee).**
   Determine the next `seq` for the thread; INSERT one row into
   `agent_message` with `role="user", content=body.message,
   thread_id=thread.id, session_id=parent_session_id,
   insight_id=insight_id`. Commit. This row is written BEFORE the
   OpenClaw call so the audit trail is intact even if OpenClaw never
   responds.
3. **POST to OpenClaw.** Open an `httpx.AsyncClient` with
   `timeout=httpx.Timeout(60.0, read=60.0)`. POST to
   `http://localhost:18789/api/sessions/insight:{insight_id}/messages`
   with:
   ```json
   {
     "content": "<user_text>",
     "stream": true,
     "attributes": {
       "parent_session_id": "<parent_session_id str>",
       "thread_id": "<thread.id str>",
       "insight_id": "<insight_id str>"
     }
   }
   ```
   (// VERIFY: `attributes` is the field OpenClaw uses for per-message
   session metadata. If not, the backend agent uses the equivalent the
   SDK exposes — the goal is for `insight_context_preload` to see those
   three fields on first turn.)
   Authentication: `Authorization: Bearer <OPENCLAW_GATEWAY_TOKEN>`.
4. **Read OpenClaw SSE.** Use `httpx`'s streaming response API
   (`async for line in response.aiter_lines(): ...`) to receive frames.
   Translate each frame into our taxonomy via the table in §5.4 and
   re-emit on the StreamingResponse the browser is consuming. Maintain
   a per-call `seq` counter for our own SSE; mint our own `event_id`
   strings (matching the legacy handler's pattern, e.g.
   `tcs_<hex>`).
5. **Buffer the assistant text and tool-call records.** As tokens
   arrive, accumulate them into `assistant_buffer`. As tool-call
   started/complete pairs arrive, accumulate into a `tool_calls_log:
   list[dict]` (each entry: `{tool_call_id, tool_name, ok, latency_ms,
   error_code}`). These will be persisted on `message_complete`.
6. **On `message_complete`,** stop reading OpenClaw, then within a
   single DB transaction:
   - INSERT one `agent_message` row with `role="assistant"`, content =
     `assistant_buffer or None`, `tool_calls = tool_calls_log or None`
     (JSONB), `thread_id`, `session_id`, `insight_id`, `seq = user_seq +
     1`.
   - Commit.
   This is the second R7 audit write.
7. **On `error` from OpenClaw,** translate to `error_event`, persist a
   best-effort `agent_message` with `role="assistant", content=None,
   tool_calls=tool_calls_log or None`, and end the stream.
8. **On client disconnect** (`request.is_disconnected()`), best-effort
   cancel the `httpx` stream. Persist whatever assistant text has
   accumulated as a partial assistant message with `tool_calls` set to
   the records we have. Finally close the DB session.

### 5.3 OpenClaw event names (// VERIFY exact strings)

The researcher's §5 will confirm OpenClaw's exact wire event names.
Until then, the candidates we map are conservative best guesses based
on the dossier's references to "SSE for token streaming" and standard
OpenAI-style streaming names. The backend agent should leave a
`# VERIFY` comment on each of these once the literal names are
confirmed.

| OpenClaw event (best guess) | Our taxonomy event |
|---|---|
| `token` / `delta` / `message.delta` | `assistant_message_token` |
| `tool_call.started` / `tool.started` | `tool_call_started` |
| `tool_call.complete` / `tool.complete` / `tool.result` | `tool_call_complete` |
| `message.complete` / `done` / `message.end` | `message_complete` |
| `error` | `error` (use `ErrorEvent` from `sse_events.py`) |
| anything else | dropped + structured-log warning |

### 5.4 SSE translation table (concrete payload mapping)

Our taxonomy lives in
`backend/agents/insights/specs/sse_events.py`. The translator builds
events with the existing Pydantic models — no schema change.

**`token` -> `AssistantMessageTokenEvent`:**
```python
AssistantMessageTokenEvent(
    event_id=f"amt_{uuid.uuid4().hex[:12]}",
    seq=next_seq(),
    data=AssistantMessageTokenData(
        thread_id=str(thread_id),
        message_id=assistant_message_id,
        delta=oc_event["delta"],   # // VERIFY field name
    ),
)
```

**`tool_call.started` -> `ToolCallStartedEvent`:**
```python
ToolCallStartedEvent(
    event_id=f"tcs_{uuid.uuid4().hex[:12]}",
    seq=next_seq(),
    data=ToolCallStartedData(
        thread_id=str(thread_id),
        tool_call_id=oc_event["tool_call_id"],   # // VERIFY
        tool_name=oc_event["name"],              # // VERIFY
        args_truncated=json.dumps(oc_event.get("args") or {}, default=str)[:200],
    ),
)
```

**`tool_call.complete` -> `ToolCallCompleteEvent`:**
```python
ToolCallCompleteEvent(
    event_id=f"tcc_{uuid.uuid4().hex[:12]}",
    seq=next_seq(),
    data=ToolCallCompleteData(
        thread_id=str(thread_id),
        tool_call_id=oc_event["tool_call_id"],
        ok=bool(oc_event.get("ok", True)),
        latency_ms=int(oc_event.get("latency_ms") or 0),
        error_code=oc_event.get("error_code"),
    ),
)
```

**`message.complete` -> `MessageCompleteEvent`:**
```python
MessageCompleteEvent(
    event_id=f"mco_{uuid.uuid4().hex[:12]}",
    seq=next_seq(),
    data=MessageCompleteData(
        thread_id=str(thread_id),
        message_id=assistant_message_id,
        finish_reason=oc_event.get("finish_reason") or "stop",  # // VERIFY enum mapping
    ),
)
```

**`error` -> `ErrorEvent`:**
```python
ErrorEvent(
    event_id=f"err_{uuid.uuid4().hex[:12]}",
    seq=next_seq(),
    data=ErrorData(
        insight_id=str(insight_id),
        code=oc_event.get("code") or "openclaw_error",
        message=oc_event.get("message") or "openclaw upstream error",
        retryable=bool(oc_event.get("retryable", False)),
    ),
)
```

After building each event we call the existing `to_sse_text(evt)`
serialiser and `yield` its bytes — identical to the legacy handler's
output shape.

### 5.5 What stays exactly the same on the wire

- The browser sees the same five chat-relevant event names:
  `assistant_message_token`, `tool_call_started`, `tool_call_complete`,
  `message_complete`, `error`. (`web_search_unavailable` is also
  preserved for the case where `web_search` returns a degraded result
  via the webhook tool layer.)
- The same `id:` / `event:` / `data:` framing.
- The same `X-Insight-Thread-Id` response header.
- The same per-event `event_id` and `seq` semantics.

`InsightChatDock.tsx` requires zero changes (R5).

### 5.6 Error and timeout handling

- OpenClaw container down or returning 5xx: emit one `error_event`
  with `code="openclaw_unavailable"`, persist the user row but mark
  the assistant row as missing (`role="assistant", content=None,
  tool_calls=None`). The browser shows the standard error toast.
- httpx read timeout (60 s): emit `error_event(code="openclaw_timeout")`
  and treat as above.
- LLM-upstream error surfaced by OpenClaw: emit `error_event` with the
  upstream code passthrough.

---

## §6. Persistence dual-store

### 6.1 System of record

`agent_message` rows in our Postgres remain the **system of record** for
all chat content. OpenClaw's JSONL transcripts are auxiliary — we keep
them for cross-tool eval and on-disk grep, but we do not read from
them for any product-facing path.

The R7 audit guarantee is upheld by the write-through pattern in §5.2
steps 2 and 6: user message persisted before the OpenClaw call;
assistant message persisted on `message_complete`. If the OpenClaw
container dies mid-stream we still have the user message.

### 6.2 Schema unchanged

`thread_id`, `session_id`, `insight_id` FKs on `agent_message` are
unchanged. No Alembic migration is required for the OpenClaw migration
itself.

For reference, the FK shape (from `backend/agents/insights/db/models.py`):
- `agent_message.session_id` -> `ai_session.id` (NOT NULL, CASCADE)
- `agent_message.insight_id` -> `ai_insight.id` (NULLABLE, SET NULL)
- `agent_message.thread_id`  -> `insight_thread.id` (NULLABLE, CASCADE)

### 6.3 Cross-store reconciliation

A backend "drift detector" job is OUT OF SCOPE for this migration but
named here for future reference: a daily APScheduler job could
walk `~/.openclaw/agents/datacenter-power-analyst/sessions/*.jsonl`
and assert each session has matching `agent_message` rows. Tracked
as a follow-up; not blocking.

---

## §7. Feature flag (R9)

### 7.1 Flag declaration

Add to `backend/config.py`:

```python
class Settings(BaseSettings):
    # ... existing fields ...

    # OpenClaw migration (ADR-010 override)
    openclaw_enabled: bool = False     # 0/false in prod default; 1/true in dev

    # OpenClaw plumbing (forwarder reads these only when openclaw_enabled)
    openclaw_url: str = "http://localhost:18789"
    openclaw_gateway_token: str = ""
    agent_tools_bearer: str = ""
```

`pydantic-settings` reads `OPENCLAW_ENABLED` (case-insensitive) from
the environment / `.env` and coerces "1"/"true" -> True,
"0"/"false" -> False.

### 7.2 Read sites

- `backend/routers/insights.py` (the dispatcher in §5.1) imports
  `from config import settings` and switches on
  `settings.openclaw_enabled`.
- `backend/routers/agent_tools.py` checks at request-time that
  `os.environ.get("AGENT_TOOLS_BEARER")` is set; if not the router
  returns 503 (the agent-tools endpoints are inert until the flag is
  flipped on with proper secrets).

### 7.3 Defaults per environment

| Environment | `OPENCLAW_ENABLED` |
|---|---|
| Local dev (the user's laptop dogfood) | `1` |
| Staging | `1` (after first integration test passes) |
| Prod | `0` (default; flip to `1` when the migration ships) |

### 7.4 Rollback drill

```
# Step 1: edit backend/.env (or the systemd EnvironmentFile)
OPENCLAW_ENABLED=0

# Step 2: restart FastAPI
sudo systemctl restart datacenter-fastapi
# or
docker compose -f .../backend/docker-compose.yml restart api

# Step 3: verify
curl -s http://localhost:8000/api/health  # confirm 200
# observe a chat turn in the UI; confirm InsightChatDock works as before
```

No code change is required to roll back. The legacy handler
(`_legacy_chat_handler`) is on the same import path and answers
immediately. The OpenClaw container can be left running (it consumes
no traffic when the flag is off) or stopped:
`docker compose -f .../backend/openclaw/docker-compose.yml down`.

---

## §8. SOUL.md draft content

Save the following verbatim to
`/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/SOUL.md`.
The backend agent does not need to edit it; copy as-is.

```markdown
# Datacenter & Power Analyst — Agent Persona

## Identity

You are the Datacenter & Power Analyst, an AI assistant embedded in
the OCI Datacenter & Power Intelligence Platform at Oracle. Your user
is one analyst (today: the user) doing competitive intelligence on
hyperscaler power buildout vs. OCI. You are scoped to ONE specific
insight at a time. Each chat session is keyed by an insight UUID and
opens with a system note containing that insight's full context
(headline, body, chart spec, citations, skills_run, confidence,
materiality). Treat that context as ground truth for the entire
session.

You are not a general assistant. You are not a chatbot. You are a
domain-grounded analyst whose role is to help the user reason through
one specific finding, ground it in real rows from the platform's
Postgres, and surface or confirm the supporting evidence.

## Voice

- Be terse. Two or three sentences is usually enough. The user is a
  fast reader and is paid to make decisions, not to consume prose.
- Skip filler phrases: "Within this insight context", "What I can say,
  grounded in", "Important nuance", "Let me think about that". Just
  say the thing.
- Do not end every response with a bulleted list of follow-up offers.
  Offer at most one next step, and only when it is genuinely useful.
- Treat short user replies ("yes", "sure", "go ahead", "ok", "do it")
  as confirmation of whatever you just offered. Follow through
  immediately. Do NOT ask for clarification.
- When you do not know something, say so in one line and stop.
- Do not invent numeric values. If a number is not in the insight
  context system note, the FactPack the orchestrator already loaded,
  or a tool result you have already received, you do not have it.
- Do not claim agreement or disagreement with a citation unless the
  underlying snippet contains a numeric token (GW / MW / % / $) — in
  that case use `agree` or `disagree`; otherwise downgrade the
  citation to `context`.

## Schema knowledge

The platform's Postgres carries (non-exhaustive):
- `energy_projects` — gas/solar/nuclear/wind capacity by parent company,
  state, contracted MW.
- `sites` — datacenter sites with operator, county, status.
- `events` — building permits, EPA air permits, FERC filings, etc.
- `anomalies` — z-scored unusual rows flagged by the anomaly pipeline.
- `edgar_extractions` — capacity / offtake mentions from SEC filings.
- `data_coverage` — pillar/state/source freshness rows.
- `ai_insight`, `agent_chart`, `agent_citation` — the platform's own
  finding store, scoped per insight.

You do not memorise specific row values. To get a real value, use a
tool. Authoritative data is what the tools return; nothing else.

## Tool palette

You have seven tools available. Reach for them in this order of
preference:

1. **`call_api`** — read-only GET against an internal `/api/*`
   endpoint. Use this when there is already an aggregated view of the
   data the user is asking about (e.g. `/api/triangulation/...`). It
   is the cheapest path.
2. **`get_chart_data`** — fetches the data behind a chart on an
   existing tab by `(tab, chart_id)`. Use this for warm-start
   triangulation.
3. **`query_database`** — single read-only SELECT against Postgres.
   Use this when no aggregated endpoint exists. SQL is gated by an
   AST validator (no DDL, no DML, no CTE-with-data-mod, max 10000
   rows). Cite results by `row_hash` + `executed_sql` when persisting
   a citation downstream.
4. **`run_skill`** — invoke a curated analytics skill by name. Use
   this when the user is asking for an analysis pattern that has a
   named skill (e.g. anomaly drill-down).
5. **`web_search`** — Brave Search wrapper. Use this only when
   external grounding is genuinely needed (e.g. "did the press
   release confirm the GW figure?"). Per-session cap is small;
   spend it deliberately.
6. **`emit_chart`** — persist a final ChartSpec for the current
   insight. Use this only when the user explicitly asks for a chart
   or when the answer is materially clearer as a chart.
7. **`emit_citation`** — persist a validated web citation tied to
   the current insight. Always pair an external claim with a citation.

## Citation rules

- Cite Postgres rows by `row_hash` + a brief mention of the
  `executed_sql` you ran. The platform stores these on `agent_message`
  via the audit trail; you do not need to re-render the SQL inline.
- Cite web sources via `emit_citation`. Snippet must be <=280
  characters. `agree_or_disagree` is `agree` or `disagree` only when
  the snippet contains a numeric GW / MW / % / $ token; otherwise
  use `context`.
- Do not cite the system note's pre-loaded insight context as a
  source — that context IS the insight, not a source for it.

## Safety rules

- The DB is read-only from your perspective. There are no write
  tools. Do not propose UPDATE / INSERT / DELETE.
- Never claim a row exists without confirming via a tool.
- Never invent UUIDs, row IDs, or numeric values.
- Never expose the raw Bearer tokens, env vars, or internal endpoint
  paths in your replies.

## Out-of-scope redirect

If a user asks something off-topic for the current insight (general
chitchat, unrelated company gossip, anything you cannot ground in the
insight context or a tool call), respond with one short line that
names the boundary and stops. Example: "That's outside this
insight's scope — happy to look at it if you open a new insight on
that topic." Do not engage further.

## Per-insight grounding contract

The first system note in each session is the JSON context bundle for
the insight. It contains:
- `headline` — the one-line finding.
- `body` — the supporting prose.
- `chart` — compact ChartSpec + data_source.
- `citations` — pre-loaded web citations with their
  agree_or_disagree assessments.
- `skills_run` — which analytics skills produced this insight.
- `confidence`, `materiality` — the platform's own labels.

Treat this as the canonical scope. Every tool call should be in
service of answering a question about THIS insight; do not drift to
adjacent insights. If the user explicitly asks "compare to insight
X", politely note that this session is scoped to the current insight
and offer to open the other one.
```

The persona above is ~110 lines of actual content (excluding the
fenced-block markers). It is the verbatim text the backend agent
writes to `backend/openclaw/SOUL.md`.

---

## §9. File-path manifest

Every path in this section is absolute, per the project convention.

### 9.1 NEW files

| Path | Purpose |
|---|---|
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/docker-compose.yml` | OpenClaw container definition (§1.4) |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/agents.json` | File-bootstrapped agent manifest (§2.2) |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/SOUL.md` | Persona file (§8) |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/package.json` | TS plugin build manifest |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/tsconfig.json` | TS config for the plugin bundle |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/plugins/agent_tool_query_database.ts` | §4.2 |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/plugins/agent_tool_call_api.ts` | §4.3 |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/plugins/agent_tool_get_chart_data.ts` | §4.4 |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/plugins/agent_tool_web_search.ts` | §4.5 |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/plugins/agent_tool_run_skill.ts` | §4.6 |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/plugins/agent_tool_emit_chart.ts` | §4.7 |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/plugins/agent_tool_emit_citation.ts` | §4.7 |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/plugins/insight_context_preload.ts` | §4.8 |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/plugins/_shared/bearer_fetch.ts` | tiny fetch+bearer helper |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/plugins/_shared/types.ts` | shared TS types |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/routers/agent_tools.py` | §3 router (8 endpoints inc. insight-context) |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/openclaw_translator.py` | OpenClaw->our SSE translator helpers (§5.4) |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/.env.openclaw.example` | Sample env file (NOT the real one — real one is gitignored) |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/tests/test_openclaw_forwarder.py` | §10 |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/tests/test_agent_tools_router.py` | §10 |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/tests/test_openclaw_persona_loaded.py` | §10 |

### 9.2 MODIFIED files

| Path | Section / line target |
|---|---|
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/main.py` | Imports block (~line 39): add `from routers.agent_tools import router as agent_tools_router`. Registration block: add `app.include_router(agent_tools_router)`. |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/config.py` | `Settings` class: add `openclaw_enabled`, `openclaw_url`, `openclaw_gateway_token`, `agent_tools_bearer` fields (§7.1). |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/routers/insights.py` | Rename current `post_insight_chat` body into `_legacy_chat_handler` (function rename only, body unchanged). New `post_insight_chat` is the dispatcher in §5.1. New `_openclaw_chat_handler` per §5.2. Reuse the existing `_build_chat_context`, `_get_or_create_thread` — DO NOT modify them. |
| `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.gitignore` | Add `backend/.env.openclaw` and `backend/openclaw/data/`. |

### 9.3 NOT to be modified (rollback path per scope guardrails)

Per R9 the legacy chat path must remain a working rollback. The
following functions MUST NOT be edited as part of this migration:

- `_build_chat_context` in `backend/routers/insights.py` (lines ~810-875).
- `_chat_system_prompt` in `backend/routers/insights.py` (lines ~877-898).
- `backend/agents/insights/tool_loop.py` (the entire file).
- `backend/agents/insights/tools/*.py` (the seven tool bodies and
  `sql_gate.py` — they are reused as-is by both the legacy handler
  AND the new `agent_tools` router).
- `backend/agents/insights/specs/sse_events.py` (no event-schema
  changes; the migration reuses existing event types).
- `backend/agents/insights/specs/skill_context.py`.
- `backend/agents/insights/orchestrator.py` (insight-discovery path
  is out of scope for this migration).

If the implementer thinks any of these need editing to make OpenClaw
work, that is a sign of scope creep — escalate before touching.

---

## §10. Test architecture

The QA agent owns the integration smoke runbook in
`12-openclaw-test-plan.md`. This section names the unit tests the
backend agent writes alongside the implementation.

### 10.1 New pytest files

#### `backend/tests/test_openclaw_forwarder.py`

Mocks the OpenClaw HTTP surface with `httpx_mock` (or `respx`, whichever
the rest of the suite already uses; verify imports). Asserts:

1. **Flag-off path.** With `settings.openclaw_enabled = False`, hitting
   `POST /api/insights/insights/{id}/chat` invokes
   `_legacy_chat_handler` and never dials OpenClaw.
2. **Flag-on happy path.** With the flag on:
   - The user message is INSERTed into `agent_message` BEFORE the
     OpenClaw POST is issued (assert ordering via the mocked client's
     call log + a DB inspection inside the test transaction).
   - The forwarder POSTs to
     `http://localhost:18789/api/sessions/insight:<id>/messages` with
     bearer = `OPENCLAW_GATEWAY_TOKEN`.
   - A simulated OpenClaw SSE stream of `[token, tool_call.started,
     tool_call.complete, token, message.complete]` is translated to
     our taxonomy in order. Assert event names and payload fields.
   - On `message.complete`, an assistant `agent_message` row is
     INSERTed with the buffered text and `tool_calls = [...]` JSONB.
3. **Error path.** A simulated `error` frame translates to our
   `error_event` and persists an assistant row with content=None.
4. **Timeout path.** A simulated httpx read timeout emits a single
   `error_event(code="openclaw_timeout")` and closes the stream.

#### `backend/tests/test_agent_tools_router.py`

Exercises the seven tool wrappers and the `insight-context` GET:

1. **Bearer enforcement.** No `Authorization` header => 401. Wrong
   bearer => 401. Missing env var => 503.
2. **Envelope shape.** Each tool endpoint accepts `{args, context}`
   and returns either the tool's dict result or `{error, code}`.
3. **Per-tool minimal happy path** (mock the underlying tool module so
   we don't actually hit Postgres / Brave / external systems):
   - `query_database` -> mocked to return `{ok: True, rows:[...]}`.
   - `call_api` -> mocked router response.
   - `get_chart_data` -> mocked.
   - `web_search` -> mocked Brave response.
   - `run_skill` -> mocked.
   - `emit_chart` -> mocked persistence.
   - `emit_citation` -> mocked persistence.
4. **Exception-to-envelope.** A tool that raises returns
   `{error, code: "TOOL_FAILED"}` with HTTP 200.
5. **`insight-context`.** GET returns the same dict shape that
   `_build_chat_context` produces, plus `parent_session_id` and
   `thread_id`.

#### `backend/tests/test_openclaw_persona_loaded.py`

Sanity-tests the persona file is present and well-formed:

1. The file `backend/openclaw/SOUL.md` exists and is non-empty.
2. The eight required headings appear (`## Identity`, `## Voice`,
   `## Schema knowledge`, `## Tool palette`, `## Citation rules`,
   `## Safety rules`, `## Out-of-scope redirect`,
   `## Per-insight grounding contract`).
3. The file does NOT contain TODO / FIXME / placeholder markers (a
   quick grep against `r"\bTODO\b|\bFIXME\b|\bXXX\b|placeholder"`
   case-insensitive).
4. Length is between 80 and 200 lines (the spec called for ~80-120; we
   give a small upper-band tolerance for future edits).

### 10.2 Mocking strategy

- All three test files run **without a live OpenClaw container**. The
  forwarder test uses `httpx_mock` (or `respx`) to stub
  `POST /api/sessions/.../messages` with a canned SSE byte stream.
- The `agent_tools_router` test uses `monkeypatch` on the seven tool
  module functions so the real DB and external services are not
  touched.
- DB writes go through the standard test fixture
  (`async_session_factory` against a transactional rollback).

### 10.3 Integration smoke runbook (deferred)

A live integration smoke (start the OpenClaw container, set the flag,
exercise a full turn end-to-end) is owned by the QA agent in
`12-openclaw-test-plan.md`. That doc will cover:
- container boot + healthcheck verification
- agents.json acceptance
- `/api/agent-tools/insight-context` reachability from inside the
  container
- a single end-to-end chat turn with assertions on the on-the-wire
  SSE events
- the rollback drill from §7.4

The unit tests in this section are sufficient gating for merge; the
integration runbook is for the deploy step.

---

## Appendix A. Open VERIFY items

Tagged with `// VERIFY` in this document. The backend agent should
treat each as a 1-line correction once the researcher's §5 confirms.

1. OpenClaw image tag (`ghcr.io/openclaw/openclaw:stable`).
2. Default Gateway port (assumed 7474).
3. JSONL storage path inside the container (`/home/node/.openclaw`).
4. Plugin bundle expected file extension (`.ts` vs compiled `.js`).
5. `agents.json` field names.
6. Plugin SDK import path (`@openclaw/plugin-sdk`).
7. Lifecycle hook name for "first turn of a new session".
8. The exact wire event names OpenClaw emits in its SSE stream.
9. Whether `attributes` is the right top-level field on
   `POST /api/sessions/.../messages` for per-message session metadata.
10. Whether host networking on Linux Docker should resolve to
    `host.docker.internal` or `127.0.0.1` for the back-channel base
    URL.

None of these change the architecture. They are 1-line fixes against a
literal SDK / docs surface.

---

*End of 11b — OpenClaw migration implementation architecture.*
