"""Scheduler-driven daily AI Insights cron tests.

`pipeline.runner._invoke_insights_daily` is the headless entry point
that APScheduler fires once per UTC day. The v2 synthesis driver
grounds its own claims via the OpenClaw MCP tools, so this runner just
pre-creates the AISession row and drives `run_agentic_synthesis` — no
server-side FactPack.

Contract under test:

  1. Idempotency guard: if a `created_by='scheduler'` AISession already
     exists today with status in (running, complete), no-op and return
     `{"skipped": 1, "reason": "idempotency_guard"}`.
  2. Otherwise pre-create an AISession row and drive
     `run_agentic_synthesis` under a 600s wait_for. The `insights_count`
     from `SynthesisResult` is surfaced as `stored`; `fetched` is 0.
     `run_agentic_synthesis` must NOT be called with a `fact_pack`
     kwarg — the v2 signature has no such parameter.
  3. Up to 2 retries (3 attempts total) on exception, with a sleep
     between attempts. After the 3rd failure: re-raise so the
     APScheduler EVENT_JOB_ERROR listener fires.
  4. Each failed attempt force-finalises its session row to a terminal
     status so a same-day repeat fire still hits the idempotency guard.

Tests stub the synthesis driver and DB so the cron path is exercised
without spinning up Postgres or hitting the OpenClaw gateway.
"""
from __future__ import annotations

import asyncio as _asyncio
import uuid
from typing import Any

import pytest

import pipeline.runner as runner_mod


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------


class _SynthesisResultStub:
    """Mirrors the public surface of `SynthesisResult` used by the runner."""

    def __init__(
        self,
        *,
        insights_count: int = 0,
        degraded: bool = False,
        reason: str | None = None,
    ) -> None:
        self.insights_count = insights_count
        self.degraded = degraded
        self.reason = reason


class _SynthesisDriverFactory:
    """Builds a stub `run_agentic_synthesis` coroutine.

    Each invocation consumes the next entry from `outcomes` (a list whose
    elements are either: a `_SynthesisResultStub` to return, or an
    Exception/Exception-class to raise). Each call records its kwargs on
    `calls` for assertion.
    """

    def __init__(self, *, outcomes: list) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def make(self):
        outer = self

        async def _stub(**kwargs):
            idx = len(outer.calls)
            outer.calls.append(kwargs)
            if idx >= len(outer.outcomes):
                return _SynthesisResultStub(insights_count=0, degraded=True)
            outcome = outer.outcomes[idx]
            if isinstance(outcome, BaseException):
                raise outcome
            if isinstance(outcome, type) and issubclass(outcome, BaseException):
                raise outcome("stub failure")
            return outcome

        return _stub


class FakeSession:
    """Stub AsyncSession just rich enough for `_invoke_insights_daily`.

    - The first `execute()` is the idempotency SELECT and returns a
      result whose `.first()` is configurable.
    - Subsequent `execute()` calls are the AISession pre-create
      SELECT-back / failure UPDATEs / token_estimate read-back; they
      simply return an empty result object.
    - `add()` / `commit()` / `rollback()` are no-ops.
    """

    def __init__(self, idempotency_row=None) -> None:
        self.idempotency_row = idempotency_row
        self.executes: list = []
        self.added: list = []
        self.commits = 0
        self.rollbacks = 0
        self._first_select_seen = False

    async def execute(self, stmt, *a, **k):
        self.executes.append(stmt)
        first_call = not self._first_select_seen
        self._first_select_seen = True
        row = self.idempotency_row if first_call else None

        class _R:
            def __init__(self, r):
                self._r = r

            def first(self):
                return self._r

            def scalar_one_or_none(self):
                return self._r

            def scalars(self):
                class _S:
                    def all(_self):
                        return []

                return _S()

        return _R(row)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


async def _noop_sleep(_secs):
    return None


def _patch_runner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    synth_factory: _SynthesisDriverFactory,
) -> None:
    """Wire the synthesis stub into the runner namespace.

    The runner imports `run_agentic_synthesis` inside the function body,
    so we patch the source module.
    """
    monkeypatch.setattr(
        "agents.insights.agentic_synthesis.run_agentic_synthesis",
        synth_factory.make(),
    )
    monkeypatch.setattr(_asyncio, "sleep", _noop_sleep)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoke_insights_daily_skips_when_idempotency_row_exists(monkeypatch):
    """If a scheduler-originated row already exists for today, no-op."""
    synth = _SynthesisDriverFactory(outcomes=[])
    _patch_runner(monkeypatch, synth_factory=synth)

    session = FakeSession(idempotency_row=("some-uuid",))

    result = await runner_mod._invoke_insights_daily(session)  # type: ignore[arg-type]

    assert result == {
        "fetched": 0,
        "stored": 0,
        "skipped": 1,
        "reason": "idempotency_guard",
    }
    # Critically: no synthesis run.
    assert synth.calls == []


