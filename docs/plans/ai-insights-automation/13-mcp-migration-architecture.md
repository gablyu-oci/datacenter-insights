# Architecture: MCP Server Migration (implementation-ready)

**Status:** Active. Implementation contract for `13-mcp-migration-prd.md`.
**Date:** 2026-05-06
**Owner:** Architect
**Reads:**
- `docs/plans/ai-insights-automation/13-mcp-migration-prd.md`
- `docs/plans/ai-insights-automation/13-mcp-migration-research.md`
- `docs/plans/ai-insights-automation/11a-openclaw-migration-prd.md`
- `docs/plans/ai-insights-automation/11c-openclaw-migration-addendum.md`

This doc is code-ready. The backend agent should not need to make design
decisions — only translate this to code.

---

## §1. Component diagram

```
                          OpenClaw lane (OPENCLAW_ENABLED=1)
                          --------------------------------------
   the user ── React dock ── POST /api/insights/<id>/chat ──┐
                                                         │
                                                         ▼
                                       backend.openclaw.forwarder
                                                         │
                            POST /v1/chat/completions    │
                            (OpenAI-compat, SSE)         ▼
   ┌────────────────────────────────────────────────────────────┐
   │  OpenClaw gateway (Docker, host-port 7474, container 18789) │
   │   - reads .openclaw/openclaw.json                            │
   │   - discovers MCP server "oci-insights" -> http://host.docker│
   │     .internal:8000/mcp                                       │
   └─────────────────────────────────┬──────────────────────────┘
                                     │  streamable-HTTP + Bearer
                                     │  Authorization: Bearer ${AGENT_TOOLS_BEARER}
                                     ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  FastAPI (uvicorn, host:8000)                                 │
   │                                                                │
   │   app.mount("/mcp", _mcp_subapp)  <-- AuthenticationMiddleware │
   │                                       (StaticBearer backend)   │
   │                                                                │
   │   _mcp_subapp = FastMCP(...).streamable_http_app()             │
   │                                                                │
   │   @mcp.tool() handlers in backend/mcp_server.py:               │
   │     query_database, call_api, get_chart_data, web_search,      │
   │     run_skill, emit_chart, emit_citation                       │
   │                          │                                     │
   │                          ▼                                     │
   │   skill_ctx_factory.build_skill_ctx(db, insight_id, ...)       │
   │                          │                                     │
   │                          ▼                                     │
   │   agents.insights.tools.registry.dispatch(name, args, ctx)     │
   │                          │                                     │
   │       ┌──────────────────┼─────────────────┬───────────────┐   │
   │       ▼                  ▼                 ▼               ▼   │
   │   sql_gate +         /api/* (loop-      Brave Search    Postgres│
   │   Postgres           back call_api)     (web_search)    (charts/│
   │   (query_database)                                        cites)│
   └──────────────────────────────────────────────────────────────┘

                          Legacy lane (OPENCLAW_ENABLED=0, rollback target)
                          ------------------------------------------------
   the user ── React dock ── POST /api/insights/<id>/chat ──┐
                                                         ▼
                              ToolLoopDriver (in-process, untouched)
                                                         │
                                                         ▼
                              registry.dispatch(...) ── tools/*.py
```

The MCP path and the legacy `ToolLoopDriver` path share **only** the leaf
tool implementations under `backend/agents/insights/tools/*.py` and
`sql_gate.validate_sql`. They never share runtime state. With
`OPENCLAW_ENABLED=0` no traffic touches `/mcp`.

The HTTP wrapper router `backend/routers/agent_tools.py` is **kept**
for direct curl-testing and as a parallel path the existing tests still
exercise. It is not on the OpenClaw chat-call hot path anymore.

---

## §2. File layout

