"""Tests for ``ingestion.earnings_transcripts.EarningsTranscriptsAdapter``.

Two layers:

1. Pure-function unit tests (no DB, no network).
   * ``_normalize_payload`` shapes the row dict the adapter upserts.
   * ``_candidate_quarters`` produces today + lookback in YYYYQN form.
   * ``_check_throttled`` raises on Alpha Vantage's Information/Note
     soft-throttle responses.

2. End-to-end adapter ``run()`` against a live Postgres test DB plus
   mocked httpx.

   The adapter uses ``pg_insert(...).on_conflict_do_update(...)`` which is
   Postgres-only — we cannot exercise the upsert path on SQLite. We
   therefore follow the existing live-DB skip pattern from
   ``test_companies_counterparties.py`` / ``test_migration_017.py``:
   skip cleanly if Postgres / migration 019 isn't reachable so the test
   file remains collectable in CI without a DB.

External dependencies stubbed:
   * ``adapter._rate_limited_get`` (replaces real HTTP) — first call
     returns the calendar CSV, second call returns the transcript JSON.
     Also bypasses ``INTER_CALL_DELAY_SECONDS=12.5`` so the test
     completes in milliseconds.
   * ``agents.earnings_extractor.extract_and_update`` — stub so no real
     LLM/Anthropic call is made. We assert it is invoked once per
     transcript.
   * ``_load_cache`` / ``_save_cache`` are pointed at a tmp dir so we
     don't pollute backend/data/cache.

Required tests
   * adapter.run produces one earnings_transcripts row, >=1
     earnings_passages row, one IngestionRun with status='success', and
     a coverage row.
   * idempotency: a second run skips the already-extracted transcript.
   * quote validation in the LLM extractor branch — a quote that isn't
     a substring of raw_text is dropped and ``logger.warning`` fires.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


# ---------------------------------------------------------------------------
# Layer 1 — pure-function unit tests (no DB, no network)
# ---------------------------------------------------------------------------


def test_normalize_payload_concatenates_turns_and_counts_speakers():
    from ingestion.earnings_transcripts import EarningsTranscriptsAdapter

    payload = {
        "symbol": "MSFT",
        "quarter": "2026Q1",
        "transcript": [
            {
                "speaker": "Satya Nadella",
                "title": "CEO",
                "content": "AI demand accelerated this quarter.",
            },
            {
                "speaker": "Amy Hood",
                "title": "CFO",
                "content": "Capex was thirty billion this quarter.",
            },
        ],
    }
    rec = EarningsTranscriptsAdapter._normalize_payload(
        cik="0000789019",
        ticker="MSFT",
        company_name="Microsoft",
        quarter="2026Q1",
        call_date=date(2026, 4, 25),
        transcript_url="https://example/x",
        payload=payload,
    )
    assert rec["cik"] == "0000789019"
    assert rec["ticker"] == "MSFT"
    assert rec["company_name"] == "Microsoft"
    assert rec["quarter"] == "2026Q1"
    assert rec["fiscal_year"] == 2026
    assert rec["fiscal_quarter"] == 1
    # 2 distinct speakers, both rendered as "Speaker: content".
    assert rec["speaker_count"] == 2
    assert "Satya Nadella: AI demand" in rec["raw_text"]
    assert "Amy Hood: Capex" in rec["raw_text"]
    # Word count is monotonically positive.
    assert rec["word_count"] > 0
    # __turns is smuggled out-of-band for the chunker.
    assert len(rec["__turns"]) == 2


def test_normalize_payload_drops_empty_and_non_dict_turns():
    from ingestion.earnings_transcripts import EarningsTranscriptsAdapter

    rec = EarningsTranscriptsAdapter._normalize_payload(
        cik="0000789019",
        ticker="MSFT",
        company_name="Microsoft",
        quarter="2026Q1",
        call_date=None,
        transcript_url=None,
        payload={
            "transcript": [
                "string-not-a-dict-should-be-skipped",
                {"speaker": "X", "content": "   "},  # empty content
                {"speaker": "Real", "content": "Some real content here."},
            ]
        },
    )
    assert len(rec["__turns"]) == 1
    assert rec["__turns"][0]["speaker"] == "Real"


def test_candidate_quarters_returns_three_distinct_labels_in_yyyyqn():
    from ingestion.earnings_transcripts import _candidate_quarters

    out = _candidate_quarters(date(2026, 5, 12))
    assert len(out) == 3
    assert len(set(out)) == 3  # all distinct
    # Format: YYYYQN where N is 1..4.
    import re

    for q in out:
        assert re.match(r"^\d{4}Q[1-4]$", q), q


def test_check_throttled_raises_on_information_payload():
    from ingestion.earnings_transcripts import EarningsTranscriptsAdapter

    with pytest.raises(RuntimeError, match="alpha_vantage_throttled"):
        EarningsTranscriptsAdapter._check_throttled(
            {"Information": "API limit reached"}
        )
    with pytest.raises(RuntimeError, match="alpha_vantage_throttled"):
        EarningsTranscriptsAdapter._check_throttled({"Note": "5 calls/minute"})


def test_check_throttled_is_a_noop_on_clean_payload():
    from ingestion.earnings_transcripts import EarningsTranscriptsAdapter

    # No exception expected.
    EarningsTranscriptsAdapter._check_throttled(
        {"symbol": "MSFT", "quarter": "2026Q1", "transcript": []}
    )
    EarningsTranscriptsAdapter._check_throttled("not a dict, also fine")


# ---------------------------------------------------------------------------
# Layer 2 — Postgres-backed adapter.run() integration test
# ---------------------------------------------------------------------------


async def _probe_pg_or_skip():
    """Skip the test if Postgres or migration 019 isn't reachable.

    Mirrors ``_probe_db_or_skip`` in test_companies_counterparties.py:
    create a fresh async engine, dispose any pre-existing engine bound
    to an earlier loop, and confirm earnings_transcripts exists.
    """
    try:
        from sqlalchemy import text as sa_text
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from config import settings
        from db import session as db_session_mod
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"backend imports unavailable: {exc!r}")

    try:
        await db_session_mod.engine.dispose()
    except Exception:
        pass

    db_session_mod.engine = create_async_engine(
        settings.database_url, echo=False, pool_pre_ping=True
    )
    db_session_mod.async_session_factory = async_sessionmaker(
        db_session_mod.engine, expire_on_commit=False
    )

    try:
        async with db_session_mod.async_session_factory() as session:
            # Migration 019 must have run.
            await session.execute(
                sa_text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'earnings_transcripts'"
                )
            )
            row = (
                await session.execute(
                    sa_text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_name = 'earnings_transcripts'"
                    )
                )
            ).first()
            if row is None:
                pytest.skip("migration 019 not applied to test DB")
    except Exception as exc:
        pytest.skip(
            "Postgres test DB unreachable or schema missing; "
            f"skipping live earnings_adapter tests ({type(exc).__name__}: {exc})"
        )

    return db_session_mod


# Fixed identifiers so cleanup is easy.
_TEST_CIK = "9999999019"
_TEST_TICKER = "TSTMSFT"
_TEST_QUARTER = "2026Q1"


async def _cleanup(db_session_mod) -> None:
    """Remove any rows from prior runs so the test is repeatable."""
    from sqlalchemy import text as sa_text

    async with db_session_mod.async_session_factory() as s:
        await s.execute(
            sa_text(
                "DELETE FROM earnings_passages WHERE document_id IN ("
                "  SELECT id FROM earnings_transcripts WHERE cik = :c"
                ")"
            ),
            {"c": _TEST_CIK},
        )
        await s.execute(
            sa_text("DELETE FROM earnings_transcripts WHERE cik = :c"),
            {"c": _TEST_CIK},
        )
        await s.execute(
            sa_text(
                "DELETE FROM ingestion_runs WHERE adapter_name = :a "
                "AND config_snapshot::text LIKE '%TSTMSFT%'"
            ),
            {"a": "earnings_transcripts"},
        )
        await s.commit()


def _calendar_csv_for_test() -> str:
    """One in-window report row for our synthetic MSFT-clone ticker."""
    today = date.today()
    return (
        "symbol,name,reportDate,fiscalDateEnding,estimate,currency\n"
        f"{_TEST_TICKER},Microsoft TestClone,"
        f"{today.isoformat()},2026-03-31,2.50,USD\n"
    )


def _transcript_payload() -> dict:
    return {
        "symbol": _TEST_TICKER,
        "quarter": _TEST_QUARTER,
        "transcript": [
            {
                "speaker": "Satya Nadella",
                "title": "CEO",
                "content": (
                    "AI demand accelerated this quarter as our datacenter "
                    "capex expanded to meet hyperscaler workload growth."
                ),
            },
            {
                "speaker": "Amy Hood",
                "title": "CFO",
                "content": (
                    "Capital expenditures landed at roughly twenty-five "
                    "billion dollars this quarter."
                ),
            },
        ],
    }


@pytest.fixture
def _patch_eligible_and_cache(monkeypatch, tmp_path):
    """Inject a synthetic ticker into the eligibility map + redirect
    the disk cache to ``tmp_path`` so we never read/write the real
    backend/data/cache.
    """
    import ingestion.earnings_transcripts as adapter_mod

    # 1) Make our synthetic ticker eligible and CIK-resolvable.
    monkeypatch.setitem(
        adapter_mod.EARNINGS_ELIGIBLE_TICKERS, "Microsoft TestClone", _TEST_TICKER
    )
    # adapter._tracked_filers_by_display reads TRACKED_FILERS — add our row.
    monkeypatch.setitem(
        adapter_mod.TRACKED_FILERS, "Microsoft TestClone", _TEST_CIK
    )

    # 2) Redirect _load_cache / _save_cache to a fresh tmp dir so the
    #    test never sees stale calendar / transcript blobs from a
    #    previous local run, and never pollutes data/cache.
    state: dict[str, dict] = {}

    def _load(key):
        return state.get(key)

    def _save(key, data):
        state[key] = data

    monkeypatch.setattr(adapter_mod, "_load_cache", _load)
    monkeypatch.setattr(adapter_mod, "_save_cache", _save)

    # 3) Provide a fake API key so _require_api_key doesn't crash.
    from config import settings

    monkeypatch.setattr(settings, "alpha_vantage_api_key", "TEST_KEY")

    return state


def _install_http_stub(adapter, *, calendar_csv: str, transcript: dict):
    """Replace adapter._rate_limited_get so neither real HTTP nor the
    12.5-second inter-call sleep occurs. Returns the AsyncMock so the
    caller can assert call counts.
    """
    calls: list[dict] = []

    async def _fake_get(params, *, as_text=False):
        calls.append({"params": dict(params), "as_text": as_text})
        adapter._daily_calls_used += 1
        fn = params.get("function")
        if fn == "EARNINGS_CALENDAR":
            return calendar_csv
        if fn == "EARNINGS_CALL_TRANSCRIPT":
            return transcript
        raise AssertionError(f"unexpected function: {fn}")

    adapter._rate_limited_get = _fake_get  # type: ignore[assignment]
    return calls


@pytest.mark.asyncio
async def test_adapter_run_happy_path_writes_transcript_passages_and_audit(
    _patch_eligible_and_cache, monkeypatch,
):
    """End-to-end: mocked HTTP + stubbed extractor -> one transcript row,
    >=1 passage rows, IngestionRun(status='success'), DataCoverage row.
    """
    db_session_mod = await _probe_pg_or_skip()
    await _cleanup(db_session_mod)

    from sqlalchemy import text as sa_text

    from ingestion.earnings_transcripts import EarningsTranscriptsAdapter

    # Stub the LLM extractor so no real model is invoked. The adapter
    # imports it lazily inside _dispatch_downstream, so we patch the
    # module attribute.
    import agents.earnings_extractor as extractor_mod

    fake_extract = AsyncMock(return_value={"ok": True, "transcript_id": 0})
    monkeypatch.setattr(extractor_mod, "extract_and_update", fake_extract)

    adapter = EarningsTranscriptsAdapter()
    http_calls = _install_http_stub(
        adapter,
        calendar_csv=_calendar_csv_for_test(),
        transcript=_transcript_payload(),
    )

    try:
        async with db_session_mod.async_session_factory() as session:
            summary = await adapter.run(
                session,
                days_back=90,
                ticker_filter=[_TEST_TICKER],
            )
            await session.commit()
    finally:
        await adapter.close()

    assert summary["adapter"] == "earnings_transcripts"
    assert summary["status"] == "success"
    assert summary["records_stored"] == 1, summary
    assert summary["passages_written"] >= 1, summary
    assert summary["extractor_runs"] == 1, summary

    # Extractor was invoked exactly once for the one transcript.
    assert fake_extract.await_count == 1
    # HTTP-stub saw exactly 2 calls: 1 calendar + 1 transcript.
    fns = [c["params"].get("function") for c in http_calls]
    assert fns.count("EARNINGS_CALENDAR") == 1
    assert fns.count("EARNINGS_CALL_TRANSCRIPT") == 1

    # ---- DB-side assertions ----
    async with db_session_mod.async_session_factory() as session:
        transcript_count = (
            await session.execute(
                sa_text(
                    "SELECT COUNT(*) FROM earnings_transcripts "
                    "WHERE cik = :c AND quarter = :q"
                ),
                {"c": _TEST_CIK, "q": _TEST_QUARTER},
            )
        ).scalar_one()
        assert transcript_count == 1

        # ticker/cik match.
        tr = (
            await session.execute(
                sa_text(
                    "SELECT ticker, company_name FROM earnings_transcripts "
                    "WHERE cik = :c"
                ),
                {"c": _TEST_CIK},
            )
        ).mappings().first()
        assert tr["ticker"] == _TEST_TICKER

        # >=1 passage rows for the transcript.
        passage_count = (
            await session.execute(
                sa_text(
                    "SELECT COUNT(*) FROM earnings_passages ep "
                    "JOIN earnings_transcripts et ON et.id = ep.document_id "
                    "WHERE et.cik = :c"
                ),
                {"c": _TEST_CIK},
            )
        ).scalar_one()
        assert passage_count >= 1

        # IngestionRun row with status='success'.
        run = (
            await session.execute(
                sa_text(
                    "SELECT status, records_stored, records_fetched "
                    "FROM ingestion_runs "
                    "WHERE adapter_name = 'earnings_transcripts' "
                    "ORDER BY id DESC LIMIT 1"
                )
            )
        ).mappings().first()
        assert run is not None
        assert run["status"] == "success"
        assert run["records_stored"] == 1

        # DataCoverage row was upserted.
        cov = (
            await session.execute(
                sa_text(
                    "SELECT coverage_status, record_count FROM data_coverage "
                    "WHERE pillar = 'earnings_intelligence' "
                    "AND state_code = 'US' AND source = 'alpha_vantage'"
                )
            )
        ).mappings().first()
        assert cov is not None
        assert cov["coverage_status"] == "live"

    # Cleanup so reruns work.
    await _cleanup(db_session_mod)
    try:
        await db_session_mod.engine.dispose()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_adapter_run_is_idempotent_on_second_invocation(
    _patch_eligible_and_cache, monkeypatch,
):
    """A second run sees ``extracted_at IS NOT NULL`` and skips the
    upsert/chunk/extract pipeline for that (cik, quarter).
    """
    db_session_mod = await _probe_pg_or_skip()
    await _cleanup(db_session_mod)

    from sqlalchemy import text as sa_text

    from ingestion.earnings_transcripts import EarningsTranscriptsAdapter
    import agents.earnings_extractor as extractor_mod

    # The first-run extractor must set extracted_at on the parent so the
    # second run skips. Real extract_and_update normally does this — our
    # stub has to mimic it.
    async def _fake_extract(session, transcript_id):
        await session.execute(
            sa_text(
                "UPDATE earnings_transcripts "
                "SET extracted_at = :now, extractor_version = '1.0.0' "
                "WHERE id = :id"
            ),
            {"now": datetime.utcnow(), "id": transcript_id},
        )
        return {"ok": True, "transcript_id": transcript_id}

    monkeypatch.setattr(extractor_mod, "extract_and_update", _fake_extract)

    # Run 1
    adapter1 = EarningsTranscriptsAdapter()
    _install_http_stub(
        adapter1,
        calendar_csv=_calendar_csv_for_test(),
        transcript=_transcript_payload(),
    )
    try:
        async with db_session_mod.async_session_factory() as session:
            s1 = await adapter1.run(
                session, days_back=90, ticker_filter=[_TEST_TICKER],
            )
            await session.commit()
    finally:
        await adapter1.close()
    assert s1["records_stored"] == 1, s1

    # Run 2 — same inputs, fresh adapter (so _daily_calls_used resets).
    adapter2 = EarningsTranscriptsAdapter()
    http2 = _install_http_stub(
        adapter2,
        calendar_csv=_calendar_csv_for_test(),
        transcript=_transcript_payload(),
    )
    try:
        async with db_session_mod.async_session_factory() as session:
            s2 = await adapter2.run(
                session, days_back=90, ticker_filter=[_TEST_TICKER],
            )
            await session.commit()
    finally:
        await adapter2.close()

    # Second run is a no-op for the stored counter; the (cik, quarter)
    # was already extracted_at-stamped so records_skipped >= 1.
    assert s2["records_stored"] == 0, s2
    assert s2["records_skipped"] >= 1, s2
    # The transcript-fetch HTTP call must NOT have happened on the
    # second run — idempotency check short-circuits before fetch.
    fns2 = [c["params"].get("function") for c in http2]
    assert "EARNINGS_CALL_TRANSCRIPT" not in fns2, fns2

    # Exactly one transcript row still exists.
    async with db_session_mod.async_session_factory() as session:
        n = (
            await session.execute(
                sa_text(
                    "SELECT COUNT(*) FROM earnings_transcripts WHERE cik = :c"
                ),
                {"c": _TEST_CIK},
            )
        ).scalar_one()
        assert n == 1

    await _cleanup(db_session_mod)
    try:
        await db_session_mod.engine.dispose()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Quote-validation defense — pure function path on the extractor
# ---------------------------------------------------------------------------


def test_extractor_quote_validation_drops_hallucinated_quotes(caplog):
    """``_filter_quote_items`` must drop any quote that isn't a verbatim
    substring of raw_text (whitespace-insensitive, case-insensitive) and
    log a ``earnings_extractor.quote_rejected`` warning. This is the
    primary defense against LLM hallucination.
    """
    from agents.earnings_extractor import (
        _filter_quote_items,
        _normalize_for_match,
    )

    raw_text = (
        "Satya Nadella: AI demand accelerated this quarter as our "
        "datacenter capex expanded."
    )
    raw_norm = _normalize_for_match(raw_text)

    items = [
        # Real verbatim substring — must survive.
        {"quote": "AI demand accelerated this quarter"},
        # Hallucinated — never appears in the transcript. Must be
        # dropped + warning logged.
        {"quote": "We will invest $50 billion in quantum computing"},
        # Trivially short (<8 chars) — must be dropped without false
        # positive.
        {"quote": "AI"},
        # Not a dict — must be dropped.
        "not a dict",
    ]

    caplog.set_level(logging.WARNING, logger="agents.earnings_extractor")
    out = _filter_quote_items(
        items, raw_norm, label="capex_mentions", transcript_id=12345,
    )

    # Only the legitimately-grounded quote survives.
    assert len(out) == 1
    assert out[0]["quote"] == "AI demand accelerated this quarter"

    # logger.warning was called at least once with the rejection event
    # and the transcript_id we passed.
    rejected_records = [
        r for r in caplog.records
        if "earnings_extractor.quote_rejected" in r.getMessage()
    ]
    assert len(rejected_records) >= 1, [r.getMessage() for r in caplog.records]
    # transcript_id is attached via the `extra` dict.
    assert any(
        getattr(r, "transcript_id", None) == 12345 for r in rejected_records
    ), "transcript_id missing from at least one quote_rejected log record"


def test_extractor_guidance_rejected_when_raw_quote_is_hallucinated(caplog):
    """guidance.raw_quote that isn't a substring -> whole guidance block
    blanked AND a warning is logged."""
    from agents.earnings_extractor import (
        _normalize_for_match,
        _validate_guidance,
    )

    raw_text = "Real text only mentions Q1 revenue growth."
    raw_norm = _normalize_for_match(raw_text)

    caplog.set_level(logging.WARNING, logger="agents.earnings_extractor")
    out = _validate_guidance(
        {
            "revenue_growth": "+15%",
            "capex_outlook": "+20%",
            "raw_quote": "We expect to grow revenue 50% YoY through Mars colonies",
        },
        raw_norm,
        transcript_id=42,
    )
    # All three fields are blanked because raw_quote failed verification.
    assert out == {"revenue_growth": None, "capex_outlook": None, "raw_quote": None}
    # One warning fired.
    rejected = [
        r for r in caplog.records
        if "earnings_extractor.guidance_rejected" in r.getMessage()
    ]
    assert len(rejected) >= 1
