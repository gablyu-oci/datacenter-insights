"""
Virginia Open Data Adapter -- building & generator permits from data.virginia.gov,
Loudoun County, and Prince William County open data portals.

NOTE: We reuse the generator_permits table for building permits as well.
The permit data shares the same structure (permit ID, facility, location,
permittee, dates) and the `source` column distinguishes the data origin.
A future migration may split building permits into a dedicated table if
the schema diverges significantly.

All three portals use the Socrata SODA API format:
  GET https://{domain}/resource/{dataset_id}.json?$where=...&$limit=1000

Dataset IDs below are best-effort; if a portal restructures its catalog the
adapter will log a warning and continue with the remaining datasets.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

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

# Proximity threshold for site matching (~100m)
_PROXIMITY_DEGREES = 0.001

# Virginia open data portals -- all use Socrata SODA API
# NOTE: dataset_id values are best-effort based on public catalog searches.
# If a dataset is removed or renamed, the adapter gracefully handles the 404.
_VA_DATASETS = [
    {
        "name": "Virginia State Permits",
        "domain": "data.virginia.gov",
        "dataset_id": "bre9-aqqr",  # Virginia building permits dataset
        "filter": "$where=naics_code LIKE '518%' OR description LIKE '%data center%'",
    },
    {
        "name": "Loudoun County Permits",
        "domain": "data.loudoun.gov",
        # Loudoun County is the #1 US datacenter market. Their open data portal
        # may use logis.loudoun.gov for GIS or data.loudoun.gov for Socrata.
        "dataset_id": "23yb-ergy",
        "filter": "$where=permit_type LIKE '%commercial%' OR description LIKE '%data center%'",
    },
    {
        "name": "Prince William County Permits",
        "domain": "data.pwcgov.org",
        "dataset_id": "nk4h-7vs9",
        "filter": "$where=category LIKE '%commercial%' OR description LIKE '%data center%'",
    },
]

_PAGE_SIZE = 1000


class VaOpenDataAdapter:
    """
    Virginia building/generator permit adapter.

    Fetches permits from three open data portals (state-level, Loudoun County,
    Prince William County) and upserts into generator_permits.
    Uses entity_resolution.resolve_company for permittee name resolution.
    """

    adapter_name = "Virginia Open Data"
    adapter_id = "va_open_data"
    adapter_version = "1.1.0"
    pillar = "building_permits"
    source_id = "va_open_data"
    declared_status = "full"
    coverage_scope = "VA"

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(4)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0),
                follow_redirects=True,
                headers={
                    "User-Agent": "DatacenterIntelPlatform/1.0 (research@oracle.com)",
                },
            )
        return self._client

    @stamina.retry(on=httpx.TransportError, attempts=3, wait_initial=1.5)
    async def _rate_limited_get(self, url: str, params: dict | None = None) -> list[dict]:
        """Fetch a page from a Socrata SODA endpoint."""
        async with self._semaphore:
            await asyncio.sleep(0.25)
            client = await self._get_client()
            resp = await client.get(url, params=params or {})
            resp.raise_for_status()
            return resp.json()

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _fetch_dataset(self, dataset_cfg: dict) -> list[dict]:
        """Paginate through a single Socrata dataset."""
        domain = dataset_cfg["domain"]
        dataset_id = dataset_cfg["dataset_id"]
        base_url = f"https://{domain}/resource/{dataset_id}.json"
        filter_clause = dataset_cfg.get("filter", "")

        all_records: list[dict] = []
        offset = 0
        max_pages = 20

        for _ in range(max_pages):
            params: dict[str, str] = {
                "$limit": str(_PAGE_SIZE),
                "$offset": str(offset),
            }
            if filter_clause and filter_clause.startswith("$where="):
                params["$where"] = filter_clause.replace("$where=", "", 1)

            try:
                records = await self._rate_limited_get(base_url, params)
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "va_open_data.fetch_error",
                    extra={
                        "dataset": dataset_cfg["name"],
                        "status": exc.response.status_code,
                        "offset": offset,
                    },
                )
                break

            if not records:
                break

            all_records.extend(records)
            if len(records) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

        return all_records

    def _normalize_record(self, record: dict, dataset_name: str) -> dict | None:
        """Convert a Socrata permit record into a GeneratorPermit-shaped dict."""
        # Try common field names across different Socrata portals
        permit_id = (
            record.get("permit_number")
            or record.get("permit_id")
            or record.get("permitnumber")
            or record.get("record_id")
        )
        if not permit_id:
            return None

        lat = record.get("latitude") or record.get("lat")
        lon = record.get("longitude") or record.get("lon") or record.get("long")

        try:
            lat_f = float(lat) if lat else None
        except (ValueError, TypeError):
            lat_f = None
        try:
            lon_f = float(lon) if lon else None
        except (ValueError, TypeError):
            lon_f = None

        # Parse dates -- Socrata often returns ISO-8601 with optional Z suffix
        issued_str = (
            record.get("issued_date")
            or record.get("issue_date")
            or record.get("permit_date")
        )
        issued_date = None
        if issued_str:
            try:
                issued_date = datetime.fromisoformat(
                    issued_str.replace("Z", "+00:00")
                ).date()
            except (ValueError, AttributeError):
                pass

        facility_name = (
            record.get("project_name")
            or record.get("facility_name")
            or record.get("description")
            or record.get("project_description")
        )
        permittee = (
            record.get("applicant_name")
            or record.get("owner_name")
            or record.get("contractor_name")
            or record.get("permittee")
        )

        # Source includes dataset name for traceability
        source_tag = f"{self.source_id}_{dataset_name.lower().replace(' ', '_')}"

        return {
            "source": source_tag,
            "source_permit_id": str(permit_id),
            "facility_name": facility_name,
            "permittee_raw_name": permittee,
            "state_code": "VA",
            "latitude": lat_f,
            "longitude": lon_f,
            "permit_status": record.get("status") or "issued",
            "issued_date": issued_date,
            "naics_code": record.get("naics_code"),
            "confidence": 0.75,
            "raw_payload": record,
        }

    async def _match_site(
        self, session: AsyncSession, lat: float, lon: float
    ) -> int | None:
        """Find a site within proximity."""
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
        """Fetch VA permits, normalize, upsert, match sites."""
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
            for dataset_cfg in _VA_DATASETS:
                try:
                    raw_records = await self._fetch_dataset(dataset_cfg)
                    records_fetched += len(raw_records)
                    logger.info(
                        "va_open_data.dataset_fetched",
                        extra={"dataset": dataset_cfg["name"], "count": len(raw_records)},
                    )

                    for rec in raw_records:
                        normalized = self._normalize_record(rec, dataset_cfg["name"])
                        if not normalized:
                            records_skipped += 1
                            continue

                        try:
                            # Entity resolution for permittee
                            raw_name = normalized.get("permittee_raw_name")
                            resolved_company_id = None
                            if raw_name:
                                cid, _conf, _method = await resolve_company(
                                    session, raw_name, source=self.source_id,
                                )
                                resolved_company_id = cid

                            normalized["resolved_company_id"] = resolved_company_id

                            # Upsert GeneratorPermit
                            stmt = pg_insert(GeneratorPermit).values(**normalized)
                            stmt = stmt.on_conflict_do_update(
                                index_elements=["source", "source_permit_id"],
                                set_={
                                    "facility_name": stmt.excluded.facility_name,
                                    "permittee_raw_name": stmt.excluded.permittee_raw_name,
                                    "resolved_company_id": stmt.excluded.resolved_company_id,
                                    "latitude": stmt.excluded.latitude,
                                    "longitude": stmt.excluded.longitude,
                                    "raw_payload": stmt.excluded.raw_payload,
                                    "updated_at": datetime.utcnow(),
                                },
                            )
                            await session.execute(stmt)
                            records_stored += 1

                            # Site matching
                            lat = normalized.get("latitude")
                            lon = normalized.get("longitude")
                            if lat is not None and lon is not None:
                                site_id = await self._match_site(session, lat, lon)
                                if site_id:
                                    alias_stmt = pg_insert(SiteAlias).values(
                                        site_id=site_id,
                                        source=normalized["source"],
                                        source_record_id=normalized["source_permit_id"],
                                        match_method="latlon_within_100m",
                                        confidence=0.75,
                                    )
                                    alias_stmt = alias_stmt.on_conflict_do_nothing(
                                        constraint="uq_site_alias_source_recid"
                                    )
                                    await session.execute(alias_stmt)

                                    if resolved_company_id:
                                        assoc_stmt = pg_insert(SiteCompanyAssociation).values(
                                            site_id=site_id,
                                            company_id=resolved_company_id,
                                            role="permittee_llc",
                                            source=normalized["source"],
                                            source_record_id=normalized["source_permit_id"],
                                            confidence=0.70,
                                        )
                                        assoc_stmt = assoc_stmt.on_conflict_do_nothing(
                                            constraint="uq_site_company_role_source"
                                        )
                                        await session.execute(assoc_stmt)

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
                        "va_open_data.dataset_error",
                        extra={
                            "dataset": dataset_cfg["name"],
                            "status": exc.response.status_code,
                        },
                    )
                    errors.append({"dataset": dataset_cfg["name"], "error": str(exc)})

            await self._write_coverage(session, records_stored)

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
            notes=(
                "Virginia building permits from data.virginia.gov, "
                "Loudoun County, Prince William County"
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
