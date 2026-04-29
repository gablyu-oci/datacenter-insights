"""
TCEQ Adapter -- Texas Commission on Environmental Quality NSR pending air permits.

Phase 1.5 fix (2026-04-29):
  Replaced the brittle regex-based scrape of the Central Registry with a
  BeautifulSoup parse of the canonical NSR Pending Permits HTML report at
  https://www.tceq.texas.gov/assets/public/permitting/air/reports/applications/nsr-pending-permits.html

The page contains a single primary <table> (the second on the page) with one
row per pending permit application. Columns:
  Applicant Name | Facility Name | Permit Number | Received Date | Application Link

We filter rows to data-center-relevant matches via a regex on applicant +
facility names (Aligned, Crusoe, Amazon, Microsoft, Google, Meta, Equinix,
Digital Realty, QTS, CyrusOne, Nexus, Stack, Compass, "data center",
"hyperscale", "colocation").
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, date
from typing import Optional

import httpx
import stamina
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import (
    DataCoverage,
    DataLineage,
    GeneratorPermit,
    IngestionRun,
    Site,
    SiteAlias,
    SiteCompanyAssociation,
)
from entity_resolution import resolve_company

logger = logging.getLogger(__name__)

_PROXIMITY_DEGREES = 0.001

# Phase 1.5 canonical endpoint
_TCEQ_NSR_URL = (
    "https://www.tceq.texas.gov/assets/public/permitting/air/reports/applications/"
    "nsr-pending-permits.html"
)

# Data-center facility/applicant regex
_DC_REGEX = re.compile(
    r"data\s*center|hyperscale|colocation|\bcolo\b|crusoe|aligned|"
    r"amazon|microsoft|google|meta|nexus|stack\s*infrastructure|"
    r"compass\s*data|equinix|digital\s*realty|qts|cyrusone",
    re.I,
)


class TceqAdapter:
    """
    TCEQ NSR Pending-Permit ingestion adapter.

    Fetches the public NSR pending-permits HTML page, parses the application
    table, filters rows whose applicant or facility name matches the
    data-center / hyperscaler regex, and upserts into generator_permits.
    """

    adapter_name = "TCEQ NSR Pending Permits"
    adapter_id = "tceq"
    adapter_version = "2.0.0"
    pillar = "building_permits"
    source_id = "tceq"
    declared_status = "partial"
    coverage_scope = "TX"

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(2)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=60.0, write=10.0, pool=15.0),
                follow_redirects=True,
                headers={
                    "User-Agent": "strategic-insights-tool/1.0 (research)",
                    "Accept": "text/html, */*",
                },
            )
        return self._client

    @stamina.retry(on=httpx.TransportError, attempts=3, wait_initial=2.0)
    async def _fetch_html(self) -> str:
        async with self._semaphore:
            await asyncio.sleep(1.0)
            client = await self._get_client()
            resp = await client.get(_TCEQ_NSR_URL)
            resp.raise_for_status()
            return resp.text

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # HTML parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_received_date(value: str) -> Optional[date]:
        if not value:
            return None
        s = value.strip()
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    def _parse_table(self, html: str) -> list[dict]:
        """
        Parse the NSR pending permits HTML page.

        Returns a list of {applicant_name, facility_name, permit_number,
        received_date, source_url} dicts -- one per matching application row.
        """
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        if len(tables) < 2:
            logger.warning("tceq.no_table_found", extra={"tables": len(tables)})
            return []

        # The applications table is table index 1 (0 is the header navigation).
        # We don't hard-code the index though -- pick whichever table has the
        # expected header row.
        target_table = None
        for t in tables:
            header = t.find("tr")
            if not header:
                continue
            header_text = header.get_text(" ", strip=True).lower()
            if "applicant" in header_text and "permit" in header_text:
                target_table = t
                break
        if target_table is None:
            logger.warning("tceq.application_table_not_found")
            return []

        results: list[dict] = []
        for tr in target_table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 4:
                continue
            applicant_text = cells[0].get_text(" ", strip=True)
            facility_text = cells[1].get_text(" ", strip=True)
            permit_text = cells[2].get_text(" ", strip=True)
            received_text = cells[3].get_text(" ", strip=True) if len(cells) > 3 else ""

            # Skip separator rows (no permit number)
            if not permit_text or not applicant_text:
                continue
            if "back to top" in permit_text.lower():
                continue

            # Strip the trailing "Plain Language Notice" tail off applicant name
            applicant = re.sub(
                r"\s*Plain\s*Language\s*Notice.*$",
                "",
                applicant_text,
                flags=re.I,
            ).strip()

            # Permit number column may contain a primary number and additional
            # PSD/GHG numbers (e.g. "182126, GHGPSDTX263, PSDTX1688"). Use the
            # first (primary) token as the source_permit_id.
            primary_permit = permit_text.split(",")[0].strip()

            # PDF / detail link from the row
            link = tr.find("a", href=True)
            source_url = link["href"] if link else None
            if source_url and source_url.startswith("/"):
                source_url = f"https://www.tceq.texas.gov{source_url}"

            results.append({
                "applicant_name": applicant,
                "facility_name": facility_text,
                "permit_number": primary_permit,
                "permit_number_raw": permit_text,
                "received_date": self._parse_received_date(received_text),
                "source_url": source_url,
            })

        return results

    def _is_data_center(self, row: dict) -> bool:
        blob = " ".join([
            row.get("applicant_name") or "",
            row.get("facility_name") or "",
        ])
        return bool(_DC_REGEX.search(blob))

    # ------------------------------------------------------------------
    # Normalize & site matching
    # ------------------------------------------------------------------

    def _normalize_record(self, row: dict) -> dict | None:
        permit_no = row.get("permit_number")
        if not permit_no:
            return None
        return {
            "source": self.source_id,
            "source_permit_id": str(permit_no)[:255],
            "facility_name": row.get("facility_name"),
            "permittee_raw_name": row.get("applicant_name"),
            "state_code": "TX",
            "permit_status": "pending",
            "issued_date": row.get("received_date"),
            "confidence": 0.65,
            "raw_payload": {
                "applicant_name": row.get("applicant_name"),
                "facility_name": row.get("facility_name"),
                "permit_number_raw": row.get("permit_number_raw"),
                "received_date": (
                    row["received_date"].isoformat() if row.get("received_date") else None
                ),
                "source_url": row.get("source_url"),
            },
        }

    async def _match_site(
        self, session: AsyncSession, lat: float, lon: float
    ) -> int | None:
        if lat is None or lon is None:
            return None
        stmt = (
            select(Site.id)
            .where(
                Site.latitude.between(lat - _PROXIMITY_DEGREES, lat + _PROXIMITY_DEGREES),
                Site.longitude.between(lon - _PROXIMITY_DEGREES, lon + _PROXIMITY_DEGREES),
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    async def run(self, session: AsyncSession) -> dict:
        run_record = IngestionRun(
            adapter_name=self.adapter_id,
            adapter_version=self.adapter_version,
            started_at=datetime.utcnow(),
            status="running",
            trigger="manual",
        )
        session.add(run_record)
        await session.flush()

        records_fetched = 0
        records_stored = 0
        records_skipped = 0
        errors: list[dict] = []

        try:
            try:
                html = await self._fetch_html()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "tceq.fetch_http_error",
                    extra={"status": exc.response.status_code},
                )
                html = ""
            except httpx.TransportError as exc:
                logger.error("tceq.fetch_transport_error", extra={"error": str(exc)})
                html = ""

            all_rows = self._parse_table(html) if html else []
            records_fetched = len(all_rows)

            dc_rows = [r for r in all_rows if self._is_data_center(r)]
            logger.info(
                "tceq.parsed",
                extra={"total": records_fetched, "data_center_matches": len(dc_rows)},
            )

            for raw in dc_rows:
                normalized = self._normalize_record(raw)
                if not normalized:
                    records_skipped += 1
                    continue

                try:
                    raw_name = normalized.get("permittee_raw_name")
                    resolved_company_id = None
                    if raw_name:
                        cid, _conf, _method = await resolve_company(
                            session, raw_name, source=self.source_id,
                        )
                        resolved_company_id = cid
                    normalized["resolved_company_id"] = resolved_company_id

                    stmt = pg_insert(GeneratorPermit).values(**normalized)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["source", "source_permit_id"],
                        set_={
                            "facility_name": stmt.excluded.facility_name,
                            "permittee_raw_name": stmt.excluded.permittee_raw_name,
                            "resolved_company_id": stmt.excluded.resolved_company_id,
                            "permit_status": stmt.excluded.permit_status,
                            "issued_date": stmt.excluded.issued_date,
                            "raw_payload": stmt.excluded.raw_payload,
                            "updated_at": datetime.utcnow(),
                        },
                    )
                    await session.execute(stmt)
                    records_stored += 1
                except Exception as exc:
                    logger.error(
                        "tceq.upsert_error",
                        extra={
                            "permit": normalized.get("source_permit_id"),
                            "error_class": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                    records_skipped += 1
                    errors.append({
                        "permit": normalized.get("source_permit_id"),
                        "error": str(exc),
                    })

            await self._write_coverage(session, records_stored)
            await self._write_lineage(session, run_record.id, records_stored)

            run_record.status = "success" if records_stored > 0 else (
                "partial_failure" if errors else "success"
            )
            run_record.completed_at = datetime.utcnow()
            run_record.records_fetched = records_fetched
            run_record.records_stored = records_stored
            run_record.records_skipped = records_skipped
            run_record.error_log = {"errors": errors[:50]} if errors else None
            await session.flush()

        except Exception as exc:
            run_record.status = "failure"
            run_record.completed_at = datetime.utcnow()
            run_record.error_log = {"fatal": str(exc)}
            await session.flush()
            logger.error(
                "tceq.run_fatal_error",
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
        stmt = pg_insert(DataCoverage).values(
            pillar=self.pillar,
            state_code=self.coverage_scope,
            source=self.source_id,
            coverage_status=self.declared_status,
            record_count=record_count,
            last_ingested_at=datetime.utcnow(),
            freshness_sla_hours=336,
            notes="TCEQ NSR pending air-permit applications -- data-center filtered",
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

    async def _write_lineage(
        self, session: AsyncSession, run_id: int, record_count: int
    ) -> None:
        if record_count <= 0:
            return
        stmt = pg_insert(DataLineage).values(
            table_name="generator_permits",
            record_id=run_id,
            ingestion_run_id=run_id,
            source_url=_TCEQ_NSR_URL,
            retrieved_at=datetime.utcnow(),
            parser_version=self.adapter_version,
            confidence=0.65,
            transformation={"method": "tceq_nsr_html_table"},
        )
        await session.execute(stmt)
