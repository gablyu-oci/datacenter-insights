"""
Loudoun County, VA -- county building-permit adapter (the user-fixes AC3).

Data source
-----------
Loudoun County publishes a curated "Data Center Building Outlines" feature
service on its ArcGIS Online tenant. Individual building permits per se are
not open as JSON (the LOGIS ArcGIS server's permit endpoints 404 publicly),
but this dataset is the closest free, structured proxy: each feature is a
single data-center building, named with its building-permit reference
(e.g. "Data Center - XXXX BP (1.79 Acres)").

  Endpoint:
    https://services1.arcgis.com/MxjRokvPm7bjslyR/arcgis/rest/services/
    Data_Center_Building_Outlines/FeatureServer/0/query

  We page with resultRecordCount=200 + resultOffset, pulling polygon
  geometry plus attributes. Each row maps to one BuildingPermit:
    * source_permit_id  = FID (stable per feature)
    * permit_type       = "DATA_CENTER_BUILDING"
    * county/state      = "Loudoun" / "VA"
    * latitude/longitude = polygon centroid (Web Mercator -> WGS84)
    * raw_payload       = full feature attributes + ring vertex count
    * permit_status     = "issued" (these polygons represent built or in
                          construction data centers; LoudounGIS only
                          publishes them once permitted)

Already-tried alternates that didn't pan out (one-line each):
    * https://logis.loudoun.gov/arcgis/rest/services/OpenData/
      ApprovedDevPipeline/MapServer/0/query  -> 404 (service decommissioned)
    * https://opendata.loudoun.gov/api/feed/dcat-us/1.1.json -> 404
"""
from __future__ import annotations

import logging
import math
import re
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BuildingPermit

logger = logging.getLogger(__name__)

SOURCE_ID = "loudoun_va"
COUNTY = "Loudoun"
STATE = "VA"
USER_AGENT = (
    "strategic-insights-tool/1.0 (research; research@oracle.com)"
)

DATACENTER_RE = re.compile(r"data\s*[-_]?\s*center|datacenter|\bDC\b", re.I)

ENDPOINT = (
    "https://services1.arcgis.com/MxjRokvPm7bjslyR/arcgis/rest/services/"
    "Data_Center_Building_Outlines/FeatureServer/0/query"
)
PAGE_SIZE = 200
MAX_PAGES = 25  # 200 * 25 = 5000 features hard cap


def _web_mercator_to_lonlat(x: float, y: float) -> tuple[float, float]:
    """Convert EPSG:3857 (Web Mercator) coords to WGS84 lon/lat."""
    lon = (x / 6378137.0) * (180.0 / math.pi)
    lat = (
        math.atan(math.exp(y / 6378137.0)) * 360.0 / math.pi - 90.0
    )
    return lon, lat


def _polygon_centroid(rings: list[list[list[float]]]) -> tuple[float | None, float | None]:
    """Crude centroid: average of all ring vertices in the first ring."""
    if not rings or not rings[0]:
        return None, None
    pts = rings[0]
    if not pts:
        return None, None
    sx = sum(p[0] for p in pts) / len(pts)
    sy = sum(p[1] for p in pts) / len(pts)
    lon, lat = _web_mercator_to_lonlat(sx, sy)
    return lat, lon


async def _fetch_page(client: httpx.AsyncClient, offset: int) -> dict[str, Any]:
    params = {
        "where": "1=1",
        "outFields": "*",
        "f": "json",
        "resultRecordCount": str(PAGE_SIZE),
        "resultOffset": str(offset),
        "returnGeometry": "true",
        "outSR": "3857",
    }
    resp = await client.get(ENDPOINT, params=params)
    resp.raise_for_status()
    return resp.json()


def _matches_datacenter(attrs: dict[str, Any]) -> bool:
    """All rows in this feed are inherently data center buildings, but we
    apply the regex defensively in case Loudoun later widens the dataset."""
    blob = " ".join(
        str(attrs.get(k) or "") for k in ("Name", "FolderPath", "Snippet", "PopupInfo")
    )
    return bool(DATACENTER_RE.search(blob))


def _normalize(feature: dict[str, Any]) -> dict[str, Any] | None:
    attrs = feature.get("attributes") or {}
    fid = attrs.get("FID")
    if fid is None:
        return None
    if not _matches_datacenter(attrs):
        return None

    lat, lon = _polygon_centroid((feature.get("geometry") or {}).get("rings") or [])

    name = str(attrs.get("Name") or "").strip()
    return {
        "source": SOURCE_ID,
        "source_permit_id": f"FID-{fid}",
        "county": COUNTY,
        "state": STATE,
        "jurisdiction": "Loudoun County",
        "address": name or None,
        "latitude": lat,
        "longitude": lon,
        "permit_type": "DATA_CENTER_BUILDING",
        "permit_status": "issued",
        "applicant_name": None,
        "raw_payload": {
            "attributes": attrs,
            "geometry_vertex_count": len(
                ((feature.get("geometry") or {}).get("rings") or [[]])[0]
            ),
            "_endpoint": ENDPOINT,
        },
    }


async def fetch_and_store(session: AsyncSession) -> dict[str, Any]:
    """Public entry point. Pages Loudoun's data-center-buildings feature
    layer and upserts each row into building_permits.
    """
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
                payload = await _fetch_page(client, offset)
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                logger.warning(
                    "loudoun.fetch_error offset=%s err=%s", offset, exc,
                )
                errors += 1
                break

            features = payload.get("features", []) or []
            if not features:
                break
            fetched += len(features)

            for feat in features:
                try:
                    norm = _normalize(feat)
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
                    logger.error(
                        "loudoun.row_error err=%s", exc, exc_info=False,
                    )
                    errors += 1

            if not payload.get("exceededTransferLimit"):
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
