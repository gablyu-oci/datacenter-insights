# MCP Server Migration Research

**Date:** 2026-05-06
**Author:** Research Agent
**Scope:** How to expose 7 existing Python tool implementations as an MCP server mounted on our FastAPI app at `/mcp`, speaking streamable-HTTP to OpenClaw, with static Bearer token auth.

---

## §1. Package & Version

- **PyPI package:** `mcp` (the official SDK published by the Model Context Protocol org).
  Source: https://pypi.org/project/mcp/
- **Latest stable as of 2026-05:** `mcp 1.27.0`, released 2026-04-02.
  Source: https://pypi.org/project/mcp/
- **Python requirement:** `>=3.10`. Optional extras: `cli`, `rich`, `ws`. Source: https://pypi.org/project/mcp/
- **Recommended install:** `pip install "mcp[cli]"` (per the official README). Source: https://github.com/modelcontextprotocol/python-sdk
- **Disambiguation — IMPORTANT:** there is also a separate third-party package called `fastmcp` (gofastmcp.com / jlowin/fastmcp). It is a *different* project from the official `mcp.server.fastmcp.FastMCP` class shipped inside the official `mcp` package. We want the official one; do not add `fastmcp` to pyproject. Source: https://gofastmcp.com/deployment/http and https://github.com/modelcontextprotocol/python-sdk

### Sub-modules to import (server side)

- High-level: `from mcp.server.fastmcp import FastMCP` — recommended for our use case.
- Low-level: `from mcp.server import Server` — direct JSON-RPC handler control; only needed if you want to customize wire framing.
- Types: `from mcp.types import TextContent, Tool, ImageContent, EmbeddedResource`.
  Source: https://github.com/modelcontextprotocol/python-sdk

### Tool registration API — minimal hello world

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Demo", json_response=True)

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b
```

The `@mcp.tool()` decorator inspects the Python function's type hints and docstring and auto-generates the JSON Schema for `inputSchema`, plus the tool description. Async functions are also supported (`async def`). Source: https://pypi.org/project/mcp/ and https://github.com/modelcontextprotocol/python-sdk

### Tool schema shape

The wire-level `Tool` object (defined in `mcp.types`) is a Pydantic model with:
- `name: str`
- `description: str | None`
- `inputSchema: dict` — a JSON Schema object (`{"type": "object", "properties": {...}, "required": [...]}`)

When you use `@mcp.tool()`, FastMCP builds this `inputSchema` for you from the function signature; you do not normally hand-write it. If you use the low-level `Server`, you return `Tool(name=..., description=..., inputSchema={...})` from the `list_tools` handler. Source: https://modelcontextprotocol.io/specification/2025-06-18/server/tools

### Tool result shape

Handlers can return Python primitives (FastMCP wraps them in a `TextContent` automatically), or explicitly return `list[TextContent | ImageContent | EmbeddedResource]`. The simplest path for our 7 tools is to return a JSON-serializable dict; FastMCP will serialize and wrap it. For backwards compatibility, even when returning structured content, the SDK also emits the JSON in a `TextContent` block. Source: https://github.com/modelcontextprotocol/python-sdk/issues/1378

```python
from mcp.types import TextContent
import json

@mcp.tool()
async def my_tool(query: str) -> list[TextContent]:
    payload = {"hits": [...]}
    return [TextContent(type="text", text=json.dumps(payload))]
```

---

## §2. FastAPI Mounting

### Does the SDK ship a streamable-HTTP ASGI helper?

Yes. `FastMCP` exposes:
- `mcp.streamable_http_app()` -> returns a Starlette ASGI app routed at `/mcp` (and `/mcp/`).
- `mcp.sse_app()` -> returns a Starlette ASGI app for the legacy HTTP+SSE transport.
- `mcp.http_app(path="/")` -> newer alias used in some examples; same Starlette-app shape.

Source: https://github.com/modelcontextprotocol/python-sdk and issue thread https://github.com/modelcontextprotocol/python-sdk/issues/1367

### Mounting pattern (the gotcha)

You **must** propagate the MCP app's `lifespan` to the parent FastAPI app. Otherwise the streamable-HTTP session manager never initializes and every request returns `RuntimeError: Task group is not initialized. Make sure to use run()`. Nested Starlette lifespans are not auto-discovered through `app.mount()`. Source: https://github.com/modelcontextprotocol/python-sdk/issues/1367 and https://github.com/modelcontextprotocol/python-sdk/issues/713

```python
# main.py — minimal correct wiring
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("StrategicInsights", json_response=True, stateless_http=True)

