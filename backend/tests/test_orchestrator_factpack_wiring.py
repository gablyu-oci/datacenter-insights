"""Integration-flavored test for the rewired
`_phase_verify_and_synthesize_iter` path.

Strategy: monkeypatch the orchestrator's bootstrap + hypothesize phase
methods so they:
  - skip the 8-endpoint survey (bootstrap)
  - seed `_fact_pack` and `_hypothesizer_insights` with stubs (hypothesize)
That isolates the new mega-call branch and lets us assert that:
  - 7 InsightCompleteEvents are emitted, each with a REAL stub headline
    (no "Candidate insight #N" canned text).
  - Per insight the SSE flow emits InsightStartedEvent +
    ReasoningStepEvent(verify) + ReasoningStepEvent(emit) +
    InsightCompleteEvent in that order, with monotonically increasing seq.
  - The literal substring "Candidate insight #" appears nowhere in the
    serialized event stream.

We pass `db=None` so all the persistence helpers are no-ops, but we
still bypass the `if self.db is None` short-circuit because the
hypothesize phase is replaced.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import pytest

from agents.insights import orchestrator as orch_mod
from agents.insights.hypothesizer import (
    FactPack,
    FactRow,
    FactSection,
    InsightOutput,
)
from agents.insights.orchestrator import InsightOrchestrator
from agents.insights.specs.sse_events import (
    InsightCompleteEvent,
    InsightStartedEvent,
    ReasoningStepEvent,
    SessionCompleteEvent,
    SessionStartedEvent,
    _SSEBase,
)


# ---------------------------------------------------------------------------
# Stub fact pack + insights
# ---------------------------------------------------------------------------


_STUB_HEADLINES: list[str] = [
    "Microsoft signed 800 MW PPA with Constellation",
    "Loudoun County issued 4 datacenter permits in 24h",
    "PJM queue MW spiked 8 sigma above trailing 12-week mean",
    "Meta Q3 10-Q discloses 1.2 GW Texas buildout",
    "EPA ECHO logged 3 new air permits in TX > 100 MW",
    "EDGAR coverage in California still partial after 48h",
    "Top developer Vantage added 600 MW week-over-week",
]

_STUB_SECTION_NAMES: list[str] = [
    "top_capacity_movers_24h",
    "new_permits_24h",
    "anomalies_today",
]


def _build_stub_fact_pack() -> FactPack:
    """3 sections x 1 row each => total_rows() == 3."""
    sections = []
    for name in _STUB_SECTION_NAMES:
        sections.append(
            FactSection(
                name=name,
                description=f"stub for {name}",
                rows=[FactRow(row_id=f"{name}:0", entity="StubCo", value=42)],
            )
        )
    return FactPack(
        generated_at=datetime.now(timezone.utc),
        sections=sections,
    )


def _build_stub_insights() -> list[InsightOutput]:
    """7 insights, each referencing a real row_id from the stub FactPack."""
    out: list[InsightOutput] = []
    for i, headline in enumerate(_STUB_HEADLINES):
        # Round-robin assign to one of the 3 stub sections.
        section = _STUB_SECTION_NAMES[i % len(_STUB_SECTION_NAMES)]
        out.append(
            InsightOutput(
                headline=headline,
                body=f"Body for {headline}",
                confidence_signal="strong",
                materiality="high",
                supporting_row_ids=[f"{section}:0"],
            )
        )
    return out


# ---------------------------------------------------------------------------
# Orchestrator harness
# ---------------------------------------------------------------------------


async def _empty_bootstrap_iter(self) -> AsyncIterator[_SSEBase]:
    """Replacement bootstrap: yields no events. Keeps the test focused."""
    if False:
        yield  # pragma: no cover -- this is a generator with no yields


def _make_seed_hypothesize_iter(stub_pack: FactPack, stub_ins: list[InsightOutput]):
    """Returns an async-generator method that seeds the hypothesize state
    and emits exactly the same single `reasoning_step="hypothesize"` event
    the real method emits.
    """
    from agents.insights.specs.sse_events import (
        ReasoningStepData,
        ReasoningStepEvent as _RSE,
    )

    async def _phase_hypothesize_iter(self) -> AsyncIterator[_SSEBase]:
        yield self._build_event(
            _RSE,
            ReasoningStepData(insight_id="session", step="hypothesize"),
        )
        self._fact_pack = stub_pack
        self._hypothesizer_insights = list(stub_ins)

    return _phase_hypothesize_iter


@pytest.fixture
def orch(monkeypatch):
    """Build an orchestrator with bootstrap stubbed out and the
    hypothesize phase replaced to seed _fact_pack + _hypothesizer_insights.
    """
    # Force is_duplicate to always return False so we don't embed.
    async def _no_dup(*args, **kwargs):
        return False

    monkeypatch.setattr(orch_mod, "is_duplicate", _no_dup)

    # max_insights is clamped to [V1_MIN_INSIGHTS=5, V1_MAX_INSIGHTS=10].
    # We want 7 InsightCompletes -> set to 7 (within the clamp range).
    o = InsightOrchestrator(
        session_id=uuid.uuid4(),
        db=None,
        llm=None,
        max_insights=7,
    )
    assert o.max_insights == 7

    pack = _build_stub_fact_pack()
    insights = _build_stub_insights()
    seed_iter = _make_seed_hypothesize_iter(pack, insights)

    # Bind the replacement methods to the instance.
    monkeypatch.setattr(o, "_phase_bootstrap_iter",
                        _empty_bootstrap_iter.__get__(o, InsightOrchestrator))
    monkeypatch.setattr(o, "_phase_hypothesize_iter",
                        seed_iter.__get__(o, InsightOrchestrator))

    return o


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_emits_seven_insight_complete_events_with_real_headlines(orch):
    events: list[_SSEBase] = []
    async for ev in orch.run_session():
        events.append(ev)

    completes = [e for e in events if isinstance(e, InsightCompleteEvent)]
    assert len(completes) == 7, f"expected 7 InsightCompleteEvents, got {len(completes)}"
    for ev in completes:
        assert "Candidate insight" not in ev.data.headline, (
            f"canned headline leaked into output: {ev.data.headline!r}"
        )

    # Every emitted headline is one of the stub headlines.
    emitted_headlines = {ev.data.headline for ev in completes}
    assert emitted_headlines == set(_STUB_HEADLINES)


@pytest.mark.asyncio
async def test_orchestrator_supporting_rows_resolved_from_factpack(orch):
    """For each emitted insight: SSE flow is
    InsightStartedEvent -> ReasoningStepEvent(verify) ->
    ReasoningStepEvent(emit) -> InsightCompleteEvent, with strictly
    increasing seq numbers.
    """
    events: list[_SSEBase] = []
    async for ev in orch.run_session():
        events.append(ev)

    # Every event has a strictly increasing seq (build_event increments).
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs)), "seq numbers must be unique"

    # Group events by insight_id (skip events with no insight_id like
    # session_started / surveying / session_complete / the session-level
    # reasoning_step where insight_id="session").
    started: list[InsightStartedEvent] = [
        e for e in events if isinstance(e, InsightStartedEvent)
    ]
    completes: list[InsightCompleteEvent] = [
        e for e in events if isinstance(e, InsightCompleteEvent)
    ]
    assert len(started) == 7
    assert len(completes) == 7

    # Build a per-insight sequence list and verify ordering.
    for s_ev, c_ev in zip(started, completes):
        iid = s_ev.data.insight_id
        # Same insight_id propagates through to the InsightCompleteEvent.
        assert c_ev.data.insight_id == iid

        # Pick out the reasoning_step events for this insight, in order.
        steps = [
            e for e in events
            if isinstance(e, ReasoningStepEvent) and e.data.insight_id == iid
        ]
        # Per-insight: exactly two reasoning steps -- verify, then emit.
        step_names = [e.data.step for e in steps]
        assert step_names == ["verify", "emit"], (
            f"insight {iid}: expected [verify, emit], got {step_names}"
        )

        # Order check: started.seq < verify.seq < emit.seq < complete.seq
        assert s_ev.seq < steps[0].seq < steps[1].seq < c_ev.seq

        # Headline propagated.
        assert c_ev.data.headline in _STUB_HEADLINES


@pytest.mark.asyncio
async def test_orchestrator_no_canned_insight_string_anywhere(orch):
    events: list[_SSEBase] = []
    async for ev in orch.run_session():
        events.append(ev)

    blob = "\n".join(e.model_dump_json() for e in events)
    assert "Candidate insight #" not in blob
    # Must have actually run -- session_started + session_complete present.
    assert any(isinstance(e, SessionStartedEvent) for e in events)
    assert any(isinstance(e, SessionCompleteEvent) for e in events)
