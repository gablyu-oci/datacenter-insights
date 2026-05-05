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

import hashlib
import logging
import re
from datetime import date as _date, date, datetime
from typing import Any

from sqlalchemy import text

from agents.edgar_agent import fetch_real_8k_deals_async, fetch_real_quarterly_filings_async
from agents.edgar_buyer_validator import validate_buyer
from llm.client import MODELS, llm_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical deal-id helpers (EDGAR-4)
# ---------------------------------------------------------------------------

_CORP_NOISE = re.compile(
    r"\b(inc\.?|llc|l\.l\.c\.|corp\.?|co\.?|ltd\.?|company|the|holdings|"
    r"corporation|energy)\b",
    re.IGNORECASE,
)


def _normalize_party(name):
    """Lowercase + strip corporate-suffix noise + collapse whitespace.

    Used to bucket "Microsoft", "Microsoft Corp", "Microsoft Corporation",
    "The Microsoft Co." into a single canonical key for deal-level dedup.
    """
    if not name:
        return ""
    n = name.lower()
    n = _CORP_NOISE.sub(" ", n)
    n = re.sub(r"[,.&/]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def compute_canonical_deal_id(buyer, seller, capacity_mw, signing_date):
    """Compute a stable 16-char hex digest for deal-level dedup.

    Buckets:
      buyer / seller -> normalized via _normalize_party()
      capacity_mw    -> nearest 1000 MW (so 27,000 MW and 31,676 MW
                        collapse — a single merger gets restated with
                        slightly different MW figures across quarterly
                        filings).
      signing_date   -> intentionally NOT in the key. The same deal
                        appears across N quarterly filings; using filing
                        date gave each mention a distinct ID. World-knowledge
                        constraint: the same buyer rarely signs two deals
                        with the same seller in the same MW bucket.

    Returns None when buyer is missing (we won't emit a dedup key without
    at least the buying party).

    Note: `signing_date` is accepted for back-compat with the call sites but
    deliberately ignored. Future change: pass an LLM-extracted deal-name
    field if/when extraction becomes reliable enough to disambiguate
    multiple parallel deals between the same parties.
    """
    if not buyer:
        return None
    b = _normalize_party(buyer)
    s = _normalize_party(seller) if seller else "unknown"
    # Tiered bucket: bucket size scales with magnitude. Same deal restated
    # across quarters often shifts MW by several GW (e.g. Calpine merger
    # restated as 27,000 → 31,676 MW). Bucket the long tail at 10 GW.
    if capacity_mw is None:
        cap_bucket = "unknown"
    elif capacity_mw < 1_000:
        cap_bucket = str(round(capacity_mw / 100) * 100)
    elif capacity_mw < 10_000:
        cap_bucket = str(round(capacity_mw / 1_000) * 1_000)
    else:
        cap_bucket = str(round(capacity_mw / 10_000) * 10_000)
    raw = f"{b}|{s}|{cap_bucket}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


# Capacity sanity threshold (EDGAR-6). 100 GW = 100,000 MW; anything past
# that is almost certainly a unit-conversion bug (annual MWh treated as MW,
# nameplate-vs-continuous confusion, etc.).
CAPACITY_FLAG_THRESHOLD_MW = 100_000


async def _load_known_company_names(session) -> set[str]:
    """One query per run: pull canonical_name for the buyer-validator allow-list."""
    try:
        result = await session.execute(text("SELECT canonical_name FROM companies"))
        return {row[0] for row in result.fetchall() if row[0]}
    except Exception as exc:
        logger.warning(
            "edgar_extractor.known_companies_load_failed",
            extra={"error": str(exc)},
        )
        return set()


async def _resolve_canonical_name(
    session,
    raw_name: str,
    *,
    source: str,
) -> tuple[int | None, str | None]:
    """Resolve raw -> (company_id, canonical_name) with confidence gate.

    Returns:
      (company_id, canonical_name) when entity_resolution returns a high-
      confidence non-auto-created match; otherwise (None, None) so the
      caller falls back to the validated raw value.
    """
    if not raw_name:
        return None, None
    try:
        from entity_resolution import resolve_company  # local import: avoid hard dep at module-load
    except Exception:
        return None, None
    try:
        company_id, confidence, match_method = await resolve_company(
            session, raw_name, source=source,
        )
    except Exception as exc:
        logger.warning(
            "edgar_extractor.entity_resolution_failed",
            extra={"raw_name": raw_name, "error": str(exc)},
        )
        return None, None
    if not company_id:
        return None, None
    if confidence < 0.90:
        return None, None
    if match_method == "auto_created":
        return None, None
    # Pull canonical name back out
    from db.models import Company
    from sqlalchemy import select
    company = (
        await session.execute(select(Company).where(Company.id == company_id))
    ).scalar_one_or_none()
    if not company:
        return None, None
    return company_id, company.canonical_name


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
        # EDGAR-2: capacity-derivation audit trail. ≤200 chars; nullable
        # only when the model fails to populate (we still persist the row).
        "methodology":       {"type": ["string", "null"], "maxLength": 200},
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
        "methodology",
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

    "MWh-TO-MW CONVERSION ALGORITHM (apply this strictly):\n"
    "1. Identify whether MWh is ANNUAL delivery or LIFETIME contracted volume.\n"
    "   Cues for LIFETIME: \"weighted-average remaining duration\", \"remaining contract life\",\n"
    "                       \"over X years\", \"cumulative contracted\", \"contract term\".\n"
    "   Cues for ANNUAL:   \"in 2024\", \"per year\", \"annual\", \"yearly\".\n"
    "2. If LIFETIME with stated duration in years:\n"
    "       capacity_mw = round(mwh_total / years / 8760)        # MW continuous-equivalent\n"
    "3. If ANNUAL:\n"
    "       capacity_mw = round(mwh_annual / 8760)\n"
    "4. If duration is unstated or ambiguous: set capacity_mw = null and put a clear\n"
    "   note in `methodology` explaining what's missing.\n"
    "5. ALWAYS populate `methodology` (≤200 chars) describing the calculation OR why\n"
    "   you couldn't compute MW.\n\n"

    "Note: 1 MW continuous = 8,760 MWh/year. NOT 8.76 — that's a unit error to avoid.\n\n"

    "WORKED EXAMPLES:\n\n"

    "Excerpt: 'Constellation Energy Corporation will restart Unit 1 of "
    "the Three Mile Island plant. The 20-year power purchase agreement "
    "with Microsoft will deliver 835 megawatts of carbon-free energy.'\n"
    "  → is_power_related=true, headline='Microsoft signs 20-yr 835 MW "
    "    nuclear PPA with Constellation (Three Mile Island restart)', "
    "    capacity_mw=835, energy_source=nuclear, buyer=Microsoft, "
    "    seller=Constellation Energy, site_name=Three Mile Island, "
    "    methodology='nameplate MW stated directly in filing'\n\n"

    "Excerpt: 'Amazon has contracted approximately 200 million megawatt-hours "
    "of clean energy and the weighted-average remaining duration of these "
    "contracts is approximately 16 years.'\n"
    "  → is_power_related=true, "
    "    headline='Amazon ~1.43 GW continuous-eq clean-energy portfolio (200M MWh / 16 yr)', "
    "    capacity_mw=1430, energy_source=mixed, buyer=Amazon, "
    "    methodology='200M MWh lifetime / 16 yr / 8760 hr = 1.43 GW continuous-eq'\n\n"

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


# Versioned tag stamped on every row produced by the new pipeline so
# operators can identify which records went through validation +
# canonicalization + dedup-id computation.
PARSER_VERSION = "llm-v5-power-pipeline"


async def _persist_extraction(
    session,
    *,
    accession: str,
    cik_padded: str,
    form_type: str,
    filing_date: date | None,
    edgar_url: str,
    result: dict,
    excerpt_fallback: str,
    confidence: float | None,
    known_company_names: set[str],
) -> dict:
    """Validate + canonicalize + persist one extraction.

    Returns a status dict suitable for delta-tracking from reprocess_one().
    Caller is responsible for the surrounding session.commit().
    """
    raw_buyer = result.get("buyer") or result.get("counterparty")
    raw_seller = result.get("seller")
    capacity_mw = result.get("capacity_mw")
    energy_source = result.get("energy_source")
    methodology = (result.get("methodology") or None)
    if methodology is not None:
        methodology = str(methodology)[:200]

    headline = (result.get("headline") or "").strip()
    stored_excerpt = headline if headline else excerpt_fallback[:600]

    # EDGAR-3: validate buyer / seller raw strings before insert.
    clean_buyer, buyer_reject = validate_buyer(raw_buyer, known_company_names)
    clean_seller, seller_reject = validate_buyer(raw_seller, known_company_names)
    rejected_buyer_raw = raw_buyer if buyer_reject else None
    rejected_seller_raw = raw_seller if seller_reject else None
    if buyer_reject:
        logger.info(
            "edgar_extractor.buyer_rejected",
            extra={"accession": accession, "raw": raw_buyer, "reason": buyer_reject},
        )
    if seller_reject:
        logger.info(
            "edgar_extractor.seller_rejected",
            extra={"accession": accession, "raw": raw_seller, "reason": seller_reject},
        )

    # EDGAR-5: canonicalize via entity_resolution if confidence ≥ 0.90 and
    # not auto_created. Otherwise we keep the validated raw value.
    buyer_company_id, buyer_canonical = (None, None)
    seller_company_id, seller_canonical = (None, None)
    if clean_buyer:
        buyer_company_id, buyer_canonical = await _resolve_canonical_name(
            session, clean_buyer, source="edgar_extraction",
        )
        if not buyer_canonical:
            buyer_canonical = clean_buyer
    if clean_seller:
        seller_company_id, seller_canonical = await _resolve_canonical_name(
            session, clean_seller, source="edgar_extraction",
        )
        if not seller_canonical:
            seller_canonical = clean_seller

    # EDGAR-6: capacity sanity guard. We still STORE the row; flag for FE.
    flagged_capacity = False
    if capacity_mw is not None and capacity_mw > CAPACITY_FLAG_THRESHOLD_MW:
        flagged_capacity = True
        logger.warning(
            "edgar_extractor.capacity_exceeds_threshold",
            extra={
                "capacity_mw": capacity_mw,
                "accession": accession,
                "buyer": clean_buyer,
            },
        )

    # EDGAR-4: canonical deal id for dedup grouping.
    # Track C: signing_date is now ONLY pulled from body prose. We do NOT
    # fall back to filing_date — that creates the canonical_deal_id phantom-
    # distinct bug Track A already fixed. compute_canonical_deal_id ignores
    # signing_date anyway in the post-Track-A implementation.
    signing_date = _parse_date(result.get("signing_date"))
    canonical_deal_id = compute_canonical_deal_id(
        clean_buyer, clean_seller, capacity_mw, signing_date,
    )

    # Track C: is_power_related — extractor's STEP-1 classifier sets this
    # explicitly for every row regardless of whether buyer/capacity got
    # extracted. Lets the UI show power-classified rows even when individual
    # fields are null. False default keeps backward compat.
    is_power_related = bool(result.get("is_power_related", False))

    # Track C: deal_index disambiguates multi-deal rows from one filing.
    # Caller passes it via result['_deal_index'] (defaults to 0 for the
    # legacy single-deal path).
    deal_index = int(result.get("_deal_index", 0))

    # appearance_count: how many times have we seen this canonical_deal_id?
    appearance_count = 1
    if canonical_deal_id:
        try:
            row = await session.execute(
                text(
                    "SELECT COALESCE(MAX(appearance_count), 0), COUNT(*) "
                    "FROM edgar_extractions WHERE canonical_deal_id = :cdid"
                ),
                {"cdid": canonical_deal_id},
            )
            existing_max, existing_count = row.fetchone() or (0, 0)
            appearance_count = max(int(existing_max or 0), int(existing_count or 0)) + 1
        except Exception as exc:
            logger.debug(
                "edgar_extractor.appearance_count_lookup_failed",
                extra={"accession": accession, "error": str(exc)},
            )

    try:
        await session.execute(
            text(
                """
                INSERT INTO edgar_extractions (
                    cik, accession_number, form_type, filing_date,
                    edgar_url, capacity_mw, energy_source,
                    buyer_raw, seller_raw,
                    rejected_buyer_raw, rejected_seller_raw,
                    buyer_canonical, seller_canonical,
                    buyer_company_id, seller_company_id,
                    methodology, canonical_deal_id, flagged_capacity,
                    appearance_count,
                    is_power_related, signing_date, deal_index,
                    excerpt, parser_version, confidence,
                    retrieved_at, created_at
                ) VALUES (
                    :cik, :accession_number, :form_type, :filing_date,
                    :edgar_url, :capacity_mw, :energy_source,
                    :buyer_raw, :seller_raw,
                    :rejected_buyer_raw, :rejected_seller_raw,
                    :buyer_canonical, :seller_canonical,
                    :buyer_company_id, :seller_company_id,
                    :methodology, :canonical_deal_id, :flagged_capacity,
                    :appearance_count,
                    :is_power_related, :signing_date, :deal_index,
                    :excerpt, :parser_version, :confidence,
                    :retrieved_at, :created_at
                )
                ON CONFLICT (accession_number, deal_index) DO UPDATE SET
                    form_type           = EXCLUDED.form_type,
                    capacity_mw         = EXCLUDED.capacity_mw,
                    energy_source       = EXCLUDED.energy_source,
                    buyer_raw           = EXCLUDED.buyer_raw,
                    seller_raw          = EXCLUDED.seller_raw,
                    rejected_buyer_raw  = EXCLUDED.rejected_buyer_raw,
                    rejected_seller_raw = EXCLUDED.rejected_seller_raw,
                    buyer_canonical     = EXCLUDED.buyer_canonical,
                    seller_canonical    = EXCLUDED.seller_canonical,
                    buyer_company_id    = EXCLUDED.buyer_company_id,
                    seller_company_id   = EXCLUDED.seller_company_id,
                    methodology         = EXCLUDED.methodology,
                    canonical_deal_id   = EXCLUDED.canonical_deal_id,
                    flagged_capacity    = EXCLUDED.flagged_capacity,
                    appearance_count    = EXCLUDED.appearance_count,
                    is_power_related    = EXCLUDED.is_power_related,
                    signing_date        = EXCLUDED.signing_date,
                    excerpt             = EXCLUDED.excerpt,
                    parser_version      = EXCLUDED.parser_version,
                    confidence          = EXCLUDED.confidence,
                    retrieved_at        = EXCLUDED.retrieved_at
                """
            ),
            {
                "cik": cik_padded or "",
                "accession_number": accession,
                "form_type": form_type,
                "filing_date": filing_date,
                "edgar_url": edgar_url,
                "capacity_mw": capacity_mw,
                "energy_source": energy_source,
                "buyer_raw": clean_buyer,
                "seller_raw": clean_seller,
                "rejected_buyer_raw": rejected_buyer_raw,
                "rejected_seller_raw": rejected_seller_raw,
                "buyer_canonical": buyer_canonical,
                "seller_canonical": seller_canonical,
                "buyer_company_id": buyer_company_id,
                "seller_company_id": seller_company_id,
                "methodology": methodology,
                "canonical_deal_id": canonical_deal_id,
                "flagged_capacity": flagged_capacity,
                "appearance_count": appearance_count,
                "is_power_related": is_power_related,
                "signing_date": signing_date,
                "deal_index": deal_index,
                "excerpt": stored_excerpt[:2000],
                "parser_version": PARSER_VERSION,
                "confidence": confidence,
                "retrieved_at": datetime.utcnow(),
                "created_at": datetime.utcnow(),
            },
        )
        return {
            "ok": True,
            "accession": accession,
            "buyer_canonical": buyer_canonical,
            "seller_canonical": seller_canonical,
            "capacity_mw": capacity_mw,
            "canonical_deal_id": canonical_deal_id,
            "flagged_capacity": flagged_capacity,
        }
    except Exception as exc:
        logger.error(
            "edgar_extractor.upsert_failed",
            extra={"accession": accession, "error": str(exc)},
        )
        return {"ok": False, "accession": accession, "error": str(exc)}


async def reprocess_one(session, row, *, known_company_names) -> dict:
    """Re-run the validation + canonicalization + dedup-id pipeline on an
    existing edgar_extractions row WITHOUT re-calling the LLM.

    Useful for the `edgar-reprocess` CLI: when we change the validator or
    canonicalizer logic we want to re-stamp every existing row through the
    new code without burning extraction tokens.

    `row` is expected to be an EdgarExtraction ORM instance (or any object
    with attribute access to the legacy column set).

    Returns a delta record:
        {accession, before:{...}, after:{...}, changed: bool}
    """
    accession = getattr(row, "accession_number", None) or "?"
    before = {
        "buyer_raw": getattr(row, "buyer_raw", None),
        "seller_raw": getattr(row, "seller_raw", None),
        "buyer_canonical": getattr(row, "buyer_canonical", None),
        "seller_canonical": getattr(row, "seller_canonical", None),
        "capacity_mw": getattr(row, "capacity_mw", None),
        "canonical_deal_id": getattr(row, "canonical_deal_id", None),
        "flagged_capacity": getattr(row, "flagged_capacity", False),
    }

    # Reconstruct an LLM-shaped result dict from the persisted columns.
    # Track C: preserve existing is_power_related (set by initial extraction
    # OR by the migration 012 backfill); preserve deal_index so re-runs don't
    # collapse multi-deal rows; pull signing_date from the row, not filing_date.
    synthesized_result = {
        "buyer": getattr(row, "buyer_raw", None),
        "seller": getattr(row, "seller_raw", None),
        "capacity_mw": getattr(row, "capacity_mw", None),
        "energy_source": getattr(row, "energy_source", None),
        "headline": getattr(row, "excerpt", None),
        "methodology": getattr(row, "methodology", None),
        "signing_date": (
            getattr(row, "signing_date", None).isoformat()
            if getattr(row, "signing_date", None) else None
        ),
        "is_power_related": bool(getattr(row, "is_power_related", False)),
        "_deal_index": int(getattr(row, "deal_index", 0)),
    }

    status = await _persist_extraction(
        session,
        accession=accession,
        cik_padded=getattr(row, "cik", "") or "",
        form_type=getattr(row, "form_type", "") or "",
        filing_date=getattr(row, "filing_date", None),
        edgar_url=getattr(row, "edgar_url", "") or "",
        result=synthesized_result,
        excerpt_fallback=getattr(row, "excerpt", "") or "",
        confidence=(
            float(row.confidence) if getattr(row, "confidence", None) is not None else None
        ),
        known_company_names=known_company_names,
    )
    after = {
        "buyer_canonical": status.get("buyer_canonical"),
        "seller_canonical": status.get("seller_canonical"),
        "capacity_mw": status.get("capacity_mw"),
        "canonical_deal_id": status.get("canonical_deal_id"),
        "flagged_capacity": status.get("flagged_capacity"),
    }
    changed = any(before.get(k) != after.get(k) for k in after.keys())
    return {
        "accession": accession,
        "before": before,
        "after": after,
        "changed": changed,
        "ok": bool(status.get("ok")),
    }


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

    # EDGAR-3: load canonical company names ONCE to feed the validator.
    known_company_names = await _load_known_company_names(session)

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
        status = await _persist_extraction(
            session,
            accession=accession,
            cik_padded=cik_padded or "",
            form_type="8-K",
            filing_date=filing_date,
            edgar_url=url,
            result=result,
            excerpt_fallback=excerpt,
            confidence=extraction.confidence,
            known_company_names=known_company_names,
        )
        if status.get("ok"):
            stored += 1
        else:
            errors += 1

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
        "methodology": None,
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
                 "energy_source", "buyer", "seller", "methodology"):
            if merged[k] is None and r.get(k):
                merged[k] = r[k]
    merged["relevance_reason"] = positive_reason or fallback_reason
    return merged


