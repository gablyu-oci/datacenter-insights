"""Seed canonical companies for entity resolution.

Populates the companies table with the 8 core hyperscalers, key
infrastructure providers, energy companies tracked for EDGAR filings,
and known LLC subsidiaries.  Also seeds the company_aliases bridge
so that the entity resolver can short-circuit on common name variants.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import Company, CompanyAlias

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Canonical company seed data
# -------------------------------------------------------------------------

CANONICAL_COMPANIES: list[dict] = [
    # Hyperscalers
    {"canonical_name": "Microsoft Corporation", "short_name": "Microsoft", "ticker": "MSFT", "cik": "0000789019", "public_private": "Public"},
    {"canonical_name": "Amazon.com Inc.", "short_name": "Amazon", "ticker": "AMZN", "cik": "0001018724", "public_private": "Public"},
    {"canonical_name": "Alphabet Inc.", "short_name": "Google", "ticker": "GOOGL", "cik": "0001652044", "public_private": "Public"},
    {"canonical_name": "Meta Platforms Inc.", "short_name": "Meta", "ticker": "META", "cik": "0001326801", "public_private": "Public"},
    {"canonical_name": "Oracle Corporation", "short_name": "Oracle", "ticker": "ORCL", "cik": "0001341439", "public_private": "Public"},
    {"canonical_name": "Apple Inc.", "short_name": "Apple", "ticker": "AAPL", "cik": "0000320193", "public_private": "Public"},
    {"canonical_name": "International Business Machines Corporation", "short_name": "IBM", "ticker": "IBM", "cik": "0000051143", "public_private": "Public"},
    {"canonical_name": "NVIDIA Corporation", "short_name": "NVIDIA", "ticker": "NVDA", "cik": "0001045810", "public_private": "Public"},
    # Key infrastructure providers
    {"canonical_name": "Equinix Inc.", "short_name": "Equinix", "ticker": "EQIX", "cik": "0001101239", "public_private": "Public"},
    {"canonical_name": "Digital Realty Trust Inc.", "short_name": "Digital Realty", "ticker": "DLR", "cik": "0001365135", "public_private": "Public"},
    {"canonical_name": "QTS Realty Trust", "short_name": "QTS", "ticker": None, "cik": None, "public_private": "Private"},
    {"canonical_name": "Compass Datacenters", "short_name": "Compass", "ticker": None, "cik": None, "public_private": "Private"},
    {"canonical_name": "CoreWeave Inc.", "short_name": "CoreWeave", "ticker": None, "cik": None, "public_private": "Private"},
    {"canonical_name": "Iron Mountain Inc.", "short_name": "Iron Mountain", "ticker": "IRM", "cik": "0000073124", "public_private": "Public"},
    # Energy companies for EDGAR
    {"canonical_name": "Constellation Energy Corporation", "short_name": "Constellation Energy", "ticker": "CEG", "cik": "0001868275", "public_private": "Public"},
    {"canonical_name": "Talen Energy Corporation", "short_name": "Talen Energy", "ticker": "TLN", "cik": "0001839839", "public_private": "Public"},
    {"canonical_name": "NuScale Power Corporation", "short_name": "NuScale Power", "ticker": "SMR", "cik": "0001808173", "public_private": "Public"},
    {"canonical_name": "Vistra Corp.", "short_name": "Vistra Energy", "ticker": "VST", "cik": "0001692819", "public_private": "Public"},
    {"canonical_name": "NextEra Energy Inc.", "short_name": "NextEra Energy", "ticker": "NEE", "cik": "0001004440", "public_private": "Public"},
    {"canonical_name": "AES Corporation", "short_name": "AES", "ticker": "AES", "cik": "0000002178", "public_private": "Public"},
    {"canonical_name": "Dominion Energy Inc.", "short_name": "Dominion Energy", "ticker": "D", "cik": "0000715957", "public_private": "Public"},
    {"canonical_name": "Taiwan Semiconductor Manufacturing Company", "short_name": "TSMC", "ticker": "TSM", "cik": "0001046179", "public_private": "Public"},
    # Known LLC aliases from permit filings
    {"canonical_name": "Amazon Web Services", "short_name": "AWS", "ticker": None, "cik": None, "public_private": "Subsidiary", "parent_short_name": "Amazon"},
]

# -------------------------------------------------------------------------
# Known aliases to seed for entity resolution
# Each tuple: (company_short_name, source, list_of_alias_strings)
# -------------------------------------------------------------------------

KNOWN_ALIASES: list[tuple[str, str, list[str]]] = [
    ("Microsoft", "aterio_csv", ["Microsoft", "MSFT", "Microsoft Corp", "Microsoft Corporation"]),
    ("Amazon", "aterio_csv", ["Amazon", "AWS", "Amazon Web Services", "Amazon.com", "AMZN", "Amazon / AWS", "Vadata Inc", "Vadata"]),
    ("Google", "aterio_csv", ["Google", "Alphabet", "GOOGL", "Google Cloud", "Alphabet Inc", "Loudoun Heights LLC", "Bowman Development"]),
    ("Meta", "aterio_csv", ["Meta", "META", "Meta Platforms", "Facebook", "Meta Platforms Inc"]),
    ("Oracle", "aterio_csv", ["Oracle", "ORCL", "Oracle Corporation", "Oracle Corp"]),
    ("Apple", "aterio_csv", ["Apple", "AAPL", "Apple Inc"]),
    ("IBM", "aterio_csv", ["IBM", "International Business Machines"]),
    ("NVIDIA", "aterio_csv", ["NVIDIA", "NVDA", "Nvidia", "Nvidia Corporation"]),
    ("Equinix", "aterio_csv", ["Equinix", "EQIX", "Equinix Inc"]),
    ("Digital Realty", "aterio_csv", ["Digital Realty", "DLR", "Digital Realty Trust", "DuPont Fabros / Digital Realty"]),
    ("QTS", "aterio_csv", ["QTS", "QTS Realty", "QTS Realty Trust", "QTS Data Centers"]),
    ("Compass", "aterio_csv", ["Compass", "Compass Datacenters"]),
    ("CoreWeave", "aterio_csv", ["CoreWeave", "CoreWeave Inc"]),
    ("Iron Mountain", "aterio_csv", ["Iron Mountain", "IRM", "Iron Mountain Inc"]),
    ("TSMC", "aterio_csv", ["TSMC", "TSM", "Taiwan Semiconductor", "Taiwan Semiconductor Manufacturing"]),
]


# -------------------------------------------------------------------------
# Seed function
# -------------------------------------------------------------------------

async def seed_companies(db: AsyncSession) -> None:
    """Upsert canonical companies and known aliases into the database.

    Idempotent: safe to call on every application startup or migration.
    Uses select-then-insert/update pattern since companies table has no
    unique constraint on ticker or canonical_name (only indexes).
    """
    from datetime import datetime

    # -- Step 1: Upsert companies ------------------------------------------
    for row in CANONICAL_COMPANIES:
        # Separate parent_short_name (not a DB column) from the rest
        parent_short_name: Optional[str] = row.get("parent_short_name")
        db_row = {k: v for k, v in row.items() if k != "parent_short_name"}

        # Try to find existing by ticker (if set) or canonical_name
        existing = None
        if db_row.get("ticker"):
            result = await db.execute(
                select(Company).where(Company.ticker == db_row["ticker"])
            )
            existing = result.scalar_one_or_none()

        if existing is None:
            result = await db.execute(
                select(Company).where(Company.canonical_name == db_row["canonical_name"])
            )
            existing = result.scalar_one_or_none()

        if existing:
            # Update existing
            existing.short_name = db_row.get("short_name", existing.short_name)
            existing.cik = db_row.get("cik", existing.cik)
            existing.public_private = db_row.get("public_private", existing.public_private)
            existing.updated_at = datetime.utcnow()
            db.add(existing)
        else:
            # Insert new
            new_company = Company(**db_row)
            db.add(new_company)

    await db.flush()

    # -- Step 2: Resolve parent_company_id for subsidiaries ----------------
    for row in CANONICAL_COMPANIES:
        parent_short_name = row.get("parent_short_name")
        if not parent_short_name:
            continue

        # Look up parent by short_name
        parent_result = await db.execute(
            select(Company).where(Company.short_name == parent_short_name)
        )
        parent = parent_result.scalar_one_or_none()
        if not parent:
            logger.warning(
                "seed_companies: parent '%s' not found for '%s'",
                parent_short_name, row["canonical_name"],
            )
            continue

        # Look up the subsidiary
        child_result = await db.execute(
            select(Company).where(Company.canonical_name == row["canonical_name"])
        )
        child = child_result.scalar_one_or_none()
        if child and child.parent_company_id != parent.id:
            child.parent_company_id = parent.id
            db.add(child)

    await db.flush()

    # -- Step 3: Seed known aliases ----------------------------------------
    # Build a short_name -> id lookup
    all_companies = (await db.execute(select(Company))).scalars().all()
    short_name_map: dict[str, int] = {}
    for c in all_companies:
        if c.short_name:
            short_name_map[c.short_name] = c.id

    for short_name, source, alias_list in KNOWN_ALIASES:
        company_id = short_name_map.get(short_name)
        if company_id is None:
            logger.warning(
                "seed_companies: alias target '%s' not found in companies",
                short_name,
            )
            continue

        for alias_name in alias_list:
            stmt = (
                pg_insert(CompanyAlias)
                .values(
                    company_id=company_id,
                    source=source,
                    raw_name=alias_name,
                    match_method="seed",
                    confidence=1.0,
                )
                .on_conflict_do_nothing(constraint="uq_company_alias_source_rawname")
            )
            await db.execute(stmt)

    await db.flush()
    logger.info(
        "seed_companies: upserted %d companies and alias groups for %d companies",
        len(CANONICAL_COMPANIES),
        len(KNOWN_ALIASES),
    )