| Path | Status | Purpose |
|---|---|---|
| `backend/mcp_server.py` | NEW | FastMCP instance, 7 `@mcp.tool()` handlers, `StaticBearer` middleware, `mount_mcp(app)` helper. |
| `backend/agents/insights/skill_ctx_factory.py` | NEW | Houses `build_skill_ctx()` and `_noop_emit_event` (extracted from `agent_tools.py`). |
| `backend/main.py` | MODIFIED | Imports `mount_mcp` and calls it after router registration. |
| `backend/routers/agent_tools.py` | MODIFIED (1-line) | Imports `build_skill_ctx` from the factory; deletes its inline copy. |
| `backend/pyproject.toml` | MODIFIED | Adds `mcp>=1.27,<2`. |
| `backend/uv.lock` | REGENERATED | `uv lock` after pyproject edit. |
| `.openclaw/openclaw.json` | MODIFIED | Adds `mcp.servers.oci-insights` block. |
| `.openclaw/extensions/insights-tools/` | DELETED | Abandoned TS scaffold (PRD F7, AC7). |
| `backend/tests/test_mcp_server.py` | NEW | 8 tests, names per §8. |
| `docs/plans/ai-insights-automation/ADR-013-mcp-vs-ts-plugin.md` | NEW (last step) | The decision record (PRD F8 / AC9). |
| `backend/agents/insights/tools/*.py` | UNCHANGED | Tool bodies (NG3). |
| `backend/agents/insights/sql_gate.py` | UNCHANGED | SELECT-only AST validator. |
| `backend/openclaw/forwarder.py` | UNCHANGED | Already streams the `/v1/chat/completions` SSE; tool dispatch is now MCP-side. |

---

## §3. The 7 MCP tools — handler signatures

All seven handlers live in `backend/mcp_server.py`. They share these
conventions:

- **First positional arg is `insight_id: str`.** OpenClaw's MCP client at
  the SDK version we pin does not give the handler a clean read on
  per-session HTTP headers (see §4). So the LLM passes `insight_id`
  explicitly. The persona's bootstrap context (per the PRD §4 F8 /
  agent:bootstrap pre-load) makes the current `insight_id` visible in
  the system prompt, and the tool descriptions instruct the model to
  echo it on every call.
- **Optional `thread_id` and `session_id`** are supported on every
  handler so the per-tool MCP call can override the values
  `build_skill_ctx` would otherwise look up from Postgres. They are
  optional in the FastMCP-derived `inputSchema` because the Python
  type is `str | None = None`.
- **Return type is `dict`.** FastMCP wraps a returned dict in a single
  `TextContent` automatically (researcher §1, "Tool result shape"). We
  pick this over the explicit `[TextContent(...)]` shape because (a)
  the tool bodies already return JSON-serialisable dicts, (b) it keeps
  the handler bodies a one-liner around `dispatch(...)`, and (c) the
  OpenClaw-side parser reads `content[0].text` either way.
- **Error envelope is `{ok: false, error, code: "TOOL_FAILED"}`** —
  same shape `_invoke_tool` already returns in `agent_tools.py`. We
  do **not** raise from the handler on tool-body failure; raises would
  get translated to MCP `isError=true` envelopes which OpenClaw
  presents to the model as a different shape than the JSON-dict error
  the legacy lane uses. Keep them aligned.

The handler skeleton, used by all 7:

```python
@mcp.tool()
async def <tool_name>(
    insight_id: str,
    <tool-specific args>,
    thread_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """<description copied from TOOL_DEFS>"""
    return await _invoke("<tool_name>", insight_id,
                         {"<arg1>": ..., "<arg2>": ...},
                         thread_id=thread_id, session_id=session_id)
```

Where `_invoke` is the shared helper in `mcp_server.py`:

```python
async def _invoke(name, insight_id, args, *, thread_id, session_id) -> dict:
    try:
        insight_uuid = uuid.UUID(insight_id)
    except (ValueError, TypeError) as exc:
        return {"ok": False, "error": f"bad_insight_id: {exc}",
                "code": "TOOL_FAILED"}
    db = async_session_factory()
    try:
        ctx = await build_skill_ctx(db, insight_id=insight_uuid,
                                     thread_id_hint=thread_id,
                                     session_id_hint=session_id)
        await db.commit()
        from agents.insights.tools.registry import dispatch
        result = await dispatch(name, args, ctx)
        return {"ok": True, "result": result}
    except Exception as exc:
        logger.exception("mcp.invoke_failed", extra={"tool": name})
        await _safe_rollback(db)
        return {"ok": False, "error": str(exc), "code": "TOOL_FAILED"}
    finally:
        try: await db.close()
        except Exception: pass
```

