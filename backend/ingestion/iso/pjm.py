"""
PJM ISO Interconnection Queue Adapter — Phase 1A.

PJM Interconnection LLC publishes its interconnection queue publicly.
This adapter fetches queue data and stores relevant entries (focusing on
large-load and generation projects that indicate datacenter buildout) into
the generator_permits table.

PJM territory covers: VA, MD, DC, NJ, PA, OH, WV, KY, IL, IN, MI, NC, TN, DE.

Coverage:
  - PJM states: 'partial'
  - Other states: 'pending' (written by the coverage seed, not this adapter)
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
from datetime import datetime, date

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
    Company,
)

logger = logging.getLogger(__name__)

_PROXIMITY_DEGREES = 0.001

# PJM queue data endpoints
# The public queue is available as a downloadable Excel/CSV from PJM
_PJM_QUEUE_URL = "https://services.pjm.com/PJMPlanningApi/api/Queue/ExportToXls"
# Fallback: the JSON API (if available)
_PJM_QUEUE_JSON_URL = "https://services.pjm.com/PJMPlanningApi/api/Queue"

# States in PJM territory
PJM_STATES = frozenset([
    "VA", "MD", "DC", "NJ", "PA", "OH", "WV", "KY",
    "IL", "IN", "MI", "NC", "TN", "DE",
])

# Keywords that indicate datacenter-related interconnection requests
_DC_KEYWORDS = re.compile(
    r"data\s*center|hyperscale|cloud|colocation|colo|"
    r"digital\s*realty|equinix|cyrusone|qts|microsoft|google|amazon|meta|oracle|"
    r"large\s*load|behind.the.meter",
    re.I,
)

# Minimum MW threshold to consider a project relevant
_MIN_MW_THRESHOLD = 10


class PjmIsoAdapter:
    """
    PJM Interconnection Queue ingestion adapter.

    Fetches the public queue, filters for datacenter-relevant projects,
    and upserts into generator_permits.
    """

    adapter_name = "PJM Interconnection Queue"
    adapter_id = "pjm_iso"
    adapter_version = "1.0.0"
    pillar = "iso_queues"
    source_id = "pjm_iso"
    declared_status = "partial"
    coverage_scope_states = PJM_STATES

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(4)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=120.0, write=10.0, pool=15.0),
                follow_redirects=True,
                headers={
                    "User-Agent": "Datacenter Intelligence Platform research@oracle.com",
                    "Accept": "application/json, text/csv, */*",
                },
            )
        return self._client

    @stamina.retry(on=httpx.TransportError, attempts=3, wait_initial=2.0)
    async def _rate_limited_get(self, url: str, params: dict | None = None) -> httpx.Response:
        """Rate-limited GET that returns the full Response object."""
        async with self._semaphore:
            await asyncio.sleep(0.5)
            client = await self._get_client()
            resp = await client.get(url, params=params or {})
            resp.raise_for_status()
            return resp

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Fetch PJM queue data
    # ------------------------------------------------------------------

    async def _fetch_queue_json(self) -> list[dict]:
        """
        Try the PJM Planning API JSON endpoint first.
        Falls back to CSV download if JSON is unavailable.
        """
        # Attempt JSON API
        try:
            resp = await self._rate_limited_get(_PJM_QUEUE_JSON_URL)
            data = resp.json()
            # PJM API may wrap results
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("items", data.get("data", data.get("results", [])))
        except (httpx.HTTPStatusError, ValueError) as exc:
            logger.info(
                "pjm_iso.json_api_unavailable",
                extra={"error": str(exc)},
            )

        # Fallback: try CSV/Excel download
        return await self._fetch_queue_csv()

    async def _fetch_queue_csv(self) -> list[dict]:
        """Download the PJM queue as CSV and parse it."""
        try:
            resp = await self._rate_limited_get(_PJM_QUEUE_URL)
            content = resp.text

            # Parse CSV
            reader = csv.DictReader(io.StringIO(content))
            return list(reader)
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "pjm_iso.csv_download_error",
                extra={"status": exc.response.status_code},
            )
            return []
        except csv.Error as exc:
            logger.warning(
                "pjm_iso.csv_parse_error",
                extra={"error": str(exc)},
            )
            return []

    # ------------------------------------------------------------------
    # Normalize and filter
    # ------------------------------------------------------------------

    def _is_relevant(self, record: dict) -> bool:
        """
        Check if a queue entry is relevant to datacenter intelligence.
        Considers project name, fuel type, MW size, and customer info.
        """
        # Check text fields for datacenter keywords
        text_fields = [
            record.get("Project Name", ""),
            record.get("project_name", ""),
            record.get("Customer Name", ""),
            record.get("customer_name", ""),
            record.get("Fuel", ""),
            record.get("fuel", ""),
            record.get("County", ""),
            record.get("county", ""),
        ]
        combined_text = " ".join(str(f) for f in text_fields if f)
        if _DC_KEYWORDS.search(combined_text):
            return True

        # Large load interconnections (>100 MW) are often datacenters
        mw = self._extract_mw(record)
        if mw and mw >= 100:
            return True

        return False

    def _extract_mw(self, record: dict) -> float | None:
        """Extract MW value from various possible field names."""
        for key in ["MFO", "MW Capacity", "mw_capacity", "Capacity (MW)",
                     "MW", "mw", "Max Facility Output"]:
            val = record.get(key)
            if val is not None:
                try:
                    return float(str(val).replace(",", ""))
                except (ValueError, TypeError):
                    continue
        return None

    def _extract_state(self, record: dict) -> str | None:
        """Extract state code from queue record."""
        for key in ["State", "state", "State Code", "state_code"]:
            val = record.get(key)
            if val and len(str(val).strip()) == 2:
                return str(val).strip().upper()

        # Try to extract from county/location
        county = record.get("County", "") or record.get("county", "")
        # PJM often formats as "County, ST"
        parts = str(county).split(",")
        if len(parts) >= 2:
            st = parts[-1].strip().upper()
            if len(st) == 2 and st in PJM_STATES:
                return st
        return None

    def _normalize_record(self, record: dict) -> dict | None:
        """Convert a PJM queue entry into a GeneratorPermit-shaped dict."""
        # Get queue position / project number as unique ID
        queue_id = (
            record.get("Queue Number", "")
            or record.get("queue_number", "")
            or record.get("Queue Position", "")
            or record.get("queue_position", "")
            or record.get("Project Number", "")
            or record.get("project_number", "")
        )
        if not queue_id:
            return None
        queue_id = str(queue_id).strip()

        project_name = (
            record.get("Project Name", "")
            or record.get("project_name", "")
            or record.get("Name", "")
        )
        customer = (
            record.get("Customer Name", "")
            or record.get("customer_name", "")
            or record.get("Developer", "")
        )

        mw = self._extract_mw(record)
        state = self._extract_state(record)
        fuel = record.get("Fuel", "") or record.get("fuel", "") or record.get("Fuel Type", "")

        # Parse submitted date
        submitted = (
            record.get("Queue Date", "")
            or record.get("queue_date", "")
            or record.get("Submitted Date", "")
        )
        issued_date = None
        if submitted:
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
                try:
                    issued_date = datetime.strptime(str(submitted).strip()[:19], fmt).date()
                    break
                except ValueError:
                    continue

        status = (
            record.get("Status", "")
            or record.get("status", "")
            or record.get("Queue Status", "")
        )

        return {
            "source": self.source_id,
            "source_permit_id": f"PJM-{queue_id}",
            "facility_name": str(project_name).strip() if project_name else None,
            "permittee_raw_name": str(customer).strip() if customer else None,
            "state_code": state,
            "rated_mw_total": mw,
            "fuel_type": str(fuel).strip()[:50] if fuel else None,
            "permit_status": str(status).strip()[:50] if status else "queued",
            "issued_date": issued_date,
            "confidence": 0.70,
            "raw_payload": record,
        }

    async def _match_site(self, session: AsyncSession, lat: float, lon: float) -> int | None:
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

    async def _find_company(self, session: AsyncSession, name: str) -> int | None:
        if not name:
            return None
        stmt = select(Company.id).where(Company.canonical_name == name).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    async def run(self, session: AsyncSession) -> dict:
        """Fetch PJM queue, filter relevant entries, upsert into generator_permits."""
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
            raw_queue = await self._fetch_queue_json()
            records_fetched = len(raw_queue)
            logger.info("pjm_iso.queue_fetched", extra={"total": records_fetched})

            # Filter to relevant entries
            relevant = [r for r in raw_queue if self._is_relevant(r)]
            logger.info(
                "pjm_iso.relevant_filtered",
                extra={"total": records_fetched, "relevant": len(relevant)},
            )

            for entry in relevant:
                normalized = self._normalize_record(entry)
                if not normalized:
                    records_skipped += 1
                    continue

                try:
                    stmt = pg_insert(GeneratorPermit).values(**normalized)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["source", "source_permit_id"],
                        set_={
                            "facility_name": stmt.excluded.facility_name,
                            "permittee_raw_name": stmt.excluded.permittee_raw_name,
                            "state_code": stmt.excluded.state_code,
                            "rated_mw_total": stmt.excluded.rated_mw_total,
                            "fuel_type": stmt.excluded.fuel_type,
                            "permit_status": stmt.excluded.permit_status,
                            "raw_payload": stmt.excluded.raw_payload,
                            "updated_at": datetime.utcnow(),
                        },
                    )
                    await session.execute(stmt)
                    records_stored += 1

                except Exception as exc:
                    logger.error(
                        "pjm_iso.upsert_error",
                        extra={
                            "queue_id": normalized.get("source_permit_id"),
                            "error_class": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                    records_skipped += 1
                    errors.append({
                        "queue_id": normalized.get("source_permit_id"),
                        "error": str(exc),
                    })

            # Write coverage rows for each PJM state
            await self._write_coverage(session, records_stored)

            run_record.status = "success" if not errors else "partial_failure"
            run_record.completed_at = datetime.utcnow()
            run_record.records_fetched = records_fetched
            run_record.records_stored = records_stored
            run_record.records_skipped = records_skipped
            run_record.records_normalized = len(relevant)
            run_record.error_log = {"errors": errors} if errors else None
            await session.flush()

        except Exception as exc:
            run_record.status = "failure"
            run_record.completed_at = datetime.utcnow()
            run_record.error_log = {"fatal": str(exc)}
            await session.flush()
            logger.error(
                "pjm_iso.run_fatal_error",
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
        """Write data_coverage rows for each PJM state."""
        for state in PJM_STATES:
            stmt = pg_insert(DataCoverage).values(
                pillar=self.pillar,
                state_code=state,
                source=self.source_id,
                coverage_status=self.declared_status,
                record_count=record_count,  # total across all PJM states
                last_ingested_at=datetime.utcnow(),
                freshness_sla_hours=168,  # weekly
                notes="PJM interconnection queue — datacenter-relevant entries",
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
