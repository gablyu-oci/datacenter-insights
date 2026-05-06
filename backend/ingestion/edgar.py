"""
EDGAR Adapter — Phase 1A ingestion for SEC 8-K / 10-K / 10-Q filings.

Fetches filings from ENERGY_COMPANIES and HYPERSCALERS, extracts MW figures
and counterparty mentions via regex, and upserts into edgar_extractions.

Rate limited to ~8 concurrent requests with 120ms delay (stays under
SEC EDGAR's 10 req/s limit with headroom).

Phase 1C will add LLM-based extraction on top of this adapter.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, date

import httpx
import stamina
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from config import settings
from agents.edgar_agent import (
    ENERGY_COMPANIES,
    HYPERSCALERS,
    CACHE_DIR,
    CACHE_TTL_HOURS,
    _html_to_text,
    _parse_mw_from_text,
    _load_cache,
    _save_cache,
)
from db.models import DataCoverage, IngestionRun

logger = logging.getLogger(__name__)

# Keywords used to detect datacenter/power relevance in filing text
_TECH_KEYWORDS = frozenset([
    "microsoft", "amazon", "google", "meta", "oracle",
    "artificial intelligence", "data center", "hyperscale",
    "nuclear", "restart", "clean energy", "power purchase",
    "megawatt", "gigawatt",
])

# Energy source detection patterns
_ENERGY_SOURCE_PATTERNS = [
    (re.compile(r"\bnuclear\b", re.I), "nuclear"),
    (re.compile(r"\bsolar\b", re.I), "solar"),
    (re.compile(r"\bwind\b", re.I), "wind"),
    (re.compile(r"\bnatural\s+gas\b", re.I), "natural_gas"),
    (re.compile(r"\bhydrogen\b", re.I), "hydrogen"),
    (re.compile(r"\bgeothermal\b", re.I), "geothermal"),
    (re.compile(r"\bbattery|storage\b", re.I), "battery_storage"),
]


def _detect_energy_source(text: str) -> str | None:
    """Return the first matching energy source from text, or None."""
    lower = text.lower()
    for pattern, source in _ENERGY_SOURCE_PATTERNS:
        if pattern.search(lower):
            return source
    return None


def _detect_counterparty(text: str, source_company: str) -> tuple[str | None, str | None]:
    """
    Detect buyer/seller from text.  For energy companies the buyer is
    typically a hyperscaler; for hyperscalers the seller is typically
    an energy company.
    """
    lower = text.lower()
    buyer = None
    seller = None

    hyperscaler_names = list(HYPERSCALERS.keys())
    energy_names = [n for n in ENERGY_COMPANIES.keys() if ENERGY_COMPANIES[n] is not None]

    # If source is an energy company, look for hyperscaler buyers
    if source_company in ENERGY_COMPANIES:
        seller = source_company
        for name in hyperscaler_names:
            if name.lower() in lower:
                buyer = name
                break
    else:
        # Source is a hyperscaler, look for energy seller
        buyer = source_company
        for name in energy_names:
            if name.lower() in lower:
                seller = name
                break

    return buyer, seller


class EdgarAdapter:
    """
    SEC EDGAR filing ingestion adapter.

    Fetches 8-K (item 1.01), 10-K, and 10-Q filings from tracked energy
    companies and hyperscalers.  Extracts capacity, counterparties, and
    energy source via regex.  Upserts into edgar_extractions table.
    """

    adapter_name = "SEC EDGAR"
    adapter_id = "edgar"
    adapter_version = "2.0.0"
    pillar = "sec_filings"
    source_id = "edgar"
    declared_status = "full"
    coverage_scope = "US"

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(8)
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": settings.edgar_user_agent,
                    "Accept": "application/json",
                },
                timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0),
                follow_redirects=True,
            )
        return self._client

    @stamina.retry(on=httpx.TransportError, attempts=3, wait_initial=1.0)
    async def _rate_limited_get(self, url: str, is_json: bool = True) -> dict | str:
        """Rate-limited HTTP GET with semaphore and retry."""
        async with self._semaphore:
            await asyncio.sleep(0.12)  # ~8 req/s to stay under 10 req/s
            client = await self._get_client()
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json() if is_json else resp.text

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # EDGAR data fetching
    # ------------------------------------------------------------------

    async def _get_submissions(self, cik: str) -> dict:
        """Fetch filing submissions for a CIK, with 12h file cache."""
        cache_key = f"submissions_{cik}"
        cached = _load_cache(cache_key)
        if cached is not None:
            return cached

        padded = cik.zfill(10)
        url = f"https://data.sec.gov/submissions/CIK{padded}.json"
        data = await self._rate_limited_get(url, is_json=True)
        _save_cache(cache_key, data)
        return data

    async def _get_filings_for_company(
        self, cik: str, company_name: str, since_date: str, form_types: set[str]
    ) -> list[dict]:
        """
        Return matching filings from a company's submission history.
        For 8-K, only include filings with item 1.01 (material agreements).
        """
        try:
            data = await self._get_submissions(cik)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "edgar.submissions_http_error",
                extra={"cik": cik, "company": company_name, "status": exc.response.status_code},
            )
            return []
        except httpx.TimeoutException:
            logger.error("edgar.submissions_timeout", extra={"cik": cik, "company": company_name})
            return []

        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accs = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [""] * len(forms))
        items_list = recent.get("items", [""] * len(forms))

        results = []
        for form, filing_date, acc, doc, items in zip(forms, dates, accs, docs, items_list):
            if form not in form_types:
                continue
            if filing_date < since_date:
                continue
            # For 8-K, require item 1.01 (Entry into a Material Definitive Agreement)
            if form == "8-K" and "1.01" not in str(items):
                continue

            cik_num = cik.lstrip("0")
            acc_path = acc.replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_path}/{doc}"

            results.append({
                "company": company_name,
                "cik": cik,
                "form_type": form,
                "filing_date": filing_date,
                "accession_number": acc,
                "edgar_url": url,
                "item_codes": str(items),
            })

        return results

    async def _extract_filing_text(self, url: str, max_chars: int = 8000) -> str:
        """Fetch a filing document and extract relevant text."""
        cache_key = f"filing_{url.split('/')[-1].replace('.', '_')}"
        cached = _load_cache(cache_key)
        if cached is not None:
            return cached.get("text", "")

        try:
            html = await self._rate_limited_get(url, is_json=False)
            text = _html_to_text(html)

            # Extract sentences mentioning power/energy keywords
            keywords = [
                "nuclear", "power purchase", "gigawatt", "megawatt",
                "energy agreement", "microsoft", "amazon", "google", "meta",
                "artificial intelligence", "data center", "hyperscale",
                "capacity", "generation", "renewable",
            ]
            sentences = re.split(r"(?<=[.!?])\s+", text)
            relevant = []
            for s in sentences:
                s = s.strip()
                if len(s) > 60 and any(kw in s.lower() for kw in keywords):
                    relevant.append(s)

            excerpt = " ".join(relevant)[:max_chars] if relevant else text[:max_chars]
            _save_cache(cache_key, {"text": excerpt})
            return excerpt
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "edgar.filing_fetch_http_error",
                extra={"url": url, "status": exc.response.status_code},
            )
            return ""
        except httpx.TimeoutException:
            logger.warning("edgar.filing_fetch_timeout", extra={"url": url})
            return ""

    # ------------------------------------------------------------------
    # Main run method
    # ------------------------------------------------------------------

    async def run(self, session: AsyncSession, *, days_back: int = 90) -> dict:
        """
        Fetch recent filings from ENERGY_COMPANIES + HYPERSCALERS.
        Extract MW, counterparties via regex.
        Upsert into edgar_extractions.
        Return summary dict with counts.
        """
        # Lazy import — the EdgarExtraction model is being added by another agent
        # and may not be present at module-load time.
        from db.models import EdgarExtraction  # noqa: F811

        since_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        form_types = {"8-K", "10-K", "10-Q"}

        # Create ingestion run record
        run_record = IngestionRun(
            adapter_name=self.adapter_id,
            adapter_version=self.adapter_version,
            started_at=datetime.utcnow(),
            status="running",
            trigger="manual",
            config_snapshot={"days_back": days_back, "since_date": since_date},
        )
        session.add(run_record)
        await session.flush()

        all_companies = {}
        all_companies.update({name: cik for name, cik in ENERGY_COMPANIES.items() if cik})
        all_companies.update({name: cik for name, cik in HYPERSCALERS.items() if cik})

        records_fetched = 0
        records_stored = 0
        records_skipped = 0
        errors: list[dict] = []

        try:
            for company_name, cik in all_companies.items():
                try:
                    filings = await self._get_filings_for_company(
                        cik, company_name, since_date, form_types
                    )
                    records_fetched += len(filings)

                    # Process up to 10 filings per company to avoid excessive load
                    for filing in filings[:10]:
                        try:
                            text = await self._extract_filing_text(filing["edgar_url"])
                            if not text:
                                records_skipped += 1
                                continue

                            # Only process filings with datacenter/power relevance
                            lower_text = text.lower()
                            is_relevant = any(kw in lower_text for kw in _TECH_KEYWORDS)
                            if not is_relevant and filing["form_type"] == "8-K":
                                records_skipped += 1
                                continue

                            capacity_mw = _parse_mw_from_text(text)
                            energy_source = _detect_energy_source(text)
                            buyer, seller = _detect_counterparty(text, company_name)
                            confidence = 0.90 if capacity_mw else 0.60

                            # Build the row for upsert
                            # Track C: set is_power_related from the keyword
                            # gate (is_relevant) plus 10-K filings of tracked
                            # filers (where the body discusses energy contracts
                            # in Note 1 / Derivative Instruments). We use
                            # deal_index=0 here because the regex extractor
                            # only emits one deal per filing — multi-deal
                            # extraction is the LLM extractor's job.
                            row = {
                                "cik": cik,
                                "accession_number": filing["accession_number"],
                                "form_type": filing["form_type"],
                                "filing_date": date.fromisoformat(filing["filing_date"]),
                                "item_codes": filing["item_codes"],
                                "edgar_url": filing["edgar_url"],
                                "capacity_mw": capacity_mw,
                                "energy_source": energy_source,
                                "buyer_raw": buyer,
                                "seller_raw": seller,
                                "excerpt": text[:2000],
                                "parser_version": self.adapter_version,
                                "confidence": confidence,
                                "retrieved_at": datetime.utcnow(),
                                "is_power_related": bool(is_relevant or capacity_mw or buyer),
                                "deal_index": 0,
                            }

                            # Upsert: target the new composite unique constraint
                            # `(accession_number, deal_index)` from migration 012.
                            stmt = pg_insert(EdgarExtraction).values(**row)
                            stmt = stmt.on_conflict_do_update(
                                index_elements=["accession_number", "deal_index"],
                                set_={
                                    "capacity_mw": stmt.excluded.capacity_mw,
                                    "energy_source": stmt.excluded.energy_source,
                                    "buyer_raw": stmt.excluded.buyer_raw,
                                    "seller_raw": stmt.excluded.seller_raw,
                                    "excerpt": stmt.excluded.excerpt,
                                    "parser_version": stmt.excluded.parser_version,
                                    "confidence": stmt.excluded.confidence,
                                    "retrieved_at": stmt.excluded.retrieved_at,
                                    "is_power_related": stmt.excluded.is_power_related,
                                },
                            )
                            await session.execute(stmt)
                            records_stored += 1

                        except httpx.HTTPStatusError as exc:
                            logger.warning(
                                "edgar.filing_process_http_error",
                                extra={
                                    "company": company_name,
                                    "accession": filing["accession_number"],
                                    "status": exc.response.status_code,
                                },
                            )
                            records_skipped += 1
                        except Exception as exc:
                            logger.error(
                                "edgar.filing_process_error",
                                extra={
                                    "company": company_name,
                                    "accession": filing.get("accession_number"),
                                    "error_class": type(exc).__name__,
                                    "error": str(exc),
                                },
                            )
                            records_skipped += 1

                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "edgar.company_batch_error",
                        extra={"company": company_name, "status": exc.response.status_code},
                    )
                    errors.append({"company": company_name, "error": str(exc)})

            # Write data_coverage row
            await self._write_coverage(session, records_stored)

            # Finalize ingestion run
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
                "edgar.run_fatal_error",
                extra={"error_class": type(exc).__name__, "error": str(exc)},
            )
            raise
        finally:
            await self.close()

        return {
            "adapter": self.adapter_id,
            "status": run_record.status,
            "records_fetched": records_fetched,
            "records_stored": records_stored,
            "records_skipped": records_skipped,
        }

    async def _write_coverage(self, session: AsyncSession, record_count: int) -> None:
        """Upsert a data_coverage row for this adapter."""
        stmt = pg_insert(DataCoverage).values(
            pillar=self.pillar,
            state_code=self.coverage_scope,
            source=self.source_id,
            coverage_status=self.declared_status,
            record_count=record_count,
            last_ingested_at=datetime.utcnow(),
            freshness_sla_hours=24,
            notes="SEC EDGAR 8-K/10-K/10-Q filings for energy and hyperscaler companies",
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
