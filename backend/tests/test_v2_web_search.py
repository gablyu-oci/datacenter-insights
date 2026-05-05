"""V2 web_search tool tests.

Pins behaviour of `agents/insights/tools/web_search.py`:
- per-session cap of 8 calls
- 280-char snippet truncation
- result rows tagged with `provider="brave"`
- 3 consecutive 5xx open the circuit; subsequent calls short-circuit to the
  documented degraded shape with `reason="circuit_open"`
- missing `BRAVE_SEARCH_API_KEY` returns degraded shape with `reason="no_api_key"`
  and does not raise
- `judge_citations` normalises tags to {"agree","disagree","context"}
"""
from __future__ import annotations

import importlib
import os
import sys
import time
import types
from typing import Any

import httpx
import pytest

# ---------------------------------------------------------------------------
# Bootstrap: stub `agents.insights.tools` package so its __init__ doesn't
# pull in sql_gate (which imports sqlglot, not present in this env).
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))
for p in (BACKEND_ROOT, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


def _ensure_tools_stub() -> None:
    if "agents.insights.tools" in sys.modules and not hasattr(
        sys.modules["agents.insights.tools"], "__path__"
    ):
        return
    if "agents.insights.tools" in sys.modules and hasattr(
        sys.modules["agents.insights.tools"], "validate_sql"
    ):
        # already real-imported; keep it
        return
    import agents  # noqa: F401
    import agents.insights  # noqa: F401

    pkg = types.ModuleType("agents.insights.tools")
    pkg.__path__ = [os.path.join(BACKEND_ROOT, "agents", "insights", "tools")]
    sys.modules["agents.insights.tools"] = pkg


_ensure_tools_stub()

import agents.insights.tools.web_search as ws  # noqa: E402

importlib.reload(ws)  # ensure fresh module-level circuit state


# ---------------------------------------------------------------------------
# httpx fakes
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, body: dict[str, Any] | None = None):
        self.status_code = status_code
        self._body = body or {}

    def json(self) -> dict[str, Any]:
        return self._body


class _FakeAsyncClient:
    """Drop-in replacement for httpx.AsyncClient used by web_search.web_search."""

    next_responses: list[_FakeResponse] = []
    raise_exc: BaseException | None = None
    calls: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_a: Any) -> None:
        return None

    async def get(self, url: str, headers=None, params=None) -> _FakeResponse:
        type(self).calls.append({"url": url, "headers": headers or {}, "params": params or {}})
        if type(self).raise_exc is not None:
            exc = type(self).raise_exc
            type(self).raise_exc = None
            raise exc
        if not type(self).next_responses:
            raise AssertionError("FakeAsyncClient: no canned response queued")
        return type(self).next_responses.pop(0)


@pytest.fixture(autouse=True)
def _reset_circuit_and_fakes(monkeypatch: pytest.MonkeyPatch):
    # Reset the module-level circuit between tests.
    ws._circuit.consecutive_failures = 0
    ws._circuit.first_failure_ts = None
    ws._circuit.unhealthy_until_ts = 0.0
    _FakeAsyncClient.next_responses = []
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.raise_exc = None
    monkeypatch.setattr(ws.httpx, "AsyncClient", _FakeAsyncClient)
    yield


def _brave_body(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"web": {"results": rows}}


# ---------------------------------------------------------------------------
# (1a) Happy path: 3 hits, snippets truncated, provider="brave",
#      cap of 8 enforced.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_returns_brave_rows_and_truncates_snippets(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")
    long = "x" * 500  # > 280
    _FakeAsyncClient.next_responses = [
        _FakeResponse(
            200,
            _brave_body(
                [
                    {"url": "https://a.example", "title": "A", "description": long},
                    {"url": "https://b.example", "title": "B", "description": "short"},
                    {"url": "https://c.example", "title": "C", "description": "ok desc"},
                ]
            ),
        )
    ]

    result = await ws.web_search("hyperscaler power", n=3, ctx=None)

    assert result["ok"] is True, result
    rows = result["results"]
    assert len(rows) == 3
    assert all(r["provider"] == "brave" for r in rows)
    assert all(len(r["snippet"]) <= ws.SNIPPET_MAX for r in rows)
    # The first row's snippet must be a truncated form of the long string.
    assert rows[0]["snippet"].endswith("…")


