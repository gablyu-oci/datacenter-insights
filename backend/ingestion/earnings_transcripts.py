"""Alpha Vantage earnings-call-transcript ingestion adapter.

Conforms to ``backend/ingestion/base.py:DataSourceAdapter`` Protocol.
Mirrors the shape of ``backend/ingestion/edgar.py`` deliberately: same
``run()`` signature, same ``IngestionRun`` + ``DataCoverage`` audit
pattern, same upsert + idempotency strategy.

Hard constraints (see ``docs/architecture/earnings_transcripts.md``):
  * US-public TRACKED_FILERS only. Foreign filers (TSMC, ASE, ASML) and
    pre-IPO / SPAC names (NuScale, Oklo, X-Energy) are excluded via the
    ``EARNINGS_SKIPPED`` audit list.
  * Free-tier safety: ``Semaphore(SEMAPHORE_LIMIT=1)`` plus
    ``INTER_CALL_DELAY_SECONDS=12.5`` between calls (~5 calls/min cap
    well under the 25-calls-per-day free-tier limit).
  * ``MAX_DAILY_CALLS=24`` runtime gate — once exhausted we log
    ``earnings.daily_budget_exhausted`` and exit cleanly without raising.
  * After every HTTP 200 we inspect for ``Information``/``Note`` keys —
    Alpha Vantage returns 200 with these keys on throttle. We treat that
    as a soft failure (skip + log, don't crash the job).
  * On a successful parent insert we dispatch the chunker
    (``earnings_chunker.chunk_and_store``) and the LLM extractor
    (``earnings_extractor.extract_and_update``) **in-line** so the
    cron job runs to a clean state in one DB session.

Entry point::

    adapter = EarningsTranscriptsAdapter()
    summary = await adapter.run(session, days_back=90)
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import stamina
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from agents.edgar_agent import TRACKED_FILERS, _load_cache, _save_cache
from db.models import DataCoverage, EarningsTranscript, IngestionRun

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — research §7 / architecture §3
# ---------------------------------------------------------------------------

ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
TRANSCRIPT_CACHE_TTL_HOURS = 12
CALENDAR_CACHE_TTL_HOURS = 12
MAX_DAILY_CALLS = 24
SEMAPHORE_LIMIT = 1
INTER_CALL_DELAY_SECONDS = 12.5
HTTP_TIMEOUT_SECONDS = 30.0
CALENDAR_HORIZON = "3month"
CALENDAR_WINDOW_DAYS = 14  # +/- around today, used to qualify upcoming/recent


# ---------------------------------------------------------------------------
# US-public ticker eligibility — see architecture §6.1 (verbatim).
# Display name → ticker. The display name must be a key in TRACKED_FILERS;
# otherwise we log a startup warning so the lists never drift apart.
# ---------------------------------------------------------------------------

EARNINGS_ELIGIBLE_TICKERS: dict[str, str] = {
    # ---- Hyperscalers ----
    "Microsoft":            "MSFT",
    "Amazon":               "AMZN",
    "Alphabet":             "GOOGL",
    "Meta":                 "META",
    "Oracle":               "ORCL",
    # ---- Energy / IPP / Utility — US-public ----
    "Constellation Energy": "CEG",
    "Talen Energy":         "TLN",
    "Vistra Energy":        "VST",
    "NextEra Energy":       "NEE",
    "AES Corporation":      "AES",
    "Dominion Energy":      "D",
    # ---- Silicon (US-public, non-FPI) ----
    "NVIDIA":               "NVDA",
    "AMD":                  "AMD",
    "Intel-DCAI":           "INTC",   # one ticker for the Intel filer
    "Broadcom":             "AVGO",
    "Marvell":              "MRVL",
    "Coherent":             "COHR",
    "Lumentum":             "LITE",
    "Credo":                "CRDO",
    "Astera Labs":          "ALAB",
    "Fabrinet":             "FN",
    "Amkor":                "AMKR",
    "Applied Materials":    "AMAT",
    # ---- Additional power-pillar US-public ----
    "Apple":                "AAPL",
    "IBM":                  "IBM",
    "Duke Energy":          "DUK",
    "Southern Co":          "SO",
    "AEP":                  "AEP",
    "Exelon":               "EXC",
    "Entergy":              "ETR",
    "PG&E":                 "PCG",
    "Snowflake":            "SNOW",
    "Palantir":             "PLTR",
    "ServiceNow":           "NOW",
    "Salesforce":           "CRM",
    "MongoDB":              "MDB",
    "Datadog":              "DDOG",
    "Equinix":              "EQIX",
    "Digital Realty":       "DLR",
    "Iron Mountain":        "IRM",
}

EARNINGS_SKIPPED: dict[str, str] = {
    "TSMC":             "FPI 20-F filer; Alpha Vantage returns []",
    "ASE Technology":   "FPI 20-F filer; Alpha Vantage returns []",
    "GlobalFoundries":  "FPI 20-F filer",
    "ASML":             "FPI 20-F filer",
    "NuScale Power":    "Excluded per skip list (pre-IPO/SPAC volatility)",
    "Oklo":             "Excluded per skip list (pre-IPO/SPAC volatility)",
    "X-Energy":         "Private, no SEC filings",
}


# ---------------------------------------------------------------------------
# Helpers — quarter math
# ---------------------------------------------------------------------------


def _quarter_from_date(d: date) -> str:
    """Convert a date to canonical ``YYYYQN`` (Alpha Vantage convention)."""
    q = (d.month - 1) // 3 + 1
    return f"{d.year}Q{q}"


def _parse_quarter(s: str) -> tuple[int, int]:
    """Return ``(fiscal_year, fiscal_quarter)`` from ``YYYYQN``.

    Falls back to ``(0, 0)`` on any parse failure so we never crash the
    pipeline on a malformed quarter label.
    """
    try:
        year_part, _, q_part = s.partition("Q")
        return int(year_part), int(q_part)
    except (ValueError, AttributeError):
        return 0, 0


def _candidate_quarters(today: date) -> list[str]:
    """The handful of quarter labels worth probing today.

    Calls land in the quarter AFTER fiscal-period-end. To keep the
    request budget tight we probe at most the current quarter and the
    two prior — i.e. companies that just reported, plus a one-quarter
    lookback buffer for late filers.
    """
    quarters: list[str] = []
    seen = set()
    for delta_months in (0, -3, -6):
        ref = today.replace(day=1)
        # naive month math: walk back ``delta_months``
        m = ref.month + delta_months
        y = ref.year
        while m <= 0:
            m += 12
            y -= 1
        q = _quarter_from_date(date(y, m, 1))
        if q not in seen:
            seen.add(q)
            quarters.append(q)
    return quarters


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class EarningsTranscriptsAdapter:
    """Alpha Vantage earnings-call-transcript ingestion adapter."""

    adapter_name = "Alpha Vantage Earnings Transcripts"
    adapter_id = "earnings_transcripts"
    adapter_version = "1.0.0"
    pillar = "earnings_intelligence"
    source_id = "alpha_vantage"
    declared_status = "live"
    coverage_scope = "US"

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
        self._client: httpx.AsyncClient | None = None
        self._daily_calls_used: int = 0

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=HTTP_TIMEOUT_SECONDS,
                    write=10.0,
                    pool=10.0,
                ),
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _require_api_key(self) -> str:
        key = settings.alpha_vantage_api_key
        if not key:
            raise RuntimeError(
                "alpha_vantage_api_key is not set — earnings_transcripts adapter "
                "cannot run. Set ALPHA_VANTAGE_API_KEY in the environment."
            )
        return key

    async def _gate_daily_budget(self) -> bool:
        """Returns False (and logs once) when the daily budget is exhausted."""
        if self._daily_calls_used >= MAX_DAILY_CALLS:
            logger.warning(
                "earnings.daily_budget_exhausted",
                extra={"used": self._daily_calls_used, "cap": MAX_DAILY_CALLS},
            )
            return False
        return True

    @staticmethod
    def _check_throttled(payload: Any) -> None:
        """Raise RuntimeError if Alpha Vantage signaled throttling.

        AV returns HTTP 200 with ``{"Information": "..."}`` or
        ``{"Note": "..."}`` when rate-limited. Crashing the whole adapter
        on a throttle is bad — callers wrap this in try/except and treat
        it as a soft skip.
        """
        if isinstance(payload, dict):
            if "Information" in payload or "Note" in payload:
                msg = payload.get("Information") or payload.get("Note") or "rate limited"
                raise RuntimeError(f"alpha_vantage_throttled: {msg}")

    @stamina.retry(on=httpx.TransportError, attempts=3, wait_initial=1.0)
    async def _rate_limited_get(
        self,
        params: dict[str, str],
        *,
        as_text: bool = False,
    ) -> Any:
        """Rate-limited GET against Alpha Vantage.

        - Honors the ``SEMAPHORE_LIMIT=1`` cap.
        - Sleeps ``INTER_CALL_DELAY_SECONDS`` before each call to spread
          out a burst (5 calls/min ceiling).
        - Increments ``_daily_calls_used`` regardless of outcome.
        - Returns the parsed JSON unless ``as_text`` is True (calendar is
          served as CSV).
        """
        async with self._semaphore:
            await asyncio.sleep(INTER_CALL_DELAY_SECONDS)
            self._daily_calls_used += 1
            client = await self._get_client()
            resp = await client.get(ALPHA_VANTAGE_BASE_URL, params=params)
            resp.raise_for_status()
            if as_text:
                return resp.text
            return resp.json()

    # ------------------------------------------------------------------
    # Calendar
    # ------------------------------------------------------------------

    async def _fetch_calendar(self) -> list[dict]:
        """Fetch + cache the earnings calendar CSV from Alpha Vantage.

        Returns a list of dicts with at least:
            ``symbol``, ``reportDate``, ``fiscalDateEnding``, ``name``.
        On throttle / HTTP error returns []. On cache hit no HTTP call is
        made and the daily-budget counter is *not* incremented.
        """
        cache_key = "earnings_av_calendar"
        cached = _load_cache(cache_key)
        if cached is not None and isinstance(cached, list):
            logger.info(
                "earnings.calendar_cache_hit",
                extra={"rows": len(cached)},
            )
            return cached

        if not await self._gate_daily_budget():
            return []

        api_key = self._require_api_key()
        try:
            csv_text = await self._rate_limited_get(
                params={
                    "function": "EARNINGS_CALENDAR",
                    "horizon": CALENDAR_HORIZON,
                    "apikey": api_key,
                },
                as_text=True,
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "earnings.calendar_http_error",
                extra={"status": exc.response.status_code},
            )
            return []
        except httpx.TimeoutException:
            logger.warning("earnings.calendar_timeout")
            return []
        except Exception as exc:
            logger.warning(
                "earnings.calendar_fetch_error",
                extra={"error_class": type(exc).__name__, "error": str(exc)},
            )
            return []

        # Throttle responses come back as JSON even though we asked for CSV;
        # detect by sniffing the first character.
        stripped = (csv_text or "").lstrip()
        if stripped.startswith("{"):
            try:
                payload = json.loads(stripped)
                self._check_throttled(payload)
            except RuntimeError as exc:
                logger.warning("earnings.calendar_throttled", extra={"detail": str(exc)})
                return []
            except json.JSONDecodeError:
                pass

        rows: list[dict] = []
        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            # AV sometimes emits blank trailing rows; skip them.
            if not (row.get("symbol") or "").strip():
                continue
            rows.append(row)

        _save_cache(cache_key, rows)
        logger.info("earnings.calendar_fetched", extra={"rows": len(rows)})
        return rows

    # ------------------------------------------------------------------
    # Transcript
    # ------------------------------------------------------------------

    async def _fetch_transcript(self, symbol: str, quarter: str) -> dict | None:
        """Fetch + cache a single ``EARNINGS_CALL_TRANSCRIPT`` payload.

        Returns the parsed JSON dict (with ``symbol``, ``quarter``,
        ``transcript=[...]``) or None on failure / not-yet-available.
        Empty ``transcript: []`` means AV has no coverage for that quarter
        — we cache it anyway so we don't re-probe on every cron tick.
        """
        cache_key = f"earnings_av_transcript_{symbol}_{quarter}"
        cached = _load_cache(cache_key)
        if cached is not None and isinstance(cached, dict):
            return cached

        if not await self._gate_daily_budget():
            return None

        api_key = self._require_api_key()
        try:
            payload = await self._rate_limited_get(
                params={
                    "function": "EARNINGS_CALL_TRANSCRIPT",
                    "symbol": symbol,
                    "quarter": quarter,
                    "apikey": api_key,
                },
                as_text=False,
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "earnings.transcript_http_error",
                extra={
                    "symbol": symbol,
                    "quarter": quarter,
                    "status": exc.response.status_code,
                },
            )
            return None
        except httpx.TimeoutException:
            logger.warning(
                "earnings.transcript_timeout",
                extra={"symbol": symbol, "quarter": quarter},
            )
            return None
        except Exception as exc:
            logger.warning(
                "earnings.transcript_fetch_error",
                extra={
                    "symbol": symbol,
                    "quarter": quarter,
                    "error_class": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return None

        # Throttle sniff.
        try:
            self._check_throttled(payload)
        except RuntimeError as exc:
            logger.warning(
                "earnings.transcript_throttled",
                extra={"symbol": symbol, "quarter": quarter, "detail": str(exc)},
            )
            return None

        if not isinstance(payload, dict):
            return None

        _save_cache(cache_key, payload)
        return payload

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    async def _is_already_extracted(
        self, session: AsyncSession, cik: str, quarter: str
    ) -> bool:
        """Return True if this (cik, quarter) is already fully extracted."""
        result = await session.execute(
            sa_text(
                "SELECT extracted_at FROM earnings_transcripts "
                "WHERE cik = :cik AND quarter = :q LIMIT 1"
            ),
            {"cik": cik, "q": quarter},
        )
        row = result.first()
        if row is None:
            return False
        return row[0] is not None

    # ------------------------------------------------------------------
    # Normalize
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_payload(
        *,
        cik: str,
        ticker: str,
        company_name: str,
        quarter: str,
        call_date: date | None,
        transcript_url: str | None,
        payload: dict,
    ) -> dict:
        """AV payload → canonical row dict for ``earnings_transcripts``.

        Concatenates ``transcript[].content`` into the parent ``raw_text``,
        computes ``speaker_count`` + ``word_count``, derives fiscal_year
        and fiscal_quarter from the quarter label. The list of turns is
        returned out-of-band on the special ``__turns`` key for the
        chunker — that field is stripped before upsert.
        """
        turns = payload.get("transcript") or []
        # Defensive: AV sometimes returns turns as dicts, sometimes as
        # strings (older shapes). Only accept dict turns with `content`.
        clean_turns: list[dict] = []
        for t in turns:
            if not isinstance(t, dict):
                continue
            content = (t.get("content") or "").strip()
            if not content:
                continue
            clean_turns.append({
                "speaker": (t.get("speaker") or "").strip() or None,
                "title": (t.get("title") or "").strip() or None,
                "content": content,
                "sentiment": t.get("sentiment"),
            })

        speakers = {t["speaker"] for t in clean_turns if t.get("speaker")}
        # raw_text uses the same "Speaker: content\n\n..." layout the
        # chunker anchors against (see earnings_chunker._format_turn_text).
        parts: list[str] = []
        for t in clean_turns:
            spk = t.get("speaker") or ""
            if spk:
                parts.append(f"{spk}: {t['content']}")
            else:
                parts.append(t["content"])
        raw_text = "\n\n".join(parts)
        word_count = len(raw_text.split()) if raw_text else 0
        fy, fq = _parse_quarter(quarter)

        return {
            "cik": cik,
            "ticker": ticker,
            "company_name": company_name,
            "quarter": quarter,
            "fiscal_year": fy or None,
            "fiscal_quarter": fq or None,
            "call_date": call_date,
            "transcript_url": transcript_url,
            "raw_text": raw_text,
            "speaker_count": len(speakers) or None,
            "word_count": word_count or None,
            "retrieved_at": datetime.utcnow(),
            "__turns": clean_turns,
        }

    # ------------------------------------------------------------------
    # Upsert + downstream dispatch
    # ------------------------------------------------------------------

    async def _upsert_one(
        self, session: AsyncSession, record: dict
    ) -> int | None:
        """Upsert one parent row and return its primary key (id)."""
        turns = record.pop("__turns", [])
        # Don't smuggle non-column keys into the insert.
        row = {k: v for k, v in record.items() if not k.startswith("__")}

        stmt = pg_insert(EarningsTranscript).values(**row)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_earnings_transcripts_cik_quarter",
            set_={
                "ticker": stmt.excluded.ticker,
                "company_name": stmt.excluded.company_name,
                "fiscal_year": stmt.excluded.fiscal_year,
                "fiscal_quarter": stmt.excluded.fiscal_quarter,
                "call_date": stmt.excluded.call_date,
                "transcript_url": stmt.excluded.transcript_url,
                "raw_text": stmt.excluded.raw_text,
                "speaker_count": stmt.excluded.speaker_count,
                "word_count": stmt.excluded.word_count,
                "retrieved_at": stmt.excluded.retrieved_at,
            },
        ).returning(EarningsTranscript.id)
        result = await session.execute(stmt)
        transcript_id = result.scalar_one_or_none()

        # Re-attach turns so the caller can dispatch the chunker.
        record["__turns"] = turns
        record["__transcript_id"] = transcript_id
        return transcript_id

    async def _dispatch_downstream(
        self,
        session: AsyncSession,
        transcript_id: int,
        raw_text: str,
        turns: list[dict],
    ) -> tuple[int, bool]:
        """Run the chunker + the LLM extractor against a freshly-upserted
        transcript. Returns ``(passage_count, extractor_ok)``.

        Failures in either step are logged and swallowed — they should
        not abort the broader ingestion run.
        """
        # 1) Chunk
        passage_count = 0
        try:
            from ingestion.earnings_chunker import chunk_and_store
            passage_count = await chunk_and_store(
                session, transcript_id, raw_text, turns=turns
            )
        except Exception as exc:
            logger.error(
                "earnings.chunker_failed",
                extra={
                    "transcript_id": transcript_id,
                    "error_class": type(exc).__name__,
                    "error": str(exc),
                },
            )

        # 2) Extract
        extractor_ok = False
        try:
            from agents.earnings_extractor import extract_and_update
            result = await extract_and_update(session, transcript_id)
            extractor_ok = bool(result.get("ok"))
        except Exception as exc:
            logger.error(
                "earnings.extractor_failed",
                extra={
                    "transcript_id": transcript_id,
                    "error_class": type(exc).__name__,
                    "error": str(exc),
                },
            )

        return passage_count, extractor_ok

    # ------------------------------------------------------------------
    # Ticker resolution (CIK lookup)
    # ------------------------------------------------------------------

    @staticmethod
    def _tracked_filers_by_display() -> dict[str, str]:
        """Restrict to US-public eligible filers and return display→cik.

        Filters TRACKED_FILERS through ``EARNINGS_ELIGIBLE_TICKERS`` and
        drops any name without a CIK (private companies).
        """
        out: dict[str, str] = {}
        for display, ticker in EARNINGS_ELIGIBLE_TICKERS.items():
            cik = TRACKED_FILERS.get(display)
            if not cik:
                logger.warning(
                    "earnings.no_cik_for_ticker",
                    extra={"display": display, "ticker": ticker},
                )
                continue
            out[display] = cik
        return out

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(
        self,
        session: AsyncSession,
        *,
        days_back: int = 90,
        ticker_filter: list[str] | None = None,
    ) -> dict:
        """fetch → normalize → upsert → chunker → extractor → coverage.

        ``ticker_filter`` narrows execution to a subset of tickers (used
        by tests / dry-run). ``days_back`` controls the candidate-quarter
        sweep window but the heavy lifting is the AV calendar.

        Returns the standard summary dict::

            {
              "adapter": "earnings_transcripts",
              "status": "success" | "partial_failure" | "failure",
              "records_fetched": int,
              "records_stored": int,
              "records_skipped": int,
              "passages_written": int,
              "extractor_runs": int,
            }
        """
        run_record = IngestionRun(
            adapter_name=self.adapter_id,
            adapter_version=self.adapter_version,
            started_at=datetime.utcnow(),
            status="running",
            trigger="manual",
            config_snapshot={
                "days_back": days_back,
                "ticker_filter": ticker_filter,
                "daily_call_cap": MAX_DAILY_CALLS,
                "inter_call_delay_seconds": INTER_CALL_DELAY_SECONDS,
            },
        )
        session.add(run_record)
        await session.flush()

        records_fetched = 0
        records_stored = 0
        records_skipped = 0
        passages_written = 0
        extractor_runs = 0
        errors: list[dict] = []

        try:
            # 1) Calendar — used to figure out which (ticker, quarter)
            #    pairs just had a call. Failures here aren't fatal; we
            #    fall back to the candidate-quarter sweep so the cron
            #    still runs against a sensible default set.
            calendar_rows = await self._fetch_calendar()
            today = datetime.utcnow().date()
            window_start = today - timedelta(days=CALENDAR_WINDOW_DAYS)
            window_end = today + timedelta(days=CALENDAR_WINDOW_DAYS)

            # ticker → most-recent reportDate seen in the calendar
            ticker_to_report_date: dict[str, date] = {}
            for row in calendar_rows:
                sym = (row.get("symbol") or "").strip().upper()
                if not sym:
                    continue
                rep_str = (row.get("reportDate") or "").strip()
                if not rep_str:
                    continue
                try:
                    rep_date = date.fromisoformat(rep_str)
                except ValueError:
                    continue
                if not (window_start <= rep_date <= window_end):
                    continue
                # If the same ticker appears twice take the latest.
                existing = ticker_to_report_date.get(sym)
                if existing is None or rep_date > existing:
                    ticker_to_report_date[sym] = rep_date

            # 2) Build the eligible-ticker → cik map and intersect.
            eligible = self._tracked_filers_by_display()  # display → cik

            # Log the skip list once per run for auditability.
            logger.info(
                "earnings.eligible_set",
                extra={
                    "eligible_count": len(eligible),
                    "skipped_count": len(EARNINGS_SKIPPED),
                },
            )

            # ticker_filter narrows by symbol (case-insensitive).
            tf_set: set[str] | None = None
            if ticker_filter:
                tf_set = {t.strip().upper() for t in ticker_filter if t and t.strip()}

            # 3) Candidate-quarter set — defends against calendars that
            #    might be empty or stale.
            candidate_quarters = _candidate_quarters(today)
            logger.info(
                "earnings.candidate_quarters",
                extra={"quarters": candidate_quarters},
            )

            for display, cik in eligible.items():
                ticker = EARNINGS_ELIGIBLE_TICKERS[display]
                if tf_set and ticker.upper() not in tf_set:
                    continue

                # Determine which quarters to probe for this ticker.
                rep_date = ticker_to_report_date.get(ticker.upper())
                if rep_date is not None:
                    # The calendar shows a recent/upcoming call: target
                    # the quarter that just ended (one quarter before
                    # the reportDate).
                    one_q_back = rep_date - timedelta(days=45)
                    primary_q = _quarter_from_date(one_q_back)
                    probe_quarters = [primary_q]
                else:
                    # No calendar hit — fall back to the candidate sweep.
                    probe_quarters = candidate_quarters

                for quarter in probe_quarters:
                    records_fetched += 1

                    # Idempotency: skip if we've already extracted this row.
                    try:
                        if await self._is_already_extracted(session, cik, quarter):
                            records_skipped += 1
                            continue
                    except Exception as exc:
                        logger.warning(
                            "earnings.idempotency_check_failed",
                            extra={
                                "cik": cik,
                                "quarter": quarter,
                                "error": str(exc),
                            },
                        )

                    # Budget gate.
                    if not await self._gate_daily_budget():
                        # Daily cap hit — stop launching new fetches and
                        # let the run finalize cleanly.
                        records_skipped += 1
                        break

                    payload = await self._fetch_transcript(ticker, quarter)
                    if payload is None:
                        records_skipped += 1
                        continue

                    turns = payload.get("transcript") or []
                    if not turns:
                        # AV returns {"symbol": "...", "quarter": "...",
                        # "transcript": []} for unavailable / pre-call
                        # quarters. Cache + skip; not an error.
                        records_skipped += 1
                        continue

                    transcript_url = None
                    record = self._normalize_payload(
                        cik=cik,
                        ticker=ticker,
                        company_name=display,
                        quarter=quarter,
                        call_date=rep_date,
                        transcript_url=transcript_url,
                        payload=payload,
                    )
                    if not record.get("raw_text"):
                        records_skipped += 1
                        continue

                    try:
                        transcript_id = await self._upsert_one(session, record)
                    except Exception as exc:
                        logger.error(
                            "earnings.upsert_failed",
                            extra={
                                "cik": cik,
                                "quarter": quarter,
                                "ticker": ticker,
                                "error_class": type(exc).__name__,
                                "error": str(exc),
                            },
                        )
                        errors.append({
                            "ticker": ticker,
                            "quarter": quarter,
                            "stage": "upsert",
                            "error": str(exc),
                        })
                        records_skipped += 1
                        continue

                    if transcript_id is None:
                        records_skipped += 1
                        continue

                    records_stored += 1

                    # Chunk + extract in-line so the cron leaves the DB
                    # in a fully-ready state.
                    passages, ok = await self._dispatch_downstream(
                        session,
                        transcript_id,
                        record["raw_text"],
                        record.get("__turns") or [],
                    )
                    passages_written += passages
                    if ok:
                        extractor_runs += 1

                # If the daily budget tripped inside the inner loop we
                # break the outer loop too so we don't keep probing.
                if not await self._gate_daily_budget():
                    break

            # 4) Coverage row.
            try:
                await self._write_coverage(session, records_stored)
            except Exception as exc:
                logger.warning(
                    "earnings.coverage_write_failed",
                    extra={"error_class": type(exc).__name__, "error": str(exc)},
                )

            # 5) Finalize the ingestion run.
            run_record.status = "success" if not errors else "partial_failure"
            run_record.completed_at = datetime.utcnow()
            run_record.records_fetched = records_fetched
            run_record.records_stored = records_stored
            run_record.records_skipped = records_skipped
            run_record.error_log = {"errors": errors} if errors else None
            await session.flush()

        except Exception as exc:
            run_record.status = "failure"
            run_record.completed_at = datetime.utcnow()
            run_record.records_fetched = records_fetched
            run_record.records_stored = records_stored
            run_record.records_skipped = records_skipped
            run_record.error_log = {"fatal": str(exc)}
            await session.flush()
            logger.error(
                "earnings.run_fatal_error",
                extra={"error_class": type(exc).__name__, "error": str(exc)},
            )
            raise
        finally:
            await self.close()

        logger.info(
            "earnings.run_done",
            extra={
                "status": run_record.status,
                "fetched": records_fetched,
                "stored": records_stored,
                "skipped": records_skipped,
                "passages": passages_written,
                "extractor_runs": extractor_runs,
                "daily_calls_used": self._daily_calls_used,
            },
        )

        return {
            "adapter": self.adapter_id,
            "status": run_record.status,
            "records_fetched": records_fetched,
            "records_stored": records_stored,
            "records_skipped": records_skipped,
            "passages_written": passages_written,
            "extractor_runs": extractor_runs,
            "daily_calls_used": self._daily_calls_used,
        }

    # ------------------------------------------------------------------
    # Coverage
    # ------------------------------------------------------------------

    async def _write_coverage(
        self, session: AsyncSession, record_count: int
    ) -> None:
        """Upsert the data_coverage row for ``earnings_intelligence`` / US."""
        stmt = pg_insert(DataCoverage).values(
            pillar=self.pillar,
            state_code=self.coverage_scope,
            source=self.source_id,
            coverage_status=self.declared_status,
            record_count=record_count,
            last_ingested_at=datetime.utcnow(),
            freshness_sla_hours=24,
            notes=(
                "Alpha Vantage earnings call transcripts for US-public "
                "TRACKED_FILERS (hyperscalers, energy/IPP/utility, silicon)."
            ),
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_coverage_pillar_state_source",
            set_={
                "coverage_status": stmt.excluded.coverage_status,
                "record_count": stmt.excluded.record_count,
                "last_ingested_at": stmt.excluded.last_ingested_at,
                "updated_at": datetime.utcnow(),
            },
        )
        await session.execute(stmt)


__all__ = [
    "EarningsTranscriptsAdapter",
    "EARNINGS_ELIGIBLE_TICKERS",
    "EARNINGS_SKIPPED",
    "ALPHA_VANTAGE_BASE_URL",
    "MAX_DAILY_CALLS",
    "SEMAPHORE_LIMIT",
    "INTER_CALL_DELAY_SECONDS",
]
