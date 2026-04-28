"""
Generic Socrata Adapter -- configurable ingestion for any Socrata-powered
state environmental permit portal.

Preconfigured instances cover:
  - NY DEC  (New York Dept of Environmental Conservation)
  - WA Ecology (Washington Dept of Ecology)
  - CO CDPHE (Colorado Dept of Public Health and Environment)
  - OR DEQ  (Oregon Dept of Environmental Quality)

Uses the Socrata Open Data API (SODA):
  GET https://{domain}/resource/{dataset_id}.json?$where=...&$limit=1000&$offset=0

Each SocrataConfig specifies the domain, dataset_id, state_code, and a field_map
that translates portal-specific column names to our canonical schema.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime

import httpx
import stamina
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import (
    DataCoverage,
    GeneratorPermit,
    IngestionRun,
    Site,
    SiteAlias,
    SiteCompanyAssociation,
)
from entity_resolution import resolve_company

logger = logging.getLogger(__name__)

_PROXIMITY_DEGREES = 0.001
_PAGE_SIZE = 1000


@dataclass
class SocrataConfig:
    """Configuration for a single Socrata dataset instance."""

    name: str
    adapter_id: str
    domain: str
    dataset_id: str
    state_code: str
    pillar: str = "generator_permits"
    where_clause: str = ""
    # Field mappings: map generic fields to Socrata column names.
    # Keys: permit_id, facility_name, permittee, latitude, longitude, status
    field_map: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Preconfigured instances for state environmental agencies.
#
# Dataset IDs are best-effort based on public catalog searches at each portal.
# If a dataset is restructured or removed, the adapter gracefully handles 404s.
# ---------------------------------------------------------------------------

SOCRATA_INSTANCES: list[SocrataConfig] = [
    SocrataConfig(
        name="NY DEC Air Permits",
        adapter_id="ny_dec",
        domain="data.ny.gov",
        dataset_id="2v3w-bkng",  # NY DEC Title V Facility Permits
        state_code="NY",
        where_clause="program_facility LIKE '%data center%' OR sic_code LIKE '518%'",
        field_map={
            "permit_id": "permit_id",
            "facility_name": "facility_name",
            "permittee": "owner_name",
            "latitude": "latitude",
            "longitude": "longitude",
            "status": "permit_status",
        },
    ),
    SocrataConfig(
        name="WA Ecology Air Permits",
        adapter_id="wa_ecology",
        domain="data.wa.gov",
        dataset_id="jbh4-3kcz",  # WA air quality permits
        state_code="WA",
        where_clause="naics_code LIKE '518%'",
        field_map={
            "permit_id": "permit_number",
            "facility_name": "facility_name",
            "permittee": "operator_name",
            "latitude": "latitude",
            "longitude": "longitude",
            "status": "permit_status",
        },
    ),
    SocrataConfig(
        name="CO CDPHE Air Permits",
        adapter_id="co_cdphe",
        domain="data.colorado.gov",
        dataset_id="xne4-4bae",  # CO CDPHE permits
        state_code="CO",
        where_clause="naics_code LIKE '518%' OR facility_name LIKE '%data center%'",
        field_map={
            "permit_id": "permit_number",
            "facility_name": "facility_name",
            "permittee": "company_name",
            "latitude": "latitude",
            "longitude": "longitude",
            "status": "status",
        },
    ),
    SocrataConfig(
        name="OR DEQ Air Permits",
        adapter_id="or_deq",
        domain="data.oregon.gov",
        dataset_id="i3pu-ckm4",  # OR DEQ facility permits
        state_code="OR",
        where_clause="naics LIKE '518%' OR source_name LIKE '%data center%'",
        field_map={
            "permit_id": "source_number",
            "facility_name": "source_name",
            "permittee": "responsible_party",
            "latitude": "latitude",
            "longitude": "longitude",
            "status": "permit_status",
        },
    ),
]


class SocrataPermitAdapter:
    """
    Generic Socrata-based permit adapter.

    Instantiate with a SocrataConfig to target a specific state portal.
    Fetches permit records via SODA API, normalizes, and upserts into
    generator_permits.  Uses entity_resolution.resolve_company for
    permittee name resolution.
    """

    adapter_version = "1.1.0"
    declared_status = "partial"

    def __init__(self, config: SocrataConfig) -> None:
        self.config = config
        self.adapter_name = config.name
        self.adapter_id = config.adapter_id
        self.pillar = config.pillar
        self.source_id = config.adapter_id
        self.coverage_scope = config.state_code
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
    async def _rate_limited_get(self, url: str, params: dict) -> list[dict]:
        async with self._semaphore:
            await asyncio.sleep(0.3)
            client = await self._get_client()
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _fetch_all(self) -> list[dict]:
        """Paginate through the Socrata dataset."""
        cfg = self.config
        base_url = f"https://{cfg.domain}/resource/{cfg.dataset_id}.json"

        all_records: list[dict] = []
        offset = 0
        max_pages = 30

        for _ in range(max_pages):
            params: dict[str, str] = {
                "$limit": str(_PAGE_SIZE),
                "$offset": str(offset),
            }
            if cfg.where_clause:
                params["$where"] = cfg.where_clause

            try:
                records = await self._rate_limited_get(base_url, params)
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "socrata.fetch_page_error",
                    extra={
                        "adapter": self.adapter_id,
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

    def _normalize_record(self, record: dict) -> dict | None:
        """Map Socrata fields to GeneratorPermit columns using the field_map."""
        fm = self.config.field_map

        permit_id = record.get(fm.get("permit_id", "permit_id"))
        if not permit_id:
            # Try common fallback field names
            for fallback in ("permit_number", "source_number", "record_id", "id"):
                permit_id = record.get(fallback)
                if permit_id:
                    break
        if not permit_id:
            return None

        lat_key = fm.get("latitude", "latitude")
        lon_key = fm.get("longitude", "longitude")
        lat = record.get(lat_key)
        lon = record.get(lon_key)

        try:
            lat_f = float(lat) if lat else None
        except (ValueError, TypeError):
            lat_f = None
        try:
            lon_f = float(lon) if lon else None
        except (ValueError, TypeError):
            lon_f = None

        facility_name = record.get(fm.get("facility_name", "facility_name"))
        permittee = record.get(fm.get("permittee", "permittee"))
        status = record.get(fm.get("status", "status"))

        return {
            "source": self.source_id,
            "source_permit_id": str(permit_id),
            "facility_name": facility_name,
            "permittee_raw_name": permittee,
            "state_code": self.config.state_code,
            "latitude": lat_f,
            "longitude": lon_f,
            "permit_status": status or "unknown",
            "naics_code": (
                record.get("naics_code")
                or record.get("naics")
                or record.get("sic_code")
            ),
            "confidence": 0.65,
            "raw_payload": record,
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
        """Fetch, normalize, upsert permits from this Socrata instance."""
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
            raw_records = await self._fetch_all()
            records_fetched = len(raw_records)
            logger.info(
                "socrata.fetched",
                extra={"adapter": self.adapter_id, "count": records_fetched},
            )

            for rec in raw_records:
                normalized = self._normalize_record(rec)
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
                                source=self.source_id,
                                source_record_id=normalized["source_permit_id"],
                                match_method="latlon_within_100m",
                                confidence=0.70,
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
                                    source=self.source_id,
                                    source_record_id=normalized["source_permit_id"],
                                    confidence=0.65,
                                )
                                assoc_stmt = assoc_stmt.on_conflict_do_nothing(
                                    constraint="uq_site_company_role_source"
                                )
                                await session.execute(assoc_stmt)

                except Exception as exc:
                    logger.error(
                        "socrata.upsert_error",
                        extra={
                            "adapter": self.adapter_id,
                            "permit_id": normalized.get("source_permit_id"),
                            "error_class": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                    records_skipped += 1
                    errors.append({
                        "permit_id": normalized.get("source_permit_id"),
                        "error": str(exc),
                    })

            await self._write_coverage(session, records_stored)

            run_record.status = "success" if not errors else "partial_failure"
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
                "socrata.run_fatal_error",
                extra={
                    "adapter": self.adapter_id,
                    "error_class": type(exc).__name__,
                    "error": str(exc),
                },
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
            notes=f"{self.adapter_name} via Socrata SODA API",
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
