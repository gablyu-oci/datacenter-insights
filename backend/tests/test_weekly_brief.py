"""
Unit tests for the weekly_brief agent.

Phase 4 retarget: ``generate_weekly_brief`` now drives an OpenClaw
agentic turn through the shared ``_drive_openclaw_stream`` helper
instead of calling ``llm_client.reason``. These tests:

  1. Lock down the Sunday-cron 24h grace window (AC7).
  2. Lock down that the agent path falls back to a synthetic BriefRun
     when the gateway is unreachable (so the UI card never goes stale).
  3. Lock down the cap-trip path (tool/wall) flips to the fallback row
     since persist_brief was never called.
  4. Lock down the outer ``asyncio.wait_for`` TimeoutError path also
     reaches the fallback row.

Tests do NOT hit a real database, real Llama Stack, or real OpenClaw —
they monkeypatch ``httpx`` inside ``openclaw.forwarder`` (mirroring
the pattern from ``test_agentic_synthesis.py`` / ``test_openclaw_forwarder.py``).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import types
from datetime import date, datetime
from typing import Any, AsyncIterator

import pytest


# Ensure backend root is on sys.path
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ---------------------------------------------------------------------------
# Shared helpers (in-memory FakeSession + httpx shim)
# ---------------------------------------------------------------------------


class _FakeRow:
    """Stand-in for a `BriefRun` ORM row when the brief lookup misses."""


class FakeSession:
    """Minimal AsyncSession-shaped stub.

    Captures `db.add(...)` calls so the test can assert that the
    fallback BriefRun was written. ``execute`` always returns an empty
    result so `_lookup_latest_brief_row` returns None and we drop into
    the fallback branch.
    """

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None

    async def rollback(self):
        return None

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = 1
        return obj

    async def flush(self):
        return None

    async def execute(self, *a, **k):
        class _R:
            def scalars(self_inner):
                return self_inner

            def all(self_inner):
                return []

            def first(self_inner):
                return None

            def fetchall(self_inner):
                return []

            def scalar(self_inner):
                return 0

            def scalar_one_or_none(self_inner):
                return None

        return _R()


def _sse(chunk: dict) -> str:
    return f"data: {json.dumps(chunk)}"


def _delta(*, content: str | None = None,
           tool_call: dict | None = None,
           finish_reason: str | None = None) -> dict:
    delta: dict = {}
    if content is not None:
        delta["content"] = content
    if tool_call is not None:
        delta["tool_calls"] = [tool_call]
    return {"choices": [{"delta": delta, "finish_reason": finish_reason}]}


class _FakeStreamResponse:
    def __init__(self, *, status_code: int, lines: list[str],
                 sleep_per_line: float = 0.0) -> None:
        self.status_code = status_code
        self._lines = lines
        self._sleep = sleep_per_line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def aiter_lines(self) -> AsyncIterator[str]:
        for ln in self._lines:
            if self._sleep:
                await asyncio.sleep(self._sleep)
            else:
                await asyncio.sleep(0)
            yield ln

    async def aread(self) -> bytes:
        return b""


class _FakeAsyncClient:
    def __init__(self, *, status_code: int, lines: list[str],
                 sleep_per_line: float = 0.0) -> None:
        self._status = status_code
        self._lines = lines
        self._sleep = sleep_per_line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    def stream(self, method: str, url: str, *, headers=None, json=None):
        return _FakeStreamResponse(
            status_code=self._status,
            lines=self._lines,
            sleep_per_line=self._sleep,
        )


@pytest.fixture
def fake_httpx(monkeypatch: pytest.MonkeyPatch):
    """Patch ``httpx`` inside ``openclaw.forwarder`` only.

    Yields a state dict the test can mutate to set the canned status
    code + SSE lines for the next call.
    """
    import httpx as _real_httpx
    import openclaw.forwarder as fwd_mod

    state: dict[str, Any] = {"status": 200, "lines": [], "sleep_per_line": 0.0}

    def _factory(*_a, **_kw):
        return _FakeAsyncClient(
            status_code=state["status"],
            lines=state["lines"],
            sleep_per_line=state["sleep_per_line"],
        )

    fake_mod = types.SimpleNamespace(
        AsyncClient=_factory,
        Timeout=_real_httpx.Timeout,
        TimeoutException=_real_httpx.TimeoutException,
        HTTPError=_real_httpx.HTTPError,
    )
    monkeypatch.setattr(fwd_mod, "httpx", fake_mod)
    return state


@pytest.fixture
def stub_context(monkeypatch: pytest.MonkeyPatch):
    """Replace `_build_context` so the brief flow doesn't need a real DB."""
    from agents import weekly_brief as wb

    async def fake_build_context(session, period_start):
        return {
            "sites": [],
            "events": [],
            "energy_projects": [],
            "edgar_extractions": [],
            "counts": {
                "sites": 0,
                "events": 0,
                "energy_projects": 0,
                "edgar_extractions": 0,
            },
        }

    monkeypatch.setattr(wb, "_build_context", fake_build_context)


# ---------------------------------------------------------------------------
# 1. AC7: Sunday cron registers with a 24h grace window.
# ---------------------------------------------------------------------------


def test_weekly_brief_cron_grace_window():
    """AC7: the weekly_brief job must have a 24h misfire_grace_time so a
    missed Sunday run still fires when the backend comes back up.
    """
    from pipeline.runner import create_scheduler

    sched = create_scheduler()
    job = sched.get_job("weekly_brief")
    assert job is not None, "weekly_brief job should be registered"
    assert job.misfire_grace_time is not None
    assert job.misfire_grace_time >= 86400, (
        f"weekly_brief grace must be >= 24h to survive a missed Sunday; "
        f"got {job.misfire_grace_time}s"
    )
    assert job.coalesce is True, "weekly_brief must coalesce missed runs"


