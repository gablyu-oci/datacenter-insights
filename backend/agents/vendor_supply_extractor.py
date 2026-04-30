"""
EDGAR vendor-supply extractor (Phase 2 — Supplier Insights).

Parallel pipeline to backend/agents/edgar_extractor.py. The power-contract
extractor classifies filings for power deals (PPAs, MW capacity, generator
restart, etc.) and writes rows tagged pillar='power_contract'. THIS module
runs a separate pass to extract HARDWARE SUPPLY signals — Data Center
segment revenue, inventory, purchase commitments, customer concentration,
advanced packaging, optical transceivers — and writes rows tagged
pillar='vendor_supply' with parser_version='vendor_supply_v1'.

Pipeline:
  1. Regex prefilter: a chunk passes only if it contains a vendor-supply
     keyword AND a quantitative anchor AND no power-deal markers.
  2. LLM extract-only: chunks that pass the gate are sent to the LLM with
     a structured-extract prompt (no relevance classification).
  3. Insert-time gate: store the row only if at least one numeric field
     (revenue_usd / inventory_usd / purchase_commitments_usd /
     customer_concentration_pct) was extracted.

Packing convention (no schema change): the structured payload is
JSON-encoded into the `excerpt` column (truncated to 2000 chars).
buyer_raw carries the segment_name for cheap router-side filtering.

Public entry point:
    async def run_vendor_supply_extraction(session, since="2024-01-01",
                                           limit=None) -> dict
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import text

from agents.edgar_agent import (
    edgar_eligible_vendors,
    fetch_real_quarterly_filings_async,
)
from llm.client import MODELS, llm_client

logger = logging.getLogger(__name__)


# ── Regex prefilter ────────────────────────────────────────────────────
# A chunk passes when it has at least one supply-relevance keyword AND
# at least one quantitative anchor AND no power-deal markers.

VENDOR_KEYWORD_RE = re.compile(
    r"\b("
    # Segment / product names (multi-segment vendors like NVIDIA, Intel, AMD)
    r"Data\s*Center|DCAI|HPC|AI\s+infrastructure|"
    r"Compute\s*&?\s*Networking|Cloud\s*&?\s*Networking|"
    r"Advanced\s+Products|Optical\s+communications|Datacom|"
    r"Foundry|CoWoS|HBM|Tomahawk|Jericho|InfiniBand|"
    r"networking\s+semiconductor|AECs?|retimer|wafer|"
    r"semiconductor\s+process\s+control|advanced\s+packaging|"
    # Generic supplier-disclosure terms (for pure-play vendors like Credo,
    # Astera, Fabrinet, ASML where the whole company is hardware supply)
    r"revenue|net\s+sales|inventor(?:y|ies)|"
    r"purchase\s+(?:commitments?|obligations?)|supply\s+commitments?|"
    r"customer\s+concentration|top\s+(?:\d+\s+)?customers?|"
    r"backlog|remaining\s+performance\s+obligations|"
    r"shipments?|units\s+shipped|gross\s+margin|"
    r"capacity\s+utilization|wafer\s+starts?"
    r")\b",
    re.IGNORECASE,
)

VENDOR_QUANT_RE = re.compile(
    r"(?:"
    r"\$\s*[\d,]+(?:\.\d+)?\s*(?:B|M|K|billion|million|thousand)?"  # $ amount
    r"|\b\d+(?:\.\d+)?\s*%(?:\s*(?:YoY|year-?over-?year|growth|of\s+(?:revenue|sales)))?"  # percentage
    r"|(?:revenue|sales|inventory|orders|capacity|backlog|shipments?)\s+(?:grew|rose|increased|fell|declined|expanded|surged)\s+\d+"  # growth verbs
    r"|\bUS\$\s*[\d,]+(?:\.\d+)?\s*(?:B|M|billion|million)?"  # US$ amount
    r")",
    re.IGNORECASE,
)

POWER_DROP_RE = re.compile(
    r"\b("
    r"PPA|power\s+purchase\s+agreement|MW\b|megawatt|"
    r"nuclear\s+restart|generator\s+restart|gas-?fired\s+generation|"
    r"interconnection\s+queue|substation|transmission\s+line"
    r")\b",
    re.IGNORECASE,
)


# Schema for the LLM extract-only call. No is_vendor_supply_related — the
# regex gate is upstream. additionalProperties=false to keep the LLM honest.
VENDOR_SUPPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline":                   {"type": ["string", "null"]},
        "segment_name":               {"type": ["string", "null"]},
        "period_end":                 {"type": ["string", "null"]},
        "revenue_usd":                {"type": ["number", "null"]},
        "inventory_usd":              {"type": ["number", "null"]},
        "purchase_commitments_usd":   {"type": ["number", "null"]},
        "customer_concentration_pct": {"type": ["number", "null"]},
        "narrative_excerpt":          {"type": ["string", "null"]},
    },
    "required": [
        "headline",
        "segment_name",
        "period_end",
        "revenue_usd",
        "inventory_usd",
        "purchase_commitments_usd",
        "customer_concentration_pct",
        "narrative_excerpt",
    ],
    "additionalProperties": False,
}


VENDOR_SUPPLY_PREAMBLE = (
    "You are an SEC filings analyst extracting HARDWARE SUPPLY signals "
    "from a chunk of a 10-K / 10-Q / 20-F / 6-K. The chunk has already "
    "been pre-filtered to contain at least one supply-relevance keyword "
    "(Data Center, DCAI, HPC, Foundry, CoWoS, optics, etc.) and at least "
    "one quantitative anchor ($-figure, percentage, or growth verb). "
    "Your job is ONLY to extract structured fields from this chunk. "
    "Populate every field; use null when a field is not stated.\n\n"

    "FIELD DEFINITIONS:\n"
    "- headline: ≤120 chars, '<Company> <segment> Q<n> revenue $X.YB ...' "
    "  style. Concrete and quantitative when possible.\n"
    "- segment_name: copy verbatim from the excerpt ('Data Center', "
    "  'DCAI', 'Cloud & Networking', 'Advanced Products', 'HPC platform', "
    "  'Foundry', 'Optical', etc.). PREFERENCE: when the excerpt mentions "
    "  BOTH a vendor segment (Data Center, DCAI, AI, Foundry, Datacom, "
    "  Advanced Products, etc.) AND a top-line consolidated revenue, "
    "  ALWAYS pick the segment name and the segment's revenue figure -- "
    "  the supplier-insights tab cares about segment trends, not "
    "  consolidated totals. Use 'Total' only when no segment is named "
    "  in the excerpt at all.\n"
    "- period_end: YYYY-MM-DD calendar quarter-end the figure refers to. "
    "  For Credo's fiscal Q2 FY26 (calendar Q3 2025) → '2025-09-30'. "
    "  For ASML 6-K Q1 2026 → '2026-03-31'. For NVIDIA Q1 FY26 → "
    "  '2025-04-27'. Null if unclear.\n"
    "- revenue_usd: in raw USD (NOT millions). '$5.1 billion' → "
    "  5100000000. '$268.0M' → 268000000. '$1.4B' → 1400000000. Never "
    "  emit a value in millions or billions; always raw USD. Null if no "
    "  absolute revenue figure is stated.\n"
    "- inventory_usd: same units rule. Null unless an inventory $ figure "
    "  is present.\n"
    "- purchase_commitments_usd: same units rule. Capture unconditional "
    "  purchase obligations / supply commitments. Null otherwise.\n"
    "- customer_concentration_pct: numeric percent. 'Nvidia ~35% of FY "
    "  revenue' → 35.0. 'top 3 customers = 88%' → 88.0. Range '70-80%' "
    "  → midpoint 75.0. Null if no concentration figure.\n"
    "- narrative_excerpt: ≤400 chars, the verbatim sentence(s) from the "
    "  filing supporting the figures. Preserve disambiguating context.\n\n"

    "WORKED EXAMPLES:\n\n"

    "Excerpt: 'NVIDIA Q1 FY26 Data Center revenue rose to $39.1 billion, "
    "up 73% year-over-year, driven by Hopper and Blackwell ramp.'\n"
    "  → segment_name='Data Center', revenue_usd=39100000000, "
    "    period_end='2025-04-27', "
    "    headline='NVIDIA Q1 FY26 Data Center revenue $39.1B (+73% YoY)', "
    "    narrative_excerpt='NVIDIA Q1 FY26 Data Center revenue rose to "
    "    $39.1 billion, up 73% YoY, driven by Hopper and Blackwell ramp.'\n\n"

    "Excerpt: 'Credo Q2 FY26 revenue $268.0M, +272% YoY; top 3 customers "
    "= 88% of revenue.'\n"
    "  → segment_name='Total', revenue_usd=268000000, "
    "    customer_concentration_pct=88.0, period_end='2025-09-30', "
    "    headline='Credo Q2 FY26 revenue $268M (+272% YoY); top 3 = 88%', "
    "    narrative_excerpt='Credo Q2 FY26 revenue $268.0M, +272% YoY; "
    "    top 3 customers = 88% of revenue.'\n\n"

    "Excerpt: 'Amkor FY2025 net sales $6,708M; Advanced Products $5,556M "
    "(82.8% of net sales); 2.5D/HDFO revenue expected to nearly triple "
    "in 2026.'\n"
    "  → segment_name='Advanced Products', revenue_usd=5556000000, "
    "    period_end='2025-12-31', "
    "    headline='Amkor FY2025 Advanced Products $5.56B (82.8%)', "
    "    narrative_excerpt='Amkor FY2025 net sales $6,708M; Advanced "
    "    Products $5,556M (82.8%); 2.5D/HDFO to ~triple in 2026.'\n\n"

    "Excerpt: 'Data Center computing grew 59%, driven by demand for our "
    "Blackwell computing platform. Revenue from Data Center networking "
    "grew 142%.'\n"
    "  → segment_name='Data Center', revenue_usd=null (no absolute $ "
    "    figure), period_end=null, "
    "    headline='Data Center computing +59% YoY; Networking +142% YoY', "
    "    narrative_excerpt='Data Center computing grew 59%... Revenue "
    "    from Data Center networking grew 142%.'\n"
    "    (Note: this row would be discarded at insert time because all "
    "    four numeric fields are null. That's correct — qualitative-only "
    "    growth rates without absolute figures don't power the timeseries "
    "    chart.)\n\n"

    "Never fabricate numbers. Be conservative: if a figure isn't clearly "
    "stated in the excerpt, leave it null. Always emit a complete JSON "
    "object matching the schema.\n\n"
    "EXCERPT:\n"
)


# Pattern: https://www.sec.gov/Archives/edgar/data/<cik>/<accpath>/<doc>
_URL_RE = re.compile(
    r"/Archives/edgar/data/(?P<cik>\d+)/(?P<accpath>\d{18})/"
)


def _parse_url(url: str) -> tuple[str | None, str | None]:
    """Parse (cik_padded, accession_number) out of an EDGAR URL."""
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


def _passes_regex_gate(excerpt: str) -> bool:
    """Cheap deterministic gate before any LLM call.

    True if the excerpt contains a vendor-supply keyword AND a quantitative
    anchor AND no obvious power-deal markers.
    """
    if not excerpt:
        return False
    if not VENDOR_KEYWORD_RE.search(excerpt):
        return False
    if not VENDOR_QUANT_RE.search(excerpt):
        return False
    if POWER_DROP_RE.search(excerpt):
        return False
    return True


def _has_useful_numeric(merged: dict) -> bool:
    """Insert-time gate: at least one numeric extraction field non-null."""
    for k in (
        "revenue_usd",
        "inventory_usd",
        "purchase_commitments_usd",
        "customer_concentration_pct",
    ):
        v = merged.get(k)
        if v is not None:
            try:
                if float(v) != 0.0 or k == "customer_concentration_pct":
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _merge_vendor_supply_chunks(chunk_results: list[dict]) -> dict:
    """Merge per-chunk extractions into a single per-filing record.

    Numeric fields: max of non-null values across chunks.
    Categorical fields: first non-null wins.
    """
    merged = {
        "headline": None,
        "segment_name": None,
        "period_end": None,
        "revenue_usd": None,
        "inventory_usd": None,
        "purchase_commitments_usd": None,
        "customer_concentration_pct": None,
        "narrative_excerpt": None,
    }
    numeric_keys = (
        "revenue_usd",
        "inventory_usd",
        "purchase_commitments_usd",
        "customer_concentration_pct",
    )
    categorical_keys = (
        "headline",
        "segment_name",
        "period_end",
        "narrative_excerpt",
    )
    for r in chunk_results:
        if not r:
            continue
        for k in numeric_keys:
            v = r.get(k)
            if v is None:
                continue
            try:
                vf = float(v)
            except (TypeError, ValueError):
                continue
            if merged[k] is None or vf > merged[k]:
                merged[k] = vf
        for k in categorical_keys:
            if merged[k] is None and r.get(k):
                merged[k] = r[k]
    return merged


# Per-CIK accession cap mirrors the fetcher's PER_FILER_CAP=6.
_PER_CIK_ACCESSION_CAP = 6


async def run_vendor_supply_extraction(
    session,
    since: str = "2024-01-01",
    limit: int | None = None,
) -> dict:
    """Fetch quarterly filings for EDGAR-eligible vendors and extract
    vendor-supply signals.

    Reuses the project's shared quarterly cache via
    fetch_real_quarterly_filings_async — no additional HTTP if the cache
    is fresh. Filters chunks to vendor CIKs only, applies a regex gate,
    runs the LLM extract-only on passing chunks, merges per accession,
    and upserts a pillar='vendor_supply' row when at least one numeric
    field was extracted.

    Returns:
      dict with keys: fetched, vendor_chunks, regex_skipped,
      llm_calls, accessions_with_extraction, vendors_with_data,
      stored, no_numeric_extracted, errors.
    """
    eligible = list(edgar_eligible_vendors())
    vendor_ciks: set[str] = {v.cik for v in eligible if v.cik}

    all_chunks = await fetch_real_quarterly_filings_async(since)
    fetched = len(all_chunks)

    # Filter to vendor-only chunks.
    vendor_chunks_list = []
    for c in all_chunks:
        cik_padded, _acc = _parse_url(c.get("edgar_url") or "")
        if cik_padded and cik_padded in vendor_ciks:
            vendor_chunks_list.append(c)
    vendor_chunks = len(vendor_chunks_list)

    # Group by accession URL and enforce per-CIK accession cap.
    by_acc: dict[str, list[dict]] = {}
    for c in vendor_chunks_list:
        by_acc.setdefault(c["edgar_url"], []).append(c)

    cik_counts: dict[str, int] = {}
    capped_urls: list[str] = []
    for url, chunks in by_acc.items():
        cik_padded, _acc = _parse_url(url)
        cik_padded = cik_padded or ""
        if cik_counts.get(cik_padded, 0) >= _PER_CIK_ACCESSION_CAP:
            continue
        capped_urls.append(url)
        cik_counts[cik_padded] = cik_counts.get(cik_padded, 0) + 1

    selected_urls = capped_urls if limit is None else capped_urls[:limit]

    stored = 0
    no_numeric_extracted = 0
    regex_skipped = 0
    llm_calls = 0
    accessions_with_extraction = 0
    errors = 0
    vendors_with_data: set[str] = set()

    for url in selected_urls:
        chunks = by_acc[url]
        cik_padded, accession = _parse_url(url)
        if not accession:
            continue

        chunk_results: list[dict] = []
        for chunk in chunks:
            excerpt_text = chunk.get("excerpt") or ""
            if not excerpt_text.strip():
                continue
            if not _passes_regex_gate(excerpt_text):
                regex_skipped += 1
                continue
            try:
                extraction = await llm_client.extract(
                    model=MODELS["extraction"],
                    prompt_version="vendor_supply_v1",
                    input_text=VENDOR_SUPPLY_PREAMBLE + excerpt_text,
                    schema=VENDOR_SUPPLY_SCHEMA,
                )
                llm_calls += 1
            except Exception as exc:
                errors += 1
                logger.error(
                    "vendor_supply_extractor.llm_call_failed",
                    extra={
                        "accession": accession,
                        "chunk_index": chunk.get("chunk_index"),
                        "error": str(exc),
                    },
                )
                continue
            chunk_results.append(extraction.result or {})

        if not chunk_results:
            continue
        accessions_with_extraction += 1

        merged = _merge_vendor_supply_chunks(chunk_results)
        if not _has_useful_numeric(merged):
            no_numeric_extracted += 1
            logger.info(
                "vendor_supply_extractor.no_numeric_extracted",
                extra={
                    "accession": accession,
                    "filer": chunks[0].get("source_company"),
                    "form": chunks[0].get("form"),
                },
            )
            continue

        filing_date = _parse_date(chunks[0].get("date"))
        form_type = chunks[0].get("form") or "10-K"

        payload = {
            "headline": merged.get("headline"),
            "segment_name": merged.get("segment_name"),
            "period_end": merged.get("period_end"),
            "revenue_usd": merged.get("revenue_usd"),
            "inventory_usd": merged.get("inventory_usd"),
            "purchase_commitments_usd": merged.get("purchase_commitments_usd"),
            "customer_concentration_pct": merged.get(
                "customer_concentration_pct"
            ),
            "narrative_excerpt": merged.get("narrative_excerpt"),
        }
        excerpt_json = json.dumps(payload, default=str)[:2000]
        buyer_raw_segment = merged.get("segment_name")
        confidence = 0.85

        try:
            await session.execute(
                text(
                    """
                    INSERT INTO edgar_extractions (
                        cik, accession_number, form_type, filing_date,
                        edgar_url, capacity_mw, energy_source, buyer_raw,
                        seller_raw, excerpt, parser_version, confidence,
                        retrieved_at, created_at, pillar
                    ) VALUES (
                        :cik, :accession_number, :form_type, :filing_date,
                        :edgar_url, NULL, NULL, :buyer_raw, NULL, :excerpt,
                        'vendor_supply_v1', :confidence, :retrieved_at,
                        :created_at, 'vendor_supply'
                    )
                    ON CONFLICT (accession_number) DO UPDATE SET
                        excerpt        = EXCLUDED.excerpt,
                        buyer_raw      = EXCLUDED.buyer_raw,
                        parser_version = EXCLUDED.parser_version,
                        pillar         = EXCLUDED.pillar,
                        confidence     = EXCLUDED.confidence,
                        retrieved_at   = EXCLUDED.retrieved_at
                    WHERE edgar_extractions.parser_version IN
                          ('vendor_supply_v1')
                       OR edgar_extractions.pillar = 'vendor_supply'
                    """
                ),
                {
                    "cik": cik_padded or "",
                    "accession_number": accession,
                    "form_type": form_type,
                    "filing_date": filing_date,
                    "edgar_url": url,
                    "buyer_raw": buyer_raw_segment,
                    "excerpt": excerpt_json,
                    "confidence": confidence,
                    "retrieved_at": datetime.utcnow(),
                    "created_at": datetime.utcnow(),
                },
            )
            stored += 1
            if cik_padded:
                vendors_with_data.add(cik_padded)
        except Exception as exc:
            errors += 1
            logger.error(
                "vendor_supply_extractor.upsert_failed",
                extra={"accession": accession, "error": str(exc)},
            )

    await session.commit()
    return {
        "fetched": fetched,
        "vendor_chunks": vendor_chunks,
        "regex_skipped": regex_skipped,
        "llm_calls": llm_calls,
        "accessions_with_extraction": accessions_with_extraction,
        "stored": stored,
        "no_numeric_extracted": no_numeric_extracted,
        "vendors_with_data": sorted(vendors_with_data),
        "errors": errors,
    }
