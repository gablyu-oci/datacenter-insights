"""V2 emit_citation tool tests.

Pins behaviour of `agents/insights/tools/emit_citation.py`:
- snippet > 280 chars => `error="snippet_too_long"` (rejected)
- rationale not a substring of snippet => `error="rationale_unsupported"`
- agree/disagree tag without GW/MW/%/$ token in snippet => downgrade to
  `context` with a non-fatal warning (still ok=True)
- URL HEAD reachability: 200 => persist; 404 / connection error => reject
  with `url_unreachable`
- ≥2 citations contract: encoded via the persister callback (counter held
  in the test harness; tool itself emits per-call so the persister is the
  single source of truth that flips the `low_external_support` flag)
"""
from __future__ import annotations

import os
import sys
import types
from typing import Any

import httpx
import pytest

# ---------------------------------------------------------------------------
# Stub the tools package so its __init__ doesn't pull sql_gate/sqlglot.
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))
for p in (BACKEND_ROOT, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

if "agents.insights.tools" not in sys.modules or not hasattr(
    sys.modules["agents.insights.tools"], "_v2_test_stub"
):
    if "agents.insights.tools" not in sys.modules:
        import agents  # noqa: F401
        import agents.insights  # noqa: F401

        pkg = types.ModuleType("agents.insights.tools")
        pkg.__path__ = [os.path.join(BACKEND_ROOT, "agents", "insights", "tools")]
        pkg._v2_test_stub = True  # type: ignore[attr-defined]
        sys.modules["agents.insights.tools"] = pkg

import agents.insights.tools.emit_citation  # noqa: E402,F401

# `agents/insights/tools/__init__.py` does `from .emit_citation import emit_citation`,
# which rebinds the package attribute `emit_citation` to the function. Pull the
# actual module from sys.modules so cross-test runs don't get the function here.
ec = sys.modules["agents.insights.tools.emit_citation"]


# ---------------------------------------------------------------------------
# httpx HEAD fakes
# ---------------------------------------------------------------------------


class _FakeHeadResp:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _FakeAsyncClient:
    """Replace httpx.AsyncClient inside emit_citation for HEAD reachability."""

    head_responses: list[Any] = []
    head_calls: list[str] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_a: Any) -> None:
        return None

    async def head(self, url: str, follow_redirects: bool = True) -> _FakeHeadResp:
        type(self).head_calls.append(url)
        if not type(self).head_responses:
            raise AssertionError("FakeAsyncClient: no canned HEAD response queued")
        nxt = type(self).head_responses.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


@pytest.fixture(autouse=True)
def _patch_httpx(monkeypatch: pytest.MonkeyPatch):
    _FakeAsyncClient.head_responses = []
    _FakeAsyncClient.head_calls = []
    monkeypatch.setattr(ec.httpx, "AsyncClient", _FakeAsyncClient)
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_GOOD_URL = "https://example.com/article"


def _ok_head_once() -> None:
    _FakeAsyncClient.head_responses.append(_FakeHeadResp(200))


# ---------------------------------------------------------------------------
# (2a) snippet > 280 chars => rejected (impl rejects with snippet_too_long;
# kickoff said "truncates and still accepts" but actual contract is reject).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snippet_over_max_is_rejected():
    _ok_head_once()
    long_snippet = "Microsoft commissioned 12 GW " + ("y" * 300)
    assert len(long_snippet) > ec.SNIPPET_MAX

    out = await ec.emit_citation(
        url=_GOOD_URL,
        title="X",
        snippet=long_snippet,
        agree_or_disagree="context",
        rationale="Microsoft commissioned 12 GW",
        search_query="ms power",
    )

    assert out["ok"] is False
    assert out["error"] == "snippet_too_long"
    # Should not have made a HEAD call (length check is first).
    assert _FakeAsyncClient.head_calls == []


# ---------------------------------------------------------------------------
# (2b) rationale not contained in snippet => rejected with rationale_unsupported
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rationale_not_in_snippet_is_rejected():
    _ok_head_once()
    out = await ec.emit_citation(
        url=_GOOD_URL,
        title="X",
        snippet="Microsoft signed a 12 GW deal in Texas this quarter.",
        agree_or_disagree="agree",
        rationale="Amazon brokered a 99 GW pact in Ohio",
        search_query="q",
    )
    assert out["ok"] is False
    assert out["error"] == "rationale_unsupported"


