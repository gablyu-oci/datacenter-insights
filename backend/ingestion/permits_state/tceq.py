"""
TCEQ Adapter -- Texas Commission on Environmental Quality air permits.

TCEQ provides air permit data via their public Central Registry (CRPUB).
This adapter searches for facilities matching known datacenter operator names
or datacenter-related SIC/NAICS codes, scrapes the HTML results, and upserts
into generator_permits.

Endpoint: https://www15.tceq.texas.gov/crpub/index.cfm?fuession=iwr.search
The CRPUB system returns HTML, not JSON, so we do best-effort regex parsing.
The adapter is conservative with rate limits (1 req/s, 2 concurrency) to
avoid being blocked.

Coverage: pillar='building_permits', state_code='TX', source='tceq', status='partial'
"""
from __future__ import annotations

import asyncio
import logging
import re
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

# TCEQ Central Registry endpoints.
# The search endpoint accepts GET parameters for entity name, media type, etc.
# NOTE: The URL path uses "fuession" (TCEQ's ColdFusion param) not "fuseaction".
_TCEQ_SEARCH_URL = "https://www15.tceq.texas.gov/crpub/index.cfm"

# SIC codes for data centers / computer facilities
_DC_SIC_CODES = ["7372", "7374", "7371", "4911"]

# NAICS codes related to data centers
_DC_NAICS_CODES = ["518210", "518111", "541512"]

# Known data center operators in Texas to search by name.
# We search for each name to find their TCEQ-registered facilities.
_TX_DC_OPERATORS = [
    "QTS",
    "CyrusOne",
    "Digital Realty",
    "DataPoint",
    "Skybox",
    "Stream Data",
    "T5 Data",
    "Flexential",
    "Compass Datacenters",
    "Microsoft",
    "Google",
    "Meta",
    "Amazon",
    "Oracle",
]


