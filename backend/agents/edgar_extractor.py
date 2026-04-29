"""
EDGAR LLM extractor -- Phase 1C.

Replaces the regex parsing in agents/edgar_agent.py with an LLM-driven
structured extractor. Reuses fetch_real_8k_deals_async() to obtain raw
filings (including the cleaned excerpt), then calls llm_client.extract()
with a strict JSON schema and upserts results into edgar_extractions.

Public entry point:
    async def run_llm_extraction(session, since="2024-01-01", limit=5) -> dict
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import text

from agents.edgar_agent import fetch_real_8k_deals_async
from llm.client import MODELS, llm_client

logger = logging.getLogger(__name__)


# Strict JSON schema for the extractor (additionalProperties=false).
EDGAR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "site_name":     {"type": ["string", "null"]},
        "capacity_mw":   {"type": ["number", "null"]},
        "counterparty":  {"type": ["string", "null"]},
        "signing_date":  {"type": ["string", "null"]},
        "energy_source": {"type": ["string", "null"]},
        "buyer":         {"type": ["string", "null"]},
        "seller":        {"type": ["string", "null"]},
    },
    "required": [
        "site_name",
        "capacity_mw",
        "counterparty",
        "signing_date",
        "energy_source",
        "buyer",
        "seller",
    ],
    "additionalProperties": False,
}


SYSTEM_PREAMBLE = (
    "You are extracting structured power-deal facts from an SEC 8-K excerpt. "
    "Follow these rules exactly.\n\n"
    "FIELD DEFINITIONS:\n"
    "- capacity_mw: the megawatts of POWER GENERATION CAPACITY contracted, "
    "  acquired, restarted, or otherwise the subject of THIS deal. NOT the "
    "  buyer's total corporate capacity, NOT NVIDIA-chip wattage, NOT total "
    "  cloud capex, NOT annual revenue. Convert units: 1 GW = 1000 MW; "
    "  1,000 MW = 1 GW. If only MWh/year is given, divide by 8760 hours. If "
    "  a range is given (e.g. '300–500 MW'), use the midpoint. If only a "
    "  storage figure in MWh is given without a duration, return null.\n"
    "- energy_source: ONE of nuclear, solar, wind, natural_gas, hydro, "
    "  geothermal, battery, mixed (multi-source PPA / portfolio), or null.\n"
    "- buyer: the party PROCURING the power (e.g. Microsoft, Amazon, Meta, "
    "  Google, Oracle). For utility/operator-side filings (Constellation, "
    "  Talen, Vistra) the buyer may be a hyperscaler counterparty.\n"
    "- seller: the party PROVIDING the power (utility, IPP, asset owner).\n"
    "- counterparty: the OTHER side of the deal from the filer's perspective. "
    "  If the filer is the seller, counterparty = buyer; if filer is the "
    "  buyer, counterparty = seller.\n"
    "- signing_date: YYYY-MM-DD if explicitly stated; null otherwise.\n"
    "- site_name: facility / plant / campus name if stated.\n\n"
    "WORKED EXAMPLES:\n"
    "Excerpt: 'Constellation Energy Corporation will restart Unit 1 of the "
    "Three Mile Island plant. The 20-year power purchase agreement with "
    "Microsoft will deliver 835 megawatts of carbon-free energy.'\n"
    "  → capacity_mw=835, energy_source=nuclear, buyer=Microsoft, "
    "    seller=Constellation Energy, site_name=Three Mile Island\n\n"
    "Excerpt: 'Amazon contracted approximately 200 million MWh of clean "
    "energy in 2024 across 510 projects.'\n"
    "  → capacity_mw=22831 (200,000,000 / 8760), energy_source=mixed, "
    "    buyer=Amazon, seller=null\n\n"
    "Excerpt: 'Talen Energy completed the acquisition of Cumulus Data for "
    "approximately $650 million. The transaction adds 2.5 GW of behind-the-"
    "meter capacity.'\n"
    "  → capacity_mw=2500, energy_source=null, buyer=Talen Energy, "
    "    seller=Cumulus Data\n\n"
    "Excerpt: 'Oracle reported Q4 cloud revenue of $5.4 billion, up 24% YoY.'\n"
    "  → capacity_mw=null, energy_source=null, buyer=null, seller=null "
    "    (this is not a power-deal disclosure)\n\n"
    "If the excerpt does not state a specific power-MW figure for the deal, "
    "return capacity_mw=null. NEVER fabricate a number. NEVER convert chip "
    "wattage, datacenter sqft, or revenue figures into MW.\n\n"
    "EXCERPT:\n"
)


# Pattern: https://www.sec.gov/Archives/edgar/data/<cik>/<accpath>/<doc>
_URL_RE = re.compile(
    r"/Archives/edgar/data/(?P<cik>\d+)/(?P<accpath>\d{18})/"
)


def _parse_url(url: str) -> tuple[str | None, str | None]:
    """Parse (cik_padded, accession_number) out of an EDGAR URL.

    accpath like '000189215424001234' becomes '0001892154-24-001234'.
    """
    if not url:
        return None, None
    m = _URL_RE.search(url)
    if not m:
        return None, None
    cik_num = m.group("cik")
    accpath = m.group("accpath")
    if len(accpath) != 18:
        return cik_num.zfill(10), None
    accession = f"{accpath[:10]}-{accpath[10:12]}-{accpath[12:]}"
    return cik_num.zfill(10), accession


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


async def run_llm_extraction(
    session,
    since: str = "2024-01-01",
    limit: int = 5,
) -> dict:
    """Fetch EDGAR 8-Ks since `since` and run LLM extraction on up to `limit`.

    Upserts results (parser_version='llm-v1') into edgar_extractions.
    Returns a counters dict.
    """
    raw = await fetch_real_8k_deals_async(since)
    fetched = len(raw)
    stored = 0
    skipped = 0
    errors = 0

    eligible = [d for d in raw if (d.get("excerpt") or "").strip()]
    selected = eligible[:limit]

    for deal in selected:
        excerpt = deal.get("excerpt") or ""
        url = deal.get("edgar_url") or ""
        cik_padded, accession = _parse_url(url)
        if not accession:
            skipped += 1
            logger.warning(
                "edgar_extractor.skip_no_accession",
                extra={"url": url[:200]},
            )
            continue

        try:
            extraction = await llm_client.extract(
                model=MODELS["extraction"],
                prompt_version="edgar_8k_v2",
                input_text=SYSTEM_PREAMBLE + excerpt,
                schema=EDGAR_SCHEMA,
            )
        except Exception as exc:
            errors += 1
            logger.error(
                "edgar_extractor.llm_call_failed",
                extra={"accession": accession, "error": str(exc)},
            )
            continue

        if extraction.errors:
            errors += 1
            logger.warning(
                "edgar_extractor.llm_parse_errors",
                extra={"accession": accession, "errors": extraction.errors},
            )

        result = extraction.result or {}
        filing_date = _parse_date(deal.get("date"))
        buyer = result.get("buyer") or result.get("counterparty")
        seller = result.get("seller")
        capacity_mw = result.get("capacity_mw")
        energy_source = result.get("energy_source")
        confidence = extraction.confidence

        # Upsert via raw SQL ON CONFLICT (accession_number) DO UPDATE.
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO edgar_extractions (
                        cik, accession_number, form_type, filing_date,
                        edgar_url, capacity_mw, energy_source, buyer_raw,
                        seller_raw, excerpt, parser_version, confidence,
                        retrieved_at, created_at
                    ) VALUES (
                        :cik, :accession_number, :form_type, :filing_date,
                        :edgar_url, :capacity_mw, :energy_source, :buyer_raw,
                        :seller_raw, :excerpt, :parser_version, :confidence,
                        :retrieved_at, :created_at
                    )
                    ON CONFLICT (accession_number) DO UPDATE SET
                        capacity_mw    = EXCLUDED.capacity_mw,
                        energy_source  = EXCLUDED.energy_source,
                        buyer_raw      = EXCLUDED.buyer_raw,
                        seller_raw     = EXCLUDED.seller_raw,
                        excerpt        = EXCLUDED.excerpt,
                        parser_version = EXCLUDED.parser_version,
                        confidence     = EXCLUDED.confidence,
                        retrieved_at   = EXCLUDED.retrieved_at
                    """
                ),
                {
                    "cik": cik_padded or "",
                    "accession_number": accession,
                    "form_type": "8-K",
                    "filing_date": filing_date,
                    "edgar_url": url,
                    "capacity_mw": capacity_mw,
                    "energy_source": energy_source,
                    "buyer_raw": buyer,
                    "seller_raw": seller,
                    "excerpt": excerpt[:2000],
                    "parser_version": "llm-v2",
                    "confidence": confidence,
                    "retrieved_at": datetime.utcnow(),
                    "created_at": datetime.utcnow(),
                },
            )
            stored += 1
        except Exception as exc:
            errors += 1
            logger.error(
                "edgar_extractor.upsert_failed",
                extra={"accession": accession, "error": str(exc)},
            )

    await session.commit()
    return {
        "fetched": fetched,
        "stored": stored,
        "skipped": skipped,
        "errors": errors,
    }
