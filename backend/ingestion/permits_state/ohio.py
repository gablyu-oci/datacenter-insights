"""
Ohio state permit / building data adapter — Phase 2 (AC9).

Ohio publishes permit + facility data via the Ohio EPA eBusiness portal
(no public REST) and via county / city open-data portals (most use
Socrata or CKAN). We hit the OPSB (Ohio Power Siting Board) Socrata
dataset by default; override via OHIO_SODA_RESOURCE env var.

Mirrors va_open_data.VaOpenDataAdapter shape: SODA fetch → filter →
normalize → upsert into generator_permits.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, date

import httpx
import stamina
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import (
    DataCoverage, DataLineage, GeneratorPermit, IngestionRun,
)

logger = logging.getLogger(__name__)

_DEFAULT_SODA_RESOURCE = "vmnd-r35z"  # Ohio OPSB cases (placeholder Socrata 4-4)
_OHIO_SODA_RESOURCE = os.environ.get("OHIO_SODA_RESOURCE", _DEFAULT_SODA_RESOURCE)
_OHIO_SODA_BASE = os.environ.get(
    "OHIO_SODA_BASE", "https://data.ohio.gov/resource"
)
_PAGE_SIZE = 1000

_DC_KEYWORDS = re.compile(
    r"data\s*center|hyperscale|cloud|colocation|colo|"
    r"microsoft|google|amazon|meta|oracle|"
    r"digital\s*realty|equinix|cologix|qts|cyrusone",
    re.I,
)


class OhioPermitAdapter:
    adapter_name = "Ohio Open Data Permits"
    adapter_id = "ohio_open_data"
    adapter_version = "1.0.0"
    pillar = "building_permits"
    source_id = "ohio_open_data"
    declared_status = "partial"
    coverage_scope = "OH"

    def __init__(self, resource_id: str | None = None) -> None:
        self._resource_id = resource_id or _OHIO_SODA_RESOURCE
        self._url = f"{_OHIO_SODA_BASE}/{self._resource_id}.json"
        self._semaphore = asyncio.Semaphore(2)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {
                "User-Agent": "strategic-insights-tool/1.0 (research)",
                "Accept": "application/json",
            }
            token = os.environ.get("SOCRATA_APP_TOKEN")
            if token:
                headers["X-App-Token"] = token
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=60.0, write=10.0, pool=15.0),
                follow_redirects=True,
                headers=headers,
            )
        return self._client

    @stamina.retry(on=httpx.TransportError, attempts=3, wait_initial=2.0)
    async def _fetch_page(self, offset: int) -> list[dict]:
        async with self._semaphore:
            await asyncio.sleep(0.3)
            client = await self._get_client()
            params = {
                "$limit": _PAGE_SIZE,
                "$offset": offset,
                "$q": "data center",
            }
            resp = await client.get(self._url, params=params)
            if resp.status_code == 404:
                logger.warning("ohio_open_data.resource_not_found id=%s", self._resource_id)
                return []
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

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
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                return datetime.strptime(s[:23] if "f" in fmt else s[:19], fmt).date()
            except ValueError:
                continue
        return None

    def _is_relevant(self, rec: dict) -> bool:
        text_blob = " ".join(str(v) for v in rec.values() if v is not None)
        if _DC_KEYWORDS.search(text_blob):
            return True
        for k in ("capacity_mw", "nameplate_mw", "rated_capacity_mw",
                  "mw_capacity", "mw"):
            mw = self._to_float(rec.get(k))
            if mw is not None and mw >= 50.0:
                return True
        return False

    def _normalize_record(self, rec: dict) -> dict | None:
        permit_id = (
            rec.get("case_number") or rec.get("permit_number")
            or rec.get("application_number") or rec.get("docket")
            or rec.get("project_id") or rec.get("id")
        )
        if not permit_id:
            return None
        permittee = (
            rec.get("applicant") or rec.get("company") or rec.get("owner")
            or rec.get("operator") or rec.get("petitioner") or ""
        )
        mw = (
            self._to_float(rec.get("capacity_mw"))
            or self._to_float(rec.get("nameplate_mw"))
            or self._to_float(rec.get("mw_capacity"))
            or self._to_float(rec.get("mw"))
        )
        fuel = rec.get("fuel_type") or rec.get("technology") or rec.get("type") or ""
        status = rec.get("case_status") or rec.get("status") or rec.get("permit_status") or "filed"
        application_date = self._to_date(
            rec.get("filing_date") or rec.get("filed_date")
            or rec.get("application_date")
        )
        effective_date = self._to_date(
            rec.get("decision_date") or rec.get("issued_date")
            or rec.get("effective_date")
        )
        return {
            "source": self.source_id,
            "source_permit_id": f"OH-{str(permit_id).strip()}",
            "facility_name": str(rec.get("project_name") or rec.get("facility_name") or "").strip() or None,
            "permittee_raw_name": str(permittee).strip() or None,
            "state_code": "OH",
            "rated_mw_total": mw,
            "fuel_type": str(fuel).strip()[:100] if fuel else None,
            "permit_status": str(status).strip()[:100],
            "issued_date": application_date,
            "expiry_date": effective_date,
            "confidence": 0.60,
            "raw_payload": rec,
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
            offset = 0
            all_rows: list[dict] = []
            for _page in range(20):
                try:
                    page = await self._fetch_page(offset)
                except httpx.HTTPStatusError as exc:
                    logger.error("ohio_open_data.fetch_http_error: %s",
                                 exc.response.status_code)
                    break
                except httpx.TransportError as exc:
                    logger.error("ohio_open_data.fetch_transport_error: %s", exc)
                    break
                if not page:
                    break
                all_rows.extend(page)
                if len(page) < _PAGE_SIZE:
                    break
                offset += _PAGE_SIZE
            records_fetched = len(all_rows)

            relevant = [r for r in all_rows if self._is_relevant(r)]
            logger.info("ohio_open_data.relevant_filtered total=%d relevant=%d",
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
                    logger.error("ohio_open_data.upsert_error pid=%s err=%s",
                                 norm.get("source_permit_id"), exc)
                    records_skipped += 1
                    errors.append({"pid": norm.get("source_permit_id"), "error": str(exc)})

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
            logger.error("ohio_open_data.run_fatal_error: %s", exc)
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

    async def _write_coverage(self, session: AsyncSession, n: int) -> None:
        stmt = pg_insert(DataCoverage).values(
            pillar=self.pillar, state_code="OH", source=self.source_id,
            coverage_status=self.declared_status, record_count=n,
            last_ingested_at=datetime.utcnow(), freshness_sla_hours=168,
            notes="Ohio Open Data (Socrata SODA) -- DC-relevant permits",
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
            confidence=0.60,
            transformation={"method": "ohio_socrata_soda"},
        )
        await session.execute(stmt)
