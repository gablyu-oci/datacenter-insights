"""Tests for `backend/routers/agent_tools.py` — the OpenClaw plugin
webhook router (PRD 11a R2/R8, ARCH 11b §3, ADDENDUM 11c §G).

Strategy
--------
The router under test does three things per request:

  1. Bearer-auth check (constant-time HMAC of `Authorization` header
     against `AGENT_TOOLS_BEARER`).
  2. Build a `SkillContext` via `_build_skill_ctx(...)`, which itself
     touches Postgres and pulls in `agents.insights.specs.skill_context`
     plus `routers.insights` helpers.
  3. Dispatch into the in-process tool registry via
     `agents.insights.tools.registry.dispatch(name, args, ctx)`.

For unit-level coverage we want to exercise (1) and the wrap-into-
envelope behavior of (3), but stub (2) so the test does not need a
real Postgres or the full SkillContext import graph (which pulls in
oci-llm clients). To do that we monkeypatch the router module's
`_build_skill_ctx` and the `dispatch` symbol it lazy-imports.

Auth contract (PRD R8):
  - missing `Authorization` -> 401
  - wrong token             -> 401
  - correct token           -> 200 (success or graceful failure envelope)
  - malformed body          -> 422 (Pydantic envelope validation)

Wrap contract:
  - tool returns dict       -> {"ok": true, "result": <dict>}, HTTP 200
  - tool raises             -> {"ok": false, "error": "<repr>",
                                "code": "TOOL_FAILED"}, HTTP 200

GET /api/agent-tools/insight-context:
  - returns the same shape as `_build_chat_context` enriched with
    `thread_id` and `parent_session_id`.
"""
from __future__ import annotations

import os
import sys
import types
import uuid
from typing import Any

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


# ---------------------------------------------------------------------------
# Module-under-test import
# ---------------------------------------------------------------------------
# The router imports cleanly without a DB; the heavy paths are lazy.
import routers.agent_tools as agent_tools_mod  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


# ---------------------------------------------------------------------------
# Test harness — a minimal FastAPI app that mounts only this router so the
# test does not pay the full `main.py` import cost.
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A FastAPI TestClient with the router mounted and bearer set."""
    monkeypatch.setenv("AGENT_TOOLS_BEARER", "test-bearer-secret")

    app = FastAPI()
    app.include_router(agent_tools_mod.router)
    return TestClient(app)


@pytest.fixture
def stub_skill_ctx(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace `_build_skill_ctx` with a lightweight stand-in.

    Returns a dict that tests can mutate to assert on call args (the
    stub captures `insight_id`, `thread_id_hint`, `session_id_hint`).
    """
    captured: dict[str, Any] = {}

    async def _fake_build_skill_ctx(db, *, insight_id, thread_id_hint, session_id_hint):
        captured["insight_id"] = insight_id
        captured["thread_id_hint"] = thread_id_hint
        captured["session_id_hint"] = session_id_hint
        # Return a sentinel object — tools are stubbed below so no real
        # SkillContext fields are touched.
        return types.SimpleNamespace(
            session_id="ses_stub",
            thread_id="thr_stub",
            insight_id=str(insight_id),
        )

    monkeypatch.setattr(agent_tools_mod, "_build_skill_ctx", _fake_build_skill_ctx)
    return captured


