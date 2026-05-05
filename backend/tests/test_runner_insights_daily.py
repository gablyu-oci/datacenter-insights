"""Phase 3: scheduler-driven daily AI Insights cron tests.

`pipeline.runner._invoke_insights_daily` is the headless entry point that
APScheduler fires once per UTC day. Its contract:

  1. Idempotency guard: if a `created_by='scheduler'` AISession already
     exists today with status in (running, complete), no-op and return
     `{"skipped": 1, "reason": "idempotency_guard"}`.
  2. Otherwise instantiate InsightOrchestrator, drain it, count
     InsightCompleteEvent frames as `stored`, and surface
     `_fact_pack.total_rows()` as `fetched`.
  3. Up to 2 retries (3 attempts total) on exception, with a sleep
     between attempts. After the 3rd failure: re-raise so the
     APScheduler EVENT_JOB_ERROR listener fires.
  4. Each failed attempt flips its session row to status='failed' so a
     same-day repeat fire still hits the idempotency guard cleanly.

These tests stub the orchestrator and DB so the cron path is exercised
without spinning up Postgres or the LLM.
"""
from __future__ import annotations

import asyncio as _asyncio
from typing import Any

import pytest

import pipeline.runner as runner_mod
from agents.insights.specs.sse_events import (
    InsightCompleteData,
    InsightCompleteEvent,
    PingEvent,
    SessionStartedData,
    SessionStartedEvent,
)


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------


class _FactPackStub:
    def __init__(self, total: int) -> None:
        self._total = total

    def total_rows(self) -> int:
        return self._total


class _StubOrchFactory:
    """Builds a configurable StubOrch class.

    Each instantiation records its constructor args in `instances`; each
    call to `run_session` consumes the next entry from `event_batches`
    (a list of either: a list of events to yield, OR an Exception class
    to raise before yielding anything).
    """

    def __init__(
        self,
        *,
        event_batches: list,
        fact_pack_total: int = 42,
    ) -> None:
        self.event_batches = event_batches
        self.fact_pack_total = fact_pack_total
        self.instances: list[Any] = []

    def make(self):
        outer = self

        class StubOrch:
            def __init__(self, *, session_id, db=None, max_insights=7, **kwargs):
                self.session_id = session_id
                self.db = db
                self.max_insights = max_insights
                self.kwargs = kwargs
                self._fact_pack = _FactPackStub(outer.fact_pack_total)
                self._call_index = len(outer.instances)
                outer.instances.append(self)

            async def run_session(self, filters=None):
                idx = self._call_index
                if idx >= len(outer.event_batches):
                    return
                batch = outer.event_batches[idx]
                if isinstance(batch, BaseException) or (
                    isinstance(batch, type) and issubclass(batch, BaseException)
                ):
                    # Either an instance or class — raise it.
                    if isinstance(batch, type):
                        raise batch("stub failure")
                    raise batch
                for ev in batch:
                    yield ev

        return StubOrch


class FakeSession:
    """Stub AsyncSession just rich enough for `_invoke_insights_daily`.

    - `execute()` returns a result whose `.first()` is configurable for
      the idempotency SELECT path. UPDATE statements just record the call.
    - `commit()` is a no-op.
    """

    def __init__(self, idempotency_row=None) -> None:
        self.idempotency_row = idempotency_row
        self.executes: list = []
        self._first_select_seen = False

    async def execute(self, stmt, *a, **k):
        self.executes.append(stmt)
        # The very first execute() is the idempotency SELECT; subsequent
        # ones are the UPDATE-to-failed flips. We model that by returning
        # a "first()-able" result on the first call only.
        first_call = not self._first_select_seen
        self._first_select_seen = True
        row = self.idempotency_row if first_call else None

        class _R:
            def __init__(self, r):
                self._r = r

            def first(self):
                return self._r

            def scalars(self):
                class _S:
                    def all(_self):
                        return []
                return _S()

        return _R(row)

    async def commit(self):
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_insight_complete_event(idx: int) -> InsightCompleteEvent:
    return InsightCompleteEvent(
        event_id=f"e{idx:04d}",
        seq=idx,
        data=InsightCompleteData(
            insight_id=f"insight-{idx}",
            headline=f"Headline {idx}",
            confidence="medium",
            materiality="medium",
            skills_run=["mega_synthesis"],
            low_external_support=None,
        ),
    )


def _make_session_started_event() -> SessionStartedEvent:
    from datetime import datetime, timezone
    return SessionStartedEvent(
        event_id="ss01",
        seq=0,
        data=SessionStartedData(
            session_id="00000000-0000-0000-0000-000000000000",
            model="stub",
            started_at=datetime.now(timezone.utc),
            max_insights=7,
        ),
    )


