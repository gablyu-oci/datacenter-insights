"""
Supply-chain endpoints: NICs/optics and Wafer-Production data.
Prefix: /api/supply-chain (legacy paths /api/nics, /api/tsmc mounted in main.py).

Reads pillar='vendor_supply' rows for the relevant tab vendors and decodes
the JSON-packed `excerpt` payload into per-vendor per-quarter timeseries.

Power-deal rows (pillar='power_contract') are NEVER returned here.

Coverage envelope flags Samsung Electronics and SK Hynix as "non-EDGAR" —
they file in Korean DART, not the SEC, so they're permanently outside our
free-data scope. Surfacing this stops users from interpreting their absence
as a bug.
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

router = APIRouter(prefix="/api/supply-chain", tags=["supply-chain"])
legacy_router = APIRouter(tags=["supply-chain-legacy"])


# Korean filers that don't file with the SEC — surface explicitly so users
# know the absence is a coverage gap, not a bug.
NON_EDGAR_VENDORS = {
    "Samsung Electronics": (
        "Samsung Electronics files with Korean DART, not SEC EDGAR — "
        "no 20-F. Track via Samsung IR / DART; out of free-EDGAR scope."
    ),
    "SK Hynix": (
        "SK Hynix files with Korean DART, not SEC EDGAR. Critical for "
        "HBM signal but unreachable from EDGAR; out of free-EDGAR scope."
    ),
}


def _decode_payload(excerpt: str | None) -> dict:
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
    """Apply FX rate (e.g., 1/32 for TWD→USD) to a raw extracted amount."""
    if amount is None:
        return None
    try:
        return float(amount) * fx
    except (TypeError, ValueError):
        return None


def _row_entry(row: EdgarExtraction, vendor) -> dict:
    """Decode the JSON payload and apply currency normalization.

    `vendor` is the matching VendorFiler entry (so we can look up the
    reporting_currency). The extractor stores raw figures as the LLM
    pulled them; FX conversion happens here at read time.
    """
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


def _build_excluded(
    edgar_vendors: list,
    vendors_with_rows: set[str],
    extra_non_edgar: dict[str, str] | None = None,
) -> dict[str, str]:
    excluded: dict[str, str] = {}
    for v in edgar_vendors:
        if v.display_name not in vendors_with_rows:
            note = (v.notes or "").strip()
            excluded[v.display_name] = (
                f"{v.display_name} filings audited via SEC EDGAR "
                f"(CIK {v.cik}); no vendor-supply numerics extracted in the "
                "2024-2026 window."
                + (f" Note: {note}" if note else "")
            )
    if extra_non_edgar:
        excluded.update(extra_non_edgar)
    return excluded


async def _fetch_tab_rows(tab: str) -> tuple[list, dict[str, str], list]:
    """Returns (rows, cik_to_name, edgar_vendors)."""
    vendors = vendor_filers_for_tab(tab)
    cik_to_name: dict[str, str] = {}
    for v in vendors:
        if v.cik:
            cik_to_name[v.cik] = v.display_name
    edgar_vendors = [v for v in vendors if v.cik and v.form_types]
    edgar_ciks = list({v.cik for v in edgar_vendors})

    if not edgar_ciks:
        return [], cik_to_name, edgar_vendors

    async with async_session_factory() as session:
        stmt = (
            select(EdgarExtraction)
            .where(EdgarExtraction.pillar == "vendor_supply")
            .where(EdgarExtraction.cik.in_(edgar_ciks))
            .order_by(desc(EdgarExtraction.filing_date))
            .limit(150)
        )
        rows = (await session.execute(stmt)).scalars().all()
    return rows, cik_to_name, edgar_vendors


async def _nics_response():
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

    rows, cik_to_name, edgar_vendors = await _fetch_tab_rows("nics_optics")

    nic_silicon: list[dict] = []
    optics: list[dict] = []
    timeseries: dict[str, list[dict]] = {}
    vendors_with_rows: set[str] = set()

    # Lookup tables: vendor metadata by display name, by cik.
    vendor_by_name: dict[str, object] = {v.display_name: v for v in edgar_vendors}

    for row in rows:
        company = cik_to_name.get(row.cik, row.cik)
        vendor = vendor_by_name.get(company)
        entry = _row_entry(row, vendor)
        bucket = getattr(vendor, "segment", None)
        if bucket == "nic":
            nic_silicon.append(entry)
        elif bucket == "optics":
            optics.append(entry)
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

    data = {
        "nic_shipments": nic_silicon,
        "optics_shipments": optics,
        "correlation_score": None,
        "timeseries": timeseries,
        "vendors_audited": [v.display_name for v in edgar_vendors],
        "filings_audited": audited_count,
    }

    excluded = _build_excluded(edgar_vendors, vendors_with_rows)

    if audited_count > 0:
        coverage = CoverageMeta(
            pillar="nics_optics",
            states_included=sorted(vendors_with_rows),
            states_excluded_with_reason=excluded or None,
            freshness_status="ok",
        )
        lineage = LineageMeta(
            source_url="sec.gov/edgar",
            retrieved_at=datetime.utcnow(),
            parser_version="nics-v3-vendor-supply",
            confidence=0.7,
        )
    else:
        coverage = CoverageMeta(
            pillar="nics_optics",
            states_included=[],
            states_excluded_with_reason=excluded
            or {
                "ALL": (
                    "No vendor_supply rows yet. Run "
                    "`python3 -m cli vendor-supply-extract --since 2024-01-01`."
                )
            },
            freshness_status="unknown",
        )
        lineage = LineageMeta(
            source_url="n/a",
            retrieved_at=datetime.utcnow(),
            parser_version="nics-v3-vendor-supply",
            confidence=0.0,
        )

    return CoverageEnvelope(data=data, lineage=lineage, coverage=coverage)


async def _tsmc_response():
    """Wafer Production & Supply tab (legacy path /api/tsmc)."""
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

    rows, cik_to_name, edgar_vendors = await _fetch_tab_rows("wafer")

    foundry: list[dict] = []
    packaging: list[dict] = []
    equipment: list[dict] = []
    timeseries: dict[str, list[dict]] = {}
    vendors_with_rows: set[str] = set()

    vendor_by_name: dict[str, object] = {v.display_name: v for v in edgar_vendors}

    for row in rows:
        company = cik_to_name.get(row.cik, row.cik)
        vendor = vendor_by_name.get(company)
        entry = _row_entry(row, vendor)
        bucket = getattr(vendor, "segment", None)
        if bucket == "foundry":
            foundry.append(entry)
        elif bucket == "packaging":
            packaging.append(entry)
        elif bucket == "equipment":
            equipment.append(entry)
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

    data = {
        "capacity": foundry,            # Foundry vendors (TSMC, Intel-Foundry, GF)
        "packaging": packaging,          # OSAT vendors (Amkor, ASE)
        "equipment": equipment,          # Equipment vendors (ASML, AMAT)
        "disclosures": foundry + packaging + equipment,
        "timeseries": timeseries,
        "vendors_audited": [v.display_name for v in edgar_vendors],
        "filings_audited": audited_count,
    }

    excluded = _build_excluded(
        edgar_vendors, vendors_with_rows, extra_non_edgar=NON_EDGAR_VENDORS
    )

    if audited_count > 0:
        coverage = CoverageMeta(
            pillar="tsmc",
            states_included=sorted(vendors_with_rows),
            states_excluded_with_reason=excluded or None,
            freshness_status="ok",
        )
        lineage = LineageMeta(
            source_url="sec.gov/edgar",
            retrieved_at=datetime.utcnow(),
            parser_version="wafer-v3-vendor-supply",
            confidence=0.7,
        )
    else:
        coverage = CoverageMeta(
            pillar="tsmc",
            states_included=[],
            states_excluded_with_reason=excluded
            or {
                "ALL": (
                    "No vendor_supply rows yet. Run "
                    "`python3 -m cli vendor-supply-extract --since 2024-01-01`."
                )
            },
            freshness_status="unknown",
        )
        lineage = LineageMeta(
            source_url="n/a",
            retrieved_at=datetime.utcnow(),
            parser_version="wafer-v3-vendor-supply",
            confidence=0.0,
        )

    return CoverageEnvelope(data=data, lineage=lineage, coverage=coverage)


@router.get("/nics")
async def nics_new():
    return await _nics_response()


@router.get("/tsmc")
async def tsmc_new():
    return await _tsmc_response()


@legacy_router.get("/api/nics")
async def nics_legacy():
    return await _nics_response()


@legacy_router.get("/api/tsmc")
async def tsmc_legacy():
    return await _tsmc_response()
