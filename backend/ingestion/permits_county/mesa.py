"""
City of Mesa, AZ -- county/city building-permit adapter (Karan-fixes AC3).

Data source
-----------
Mesa, AZ (in Maricopa County) publishes its full Building Permits dataset
on Socrata (data.mesaaz.gov) at resource id `dzpk-hxfb`. The original
hint in the brief (`efpa-7bbb`) returned 404 -- discovered the active id
by querying the catalog endpoint:

    https://data.mesaaz.gov/api/catalog/v1?q=permits
        &domains=data.mesaaz.gov&search_context=data.mesaaz.gov

We use the SODA $where clause to filter description_of_work for
data-center variants. The endpoint has no auth requirement at low rates.

  Endpoint:
    https://data.mesaaz.gov/resource/dzpk-hxfb.json
        ?$where=upper(description_of_work) like '%DATA CENTER%'
              OR upper(description_of_work) like '%DATACENTER%'
        &$limit=200&$offset=N

NB: Mesa is a *city* in Maricopa County, but Karan's brief specified
'mesa_az' as the source id and the dataset is the city-issued permit
feed. We store county="Maricopa" and jurisdiction="City of Mesa".
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BuildingPermit

logger = logging.getLogger(__name__)

SOURCE_ID = "mesa_az"
COUNTY = "Maricopa"
STATE = "AZ"
USER_AGENT = "strategic-insights-tool/1.0 (research; karan@oracle.com)"

DATACENTER_RE = re.compile(r"data\s*[-_]?\s*center|datacenter|\bDC\b", re.I)

ENDPOINT = "https://data.mesaaz.gov/resource/dzpk-hxfb.json"
# Server-side filter: cuts ~600k rows down to a few hundred matches.
SOQL_WHERE = (
    "upper(description_of_work) like '%DATA CENTER%' "
    "OR upper(description_of_work) like '%DATACENTER%' "
    "OR upper(description_of_work) like '%DATA-CENTER%'"
)
PAGE_SIZE = 1000
MAX_PAGES = 20


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    s = str(value).split("T")[0].strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    f = _to_float(value)
    return int(f) if f is not None else None


async def _fetch_page(client: httpx.AsyncClient, offset: int) -> list[dict[str, Any]]:
    params = {
        "$where": SOQL_WHERE,
        "$limit": str(PAGE_SIZE),
        "$offset": str(offset),
        "$order": "issued_date DESC NULLS LAST",
    }
    resp = await client.get(ENDPOINT, params=params)
    resp.raise_for_status()
    return resp.json()


def _normalize(rec: dict[str, Any]) -> dict[str, Any] | None:
    permit_id = rec.get("permit_number") or rec.get("rowid")
    if not permit_id:
        return None

    description = rec.get("description_of_work") or ""
    if not DATACENTER_RE.search(description):
        # Defense-in-depth: skip if SoQL match was too broad
        return None

    location = rec.get("location") or {}
    coords = location.get("coordinates") if isinstance(location, dict) else None
    lat = lon = None
    if coords and isinstance(coords, list) and len(coords) >= 2:
        lon, lat = float(coords[0]), float(coords[1])
    else:
        lat = _to_float(rec.get("latitude"))
        lon = _to_float(rec.get("longitude"))

    return {
        "source": SOURCE_ID,
        "source_permit_id": str(permit_id)[:80],
        "county": COUNTY,
        "state": STATE,
        "jurisdiction": "City of Mesa",
        "address": rec.get("property_address"),
        "latitude": lat,
        "longitude": lon,
        "permit_type": (rec.get("permit_type") or rec.get("type_of_work") or "")[:80] or None,
        "permit_status": (rec.get("status") or "")[:40] or None,
        "applied_date": _parse_date(rec.get("opened_date")),
        "issued_date": _parse_date(rec.get("issued_date")),
        "completed_date": _parse_date(rec.get("finaled_date")),
        "valuation_usd": _to_float(rec.get("total_valuation") or rec.get("job_value") or rec.get("icc_value")),
        "square_footage": _to_int(rec.get("total_square_feet")),
        "applicant_name": (rec.get("applicant") or rec.get("contractor_name") or "")[:200] or None,
        "raw_payload": {**rec, "_endpoint": ENDPOINT},
    }


async def fetch_and_store(session: AsyncSession) -> dict[str, Any]:
    fetched = 0
    stored = 0
    errors = 0
    skipped = 0

    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    ) as client:
        offset = 0
        for _ in range(MAX_PAGES):
            try:
                rows = await _fetch_page(client, offset)
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                logger.warning("mesa.fetch_error offset=%s err=%s", offset, exc)
                errors += 1
                break

            if not rows:
                break
            fetched += len(rows)

            for rec in rows:
                try:
                    norm = _normalize(rec)
                    if norm is None:
                        skipped += 1
                        continue

                    stmt = pg_insert(BuildingPermit).values(**norm)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["source", "source_permit_id"],
                        set_={
                            "raw_payload": stmt.excluded.raw_payload,
                            "retrieved_at": datetime.utcnow(),
                        },
                    )
                    await session.execute(stmt)
                    stored += 1
                except Exception as exc:
                    logger.error("mesa.row_error err=%s", exc, exc_info=False)
                    errors += 1

            if len(rows) < PAGE_SIZE:
                break
            offset += PAGE_SIZE

        await session.commit()

    return {
        "source": SOURCE_ID,
        "fetched": fetched,
        "stored": stored,
        "errors": errors,
        "skipped_non_datacenter": skipped,
    }