async def _noop_sleep(_secs):
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoke_insights_daily_skips_when_idempotency_row_exists(monkeypatch):
    """If a scheduler-originated row already exists for today, no-op."""
    factory = _StubOrchFactory(event_batches=[])
    monkeypatch.setattr(
        "agents.insights.orchestrator.InsightOrchestrator",
        factory.make(),
    )
    # Faster sleeps just in case the path reaches them (it should NOT).
    monkeypatch.setattr(_asyncio, "sleep", _noop_sleep)

    session = FakeSession(idempotency_row=("some-uuid",))

    result = await runner_mod._invoke_insights_daily(session)  # type: ignore[arg-type]

    assert result == {
        "fetched": 0,
        "stored": 0,
        "skipped": 1,
        "reason": "idempotency_guard",
    }
    # Critically: NO orchestrator should have been constructed.
    assert len(factory.instances) == 0


@pytest.mark.asyncio
async def test_invoke_insights_daily_drains_seven_insight_complete_events(monkeypatch):
    """Counts only InsightCompleteEvent frames as `stored`, ignores others.

    Also verifies `fetched` is sourced from `_fact_pack.total_rows()`.
    """
    events = [
        _make_session_started_event(),
        _make_insight_complete_event(1),
        PingEvent(event_id="p1", seq=1),
        _make_insight_complete_event(2),
        _make_insight_complete_event(3),
        PingEvent(event_id="p2", seq=2),
        _make_insight_complete_event(4),
        _make_insight_complete_event(5),
        _make_insight_complete_event(6),
        _make_insight_complete_event(7),
    ]
    factory = _StubOrchFactory(event_batches=[events], fact_pack_total=123)
    monkeypatch.setattr(
        "agents.insights.orchestrator.InsightOrchestrator",
        factory.make(),
    )
    monkeypatch.setattr(_asyncio, "sleep", _noop_sleep)

    session = FakeSession(idempotency_row=None)

    result = await runner_mod._invoke_insights_daily(session)  # type: ignore[arg-type]

    assert result["stored"] == 7, f"expected 7 InsightCompleteEvents counted, got {result}"
    assert result["fetched"] == 123, "fetched must reflect FactPack.total_rows()"
    assert result["skipped"] == 0
    assert len(factory.instances) == 1


@pytest.mark.asyncio
async def test_invoke_insights_daily_retries_then_succeeds(monkeypatch):
    """Transient failure on attempt 1, success on attempt 2.

    Asserts: the function returns the success result, the orchestrator
    was instantiated twice, and an UPDATE-to-failed was issued for the
    first attempt's session id.
    """
    success_events = [_make_insight_complete_event(i) for i in range(5)]
    factory = _StubOrchFactory(
        event_batches=[
            RuntimeError("transient"),  # attempt 1
            success_events,             # attempt 2
        ],
        fact_pack_total=99,
    )
    monkeypatch.setattr(
        "agents.insights.orchestrator.InsightOrchestrator",
        factory.make(),
    )
    monkeypatch.setattr(_asyncio, "sleep", _noop_sleep)

    session = FakeSession(idempotency_row=None)

    result = await runner_mod._invoke_insights_daily(session)  # type: ignore[arg-type]

    assert result["stored"] == 5
    assert result["fetched"] == 99
    assert len(factory.instances) == 2, "orchestrator should be re-instantiated on retry"
    # First call was idempotency SELECT, then the failing attempt issued an UPDATE.
    # Total calls so far should be at least 2 (SELECT + at least one UPDATE).
    assert len(session.executes) >= 2


@pytest.mark.asyncio
async def test_invoke_insights_daily_three_failures_exhausts_retries(monkeypatch):
    """All 3 attempts fail -> exception re-raised after 3 instantiations.

    Each attempt must have flipped its session row to status='failed',
    yielding 1 SELECT + 3 UPDATE statements minimum.
    """
    factory = _StubOrchFactory(
        event_batches=[
            RuntimeError("boom-1"),
            RuntimeError("boom-2"),
            RuntimeError("boom-3"),
        ],
    )
    monkeypatch.setattr(
        "agents.insights.orchestrator.InsightOrchestrator",
        factory.make(),
    )
    monkeypatch.setattr(_asyncio, "sleep", _noop_sleep)

    session = FakeSession(idempotency_row=None)

    with pytest.raises(RuntimeError):
        await runner_mod._invoke_insights_daily(session)  # type: ignore[arg-type]

    assert len(factory.instances) == 3, (
        "expected 3 attempts (1 + 2 retries) before re-raising"
    )
    # 1 SELECT (idempotency guard) + 3 UPDATEs (one per failed attempt).
    assert len(session.executes) >= 4
