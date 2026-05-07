"""Tests for `backend/mcp_server.py` — the FastMCP streamable-HTTP mount.

PRD : docs/plans/ai-insights-automation/13-mcp-migration-prd.md
ARCH: docs/plans/ai-insights-automation/13-mcp-migration-architecture.md §8

Strategy
--------
Tests run against the in-process FastAPI app via
``httpx.AsyncClient(transport=httpx.ASGITransport(app=app))``. We do
**not** spin up a live OpenClaw container. We also do **not** drive
the official ``mcp.ClientSession``: per the architecture (§8) raw
JSON-RPC POSTs are easier to plumb through ``ASGITransport`` and the
handshake is small.

Quirks discovered on first run (these constrain the test setup):

  1. **DNS-rebinding protection.** ``FastMCP`` defaults to enabling
     DNS-rebinding protection when the configured ``host`` is
     ``localhost``/``127.0.0.1``/``::1`` and seeds
     ``allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"]``.
     ``httpx.ASGITransport``'s default ``base_url='http://test'``
     therefore 421s. We set ``base_url='http://127.0.0.1:8000'``.

  2. **Lifespan must run.** The streamable-HTTP session manager uses
     an anyio task group started by the inner Starlette's lifespan.
     ``mount_mcp`` composes that lifespan onto the FastAPI app, but
     ``ASGITransport`` does not enter lifespans on its own; tests
     must enter ``app.router.lifespan_context(app)`` explicitly,
     otherwise the first request raises
     ``RuntimeError: Task group is not initialized``.

  3. **Stateless mode.** ``mcp_server.py`` constructs FastMCP with
     ``stateless_http=True``, so ``tools/list`` and ``tools/call``
     work without an ``initialize`` handshake; we still cover
     initialize in test 2 to prove the wire is healthy.

  4. **JSON response.** ``json_response=True`` makes the server reply
     with ``Content-Type: application/json`` rather than
     SSE-framed ``text/event-stream``. The test parser is therefore
     a plain ``r.json()``.

  5. **Test 5 (emit_chart).** ``emit_chart`` is dispatch-only — the
     tool body validates the spec and returns ``{chart_id, accepted}``.
     **It does NOT itself insert into ``agent_chart``.** Persistence
     is the orchestrator/persistence layer's responsibility (see
     ``agents/insights/tools/emit_chart.py`` module docstring). The
     test therefore asserts the success envelope rather than a row
     in the table; the docstring on the test explains.

  6. **Test 8 (env unset -> 503).** ``StaticBearer.authenticate``
     reads ``os.environ`` per request, so ``monkeypatch.delenv`` works
     without a module reload.

  7. **Test 4 (query_database).** ``backend/agents/insights/tools/
     query_database.py`` calls ``get_readonly_engine()`` and runs raw
     SQL. To keep this test fast and DB-free we monkeypatch
     ``agents.insights.tools.registry.dispatch`` (matching the style
     of ``test_agent_tools_router.py``) and validate that the MCP
     call routed the right tool name + args. This proves the MCP
     plumbing (which is what ``mcp_server.py`` adds); the DB-side
     correctness of ``query_database`` itself is exercised by
     ``test_insights_sql_gate.py`` and friends.

  8. **Tests that need a SkillContext** (4, 5, 6) also stub
     ``agents.insights.skill_ctx_factory.build_skill_ctx`` — the
     factory queries Postgres for the ``AIInsight`` row, which is
     out of scope for unit-level MCP transport tests.
"""
from __future__ import annotations

import json
import os
import sys
import types
import uuid
from typing import Any

