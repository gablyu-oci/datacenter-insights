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
from db.session import async_session_factory
from agents.triangulation import compute_l1, compute_l2

MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"

router = APIRouter(prefix="/api/triangulation", tags=["triangulation"])


@router.get("/l1")
async def triangulation_l1():
    """Layer 1 — contracted-power GW per company × state.

    L1 only. L2-L4 require paid data sources (NVIDIA shipments, NIC/optics
    vendor data, county building permits) which we have not procured.
    """
    if MOCK_ENABLED:
        mock = [
            {"company": "Microsoft", "state": "VA",
             "gw_total": 2.45,
             "sources": [{"type": "sites", "count": 14, "mw": 1200.0},
                         {"type": "deals", "count": 2, "mw": 1250.0}],
             "confidence": 0.65},
            {"company": "Amazon", "state": "VA",
             "gw_total": 1.82,
             "sources": [{"type": "sites", "count": 11, "mw": 950.0},
                         {"type": "deals", "count": 1, "mw": 870.0}],
             "confidence": 0.65},
            {"company": "Alphabet", "state": "TX",
             "gw_total": 0.92,
             "sources": [{"type": "sites", "count": 4, "mw": 920.0}],
             "confidence": 0.50},
        ]
        return CoverageEnvelope(
            data={"data": mock,
                  "note": "Layer 1 (Contracted Power) only. L2-L4 require paid data sources."},
            lineage=LineageMeta(
                source_url="mock",
                retrieved_at=datetime.utcnow(),
                parser_version="triangulation-l1-v1",
                confidence=0.5,
            ),
            coverage=CoverageMeta(pillar="triangulation"),
        )

    async with async_session_factory() as session:
        records = await compute_l1(session)

    return CoverageEnvelope(
        data={
            "data": records,
            "note": (
                "Layer 1 (Contracted Power) only — sums sites.power_capacity_mw + "
                "curated_deals.capacity_mw + edgar_extractions.capacity_mw, "
                "deduplicated by (canonicalized buyer, state). "
                "L2-L4 require paid data sources (NVIDIA shipments, NIC/optics "
                "vendor disclosures, county building permits) — see roadmap."
            ),
            "layers_implemented": ["L1"],
            "layers_pending": ["L2", "L3", "L4"],
        },
        lineage=LineageMeta(
            source_url="internal://triangulation-l1",
            retrieved_at=datetime.utcnow(),
            parser_version="triangulation-l1-v1",
            confidence=0.65 if records else 0.0,
        ),
        coverage=CoverageMeta(
            pillar="triangulation",
            states_included=sorted({r["state"] for r in records if r["state"] != "ALL"}),
            freshness_status="ok" if records else "unknown",
        ),
    )


@router.get("/l2")
async def triangulation_l2():
    """Layer 2 — compute-demand layer.

    Translates the most recent NVIDIA Data Center segment revenue into
    an inferred GPU-units count and an inferred deployable-compute GW
    estimate, then distributes that GW across {Microsoft, Amazon,
    Google, Oracle, Meta} proportionally to their contracted_gw from
    curated_deals. The gap between contracted_gw and implied_compute_gw
    is the surfaced signal.

    Unit economics (H100/B200 power, ASP, utilization, overhead) are
    explicitly model assumptions, not vendor disclosures — see the
    `assumptions` block in the response.
    """
    async with async_session_factory() as session:
        l2 = await compute_l2(session)

    has_data = l2.get("nvidia_dc_revenue_usd") is not None
    return CoverageEnvelope(
        data=l2,
        lineage=LineageMeta(
            source_url="internal://triangulation-l2",
            retrieved_at=datetime.utcnow(),
            parser_version="l2-v1",
            confidence=0.55 if has_data else 0.0,
        ),
        coverage=CoverageMeta(
            pillar="triangulation",
            freshness_status="ok" if has_data else "unknown",
            states_excluded_with_reason={
                "ALL": (
                    "L2 derived from latest NVIDIA Data Center segment "
                    "revenue in edgar_extractions; H100/B200 unit "
                    "economics are model assumptions, not vendor "
                    "disclosures. Per-hyperscaler split distributes "
                    "inferred_compute_gw proportionally to contracted_gw "
                    "across {Microsoft, Amazon, Google, Oracle, Meta}, "
                    "since authoritative customer-concentration data is "
                    "not available in free SEC filings."
                )
            },
        ),
    )


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