### 3.1 query_database

```python
@mcp.tool()
async def query_database(
    insight_id: str,
    sql: str,
    max_rows: int = 10000,
    thread_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Run a single read-only SELECT against the strategic-insights Postgres.
    Returns rows + row_hash + executed_sql. Max 10000 rows."""
    return await _invoke("query_database", insight_id,
                         {"sql": sql, "max_rows": max_rows},
                         thread_id=thread_id, session_id=session_id)
```

`sql_gate.validate_sql` continues to run inside the tool body (NG3 / F2).

### 3.2 call_api

```python
@mcp.tool()
async def call_api(
    insight_id: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
    thread_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Invoke an internal /api/ endpoint in-process. GET only.
    Use for fetching aggregated views from the existing routers."""
    return await _invoke("call_api", insight_id,
                         {"endpoint": endpoint, "params": params or {}},
                         thread_id=thread_id, session_id=session_id)
```

### 3.3 get_chart_data

```python
@mcp.tool()
async def get_chart_data(
    insight_id: str,
    tab: str,
    chart_id: str,
    thread_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Fetch the data behind a known chart on an existing tab.
    Use for warm-start triangulation."""
    return await _invoke("get_chart_data", insight_id,
                         {"tab": tab, "chart_id": chart_id},
                         thread_id=thread_id, session_id=session_id)
```

### 3.4 web_search

```python
@mcp.tool()
async def web_search(
    insight_id: str,
    query: str,
    n: int = 5,
    thread_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """V2: run a Brave Search query and return up to 5 results.
    Per-session cap: 8 calls. Snippets are pre-truncated to 280 characters.
    If the API key is missing or the upstream circuit is open, the tool
    returns degraded=true with a reason."""
    return await _invoke("web_search", insight_id,
                         {"query": query, "n": n},
                         thread_id=thread_id, session_id=session_id)
```

### 3.5 run_skill

```python
@mcp.tool()
async def run_skill(
    insight_id: str,
    skill_name: str,
    inputs: dict[str, Any],
    thread_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Invoke a converted analytics skill. The dispatcher injects the skill's
    process fragment + RAG chunks for the next reasoning turn only."""
    return await _invoke("run_skill", insight_id,
                         {"skill_name": skill_name, "inputs": inputs},
                         thread_id=thread_id, session_id=session_id)
```

`skill_name` enum constraint from `TOOL_DEFS` is documented in the
docstring instead of the type annotation; FastMCP would otherwise need
a `Literal[...]` of the 15 names which couples the MCP server module
to `ALL_SKILLS` at import time. Validation already happens inside
`run_skill`'s body — leave it there.

### 3.6 emit_chart

```python
@mcp.tool()
async def emit_chart(
    insight_id: str,
    spec: dict[str, Any],
    thread_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Emit a final ChartSpec for the current insight. The spec is validated
    and the row_hash recomputed at server side."""
    return await _invoke("emit_chart", insight_id,
                         spec,  # <- the spec IS the args dict
                         thread_id=thread_id, session_id=session_id)
```

`emit_chart`'s input is a free-form ChartSpec object (see TOOL_DEFS
`additionalProperties: True`). FastMCP would normally introspect a
typed Python signature; here we pass `spec: dict[str, Any]` and the
generated `inputSchema` will be `{type: "object", additionalProperties: true}`.
That matches the OpenAI shape.

### 3.7 emit_citation

```python
@mcp.tool()
async def emit_citation(
    insight_id: str,
    url: str,
    title: str,
    snippet: str,
    agree_or_disagree: str,
    rationale: str,
    search_query: str,
    thread_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """V2: persist + emit a validated web citation for the current insight.
    Validates snippet <=280 chars, agree_or_disagree enum, URL reachability
    (HEAD 2xx/3xx), and rationale-substring-of-snippet. agree/disagree tags
    require a numeric GW/MW/%/$ token in the snippet else are downgraded to
    'context'."""
    return await _invoke("emit_citation", insight_id,
                         {"url": url, "title": title, "snippet": snippet,
                          "agree_or_disagree": agree_or_disagree,
                          "rationale": rationale,
                          "search_query": search_query},
                         thread_id=thread_id, session_id=session_id)
```