@mcp.tool()
async def search_filings(ticker: str) -> dict:
    """Search SEC filings for a ticker."""
    ...  # call into existing backend code

mcp_app = mcp.streamable_http_app()           # Starlette app, routes /mcp and /mcp/
app = FastAPI(lifespan=mcp_app.router.lifespan_context)  # CRITICAL — VERIFY at implementation time
app.mount("/mcp", mcp_app)
```

`// VERIFY at implementation time`: the exact attribute name for the lifespan handle differs between SDK examples — some show `mcp_app.lifespan`, others `mcp_app.router.lifespan_context`. The third-party `fastmcp` package uses `mcp_app.lifespan` directly. Confirm by inspecting `mcp.streamable_http_app()` return value at runtime. Sources: https://gofastmcp.com/deployment/http (third-party shape) and https://github.com/modelcontextprotocol/python-sdk/issues/1367 (official SDK).

### Path collision warning

`mcp.streamable_http_app()` already binds its routes at `/mcp`. If you then `app.mount("/mcp", mcp_app)`, the effective endpoint becomes `/mcp/mcp`. To get a clean `/mcp` external path, either:
- Mount at `/` (ugly, but works), or
- Use `mcp.http_app(path="/")` to strip the inner prefix, then mount at `/mcp`.

Source: https://github.com/modelcontextprotocol/python-sdk/issues/1367

### Auth via Starlette middleware — yes, fully supported

The mounted ASGI app is a regular Starlette app, so `AuthenticationMiddleware` works:

```python
from starlette.authentication import AuthenticationBackend, AuthCredentials, SimpleUser
from starlette.middleware.authentication import AuthenticationMiddleware
import os, hmac

EXPECTED = os.environ["MCP_BEARER_TOKEN"]

class StaticBearer(AuthenticationBackend):
    async def authenticate(self, request):
        h = request.headers.get("Authorization", "")
        if not h.startswith("Bearer "):
            return None
        token = h[7:]
        if not hmac.compare_digest(token, EXPECTED):
            return None
        return AuthCredentials(["authenticated"]), SimpleUser("openclaw")

# Apply to the mounted MCP sub-app only:
mcp_app.add_middleware(AuthenticationMiddleware, backend=StaticBearer())
```

Source: https://github.com/modelcontextprotocol/python-sdk/issues/431

---

## §3. Transport Choice for OpenClaw

OpenClaw's MCP client supports three transports: `stdio`, `sse`, and `streamable-http`. Default is `sse` when omitted. Sources: https://docs.openclaw.ai/cli/mcp.md

### URL path convention

OpenClaw does not enforce a particular path — it takes whatever URL you give it in the `url` field. Our planned `http://host.docker.internal:8000/mcp` is fine. Source: https://docs.openclaw.ai/cli/mcp.md

### Authorization header forwarding

Yes. Headers configured under `mcp.servers.<name>.headers` in `.openclaw.json` are forwarded verbatim to the MCP server. Sensitive values are redacted in logs. Example from the docs:

```json
{
  "mcp": {
    "servers": {
      "strategic-insights": {
        "url": "http://host.docker.internal:8000/mcp",
        "transport": "streamable-http",
        "headers": { "Authorization": "Bearer <token>" }
      }
    }
  }
}
```

Source: https://docs.openclaw.ai/cli/mcp.md

---

## §4. Tool Dispatch in Python MCP

- **Input args:** the FastMCP decorator unpacks `tools/call.arguments` (a dict) into kwargs that match your function signature; type coercion is handled via Pydantic. With the low-level `Server`, the handler receives the raw `arguments: dict`.
- **Return value:** primitive (`str`, `int`, `dict`, ...) -> auto-wrapped to `TextContent`. Or return `list[TextContent | ImageContent | EmbeddedResource]` explicitly. JSON-encoding a dict into a `TextContent.text` is the most reliable shape for OpenClaw to parse on the other side.
- **Async:** fully supported. `async def my_tool(...)` is the recommended style for any tool that does I/O.
- **Per-call request metadata:** FastMCP supports a `Context` parameter — annotate any parameter with `Context` and FastMCP injects an object that exposes `ctx.request_context` and (via dependency helpers) HTTP headers. The official SDK has `mcp.server.fastmcp.Context`; the third-party `fastmcp` exposes `from fastmcp.server.dependencies import get_http_headers`. We do **not** need this for the static-bearer model — auth is handled by middleware before the handler runs.

  ```python
  from mcp.server.fastmcp import Context

  @mcp.tool()
  async def whoami(ctx: Context) -> str:
      return ctx.request_context.request.headers.get("x-trace-id", "unknown")
  ```

  `// VERIFY at implementation time` — the exact attribute path on `ctx.request_context` is documented inconsistently across SDK versions; treat the snippet above as illustrative.