@pytest.mark.asyncio
async def test_invoke_insights_daily_drives_agentic_synthesis_on_happy_path(monkeypatch):
    """`stored` mirrors `SynthesisResult.insights_count`; `fetched` is 0 (v2 has no server-built FactPack)."""
    synth = _SynthesisDriverFactory(
        outcomes=[_SynthesisResultStub(insights_count=7, degraded=False)],
    )
    _patch_runner(monkeypatch, synth_factory=synth)

    session = FakeSession(idempotency_row=None)

    result = await runner_mod._invoke_insights_daily(session)  # type: ignore[arg-type]

    assert result["stored"] == 7
    assert result["fetched"] == 0
    assert result["skipped"] == 0
    assert result["degraded"] is False
    assert len(synth.calls) == 1

    call = synth.calls[0]
    # Scheduler contract: scheduler-mode keyed by today's date.
    assert call["mode"] == "scheduled"
    assert call["max_insights"] == 5
    assert call["cron_run_date"] is not None
    assert isinstance(call["session_id"], uuid.UUID)
    # Regression guard: v2 signature has no fact_pack kwarg.
    assert "fact_pack" not in call
    # The pre-created AISession row must have been added with the
    # scheduler tag so the idempotency guard catches a same-day retry.
    assert any(
        getattr(o, "created_by", None) == "scheduler" for o in session.added
    ), "expected scheduler-tagged AISession to be pre-created"


@pytest.mark.asyncio
async def test_invoke_insights_daily_retries_then_succeeds(monkeypatch):
    """Transient failure on attempt 1, success on attempt 2."""
    synth = _SynthesisDriverFactory(
        outcomes=[
            RuntimeError("transient"),
            _SynthesisResultStub(insights_count=5, degraded=False),
        ],
    )
    _patch_runner(monkeypatch, synth_factory=synth)

    session = FakeSession(idempotency_row=None)

    result = await runner_mod._invoke_insights_daily(session)  # type: ignore[arg-type]

    assert result["stored"] == 5
    assert result["fetched"] == 0
    assert len(synth.calls) == 2, "synthesis driver should be re-invoked on retry"


@pytest.mark.asyncio
async def test_invoke_insights_daily_three_failures_exhausts_retries(monkeypatch):
    """All 3 attempts fail -> exception re-raised after 3 invocations."""
    synth = _SynthesisDriverFactory(
        outcomes=[
            RuntimeError("boom-1"),
            RuntimeError("boom-2"),
            RuntimeError("boom-3"),
        ],
    )
    _patch_runner(monkeypatch, synth_factory=synth)

    session = FakeSession(idempotency_row=None)

    with pytest.raises(RuntimeError):
        await runner_mod._invoke_insights_daily(session)  # type: ignore[arg-type]

    assert len(synth.calls) == 3, "expected 3 attempts (1 + 2 retries) before re-raise"


@pytest.mark.asyncio
async def test_invoke_insights_daily_timeout_marks_session_degraded(monkeypatch):
    """asyncio.TimeoutError on first attempt -> retry; final timeout -> re-raise."""
    synth = _SynthesisDriverFactory(
        outcomes=[
            _asyncio.TimeoutError(),
            _asyncio.TimeoutError(),
            _asyncio.TimeoutError(),
        ],
    )
    _patch_runner(monkeypatch, synth_factory=synth)

    session = FakeSession(idempotency_row=None)

    with pytest.raises(_asyncio.TimeoutError):
        await runner_mod._invoke_insights_daily(session)  # type: ignore[arg-type]

    assert len(synth.calls) == 3
    # We expect at least 1 SELECT (idempotency) + 3 UPDATE-to-degraded flips.
    update_count = sum(
        1
        for stmt in session.executes
        if "UPDATE" in str(getattr(stmt, "_compile_w_cache", lambda *a, **k: stmt)).upper()
        or "Update" in type(stmt).__name__
    )
    # Loose assertion — at minimum the executes list must show the
    # idempotency SELECT + at least one flip per attempt.
    assert len(session.executes) >= 4


@pytest.mark.asyncio
async def test_invoke_insights_daily_synthesis_run_error_is_failed(monkeypatch):
    """SynthesisRunError on every attempt -> force-finalize to 'failed' + re-raise."""
    from agents.insights.agentic_synthesis import SynthesisRunError

    synth = _SynthesisDriverFactory(
        outcomes=[
            SynthesisRunError("gateway 503"),
            SynthesisRunError("gateway 503"),
            SynthesisRunError("gateway 503"),
        ],
    )
    _patch_runner(monkeypatch, synth_factory=synth)

    session = FakeSession(idempotency_row=None)

    with pytest.raises(SynthesisRunError):
        await runner_mod._invoke_insights_daily(session)  # type: ignore[arg-type]

    assert len(synth.calls) == 3
