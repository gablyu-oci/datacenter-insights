"""
One-shot seed: migrate the 23 hand-verified deals from the legacy Python
module into the curated_deals DB table. Idempotent — safe to re-run; uses
ON CONFLICT (legacy_id) DO UPDATE so re-running picks up edits.

Usage:
  cd backend && .venv/bin/python -m seed.seed_curated_deals
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from db.session import async_session_factory


logger = logging.getLogger(__name__)


# Source of historical truth — the 23 hand-verified deals (with real source
# URLs) live as a JSON data file alongside this script, NOT as Python code.
# Adding/editing deals = edit the JSON. The seed script is the only place
# this data lives outside the DB.
import json
from pathlib import Path

_DATA_FILE = Path(__file__).parent / "data" / "curated_deals.json"


def _load_legacy_deals() -> list[dict]:
    with _DATA_FILE.open() as f:
        return json.load(f)


SQL_UPSERT = text(
    """
    INSERT INTO curated_deals (
        legacy_id, buyer, seller, deal_type, energy_source, capacity_mw,
        location, state, lat, lon, announced_date, status, duration_years,
        headline, excerpt, source_type, source_url, edgar_url, confidence,
        data_source, energy_contract_mwh_million, note, created_at, updated_at
    ) VALUES (
        :legacy_id, :buyer, :seller, :deal_type, :energy_source, :capacity_mw,
        :location, :state, :lat, :lon, :announced_date, :status, :duration_years,
        :headline, :excerpt, :source_type, :source_url, :edgar_url, :confidence,
        :data_source, :energy_contract_mwh_million, :note, NOW(), NOW()
    )
    ON CONFLICT (legacy_id) DO UPDATE SET
        buyer = EXCLUDED.buyer,
        seller = EXCLUDED.seller,
        deal_type = EXCLUDED.deal_type,
        energy_source = EXCLUDED.energy_source,
        capacity_mw = EXCLUDED.capacity_mw,
        location = EXCLUDED.location,
        state = EXCLUDED.state,
        lat = EXCLUDED.lat,
        lon = EXCLUDED.lon,
        announced_date = EXCLUDED.announced_date,
        status = EXCLUDED.status,
        duration_years = EXCLUDED.duration_years,
        headline = EXCLUDED.headline,
        excerpt = EXCLUDED.excerpt,
        source_type = EXCLUDED.source_type,
        source_url = EXCLUDED.source_url,
        edgar_url = EXCLUDED.edgar_url,
        confidence = EXCLUDED.confidence,
        data_source = EXCLUDED.data_source,
        energy_contract_mwh_million = EXCLUDED.energy_contract_mwh_million,
        note = EXCLUDED.note,
        updated_at = NOW()
    """
)


async def seed_curated_deals() -> int:
    """Upsert every row from CURATED_DEALS into the curated_deals table."""
    deals = _load_legacy_deals()
    n = 0
    async with async_session_factory() as session:
        for deal in deals:
            params = {
                "legacy_id": deal.get("id") or deal.get("legacy_id"),
                "buyer": deal.get("buyer", ""),
                "seller": deal.get("seller"),
                "deal_type": deal.get("deal_type"),
                "energy_source": deal.get("energy_source"),
                "capacity_mw": deal.get("capacity_mw"),
                "location": deal.get("location"),
                "state": deal.get("state"),
                "lat": deal.get("lat"),
                "lon": deal.get("lon"),
                "announced_date": deal.get("announced_date"),
                "status": deal.get("status"),
                "duration_years": deal.get("duration_years"),
                "headline": deal.get("headline"),
                "excerpt": deal.get("excerpt"),
                "source_type": deal.get("source_type"),
                "source_url": deal.get("source_url"),
                "edgar_url": deal.get("edgar_url"),
                "confidence": deal.get("confidence"),
                # parser_version is reserved for live extractions; for the
                # one-time seed we set data_source so it's clear this row was
                # imported, not LLM-derived.
                "data_source": deal.get("data_source") or "curated-seed-v1",
                "energy_contract_mwh_million": deal.get("energy_contract_mwh_million"),
                "note": deal.get("note"),
            }
            if not params["legacy_id"]:
                logger.warning("seed_curated_deals.skip_no_id", extra={"deal": deal.get("buyer")})
                continue
            await session.execute(SQL_UPSERT, params)
            n += 1
        await session.commit()
    logger.info("seed_curated_deals.done", extra={"upserted": n})
    return n


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    count = asyncio.run(seed_curated_deals())
    print(f"upserted {count} curated_deals rows")