def test_quarterly_filings_cron_grace_window():
    """The quarterly_filings_daily cron is registered with at least the daily
    1h grace (post-the user-round-2 weekly→daily rename in pipeline/runner.py)."""
    from pipeline.runner import create_scheduler

    sched = create_scheduler()
    job = sched.get_job("quarterly_filings_daily")
    assert job is not None
    assert job.misfire_grace_time >= 3600


# ---------------------------------------------------------------------------
# 2. Fallback path — gateway returns 5xx -> synthetic BriefRun row.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_brief_falls_back_when_gateway_down(
    fake_httpx, stub_context
):
    """If the OpenClaw gateway is unreachable (HTTP error), the agent
    flow ends degraded WITHOUT persisting any BriefRun, so
    ``generate_weekly_brief`` must write a synthetic fallback row.
    """
    from agents import weekly_brief as wb

    # Force a 503 response from the fake gateway -> degraded close,
    # accumulator never sees finalize_session.
    fake_httpx["status"] = 503
    fake_httpx["lines"] = []

    sess = FakeSession()
    row = await wb.generate_weekly_brief(sess)

    assert row is not None
    assert getattr(row, "markdown", None), (
        "BriefRun.markdown must be populated on the fallback path"
    )
    assert "Top developments" in row.markdown
    # The fallback writer adds the row via session.add(...).
    assert any(
        type(o).__name__ == "BriefRun" for o in sess.added
    ), sess.added
    # prompt_version should carry the +fallback suffix so ops can tell
    # this row from a real agent-driven brief.
    assert "fallback" in (row.prompt_version or ""), row.prompt_version


# ---------------------------------------------------------------------------
# 3. Cap exceeded — 21 web_search tool_calls in one turn -> tool_cap
#    -> degraded close, no persist_brief seen, fallback row written.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_brief_tool_cap_trips_fallback(
    fake_httpx, stub_context
):
    from agents import weekly_brief as wb

    chunks: list[dict] = []
    for i in range(21):  # cap_tool_calls=20 in weekly_brief; 21 trips it
        chunks.append(_delta(tool_call={
            "index": i,
            "id": f"call_{i}",
            "function": {
                "name": "web_search",
                "arguments": '{"query":"q"}',
            },
        }))
    chunks.append(_delta(finish_reason="tool_calls"))
    chunks.append(_delta(finish_reason="stop"))
    fake_httpx["status"] = 200
    fake_httpx["lines"] = [_sse(c) for c in chunks] + ["data: [DONE]"]

    sess = FakeSession()
    row = await wb.generate_weekly_brief(sess)

    # Cap-tripped close means agent never called persist_brief -> fallback.
    assert row is not None
    assert "fallback" in (row.prompt_version or ""), row.prompt_version
    assert any(
        type(o).__name__ == "BriefRun" for o in sess.added
    )


# ---------------------------------------------------------------------------
# 4. Outer asyncio.wait_for TimeoutError -> fallback row.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_brief_outer_timeout_falls_back(
    fake_httpx, stub_context, monkeypatch
):
    from agents import weekly_brief as wb

    # Patch asyncio.wait_for inside the weekly_brief module so the
    # call raises TimeoutError immediately. Mirrors the pattern from
    # tests/test_agentic_synthesis.py.
    real_wait_for = asyncio.wait_for

    async def _instant_timeout(coro, timeout):
        # Cancel the coro to keep asyncio happy and raise.
        try:
            coro.close()
        except Exception:  # noqa: BLE001
            pass
        raise asyncio.TimeoutError("forced for test")

    monkeypatch.setattr(wb.asyncio, "wait_for", _instant_timeout)

    sess = FakeSession()
    row = await wb.generate_weekly_brief(sess)

    assert row is not None
    assert "fallback" in (row.prompt_version or "")
    assert any(
        type(o).__name__ == "BriefRun" for o in sess.added
    )

    # Restore (defensive — monkeypatch undoes anyway, but other tests
    # in the same file shouldn't observe the patched wait_for).
    monkeypatch.setattr(wb.asyncio, "wait_for", real_wait_for)


# ---------------------------------------------------------------------------
# 5. session_key shape: weekly-brief-YYYYWW (ISO year+week, zero-padded).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_brief_session_key_shape(
    fake_httpx, stub_context, monkeypatch
):
    """Capture the session_key passed to `_drive_openclaw_stream` and
    assert it matches `weekly-brief-YYYYWW`.
    """
    from agents import weekly_brief as wb

    captured: dict[str, Any] = {}

    async def _fake_drive(**kwargs):
        captured["session_key"] = kwargs.get("session_key")
        # Return a minimal degraded result so the wrapper proceeds to
        # the fallback path (we don't care about the row body here).
        from openclaw.forwarder import StreamResult

        return StreamResult(degraded=True, reason="test", total_chunks=0)

    monkeypatch.setattr(wb, "_drive_openclaw_stream", _fake_drive)

    sess = FakeSession()
    await wb.generate_weekly_brief(sess)

    key = captured.get("session_key")
    assert isinstance(key, str)
    assert key.startswith("weekly-brief-"), key
    suffix = key.removeprefix("weekly-brief-")
    # YYYYWW: 6 digits, year 4 + week 2 (zero-padded)
    assert len(suffix) == 6, suffix
    assert suffix.isdigit(), suffix