`agree_or_disagree` enum is enforced inside the tool body, not in the
MCP schema, for the same reason as `skill_name`.

---

## §4. Bearer auth flow

### 4.1 Where it lives

A Starlette `AuthenticationMiddleware` with a `StaticBearer` backend is
attached **only** to the mounted MCP sub-app. It is not added to the
parent FastAPI `app`, because that would re-shape auth on every other
existing route (we already protect the FastAPI surface differently
elsewhere).

### 4.2 Exact mounting pattern (avoids issue #1367 path-doubling)

```python
# backend/mcp_server.py (excerpt)
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.authentication import (
    AuthenticationBackend, AuthenticationError,
    AuthCredentials, SimpleUser,
)
from starlette.routing import Mount
import hmac, os

mcp = FastMCP(
    "oci-insights",
    json_response=True,
    stateless_http=True,   # researcher §5: simpler, avoids per-session bloat
)

# ... @mcp.tool() decorators ...

class StaticBearer(AuthenticationBackend):
    async def authenticate(self, conn):
        expected = os.environ.get("AGENT_TOOLS_BEARER", "") or ""
        if not expected:
            # Fail closed - mirror agent_tools.py _require_bearer.
            raise AuthenticationError("agent_tools_bearer_not_configured_503")
        h = conn.headers.get("Authorization", "")
        if not h.startswith("Bearer "):
            raise AuthenticationError("missing_bearer")
        token = h[7:]
        if not hmac.compare_digest(token.encode("utf-8"),
                                    expected.encode("utf-8")):
            raise AuthenticationError("invalid_bearer")
        return AuthCredentials(["authenticated"]), SimpleUser("openclaw")

def _on_auth_error(conn, exc: AuthenticationError):
    # Translate the sentinel string into the right HTTP status.
    detail = str(exc)
    status = 503 if detail.endswith("_503") else 401
    from starlette.responses import JSONResponse
    return JSONResponse({"detail": detail.removesuffix("_503")},
                        status_code=status)

def mount_mcp(app):
    """Wire the MCP streamable-HTTP sub-app under /mcp on the FastAPI app.

    Mount pattern: build the streamable-HTTP ASGI app, wrap it in a
    Starlette parent that holds the auth middleware, then mount THAT
    parent at /mcp on FastAPI. This sidesteps the /mcp/mcp doubling
    in issue #1367 because we use http_app(path='/') to strip the
    inner /mcp prefix.
    """
    # path='/' strips the inner /mcp prefix that streamable_http_app()
    # would otherwise add. researcher §2 "Path collision warning".
    inner = mcp.streamable_http_app()  # Starlette app, routes at '/mcp'
    # If `http_app(path="/")` is the documented variant on the pinned
    # SDK, prefer it. Otherwise: re-route the inner app under '/' by
    # mounting it inside a sub-Starlette and consuming /mcp at the
    # parent.
    sub = Starlette(
        routes=[Mount("/", app=inner)],
        lifespan=inner.router.lifespan_context,
        middleware=[],
    )
    sub.add_middleware(
        AuthenticationMiddleware,
        backend=StaticBearer(),
        on_error=_on_auth_error,
    )
    # Lifespan plumbing: the parent FastAPI must inherit the inner
    # lifespan or streamable-HTTP raises "Task group is not initialized"
    # on first request (researcher §2). FastAPI does not auto-discover
    # mounted lifespans, so we attach explicitly.
    _attach_lifespan(app, inner.router.lifespan_context)
    app.mount("/mcp", sub)


def _attach_lifespan(app, lifespan_ctx):
    """Compose the MCP sub-app's lifespan with the FastAPI app's existing
    lifespan handler so neither is dropped."""
    existing = app.router.lifespan_context
    @asynccontextmanager
    async def combined(app_ref):
        async with lifespan_ctx(app_ref):
            async with existing(app_ref):
                yield
    app.router.lifespan_context = combined
```