@pytest.fixture
def stub_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace `async_session_factory` with a no-op async session.

    The router calls `db.commit()` and `db.close()` on the result; we
    only need those two methods to be awaitable.
    """

    class _NoopSession:
        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

        async def close(self) -> None:
            return None

        async def execute(self, *_a, **_kw):  # pragma: no cover - unused
            class _R:
                def scalar_one_or_none(self):
                    return None

            return _R()

    def _factory():
        return _NoopSession()

    monkeypatch.setattr(agent_tools_mod, "async_session_factory", _factory)


@pytest.fixture
def stub_dispatch(monkeypatch: pytest.MonkeyPatch):
    """Insert a fake `agents.insights.tools.registry` whose `dispatch` is
    a recorder we can program per-test.

    The router imports `dispatch` lazily inside `_invoke_tool`. By
    pre-registering the module in `sys.modules` we short-circuit that
    lazy import to our fake.
    """
    calls: list[dict[str, Any]] = []
    behavior: dict[str, Any] = {"return_value": None, "raise": None}

    async def _fake_dispatch(name: str, args: dict[str, Any], ctx: Any) -> Any:
        calls.append({"name": name, "args": dict(args), "ctx": ctx})
        if behavior["raise"] is not None:
            raise behavior["raise"]
        return behavior["return_value"]

    fake_registry = types.ModuleType("agents.insights.tools.registry")
    fake_registry.dispatch = _fake_dispatch  # type: ignore[attr-defined]

    # Make sure the parent packages exist so `from agents.insights.tools.registry
    # import dispatch` resolves to ours.
    for parent in ("agents", "agents.insights", "agents.insights.tools"):
        if parent not in sys.modules:
            mod = types.ModuleType(parent)
            mod.__path__ = []  # type: ignore[attr-defined]
            sys.modules[parent] = mod

    monkeypatch.setitem(sys.modules, "agents.insights.tools.registry", fake_registry)
    return {"calls": calls, "behavior": behavior}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelope(insight_id: str | None = None, args: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "args": args or {},
        "context": {"insight_id": insight_id or str(uuid.uuid4())},
    }


# Every POST tool-endpoint name (path -> tool name).
_TOOL_PATHS = [
    ("/api/agent-tools/query_database", "query_database"),
    ("/api/agent-tools/call_api", "call_api"),
    ("/api/agent-tools/get_chart_data", "get_chart_data"),
    ("/api/agent-tools/web_search", "web_search"),
    ("/api/agent-tools/run_skill", "run_skill"),
    ("/api/agent-tools/emit_chart", "emit_chart"),
    ("/api/agent-tools/emit_citation", "emit_citation"),
]


# ---------------------------------------------------------------------------
# (1) Bearer auth
# ---------------------------------------------------------------------------


def test_bearer_missing_authorization_returns_401(client: TestClient) -> None:
    r = client.post(
        "/api/agent-tools/query_database",
        json=_envelope(),
    )
    assert r.status_code == 401, r.text


def test_bearer_wrong_token_returns_401(client: TestClient) -> None:
    r = client.post(
        "/api/agent-tools/query_database",
        headers={"Authorization": "Bearer not-the-secret"},
        json=_envelope(),
    )
    assert r.status_code == 401, r.text


def test_bearer_env_unset_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """If `AGENT_TOOLS_BEARER` is empty the router fails closed (503)."""
    monkeypatch.delenv("AGENT_TOOLS_BEARER", raising=False)
    app = FastAPI()
    app.include_router(agent_tools_mod.router)
    c = TestClient(app)
    r = c.post(
        "/api/agent-tools/query_database",
        headers={"Authorization": "Bearer anything"},
        json=_envelope(),
    )
    assert r.status_code == 503, r.text


def test_bearer_correct_token_allows_call(
    client: TestClient, stub_db, stub_skill_ctx, stub_dispatch
) -> None:
    stub_dispatch["behavior"]["return_value"] = {"rows": []}
    r = client.post(
        "/api/agent-tools/query_database",
        headers={"Authorization": "Bearer test-bearer-secret"},
        json=_envelope(args={"sql": "SELECT 1"}),
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# (2) Each POST tool wraps a successful tool call into {"ok": true, ...}
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path,tool_name", _TOOL_PATHS)
def test_tool_success_envelope(
    path: str,
    tool_name: str,
    client: TestClient,
    stub_db,
    stub_skill_ctx,
    stub_dispatch,
) -> None:
    expected_result = {"tool_marker": tool_name, "rows": [{"x": 1}]}
    stub_dispatch["behavior"]["return_value"] = expected_result

    r = client.post(
        path,
        headers={"Authorization": "Bearer test-bearer-secret"},
        json=_envelope(args={"foo": "bar"}),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body
    assert body["result"] == expected_result, body

    # The dispatcher must have been called once with the right tool name
    # and the args we sent.
    assert len(stub_dispatch["calls"]) == 1
    call = stub_dispatch["calls"][0]
    assert call["name"] == tool_name
    assert call["args"] == {"foo": "bar"}


# ---------------------------------------------------------------------------
# (3) Each POST tool wraps a tool exception into the failure envelope
#     (HTTP 200, ok=false, code=TOOL_FAILED).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path,tool_name", _TOOL_PATHS)
def test_tool_exception_envelope(
    path: str,
    tool_name: str,
    client: TestClient,
    stub_db,
    stub_skill_ctx,
    stub_dispatch,
) -> None:
    stub_dispatch["behavior"]["raise"] = RuntimeError(f"{tool_name}_blew_up")

    r = client.post(
        path,
        headers={"Authorization": "Bearer test-bearer-secret"},
        json=_envelope(),
    )
    # PRD R8 / ARCH 11b §3.3: failures are HTTP 200 with ok=false so the
    # plugin can hand the JSON straight back to the model.
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False, body
    assert body["code"] == "TOOL_FAILED", body
    assert tool_name in body["error"] or "blew_up" in body["error"], body


# ---------------------------------------------------------------------------
# (4) 422 on malformed body (envelope rejects missing context.insight_id).
# ---------------------------------------------------------------------------


def test_malformed_body_returns_422(client: TestClient) -> None:
    """A body missing the `context` block (and thus `context.insight_id`)
    must fail Pydantic validation with 422 before reaching the tool layer.
    """
    r = client.post(
        "/api/agent-tools/query_database",
        headers={"Authorization": "Bearer test-bearer-secret"},
        json={"args": {"sql": "SELECT 1"}},  # no "context" key at all
    )
    assert r.status_code == 422, r.text


def test_malformed_body_missing_insight_id_returns_422(client: TestClient) -> None:
    r = client.post(
        "/api/agent-tools/query_database",
        headers={"Authorization": "Bearer test-bearer-secret"},
        json={"args": {}, "context": {}},  # context present but no insight_id
    )
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# (5) GET /api/agent-tools/insight-context shape
# ---------------------------------------------------------------------------


def test_insight_context_returns_build_chat_context_shape(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The GET endpoint must return whatever `_build_chat_context` does,
    plus `thread_id` and `parent_session_id` (ADDENDUM 11c §G/§H).

    We patch the lazy imports inside `routers.insights` and stub the
    DB session factory and the `AIInsight` ORM lookup.
    """
    insight_id = uuid.uuid4()
    expected_ctx = {
        "insight_id": str(insight_id),
        "headline": "Crusoe ICY-12 ramp",
        "body": "...",
        "skills_run": ["energy_buildout"],
        "confidence": "high",
        "materiality": "high",
        "chart": None,
        "citations": [],
    }

    # Build a fake `routers.insights` module exporting just what the
    # endpoint uses, so we don't need to import the real heavy module.
    fake_insights = types.ModuleType("routers.insights")

    async def _fake_build_chat_context(db, _insight_id):
        return dict(expected_ctx)

    async def _fake_get_or_create_thread(db, *, insight_id):
        return types.SimpleNamespace(id=uuid.UUID("11111111-1111-1111-1111-111111111111"))

    fake_insights._build_chat_context = _fake_build_chat_context  # type: ignore[attr-defined]
    fake_insights._get_or_create_thread = _fake_get_or_create_thread  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "routers.insights", fake_insights)

    # The endpoint also calls `select(AIInsight).where(AIInsight.id == ...)`
    # then `db.execute(...).scalar_one_or_none()`. We don't care about the
    # SQL — only that the session returns a row with `session_id`. So we
    # short-circuit `sqlalchemy.select` to a passthrough sentinel; the
    # session's `.execute` then ignores it and returns our row.
    import sqlalchemy as _sa

    class _FakeSelect:
        def where(self, *_a, **_kw):
            return self

        def order_by(self, *_a, **_kw):
            return self

        def limit(self, *_a, **_kw):
            return self

    def _fake_select(*_a, **_kw):
        return _FakeSelect()

    monkeypatch.setattr(_sa, "select", _fake_select)

    # Provide an AIInsight stub (only its identity is used; never the columns).
    fake_models = types.ModuleType("agents.insights.db.models")

    class _FakeAIInsight:
        id = object()  # any attribute access is fine; equality is unused

    fake_models.AIInsight = _FakeAIInsight  # type: ignore[attr-defined]
    for parent in ("agents", "agents.insights", "agents.insights.db"):
        if parent not in sys.modules:
            mod = types.ModuleType(parent)
            mod.__path__ = []  # type: ignore[attr-defined]
            sys.modules[parent] = mod
    monkeypatch.setitem(sys.modules, "agents.insights.db.models", fake_models)

    parent_session_uuid = uuid.UUID("22222222-2222-2222-2222-222222222222")

    class _FakeRow:
        def __init__(self, sid):
            self.session_id = sid

    class _FakeResult:
        def __init__(self, row):
            self._row = row

        def scalar_one_or_none(self):
            return self._row

    class _Session:
        async def execute(self, *_a, **_kw):
            return _FakeResult(_FakeRow(parent_session_uuid))

        async def commit(self):
            return None

        async def rollback(self):
            return None

        async def close(self):
            return None

    monkeypatch.setattr(agent_tools_mod, "async_session_factory", lambda: _Session())

    r = client.get(
        f"/api/agent-tools/insight-context?insight_id={insight_id}",
        headers={"Authorization": "Bearer test-bearer-secret"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Underlying chat-context fields preserved.
    for k, v in expected_ctx.items():
        assert body[k] == v, (k, body)
    # Plus the two enrichments.
    assert body["thread_id"] == "11111111-1111-1111-1111-111111111111"
    assert body["parent_session_id"] == str(parent_session_uuid)


def test_insight_context_bad_uuid_returns_422(client: TestClient) -> None:
    r = client.get(
        "/api/agent-tools/insight-context?insight_id=not-a-uuid",
        headers={"Authorization": "Bearer test-bearer-secret"},
    )
    assert r.status_code == 422, r.text


def test_insight_context_requires_bearer(client: TestClient) -> None:
    r = client.get(
        f"/api/agent-tools/insight-context?insight_id={uuid.uuid4()}",
    )
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# (6) Bad insight_id in POST envelope returns the failure envelope
#     (graceful-degradation contract: HTTP 200, ok=false).
# ---------------------------------------------------------------------------


def test_bad_insight_id_in_post_returns_failure_envelope(
    client: TestClient, stub_db, stub_skill_ctx, stub_dispatch
) -> None:
    r = client.post(
        "/api/agent-tools/query_database",
        headers={"Authorization": "Bearer test-bearer-secret"},
        json={"args": {}, "context": {"insight_id": "not-a-uuid"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["code"] == "TOOL_FAILED"
    assert "bad_insight_id" in body["error"]
