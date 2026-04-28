"""
EDGAR XBRL frames proxy -- Phase 1A.
Prefix: /api/edgar

Proxies requests to data.sec.gov/api/xbrl/frames/ with a simple
in-memory cache (12-hour TTL).
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException

from config import settings
from schemas.common import LineageEnvelope, LineageMeta

router = APIRouter(prefix="/api/edgar", tags=["edgar"])

# Simple TTL cache: key -> (data, timestamp)
_CACHE: Dict[str, Tuple[Any, float]] = {}
_CACHE_TTL_SECONDS = 12 * 60 * 60  # 12 hours


def _cache_get(key: str) -> Optional[Any]:
    """Return cached value if present and not expired."""
    entry = _CACHE.get(key)
    if entry is None:
        return None
    data, ts = entry
    if time.time() - ts > _CACHE_TTL_SECONDS:
        del _CACHE[key]
        return None
    return data


def _cache_set(key: str, data: Any) -> None:
    """Store value in cache with current timestamp."""
    _CACHE[key] = (data, time.time())


@router.get("/frames/{concept}/{period}")
async def edgar_frames(concept: str, period: str):
    """
    Pass-through proxy to SEC EDGAR XBRL frames API.

    URL pattern: https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/{period}.json

    Results are cached in-memory for 12 hours to respect SEC rate limits.
    """
    cache_key = f"{concept}:{period}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return LineageEnvelope(
            data=cached,
            lineage=LineageMeta(
                source_url=f"https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/{period}.json",
                retrieved_at=datetime.utcnow(),
                parser_version="edgar-frames-proxy-v1.0.0",
                confidence=1.0,
            ),
        )

    url = f"https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/{period}.json"
    headers = {
        "User-Agent": settings.edgar_user_agent,
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"SEC EDGAR returned 404 for concept={concept}, period={period}",
            )
        if resp.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail="SEC EDGAR rate limit exceeded. Try again later.",
            )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"SEC EDGAR returned status {exc.response.status_code}",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach SEC EDGAR: {exc}",
        )

    _cache_set(cache_key, data)

    return LineageEnvelope(
        data=data,
        lineage=LineageMeta(
            source_url=url,
            retrieved_at=datetime.utcnow(),
            parser_version="edgar-frames-proxy-v1.0.0",
            confidence=1.0,
        ),
    )
