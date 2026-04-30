"""
Anomalies endpoints — Phase 2 (AC5).
Prefix: /api/anomalies

Returns recent ±2σ deviations detected by agents.anomaly_detector.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import select, desc

from db.session import async_session_factory
from db.models import Anomaly
from schemas.common import CoverageEnvelope, CoverageMeta, LineageMeta

MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


def _serialize(row: Anomaly) -> dict:
    return {
        "id": row.id,
        "metric_kind": row.metric_kind,
        "dimension": row.dimension,
        "period_end": row.period_end.isoformat() if row.period_end else None,
        "value": row.value,
        "baseline_mean": row.baseline_mean,
        "baseline_stddev": row.baseline_stddev,
        "z_score": row.z_score,
        "direction": row.direction,
        "sample_size": row.sample_size,
        "note": row.note,
        "detected_at": row.detected_at.isoformat() if row.detected_at else None,
    }


@router.get("/recent")
async def recent(
    days: int = Query(default=90, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=500),
):
    """Return anomalies whose period_end is within the last `days` days,
    newest-first. Limited to `limit` rows.
    """
    if MOCK_ENABLED:
        return CoverageEnvelope(
            data={"data": [
                {"metric_kind": "permit_filings", "dimension": "VA",
                 "period_end": "2026-04-26", "value": 7, "z_score": 2.4,
                 "direction": "spike", "note": "VA permit filings spiked vs trailing 12-week mean"},
            ]},
            lineage=LineageMeta(
                source_url="mock", retrieved_at=datetime.utcnow(),
                parser_version="anomaly-v1", confidence=0.5,
            ),
            coverage=CoverageMeta(pillar="anomalies"),
        )

    cutoff = (datetime.utcnow() - timedelta(days=days)).date()
    async with async_session_factory() as session:
        stmt = (select(Anomaly)
                .where(Anomaly.period_end >= cutoff)
                .order_by(desc(Anomaly.period_end), desc(Anomaly.detected_at))
                .limit(limit))
        rows = (await session.execute(stmt)).scalars().all()

    serialized = [_serialize(r) for r in rows]
    return CoverageEnvelope(
        data={"data": serialized, "count": len(serialized)},
        lineage=LineageMeta(
            source_url="internal://anomaly-detector",
            retrieved_at=datetime.utcnow(),
            parser_version="anomaly-v1",
            confidence=0.7 if serialized else 0.0,
        ),
        coverage=CoverageMeta(
            pillar="anomalies",
            freshness_status="ok" if serialized else "unknown",
        ),
    )
