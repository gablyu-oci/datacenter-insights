"""
GPU supply endpoints.
Prefix: /api/gpu

When MOCK_DATA=1, returns mock GPU data.
When MOCK_DATA=0, returns a CoverageEnvelope with empty data and coverage
explaining what is missing. Does NOT fall back to random generation.
"""
from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter

from schemas.common import CoverageEnvelope, CoverageMeta, LineageMeta

MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"

router = APIRouter(prefix="/api/gpu", tags=["gpu"])


@router.get("/supply")
def gpu_supply():
    if MOCK_ENABLED:
        from data.mock_data import get_gpu_data

        return CoverageEnvelope(
            data=get_gpu_data(),
            lineage=LineageMeta(
                source_url="mock",
                retrieved_at=datetime.utcnow(),
                parser_version="mock-v1",
                confidence=0.5,
            ),
            coverage=CoverageMeta(pillar="gpu_supply"),
        )

    return CoverageEnvelope(
        data={
            "shipped": [],
            "deployed": [],
            "inventory": [],
            "revenue_estimates": [],
        },
        lineage=LineageMeta(
            source_url="n/a",
            retrieved_at=datetime.utcnow(),
            parser_version="gpu-v1.0.0",
            confidence=0.0,
        ),
        coverage=CoverageMeta(
            pillar="gpu_supply",
            states_included=[],
            states_excluded_with_reason={
                "ALL": "GPU supply data requires NVIDIA earnings transcript extraction (Phase 2)"
            },
            freshness_status="unknown",
        ),
    )
