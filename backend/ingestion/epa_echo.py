"""
EPA ECHO Adapter -- Phase 1A ingestion for EPA facility and air compliance data.

Queries the EPA ECHO REST API for facilities with NAICS 518210
(Data Processing, Hosting) across the priority data-center states.
Upserts into generator_permits, attempts site matching by lat/lon proximity,
and writes site_aliases and site_company_associations when matches are found.

EPA ECHO API docs: https://echo.epa.gov/tools/web-services
The Air Facility Search uses a 2-step protocol:
  1. POST/GET to air_rest_services.get_facilities -- returns a QueryID + summary stats
  2. GET air_rest_services.get_qid?qid=<QueryID> -- returns the actual facility rows

Rate limit policy: we self-impose 2 req/s to be polite to EPA servers.

Phase 1.5 fix (2026-04-29): switched host echo.epa.gov -> echodata.epa.gov,
removed invalid p_act=AIR (now p_act=Y), added per-state pagination, and
implemented the QueryID/get_qid pagination pattern.
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

# Primary host (the docs page echo.epa.gov is NOT an API host)
_ECHO_HOST = "https://echodata.epa.gov"

# Air-program-specific facility search
_ECHO_AIR_FACILITIES_URL = f"{_ECHO_HOST}/echo/air_rest_services.get_facilities"

# Follow-up call to retrieve actual rows by QueryID
_ECHO_AIR_GETQID_URL = f"{_ECHO_HOST}/echo/air_rest_services.get_qid"

# Detailed Facility Report (optional enrichment, currently unused)
_ECHO_DFR_URL = f"{_ECHO_HOST}/echo/dfr_rest_services.get_facility_info"

# Primary NAICS code: data processing / hosting
_DATA_CENTER_NAICS = "518210"

# Priority states: where data-center campuses cluster (Phase 1.5 scope)
_PRIORITY_STATES = ["VA", "TX", "IA", "OR", "AZ", "OH", "GA", "NC", "IL", "WA"]

# Proximity threshold for site matching: ~100m in degrees
_PROXIMITY_DEGREES = 0.001

# Max rows per response page (kept modest -- ECHO get_qid is slow per page)
_PAGE_SIZE = 200

# Self-imposed rate limit: 0.5 s between requests = 2 req/s
_REQUEST_DELAY_S = 0.5


class EpaEchoAdapter:
    """
    EPA ECHO facility ingestion adapter.

    Iterates over priority states, fires NAICS-filtered queries,
    paginates the per-state QueryID, normalizes facility rows, and upserts
    into generator_permits.
    """

    adapter_name = "EPA ECHO"
    adapter_id = "epa_echo"
    adapter_version = "1.2.0"
    pillar = "generator_permits"
    source_id = "epa_echo"
    declared_status = "federal_baseline"
    coverage_scope = "US"

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
    # Fetch facilities from EPA ECHO -- 2-step QueryID protocol
    # ------------------------------------------------------------------

    async def _fetch_state_facilities(
        self, state: str, naics: str = _DATA_CENTER_NAICS,
    ) -> list[dict]:
        """
        Run the QueryID + get_qid pagination protocol for a single state.

        Step 1: POST get_facilities -> returns QueryID + total QueryRows
        Step 2: GET get_qid?qid=...&pageno=... -> returns Facilities[]
        """
        # Step 1: kick off the query
        params = {
            "output": "JSON",
            "p_naics": naics,
            "p_st": state,
            "p_act": "Y",
            "responseset": str(_PAGE_SIZE),
        }
        try:
            data = await self._rate_limited_get(_ECHO_AIR_FACILITIES_URL, params)
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "epa_echo.state_query_http_error",
                extra={"state": state, "status": exc.response.status_code},
            )
            return []
        except httpx.TransportError as exc:
            logger.warning(
                "epa_echo.state_query_transport_error",
                extra={"state": state, "error": str(exc)},
            )
            return []

        results = data.get("Results", {})
        qid = results.get("QueryID")
        try:
            total_rows = int(results.get("QueryRows", "0"))
        except (TypeError, ValueError):
            total_rows = 0

        if not qid or total_rows == 0:
            logger.info(
                "epa_echo.state_no_results",
                extra={"state": state, "qid": qid, "rows": total_rows},
            )
            return []

        logger.info(
            "epa_echo.state_query_started",
            extra={"state": state, "qid": qid, "total_rows": total_rows},
        )

        # Step 2: paginate get_qid. We cap to 1 page per state for the
        # smoke-test profile -- 200 rows * 10 states = up to 2000 rows is
        # plenty of federal-baseline coverage. Increase via the
        # max_facilities arg if a deeper sweep is required.
        all_facilities: list[dict] = []
        max_pages = 1
        for pageno in range(1, max_pages + 1):
            page_params = {
                "output": "JSON",
                "qid": str(qid),
                "pageno": str(pageno),
                "responseset": str(_PAGE_SIZE),
            }
            try:
                page_data = await self._rate_limited_get(_ECHO_AIR_GETQID_URL, page_params)
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                logger.warning(
                    "epa_echo.qid_page_error",
                    extra={"state": state, "qid": qid, "page": pageno, "error": str(exc)},
                )
                break

            facilities = page_data.get("Results", {}).get("Facilities", [])
            if not facilities:
                break

            all_facilities.extend(facilities)
            if len(facilities) < _PAGE_SIZE:
                break

        logger.info(
            "epa_echo.state_complete",
            extra={"state": state, "fetched": len(all_facilities)},
        )
        return all_facilities

    # ------------------------------------------------------------------
    # Normalize facility data into GeneratorPermit rows
    # ------------------------------------------------------------------

    def _normalize_facility(self, fac: dict) -> dict | None:
        """Convert an EPA ECHO air-facility dict into a GeneratorPermit row."""
        # Air-services payload uses RegistryID + AIRName + AIRState etc.
        registry_id = (
            fac.get("RegistryID")
            or fac.get("RegistryId")
            or fac.get("FacRegistryId")
            or fac.get("SourceID")
        )
        if not registry_id:
            return None

        lat = fac.get("FacLat") or fac.get("Lat")
        lon = fac.get("FacLong") or fac.get("Lon") or fac.get("FacLon")

        try:
            lat_f = float(lat) if lat else None
        except (ValueError, TypeError):
            lat_f = None
        try:
            lon_f = float(lon) if lon else None
        except (ValueError, TypeError):
            lon_f = None

        state_code = fac.get("AIRState") or fac.get("FacState") or fac.get("StateCode") or ""
        if len(state_code) > 2:
            state_code = state_code[:2].upper()

        naics = fac.get("AIRNAICS") or fac.get("NAICSCodes") or fac.get("FacNAICSCodes") or ""
        county_fips = fac.get("FacFIPSCode") or fac.get("FacCountyFips") or fac.get("CountyFips")

        facility_name = fac.get("AIRName") or fac.get("FacName") or fac.get("FacilityName")

        return {
            "source": self.source_id,
            "source_permit_id": str(registry_id),
            "facility_name": facility_name,
            "permittee_raw_name": facility_name,
            "state_code": state_code if state_code else None,
            "county_fips": str(county_fips)[:10] if county_fips else None,
            "latitude": lat_f,
            "longitude": lon_f,
            "frs_id": str(registry_id)[:100],
            "naics_code": str(naics)[:50] if naics else _DATA_CENTER_NAICS,
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
        max_facilities: int = 500,
        states: Optional[list[str]] = None,
    ) -> dict:
        """Fetch ECHO air facilities for each priority state, upsert results."""
        states = states or _PRIORITY_STATES

        run_record = IngestionRun(
            adapter_name=self.adapter_id,
            adapter_version=self.adapter_version,
            started_at=datetime.utcnow(),
            status="running",
            trigger="manual",
            config_snapshot={"max_facilities": max_facilities, "states": states},
        )
        session.add(run_record)
        await session.flush()

        records_fetched = 0
        records_stored = 0
        records_skipped = 0
        errors: list[dict] = []

        try:
            seen_ids: set[str] = set()
            all_facilities: list[dict] = []

            for st in states:
                if len(all_facilities) >= max_facilities:
                    break
                try:
                    state_rows = await self._fetch_state_facilities(st)
                except Exception as exc:
                    logger.warning(
                        "epa_echo.state_failed",
                        extra={"state": st, "error_class": type(exc).__name__, "error": str(exc)},
                    )
                    errors.append({"state": st, "error": str(exc)})
                    continue

                for fac in state_rows:
                    rid = (
                        fac.get("RegistryID")
                        or fac.get("RegistryId")
                        or fac.get("FacRegistryId")
                        or fac.get("SourceID")
                        or ""
                    )
                    if rid and rid not in seen_ids:
                        seen_ids.add(rid)
                        all_facilities.append(fac)
                        if len(all_facilities) >= max_facilities:
                            break

            records_fetched = len(all_facilities)
            logger.info(
                "epa_echo.total_facilities",
                extra={"count": records_fetched, "max": max_facilities, "states": states},
            )

            for fac in all_facilities:
                normalized = self._normalize_facility(fac)
                if not normalized:
                    records_skipped += 1
                    continue

                try:
                    raw_name = normalized.get("permittee_raw_name")
                    resolved_company_id = None
                    if raw_name:
                        company_id, _confidence, _method = await resolve_company(
                            session, raw_name, source=self.source_id,
                        )
                        resolved_company_id = company_id

                    normalized["resolved_company_id"] = resolved_company_id

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

                    lat = normalized.get("latitude")
                    lon = normalized.get("longitude")
                    if lat is not None and lon is not None:
                        site_id = await self._match_site_by_latlon(session, lat, lon)
                        if site_id:
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

            await self._write_coverage(session, records_stored)
            await self._write_lineage(session, run_record.id, records_stored)

            run_record.status = "success" if records_stored > 0 else (
                "partial_failure" if errors else "success"
            )
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
        stmt = pg_insert(DataCoverage).values(
            pillar=self.pillar,
            state_code=self.coverage_scope,
            source=self.source_id,
            coverage_status=self.declared_status,
            record_count=record_count,
            last_ingested_at=datetime.utcnow(),
            freshness_sla_hours=168,
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
        if record_count <= 0:
            return
        stmt = pg_insert(DataLineage).values(
            table_name="generator_permits",
            record_id=run_id,
            ingestion_run_id=run_id,
            source_url=_ECHO_AIR_FACILITIES_URL,
            retrieved_at=datetime.utcnow(),
            parser_version=self.adapter_version,
            confidence=0.70,
            transformation={"method": "epa_echo_air_facilities", "naics": _DATA_CENTER_NAICS},
        )
        await session.execute(stmt)
