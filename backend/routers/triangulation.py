"""
Triangulation (cross-signal validation) endpoints.
Prefix: /api/triangulation

When MOCK_DATA=1, returns mock triangulation data.
When MOCK_DATA=0, returns CoverageEnvelope with empty data and coverage
explaining what is missing. Does NOT fall back to random generation.
"""
from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter

from schemas.common import CoverageEnvelope, CoverageMeta, LineageMeta

MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"

router = APIRouter(prefix="/api/triangulation", tags=["triangulation"])


@router.get("/")
async def triangulation():
    if MOCK_ENABLED:
        from data.mock_data import get_triangulation_data

        return CoverageEnvelope(
            data={"data": get_triangulation_data()},
            lineage=LineageMeta(
                source_url="mock",
                retrieved_at=datetime.utcnow(),
                parser_version="mock-v1",
                confidence=0.5,
            ),
            coverage=CoverageMeta(pillar="triangulation"),
        )

    return CoverageEnvelope(
        data={"data": []},
        lineage=LineageMeta(
            source_url="n/a",
            retrieved_at=datetime.utcnow(),
            parser_version="triangulation-v1.0.0",
            confidence=0.0,
        ),
        coverage=CoverageMeta(
            pillar="triangulation",
            states_included=[],
            states_excluded_with_reason={
                "ALL": "Triangulation requires cross-signal data from multiple pillars (Phase 2)"
            },
            freshness_status="unknown",
        ),
    )
