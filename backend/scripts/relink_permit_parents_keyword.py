"""Keyword-based parent-LLC linker for generator_permits.

This is a lighter, network-free counterpart to
``backfill_permit_parents.py``. It does not call OpenCorporates or the
LLM -- it only uses two deterministic signals so we can re-run it on
demand and get reproducible results:

  1. SEC Exhibit 21 EXACT alias match against ``company_aliases``
     (source = sec_exhibit_21). This catches the well-known LLCs
     (Vadata, Raiden, MFNW, ...).

  2. Substring keyword match using the same ``_CANONICAL_KEYWORDS``
     table that the permits router uses for its read-time fallback.
     This catches the PJM project names ("PSEG", "PEPCO", "Dominion",
     etc.) that the alias table doesn't cover. The matching parent
     company is looked up by canonical_name; if it doesn't exist we
     create it (with public_private = "public").

It also CLEARS the resolved_company_id on rows where the current
"parent" is just a self-named auto-resolution (canonical_name == the
permittee_raw_name) and no keyword signal hit -- so the UI no longer
sees the false-positive "AGRI DRAIN CORP -> AGRI DRAIN CORP" rows
masquerading as parent resolutions.

Idempotent. Safe to re-run.

Usage:
    cd backend && python -m scripts.relink_permit_parents_keyword
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys
from typing import Optional

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Company, CompanyAlias, GeneratorPermit
from db.session import async_session_factory
# Reuse the exact same keyword table the router uses, so DB-level
# resolution and read-time fallback never disagree.
from routers.permits import _CANONICAL_KEYWORDS, _keyword_canonical

logger = logging.getLogger("relink_permit_parents_keyword")


def _norm(s: Optional[str]) -> str:
    """Lowercase, strip, collapse whitespace, drop punctuation."""
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


async def _ensure_company(db: AsyncSession, canonical_name: str) -> int:
    """Return the id of a Company with this canonical_name, inserting
    if missing.  We don't try to deduplicate against existing parents
    -- the canonical_name uniqueness is by exact spelling."""
    cid = (
        await db.execute(
            select(Company.id).where(Company.canonical_name == canonical_name)
        )
    ).scalar_one_or_none()
    if cid is not None:
        return cid
    c = Company(canonical_name=canonical_name, public_private="public")
    db.add(c)
    await db.flush()
    return c.id


async def _exhibit21_lookup(
    db: AsyncSession, permittee_raw: str
) -> Optional[int]:
    """Return company_id for an exact (normalized) Exhibit 21 alias match,
    or None."""
    norm = _norm(permittee_raw)
    if not norm:
        return None
    rows = (
        await db.execute(
            select(CompanyAlias.company_id, CompanyAlias.raw_name).where(
                CompanyAlias.source.in_(["sec_exhibit_21", "sec_exhibit21"])
            )
        )
    ).all()
    for company_id, raw_name in rows:
        if _norm(raw_name) == norm:
            return company_id
    return None


async def _keyword_lookup(
    db: AsyncSession, permittee_raw: str, *, cache: dict
) -> Optional[int]:
    """Return company_id for a keyword match against the router's
    _CANONICAL_KEYWORDS, creating the canonical Company row if needed."""
    canonical = _keyword_canonical(permittee_raw)
    if not canonical:
        return None
    if canonical in cache:
        return cache[canonical]
    cid = await _ensure_company(db, canonical)
    cache[canonical] = cid
    return cid


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    async with async_session_factory() as db:
        # Pre-warm a Company-name -> id cache for the keyword targets so
        # we make at most O(distinct canonicals) inserts.
        cache: dict[str, int] = {}

        # --- Pass A: link via Exhibit 21 + keywords ----------------------
        permits = (
            await db.execute(select(GeneratorPermit))
        ).scalars().all()
        print(f"[relink] scanning {len(permits)} permits...")

        ex21_hits = 0
        keyword_hits = 0
        cleared = 0
        kept = 0
        unchanged = 0

        # Pre-load existing parent canonical_name per permit so we can
        # detect self-named auto-resolutions cheaply.
        existing_parents = {
            r[0]: r[1]
            for r in (
                await db.execute(
                    text(
                        "SELECT gp.id, c.canonical_name "
                        "FROM generator_permits gp "
                        "JOIN companies c ON c.id = gp.resolved_company_id"
                    )
                )
            ).all()
        }

        for p in permits:
            new_id: Optional[int] = None

            # 1. Exhibit 21 exact
            new_id = await _exhibit21_lookup(db, p.permittee_raw_name or "")
            if new_id:
                ex21_hits += 1
            else:
                # 2. Keyword
                new_id = await _keyword_lookup(
                    db, p.permittee_raw_name or "", cache=cache
                )
                if new_id:
                    keyword_hits += 1

            if new_id is not None:
                # Apply if different from current
                if p.resolved_company_id != new_id:
                    await db.execute(
                        update(GeneratorPermit)
                        .where(GeneratorPermit.id == p.id)
                        .values(resolved_company_id=new_id, confidence=0.85)
                    )
                else:
                    unchanged += 1
                continue

            # 3. No signal: clear self-named auto-resolutions
            curr_parent = existing_parents.get(p.id)
            if curr_parent and _norm(curr_parent) == _norm(p.permittee_raw_name or ""):
                await db.execute(
                    update(GeneratorPermit)
                    .where(GeneratorPermit.id == p.id)
                    .values(resolved_company_id=None, confidence=None)
                )
                cleared += 1
            elif curr_parent:
                # Genuine non-self parent (rare) -- leave alone.
                kept += 1
            else:
                unchanged += 1

        await db.commit()

        print(f"[relink] exhibit21 hits   : {ex21_hits}")
        print(f"[relink] keyword hits     : {keyword_hits}")
        print(f"[relink] cleared self-named: {cleared}")
        print(f"[relink] kept other parent: {kept}")
        print(f"[relink] unchanged        : {unchanged}")

        # --- Final report ----------------------------------------------
        total = (
            await db.execute(select(func.count(GeneratorPermit.id)))
        ).scalar_one()
        resolved_real = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM generator_permits gp "
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
                    "ORDER BY n DESC LIMIT 25"
                )
            )
        ).all()

        print(f"[relink] FINAL: total permits = {total}, "
              f"resolved -> real parent = {resolved_real}")
        print("[relink] top real parents:")
        for canon, n in by_parent:
            print(f"[relink]   {canon:35s} {n}")

        # Spot-check: any permit whose name contains 'bowman' / 'raiden'
        # / 'vadata' should now have a hyperscaler parent.
        spot = (
            await db.execute(
                text(
                    "SELECT gp.id, gp.source, gp.permittee_raw_name, c.canonical_name "
                    "FROM generator_permits gp "
                    "LEFT JOIN companies c ON c.id = gp.resolved_company_id "
                    "WHERE lower(coalesce(gp.permittee_raw_name,'')) ~ "
                    "  'vadata|raiden|bowman dev|mfnw|starbelt|amazoncom services|"
                    "azure fxs' "
                    "ORDER BY gp.id LIMIT 10"
                )
            )
        ).all()
        print("[relink] hyperscaler-LLC spot check:")
        for r in spot:
            print(f"[relink]   {dict(r._mapping)}")

        return 0 if resolved_real >= 20 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
