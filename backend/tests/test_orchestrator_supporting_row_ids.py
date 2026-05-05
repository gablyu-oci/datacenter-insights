"""Phase 2: orchestrator persistence tests for the new ai_insight columns.

Lock down the migration-013 contract on the persistence boundary:

  * `supporting_row_ids` lands in the dedicated JSONB column, NOT as a
    `_Sources: row_ids=...` footer in body (that Phase 1 stop-gap is gone).
  * `body` stays clean — exactly what the synthesizer produced.
  * `headline_embedding` and `ongoing_of_id` round-trip onto the row when
    the orchestrator chooses to set them (the cross-day "ongoing" pill
    in UX D14 depends on the FK actually being persisted).

These tests use a FakeDB stub — no real Postgres, no migrations — so they
stay fast and run in any environment. The orchestrator's persistence
helper swallows DB exceptions by design (best-effort, never break the
SSE stream); we therefore assert against the captured payload rather
than the result of a network round-trip.
"""
from __future__ import annotations

import uuid

import pytest

from agents.insights.orchestrator import InsightOrchestrator


class FakeDB:
    """Minimal AsyncSession stand-in for `_persist_insight`.

    Captures whatever ORM rows the orchestrator hands to `add()` so the
    test can introspect what fields landed where.
    """

    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def execute(self, *a, **k):
        class _R:
            def first(self_inner):
                return None
        return _R()


def _make_orch() -> tuple[InsightOrchestrator, FakeDB]:
    db = FakeDB()
    orch = InsightOrchestrator(
        session_id=uuid.uuid4(),
        db=db,  # type: ignore[arg-type]
        max_insights=7,
    )
    return orch, db


@pytest.mark.asyncio
async def test_persist_insight_writes_supporting_row_ids_to_jsonb_column():
    """The supporting_row_ids JSONB column gets the list verbatim and the
    body stays clean of the Phase 1 `_Sources: row_ids=...` footer.
    """
    orch, db = _make_orch()

    await orch._persist_insight(
        insight_id=uuid.uuid4(),
        idx=0,
        headline="x",
        body="clean body text",
        confidence="medium",
        materiality="medium",
        skills_run=["mega_synthesis"],
        supporting_row_ids=["a:1", "b:2"],
    )

    assert len(db.added) == 1, "expected exactly one ORM row to be added"
    row = db.added[0]

    # JSONB column populated with the literal list.
    assert getattr(row, "supporting_row_ids", None) == ["a:1", "b:2"]
    # Body unchanged — no Phase 1 footer pollution.
    assert row.body == "clean body text"
    assert "_Sources: row_ids=" not in (row.body or "")


@pytest.mark.asyncio
async def test_persist_insight_supporting_row_ids_none_persists_as_none():
    """None must round-trip as None on the row, NOT coerce to []. A NULL
    column makes the absence of grounding explicit; an empty list would
    falsely imply "we tried but found zero rows".
    """
    orch, db = _make_orch()

    await orch._persist_insight(
        insight_id=uuid.uuid4(),
        idx=0,
        headline="h",
        body="body",
        confidence="low",
        materiality="medium",
        skills_run=["insight_synthesis"],
        supporting_row_ids=None,
    )

    assert len(db.added) == 1
    row = db.added[0]
    assert row.supporting_row_ids is None, (
        "supporting_row_ids must persist as None, not []"
    )


@pytest.mark.asyncio
async def test_persist_insight_writes_embedding_and_ongoing_of_id():
    """When the orchestrator passes a headline_embedding + ongoing_of_id
    those must land on the row. UX D14 (cross-day "ongoing" pill) reads
    the FK; if it does not get written we silently lose the linkage.
    """
    orch, db = _make_orch()

    prior_id = uuid.uuid4()
    await orch._persist_insight(
        insight_id=uuid.uuid4(),
        idx=2,
        headline="continued story",
        body="body",
        confidence="high",
        materiality="high",
        skills_run=["mega_synthesis"],
        supporting_row_ids=["c:3"],
        headline_embedding=[0.1, 0.2, 0.3],
        ongoing_of_id=prior_id,
    )

    assert len(db.added) == 1
    row = db.added[0]
    assert row.headline_embedding == [0.1, 0.2, 0.3]
    assert row.ongoing_of_id == prior_id
    # supporting_row_ids must still land too, for completeness.
    assert row.supporting_row_ids == ["c:3"]