Sources: https://github.com/modelcontextprotocol/python-sdk and https://gelembjuk.com/blog/post/authentication-remote-mcp-server-python/

---

## §5. Concrete Recommendation

1. **Use the official `mcp` package's `FastMCP` class** (`mcp.server.fastmcp.FastMCP`) — not the third-party `fastmcp` PyPI package, and not hand-rolled JSON-RPC. The decorator-based API gives us automatic JSON Schema generation from type hints, automatic content wrapping, and a ready-made ASGI app. Hand-rolling JSON-RPC framing would add ~300 lines of code we'd then have to keep in sync with the spec.

2. **Use the streamable-HTTP transport** (`mcp.streamable_http_app()`). It's supported in `mcp` 1.27.0, OpenClaw supports it explicitly per its docs, and it's the forward-looking transport (the spec is deprecating SSE-only servers). Fallback to `mcp.sse_app()` is only needed if the streamable-HTTP mount turns out to be broken in our pinned version — both apps have the same Starlette shape so the swap is one-line.

3. **Static Bearer auth via Starlette `AuthenticationMiddleware`** added to the mounted sub-app. Compare tokens with `hmac.compare_digest`. Read the expected token from an env var (we'll re-use `AGENT_TOOLS_BEARER` so the existing `.env` doesn't grow).

### Pitfalls to expect

- **Lifespan plumbing is mandatory.** Forgetting to wire `lifespan=mcp_app.lifespan` (or equivalent) on the parent FastAPI app causes a runtime `Task group is not initialized` error on the first request. https://github.com/modelcontextprotocol/python-sdk/issues/1367
- **Path doubling.** `streamable_http_app()` already routes `/mcp`; mounting it again at `/mcp` produces `/mcp/mcp`. Pick one and verify with `curl` early.
- **Trailing-slash redirect.** Some SDK versions 307-redirect `/mcp` to `/mcp/`; ensure OpenClaw's HTTP client follows redirects, or configure the URL with the trailing slash. Same issue thread.
- **Stateless vs stateful.** Pass `stateless_http=True` to `FastMCP(...)` so each request is independent — simpler for a small fleet of static tools and avoids per-session memory growth. Source: https://github.com/modelcontextprotocol/python-sdk/issues/1367
- **Don't confuse `fastmcp` (PyPI) with `mcp.server.fastmcp` (inside `mcp`).** Wrong import = wrong API surface (e.g., `http_app()` vs `streamable_http_app()`).

---

## §6. Verified Version Pin

Add to `backend/pyproject.toml`:

```toml
"mcp>=1.27,<2"
```

Rationale: 1.27.0 is the latest as of 2026-04-02, the 1.x line is stable, and pinning `<2` guards against breaking changes in the planned v2 (per release notes: v2 is on the roadmap and 1.x users are advised to pin `<2`). Source: https://pypi.org/project/mcp/ and https://github.com/modelcontextprotocol/python-sdk/releases

---

## Sources

- [mcp on PyPI](https://pypi.org/project/mcp/)
- [modelcontextprotocol/python-sdk (GitHub)](https://github.com/modelcontextprotocol/python-sdk)
- [Python SDK docs site](https://py.sdk.modelcontextprotocol.io/)
- [Issue #1367 — mounting streamable-HTTP on FastAPI](https://github.com/modelcontextprotocol/python-sdk/issues/1367)
- [Issue #713 — multi streamable-HTTP lifespan](https://github.com/modelcontextprotocol/python-sdk/issues/713)
- [Issue #431 — Bearer auth with SSE/Starlette](https://github.com/modelcontextprotocol/python-sdk/issues/431)
- [Issue #1378 — structured tool responses / TextContent](https://github.com/modelcontextprotocol/python-sdk/issues/1378)
- [MCP Tools spec (2025-06-18)](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [OpenClaw MCP CLI docs](https://docs.openclaw.ai/cli/mcp.md)
- [gofastmcp.com — HTTP Deployment (third-party, reference only)](https://gofastmcp.com/deployment/http)
- [Bearer token MCP server tutorial — gelembjuk](https://gelembjuk.com/blog/post/authentication-remote-mcp-server-python/)