### 4.3 Behaviour parity with `_require_bearer`

| Condition | `agent_tools.py` | `mcp_server.py` |
|---|---|---|
| `AGENT_TOOLS_BEARER` env unset / empty | 503 `agent_tools_bearer_not_configured` | 503 `agent_tools_bearer_not_configured` |
| Header missing | 401 `missing_bearer` | 401 `missing_bearer` |
| Header wrong value | 401 `invalid_bearer` | 401 `invalid_bearer` |
| Header correct | passes | passes |

Constant-time compare via `hmac.compare_digest` on both sides.

### 4.4 Final external URL

After the mount, OpenClaw posts MCP framing to
`http://host.docker.internal:8000/mcp` (no trailing slash). Per
researcher §5 "Trailing-slash redirect", the SDK may 307 to `/mcp/` —
the OpenClaw HTTP client follows redirects, so this is benign. If the
backend agent observes the redirect being rejected, change the
openclaw.json URL to the trailing-slash form and document.

---

## §5. SkillContext factory — refactor

Move the existing helpers from `backend/routers/agent_tools.py` to a
new module so both that router and `mcp_server.py` import them:

**New file `backend/agents/insights/skill_ctx_factory.py`:**

```python
"""SkillContext factory shared by the agent_tools HTTP router and the
MCP server. Behaviour is the EXACT code lifted from
backend/routers/agent_tools.py; do not edit."""
from __future__ import annotations
import uuid
from typing import Any, Optional
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

async def _noop_emit_event(_evt: Any) -> None:
    return None

async def build_skill_ctx(
    db: AsyncSession,
    *,
    insight_id: uuid.UUID,
    thread_id_hint: Optional[str],
    session_id_hint: Optional[str],
) -> Any:
    # ... identical body to today's _build_skill_ctx ...
```

**Modify `backend/routers/agent_tools.py`:**

- Delete the inline `_build_skill_ctx` (lines 129-190 in the current
  file) and the `_noop_emit_event` (lines 119-126).
- Add at top: `from agents.insights.skill_ctx_factory import build_skill_ctx`
- Replace the call site `_build_skill_ctx(...)` with `build_skill_ctx(...)`.

This is the **only** refactor accepted in this migration. No other
edits to `agent_tools.py` are sanctioned by this architecture.

---

## §6. Schema mapping table

| Tool | OpenAI-shape JSON Schema (TOOL_DEFS) | FastMCP handler signature | Notes |
|---|---|---|---|
| `query_database` | `{sql: string (req), max_rows: int (def 10000, max 10000)}` | `(insight_id, sql, max_rows=10000, thread_id=None, session_id=None)` | `sql_gate.validate_sql` runs in body; MCP never sees raw SQL bypassed |
| `call_api` | `{endpoint: string (req), params: object (def {})}` | `(insight_id, endpoint, params=None, thread_id=None, session_id=None)` | `params` defaults to `None` in Python, normalised to `{}` in `_invoke` |
| `get_chart_data` | `{tab: string (req), chart_id: string (req)}` | `(insight_id, tab, chart_id, thread_id=None, session_id=None)` | Straight 1:1 |
| `web_search` | `{query: string (req), n: int (def 5, 1..5)}` | `(insight_id, query, n=5, thread_id=None, session_id=None)` | Range constraint enforced in body |
| `run_skill` | `{skill_name: enum[15], inputs: object}` | `(insight_id, skill_name, inputs, thread_id=None, session_id=None)` | enum validated in body, not in MCP schema (avoids module-load coupling) |
| `emit_chart` | `{*: any}` (free-form ChartSpec) | `(insight_id, spec: dict[str, Any], thread_id=None, session_id=None)` | `spec` IS the args dict; FastMCP renders `additionalProperties: true` |
| `emit_citation` | `{url, title, snippet (<=280), agree_or_disagree (enum), rationale, search_query}` (all req) | `(insight_id, url, title, snippet, agree_or_disagree, rationale, search_query, thread_id=None, session_id=None)` | enum + length validated in body |

