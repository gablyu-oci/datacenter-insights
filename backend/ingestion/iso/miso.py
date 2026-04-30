"""
MISO ISO Generator Interconnection Queue Adapter — Phase 2 (AC8).

MISO publishes its Generator Interconnection Queue as a CDN-hosted XLSX
linked from the GI_Queue landing page. The CDN filename is regenerated
on each refresh, so we scrape the landing page for the current
``cdn.misoenergy.org/.../GI%20Queue*.xlsx`` href and download it.

Override behaviour:
  * MISO_QUEUE_URL  -- pin a specific xlsx URL (skip the scrape).
  * MISO_LANDING_URL -- override the page we scrape (default below).

This adapter mirrors the PJM XML adapter shape: filter for DC-relevant
entries (>= 100 MW OR keyword match), normalize into generator_permits,
upsert by (source, source_permit_id).
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
from datetime import date, datetime

import httpx
import stamina
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import (
    DataCoverage, DataLineage, GeneratorPermit, IngestionRun,
)

logger = logging.getLogger(__name__)

MISO_LANDING_URL = os.environ.get(
    "MISO_LANDING_URL",
    "https://www.misoenergy.org/planning/resource-utilization/GI_Queue/",
)
MISO_QUEUE_URL = os.environ.get("MISO_QUEUE_URL")  # optional pin
# Match cdn.misoenergy.org links to GI Queue xlsx files
_MISO_XLSX_HREF_RE = re.compile(
    r'href=["\']([^"\']*cdn\.misoenergy\.org/[^"\']*GI[^"\']*\.xlsx)["\']',
    re.I,
)

MISO_STATES = frozenset([
    # MISO Midwest + South footprint
    "IL", "IN", "IA", "MI", "MN", "MO", "MT", "ND", "SD", "WI",
    "AR", "LA", "MS", "TX",  # MISO South partial
    "KY",
])

_DC_KEYWORDS = re.compile(
    r"data\s*center|hyperscale|cloud|colocation|colo|"
    r"microsoft|google|amazon|meta|oracle|"
    r"digital\s*realty|equinix|qts|crusoe|aligned|stack|compass",
    re.I,
)
_MIN_MW = 10.0


class MisoIsoAdapter:
    adapter_name = "MISO Generator Interconnection Queue"
    adapter_id = "miso_iso"
    adapter_version = "1.0.0"
    pillar = "iso_queues"
    source_id = "miso"
    declared_status = "partial"
    coverage_scope_states = MISO_STATES

    def __init__(self, url: str | None = None) -> None:
        self._url = url or MISO_QUEUE_URL  # may be None — scrape lookup
        self._landing_url = MISO_LANDING_URL
        self._semaphore = asyncio.Semaphore(2)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=120.0, write=10.0, pool=15.0),
                follow_redirects=True,
                headers={
                    "User-Agent": "strategic-insights-tool/1.0 (research)",
                    "Accept": "application/json, text/plain, */*",
                },
            )
        return self._client

    @stamina.retry(on=httpx.TransportError, attempts=3, wait_initial=2.0)
    async def _resolve_xlsx_url(self) -> str | None:
        """Scrape the GI_Queue landing page for the current
        cdn.misoenergy.org/.../GI Queue*.xlsx href.
        """
        async with self._semaphore:
            await asyncio.sleep(0.5)
            client = await self._get_client()
            resp = await client.get(self._landing_url)
            resp.raise_for_status()
            html = resp.text
        m = _MISO_XLSX_HREF_RE.search(html)
        if not m:
            logger.warning("miso_iso.no_xlsx_link_on_landing url=%s",
                           self._landing_url)
            return None
        url = m.group(1)
        if url.startswith("//"):
            url = "https:" + url
        logger.info("miso_iso.resolved_xlsx_url=%s", url)
        return url

    @stamina.retry(on=httpx.TransportError, attempts=3, wait_initial=2.0)
    async def _fetch_xlsx(self) -> bytes:
        url = self._url or await self._resolve_xlsx_url()
        if not url:
            return b""
        self._url = url  # cache for lineage
        async with self._semaphore:
            await asyncio.sleep(0.5)
            client = await self._get_client()
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content

    def _parse_xlsx(self, blob: bytes) -> list[dict]:
        if not blob:
            return []
        try:
            import openpyxl
        except ImportError:
            logger.error("miso_iso.openpyxl_missing")
            return []
        try:
            wb = openpyxl.load_workbook(io.BytesIO(blob), data_only=True, read_only=True)
        except Exception as exc:
            logger.error("miso_iso.xlsx_parse_error: %s", exc)
            return []
        rows: list[dict] = []
        # MISO's GI Queue workbook usually has a "Projects" sheet (or named
        # "PROJECTS"); fall back to first sheet.
        sheet = None
        for name in wb.sheetnames:
            if "project" in name.lower() or "queue" in name.lower():
                sheet = name
                break
        if sheet is None and wb.sheetnames:
            sheet = wb.sheetnames[0]
        if sheet is None:
            return []
        ws = wb[sheet]
        it = ws.iter_rows(values_only=True)
        try:
            header = [str(c).strip() if c is not None else "" for c in next(it)]
        except StopIteration:
            return []
        for row in it:
            if not row or all(c is None for c in row):
                continue
            rec = dict(zip(header, row))
            rows.append(rec)
        return rows

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _to_float(value) -> float | None:
        if value is None:
            return None
        try:
            return float(str(value).replace(",", ""))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _to_date(value) -> date | None:
        if not value:
            return None
        s = str(value).strip()
        if not s or s.upper() in {"N/A", "NA", "NULL"}:
            return None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S.%fZ"):
            try:
                return datetime.strptime(s[:23], fmt[:23] if "f" in fmt else fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _get_first(rec: dict, *keys) -> object:
        for k in keys:
            if k in rec and rec[k] is not None and str(rec[k]).strip():
                return rec[k]
        # Case-insensitive fallback
        lower = {str(k).lower(): v for k, v in rec.items()}
        for k in keys:
            v = lower.get(str(k).lower())
            if v is not None and str(v).strip():
                return v
        return None

    def _extract_mw(self, rec: dict) -> float | None:
        for key in (
            "Summer MW", "Summer Capacity (MW)", "Winter MW", "Capacity (MW)",
            "MW", "Net Capacity (MW)", "Nameplate (MW)",
        ):
            v = self._get_first(rec, key)
            mw = self._to_float(v)
            if mw is not None and mw > 0:
                return mw
        return None

    def _is_relevant(self, rec: dict) -> bool:
        mw = self._extract_mw(rec)
        text_blob = " ".join(
            str(v) for v in rec.values() if v is not None
        )
        if _DC_KEYWORDS.search(text_blob):
            return True
        if mw is not None and mw >= 100.0:
            return True
        return False

    def _normalize_record(self, rec: dict) -> dict | None:
        proj = self._get_first(
            rec, "Project #", "Queue Position", "Project Number",
            "QueueProjectNumber", "ProjectNumber",
        )
        if not proj:
            return None
        permittee = self._get_first(
            rec, "Interconnection Customer", "InterconnCustomer",
            "Customer", "Developer", "Project Name",
        ) or ""
        mw = self._extract_mw(rec)
        state = self._get_first(rec, "State", "State/Province", "ST")
        if state and len(str(state)) > 2:
            state = str(state)[:2].upper()
        fuel = self._get_first(rec, "Fuel Type", "Fuel", "Type", "Generation Type") or ""
        status = self._get_first(
            rec, "Studies Phase", "GIM Phase", "Project Status",
            "Status", "Withdrawn Date",
        ) or "queued"
        application_date = self._to_date(self._get_first(
            rec, "Queue Date", "Request Date", "Application Date",
            "Initial Submit Date",
        ))
        effective_date = self._to_date(self._get_first(
            rec, "Commercial Operation Date", "In-Service Date",
            "Projected COD", "InServiceDate",
        ))
        # Excel's date cells deserialize to datetime objects; convert.
        rec_clean = {
            str(k): (v.isoformat() if isinstance(v, (date, datetime)) else v)
            for k, v in rec.items()
        }
        return {
            "source": self.source_id,
            "source_permit_id": f"MISO-{str(proj).strip()}",
            "facility_name": str(self._get_first(rec, "Project Name") or "").strip() or None,
            "permittee_raw_name": str(permittee).strip() or None,
            "state_code": state,
            "rated_mw_total": mw,
            "fuel_type": str(fuel).strip()[:100] if fuel else None,
            "permit_status": str(status).strip()[:100],
            "issued_date": application_date,
            "expiry_date": effective_date,
            "confidence": 0.65,
            "raw_payload": rec_clean,
        }

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
                blob = await self._fetch_xlsx()
            except httpx.HTTPStatusError as exc:
                logger.error("miso_iso.fetch_http_error: %s", exc.response.status_code)
                blob = b""
            except httpx.TransportError as exc:
                logger.error("miso_iso.fetch_transport_error: %s", exc)
                blob = b""

            raw = self._parse_xlsx(blob) if blob else []
            records_fetched = len(raw)
            relevant = [r for r in raw if self._is_relevant(r)]
            logger.info("miso_iso.relevant_filtered total=%d relevant=%d",
                        records_fetched, len(relevant))

            for entry in relevant:
                norm = self._normalize_record(entry)
                if not norm:
                    records_skipped += 1
                    continue
                try:
                    stmt = pg_insert(GeneratorPermit).values(**norm)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["source", "source_permit_id"],
                        set_={
                            "facility_name": stmt.excluded.facility_name,
                            "permittee_raw_name": stmt.excluded.permittee_raw_name,
                            "state_code": stmt.excluded.state_code,
                            "rated_mw_total": stmt.excluded.rated_mw_total,
                            "fuel_type": stmt.excluded.fuel_type,
                            "permit_status": stmt.excluded.permit_status,
                            "issued_date": stmt.excluded.issued_date,
                            "expiry_date": stmt.excluded.expiry_date,
                            "raw_payload": stmt.excluded.raw_payload,
                            "updated_at": datetime.utcnow(),
                        },
                    )
                    await session.execute(stmt)
                    records_stored += 1
                except Exception as exc:
                    logger.error("miso_iso.upsert_error proj=%s err=%s",
                                 norm.get("source_permit_id"), exc)
                    records_skipped += 1
                    errors.append({"proj": norm.get("source_permit_id"), "error": str(exc)})

            await self._write_coverage(session, records_stored)
            await self._write_lineage(session, run_record.id, records_stored)

            run_record.status = "success" if records_stored or not errors else "partial_failure"
            run_record.completed_at = datetime.utcnow()
            run_record.records_fetched = records_fetched
            run_record.records_stored = records_stored
            run_record.records_skipped = records_skipped
            run_record.records_normalized = len(relevant)
            run_record.error_log = {"errors": errors[:50]} if errors else None
            await session.flush()
        except Exception as exc:
            run_record.status = "failure"
            run_record.completed_at = datetime.utcnow()
            run_record.error_log = {"fatal": str(exc)}
            await session.flush()
            logger.error("miso_iso.run_fatal_error: %s", exc)
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
        for state in MISO_STATES:
            stmt = pg_insert(DataCoverage).values(
                pillar=self.pillar,
                state_code=state,
                source=self.source_id,
                coverage_status=self.declared_status,
                record_count=record_count,
                last_ingested_at=datetime.utcnow(),
                freshness_sla_hours=168,
                notes="MISO Generator Interconnection Queue (JSON) -- DC-relevant",
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

    async def _write_lineage(self, session: AsyncSession, run_id: int, n: int) -> None:
        if n <= 0:
            return
        stmt = pg_insert(DataLineage).values(
            table_name="generator_permits",
            record_id=run_id,
            ingestion_run_id=run_id,
            source_url=self._url,
            retrieved_at=datetime.utcnow(),
            parser_version=self.adapter_version,
            confidence=0.65,
            transformation={"method": "miso_giqueue_xlsx_scrape"},
        )
        await session.execute(stmt)