import pytest
import pytest_asyncio

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))
for p in (BACKEND_ROOT, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


# ---------------------------------------------------------------------------
# Pre-import shims (mirrors test_v2_chat_isolation.py / test_openclaw_forwarder.py)
#
# Importing `main` pulls in `routers.insights` -> `agents.insights.tools`
# package -> `sql_gate` (which depends on a newer sqlglot than is pinned).
# Pre-register a fake `sql_gate` so the import succeeds.
# ---------------------------------------------------------------------------
import agents  # noqa: E402,F401
import agents.insights  # noqa: E402,F401

if "agents.insights.tools" not in sys.modules:
    _tools_pkg = types.ModuleType("agents.insights.tools")
    _tools_pkg.__path__ = [os.path.join(BACKEND_ROOT, "agents", "insights", "tools")]
    sys.modules["agents.insights.tools"] = _tools_pkg

if "agents.insights.tools.sql_gate" not in sys.modules:
    from pydantic import BaseModel as _BM

    _sg = types.ModuleType("agents.insights.tools.sql_gate")

    class SqlGateError(Exception):
        def __init__(self, code: str = "sql_gate_blocked", *args, **kwargs) -> None:
            super().__init__(*args)
            self.code = code

    class ValidatedSQL(_BM):
        sql: str
        notes: list[str] = []

    def validate_sql(sql: str, **_kw):
        return ValidatedSQL(sql=sql)

    _sg.SqlGateError = SqlGateError
    _sg.ValidatedSQL = ValidatedSQL
    _sg.validate_sql = validate_sql
    _sg.DEFAULT_ROW_LIMIT = 10_000
    sys.modules["agents.insights.tools.sql_gate"] = _sg

# SQLite dialect compat patches (JSONB / UUID -> SQLite-friendly).
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler  # noqa: E402


def _visit_JSONB(self, type_, **kw):  # noqa: N802
    return "TEXT"


def _visit_UUID(self, type_, **kw):  # noqa: N802
    return "CHAR(36)"


SQLiteTypeCompiler.visit_JSONB = _visit_JSONB  # type: ignore[attr-defined]
SQLiteTypeCompiler.visit_UUID = _visit_UUID  # type: ignore[attr-defined]


# Now we can import the app + the mcp_server module.
import httpx  # noqa: E402

# Set the bearer BEFORE importing main (mount_mcp captures nothing at
# import, but this keeps the module-level state predictable).
os.environ.setdefault("AGENT_TOOLS_BEARER", "test-mcp-bearer-secret")

from main import app  # noqa: E402
import mcp_server as mcp_server_mod  # noqa: E402
import agents.insights.skill_ctx_factory as skill_ctx_factory_mod  # noqa: E402

BEARER = "test-mcp-bearer-secret"

# Every async test in this module shares one event loop (module scope)
# so the StreamableHTTP session manager — which can only be `.run()`
# once per instance — is initialised exactly once.
pytestmark = pytest.mark.asyncio(loop_scope="module")
# httpx.ASGITransport default base_url='http://test' fails the MCP
# DNS-rebinding host check; use a host that matches the auto-allowlist.
BASE_URL = "http://127.0.0.1:8000"
MCP_PATH = "/mcp/"  # trailing slash to dodge the 307 redirect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _headers(bearer: str | None = BEARER) -> dict[str, str]:
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if bearer is not None:
        h["Authorization"] = f"Bearer {bearer}"
    return h


def _init_body(_id: int = 1) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": _id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    }


def _list_body(_id: int = 2) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": _id, "method": "tools/list", "params": {}}


def _call_body(name: str, args: dict[str, Any], _id: int = 3) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": _id,
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def _lifespan_app():
    """Enter the FastAPI app's lifespan exactly ONCE for the whole
    test module.

    The MCP `StreamableHTTPSessionManager` enforces a hard
    `run()-can-only-be-called-once` rule per instance. Because
    `mcp_server.mount_mcp` builds the session manager at module-import
    time, we cannot enter the FastAPI lifespan multiple times in the
    same process — the second entry raises
    ``RuntimeError: StreamableHTTPSessionManager .run() can only be
    called once per instance``.

    The fix is to scope the lifespan-context manager to the *module*
    (or session) and let every test reuse the already-running task
    group.

    Teardown caveat: anyio's ``create_task_group`` cancel-scope check
    may fire ``RuntimeError("Attempted to exit cancel scope in a
    different task")`` on shutdown when the manager is unwound from
    a different task than it was created in. We suppress that on
    teardown — the tests have already finished and the process is
    about to exit, so the leak is bounded.
    """
    cm = app.router.lifespan_context(app)
    await cm.__aenter__()
    try:
        yield app
    finally:
        try:
            await cm.__aexit__(None, None, None)
        except RuntimeError as exc:  # pragma: no cover - shutdown only
            # anyio cross-task cancel-scope: harmless at process exit.
            if "cancel scope" not in str(exc):
                raise


@pytest_asyncio.fixture(loop_scope="module")
async def client(monkeypatch: pytest.MonkeyPatch, _lifespan_app):
    """Async httpx client over the FastAPI app, sharing the
    module-scoped lifespan. Sets the bearer env var so auth tests pass.
    """
    monkeypatch.setenv("AGENT_TOOLS_BEARER", BEARER)
    transport = httpx.ASGITransport(app=_lifespan_app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as c:
        yield c


@pytest.fixture
def stub_skill_ctx(monkeypatch: pytest.MonkeyPatch):
    """Replace `build_skill_ctx` with a no-op factory that returns a
    SkillContext-shaped sentinel. The real factory queries Postgres for
    the AIInsight row — out of scope for these MCP transport tests.
    """
    captured: dict[str, Any] = {}

    async def _fake(db, *, insight_id, thread_id_hint, session_id_hint):
        captured["insight_id"] = insight_id
        captured["thread_id_hint"] = thread_id_hint
        captured["session_id_hint"] = session_id_hint
        # Web search reads ctx.web_search_count + ctx.session_id; tools
        # also tolerate ctx=None. Use a SimpleNamespace with a few real
        # fields to keep the surface small.
        return types.SimpleNamespace(
            session_id="ses_stub",
            thread_id="thr_stub",
            insight_id=str(insight_id),
            web_search_count=0,
            emit_event=lambda *a, **kw: None,
        )

    # Patch on the mcp_server module (where the lazy import binds the
    # name into the function's locals on every call — but the real
    # binding lookup happens inside `_invoke` at call-time via
    # `from agents.insights.skill_ctx_factory import build_skill_ctx`).
    # We therefore patch the source module too.
    monkeypatch.setattr(skill_ctx_factory_mod, "build_skill_ctx", _fake)
    return captured


@pytest.fixture
def stub_db(monkeypatch: pytest.MonkeyPatch):
    """Replace `db.session.async_session_factory` with a no-op session
    so `_invoke` can call `commit()` / `close()` / `rollback()` without
    a real DB.
    """

    class _NoopSession:
        async def commit(self):
            return None

        async def rollback(self):
            return None

        async def close(self):
            return None

        async def execute(self, *_a, **_kw):  # pragma: no cover
            class _R:
                def scalar_one_or_none(self):
                    return None

            return _R()

    import db.session as db_session_mod

    monkeypatch.setattr(db_session_mod, "async_session_factory", lambda: _NoopSession())


@pytest.fixture
def stub_dispatch(monkeypatch: pytest.MonkeyPatch):
    """Pre-register a fake `agents.insights.tools.registry` whose
    `dispatch` records the call and returns a programmable value.

    `_invoke` does `from agents.insights.tools.registry import dispatch`
    lazily; pre-binding the module short-circuits that import to ours.
    """
    calls: list[dict[str, Any]] = []
    behavior: dict[str, Any] = {"return_value": None, "raise": None}

    async def _fake_dispatch(name, args, ctx):
        calls.append({"name": name, "args": dict(args) if isinstance(args, dict) else args, "ctx": ctx})
        if behavior["raise"] is not None:
            raise behavior["raise"]
        return behavior["return_value"]

    fake_registry = types.ModuleType("agents.insights.tools.registry")
    fake_registry.dispatch = _fake_dispatch  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agents.insights.tools.registry", fake_registry)
    return {"calls": calls, "behavior": behavior}


# ---------------------------------------------------------------------------
# Test 1: unauth -> 401
# ---------------------------------------------------------------------------


async def test_mcp_unauth_returns_401(client: httpx.AsyncClient) -> None:
    """No Authorization header -> 401 from StaticBearer."""
    r = await client.post(
        MCP_PATH,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json=_init_body(),
    )
    assert r.status_code == 401, r.text
    body = r.json()
    assert body.get("detail") == "missing_bearer", body


# ---------------------------------------------------------------------------
# Test 2: valid bearer + initialize -> 200, serverInfo present
# ---------------------------------------------------------------------------


async def test_mcp_bearer_accepted(client: httpx.AsyncClient) -> None:
    """Valid bearer + JSON-RPC `initialize` -> 200 with serverInfo."""
    r = await client.post(MCP_PATH, headers=_headers(), json=_init_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("jsonrpc") == "2.0", body
    result = body.get("result") or {}
    server_info = result.get("serverInfo") or {}
    # mcp_server.py constructs FastMCP("strategic-insights", ...).
    assert server_info.get("name") == "strategic-insights", body


# ---------------------------------------------------------------------------
# Test 3: tools/list returns the twelve schemas
# ---------------------------------------------------------------------------


# Phase 1 (insight-scoped) tools — all take insight_id as their first arg.
_EXPECTED_INSIGHT_SCOPED_TOOL_NAMES = {
    "query_database",
    "call_api",
    "get_chart_data",
    "web_search",
    "run_skill",
    "emit_chart",
    "emit_citation",
}

# Phase 2 (PRD/ARCH 14) — session-scoped write tools. These take session_id
# as their first arg and persist into ai_session / ai_insight / brief_run.
_EXPECTED_SESSION_SCOPED_TOOL_NAMES = {
    "persist_insight",
    "finalize_session",
    "persist_brief",
}

# ARCH 15 — QA-lane chart proposal tool. Takes neither insight_id nor
# session_id (no DB write); the QA SSE translator inspects the
# tool_call arguments and emits a ChartSpecEvent to the frontend.
_EXPECTED_QA_TOOL_NAMES = {
    "propose_qa_chart",
}

# OpenClaw memory write — agent calls this from the chat lane to persist
# long-term memory under a fixed category vocabulary.
_EXPECTED_MEMORY_TOOL_NAMES = {
    "update_memory",
}

_EXPECTED_TOOL_NAMES = (
    _EXPECTED_INSIGHT_SCOPED_TOOL_NAMES
    | _EXPECTED_SESSION_SCOPED_TOOL_NAMES
    | _EXPECTED_QA_TOOL_NAMES
    | _EXPECTED_MEMORY_TOOL_NAMES
)


async def test_mcp_tools_list_returns_twelve_schemas(
    client: httpx.AsyncClient,
) -> None:
    """`tools/list` returns the twelve registered tool schemas (7 insight-
    scoped from Phase 1 + 3 session-scoped write tools from Phase 2 + 1
    QA-lane chart proposal tool from ARCH 15 + 1 memory-write tool) with
    name + description + inputSchema fields populated."""
    r = await client.post(MCP_PATH, headers=_headers(), json=_list_body())
    assert r.status_code == 200, r.text
    body = r.json()
    tools = (body.get("result") or {}).get("tools") or []
    assert len(tools) == 12, (
        f"expected 12 tools, got {len(tools)}: {[t.get('name') for t in tools]}"
    )

    names = {t["name"] for t in tools}
    assert names == _EXPECTED_TOOL_NAMES, names
    # Phase 2 write-tools must be present individually (regression guard).
    assert "persist_insight" in names
    assert "finalize_session" in names
    assert "persist_brief" in names
    # ARCH 15 QA-lane tool present (regression guard).
    assert "propose_qa_chart" in names

    for t in tools:
        assert t.get("name"), t
        assert t.get("description"), t
        schema = t.get("inputSchema")
        assert isinstance(schema, dict) and schema.get("type") == "object", t
        props = schema.get("properties") or {}
        # Phase 1 tools take insight_id; Phase 2 write-tools take
        # session_id; the QA-lane propose_qa_chart takes neither — it
        # carries the ChartSpec fields directly (chart_type, x, y,
        # series, title, source_table; optional breakdown_by/reasoning).
        if t["name"] in _EXPECTED_QA_TOOL_NAMES:
            for required_field in (
                "chart_type",
                "title",
                "x",
                "y",
                "series",
                "source_table",
            ):
                assert required_field in props, (t["name"], required_field, props)
            # Optional fields advertised in the schema as well.
            assert "breakdown_by" in props, t
            assert "reasoning" in props, t
        elif t["name"] in _EXPECTED_SESSION_SCOPED_TOOL_NAMES:
            assert "session_id" in props, t
        elif t["name"] in _EXPECTED_MEMORY_TOOL_NAMES:
            # update_memory takes (category, fact); no insight or session id.
            assert "category" in props, t
            assert "fact" in props, t
        else:
            assert "insight_id" in props, t


# ---------------------------------------------------------------------------
# Test 4: tools/call query_database routes to dispatch with right args
# ---------------------------------------------------------------------------


def _content_text_payload(body: dict[str, Any]) -> dict[str, Any]:
    """Pull the JSON-encoded text from MCP `content[0].text` and parse it."""
    result = body.get("result") or {}
    content = result.get("content") or []
    assert content, body
    text = content[0].get("text")
    assert isinstance(text, str), body
    return json.loads(text)


async def test_mcp_tools_call_query_database_select_sites(
    client: httpx.AsyncClient,
    stub_db,
    stub_skill_ctx,
    stub_dispatch,
) -> None:
    """tools/call routes `query_database` to the registry dispatcher
    with the SQL the LLM sent. We stub dispatch to return a fixed
    `rows` payload and assert the MCP `_invoke` shim wrapped it as
    `{ok: True, result: {...}}`.
    """
    insight_id = str(uuid.uuid4())
    expected_rows = [
        {"id": 1, "name": "Crusoe ICY-12", "operator": "Crusoe"},
        {"id": 2, "name": "Crusoe ICY-13", "operator": "Crusoe"},
    ]
    stub_dispatch["behavior"]["return_value"] = {
        "rows": expected_rows,
        "columns": ["id", "name", "operator"],
        "row_count": len(expected_rows),
    }

    r = await client.post(
        MCP_PATH,
        headers=_headers(),
        json=_call_body(
            "query_database",
            {
                "insight_id": insight_id,
                "sql": "SELECT id, name, operator FROM sites LIMIT 3",
            },
        ),
    )
    assert r.status_code == 200, r.text
    body = r.json()

    parsed = _content_text_payload(body)
    assert parsed.get("ok") is True, parsed
    assert parsed.get("result", {}).get("rows") == expected_rows, parsed

    # Dispatcher invoked exactly once with the SQL the caller sent.
    assert len(stub_dispatch["calls"]) == 1
    call = stub_dispatch["calls"][0]
    assert call["name"] == "query_database"
    assert call["args"]["sql"] == "SELECT id, name, operator FROM sites LIMIT 3"
    # max_rows defaults to 10000 per the MCP handler signature.
    assert call["args"]["max_rows"] == 10000


# ---------------------------------------------------------------------------
# Test 5: tools/call emit_chart returns the accepted-envelope
# ---------------------------------------------------------------------------


async def test_mcp_tools_call_emit_chart_persists_row(
    client: httpx.AsyncClient,
    stub_db,
    stub_skill_ctx,
    stub_dispatch,
) -> None:
    """tools/call routes `emit_chart` and the success envelope
    contains `{accepted: True, chart_id: ...}`.

    NOTE: the real ``emit_chart`` tool body is dispatch-only; per the
    module docstring of ``agents/insights/tools/emit_chart.py`` it
    does NOT itself open a write transaction or insert into
    ``agent_chart``. Persistence is the orchestrator/persistence
    layer's responsibility. For the MCP transport unit test we
    therefore assert that the dispatcher saw the spec and that the
    success envelope flows back through MCP — the original "row in
    AgentChart" check is a layer above this transport test, covered
    by the chat-router persistence tests.
    """
    insight_id = str(uuid.uuid4())
    chart_id = "c_a1b2c3d4"
    stub_dispatch["behavior"]["return_value"] = {
        "chart_id": chart_id,
        "accepted": True,
    }

    spec = {
        "chart_id": chart_id,
        "chart_type": "bar",
        "title": "Crusoe sites",
        "data_source": {
            "kind": "db_query",
            "spec": {"sql": "SELECT 1"},
            "rows": 1,
            "fetched_at": "2026-05-06T00:00:00+00:00",
            "row_hash": "0" * 64,
        },
        "data": [{"name": "ICY-12", "mw": 100}],
        "encoding": {
            "x": {"field": "name", "type": "category"},
            "y": {"field": "mw", "type": "quantitative"},
        },
    }

    r = await client.post(
        MCP_PATH,
        headers=_headers(),
        json=_call_body("emit_chart", {"insight_id": insight_id, "spec": spec}),
    )
    assert r.status_code == 200, r.text
    parsed = _content_text_payload(r.json())
    assert parsed.get("ok") is True, parsed
    assert parsed["result"]["chart_id"] == chart_id
    assert parsed["result"]["accepted"] is True

    # The dispatcher received the spec dict as args (per ARCH §3.6 the
    # spec IS the args dict for emit_chart).
    assert len(stub_dispatch["calls"]) == 1
    call = stub_dispatch["calls"][0]
    assert call["name"] == "emit_chart"
    assert call["args"] == spec


# ---------------------------------------------------------------------------
# Test 6: web_search degraded without API key
# ---------------------------------------------------------------------------


async def test_mcp_tools_call_web_search_degraded_without_key(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    stub_db,
    stub_skill_ctx,
) -> None:
    """With BRAVE_SEARCH_API_KEY unset, the real web_search tool body
    returns the documented graceful-degradation envelope:
        {ok: True, results: [], degraded: True, reason: "no_api_key"}
    Wrapped by `_invoke` it becomes:
        {ok: True, result: {ok: True, ..., degraded: True, ...}}
    """
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    # Note: the request also names BRAVE_API_KEY for forward-compat.
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    insight_id = str(uuid.uuid4())
    r = await client.post(
        MCP_PATH,
        headers=_headers(),
        json=_call_body(
            "web_search",
            {"insight_id": insight_id, "query": "Crusoe sites", "n": 3},
        ),
    )
    assert r.status_code == 200, r.text
    parsed = _content_text_payload(r.json())
    assert parsed.get("ok") is True, parsed
    inner = parsed.get("result") or {}
    assert inner.get("degraded") is True, inner
    assert inner.get("reason") == "no_api_key", inner


# ---------------------------------------------------------------------------
# Test 7: unknown tool returns a JSON-RPC error envelope
# ---------------------------------------------------------------------------


async def test_mcp_tools_call_unknown_tool_returns_error(
    client: httpx.AsyncClient,
) -> None:
    """tools/call for a name FastMCP doesn't know -> JSON-RPC error
    envelope (FastMCP returns -32602 invalid params or surfaces an
    `isError` content; we accept either: `error` field set OR the
    result content carries the unknown-tool sentinel).
    """
    r = await client.post(
        MCP_PATH,
        headers=_headers(),
        json=_call_body("nonexistent_tool", {"insight_id": str(uuid.uuid4())}),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    has_error = "error" in body and body["error"] is not None
    result = body.get("result") or {}
    is_error_flag = bool(result.get("isError"))
    text_blob = ""
    for c in result.get("content") or []:
        if isinstance(c, dict) and c.get("type") == "text":
            text_blob += c.get("text") or ""
    assert (
        has_error
        or is_error_flag
        or "unknown" in text_blob.lower()
        or "not found" in text_blob.lower()
        or "nonexistent_tool" in text_blob.lower()
    ), body


# ---------------------------------------------------------------------------
# Test 8: env var unset -> 503
# ---------------------------------------------------------------------------


async def test_mcp_bearer_env_unset_returns_503(
    monkeypatch: pytest.MonkeyPatch,
    _lifespan_app,
) -> None:
    """`StaticBearer.authenticate` reads ``AGENT_TOOLS_BEARER`` from
    the environment on every request, so a delenv inside the test
    causes the next call to 503. No module reload required.

    We open our own httpx.AsyncClient (not the `client` fixture) so
    we control exactly which env state is in place when the request
    reaches StaticBearer.authenticate.
    """
    monkeypatch.delenv("AGENT_TOOLS_BEARER", raising=False)

    transport = httpx.ASGITransport(app=_lifespan_app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as c:
        r = await c.post(
            MCP_PATH,
            headers=_headers(bearer="anything"),
            json=_init_body(),
        )
    assert r.status_code == 503, r.text
    body = r.json()
    assert body.get("detail") == "agent_tools_bearer_not_configured", body