**Note on the extra args.** `insight_id` appears in every tool's
`inputSchema` as a required `string`. `thread_id` and `session_id`
appear as optional nullable strings. This means OpenClaw will see
9-10 input fields per tool instead of the 1-7 the OpenAI schema
suggests. That is acceptable — the LLM will fill `insight_id` from
the system-prompt context every turn (the `agent:bootstrap` hook
front-loaded the insight_id into the persona context per the parent
PRD §F4), and `thread_id`/`session_id` are typically omitted.

---

## §7. .openclaw/openclaw.json patch

Add an `mcp.servers` block. Preserve every existing key. The diff:

```diff
 {
   "models": { ... unchanged ... },
   "agents":  { ... unchanged ... },
   "gateway": { ... unchanged ... },
+  "mcp": {
+    "servers": {
+      "oci-insights": {
+        "url": "http://host.docker.internal:8000/mcp",
+        "transport": "streamable-http",
+        "headers": {
+          "Authorization": "Bearer ${AGENT_TOOLS_BEARER}"
+        }
+      }
+    }
+  },
   "meta": { ... bump lastTouchedAt to migration date ... }
 }
```

**`host.docker.internal` substitution:** `docker-compose.openclaw.yml`
already maps `extra_hosts: ["host.docker.internal:host-gateway"]`
(addendum 11c §A), so this URL resolves from inside the gateway
container to the host's FastAPI on port 8000.

**Env var substitution in headers:** OpenClaw substitutes
`${ENV_VAR}` in JSON5 config values at boot, including header values
(researcher §3 doc-snippet showed exactly this pattern). The
`AGENT_TOOLS_BEARER` env var must be set in the gateway container's
environment (already wired via `docker-compose.openclaw.yml`'s
`environment:` block — confirm during smoke).

**Verification at boot:** the gateway prints a discovery log of the
form `MCP server "oci-insights" discovered N tools`. AC4 requires
N=7. If the discovery line is absent or N != 7, the gateway is
rejecting the streamable-HTTP handshake; the backend agent should
curl `/mcp` directly with the bearer to bisect.

---

## §8. Test architecture

**File:** `backend/tests/test_mcp_server.py`

**Approach:** Tests run against the in-process FastAPI app via
`httpx.AsyncClient(transport=httpx.ASGITransport(app=app))`. We do
**not** spin up a live OpenClaw container in unit tests. The official
`mcp` Python client (`mcp.ClientSession` + `streamablehttp_client`)
expects a real HTTP transport and is hard to plumb through
`ASGITransport` — so for protocol-level tests we use **raw HTTP
POSTs with the JSON-RPC 2.0 body shape** the MCP spec defines.

This is the architect's directive: **use raw HTTP POSTs, not
the official MCP client**, in `test_mcp_server.py`. The trade-off
(no client-side schema validation) is acceptable because:
1. We control both ends of the wire.
2. The handshake is three calls (`initialize`, `tools/list`,
   `tools/call`) — small enough to spell out.
3. Any future end-to-end test against a live gateway can use the
   official client; tests in this file are unit-scope.

**JSON-RPC body shapes** (cookie-cutter for the test file):

```python
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18",
                   "capabilities": {},
                   "clientInfo": {"name": "pytest", "version": "0"}}}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
def CALL(name, args, _id=3):
    return {"jsonrpc": "2.0", "id": _id, "method": "tools/call",
            "params": {"name": name, "arguments": args}}
```

Each test posts to `/mcp` with `Authorization: Bearer <token>` and
`Content-Type: application/json`, and parses the SSE-framed response
(`data: {...}\n\n`). A small helper `_parse_sse(resp)` returns the
JSON body of the last `data:` frame.

**The 8 tests (names exact):**

1. **`test_mcp_unauth_returns_401`** — POST `/mcp` with no header;
   assert 401.
2. **`test_mcp_bearer_accepted`** — POST `/mcp` with valid bearer +
   `INIT`; assert 200 and the response includes a `serverInfo` block.
