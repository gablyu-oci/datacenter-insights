# 11c - OpenClaw Migration: Addendum (researcher reconciliation)

> **§G (TypeScript extension scaffold) is ABANDONED as of ADR-13
> (`13-mcp-migration.md`, 2026-05-06).** Tool routing has migrated to a
> native Python MCP server on FastAPI; `.openclaw/extensions/insights-tools/`
> has been deleted. All other sections in this addendum (§A Docker,
> §B REST API, §C session key, §D agent, §E SOUL.md location, §F provider
> config, §H bootstrap hook) remain authoritative.

**Status:** Authoritative override of any conflicting items in `11b-openclaw-migration-architecture.md`.
**Date:** 2026-05-05
**Reason:** The architect doc was written from ADR-010's component map, which predated full Docker/REST-API verification. Researcher's `/tmp/openclaw_integration_research.md` confirmed several wire-format details from primary sources (docs.openclaw.ai + GitHub `docker-compose.yml`). Where this addendum and 11b disagree, **this addendum wins**.

---

## A. Docker — corrected

| Field | 11b said | Truth (verified) |
|---|---|---|
| Image tag | `ghcr.io/openclaw/openclaw:stable` (with VERIFY) | `ghcr.io/openclaw/openclaw:latest` |
| Container port | `7474` | `18789` (container's gateway port; bridge `18790` not used) |
| Host port | `18789` | `7474` (per user spec R1: "suggest 7474, but check if free" — checked, free) |
| Port mapping | `7474:18789` (inverted) | `7474:18789` interpreted as **host 7474 → container 18789** |
| Network mode | `host` | `bridge` (default) + `extra_hosts: ["host.docker.internal:host-gateway"]` so plugins can reach FastAPI on the host |
| Container HOME | unspecified | `/home/node` |

**Mounts (host → container):**
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw` → `/home/node/.openclaw`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/workspace` → `/home/node/.openclaw/workspace`

**Healthcheck:** `GET http://127.0.0.1:18789/healthz` (NOT `/api/status`).

---

## B. REST API — corrected (this is the most important change)

**11b assumed** `POST /api/sessions/{key}/messages`. **That endpoint does not exist.**

**Real chat path (OpenAI-compatible):**

```
POST http://localhost:7474/v1/chat/completions
Headers:
  Authorization: Bearer ${OPENCLAW_GATEWAY_TOKEN}
  Content-Type: application/json
  x-openclaw-session-key: agent:main:insight:<INSIGHT_ID>
Body:
  {
    "model": "openclaw/default",
    "messages": [{"role": "user", "content": "<user text>"}],
    "stream": true
  }
```

**Response:** `Content-Type: text/event-stream`. Frames are `data: <json>` where `<json>` is OpenAI `chat.completion.chunk` shape:

```json
{"id":"...","choices":[{"index":0,"delta":{"content":"text"},"finish_reason":null}]}
```

Terminator: `data: [DONE]`.

**SSE → our taxonomy translation table:**

| Chunk shape | Our event |
|---|---|
| `choices[0].delta.content` non-empty | `assistant_message_token` |
| `choices[0].delta.tool_calls[0]` first appearance with `id`+`function.name` | `tool_call_started` |
| `choices[0].finish_reason == "tool_calls"` (or post-tool-result frame) | `tool_call_complete` |
| `choices[0].finish_reason == "stop"` then `data: [DONE]` | `message_complete` |
| Error JSON in `data:` frame OR HTTP non-2xx | `error_event` |

**Backend agent: capture a real session's raw SSE during smoke and lock the precise mapping in `backend/openclaw/sse_translator.py`.**

---

## C. sessionKey — corrected

**11b said** `insight:<INSIGHT_ID>`. **Researcher recommends** `agent:main:insight:<INSIGHT_ID>` to match the documented `agent:<agentId>:<mainKey>` pattern. Use the longer form everywhere.

---

## D. Agent provisioning — simplified

**11b assumed** a custom agent named `datacenter-power-analyst` provisioned via `backend/openclaw/agents.json`. **Researcher found** there is no REST agent-create endpoint and the default `agentId="main"` is sufficient for our single-purpose use.

**Use the default `main` agent.** SOUL.md goes at `~/.openclaw/workspace/SOUL.md` (workspace root, NOT under `agents/<id>/`) and is auto-injected by OpenClaw on every turn. No manual config wiring needed for SOUL.md discovery.

If the backend agent later wants to use a custom agent name, that is done via CLI inside the container:
```
docker exec openclaw-gateway openclaw agents add insights --workspace /home/node/.openclaw/workspace
```
For v1, do NOT do this — keep `main`.

---

## E. SOUL.md location — corrected

| 11b said | Truth |
|---|---|
| `backend/openclaw/SOUL.md` mounted into agent dir | `${REPO}/.openclaw/workspace/SOUL.md` (mounted as `/home/node/.openclaw/workspace/SOUL.md`) |

The §8 SOUL.md draft content from 11b is fine — copy it verbatim. The TARGET PATH changes only.

For the test in `test_openclaw_persona_loaded.py`, assert `Path(".openclaw/workspace/SOUL.md").exists()` and grep for the persona signature line.

---

## F. Provider config — concrete

`/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/openclaw.json` (JSON5):

```json5
{
  models: {
    providers: {
      llamastack: {
        baseUrl: "https://llama-stack.ai-apps-ord.oci-incubations.com/v1",
        apiKey: "${LLAMA_STACK_API_KEY}",
        api: "openai-completions",
        request: { allowPrivateNetwork: true },
        timeoutSeconds: 300,
        models: [{
          id: "openai.gpt-5.4",
          name: "OCI GPT-5.4 via Llama Stack",
          reasoning: false,
          input: ["text"],
          contextWindow: 128000,
          maxTokens: 8192,
        }],
      },
    },
  },
  agents: {
    defaults: { model: { primary: "llamastack/openai.gpt-5.4" } },
  },
  gateway: { auth: { mode: "token", token: "${OPENCLAW_GATEWAY_TOKEN}" } },
}
```

The reference string OpenClaw sends to Llama Stack is `models[0].id = "openai.gpt-5.4"`. The `llamastack/openai.gpt-5.4` form is OpenClaw's internal `provider/model` ref; OpenClaw does NOT send the `llamastack/` prefix to the upstream provider.

---

## G. Plugin SDK — corrected

| 11b said | Truth |
|---|---|
| Plugin shape via pseudocode with VERIFY tags | Real SDK is `openclaw/plugin-sdk/<subpath>` (in-package, not separate npm) |
| Plugin location `backend/openclaw/plugins/` | Acceptable for source storage; runtime location is `${REPO}/.openclaw/extensions/insights-tools/` (mounted to `/home/node/.openclaw/extensions/insights-tools/`) |

**Working entry point shape:**

```typescript
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { Type } from "@sinclair/typebox";

export default definePluginEntry({
  id: "insights-tools",
  name: "OCI Insights Tools",
  description: "Routes insights chat tools back to FastAPI wrappers",
  register(api) {
    // capture per-toolCallId session ctx via before_tool_call hook
    const ctxByCallId = new Map<string, {sessionKey: string, agentId: string}>();
    api.registerHook("before_tool_call", async (event, ctx) => {
      ctxByCallId.set(event.toolCallId, {sessionKey: ctx.sessionKey, agentId: ctx.agentId});
      return undefined;  // do not block
    });

    // R6 pre-load
    api.registerHook("agent:bootstrap", async (event, ctx) => {
      if (!ctx.sessionKey?.startsWith("agent:main:insight:")) return undefined;
      const insightId = ctx.sessionKey.split(":").pop();
      const resp = await fetch(`http://host.docker.internal:8000/api/agent-tools/insight-context?insight_id=${insightId}`, {
        headers: { Authorization: `Bearer ${process.env.AGENT_TOOLS_BEARER}` }
      });
      if (!resp.ok) return undefined;
      const ctxJson = await resp.json();
      event.context.bootstrapFiles.push({
        path: "INSIGHT_CONTEXT.md",
        content: `# Insight context (auto-loaded)\n\n${JSON.stringify(ctxJson, null, 2)}`,
        gate: "always",
      });
      return undefined;
    });

    // tool example
    api.registerTool({
      name: "query_database",
      description: "Run a SELECT against the OCI DC&P platform Postgres",
      parameters: Type.Object({ sql: Type.String() }),
      async execute(toolCallId, params) {
        const ctx = ctxByCallId.get(toolCallId);
        const resp = await fetch("http://host.docker.internal:8000/api/agent-tools/query_database", {
          method: "POST",
          headers: {
            Authorization: `Bearer ${process.env.AGENT_TOOLS_BEARER}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            args: params,
            context: ctx ? {
              session_key: ctx.sessionKey,
              insight_id: ctx.sessionKey.split(":").pop(),
            } : {},
          }),
        });
        const data = await resp.json();
        return { content: [{ type: "text", text: JSON.stringify(data) }] };
      },
    });
    // ... other 6 tools follow the same template
  },
});
```

**Required sibling files** in `${REPO}/.openclaw/extensions/insights-tools/`:
- `package.json` with `openclaw.extensions: ["./index.ts"]`, deps: `@sinclair/typebox`
- `openclaw.plugin.json` with `id: "insights-tools"`, `configSchema: {}` (minimum)
- `index.ts` (the entry above; will likely be split into one file per tool with shared helpers)

**Discovery:** files in `/home/node/.openclaw/extensions/insights-tools/` are auto-loaded by OpenClaw on boot. No additional config required.

---

## H. R6 hook — concrete

Use `agent:bootstrap` hook (mutation event, fires before bootstrap files are injected). Pseudocode in §G above. Fallback if needed: write a `custom_message` JSONL entry directly into `~/.openclaw/agents/main/sessions/<sessionId>.jsonl`.

---

## I. Updated file-path manifest (overrides 11b §9)

**NEW files (host paths):**
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/openclaw.json`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/workspace/SOUL.md`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/extensions/insights-tools/package.json`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/extensions/insights-tools/openclaw.plugin.json`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/extensions/insights-tools/index.ts`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/extensions/insights-tools/tools/{query_database,call_api,get_chart_data,web_search,run_skill,emit_chart,emit_citation}.ts`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/extensions/insights-tools/hooks/insight_context_preload.ts`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/routers/agent_tools.py`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/__init__.py`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/forwarder.py`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/sse_translator.py`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docker-compose.openclaw.yml`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/tests/test_openclaw_forwarder.py`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/tests/test_agent_tools_router.py`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/tests/test_openclaw_persona_loaded.py`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/plans/ai-insights-automation/12-openclaw-test-plan.md`

**MODIFIED files:**
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/main.py` — register `agent_tools_router`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/config.py` — add `openclaw_enabled`, `openclaw_gateway_url`, `openclaw_gateway_token`, `agent_tools_bearer`, `llama_stack_api_key`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/routers/insights.py` — branch `post_insight_chat` on `settings.openclaw_enabled`; rename current body to `_legacy_chat_handler`; add `_openclaw_chat_handler` calling `backend.openclaw.forwarder.forward()`
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/.env.example` — document new env vars

**DO NOT MODIFY (rollback path — scope guardrail):**
- `_build_chat_context` (insights.py)
- `_chat_system_prompt` (insights.py)
- `tool_loop.py`
- The 7 tool implementations under `backend/agents/insights/tools/`
- `sse_events.py` schema

**Deferred (later infra agent decision):**
- Whether to use a `docker-compose.yml` add-on file or a systemd unit; the addendum picks `docker-compose.openclaw.yml` so the gateway can be started with `docker compose -f docker-compose.openclaw.yml up -d` and added to the host's existing systemd-managed compose target.

---

## J. host.docker.internal vs 127.0.0.1

In `bridge` networking + `extra_hosts: ["host.docker.internal:host-gateway"]`, plugins inside the container reach the FastAPI process on the host via `http://host.docker.internal:8000`. **Use this URL in plugin code, not `127.0.0.1`** (which would refer to the container itself).

The forwarder (FastAPI process talking to OpenClaw) reaches the gateway via `http://localhost:7474` (host port).

---

## K. One-page implementation order for the backend agent

1. Add config knobs in `backend/config.py`.
2. Build `backend/routers/agent_tools.py` (7 + 1 endpoints, bearer auth) — testable in isolation.
3. Build `backend/openclaw/sse_translator.py` (chunk → our event).
4. Build `backend/openclaw/forwarder.py` (httpx async POST to `/v1/chat/completions`, stream translation, agent_message write-through).
5. Wire `post_insight_chat` to branch on `settings.openclaw_enabled`. Rename existing body to `_legacy_chat_handler`. Add `_openclaw_chat_handler` calling forwarder.
6. Author `${REPO}/.openclaw/workspace/SOUL.md` from 11b §8.
7. Author `${REPO}/.openclaw/openclaw.json` from §F above.
8. Author the TS plugin (`index.ts` + 7 per-tool files + bootstrap hook + `package.json` + `openclaw.plugin.json`).
9. Hand off to infra agent for `docker-compose.openclaw.yml`.
10. Hand off to QA agent for tests + smoke runbook.

---

*End of addendum.*
