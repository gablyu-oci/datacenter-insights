"""
Grant County, WA / City of Quincy -- county building-permit adapter
(the user-fixes AC3).

Status: NO FREE JSON ENDPOINT FOUND.

Endpoints attempted (2026-04-30):
  * https://www.grantcountywa.gov           -- HTML-only permits portal,
                                               no machine-readable feed
  * https://data.wa.gov ydr8-5enu/c2es-76ed -- those are Chicago / OSCN
                                               federated entries, not WA
  * https://hub.arcgis.com (q="grant county wa permits")
                                            -- only road-map and parcel
                                               atlas layers, no permit
                                               feature service
  * grantcountywa.maps.arcgis.com           -- public viewer with no
                                               REST query endpoint
                                               exposed for permits
  * Quincy WA building permits              -- the city uses an EnerGov
                                               / TylerTech permit portal
                                               that requires a session
                                               and CAPTCHA; no JSON

Quincy/Grant County is the densest data-center cluster in WA (Microsoft,
H5, Sabey) so a future ticket should either:
  (a) FOIA Grant County Planning for a CSV drop, or
  (b) scrape the EnerGov HTML with a periodic rotating session token.

Per AC3 brief: "if after 10 minutes you can't find a JSON endpoint,
document the attempt ... and have it return an empty list with
reason='no_free_api_found'." Returning an empty result so the weekly
job logs the gap without hard-failing.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

SOURCE_ID = "grantwa"


async def fetch_and_store(session: AsyncSession) -> dict[str, Any]:
    """No-op adapter -- documents the lack of a free API.

    Intentionally returns the same envelope shape as loudoun/mesa so the
    pipeline-runner summary line is uniform. `reason` is added so log
    consumers can distinguish "found no rows" from "couldn't even try".
    """
    logger.info(
        "grantwa.fetch_and_store: no free JSON endpoint -- skipping. "
        "See ingestion/permits_county/grantwa.py docstring for rationale.",
    )
    return {
        "source": SOURCE_ID,
        "fetched": 0,
        "stored": 0,
        "errors": 0,
        "skipped_non_datacenter": 0,
        "reason": "no_free_api_found",
    }