3. **`test_mcp_tools_list_returns_seven_schemas`** — `INIT` then
   `LIST`; assert response `result.tools` has length 7 and the names
   match the registry exactly (set equality).
4. **`test_mcp_tools_call_query_database_select_sites`** — `CALL`
   `query_database` with a real SELECT + a seeded insight_id from the
   test fixtures; assert `result.content[0].text` JSON-decodes to
   `{ok: true, result: {...rows: [...]}}`. Uses the existing pytest
   DB fixture.
5. **`test_mcp_tools_call_emit_chart_persists_row`** — `CALL`
   `emit_chart` with a minimal valid ChartSpec; after the call, query
   `agent_chart` and assert exactly one row was inserted with the
   expected `insight_id`.
6. **`test_mcp_tools_call_web_search_degraded_without_key`** — `CALL`
   `web_search` with `BRAVE_SEARCH_API_KEY` unset (use
   `monkeypatch.delenv`); assert `result.degraded == True` and the
   reason mentions missing API key. Tool body already supports this.
7. **`test_mcp_tools_call_unknown_tool_returns_error`** — `CALL`
   `not_a_real_tool`; assert the JSON-RPC response has `isError: true`
   or our `{ok: false, code: "TOOL_FAILED"}` envelope (whichever
   FastMCP routes for unknown names — verify at first run; if FastMCP
   replies with JSON-RPC `error` block, the test asserts that
   instead).
8. **`test_mcp_bearer_env_unset_returns_503`** — `monkeypatch.delenv("AGENT_TOOLS_BEARER")`;
   POST `/mcp` with **any** header value; assert 503 with detail
   `agent_tools_bearer_not_configured`.

---

## §9. Risks (MCP-specific)

### R-MCP-A1. Lifespan plumbing breakage (issue #1367)

If the parent FastAPI app does not inherit the MCP sub-app's lifespan,
the streamable-HTTP session manager raises `Task group is not
initialized` on the first request.
**Mitigation:** `_attach_lifespan` in §4.2 composes the two lifespans;
test 2 (`test_mcp_bearer_accepted`) exercises this on every CI run.

### R-MCP-A2. Path doubling (`/mcp/mcp`)

`streamable_http_app()` self-mounts under `/mcp`; mounting again at
`/mcp` produces `/mcp/mcp`.
**Mitigation:** the §4.2 pattern uses `Mount("/", inner)` inside a
sub-Starlette so the inner `/mcp` is consumed at the sub level. Verify
with `curl -X POST http://localhost:8000/mcp -H 'Authorization: Bearer ...'`
during smoke.

### R-MCP-A3. FastMCP context binding to `insight_id`