async def run_llm_extraction_quarterly(
    session,
    since: str = "2024-01-01",
    limit: int = 10,
    days_back: int | None = None,
) -> dict:
    """Fetch 10-K + 10-Q filings, run classify+extract per chunk, merge,
    and upsert one row per accession into edgar_extractions.

    `limit` bounds the number of distinct accessions processed (NOT chunks);
    a 10-K split into 12 chunks counts as 1 accession.

    `days_back` (Track C ride-along fix): allow callers to pass days-from-today
    instead of an absolute `since` date. Translated to `since` internally so
    downstream code is unchanged. The CLI passes this to align with the 8-K
    ingest flag.
    """
    if days_back is not None:
        from datetime import date as _date, timedelta as _td
        since = (_date.today() - _td(days=int(days_back))).isoformat()

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

    # EDGAR-3: load canonical company names ONCE for the validator allow-list.
    known_company_names = await _load_known_company_names(session)

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
        excerpt_fallback = chunks[0].get("excerpt") or ""

        status = await _persist_extraction(
            session,
            accession=accession,
            cik_padded=cik_padded or "",
            form_type=form_type,
            filing_date=filing_date,
            edgar_url=url,
            result=merged,
            excerpt_fallback=excerpt_fallback,
            confidence=0.85,
            known_company_names=known_company_names,
        )
        if status.get("ok"):
            stored += 1
        else:
            errors += 1

    await session.commit()
    return {
        "fetched": fetched,
        "accessions_selected": len(selected_urls),
        "stored": stored,
        "skipped": skipped,
        "classifier_rejected": classifier_rejected,
        "errors": errors,
    }
