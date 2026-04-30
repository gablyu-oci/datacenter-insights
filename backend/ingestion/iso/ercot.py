"""
ERCOT ISO Generator Interconnection Status (GIS) Report Adapter — Phase 2 (AC8).

ERCOT publishes a monthly GIS Report as an Excel workbook at a stable
public URL pattern. The report contains every active GINR (Generator
Interconnection or Change Request) project; relevant sheets include:

    "Project Details - Large Gen"
    "Project Details - Small Gen"

Each row carries a Project Code (INR), Capacity (MW), Fuel, County,
Interconnecting Entity (the LLC), POI Location, and Status.

Public URL: https://www.ercot.com/files/docs/<YYYY>/<MM>/<DD>/GIS_Report.xlsx
The report file is uploaded on a rolling basis. We allow the URL to be
overridden via `ERCOT_GIS_URL` env var so ops can pin a specific snapshot.

This adapter mirrors the PJM XML adapter shape: filter for DC-relevant
entries (>= 50 MW OR keyword match), normalize into generator_permits,
upsert by (source, source_permit_id).
"""
from __future__ import annotations

import asyncio
import io
import json
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

# ERCOT publishes the GIS Report as a sequence of versioned XLSX files
# referenced from a JSON listing (reportTypeId=15933 == GIS Report). We
# resolve the latest doclookupId at runtime via that listing, then download
# the file via misdownload?doclookupId=<id>. Override with ERCOT_GIS_URL to
# pin a specific file.
_ERCOT_LISTING_URL = (
    "https://www.ercot.com/misapp/servlets/IceDocListJsonWS?reportTypeId=15933"
)
_ERCOT_DOWNLOAD_URL = "https://www.ercot.com/misdownload/servlets/mirDownload"
ERCOT_GIS_URL = os.environ.get("ERCOT_GIS_URL")  # optional pin

ERCOT_STATES = frozenset(["TX"])

_DC_KEYWORDS = re.compile(
    r"data\s*center|hyperscale|cloud|colocation|colo|"
    r"microsoft|google|amazon|meta|oracle|"
    r"crusoe|aligned|stack|compass|lancium|riot|core\s*scientific",
    re.I,
)
_MIN_MW = 10.0