@pytest.mark.asyncio
async def test_per_session_cap_blocks_after_eight_calls(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")

    class _Ctx:
        web_search_count = 8  # already at cap

    out = await ws.web_search("q", ctx=_Ctx())
    assert out == {
        "ok": False,
        "error": "web_search_cap",
        "detail": {"used": 8, "cap": ws.PER_SESSION_CAP},
    }
    # No HTTP call should have been made.
    assert _FakeAsyncClient.calls == []


# ---------------------------------------------------------------------------
# (1b) 3 consecutive 5xx -> circuit opens; 4th call short-circuits.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_three_5xx_open_circuit_then_short_circuits(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-key")
    _FakeAsyncClient.next_responses = [
        _FakeResponse(503),
        _FakeResponse(502),
        _FakeResponse(500),
    ]

    for _ in range(3):
        r = await ws.web_search("q")
        assert r["ok"] is False
        assert r["error"] == "upstream_5xx"

    # Circuit must now be open.
    assert ws._circuit.is_open(), "expected circuit to be open after 3 consecutive 5xx"

    pre_calls = len(_FakeAsyncClient.calls)
    out = await ws.web_search("q-after-trip")
    assert out == {
        "ok": True,
        "results": [],
        "degraded": True,
        "reason": "circuit_open",
    }
    # No additional HTTP call made (short-circuit).
    assert len(_FakeAsyncClient.calls) == pre_calls


# ---------------------------------------------------------------------------
# (1c) Missing API key -> graceful degradation, no exception.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_api_key_returns_degraded(monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    out = await ws.web_search("q")
    assert out == {
        "ok": True,
        "results": [],
        "degraded": True,
        "reason": "no_api_key",
    }
    # No HTTP call attempted.
    assert _FakeAsyncClient.calls == []


@pytest.mark.asyncio
async def test_missing_api_key_emits_unavailable_event(monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    seen: list[Any] = []

    class _Ctx:
        session_id = "sess-1"
        insight_id = None

        async def emit_event(self, evt: Any) -> None:
            seen.append(evt)

    out = await ws.web_search("q", ctx=_Ctx())
    assert out["reason"] == "no_api_key"
    assert seen, "expected web_search_unavailable SSE emission"
    evt = seen[0]
    assert getattr(evt, "event", None) == "web_search_unavailable"
    assert evt.data.reason == "no_api_key"


# ---------------------------------------------------------------------------
# (1d) judge_citations: normalise tag enum.
# ---------------------------------------------------------------------------


class _FakeTurn:
    def __init__(self, content: str):
        self.content = content
        self.tool_calls = None
        self.model = "fake"
        self.tokens = {}


@pytest.mark.asyncio
async def test_judge_citations_normalises_tags(monkeypatch):
    """The judge LLM returns mixed-case + bogus tags. The tagger must clamp
    everything to the enum {"agree","disagree","context"}.
    """
    canned = (
        '[{"url":"https://a.example","tag":"AGREE","rationale":"matches snippet"},'
        '{"url":"https://b.example","tag":"DISAGREE","rationale":"matches snippet"},'
        '{"url":"https://c.example","tag":"context","rationale":"matches snippet"},'
        '{"url":"https://d.example","tag":"foobar","rationale":"matches snippet"}]'
    )

    class _FakeClient:
        async def reason(self, **kwargs: Any) -> _FakeTurn:
            return _FakeTurn(canned)

    # Patch via the import path the module uses (lazy import inside function).
    import backend.llm.client as real_client_mod

    monkeypatch.setattr(real_client_mod, "llm_client", _FakeClient(), raising=True)

    results = [
        {"url": "https://a.example", "title": "A", "snippet": "matches snippet"},
        {"url": "https://b.example", "title": "B", "snippet": "matches snippet"},
        {"url": "https://c.example", "title": "C", "snippet": "matches snippet"},
        {"url": "https://d.example", "title": "D", "snippet": "matches snippet"},
    ]
    out = await ws.judge_citations("OCI vs AWS power buildout", results)
    by_url = {r["url"]: r for r in out}
    assert by_url["https://a.example"]["tag"] == "agree"
    assert by_url["https://b.example"]["tag"] == "disagree"
    assert by_url["https://c.example"]["tag"] == "context"
    # Out-of-enum -> safe default 'context'.
    assert by_url["https://d.example"]["tag"] == "context"
