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

from agents.edgar_agent import fetch_real_8k_deals_async, fetch_real_quarterly_filings_async
from llm.client import MODELS, llm_client

logger = logging.getLogger(__name__)


# Strict JSON schema. additionalProperties=false so the LLM can't sneak in
# free-form fields. is_power_related is the relevance gate — false skips
# the row at insert time. headline is a short human-readable summary the
# Power Contracts table renders so the user doesn't have to read the
# placeholder excerpt.
EDGAR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_power_related":  {"type": "boolean"},
        "relevance_reason":  {"type": ["string", "null"]},
        "headline":          {"type": ["string", "null"]},
        "site_name":         {"type": ["string", "null"]},
        "capacity_mw":       {"type": ["number", "null"]},
        "counterparty":      {"type": ["string", "null"]},
        "signing_date":      {"type": ["string", "null"]},
        "energy_source":     {"type": ["string", "null"]},
        "buyer":             {"type": ["string", "null"]},
        "seller":            {"type": ["string", "null"]},
    },
    "required": [
        "is_power_related",
        "relevance_reason",
        "headline",
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
    "You are an SEC filings analyst classifying + extracting structured "
    "facts from an 8-K / 10-K excerpt. Two responsibilities, in order:\n\n"

    "STEP 1 — CLASSIFY whether this filing is power-related.\n"
    "  is_power_related = true ONLY if the filing materially discusses one "
    "of:\n"
    "    • power purchase agreements / PPAs / energy supply contracts\n"
    "    • power generation asset M&A (nuclear, solar, wind, gas plants)\n"
    "    • generator interconnection / transmission upgrades\n"
    "    • new datacenter campus + its associated power deal\n"
    "    • permits / regulatory approvals for power generation\n"
    "    • generation portfolio expansion / decommission / restart\n"
    "    • disclosed MW or GW of capacity tied to a deal\n"
    "  is_power_related = false for ALL of:\n"
    "    • CFO / officer appointments or departures (Item 5.02)\n"
    "    • earnings releases, dividend declarations, share buybacks\n"
    "    • debt offerings / indenture amendments (unless asset-backed by\n"
    "      power-generation collateral)\n"
    "    • litigation, cybersecurity-incident, governance updates\n"
    "    • routine 10-K/10-Q narrative without a specific power deal\n"
    "    • cloud / SaaS / software / chip revenue or capex announcements\n"
    "  Set relevance_reason to a one-sentence explanation either way.\n\n"

    "STEP 2 — If is_power_related = true, extract the structured fields. "
    "If false, set every field other than is_power_related and "
    "relevance_reason to null.\n\n"

    "FIELD DEFINITIONS (only filled when is_power_related = true):\n"
    "- headline: 1-line summary the dashboard renders (≤120 chars). Style: "
    "  '<buyer> signs <MW>MW <type> PPA with <seller>' or '<filer> "
    "  acquires <asset> for $<amount>'. Concrete and quantitative.\n"
    "- capacity_mw: the megawatts of POWER GENERATION CAPACITY contracted, "
    "  acquired, restarted, or otherwise the subject of THIS deal. NOT the "
    "  buyer's total corporate capacity, NOT chip wattage, NOT total cloud "
    "  capex, NOT annual revenue. Convert units: 1 GW = 1000 MW. If only "
    "  MWh/year is given, divide by 8760 hours. If a range, use midpoint. "
    "  If only an MWh storage figure with no duration, return null.\n"
    "- energy_source: ONE of nuclear, solar, wind, natural_gas, hydro, "
    "  geothermal, battery, mixed, or null.\n"
    "- buyer: the party PROCURING the power (e.g. Microsoft, Amazon, Meta).\n"
    "- seller: the party PROVIDING the power (utility, IPP, asset owner).\n"
    "- counterparty: the other side from the filer's perspective.\n"
    "- signing_date: YYYY-MM-DD if explicitly stated; null otherwise.\n"
    "- site_name: facility / plant / campus name if stated.\n\n"

    "WORKED EXAMPLES:\n\n"

    "Excerpt: 'Constellation Energy Corporation will restart Unit 1 of "
    "the Three Mile Island plant. The 20-year power purchase agreement "
    "with Microsoft will deliver 835 megawatts of carbon-free energy.'\n"
    "  → is_power_related=true, headline='Microsoft signs 20-yr 835 MW "
    "    nuclear PPA with Constellation (Three Mile Island restart)', "
    "    capacity_mw=835, energy_source=nuclear, buyer=Microsoft, "
    "    seller=Constellation Energy, site_name=Three Mile Island\n\n"

    "Excerpt: 'Amazon contracted approximately 200 million MWh of clean "
    "energy in 2024 across 510 projects.'\n"
    "  → is_power_related=true, headline='Amazon discloses 200M MWh "
    "    (~22.8 GW avg) clean-energy contracts across 510 projects', "
    "    capacity_mw=22831, energy_source=mixed, buyer=Amazon\n\n"

    "Excerpt: 'On April 6, 2026, Oracle announced that Hilary Maxson "
    "will join Oracle as Chief Financial Officer. Ms. Maxson will receive "
    "an annual base salary of $950,000 …'\n"
    "  → is_power_related=false, "
    "    relevance_reason='CFO appointment; no power-related content'\n\n"

    "Excerpt: 'Vistra Corp completed the acquisition of Cumulus Data, "
    "adding 2.5 GW of behind-the-meter generation capacity in PJM.'\n"
    "  → is_power_related=true, headline='Vistra acquires Cumulus Data, "
    "    adding 2.5 GW behind-the-meter capacity in PJM', "
    "    capacity_mw=2500, buyer=Vistra Corp, seller=Cumulus Data\n\n"

    "Excerpt: 'Oracle reported Q4 cloud revenue of $5.4 billion, up 24% "
    "year-over-year, and announced a $25B share-repurchase authorization.'\n"
    "  → is_power_related=false, "
    "    relevance_reason='earnings + buyback; no power deal disclosed'\n\n"

    "Excerpt: 'Constellation issued $1.5B of senior notes due 2034 to "
    "fund general corporate purposes.'\n"
    "  → is_power_related=false, "
    "    relevance_reason='debt offering not asset-backed by specific "
    "power generation; routine treasury'\n\n"

    "If is_power_related=true but a specific power-MW figure isn't stated, "
    "set capacity_mw=null. Never fabricate. Never convert chip wattage, "
    "datacenter sqft, or revenue figures into MW.\n\n"
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

    Calls the LLM once per filing for combined (classify + extract). Skips
    inserts when the classifier returns is_power_related=false. Upserts
    surviving rows into edgar_extractions with parser_version='llm-v3'.
    Returns counters: fetched, stored, skipped (incl. classifier-rejected),
    errors.
    """
    raw = await fetch_real_8k_deals_async(since)
    fetched = len(raw)
    stored = 0
    skipped = 0
    classifier_rejected = 0
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
                prompt_version="edgar_8k_v3",
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

        # CLASSIFIER GATE — drop non-power filings before they hit the table.
        # The relevance_reason is logged for explainability if anyone wonders
        # why a particular filing didn't show up.
        is_power_related = bool(result.get("is_power_related"))
        if not is_power_related:
            classifier_rejected += 1
            logger.info(
                "edgar_extractor.classifier_rejected",
                extra={
                    "accession": accession,
                    "filer": deal.get("source_company"),
                    "items": deal.get("items"),
                    "reason": (result.get("relevance_reason") or "")[:200],
                },
            )
            continue

        filing_date = _parse_date(deal.get("date"))
        buyer = result.get("buyer") or result.get("counterparty")
        seller = result.get("seller")
        capacity_mw = result.get("capacity_mw")
        energy_source = result.get("energy_source")
        # Prefer the LLM-generated headline; fall back to a clipped excerpt.
        # We persist the headline into the excerpt column so downstream
        # surfaces (announcements endpoint, drill modal) get something
        # readable instead of placeholder text.
        headline = (result.get("headline") or "").strip()
        stored_excerpt = headline if headline else excerpt[:600]
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
                    "excerpt": stored_excerpt[:2000],
                    "parser_version": "llm-v4-multiform",
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
        "classifier_rejected": classifier_rejected,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# AC1 (Phase 2): 10-K + 10-Q multi-form runner with per-chunk classify+merge.
# ---------------------------------------------------------------------------

def _merge_chunk_results(chunk_results: list[dict]) -> dict:
    """Merge per-chunk LLM extraction outputs into a single per-filing record.

    Rules:
      * is_power_related = OR across chunks (any true → true).
      * Numeric (capacity_mw): max of non-null values.
      * Categorical (energy_source, buyer, seller, site_name, headline,
        signing_date, counterparty): first non-null value wins.
      * relevance_reason: the first reason from a chunk where
        is_power_related=true; else the first reason at all.
    """
    merged = {
        "is_power_related": False,
        "relevance_reason": None,
        "headline": None,
        "site_name": None,
        "capacity_mw": None,
        "counterparty": None,
        "signing_date": None,
        "energy_source": None,
        "buyer": None,
        "seller": None,
    }
    positive_reason = None
    fallback_reason = None
    for r in chunk_results:
        if not r:
            continue
        if r.get("is_power_related"):
            merged["is_power_related"] = True
            if positive_reason is None and r.get("relevance_reason"):
                positive_reason = r["relevance_reason"]
        else:
            if fallback_reason is None and r.get("relevance_reason"):
                fallback_reason = r["relevance_reason"]
        # Numeric max
        cm = r.get("capacity_mw")
        if cm is not None:
            if merged["capacity_mw"] is None or cm > merged["capacity_mw"]:
                merged["capacity_mw"] = cm
        # Categorical first-non-null
        for k in ("headline", "site_name", "counterparty", "signing_date",
                 "energy_source", "buyer", "seller"):
            if merged[k] is None and r.get(k):
                merged[k] = r[k]
    merged["relevance_reason"] = positive_reason or fallback_reason
    return merged


async def run_llm_extraction_quarterly(
    session,
    since: str = "2024-01-01",
    limit: int = 10,
) -> dict:
    """Fetch 10-K + 10-Q filings, run classify+extract per chunk, merge,
    and upsert one row per accession into edgar_extractions.

    `limit` bounds the number of distinct accessions processed (NOT chunks);
    a 10-K split into 12 chunks counts as 1 accession.
    """
    all_chunks = await fetch_real_quarterly_filings_async(since)
    fetched = len(all_chunks)

    # Group chunks by edgar_url so we run the LLM per-chunk, then merge.
    by_acc: dict[str, list[dict]] = {}
    for c in all_chunks:
        by_acc.setdefault(c["edgar_url"], []).append(c)

    selected_urls = list(by_acc.keys())[:limit]

    stored = 0
    skipped = 0
    classifier_rejected = 0
    errors = 0

    for url in selected_urls:
        chunks = by_acc[url]
        cik_padded, accession = _parse_url(url)
        if not accession:
            skipped += 1
            continue

        # Run LLM on each chunk
        chunk_results: list[dict] = []
        for chunk in chunks:
            excerpt = chunk.get("excerpt") or ""
            if not excerpt.strip():
                continue
            try:
                extraction = await llm_client.extract(
                    model=MODELS["extraction"],
                    prompt_version="edgar_8k_v3",  # same prompt; works for any form
                    input_text=SYSTEM_PREAMBLE + excerpt,
                    schema=EDGAR_SCHEMA,
                )
            except Exception as exc:
                errors += 1
                logger.error(
                    "edgar_extractor_quarterly.llm_call_failed",
                    extra={"accession": accession, "chunk_index": chunk.get("chunk_index"),
                           "error": str(exc)},
                )
                continue
            chunk_results.append(extraction.result or {})

        if not chunk_results:
            skipped += 1
            continue

        merged = _merge_chunk_results(chunk_results)
        if not merged["is_power_related"]:
            classifier_rejected += 1
            logger.info(
                "edgar_extractor_quarterly.classifier_rejected",
                extra={"accession": accession,
                       "filer": chunks[0].get("source_company"),
                       "form": chunks[0].get("form"),
                       "reason": (merged.get("relevance_reason") or "")[:200]},
            )
            continue

        filing_date = _parse_date(chunks[0].get("date"))
        form_type = chunks[0].get("form") or "10-K"
        buyer = merged.get("buyer") or merged.get("counterparty")
        seller = merged.get("seller")
        capacity_mw = merged.get("capacity_mw")
        energy_source = merged.get("energy_source")
        headline = (merged.get("headline") or "").strip()
        stored_excerpt = headline if headline else (chunks[0].get("excerpt") or "")[:600]

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
                        form_type      = EXCLUDED.form_type,
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
                    "form_type": form_type,
                    "filing_date": filing_date,
                    "edgar_url": url,
                    "capacity_mw": capacity_mw,
                    "energy_source": energy_source,
                    "buyer_raw": buyer,
                    "seller_raw": seller,
                    "excerpt": stored_excerpt[:2000],
                    "parser_version": "llm-v4-multiform",
                    "confidence": 0.85,
                    "retrieved_at": datetime.utcnow(),
                    "created_at": datetime.utcnow(),
                },
            )
            stored += 1
        except Exception as exc:
            errors += 1
            logger.error(
                "edgar_extractor_quarterly.upsert_failed",
                extra={"accession": accession, "error": str(exc)},
            )

    await session.commit()
    return {
        "fetched": fetched,
        "accessions_selected": len(selected_urls),
        "stored": stored,
        "skipped": skipped,
        "classifier_rejected": classifier_rejected,
        "errors": errors,
    }