class ErcotIsoAdapter:
    adapter_name = "ERCOT GIS Report"
    adapter_id = "ercot_iso"
    adapter_version = "1.0.0"
    pillar = "iso_queues"
    source_id = "ercot"
    declared_status = "partial"
    coverage_scope_states = ERCOT_STATES

    def __init__(self, url: str | None = None) -> None:
        # url, if provided (or via ERCOT_GIS_URL env), pins a specific XLSX;
        # otherwise we resolve the latest via the JSON listing.
        self._url = url or ERCOT_GIS_URL  # may be None — runtime resolution
        self._semaphore = asyncio.Semaphore(2)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=180.0, write=10.0, pool=15.0),
                follow_redirects=True,
                headers={
                    "User-Agent": "strategic-insights-tool/1.0 (research)",
                    "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                },
            )
        return self._client

    @stamina.retry(on=httpx.TransportError, attempts=3, wait_initial=2.0)
    async def _resolve_latest_xlsx_url(self) -> str | None:
        """Hit the ERCOT MIS listing JSON and return a download URL for the
        most-recent GIS_Report*.xlsx entry.
        """
        async with self._semaphore:
            await asyncio.sleep(0.5)
            client = await self._get_client()
            resp = await client.get(_ERCOT_LISTING_URL)
            resp.raise_for_status()
            try:
                payload = resp.json()
            except json.JSONDecodeError:
                logger.error("ercot_iso.listing_json_decode_failed")
                return None
        # The listing is a list of dicts with FriendlyName and DocID fields.
        items = payload if isinstance(payload, list) else payload.get("ListDocsByRptTypeRes", {}).get("DocumentList", [])
        if isinstance(items, dict):
            items = items.get("Document", [])
        if not isinstance(items, list):
            return None
        # Filter to xlsx entries, prefer the latest by PublishDate.
        xlsx_items = []
        for it in items:
            if not isinstance(it, dict):
                continue
            doc = it.get("Document", it)  # nested or flat
            name = (doc.get("FriendlyName") or doc.get("ConstructedName")
                    or doc.get("Name") or "")
            if ".xlsx" not in str(name).lower():
                continue
            doc_id = (doc.get("DocID") or doc.get("DocId")
                      or doc.get("doclookupId") or doc.get("DocLookupId"))
            pub = doc.get("PublishDate") or doc.get("EffectiveDate") or ""
            if doc_id:
                xlsx_items.append((str(pub), str(doc_id), str(name)))
        if not xlsx_items:
            return None
        xlsx_items.sort(reverse=True)
        _pub, doc_id, name = xlsx_items[0]
        logger.info("ercot_iso.resolved_doc id=%s name=%s pub=%s",
                    doc_id, name, _pub)
        return f"{_ERCOT_DOWNLOAD_URL}?doclookupId={doc_id}"

    @stamina.retry(on=httpx.TransportError, attempts=3, wait_initial=2.0)
    async def _fetch_xlsx(self) -> bytes:
        # Resolve URL each call so the adapter follows ERCOT's monthly rotation.
        url = self._url or await self._resolve_latest_xlsx_url()
        if not url:
            return b""
        # Cache for lineage logging
        self._url = url
        async with self._semaphore:
            await asyncio.sleep(0.5)
            client = await self._get_client()
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Excel parse
    # ------------------------------------------------------------------

    def _parse_xlsx(self, blob: bytes) -> list[dict]:
        try:
            import openpyxl  # local import — large module
        except ImportError:
            logger.error("ercot_iso.openpyxl_missing")
            return []

        try:
            wb = openpyxl.load_workbook(io.BytesIO(blob), data_only=True, read_only=True)
        except Exception as exc:
            logger.error("ercot_iso.xlsx_parse_error: %s", exc)
            return []

        rows: list[dict] = []
        for sheet_name in wb.sheetnames:
            if "Project Details" not in sheet_name:
                continue
            ws = wb[sheet_name]
            it = ws.iter_rows(values_only=True)
            try:
                header = [str(c).strip() if c is not None else "" for c in next(it)]
            except StopIteration:
                continue
            for row in it:
                if not row or all(c is None for c in row):
                    continue
                rec = dict(zip(header, row))
                rec["__sheet"] = sheet_name
                rows.append(rec)
        return rows

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
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        s = str(value).strip()
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
            try:
                return datetime.strptime(s[:10], fmt).date()
            except ValueError:
                continue
        return None

    def _extract_mw(self, rec: dict) -> float | None:
        for k in (
            "Capacity (MW)", "Capacity", "Total Capacity (MW)",
            "Summer Capacity (MW)", "Net Cap (MW)", "MW",
        ):
            mw = self._to_float(rec.get(k))
            if mw is not None and mw > 0:
                return mw
        return None

    def _is_relevant(self, rec: dict) -> bool:
        mw = self._extract_mw(rec)
        text_blob = " ".join(
            str(rec.get(k, "") or "")
            for k in ("Unit Code", "Project Code", "Interconnecting Entity",
                      "County", "POI Location", "Fuel")
        )
        if _DC_KEYWORDS.search(text_blob):
            return True
        if mw is not None and mw >= 100.0:
            return True
        return False

    def _normalize_record(self, rec: dict) -> dict | None:
        inr = rec.get("INR") or rec.get("Project Code") or rec.get("Unit Code")
        if not inr:
            return None
        permittee = (
            rec.get("Interconnecting Entity")
            or rec.get("Resource Entity")
            or rec.get("Owner")
            or ""
        )
        mw = self._extract_mw(rec)
        fuel = rec.get("Fuel") or rec.get("Technology") or ""
        status = rec.get("GIM Study Phase") or rec.get("Status") or "queued"
        application_date = self._to_date(rec.get("Screening Study Started")) or self._to_date(
            rec.get("Date First Submitted")
        )
        effective_date = self._to_date(rec.get("Approved for Energization")) or self._to_date(
            rec.get("Projected COD")
        )
        return {
            "source": self.source_id,
            "source_permit_id": f"ERCOT-{str(inr).strip()}",
            "facility_name": str(rec.get("Project Name") or rec.get("Unit Code") or "").strip() or None,
            "permittee_raw_name": str(permittee).strip() or None,
            "state_code": "TX",
            "rated_mw_total": mw,
            "fuel_type": str(fuel).strip()[:100] if fuel else None,
            "permit_status": str(status).strip()[:100],
            "issued_date": application_date,
            "expiry_date": effective_date,
            "confidence": 0.65,
            "raw_payload": {k: (v.isoformat() if isinstance(v, (date, datetime)) else v)
                            for k, v in rec.items() if k != "__sheet"},
        }

    # ------------------------------------------------------------------
    # Run
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
                blob = await self._fetch_xlsx()
            except httpx.HTTPStatusError as exc:
                logger.error("ercot_iso.fetch_http_error: %s url=%s",
                             exc.response.status_code, self._url)
                blob = b""
            except httpx.TransportError as exc:
                logger.error("ercot_iso.fetch_transport_error: %s", exc)
                blob = b""

            raw = self._parse_xlsx(blob) if blob else []
            records_fetched = len(raw)
            relevant = [r for r in raw if self._is_relevant(r)]
            logger.info("ercot_iso.relevant_filtered total=%d relevant=%d",
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
                    logger.error("ercot_iso.upsert_error inr=%s err=%s",
                                 norm.get("source_permit_id"), exc)
                    records_skipped += 1
                    errors.append({"inr": norm.get("source_permit_id"), "error": str(exc)})

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
            logger.error("ercot_iso.run_fatal_error: %s", exc)
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
            state_code="TX",
            source=self.source_id,
            coverage_status=self.declared_status,
            record_count=record_count,
            last_ingested_at=datetime.utcnow(),
            freshness_sla_hours=720,  # monthly
            notes="ERCOT GIS Report (monthly XLSX) -- DC-relevant entries",
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
            transformation={"method": "ercot_gis_xlsx"},
        )
        await session.execute(stmt)
