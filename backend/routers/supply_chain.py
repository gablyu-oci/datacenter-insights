"""
Supply-chain endpoints: NICs/optics and TSMC data.
Prefix: /api/supply-chain

Legacy paths (/api/nics, /api/tsmc) are mounted in main.py as separate
routers sharing the same handler functions.

When MOCK_DATA=1, returns mock data.
When MOCK_DATA=0, returns CoverageEnvelope with empty data and coverage
explaining what is missing. Does NOT fall back to random generation.
"""
from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter

from schemas.common import CoverageEnvelope, CoverageMeta, LineageMeta

MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"

router = APIRouter(prefix="/api/supply-chain", tags=["supply-chain"])

# Also expose legacy paths without prefix (mounted from main.py)
legacy_router = APIRouter(tags=["supply-chain-legacy"])


def _nics_response():
    if MOCK_ENABLED:
        from data.mock_data import get_nics_optics_data

        return CoverageEnvelope(
            data=get_nics_optics_data(),
            lineage=LineageMeta(
                source_url="mock",
                retrieved_at=datetime.utcnow(),
                parser_version="mock-v1",
                confidence=0.5,
            ),
            coverage=CoverageMeta(pillar="nics_optics"),
        )

    return CoverageEnvelope(
        data={
            "nic_shipments": [],
            "optics_shipments": [],
            "correlation_score": None,
        },
        lineage=LineageMeta(
            source_url="n/a",
            retrieved_at=datetime.utcnow(),
            parser_version="nics-v1.0.0",
            confidence=0.0,
        ),
        coverage=CoverageMeta(
            pillar="nics_optics",
            states_included=[],
            states_excluded_with_reason={
                "ALL": "NIC/optics shipment data requires vendor import feeds (Phase 2)"
            },
            freshness_status="unknown",
        ),
    )


def _tsmc_response():
    if MOCK_ENABLED:
        from data.mock_data import get_tsmc_data

        return CoverageEnvelope(
            data=get_tsmc_data(),
            lineage=LineageMeta(
                source_url="mock",
                retrieved_at=datetime.utcnow(),
                parser_version="mock-v1",
                confidence=0.5,
            ),
            coverage=CoverageMeta(pillar="tsmc"),
        )

    return CoverageEnvelope(
        data={
            "capacity": [],
            "packaging": [],
        },
        lineage=LineageMeta(
            source_url="n/a",
            retrieved_at=datetime.utcnow(),
            parser_version="tsmc-v1.0.0",
            confidence=0.0,
        ),
        coverage=CoverageMeta(
            pillar="tsmc",
            states_included=[],
            states_excluded_with_reason={
                "ALL": "TSMC capacity data requires earnings transcript extraction (Phase 2)"
            },
            freshness_status="unknown",
        ),
    )


@router.get("/nics")
def nics_new():
    return _nics_response()


@router.get("/tsmc")
def tsmc_new():
    return _tsmc_response()


# Legacy endpoints (mounted at root by main.py)
@legacy_router.get("/api/nics")
def nics_legacy():
    return _nics_response()


@legacy_router.get("/api/tsmc")
def tsmc_legacy():
    return _tsmc_response()
