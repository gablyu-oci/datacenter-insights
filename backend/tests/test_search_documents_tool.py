"""Unit tests for ``agents.insights.tools.search_documents``.

Phase B.1 of AI Insights v2. The DB is mocked; recall measurements
against real data are in ``test_search_documents_recall.py``.

Cases:
  * Empty query is rejected up front.
  * Invalid source is rejected.
  * Invalid k is rejected.
  * k > MAX_K clamps with truncated=True.
  * source='edgar' returns shaped citation block (filing_type/url).
  * source='permits' returns shaped citation block.
  * source='all' merges and re-ranks.
  * Latency stays under 500 ms on a mock-only call.
"""
from __future__ import annotations

import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest import mock

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from agents.insights.tools.search_documents import (  # noqa: E402
    DEFAULT_K,
    MAX_K,
    search_documents,
)


# ---------------------------------------------------------------------------
# DB mock helpers
# ---------------------------------------------------------------------------


class _StubResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return [_StubMapping(r) for r in self._rows]


class _StubMapping(dict):
    """dict subclass so SQLAlchemy callers expecting a Row mapping work."""


def _make_engine_with_branches(edgar_rows=None, permit_rows=None):
    """Return a fake engine whose ``connect()`` routes responses by
    inspecting the issued SQL — `edgar_passages` queries get edgar_rows,
    `permit_passages` queries get permit_rows. This is order- and
    source-independent so source='edgar', 'permits', or 'all' all work.
    """
    edgar_rows = edgar_rows or []
    permit_rows = permit_rows or []

    class _StubConn:
        async def execute(self, statement, *args, **kwargs):
            sql_text = str(getattr(statement, "text", statement)).lower()
            if "permit_passages" in sql_text:
                return _StubResult(permit_rows)
            if "edgar_passages" in sql_text:
                return _StubResult(edgar_rows)
            return _StubResult([])

    @asynccontextmanager
    async def _connect():
        yield _StubConn()

    eng = mock.MagicMock()
    eng.connect = _connect
    return eng


def _patch_engine(engine):
    return mock.patch(
        "agents.insights.tools.search_documents.get_readonly_engine",
        return_value=engine,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_query_is_rejected():
    out = await search_documents("")
    assert out == {"ok": False, "error": "empty_query"}

    out = await search_documents("   \n\t  ")
    assert out == {"ok": False, "error": "empty_query"}


@pytest.mark.asyncio
async def test_invalid_source_is_rejected():
    out = await search_documents("hello", source="news")  # type: ignore[arg-type]
    assert out["ok"] is False
    assert out["error"] == "invalid_source"
    assert out["detail"]["source"] == "news"


@pytest.mark.asyncio
async def test_invalid_k_is_rejected():
    out = await search_documents("hello", k=0)
    assert out["ok"] is False
    assert out["error"] == "invalid_k"


@pytest.mark.asyncio
async def test_k_above_cap_is_clamped_with_truncated_flag():
    edgar = [
        {
            "passage_id": str(i),
            "passage_text": f"chunk-{i}",
            "score": 1.0 / (i + 1),
            "cik": "0001",
            "form_type": "8-K",
            "url": "https://sec.gov/x",
            "retrieved_at": datetime.now(timezone.utc),
            "company": "Test Co",
        }
        for i in range(3)
    ]
    eng = _make_engine_with_branches(edgar_rows=edgar)
    with _patch_engine(eng):
        out = await search_documents("foo", source="edgar", k=999)
    assert out["ok"] is True
    assert out["truncated"] is True
    assert len(out["passages"]) == 3  # only 3 mock rows; capped at MAX_K=50
    assert out["diagnostics"]["k_requested"] == 999


@pytest.mark.asyncio
async def test_edgar_source_shapes_citation_block():
    eng = _make_engine_with_branches(
        edgar_rows=[
            {
                "passage_id": "p-edgar-1",
                "passage_text": "Crusoe Wyoming has 720 MW capacity ...",
                "score": 0.42,
                "cik": "0001234567",
                "form_type": "8-K",
                "url": "https://www.sec.gov/Archives/...",
                "retrieved_at": datetime(2026, 5, 7, tzinfo=timezone.utc),
                "company": "Crusoe Energy",
            }
        ]
    )
    with _patch_engine(eng):
        out = await search_documents("Crusoe Wyoming", source="edgar")
    assert out["ok"] is True
    assert len(out["passages"]) == 1
    p = out["passages"][0]
    assert p["text"].startswith("Crusoe Wyoming")
    assert p["score"] == pytest.approx(0.42)
    cit = p["citation"]
    assert cit["source"] == "edgar"
    assert cit["company"] == "Crusoe Energy"
    assert cit["filing_type"] == "8-K"
    assert cit["url"].startswith("https://www.sec.gov/")
    assert cit["passage_id"] == "p-edgar-1"
    assert cit["retrieved_at"] is not None


@pytest.mark.asyncio
async def test_permits_source_shapes_citation_block():
    eng = _make_engine_with_branches(
        permit_rows=[
            {
                "passage_id": "p-perm-1",
                "source_kind": "generator_permit",
                "source_doc_id": "12345",
                "passage_text": "Air permit issued for Crusoe data center diesel ...",
                "score": 0.31,
            }
        ]
    )
    with _patch_engine(eng):
        out = await search_documents("Crusoe permit", source="permits")
    assert out["ok"] is True
    assert len(out["passages"]) == 1
    cit = out["passages"][0]["citation"]
    assert cit["source"] == "permits"
    assert cit["filing_type"] == "generator_permit"
    assert cit["company"] is None
    assert cit["passage_id"] == "p-perm-1"


@pytest.mark.asyncio
async def test_all_source_merges_and_reranks():
    eng = _make_engine_with_branches(
        edgar_rows=[
            {
                "passage_id": "edgar-low",
                "passage_text": "low score",
                "score": 0.1,
                "cik": "0001",
                "form_type": "8-K",
                "url": "https://sec.gov/x",
                "retrieved_at": None,
                "company": None,
            }
        ],
        permit_rows=[
            {
                "passage_id": "perm-high",
                "source_kind": "building_permit",
                "source_doc_id": "abc",
                "passage_text": "high score",
                "score": 0.9,
            }
        ],
    )
    with _patch_engine(eng):
        out = await search_documents("foo", source="all", k=DEFAULT_K)
    assert out["ok"] is True
    # Re-rank by score: permit (0.9) should come first.
    ids = [p["citation"]["passage_id"] for p in out["passages"]]
    assert ids == ["perm-high", "edgar-low"]


@pytest.mark.asyncio
async def test_search_documents_returns_quickly_under_500ms_synthetic():
    eng = _make_engine_with_branches(edgar_rows=[])
    started = time.perf_counter()
    with _patch_engine(eng):
        out = await search_documents("anything", source="edgar")
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert out["ok"] is True
    # On mocks this is well under the 500 ms p95 spec target.
    assert elapsed_ms < 500


@pytest.mark.asyncio
async def test_db_failure_returns_search_failed():
    """If the DB raises, the tool returns a structured error — never raises."""

    class _BoomConn:
        async def execute(self, *args, **kwargs):
            raise RuntimeError("simulated DB failure")

    @asynccontextmanager
    async def _connect():
        yield _BoomConn()

    eng = mock.MagicMock()
    eng.connect = _connect
    with _patch_engine(eng):
        out = await search_documents("hello", source="edgar")
    assert out["ok"] is False
    assert out["error"] == "search_failed"
    assert "simulated DB failure" in out["detail"]["reason"]