The pinned SDK version's `Context` parameter exposes the request
inconsistently across releases (researcher §4 "VERIFY at implementation
time"). We sidestep this by making `insight_id` an explicit handler
arg the LLM passes — no reliance on per-request request_context
introspection inside the handler body.

### R-MCP-A4. MCP client/server version skew

OpenClaw's MCP client may expect a protocol version that diverges from
our pinned `mcp 1.27.x`.
**Mitigation:** test 3 (`test_mcp_tools_list_returns_seven_schemas`)
exercises the discovery handshake; F6 smoke runs the live gateway
boot-time discovery assertion. If skew surfaces, pin OpenClaw to the
known-compatible version it shipped with — the gateway image tag is
already pinned in the docker-compose file.

### R-MCP-A5. OpenClaw streamable-HTTP transport bugs

Researcher §3 noted OpenClaw documents support for streamable-HTTP but
real-world bugs are possible.
**Mitigation:** if the gateway boot logs show `streamable-http
handshake failed`, the addendum/ADR documents the fallback to
`mcp.sse_app()` (one-line swap in `mount_mcp`). The OpenClaw config's
`transport: "streamable-http"` field would change to `"sse"`.

---

## §10. Acceptance — implementation flavor

Restated from the PRD §6 with concrete file/test bindings.

| AC | Implementation evidence |
|---|---|
| AC1 (`mcp` SDK declared) | `pyproject.toml` has `mcp>=1.27,<2`; `uv lock` regenerates `uv.lock`; `uv sync` in clean venv succeeds. |
| AC2 (7 MCP tools exposed) | Test 3 (`test_mcp_tools_list_returns_seven_schemas`) green; tool name set equals `{query_database, call_api, get_chart_data, web_search, run_skill, emit_chart, emit_citation}`. |
| AC3 (`/mcp` mounted with bearer) | Tests 1, 2, 8 green (401, 200, 503 paths). |
| AC4 (openclaw.json points at MCP) | `.openclaw/openclaw.json` has `mcp.servers.oci-insights` block; live gateway boot log shows `discovered 7 tools`. |
| AC5 (tests pass) | `pytest backend/tests/test_mcp_server.py` is green; pre-existing `test_openclaw_forwarder.py`, `test_openclaw_persona_loaded.py`, and chat tests still pass (no regressions). |
| AC6 (live smoke succeeds) | Manual runbook in §11 step 7: with `OPENCLAW_ENABLED=1`, ask "what other Crusoe sites?" and observe an MCP `query_database` invocation in the gateway log + `agent_tool_call` row in Postgres. |
| AC7 (TS scaffold gone) | `git ls-files .openclaw/extensions/insights-tools` returns empty; `git grep -l 'insights-tools'` returns docs only (no source). |
| AC8 (rollback unaffected) | With `OPENCLAW_ENABLED=0`, `httpx` access log against `/mcp` is empty during a chat turn — captured in the smoke runbook step 8. |
| AC9 (ADR exists) | `docs/plans/ai-insights-automation/ADR-013-mcp-vs-ts-plugin.md` exists, cross-linked from PRD §12 References. |

---

## §11. Implementation order

The backend agent executes these in order. Each step produces a
testable artefact so a partial completion is not a brick.

1. **Refactor SkillContext factory.** Create
   `backend/agents/insights/skill_ctx_factory.py` containing
   `build_skill_ctx` and `_noop_emit_event`. Update
   `backend/routers/agent_tools.py` to import them. Run the existing
   `test_agent_tools_router.py` and confirm green. (Pure refactor; no
   behaviour change.)
2. **Add the `mcp` dependency.** Edit `backend/pyproject.toml`, add
   `mcp>=1.27,<2`. Run `uv lock` and commit `uv.lock`. `uv sync` in a
   clean venv must succeed.
3. **Write `backend/mcp_server.py`.** FastMCP instance, 7
   `@mcp.tool()` handlers per §3, `_invoke` helper, `StaticBearer`
   middleware, `mount_mcp(app)` per §4, and the `_attach_lifespan`
   composer.
4. **Wire `backend/main.py`.** Add `from mcp_server import mount_mcp`
   at the import block; after the last `app.include_router(...)` call
   (after `oci_share_router`), add `mount_mcp(app)`. Restart uvicorn
   and confirm `/mcp` responds 401 to an unauthenticated POST.
5. **Update `.openclaw/openclaw.json`.** Apply the §7 diff. Bump
   `meta.lastTouchedAt`.
6. **Write `backend/tests/test_mcp_server.py`.** All 8 tests per §8.
   `pytest backend/tests/test_mcp_server.py` green.
7. **Live smoke (manual).** With `OPENCLAW_ENABLED=1` and the gateway
   running on `localhost:7474`, run the F6 smoke runbook: ask "what
   other Crusoe sites?" in the dock, watch the gateway log for an MCP
   `query_database` call, watch the dock SSE for
   `tool_call_started`/`tool_call_complete`, query Postgres for the
   `agent_tool_call` row.
8. **Cleanup.** Delete `.openclaw/extensions/insights-tools/`. Confirm
   `git grep -l 'insights-tools'` returns docs only.
9. **Write the ADR.** `docs/plans/ai-insights-automation/ADR-013-mcp-vs-ts-plugin.md`
   capturing the decision, the streamable-HTTP transport choice, the
   bearer model, and the rollback contract. Cross-link from PRD §12.

---

*End of architecture.*
