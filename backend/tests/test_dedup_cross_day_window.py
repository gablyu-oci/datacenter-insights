"""Phase 2 D8: cross-day dedup window tests.

`fetch_recent_embeddings` primes the orchestrator's `_emitted_headlines`
list with the last 14 days of successful AIInsight rows. These tests
lock down its contract WITHOUT touching a real DB:

  * 14-day cutoff is computed correctly.
  * Custom `days` value flows through to the SQL parameters.
  * `days=0` short-circuits and returns [] before hitting the DB.
  * `db is None` short-circuits and returns [] before hitting the DB.
  * Malformed `embedding_text` rows are silently skipped, not raised.
  * Exceptions raised by `db.execute()` are swallowed (returns []).

Plus direct tests for `_parse_embedding_text` (the helper that has to
tolerate both pgvector text-mode and bare Python lists).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from agents.insights.dedup import (
    CROSS_DAY_LOOKBACK_DAYS,
    _parse_embedding_text,
    fetch_recent_embeddings,
)


# ---------------------------------------------------------------------------
# Stub plumbing
# ---------------------------------------------------------------------------


class _FakeMappings:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def all(self) -> list[dict]:
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._rows)


class FakeDB:
    """Captures (stmt, params) on execute() and returns canned rows."""

    def __init__(self, rows: list[dict] | None = None, raise_on_execute: bool = False) -> None:
        self.rows = rows or []
        self.raise_on_execute = raise_on_execute
        self.last_params: dict | None = None
        self.execute_calls = 0

    async def execute(self, stmt, params=None):  # type: ignore[no-untyped-def]
        self.execute_calls += 1
        self.last_params = params
        if self.raise_on_execute:
            raise RuntimeError("simulated DB failure")
        return _FakeResult(self.rows)


# ---------------------------------------------------------------------------
# fetch_recent_embeddings — window + parameters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_recent_embeddings_uses_14_day_default_cutoff():
    """The default cutoff must equal `now - 14 days` within a few seconds."""
    db = FakeDB(rows=[])
    before = datetime.now(timezone.utc)
    out = await fetch_recent_embeddings(db)  # type: ignore[arg-type]
    after = datetime.now(timezone.utc)

    assert out == []
    assert db.last_params is not None
    cutoff = db.last_params["cutoff"]
    expected_lo = before - timedelta(days=CROSS_DAY_LOOKBACK_DAYS) - timedelta(seconds=2)
    expected_hi = after - timedelta(days=CROSS_DAY_LOOKBACK_DAYS) + timedelta(seconds=2)
    assert expected_lo <= cutoff <= expected_hi


@pytest.mark.asyncio
async def test_fetch_recent_embeddings_respects_custom_days():
    """`days=7` must produce a 7-day cutoff, not 14."""
    db = FakeDB(rows=[])
    before = datetime.now(timezone.utc)
    out = await fetch_recent_embeddings(db, days=7)  # type: ignore[arg-type]
    after = datetime.now(timezone.utc)

    assert out == []
    cutoff = db.last_params["cutoff"]  # type: ignore[index]
    expected_lo = before - timedelta(days=7) - timedelta(seconds=2)
    expected_hi = after - timedelta(days=7) + timedelta(seconds=2)
    assert expected_lo <= cutoff <= expected_hi


@pytest.mark.asyncio
async def test_fetch_recent_embeddings_zero_days_short_circuits():
    """`days=0` must return [] immediately without hitting the DB."""
    db = FakeDB(rows=[{"id": uuid.uuid4(), "headline": "h", "embedding_text": "[1,2,3]"}])
    out = await fetch_recent_embeddings(db, days=0)  # type: ignore[arg-type]
    assert out == []
    assert db.execute_calls == 0


@pytest.mark.asyncio
async def test_fetch_recent_embeddings_none_db_short_circuits():
    """db=None must return [] without raising."""
    out = await fetch_recent_embeddings(None)  # type: ignore[arg-type]
    assert out == []


@pytest.mark.asyncio
async def test_fetch_recent_embeddings_swallows_execute_exception():
    """A DB error during execute() must NOT propagate; return []."""
    db = FakeDB(raise_on_execute=True)
    out = await fetch_recent_embeddings(db)  # type: ignore[arg-type]
    assert out == []


# ---------------------------------------------------------------------------
# fetch_recent_embeddings — row shape handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_recent_embeddings_parses_well_formed_row():
    row_id = uuid.uuid4()
    rows = [
        {"id": row_id, "headline": "alpha", "embedding_text": "[1.0,2.0,3.0]"},
    ]
    db = FakeDB(rows=rows)
    out = await fetch_recent_embeddings(db)  # type: ignore[arg-type]

    assert len(out) == 1
    rid, headline, vec = out[0]
    assert rid == row_id
    assert headline == "alpha"
    assert vec == [1.0, 2.0, 3.0]


@pytest.mark.asyncio
async def test_fetch_recent_embeddings_skips_null_embedding_row():
    rows = [
        {"id": uuid.uuid4(), "headline": "skip me", "embedding_text": None},
        {"id": uuid.uuid4(), "headline": "keep me", "embedding_text": "[0.5,0.5]"},
    ]
    db = FakeDB(rows=rows)
    out = await fetch_recent_embeddings(db)  # type: ignore[arg-type]

    assert len(out) == 1
    assert out[0][1] == "keep me"
    assert out[0][2] == [0.5, 0.5]


@pytest.mark.asyncio
async def test_fetch_recent_embeddings_skips_garbage_embedding_row():
    rows = [
        {"id": uuid.uuid4(), "headline": "junk", "embedding_text": "garbage"},
        {"id": uuid.uuid4(), "headline": "keep me", "embedding_text": "[1.0]"},
    ]
    db = FakeDB(rows=rows)
    out = await fetch_recent_embeddings(db)  # type: ignore[arg-type]

    assert len(out) == 1
    assert out[0][1] == "keep me"


# ---------------------------------------------------------------------------
# _parse_embedding_text helper
# ---------------------------------------------------------------------------


def test_parse_embedding_text_python_list():
    assert _parse_embedding_text([1, 2, 3]) == [1.0, 2.0, 3.0]


def test_parse_embedding_text_bracketed_string():
    assert _parse_embedding_text("[1.0, 2.0, 3.0]") == [1.0, 2.0, 3.0]


def test_parse_embedding_text_empty_string():
    assert _parse_embedding_text("") == []


def test_parse_embedding_text_none():
    assert _parse_embedding_text(None) == []


def test_parse_embedding_text_garbage():
    assert _parse_embedding_text("not a vector") == []


def test_parse_embedding_text_list_with_non_numeric():
    # A list that contains a non-numeric entry must fail closed (no partial
    # vectors leak through and corrupt the cosine math downstream).
    assert _parse_embedding_text([1.5, "bad"]) == []
