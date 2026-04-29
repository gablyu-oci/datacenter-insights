"""
Virginia Open Data Adapter -- CKAN datastore_search ingestion.

Phase 1.5 fix (2026-04-29):
  data.virginia.gov migrated from Socrata to CKAN in 2023. The old 4-4
  dataset IDs (e.g. bre9-aqqr) and /resource/<id>.json endpoints no longer
  resolve. Resources are now UUIDs and queried via CKAN's
  datastore_search action.

We query the Lynchburg Building Permits resource
(c7f42b70-8b91-4a4a-94ce-6958a729bd62) with q="data center" and persist all
matching rows to generator_permits.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, date

import httpx
import stamina
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
_PAGE_SIZE = 200

# CKAN datastore_search endpoint
_CKAN_BASE = "https://data.virginia.gov/api/3/action/datastore_search"

# Curated CKAN resources to scan. Add additional UUIDs here as they become
# available; one working resource is sufficient for landing rows.
_VA_CKAN_RESOURCES: list[dict] = [
    {
        "name": "Lynchburg Building Permits",
        "resource_id": "c7f42b70-8b91-4a4a-94ce-6958a729bd62",
        "query": "data center",
    },
]


class VaOpenDataAdapter:
    """
    Virginia open-data permit adapter.

    Fetches CKAN datastore_search results for each configured resource,
    normalizes records to the GeneratorPermit shape, and upserts.
    """

    adapter_name = "Virginia Open Data"
    adapter_id = "va_open_data"
    adapter_version = "2.0.0"
    pillar = "building_permits"
    source_id = "va_open_data"
    declared_status = "partial"
    coverage_scope = "VA"

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
                    "Accept": "application/json, */*",
                },
            )
        return self._client

    @stamina.retry(on=httpx.TransportError, attempts=3, wait_initial=1.5)
    async def _ckan_search(
        self, resource_id: str, *, q: str, limit: int, offset: int,
    ) -> dict:
        async with self._semaphore:
            await asyncio.sleep(0.3)
            client = await self._get_client()
            params = {
                "resource_id": resource_id,
                "limit": str(limit),
                "offset": str(offset),
            }
            if q:
                params["q"] = q
            resp = await client.get(_CKAN_BASE, params=params)
            resp.raise_for_status()
            return resp.json()

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # CKAN fetch
    # ------------------------------------------------------------------

    async def _fetch_resource(self, cfg: dict) -> list[dict]:
        """Page through a single CKAN resource, returning every record."""
        all_records: list[dict] = []
        offset = 0
        max_pages = 20

        for _ in range(max_pages):
            try:
                payload = await self._ckan_search(
                    cfg["resource_id"], q=cfg.get("query", ""),
                    limit=_PAGE_SIZE, offset=offset,
                )
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "va_open_data.ckan_http_error",
                    extra={
                        "resource": cfg["name"],
                        "status": exc.response.status_code,
                        "offset": offset,
                    },
                )
                break
            except (httpx.TransportError, httpx.RequestError) as exc:
                logger.warning(
                    "va_open_data.ckan_transport_error",
                    extra={"resource": cfg["name"], "error": str(exc)},
                )
                break

            if not payload.get("success"):
                logger.warning(
                    "va_open_data.ckan_unsuccessful",
                    extra={"resource": cfg["name"], "payload_keys": list(payload.keys())},
                )
                break

            result = payload.get("result", {})
            records = result.get("records", [])
            if not records:
                break
            all_records.extend(records)

            if len(records) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

        return all_records

    # ------------------------------------------------------------------
    # Normalize
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date(value) -> date | None:
        if not value:
            return None
        s = str(value).strip()
        if not s:
            return None
        # CKAN/TRAKiT format: "2008/04/25 00:00:00+00"
        for fmt in ("%Y/%m/%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(s.split("+")[0].strip(), fmt.replace("%z", "")).date()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _to_float(value) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(str(value).replace(",", ""))
        except (ValueError, TypeError):
            return None

    def _normalize_record(self, record: dict, resource_name: str) -> dict | None:
        # Lynchburg TRAKiT uses RecordNo as the permit ID. Generic fallbacks
        # accommodate other Virginia CKAN resources we add later.
        permit_id = (
            record.get("RecordNo")
            or record.get("permit_number")
            or record.get("permit_id")
            or record.get("PermitNumber")
            or record.get("record_id")
            or str(record.get("_id", "")) if record.get("_id") else None
        )
        if not permit_id:
            return None

        facility_name = (
            record.get("Name")
            or record.get("project_name")
            or record.get("facility_name")
            or record.get("description")
            or record.get("permit_type")
        )
        permittee = (
            record.get("Owner_TRAKiT")
            or record.get("applicant_name")
            or record.get("owner_name")
            or record.get("contractor_name")
            or record.get("permittee")
        )

        permit_type_field = record.get("Type") or record.get("permit_type") or ""
        sub_type = record.get("SubType") or ""
        description = (
            record.get("description")
            or (f"{permit_type_field} / {sub_type}".strip(" /") or None)
        )

        issued_date = self._parse_date(
            record.get("StartDate")
            or record.get("issue_date")
            or record.get("issued_date")
            or record.get("permit_date")
        )

        return {
            "source": self.source_id,
            "source_permit_id": str(permit_id)[:255],
            "facility_name": str(facility_name)[:500] if facility_name else description,
            "permittee_raw_name": str(permittee) if permittee else None,
            "state_code": "VA",
            "permit_status": str(record.get("Status") or "issued")[:100],
            "issued_date": issued_date,
            "naics_code": str(record.get("naics_code"))[:50] if record.get("naics_code") else None,
            "confidence": 0.70,
            "raw_payload": {**record, "_resource": resource_name},
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
            for cfg in _VA_CKAN_RESOURCES:
                try:
                    raw_records = await self._fetch_resource(cfg)
                    records_fetched += len(raw_records)
                    logger.info(
                        "va_open_data.resource_fetched",
                        extra={"resource": cfg["name"], "count": len(raw_records)},
                    )

                    for rec in raw_records:
                        normalized = self._normalize_record(rec, cfg["name"])
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
                                "va_open_data.upsert_error",
                                extra={
                                    "permit_id": normalized.get("source_permit_id"),
                                    "error_class": type(exc).__name__,
                                    "error": str(exc),
                                },
                            )
                            records_skipped += 1

                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "va_open_data.resource_error",
                        extra={"resource": cfg["name"], "status": exc.response.status_code},
                    )
                    errors.append({"resource": cfg["name"], "error": str(exc)})
                except (httpx.TransportError, httpx.RequestError) as exc:
                    logger.error(
                        "va_open_data.resource_transport_error",
                        extra={"resource": cfg["name"], "error": str(exc)},
                    )
                    errors.append({"resource": cfg["name"], "error": str(exc)})

            await self._write_coverage(session, records_stored)
            await self._write_lineage(session, run_record.id, records_stored)

            run_record.status = "success" if records_stored > 0 else (
                "partial_failure" if errors else "success"
            )
            run_record.completed_at = datetime.utcnow()
            run_record.records_fetched = records_fetched
            run_record.records_stored = records_stored
            run_record.records_skipped = records_skipped
            run_record.error_log = {"errors": errors} if errors else None
            await session.flush()

        except Exception as exc:
            run_record.status = "failure"
            run_record.completed_at = datetime.utcnow()
            run_record.error_log = {"fatal": str(exc)}
            await session.flush()
            logger.error(
                "va_open_data.run_fatal_error",
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
            freshness_sla_hours=168,
            notes="Virginia CKAN open-data permits (Lynchburg + others)",
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
            source_url=_CKAN_BASE,
            retrieved_at=datetime.utcnow(),
            parser_version=self.adapter_version,
            confidence=0.70,
            transformation={"method": "va_ckan_datastore_search"},
        )
        await session.execute(stmt)
