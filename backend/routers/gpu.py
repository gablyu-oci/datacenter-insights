"""
GPU supply endpoints.
Prefix: /api/gpu

Reads pillar='vendor_supply' rows for the GPU-tab vendors (NVIDIA, AMD,
Intel-DCAI). Each row's `excerpt` column carries a JSON-encoded payload
(headline / segment_name / period_end / revenue_usd / inventory_usd /
purchase_commitments_usd / customer_concentration_pct / narrative_excerpt)
written by vendor_supply_extractor.py. We decode and reshape into a
per-vendor per-quarter timeseries.

Power-deal rows (pillar='power_contract') are NEVER returned here — that
data belongs to the Power Tab.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import select, desc

from agents.edgar_agent import FX_TO_USD, vendor_filers_for_tab
from db.session import async_session_factory
from db.models import EdgarExtraction
from schemas.common import CoverageEnvelope, CoverageMeta, LineageMeta

MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"

router = APIRouter(prefix="/api/gpu", tags=["gpu"])


def _decode_payload(excerpt: str | None) -> dict:
    """Parse the JSON payload packed into the `excerpt` column.

    Falls back to an empty dict for legacy rows where excerpt is plain text.
    """
    if not excerpt:
        return {}
    try:
        d = json.loads(excerpt)
        if isinstance(d, dict):
            return d
    except (ValueError, TypeError):
        pass
    return {}


def _convert(amount: float | None, fx: float) -> float | None:
    if amount is None:
        return None
    try:
        return float(amount) * fx
    except (TypeError, ValueError):
        return None


def _row_entry(row: EdgarExtraction, vendor) -> dict:
    payload = _decode_payload(row.excerpt)
    fx = FX_TO_USD.get(getattr(vendor, "reporting_currency", "USD"), 1.0)
    return {
        "company": vendor.display_name if vendor is not None else row.cik,
        "filing_date": row.filing_date.isoformat() if row.filing_date else None,
        "form_type": row.form_type,
        "accession_number": row.accession_number,
        "edgar_url": row.edgar_url,
        "headline": payload.get("headline"),
        "segment_name": payload.get("segment_name"),
        "period_end": payload.get("period_end"),
        "revenue_usd": _convert(payload.get("revenue_usd"), fx),
        "inventory_usd": _convert(payload.get("inventory_usd"), fx),
        "purchase_commitments_usd": _convert(payload.get("purchase_commitments_usd"), fx),
        "customer_concentration_pct": payload.get("customer_concentration_pct"),
        "narrative_excerpt": payload.get("narrative_excerpt"),
        "confidence": float(row.confidence) if row.confidence is not None else None,
        "reporting_currency": getattr(vendor, "reporting_currency", "USD"),
    }


@router.get("/supply")
async def gpu_supply():
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

    vendors = vendor_filers_for_tab("gpu")
    cik_to_name: dict[str, str] = {v.cik: v.display_name for v in vendors if v.cik}
    edgar_vendors = [v for v in vendors if v.cik and v.form_types]
    press_only_vendors = [v for v in vendors if v.cik and not v.form_types]
    edgar_ciks = list({v.cik for v in edgar_vendors})

    async with async_session_factory() as session:
        stmt = (
            select(EdgarExtraction)
            .where(EdgarExtraction.pillar == "vendor_supply")
            .where(EdgarExtraction.cik.in_(edgar_ciks))
            .order_by(desc(EdgarExtraction.filing_date))
            .limit(100)
        )
        rows = (await session.execute(stmt)).scalars().all()

    revenue_estimates: list[dict] = []
    inventory: list[dict] = []
    timeseries: dict[str, list[dict]] = {}
    vendors_with_rows: set[str] = set()
    vendor_by_name: dict[str, object] = {v.display_name: v for v in edgar_vendors}

    for row in rows:
        company = cik_to_name.get(row.cik, row.cik)
        vendor = vendor_by_name.get(company)
        entry = _row_entry(row, vendor)
        revenue_estimates.append(entry)
        if entry.get("inventory_usd") is not None:
            inventory.append(entry)
        if entry.get("revenue_usd") is not None:
            timeseries.setdefault(company, []).append({
                "period_end": entry.get("period_end"),
                "filing_date": entry.get("filing_date"),
                "segment_name": entry.get("segment_name"),
                "revenue_usd": entry.get("revenue_usd"),
                "headline": entry.get("headline"),
            })
        vendors_with_rows.add(company)

    for series in timeseries.values():
        series.sort(key=lambda x: (x.get("period_end") or x.get("filing_date") or ""))

    audited_count = len(rows)

    excluded: dict[str, str] = {}
    for v in edgar_vendors:
        if v.display_name not in vendors_with_rows:
            excluded[v.display_name] = (
                f"{v.display_name} filings audited via SEC EDGAR (CIK {v.cik}); "
                "no datacenter-segment-revenue figures extracted in the "
                "2024-2026 window. "
                + (v.notes or "")
            ).strip()
    for v in press_only_vendors:
        excluded[v.display_name] = (
            f"{v.display_name}: in-house silicon (TPU/Trainium/Maia) is not "
            "broken out in the 10-K. Track via press releases instead."
        )

    data = {
        "shipped": [],
        "deployed": [],
        "inventory": inventory,
        "revenue_estimates": revenue_estimates,
        "timeseries": timeseries,
        "vendors_audited": [v.display_name for v in edgar_vendors],
        "filings_audited": audited_count,
    }

    if audited_count > 0:
        coverage = CoverageMeta(
            pillar="gpu_supply",
            states_included=sorted(vendors_with_rows),
            states_excluded_with_reason=excluded or None,
            freshness_status="ok",
        )
        lineage = LineageMeta(
            source_url="sec.gov/edgar",
            retrieved_at=datetime.utcnow(),
            parser_version="gpu-v3-vendor-supply",
            confidence=0.75,
        )
    else:
        coverage = CoverageMeta(
            pillar="gpu_supply",
            states_included=[],
            states_excluded_with_reason=excluded
            or {
                "ALL": (
                    "No vendor_supply rows in edgar_extractions for the GPU "
                    "tab vendors yet. Run "
                    "`python3 -m cli vendor-supply-extract --since 2024-01-01`."
                )
            },
            freshness_status="unknown",
        )
        lineage = LineageMeta(
            source_url="n/a",
            retrieved_at=datetime.utcnow(),
            parser_version="gpu-v3-vendor-supply",
            confidence=0.0,
        )

    return CoverageEnvelope(data=data, lineage=lineage, coverage=coverage)