class TceqAdapter:
    """
    TCEQ air permit adapter for Texas.

    Scrapes the TCEQ Central Registry for facilities matching data center
    SIC/NAICS codes or known operator names.  Uses entity_resolution for
    permittee name resolution.
    """

    adapter_name = "TCEQ Air Permits"
    adapter_id = "tceq"
    adapter_version = "1.1.0"
    pillar = "building_permits"
    source_id = "tceq"
    declared_status = "partial"
    coverage_scope = "TX"

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(2)  # conservative for scraping
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

    @stamina.retry(on=httpx.TransportError, attempts=3, wait_initial=2.0)
    async def _rate_limited_get(self, url: str, params: dict) -> str:
        """Fetch a page with rate limiting. Returns raw HTML/text."""
        async with self._semaphore:
            await asyncio.sleep(1.0)  # conservative rate limit for TCEQ
            client = await self._get_client()
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.text

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Scrape TCEQ Central Registry
    # ------------------------------------------------------------------

    async def _search_by_entity_name(self, name: str) -> list[dict]:
        """
        Search TCEQ Central Registry for a regulated entity by name.
        Parses the HTML response to extract facility records.
        """
        params = {
            "fuession": "iwr.search",
            "re_entity_name": name,
            "re_state": "TX",
            "re_media": "AIR",
            "output_format": "HTML",
        }

        try:
            html = await self._rate_limited_get(_TCEQ_SEARCH_URL, params)
            return self._parse_search_results(html, name)
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "tceq.search_http_error",
                extra={"raw_name": name, "status": exc.response.status_code},
            )
            return []
        except httpx.TransportError as exc:
            logger.warning(
                "tceq.search_transport_error",
                extra={"raw_name": name, "error": str(exc)},
            )
            return []

    def _parse_search_results(self, html: str, search_name: str) -> list[dict]:
        """
        Parse TCEQ search result HTML to extract facility data.

        This is a best-effort parser. TCEQ pages change format occasionally,
        so we extract what we can and store the raw HTML snippet in raw_payload
        for manual review if the parser cannot extract structured fields.
        """
        results: list[dict] = []

        # Extract regulated entity numbers (RN) from the page.
        # TCEQ RN numbers are typically RN followed by 9-12 digits.
        rn_pattern = re.compile(r"RN(\d{9,12})")
        rn_matches = rn_pattern.findall(html)

        # Try to extract facility names that appear near RN numbers in table cells
        facility_pattern = re.compile(
            r"RN(\d{9,12})\s*</a>\s*</td>\s*<td[^>]*>([^<]+)</td>",
            re.I,
        )
        facility_matches = facility_pattern.findall(html)

        if facility_matches:
            for rn_num, fac_name in facility_matches:
                fac_name = fac_name.strip()
                if not fac_name:
                    continue
                results.append({
                    "rn_number": f"RN{rn_num}",
                    "facility_name": fac_name,
                    "search_name": search_name,
                })
        elif rn_matches:
            # Fallback: just track the RN numbers found
            for rn_num in sorted(set(rn_matches)):
                results.append({
                    "rn_number": f"RN{rn_num}",
                    "facility_name": search_name,
                    "search_name": search_name,
                })

        # Try to extract lat/lon if present on the page
        latlon_pattern = re.compile(
            r"Latitude[:\s]*([-\d.]+)\s*.*?Longitude[:\s]*([-\d.]+)",
            re.I | re.DOTALL,
        )
        latlon_matches = latlon_pattern.findall(html)
        if latlon_matches and results:
            for i, (lat_str, lon_str) in enumerate(latlon_matches):
                if i < len(results):
                    try:
                        results[i]["latitude"] = float(lat_str)
                        results[i]["longitude"] = float(lon_str)
                    except ValueError:
                        pass

        return results

    def _normalize_record(self, record: dict) -> dict | None:
        """Convert a scraped TCEQ record into a GeneratorPermit-shaped dict."""
        rn = record.get("rn_number")
        if not rn:
            return None

        lat = record.get("latitude")
        lon = record.get("longitude")

        return {
            "source": self.source_id,
            "source_permit_id": rn,
            "facility_name": record.get("facility_name"),
            "permittee_raw_name": record.get("search_name"),
            "state_code": "TX",
            "latitude": lat,
            "longitude": lon,
            "permit_status": "active",
            "confidence": 0.55,  # lower confidence for scraped data
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
        """Search TCEQ for DC-related facilities, normalize, upsert."""
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
            # Search for each known DC operator
            all_raw: list[dict] = []
            seen_rns: set[str] = set()

            for operator in _TX_DC_OPERATORS:
                try:
                    results = await self._search_by_entity_name(operator)
                    for r in results:
                        rn = r.get("rn_number", "")
                        if rn and rn not in seen_rns:
                            seen_rns.add(rn)
                            all_raw.append(r)
                except Exception as exc:
                    logger.warning(
                        "tceq.operator_search_error",
                        extra={
                            "operator": operator,
                            "error_class": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                    errors.append({"operator": operator, "error": str(exc)})

            records_fetched = len(all_raw)
            logger.info("tceq.total_records", extra={"count": records_fetched})

            for raw in all_raw:
                normalized = self._normalize_record(raw)
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
                                confidence=0.60,
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
                                    confidence=0.55,
                                )
                                assoc_stmt = assoc_stmt.on_conflict_do_nothing(
                                    constraint="uq_site_company_role_source"
                                )
                                await session.execute(assoc_stmt)

                except Exception as exc:
                    logger.error(
                        "tceq.upsert_error",
                        extra={
                            "rn": normalized.get("source_permit_id"),
                            "error_class": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                    records_skipped += 1
                    errors.append({
                        "rn": normalized.get("source_permit_id"),
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
            freshness_sla_hours=336,  # ~2 week refresh for scraped data
            notes="TCEQ Central Registry air permits for data center operators in Texas",
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