# ---------------------------------------------------------------------------
# (2c) agree/disagree tag with no GW/MW/%/$ numeric token in snippet =>
#      downgraded to 'context' (still ok=True, with warnings).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agree_without_quant_token_downgrades_to_context():
    _ok_head_once()
    out = await ec.emit_citation(
        url=_GOOD_URL,
        title="X",
        snippet="The hyperscaler increased its data center footprint substantially.",
        agree_or_disagree="agree",
        rationale="increased its data center footprint",
        search_query="q",
    )
    assert out["ok"] is True, out
    assert out["citation"]["agree_or_disagree"] == "context"
    assert "warnings" in out
    assert any("downgraded" in w for w in out["warnings"])


@pytest.mark.asyncio
async def test_agree_with_quant_token_keeps_tag():
    _ok_head_once()
    out = await ec.emit_citation(
        url=_GOOD_URL,
        title="X",
        snippet="Oracle commissioned 11.6 GW of new capacity.",
        agree_or_disagree="agree",
        rationale="Oracle commissioned 11.6 GW of new capacity",
        search_query="q",
    )
    assert out["ok"] is True
    assert out["citation"]["agree_or_disagree"] == "agree"


# ---------------------------------------------------------------------------
# (2d) URL HEAD reachability: 200 persists; 404 + connection error rejected.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_head_200_persists():
    _ok_head_once()
    persisted: list[dict[str, Any]] = []

    async def persister(payload: dict[str, Any]) -> str:
        persisted.append(payload)
        return "cit-123"

    out = await ec.emit_citation(
        url=_GOOD_URL,
        title="X",
        snippet="Oracle commissioned 11.6 GW of new capacity.",
        agree_or_disagree="agree",
        rationale="Oracle commissioned 11.6 GW",
        search_query="q",
        persister=persister,
    )
    assert out["ok"] is True
    assert out.get("citation_id") == "cit-123"
    assert len(persisted) == 1


@pytest.mark.asyncio
async def test_head_404_rejected_with_url_unreachable():
    _FakeAsyncClient.head_responses.append(_FakeHeadResp(404))
    out = await ec.emit_citation(
        url=_GOOD_URL,
        title="X",
        snippet="Oracle commissioned 11.6 GW of new capacity.",
        agree_or_disagree="agree",
        rationale="Oracle commissioned 11.6 GW",
        search_query="q",
    )
    assert out["ok"] is False
    assert out["error"] == "url_unreachable"


@pytest.mark.asyncio
async def test_head_connection_error_rejected_with_url_unreachable():
    _FakeAsyncClient.head_responses.append(httpx.ConnectError("boom"))
    out = await ec.emit_citation(
        url=_GOOD_URL,
        title="X",
        snippet="Oracle commissioned 11.6 GW of new capacity.",
        agree_or_disagree="agree",
        rationale="Oracle commissioned 11.6 GW",
        search_query="q",
    )
    assert out["ok"] is False
    assert out["error"] == "url_unreachable"


# ---------------------------------------------------------------------------
# (2e) The 2-citation rule for low_external_support is enforced *outside*
# emit_citation -- the tool itself emits per-call. We assert the contract by
# letting the persister act as the SkillContext counter, the same way the
# real router will: low_external_support flips False only when ≥2 valid
# citations have been persisted.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_citation_contract_via_persister_counter():
    state = {"count": 0, "low_external_support": True}

    async def persister(payload: dict[str, Any]) -> str:
        state["count"] += 1
        if state["count"] >= 2:
            state["low_external_support"] = False
        return f"cit-{state['count']}"

    # First citation -- still flagged.
    _ok_head_once()
    r1 = await ec.emit_citation(
        url="https://example.com/a",
        title="A",
        snippet="Amazon committed 17.9 GW of new capacity.",
        agree_or_disagree="agree",
        rationale="Amazon committed 17.9 GW",
        search_query="q",
        persister=persister,
    )
    assert r1["ok"] is True
    assert state["count"] == 1
    assert state["low_external_support"] is True, (
        "low_external_support must remain True after a single valid citation"
    )

    # Second citation -- flips the flag.
    _ok_head_once()
    r2 = await ec.emit_citation(
        url="https://example.com/b",
        title="B",
        snippet="Microsoft signed a 10.47 GW pact this quarter.",
        agree_or_disagree="agree",
        rationale="Microsoft signed a 10.47 GW pact",
        search_query="q",
        persister=persister,
    )
    assert r2["ok"] is True
    assert state["count"] == 2
    assert state["low_external_support"] is False, (
        "low_external_support must flip False after the 2nd valid citation"
    )
