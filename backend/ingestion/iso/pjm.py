"""
PJM ISO Interconnection Queue Adapter -- Phase 1.5.

PJM Interconnection LLC publishes its full active planning queue as a public
XML feed. We fetch the bulk feed, parse with stdlib xml.etree, and persist
filtered rows to generator_permits.

Phase 1.5 fix (2026-04-29):
  * Retired the services.pjm.com/PJMPlanningApi/api/Queue POST endpoint --
    PJM migrated to Data Miner 2 + the bulk XML feed.
  * Switched to the public bulk XML feed at
    https://www.pjm.com/pjmfiles/media/planning/queues-data/PlanningQueues.xml
    which contains every active <Project> in the queue.

The XML root element is <Projects>; children are <Project>. Field names
include ProjectNumber, Name, CommercialName, State, County, Status,
TransmissionOwner, MWEnergy, MWCapacity, MaximumFacilityOutput, Fuel,
SubmittedDate, ProjectedInServiceDate, ActualInServiceDate.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, date
from xml.etree import ElementTree as ET

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
    Company,
)

logger = logging.getLogger(__name__)

_PROXIMITY_DEGREES = 0.001

# Public bulk XML feed -- Phase 1.5 canonical endpoint
_PJM_QUEUE_XML_URL = (
    "https://www.pjm.com/pjmfiles/media/planning/queues-data/PlanningQueues.xml"
)

# States in PJM territory
PJM_STATES = frozenset([
    "VA", "MD", "DC", "NJ", "PA", "OH", "WV", "KY",
    "IL", "IN", "MI", "NC", "TN", "DE",
])

# Data-center-heavy transmission-owner zones (DOM = Dominion VA, etc.)
_DC_TRANS_OWNERS = frozenset(["DOM", "BGE", "PEPCO", "APS", "JCPL", "ATSI"])

# Hyperscaler / colocation regex catch-all on the project-name fields
_DC_KEYWORDS = re.compile(
    r"data\s*center|hyperscale|cloud|colocation|colo|"
    r"digital\s*realty|equinix|cyrusone|qts|microsoft|google|amazon|meta|oracle|"
    r"large\s*load|behind.the.meter|crusoe|aligned|stack|compass",
    re.I,
)

# Minimum MW threshold for relevance
_MIN_MW_THRESHOLD = 10.0


class PjmIsoAdapter:
    """
    PJM Interconnection Queue ingestion adapter.

    Pulls the public bulk XML feed, parses each <Project>, applies a
    relevance filter (MW > 10 AND TransmissionOwner in DC-heavy zones,
    OR project-name regex match), and upserts into generator_permits.
    """

    adapter_name = "PJM Interconnection Queue"
    adapter_id = "pjm_iso"
    adapter_version = "1.1.0"
    pillar = "iso_queues"
    source_id = "pjm"
    declared_status = "partial"
    coverage_scope_states = PJM_STATES

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(2)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=120.0, write=10.0, pool=15.0),
                follow_redirects=True,
                headers={
                    "User-Agent": "strategic-insights-tool/1.0 (research)",
                    "Accept": "application/xml, text/xml, */*",
                },
            )
        return self._client

    @stamina.retry(on=httpx.TransportError, attempts=3, wait_initial=2.0)
    async def _fetch_xml(self) -> str:
        async with self._semaphore:
            await asyncio.sleep(0.5)
            client = await self._get_client()
            resp = await client.get(_PJM_QUEUE_XML_URL)
            resp.raise_for_status()
            return resp.text

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Parse PJM XML into dicts
    # ------------------------------------------------------------------

    def _parse_xml(self, xml_text: str) -> list[dict]:
        """Parse the PJM PlanningQueues XML into a list of project dicts."""
        try:
            # Strip BOM if present
            if xml_text.startswith("\ufeff"):
                xml_text = xml_text[1:]
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            logger.error("pjm_iso.xml_parse_error", extra={"error": str(exc)})
            return []

        projects: list[dict] = []
        # Root tag is <Projects>; <Project> children. Accept either
        # legacy <PlanningQueues> wrapper too in case PJM ever switches back.
        for elem in root.findall(".//Project") + root.findall(".//PlanningQueues"):
            row: dict = {}
            for child in elem:
                txt = (child.text or "").strip()
                row[child.tag] = txt if txt else None
            if row:
                projects.append(row)
        return projects

    # ------------------------------------------------------------------
    # Relevance filter & normalization
    # ------------------------------------------------------------------

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
        if not s or s.upper() in {"N/A", "NA"}:
            return None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(s[:19], fmt).date()
            except ValueError:
                continue
        return None

    def _extract_mw(self, record: dict) -> float | None:
        for key in ("MWEnergy", "MWCapacity", "MaximumFacilityOutput", "MWInService"):
            mw = self._to_float(record.get(key))
            if mw is not None and mw > 0:
                return mw
        return None

    def _is_relevant(self, record: dict) -> bool:
        """Pass if MW > 10 AND TransOwner in DC zones, OR project-name DC match."""
        mw = self._extract_mw(record)
        owner = (record.get("TransmissionOwner") or "").strip().upper()
        text_blob = " ".join(
            str(record.get(k, "") or "")
            for k in ("Name", "CommercialName", "ProjectNumber", "Fuel", "County")
        )

        if _DC_KEYWORDS.search(text_blob):
            return True
        if mw is not None and mw >= _MIN_MW_THRESHOLD and owner in _DC_TRANS_OWNERS:
            return True
        # Catch large generation interconnections regardless of zone (>= 100 MW)
        if mw is not None and mw >= 100.0:
            return True
        return False

    def _normalize_record(self, record: dict) -> dict | None:
        queue_id = record.get("ProjectNumber") or record.get("Queue")
        if not queue_id:
            return None
        queue_id = str(queue_id).strip()

        project_name = record.get("Name") or record.get("CommercialName")
        # Use commercial name as the permittee proxy (developer)
        permittee = record.get("CommercialName") or record.get("TransmissionOwner") or ""

        mw = self._extract_mw(record)

        state = record.get("State")
        if state and len(state) > 2:
            state = state[:2].upper()

        fuel = record.get("Fuel") or ""

        # Application date = SubmittedDate; effective_date = ActualInServiceDate
        # (or ProjectedInServiceDate as fallback)
        application_date = self._to_date(record.get("SubmittedDate"))
        effective_date = self._to_date(record.get("ActualInServiceDate")) or self._to_date(
            record.get("ProjectedInServiceDate")
        )

        status = (record.get("Status") or "queued").strip()

        return {
            "source": self.source_id,
            "source_permit_id": f"PJM-{queue_id}",
            "facility_name": str(project_name).strip() if project_name else None,
            "permittee_raw_name": str(permittee).strip() if permittee else None,
            "state_code": state,
            "rated_mw_total": mw,
            "fuel_type": str(fuel).strip()[:100] if fuel else None,
            "permit_status": status[:100],
            "issued_date": application_date,
            "expiry_date": effective_date,
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

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    async def run(self, session: AsyncSession) -> dict:
        """Fetch PJM queue XML, filter, normalize, upsert."""
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
                xml_text = await self._fetch_xml()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "pjm_iso.fetch_http_error",
                    extra={"status": exc.response.status_code},
                )
                xml_text = ""
            except httpx.TransportError as exc:
                logger.error("pjm_iso.fetch_transport_error", extra={"error": str(exc)})
                xml_text = ""

            raw_queue = self._parse_xml(xml_text) if xml_text else []
            records_fetched = len(raw_queue)
            logger.info("pjm_iso.queue_fetched", extra={"total": records_fetched})

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

            await self._write_coverage(session, records_stored)
            await self._write_lineage(session, run_record.id, records_stored)

            run_record.status = "success" if records_stored > 0 else (
                "partial_failure" if errors else "success"
            )
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
        for state in PJM_STATES:
            stmt = pg_insert(DataCoverage).values(
                pillar=self.pillar,
                state_code=state,
                source=self.source_id,
                coverage_status=self.declared_status,
                record_count=record_count,
                last_ingested_at=datetime.utcnow(),
                freshness_sla_hours=168,
                notes="PJM interconnection queue (bulk XML feed) -- DC-relevant entries",
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
            source_url=_PJM_QUEUE_XML_URL,
            retrieved_at=datetime.utcnow(),
            parser_version=self.adapter_version,
            confidence=0.70,
            transformation={"method": "pjm_planning_queues_xml"},
        )
        await session.execute(stmt)
