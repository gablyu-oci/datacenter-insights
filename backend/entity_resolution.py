"""Entity resolution: raw company name -> canonical companies.id

Implements a five-layer resolution cascade:
  1. ticker -> CIK exact match (curated map or companies.ticker)
  2. exact canonical_name / short_name match (case-insensitive)
  3. company_aliases.raw_name lookup (normalised lowercase)
  4. rapidfuzz fuzzy match (WRatio, threshold 90)
  5. auto-create new company as Subsidiary

Every successful resolution writes a company_aliases bridge entry so
subsequent lookups for the same raw_name skip straight to layer 3.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from rapidfuzz import fuzz, process

from db.models import Company, CompanyAlias

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Curated ticker -> CIK mapping for deterministic resolution
# -------------------------------------------------------------------------
TICKER_TO_CIK = {
    "MSFT": "0000789019",
    "AMZN": "0001018724",
    "GOOGL": "0001652044",
    "META": "0001326801",
    "ORCL": "0001341439",
    "AAPL": "0000320193",
    "IBM": "0000051143",
    "NVDA": "0001045810",
    "EQIX": "0001101239",
    "DLR": "0001365135",
    "TSMC": "0001046179",  # TSM on NYSE
}

FUZZY_THRESHOLD = 90


async def resolve_company(
    db: AsyncSession,
    raw_name: str,
    *,
    ticker: Optional[str] = None,
    source: str = "unknown",
) -> Tuple[Optional[int], float, str]:
    """
    Resolve a raw company name to a canonical company_id.

    Returns
    -------
    tuple of (company_id, confidence, match_method)
        company_id : int or None (None only when raw_name is empty)
        confidence : float in [0, 1]
        match_method : str label for audit trail
    """
    if not raw_name or not raw_name.strip():
        return None, 0.0, "empty_input"

    raw_name_clean = raw_name.strip()
    raw_name_lower = raw_name_clean.lower()

    # ------------------------------------------------------------------
    # Layer 1: Ticker -> CIK exact match
    # ------------------------------------------------------------------
    if ticker:
        ticker_upper = ticker.upper().strip()
        cik = TICKER_TO_CIK.get(ticker_upper)
        if cik:
            stmt = select(Company).where(Company.cik == cik)
            result = await db.execute(stmt)
            company = result.scalar_one_or_none()
            if company:
                await _write_alias(db, company.id, source, raw_name_clean, "ticker_exact", 1.0)
                return company.id, 1.0, "ticker_exact"

        # Fallback: try companies.ticker column directly
        stmt = select(Company).where(func.upper(Company.ticker) == ticker_upper)
        result = await db.execute(stmt)
        company = result.scalar_one_or_none()
        if company:
            await _write_alias(db, company.id, source, raw_name_clean, "ticker_exact", 1.0)
            return company.id, 1.0, "ticker_exact"

    # ------------------------------------------------------------------
    # Layer 2: Exact canonical_name or short_name match
    # ------------------------------------------------------------------
    stmt = select(Company).where(func.lower(Company.canonical_name) == raw_name_lower)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()
    if company:
        await _write_alias(db, company.id, source, raw_name_clean, "name_exact", 1.0)
        return company.id, 1.0, "name_exact"

    stmt = select(Company).where(func.lower(Company.short_name) == raw_name_lower)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()
    if company:
        await _write_alias(db, company.id, source, raw_name_clean, "name_exact", 0.98)
        return company.id, 0.98, "name_exact"

    # ------------------------------------------------------------------
    # Layer 3: Alias table lookup
    # ------------------------------------------------------------------
    stmt = select(CompanyAlias).where(func.lower(CompanyAlias.raw_name) == raw_name_lower)
    result = await db.execute(stmt)
    alias = result.scalar_one_or_none()
    if alias:
        # Write a cross-source alias if caller is a different source
        if alias.source != source:
            await _write_alias(
                db, alias.company_id, source, raw_name_clean,
                "alias_lookup", alias.confidence or 0.95,
            )
        return alias.company_id, float(alias.confidence or 0.95), "alias_lookup"

    # ------------------------------------------------------------------
    # Layer 4: Fuzzy match (rapidfuzz WRatio)
    # ------------------------------------------------------------------
    all_companies = (await db.execute(select(Company))).scalars().all()
    candidates: dict[str, int] = {}
    for c in all_companies:
        candidates[c.canonical_name] = c.id
        if c.short_name:
            candidates[c.short_name] = c.id

    all_aliases = (await db.execute(select(CompanyAlias))).scalars().all()
    for a in all_aliases:
        candidates[a.raw_name] = a.company_id

    if candidates:
        match = process.extractOne(
            raw_name_clean,
            list(candidates.keys()),
            scorer=fuzz.WRatio,
            score_cutoff=FUZZY_THRESHOLD,
        )
        if match:
            matched_name, score, _ = match
            company_id = candidates[matched_name]
            confidence = round(score / 100.0, 2)
            await _write_alias(db, company_id, source, raw_name_clean, "rapidfuzz", confidence)
            return company_id, confidence, "rapidfuzz"

    # ------------------------------------------------------------------
    # Layer 5: Auto-create new company
    # ------------------------------------------------------------------
    new_company = Company(
        canonical_name=raw_name_clean,
        short_name=raw_name_clean,
        public_private="Subsidiary",
    )
    db.add(new_company)
    await db.flush()
    await _write_alias(db, new_company.id, source, raw_name_clean, "auto_created", 0.5)
    logger.info(
        "entity_resolution.new_company",
        extra={"raw_name": raw_name_clean, "id": new_company.id},
    )
    return new_company.id, 0.5, "auto_created"


async def _write_alias(
    db: AsyncSession,
    company_id: int,
    source: str,
    raw_name: str,
    match_method: str,
    confidence: float,
) -> None:
    """Write company_aliases bridge entry. ON CONFLICT DO NOTHING (UNIQUE source, raw_name)."""
    stmt = (
        pg_insert(CompanyAlias)
        .values(
            company_id=company_id,
            source=source,
            raw_name=raw_name,
            match_method=match_method,
            confidence=confidence,
        )
        .on_conflict_do_nothing(constraint="uq_company_alias_source_rawname")
    )
    await db.execute(stmt)
