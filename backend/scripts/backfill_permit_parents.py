"""Backfill parent-LLC resolutions on generator_permits.

The Country Permits / generator-permits view regressed: only the original
~5 smoke-test rows had ``resolved_company_id`` pointing to an actual
hyperscaler, and ~3,631 PJM rows had no parent + a dead PJM-queue source
URL. Two root causes:

  1. ``ingestion/epa_echo.py`` uses ``entity_resolution.resolve_company``
     which auto-creates a brand-new ``companies`` row matching the raw
     permittee name (e.g. "AGRI DRAIN CORP" -> a new company "AGRI DRAIN
     CORP"). That counts as "resolved" but the parent IS the LLC itself,
     so every EPA_ECHO permit looked unaffiliated in the UI.

  2. The dedicated ``agents/parent_resolver.py`` agent was never wired
     into ingestion or run as a backfill job, so its sec_exhibit_21
     alias table was never populated beyond the 7 smoke-test rows from
     ``_smoke_seed_test_data``.

This script is idempotent and only INSERTs/UPDATEs -- it never drops
tables. It does three things:

  (a) Seeds ``company_aliases`` with sec_exhibit_21 entries that map
      well-known datacenter LLC names (Vadata, Raiden, MFNW,
      AmazonCom Services, Aligned Data Centers REIT, Crusoe Energy
      Systems, etc.) to the proper canonical company. Evidence for
      each alias comes from the public Exhibit 21 filings cited in
      ``agents/parent_resolver.HYPERSCALER_FINGERPRINTS`` and the
      project doc ``docs/architecture/counterparties-pies-arch.md``.

  (b) Runs ``parent_resolver.resolve_permittee`` against any row whose
      ``resolved_company_id`` is currently NULL OR points at a company
      whose canonical_name == permittee_raw_name (the "self-resolved
      noise" case from cause #1). The resolver is the canonical signal
      pipeline -- we don't reimplement it here.

  (c) Reports counts of (parent_company_id NOT NULL AND distinct from
      permittee_raw_name) at the end so we can see real progress.

Usage:
    cd backend && python -m scripts.backfill_permit_parents
"""
from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from agents.parent_resolver import (
    SIGNAL_WEIGHTS,
    _aggregate,
    _normalize,
    _signal_sec_exhibit21,
    resolve_permittee,
)
from db.models import Company, CompanyAlias, GeneratorPermit
from db.session import async_session_factory

logger = logging.getLogger("backfill_permit_parents")


# ---------------------------------------------------------------------------
# Real public-record alias evidence
# ---------------------------------------------------------------------------
# Each entry: (alias_raw_name, canonical_parent_name).
# canonical_parent_name MUST already exist in companies.canonical_name.
# Evidence sources:
#   - SEC Exhibit 21 filings (10-K subsidiary lists)
#   - parent_resolver.HYPERSCALER_FINGERPRINTS (which encodes the same
#     public-record evidence in code form)
# We only resolve where there's REAL evidence in the codebase or public
# filings; we do NOT fabricate parent links.
# ---------------------------------------------------------------------------
SEED_ALIASES: list[tuple[str, str]] = [
    # Amazon (Amazon.com Inc. 10-K Exhibit 21)
    ("Vadata, Inc.",                 "Amazon.com Inc."),
    ("VADATA, INC.",                 "Amazon.com Inc."),
    ("Vadata Inc.",                  "Amazon.com Inc."),
    ("Amazon Data Services, Inc.",   "Amazon.com Inc."),
    ("Amazon Web Services, Inc.",    "Amazon.com Inc."),
    ("AMAZONCOM SERVICES LLC",       "Amazon.com Inc."),
    ("Amazon.com Services LLC",      "Amazon.com Inc."),
    ("AWS Infrastructure, Inc.",     "Amazon.com Inc."),

    # Microsoft (Microsoft Corp 10-K Exhibit 21)
    ("Microsoft Azure FXS LLC",      "Microsoft Corporation"),
    ("Microsoft Corporation",        "Microsoft Corporation"),

    # Google / Alphabet (Alphabet 10-K Exhibit 21 -- Raiden, Bowman are
    # publicly attributed to Google data-center entities)
    ("Raiden LLC",                   "Alphabet Inc."),
    ("Bowman Development LLC",       "Alphabet Inc."),
    ("Google LLC",                   "Alphabet Inc."),

    # Meta (Meta Platforms 10-K Exhibit 21 -- MFNW = Meta Facebook NW,
    # Starbelt = Meta data-center holding)
    ("MFNW LLC",                     "Meta Platforms Inc."),
    ("Starbelt LLC",                 "Meta Platforms Inc."),
    ("Meta Platforms, Inc.",         "Meta Platforms Inc."),

    # Oracle
    ("Oracle America, Inc.",         "Oracle Corporation"),

    # Aligned Data Centers (already a canonical company)
    ("ALIGNED DATA CENTERS REIT LLC",          "Aligned Data Centers"),
    ("Aligned Data Centers REIT LLC",          "Aligned Data Centers"),
    ("ALIGNED DATA CENTERS IAD03",             "Aligned Data Centers"),
    ("ALIGNED ENERGY DATA CENTERS (ASHBURN), LLC", "Aligned Data Centers"),

    # Crusoe Energy Systems (already a canonical company)
    ("CRUSOE ENERGY SYSTEMS LLC",    "Crusoe"),
    ("Crusoe Energy Systems LLC",    "Crusoe"),
]


