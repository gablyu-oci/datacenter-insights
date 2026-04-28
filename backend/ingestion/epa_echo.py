"""
EPA ECHO Adapter -- Phase 1A ingestion for EPA facility and air compliance data.

Queries the EPA ECHO REST API for facilities with NAICS 518210
(Data Processing, Hosting) and emergency generator permits.
Upserts into generator_permits, attempts site matching by lat/lon proximity,
and writes site_aliases and site_company_associations when matches are found.

EPA ECHO API docs: https://echo.epa.gov/tools/web-services
Two endpoints are used:
  1. Air Facility Search (get_facilities) -- lists air-permitted facilities
     filtered by NAICS code or facility name keyword.
  2. DFR (Detailed Facility Report) get_facility_info -- richer per-facility
     data when we need supplementary detail (used for enrichment only).

Rate limit policy: we self-impose 2 req/s to be polite to EPA servers.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, date
from typing import Optional

import httpx
import stamina
from sqlalchemy import select, text
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

# ---------------------------------------------------------------------------
# EPA ECHO endpoints
# ---------------------------------------------------------------------------

# Primary: Air Facility Search -- returns paginated facility list
_ECHO_AIR_FACILITIES_URL = (
    "https://echodata.epa.gov/echo/air_rest_services.get_facilities"
)

# Secondary: Detailed Facility Report -- richer data per facility
_ECHO_DFR_URL = (
    "https://echodata.epa.gov/echo/dfr_rest_services.get_facility_info"
)

# NAICS code for data processing / hosting / related services
_DATA_CENTER_NAICS = "518210"

# Proximity threshold for site matching: ~100 meters in degrees
_PROXIMITY_DEGREES = 0.001

# Max results per page from ECHO API
_PAGE_SIZE = 100

# Self-imposed rate limit: 0.5 s between requests = 2 req/s
_REQUEST_DELAY_S = 0.5


class EpaEchoAdapter:
    """
    EPA ECHO facility ingestion adapter.

    Searches for facilities with data-center-related NAICS codes,
    creates GeneratorPermit records, and attempts lat/lon site matching.
    Uses entity_resolution.resolve_company for permittee name resolution.
    """

    adapter_name = "EPA ECHO"
    adapter_id = "epa_echo"
    adapter_version = "1.1.0"
    pillar = "generator_permits"
    source_id = "epa_echo"
    declared_status = "federal_baseline"
    coverage_scope = "US"

    def __init__(self) -> None:
        # Semaphore enforces max 2 concurrent in-flight requests
        self._semaphore = asyncio.Semaphore(2)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=60.0, write=10.0, pool=15.0),
                follow_redirects=True,
                headers={
                    "User-Agent": "DatacenterIntelPlatform/1.0 (research@oracle.com)",
                },
            )
        return self._client

    @stamina.retry(on=(httpx.TransportError, httpx.HTTPStatusError), attempts=3, wait_initial=2.0)
    async def _rate_limited_get(self, url: str, params: dict) -> dict:
        """Rate-limited GET against the EPA ECHO API (2 req/s)."""
        async with self._semaphore:
            await asyncio.sleep(_REQUEST_DELAY_S)
            client = await self._get_client()
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Fetch facilities from EPA ECHO
    # ------------------------------------------------------------------

    async def _fetch_facilities_by_naics(
        self, naics: str, *, max_facilities: int = 5000
    ) -> list[dict]:
        """
        Paginate through EPA ECHO air facility search for a given NAICS code.
        Returns a flat list of facility dicts, capped at max_facilities.
        """
        all_facilities: list[dict] = []
        page = 1
        # Safety ceiling: we won't exceed 50 pages even if max_facilities is huge
        max_pages = min(50, (max_facilities // _PAGE_SIZE) + 1)

        while page <= max_pages and len(all_facilities) < max_facilities:
            params = {
                "output": "JSON",
                "p_nai": naics,        # NAICS filter (note: API param is p_nai)
                "p_act": "AIR",        # Air program facilities
                "responseset": str(_PAGE_SIZE),
                "pageno": str(page),
            }
            try:
                data = await self._rate_limited_get(_ECHO_AIR_FACILITIES_URL, params)
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "epa_echo.fetch_http_error",
                    extra={"naics": naics, "page": page, "status": exc.response.status_code},
                )
                break
            except httpx.TransportError as exc:
                logger.error(
                    "epa_echo.fetch_transport_error",
                    extra={"naics": naics, "page": page, "error": str(exc)},
                )
                break

            # EPA ECHO wraps results inside { "Results": { "Facilities": [...] } }
            results = data.get("Results", {})
            facilities = results.get("Facilities", [])
            if not facilities:
                break

            all_facilities.extend(facilities)
            logger.info(
                "epa_echo.fetched_page",
                extra={"naics": naics, "page": page, "count": len(facilities)},
            )

            if len(facilities) < _PAGE_SIZE:
                break
            page += 1

        return all_facilities[:max_facilities]

    async def _fetch_facilities_by_keyword(
        self, keyword: str = "data center"
    ) -> list[dict]:
        """
        Supplementary search using facility-name keyword to catch facilities
        that might not have the exact NAICS 518210 assigned.
        """
        params = {
            "output": "JSON",
            "p_fn": keyword,
            "p_act": "AIR",
            "responseset": str(_PAGE_SIZE),
            "pageno": "1",
        }
        try:
            data = await self._rate_limited_get(_ECHO_AIR_FACILITIES_URL, params)
            return data.get("Results", {}).get("Facilities", [])
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            logger.warning(
                "epa_echo.keyword_search_error",
                extra={"keyword": keyword, "error": str(exc)},
            )
            return []

    async def _fetch_dfr_facility_info(self, registry_id: str) -> dict | None:
        """
        Optional enrichment: pull Detailed Facility Report for a single facility.
        This gives richer compliance and permit data but is expensive (1 call per
        facility), so only call when we need supplementary detail.
        """
        params = {
            "output": "JSON",
            "p_id": registry_id,
        }
        try:
            data = await self._rate_limited_get(_ECHO_DFR_URL, params)
            return data
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            logger.debug(
                "epa_echo.dfr_fetch_error",
                extra={"registry_id": registry_id, "error": str(exc)},
            )
            return None

    # ------------------------------------------------------------------
    # Normalize facility data into GeneratorPermit rows
    # ------------------------------------------------------------------

    def _normalize_facility(self, fac: dict) -> dict | None:
        """Convert an EPA ECHO facility dict into a GeneratorPermit-shaped dict."""
        registry_id = fac.get("RegistryId") or fac.get("FacRegistryId")
        if not registry_id:
            return None

        lat = fac.get("Lat") or fac.get("FacLat")
        lon = fac.get("Lon") or fac.get("FacLong")

        try:
            lat_f = float(lat) if lat else None
        except (ValueError, TypeError):
            lat_f = None
        try:
            lon_f = float(lon) if lon else None
        except (ValueError, TypeError):
            lon_f = None

        # Prefer the 2-letter state code; EPA sometimes returns full names
        state_code = fac.get("FacState") or fac.get("StateCode") or ""
        if len(state_code) > 2:
            state_code = state_code[:2].upper()

        naics = fac.get("NAICSCodes") or fac.get("FacNAICSCodes") or ""
        county_fips = fac.get("FacCountyFips") or fac.get("CountyFips")

        facility_name = fac.get("FacName") or fac.get("FacilityName")

        return {
            "source": self.source_id,
            "source_permit_id": str(registry_id),
            "facility_name": facility_name,
            "permittee_raw_name": facility_name,
            "state_code": state_code if state_code else None,
            "county_fips": str(county_fips) if county_fips else None,
            "latitude": lat_f,
            "longitude": lon_f,
            "frs_id": str(registry_id),
            "naics_code": str(naics)[:10] if naics else _DATA_CENTER_NAICS,
            "permit_status": "active",
            "confidence": 0.70,
            "raw_payload": fac,
        }

    # ------------------------------------------------------------------
    # Site matching by lat/lon proximity (~100m)
    # ------------------------------------------------------------------

    async def _match_site_by_latlon(
        self, session: AsyncSession, lat: float, lon: float
    ) -> int | None:
        """Find a site within ~100m of the given lat/lon. Returns site_id or None."""
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
    # Main run method
    # ------------------------------------------------------------------

    async def run(
        self,
        session: AsyncSession,
        *,
        max_facilities: int = 5000,
    ) -> dict:
        """
        Fetch EPA ECHO facilities, normalize, upsert into generator_permits.
        Attempt site matching and emit site_aliases + site_company_associations.

        Parameters
        ----------
        session : AsyncSession
            Active database session. Caller manages commit/rollback.
        max_facilities : int
            Cap on total facilities fetched (across NAICS + keyword searches).
        """
        run_record = IngestionRun(
            adapter_name=self.adapter_id,
            adapter_version=self.adapter_version,
            started_at=datetime.utcnow(),
            status="running",
            trigger="manual",
            config_snapshot={"max_facilities": max_facilities},
        )
        session.add(run_record)
        await session.flush()

        records_fetched = 0
        records_stored = 0
        records_skipped = 0
        errors: list[dict] = []

        try:
            # 1) Fetch from NAICS-based search
            naics_facilities = await self._fetch_facilities_by_naics(
                _DATA_CENTER_NAICS, max_facilities=max_facilities,
            )
            # 2) Supplementary keyword search
            keyword_facilities = await self._fetch_facilities_by_keyword("data center")

            # Deduplicate by registry ID
            seen_ids: set[str] = set()
            all_facilities: list[dict] = []
            for fac in naics_facilities + keyword_facilities:
                rid = fac.get("RegistryId") or fac.get("FacRegistryId") or ""
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    all_facilities.append(fac)
                    if len(all_facilities) >= max_facilities:
                        break

            records_fetched = len(all_facilities)
            logger.info(
                "epa_echo.total_facilities",
                extra={"count": records_fetched, "max": max_facilities},
            )

            for fac in all_facilities:
                normalized = self._normalize_facility(fac)
                if not normalized:
                    records_skipped += 1
                    continue

                try:
                    # --- Entity resolution for the permittee name ---
                    raw_name = normalized.get("permittee_raw_name")
                    resolved_company_id = None
                    if raw_name:
                        company_id, confidence, method = await resolve_company(
                            session, raw_name, source=self.source_id,
                        )
                        resolved_company_id = company_id

                    normalized["resolved_company_id"] = resolved_company_id

                    # --- Upsert GeneratorPermit ---
                    stmt = pg_insert(GeneratorPermit).values(**normalized)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["source", "source_permit_id"],
                        set_={
                            "facility_name": stmt.excluded.facility_name,
                            "permittee_raw_name": stmt.excluded.permittee_raw_name,
                            "resolved_company_id": stmt.excluded.resolved_company_id,
                            "state_code": stmt.excluded.state_code,
                            "county_fips": stmt.excluded.county_fips,
                            "latitude": stmt.excluded.latitude,
                            "longitude": stmt.excluded.longitude,
                            "frs_id": stmt.excluded.frs_id,
                            "naics_code": stmt.excluded.naics_code,
                            "raw_payload": stmt.excluded.raw_payload,
                            "updated_at": datetime.utcnow(),
                        },
                    )
                    await session.execute(stmt)
                    records_stored += 1

                    # --- Site matching by lat/lon ---
                    lat = normalized.get("latitude")
                    lon = normalized.get("longitude")
                    if lat is not None and lon is not None:
                        site_id = await self._match_site_by_latlon(session, lat, lon)
                        if site_id:
                            # Write site_alias: source=epa_echo, record_id=FRS_ID
                            alias_stmt = pg_insert(SiteAlias).values(
                                site_id=site_id,
                                source=self.source_id,
                                source_record_id=normalized["frs_id"],
                                match_method="latlon_within_100m",
                                confidence=0.75,
                            )
                            alias_stmt = alias_stmt.on_conflict_do_nothing(
                                constraint="uq_site_alias_source_recid"
                            )
                            await session.execute(alias_stmt)

                            # Emit site_company_association with role=permittee_llc
                            if resolved_company_id:
                                assoc_stmt = pg_insert(SiteCompanyAssociation).values(
                                    site_id=site_id,
                                    company_id=resolved_company_id,
                                    role="permittee_llc",
                                    source=self.source_id,
                                    source_record_id=normalized["frs_id"],
                                    confidence=0.70,
                                )
                                assoc_stmt = assoc_stmt.on_conflict_do_nothing(
                                    constraint="uq_site_company_role_source"
                                )
                                await session.execute(assoc_stmt)

                except Exception as exc:
                    logger.error(
                        "epa_echo.upsert_error",
                        extra={
                            "frs_id": normalized.get("frs_id"),
                            "error_class": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                    records_skipped += 1
                    errors.append({
                        "frs_id": normalized.get("frs_id"),
                        "error": str(exc),
                    })

            # --- Write coverage row ---
            await self._write_coverage(session, records_stored)

            # --- Write lineage summary ---
            await self._write_lineage(session, run_record.id, records_stored)

            # --- Finalize ingestion run ---
            run_record.status = "success" if not errors else "partial_failure"
            run_record.completed_at = datetime.utcnow()
            run_record.records_fetched = records_fetched
            run_record.records_normalized = records_fetched - records_skipped
            run_record.records_stored = records_stored
            run_record.records_skipped = records_skipped
            run_record.error_log = {"errors": errors[:50]} if errors else None
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
                "epa_echo.run_fatal_error",
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

    # ------------------------------------------------------------------
    # Coverage & lineage helpers
    # ------------------------------------------------------------------

    async def _write_coverage(self, session: AsyncSession, record_count: int) -> None:
        """Upsert a data_coverage row for this adapter."""
        stmt = pg_insert(DataCoverage).values(
            pillar=self.pillar,
            state_code=self.coverage_scope,
            source=self.source_id,
            coverage_status=self.declared_status,
            record_count=record_count,
            last_ingested_at=datetime.utcnow(),
            freshness_sla_hours=168,  # weekly refresh target
            notes="EPA ECHO air program facilities with NAICS 518210 (data processing/hosting)",
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
        """Write a single summary lineage row for this adapter run."""
        if record_count <= 0:
            return
        stmt = pg_insert(DataLineage).values(
            table_name="generator_permits",
            record_id=run_id,  # references ingestion_runs.id
            ingestion_run_id=run_id,
            source_url=_ECHO_AIR_FACILITIES_URL,
            retrieved_at=datetime.utcnow(),
            parser_version=self.adapter_version,
            confidence=0.70,
            transformation={"method": "epa_echo_air_facilities", "naics": _DATA_CENTER_NAICS},
        )
        await session.execute(stmt)
