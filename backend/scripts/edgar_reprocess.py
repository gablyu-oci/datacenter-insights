"""Runnable entry point for the EDGAR reprocess pipeline (EDGAR-7).

Bootstraps an async session and calls the same code path as the
`edgar-reprocess` Click subcommand, so operators can invoke either:

    python cli.py edgar-reprocess --dry-run --limit 50
    python -m scripts.edgar_reprocess --dry-run --limit 50

Both share the same `reprocess_one()` implementation in
agents/edgar_extractor.py.
"""
from __future__ import annotations

import argparse
import asyncio


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Re-run EDGAR validation pipeline.")
    p.add_argument("--dry-run", action="store_true", help="Compute deltas but skip UPDATE.")
    p.add_argument("--limit", type=int, default=None, help="Process at most N rows.")
    return p.parse_args()


async def _main(dry_run: bool, limit: int | None) -> None:
    from db.session import async_session_factory
    from db.models import EdgarExtraction
    from sqlalchemy import select, func
    from agents.edgar_extractor import reprocess_one, _load_known_company_names

    async with async_session_factory() as session:
        before_count = (
            await session.execute(select(func.count(EdgarExtraction.id)))
        ).scalar() or 0
        known_company_names = await _load_known_company_names(session)

        stmt = select(EdgarExtraction).order_by(EdgarExtraction.id)
        if limit:
            stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

        deduped = 0
        flagged = 0
        changed = 0
        for row in rows:
            delta = await reprocess_one(
                session, row, known_company_names=known_company_names,
            )
            if delta.get("changed"):
                changed += 1
            after = delta.get("after") or {}
            if after.get("flagged_capacity"):
                flagged += 1
            before = delta.get("before") or {}
            if after.get("canonical_deal_id") and not before.get("canonical_deal_id"):
                deduped += 1

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

        after_count = (
            await session.execute(select(func.count(EdgarExtraction.id)))
        ).scalar() or 0

    print(f"EDGAR rows before: {before_count}, after: {after_count}, deduped: {deduped}, flagged: {flagged}")
    print(f"  rows changed: {changed} (dry_run={dry_run})")


def main() -> None:
    args = _parse_args()
    asyncio.run(_main(args.dry_run, args.limit))


if __name__ == "__main__":
    main()