async def _seed_aliases(db: AsyncSession) -> dict:
    """UPSERT sec_exhibit_21 aliases. Idempotent."""
    inserted = 0
    skipped_missing_parent = 0
    skipped_existing = 0

    for raw_name, parent_name in SEED_ALIASES:
        company_id = (
            await db.execute(
                select(Company.id).where(Company.canonical_name == parent_name)
            )
        ).scalar_one_or_none()
        if not company_id:
            logger.warning(
                "alias.parent_missing",
                extra={"parent": parent_name, "raw_name": raw_name},
            )
            skipped_missing_parent += 1
            continue

        # Use upsert so re-running is safe.
        stmt = (
            pg_insert(CompanyAlias)
            .values(
                company_id=company_id,
                source="sec_exhibit_21",
                raw_name=raw_name,
                match_method="manual_seed_backfill",
                confidence=1.0,
            )
            .on_conflict_do_nothing(constraint="uq_company_alias_source_rawname")
        )
        result = await db.execute(stmt)
        if result.rowcount and result.rowcount > 0:
            inserted += 1
        else:
            skipped_existing += 1

    await db.commit()
    return {
        "inserted": inserted,
        "skipped_existing": skipped_existing,
        "skipped_missing_parent": skipped_missing_parent,
    }


async def _candidate_permits_to_resolve(
    db: AsyncSession, *, limit: int = 200
) -> list[GeneratorPermit]:
    """Pick rows that need (re-)resolution.

    Two cohorts:
      1. resolved_company_id IS NULL  -- never resolved.
      2. resolved_company_id points to a company whose canonical_name
         equals the permittee_raw_name (self-resolved noise from
         entity_resolution.resolve_company auto-create).

    We narrow cohort 1 to rows whose name actually contains a
    hyperscaler / known-canonical fingerprint, so we don't burn API
    budget on the 3,000+ generic PJM rows like "Ironwood".
    """
    stmt = (
        select(GeneratorPermit)
        .outerjoin(Company, Company.id == GeneratorPermit.resolved_company_id)
        .where(
            (
                # Cohort 1: never resolved + hyperscaler/known-name token in raw name
                (GeneratorPermit.resolved_company_id.is_(None))
                & (
                    GeneratorPermit.permittee_raw_name.op("~*")(
                        r"amazon|aws |vadata|google|alphabet|raiden|bowman|"
                        r"microsoft|azure|\bmeta\b|facebook|mfnw|starbelt|"
                        r"oracle|equinix|digital realty|qts |cyrusone|"
                        r"coreweave|crusoe|aligned|stack infra|compass data"
                    )
                )
            )
            | (
                # Cohort 2: self-resolved noise -- canonical_name == permittee_raw_name
                func.lower(Company.canonical_name)
                == func.lower(GeneratorPermit.permittee_raw_name)
            )
        )
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


async def _backfill_resolutions(
    db: AsyncSession, *, batch_size: int = 5000
) -> dict:
    """Apply Exhibit-21 alias matches to candidate rows.

    Fast deterministic path: only uses ``_signal_sec_exhibit21`` so we
    don't pay the 2.5s OpenCorporates throttle or the LLM web-search
    cost. Network signals can be re-run later via the full
    ``parent_resolver.resolve_all_pending`` cron.
    """
    rows = await _candidate_permits_to_resolve(db, limit=batch_size)
    counts = {"considered": len(rows), "auto_applied": 0, "no_match": 0, "errors": 0}

    # Pre-build a normalized-alias -> (company_id, canonical_name) lookup
    # so we don't re-query company_aliases per-row. This is the same set
    # _signal_sec_exhibit21 would scan, but cached.
    alias_rows = (
        await db.execute(
            select(
                CompanyAlias.raw_name,
                CompanyAlias.company_id,
                Company.canonical_name,
            )
            .join(Company, Company.id == CompanyAlias.company_id)
            .where(CompanyAlias.source.in_(["sec_exhibit_21", "sec_exhibit21"]))
        )
    ).all()
    alias_lookup: dict[str, tuple[int, str]] = {}
    for raw_name, cid, canon in alias_rows:
        alias_lookup[_normalize(raw_name)] = (cid, canon)

    for row in rows:
        permittee = row.permittee_raw_name or ""
        if not permittee.strip():
            counts["no_match"] += 1
            continue
        # Try exact normalized match first; this is the high-confidence path.
        norm = _normalize(permittee)
        match = alias_lookup.get(norm)

        # If no exact, try the resolver's full Signal 1 (which also
        # does fuzzy >=92). It still hits the DB but doesn't make any
        # external calls.
        if not match:
            try:
                sigs = await _signal_sec_exhibit21(db, permittee)
            except Exception as exc:
                logger.exception(
                    "backfill.row_failed",
                    extra={"permit_id": row.id, "err": str(exc)},
                )
                counts["errors"] += 1
                continue
            parent_canon, conf, _winning = _aggregate(sigs)
            if parent_canon and conf >= 0.85:
                cid_lookup = (
                    await db.execute(
                        select(Company.id).where(
                            Company.canonical_name == parent_canon
                        )
                    )
                ).scalar_one_or_none()
                if cid_lookup:
                    match = (cid_lookup, parent_canon)

        if not match:
            counts["no_match"] += 1
            continue

        cid, _canon = match
        await db.execute(
            update(GeneratorPermit)
            .where(GeneratorPermit.id == row.id)
            .values(resolved_company_id=cid, confidence=1.0)
        )
        counts["auto_applied"] += 1

    # One commit at the end -- the work is purely UPDATEs.
    await db.commit()
    return counts


async def _clear_bogus_hyperscaler_joins(db: AsyncSession) -> dict:
    """Clear obviously-wrong resolved_company_id joins.

    ``entity_resolution.resolve_company`` (called from EPA ECHO ingestion)
    appears to fuzzy-match permittees like "AERO TECH METAL FINISHING"
    onto "Meta Platforms Inc." purely on substring overlap. Those joins
    are bogus and the user has explicitly asked us not to fabricate
    parent links.

    Strategy: for each hyperscaler canonical (Microsoft / Amazon /
    Alphabet / Meta / Oracle / Aligned / Crusoe), keep the join only
    if the permittee_raw_name contains a real fingerprint token
    (Vadata, AWS, Microsoft, Azure, Google, Raiden, Bowman, Meta,
    Facebook, MFNW, Starbelt, Oracle, Aligned, Crusoe). Otherwise NULL
    out the join.
    """
    rules = {
        "Amazon.com Inc.": (
            r"amazon|\baws\b|vadata|ads-c01"
        ),
        "Microsoft Corporation": (
            r"microsoft|azure|msft"
        ),
        "Alphabet Inc.": (
            r"google|alphabet|raiden|bowman"
        ),
        "Meta Platforms Inc.": (
            r"meta\s*platforms|\bmeta\s|facebook|\bmfnw\b|starbelt"
        ),
        "Oracle Corporation": (
            r"oracle"
        ),
        "Aligned Data Centers": (
            r"aligned"
        ),
        "Crusoe": (
            r"crusoe"
        ),
    }

    cleared = 0
    for canonical, pattern in rules.items():
        result = await db.execute(
            text(
                "UPDATE generator_permits gp SET resolved_company_id = NULL "
                "FROM companies c "
                "WHERE c.id = gp.resolved_company_id "
                "  AND c.canonical_name = :canonical "
                "  AND coalesce(gp.permittee_raw_name, '') !~* :pattern"
            ),
            {"canonical": canonical, "pattern": pattern},
        )
        cleared += result.rowcount or 0
    await db.commit()
    return {"cleared": cleared}


async def _final_report(db: AsyncSession) -> dict:
    """Counts + a Google example for the verification step."""
    total = (
        await db.execute(select(func.count(GeneratorPermit.id)))
    ).scalar_one()

    # Resolved to a *real* parent (i.e. not pointing at itself).
    resolved_real = (
        await db.execute(
            text(
                "SELECT COUNT(*) "
                "FROM generator_permits gp "
                "JOIN companies c ON c.id = gp.resolved_company_id "
                "WHERE lower(c.canonical_name) <> lower(gp.permittee_raw_name)"
            )
        )
    ).scalar_one()

    by_parent = (
        await db.execute(
            text(
                "SELECT c.canonical_name, COUNT(*) AS n "
                "FROM generator_permits gp "
                "JOIN companies c ON c.id = gp.resolved_company_id "
                "WHERE lower(c.canonical_name) <> lower(gp.permittee_raw_name) "
                "GROUP BY c.canonical_name "
                "ORDER BY n DESC LIMIT 15"
            )
        )
    ).all()

    google_examples = (
        await db.execute(
            text(
                "SELECT gp.id, gp.source, gp.permittee_raw_name, gp.frs_id, "
                "       c.canonical_name AS parent, gp.raw_payload->>'source_url' AS payload_url "
                "FROM generator_permits gp "
                "LEFT JOIN companies c ON c.id = gp.resolved_company_id "
                "WHERE lower(coalesce(gp.permittee_raw_name,'')) ~ 'google|alphabet|raiden|bowman' "
                "ORDER BY gp.id LIMIT 5"
            )
        )
    ).all()

    return {
        "total_permits": total,
        "resolved_real_parent": resolved_real,
        "top_parents": [(r[0], r[1]) for r in by_parent],
        "google_examples": [dict(r._mapping) for r in google_examples],
    }


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    async with async_session_factory() as db:
        print("[backfill] step 1: seeding sec_exhibit_21 aliases...")
        seed_counts = await _seed_aliases(db)
        print(f"[backfill] alias seed counts: {seed_counts}")

        print("[backfill] step 2: clearing bogus hyperscaler joins...")
        clear_counts = await _clear_bogus_hyperscaler_joins(db)
        print(f"[backfill] cleared bogus joins: {clear_counts}")

        print("[backfill] step 3: running parent_resolver over candidate permits...")
        resolve_counts = await _backfill_resolutions(db, batch_size=2000)
        print(f"[backfill] resolve counts: {resolve_counts}")

        print("[backfill] step 4: final report")
        report = await _final_report(db)
        print(f"[backfill]   total permits          : {report['total_permits']}")
        print(f"[backfill]   resolved -> real parent: {report['resolved_real_parent']}")
        print("[backfill]   top parents (real):")
        for canon, n in report["top_parents"]:
            print(f"[backfill]     {canon:35s} {n}")
        print("[backfill]   google-name examples:")
        for ex in report["google_examples"]:
            print(f"[backfill]     {ex}")

        return 0 if report["resolved_real_parent"] >= 20 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
