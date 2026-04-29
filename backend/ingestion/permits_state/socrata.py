"""
Generic Socrata Adapter -- configurable ingestion for state environmental
permit portals served by Socrata SODA.

Phase 1.5 fix (2026-04-29):
  * Updated NY DEC dataset IDs to the current canonical set:
      4n3a-en4b -- Issued Title V Facility Permits
      2wgt-bc53 -- Issued State Facility Air Permits
      f4rp-2kvy -- Clean Air Tracking System (CATS) Permits
  * Removed WA Ecology and CO CDPHE configs -- no Socrata datasets exist
    for those states (researcher-confirmed); EPA ECHO covers them instead.
  * Use $where=upper(facility_name) like '%DATA CENTER%' as the primary
    filter to keep volume manageable.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
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
    field_map: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Per-state dataset registry. NY only as of Phase 1.5 -- WA and CO removed.
# ---------------------------------------------------------------------------

STATE_DATASETS: dict[str, list[tuple[str, str]]] = {
    "NY": [
        ("4n3a-en4b", "Title V Permits"),
        ("2wgt-bc53", "State Facility Air Permits"),
        ("f4rp-2kvy", "CATS Permits"),
    ],
    # WA and CO intentionally omitted -- routed through EPA ECHO instead.
}

# Default $where filter for NY -- substring on facility_name. Datasets
# without a facility_name column will silently drop the filter.
_NY_DEFAULT_WHERE = "upper(facility_name) like '%DATA CENTER%'"


def _build_ny_instances() -> list[SocrataConfig]:
    """Materialize NY SocrataConfig instances from STATE_DATASETS."""
    instances: list[SocrataConfig] = []
    for ds_id, label in STATE_DATASETS.get("NY", []):
        slug = ds_id.replace("-", "_")
        instances.append(
            SocrataConfig(
                name=f"NY DEC {label}",
                adapter_id=f"ny_dec_{slug}",
                domain="data.ny.gov",
                dataset_id=ds_id,
                state_code="NY",
                where_clause=_NY_DEFAULT_WHERE,
                field_map={
                    "permit_id": "permit_id",
                    "facility_name": "facility_name",
                    "permittee": "facility_name",  # NY datasets lack a separate operator field
                    "latitude": "latitude",
                    "longitude": "longitude",
                    "status": "permit_status",
                    "issue_date": "issue_date",
                    "expiry_date": "expiration_date",
                },
            )
        )
    return instances


SOCRATA_INSTANCES: list[SocrataConfig] = _build_ny_instances()


class SocrataPermitAdapter:
    """
    Generic Socrata-based permit adapter.

    Instantiated with a SocrataConfig pointing at a specific dataset.
    """

    adapter_version = "2.0.0"
    declared_status = "partial"

    def __init__(self, config: SocrataConfig) -> None:
        self.config = config
        self.adapter_name = config.name
        self.adapter_id = config.adapter_id
        self.pillar = config.pillar
        # All NY datasets share the same source label so the row counts
        # roll up cleanly under a single source in generator_permits.
        self.source_id = "socrata_ny" if config.state_code == "NY" else config.adapter_id
        self.coverage_scope = config.state_code
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
        """
        Paginate through the Socrata dataset.

        Tries the configured $where clause first; if Socrata rejects the
        clause (HTTP 400, e.g. column doesn't exist on this dataset), falls
        back to a single unfiltered page so we still land rows.
        """
        cfg = self.config
        base_url = f"https://{cfg.domain}/resource/{cfg.dataset_id}.json"

        async def fetch(where: str | None) -> list[dict]:
            results: list[dict] = []
            offset = 0
            for _ in range(10):
                params: dict[str, str] = {
                    "$limit": str(_PAGE_SIZE),
                    "$offset": str(offset),
                }
                if where:
                    params["$where"] = where
                try:
                    page = await self._rate_limited_get(base_url, params)
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "socrata.fetch_page_error",
                        extra={
                            "adapter": self.adapter_id,
                            "status": exc.response.status_code,
                            "offset": offset,
                            "where": where,
                        },
                    )
                    if exc.response.status_code == 400 and where:
                        # Surface the bad-clause error to the outer fallback
                        raise
                    break
                if not page:
                    break
                results.extend(page)
                if len(page) < _PAGE_SIZE:
                    break
                offset += _PAGE_SIZE
            return results

        # Attempt with where clause; on 400 (bad column), retry without.
        try:
            return await fetch(cfg.where_clause or None)
        except httpx.HTTPStatusError:
            logger.info(
                "socrata.where_clause_unsupported_falling_back",
                extra={"adapter": self.adapter_id, "dataset": cfg.dataset_id},
            )
            return await fetch(None)

    @staticmethod
    def _parse_date(value) -> date | None:
        if not value:
            return None
        s = str(value).strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        except (ValueError, AttributeError):
            return None

    def _normalize_record(self, record: dict) -> dict | None:
        fm = self.config.field_map

        permit_id = record.get(fm.get("permit_id", "permit_id"))
        if not permit_id:
            for fallback in ("permit_number", "source_number", "record_id", "id"):
                permit_id = record.get(fallback)
                if permit_id:
                    break
        if not permit_id:
            return None

        lat_key = fm.get("latitude", "latitude")
        lon_key = fm.get("longitude", "longitude")
        # NY datasets often expose lat/lon inside a georeference dict
        georef = record.get("georeference") or {}
        georef_coords = georef.get("coordinates") if isinstance(georef, dict) else None

        lat = record.get(lat_key)
        lon = record.get(lon_key)
        if (lat is None or lon is None) and georef_coords and len(georef_coords) >= 2:
            lon = georef_coords[0]
            lat = georef_coords[1]

        try:
            lat_f = float(lat) if lat else None
        except (ValueError, TypeError):
            lat_f = None
        try:
            lon_f = float(lon) if lon else None
        except (ValueError, TypeError):
            lon_f = None

        facility_name = record.get(fm.get("facility_name", "facility_name"))
        permittee = record.get(fm.get("permittee", "facility_name"))
        status = record.get(fm.get("status", "status"))
        issue_date = self._parse_date(record.get(fm.get("issue_date", "issue_date")))
        expiry_date = self._parse_date(record.get(fm.get("expiry_date", "expiration_date")))

        return {
            "source": self.source_id,
            "source_permit_id": str(permit_id)[:255],
            "facility_name": facility_name,
            "permittee_raw_name": permittee,
            "state_code": self.config.state_code,
            "latitude": lat_f,
            "longitude": lon_f,
            "permit_status": (str(status) if status else "issued")[:100],
            "issued_date": issue_date,
            "expiry_date": expiry_date,
            "naics_code": (
                str(record.get("naics_code") or record.get("naics") or record.get("sic_code"))[:50]
                if (record.get("naics_code") or record.get("naics") or record.get("sic_code"))
                else None
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
                            "latitude": stmt.excluded.latitude,
                            "longitude": stmt.excluded.longitude,
                            "issued_date": stmt.excluded.issued_date,
                            "expiry_date": stmt.excluded.expiry_date,
                            "raw_payload": stmt.excluded.raw_payload,
                            "updated_at": datetime.utcnow(),
                        },
                    )
                    await session.execute(stmt)
                    records_stored += 1
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

    async def _write_lineage(
        self, session: AsyncSession, run_id: int, record_count: int
    ) -> None:
        if record_count <= 0:
            return
        cfg = self.config
        stmt = pg_insert(DataLineage).values(
            table_name="generator_permits",
            record_id=run_id,
            ingestion_run_id=run_id,
            source_url=f"https://{cfg.domain}/resource/{cfg.dataset_id}.json",
            retrieved_at=datetime.utcnow(),
            parser_version=self.adapter_version,
            confidence=0.65,
            transformation={
                "method": "socrata_soda",
                "dataset_id": cfg.dataset_id,
                "where": cfg.where_clause,
            },
        )
        await session.execute(stmt)
