"""Shape tests for ``search_documents(source='earnings')``.

Mirrors the existing ``test_search_documents_tool.py`` mocking pattern:
we never touch a real Postgres. The earnings branch of the tool issues
a ``websearch_to_tsquery`` query against ``earnings_passages`` joined to
``earnings_transcripts``; the assertions here pin the citation envelope
shape so the synthesis prompt downstream can rely on it.

Why we mock the engine (not seed a real DB)
-------------------------------------------
The ``earnings_passages.tsv`` column is a Postgres tsvector populated by
a trigger from migration 019. SQLite has no tsvector / GIN / trigger
equivalent — the search_documents SQL would fail before returning a
single row. The existing tool test
(``test_search_documents_tool.py``) handles this by patching the engine
to return canned rows shaped like the SQL output. We do the same here
for the earnings branch.

Cases:
  * Canonical row from the earnings SQL is shaped into the documented
    citation envelope (source='earnings', filing_type='earnings_call_<Q>',
    company, url, retrieved_at, passage_id, speaker, section).
  * source='all' merges earnings rows with edgar/permits and re-ranks by
    score (smoke; full re-rank logic is covered by the sibling test
    file's all-source case).
  * A null quarter falls back to ``filing_type='earnings_call'``.
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest import mock

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from agents.insights.tools.search_documents import (  # noqa: E402
    search_documents,
)


# ---------------------------------------------------------------------------
# Engine mock — routes the earnings SQL to a canned row set
# ---------------------------------------------------------------------------


class _StubResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return [_StubMapping(r) for r in self._rows]


class _StubMapping(dict):
    """dict subclass — SQLAlchemy callers expecting a Row mapping work."""


def _make_engine_with_branches(
    *, edgar_rows=None, permit_rows=None, earnings_rows=None,
):
    edgar_rows = edgar_rows or []
    permit_rows = permit_rows or []
    earnings_rows = earnings_rows or []

    class _StubConn:
        async def execute(self, statement, *args, **kwargs):
            sql_text = str(getattr(statement, "text", statement)).lower()
            # Order matters: the earnings SQL has BOTH `earnings_passages`
            # and the same `passage_id::text` pattern — match earnings
            # before edgar.
            if "earnings_passages" in sql_text:
                return _StubResult(earnings_rows)
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
async def test_earnings_source_shapes_citation_block():
    """One canonical earnings_passages row -> documented citation shape."""
    eng = _make_engine_with_branches(
        earnings_rows=[
            {
                "passage_id": "p-earn-1",
                "passage_text": (
                    "AI demand continued to accelerate this quarter ..."
                ),
                "speaker": "Satya Nadella",
                "section": "prepared_remarks",
                "score": 0.81,
                "cik": "0000789019",
                "ticker": "MSFT",
                "company": "Microsoft",
                "quarter": "2026Q1",
                "call_date": None,
                "url": (
                    "https://www.alphavantage.co/query"
                    "?function=EARNINGS_CALL_TRANSCRIPT&symbol=MSFT&quarter=2026Q1"
                ),
                "retrieved_at": datetime(2026, 5, 12, tzinfo=timezone.utc),
            }
        ]
    )

    with _patch_engine(eng):
        out = await search_documents("AI demand", source="earnings")

    assert out["ok"] is True
    assert len(out["passages"]) == 1
    p = out["passages"][0]
    assert p["text"].startswith("AI demand")
    assert p["score"] == pytest.approx(0.81)

    cit = p["citation"]
    # All eight documented citation keys must be present.
    assert set(cit.keys()) == {
        "source",
        "company",
        "filing_type",
        "url",
        "retrieved_at",
        "passage_id",
        "speaker",
        "section",
    }
    assert cit["source"] == "earnings"
    assert cit["company"] == "Microsoft"
    assert cit["filing_type"] == "earnings_call_2026Q1"
    assert cit["filing_type"].startswith("earnings_call_")
    assert cit["url"].startswith("https://www.alphavantage.co/query")
    assert cit["passage_id"] == "p-earn-1"
    assert cit["speaker"] == "Satya Nadella"
    assert cit["section"] == "prepared_remarks"
    # retrieved_at must be ISO8601 — Z or +00:00 suffix is fine.
    assert cit["retrieved_at"]
    assert "2026-05-12" in cit["retrieved_at"]
    # Sanity: parses back as ISO.
    datetime.fromisoformat(cit["retrieved_at"].replace("Z", "+00:00"))


@pytest.mark.asyncio
async def test_earnings_null_quarter_falls_back_to_generic_filing_type():
    """A row with no quarter gets ``filing_type='earnings_call'`` (no suffix)."""
    eng = _make_engine_with_branches(
        earnings_rows=[
            {
                "passage_id": "p-earn-noq",
                "passage_text": "Some passage with no quarter.",
                "speaker": None,
                "section": "q_and_a",
                "score": 0.2,
                "cik": "0000000000",
                "ticker": "XYZ",
                "company": "Mystery Co",
                "quarter": None,
                "call_date": None,
                "url": None,
                "retrieved_at": None,
            }
        ]
    )
    with _patch_engine(eng):
        out = await search_documents("foo", source="earnings")
    cit = out["passages"][0]["citation"]
    assert cit["filing_type"] == "earnings_call"
    assert cit["retrieved_at"] is None
    assert cit["url"] is None


@pytest.mark.asyncio
async def test_source_all_merges_earnings_with_other_sources_and_reranks():
    """source='all' fans out across edgar/permits/earnings and re-ranks
    the combined list by score. Smoke test only — full re-rank behaviour
    is covered by the sibling permits/edgar test file."""
    eng = _make_engine_with_branches(
        edgar_rows=[
            {
                "passage_id": "edgar-mid",
                "passage_text": "edgar mid score",
                "score": 0.5,
                "cik": "0001",
                "form_type": "8-K",
                "url": "https://sec.gov/x",
                "retrieved_at": None,
                "company": "Some Co",
            }
        ],
        earnings_rows=[
            {
                "passage_id": "earn-high",
                "passage_text": "earnings high score",
                "speaker": "CEO",
                "section": "prepared_remarks",
                "score": 0.9,
                "cik": "0000789019",
                "ticker": "MSFT",
                "company": "Microsoft",
                "quarter": "2026Q1",
                "call_date": None,
                "url": "https://example",
                "retrieved_at": None,
            }
        ],
        permit_rows=[
            {
                "passage_id": "perm-low",
                "source_kind": "building_permit",
                "source_doc_id": "abc",
                "passage_text": "permit low score",
                "score": 0.1,
            }
        ],
    )
    with _patch_engine(eng):
        out = await search_documents("anything", source="all", k=10)
    assert out["ok"] is True
    ids = [p["citation"]["passage_id"] for p in out["passages"]]
    # 0.9 > 0.5 > 0.1 — earnings on top, permit at the bottom.
    assert ids == ["earn-high", "edgar-mid", "perm-low"]


@pytest.mark.asyncio
async def test_earnings_source_is_allowlisted():
    """Defensive: source='earnings' is one of ALLOWED_SOURCES — the
    tool must not reject it as invalid_source."""
    eng = _make_engine_with_branches(earnings_rows=[])
    with _patch_engine(eng):
        out = await search_documents("hello", source="earnings")
    assert out["ok"] is True
    assert out["row_count"] == 0
    assert out["diagnostics"]["source"] == "earnings"
