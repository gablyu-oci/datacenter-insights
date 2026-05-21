"""
Power capacity, timeseries, announcements, and GW-summary endpoints.
Prefix: /api/power

When MOCK_DATA=0, queries the sites table for real power capacity data.
When MOCK_DATA=1, returns mock data from data/mock_data.py.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from db.models import EdgarExtraction, Site
from schemas.common import CoverageEnvelope, CoverageMeta, LineageEnvelope, LineageMeta

MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"

router = APIRouter(prefix="/api/power", tags=["power"])

_MOCK_DISABLED_NOTE = "Mock data disabled. Set MOCK_DATA=1 to enable."


def _colors() -> dict:
    if MOCK_ENABLED:
        from data.mock_data import COLORS
        return COLORS
    return {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/capacity")
async def power_capacity(db: AsyncSession = Depends(get_db)):
    if MOCK_ENABLED:
        from data.mock_data import get_power_data, COLORS

        return LineageEnvelope(
            data={"data": get_power_data(), "colors": COLORS},
            lineage=LineageMeta(
                source_url="mock",
                retrieved_at=datetime.utcnow(),
                parser_version="mock-v1",
                confidence=0.5,
            ),
        )

    # Real DB: aggregate power_capacity_mw by provider_name
    stmt = (
        select(
            Site.provider_name,
            func.count(Site.id).label("site_count"),
            func.coalesce(func.sum(Site.power_capacity_mw), 0).label("total_mw"),
            func.coalesce(func.avg(Site.power_capacity_mw), 0).label("avg_mw"),
            func.coalesce(func.max(Site.power_capacity_mw), 0).label("max_mw"),
        )
        .where(Site.provider_name.isnot(None))
        .group_by(Site.provider_name)
        .order_by(func.sum(Site.power_capacity_mw).desc().nullslast())
    )
    result = await db.execute(stmt)
    rows = result.fetchall()

    data = []
    for provider_name, site_count, total_mw, avg_mw, max_mw in rows:
        data.append(
            {
                "provider": provider_name,
                "site_count": site_count,
                "total_mw": float(total_mw),
                "avg_mw": round(float(avg_mw), 2),
                "max_mw": float(max_mw),
            }
        )

    return CoverageEnvelope(
        data={"data": data, "colors": {}},
        lineage=LineageMeta(
            source_url="sites",
            retrieved_at=datetime.utcnow(),
            parser_version="power-v1.0.0",
            confidence=0.85,
        ),
        coverage=CoverageMeta(pillar="power_capacity"),
    )


@router.get("/timeseries")
async def power_timeseries(db: AsyncSession = Depends(get_db)):
    if MOCK_ENABLED:
        from data.mock_data import get_power_timeseries, COLORS

        return LineageEnvelope(
            data={"data": get_power_timeseries(), "colors": COLORS},
            lineage=LineageMeta(
                source_url="mock",
                retrieved_at=datetime.utcnow(),
                parser_version="mock-v1",
                confidence=0.5,
            ),
        )

    # Real DB: aggregate power_capacity_mw by stage for a rough timeseries proxy
    # Group by provider and stage to show pipeline progression
    stmt = (
        select(
            Site.provider_name,
            Site.stage,
            func.count(Site.id).label("site_count"),
            func.coalesce(func.sum(Site.power_capacity_mw), 0).label("total_mw"),
        )
        .where(Site.provider_name.isnot(None))
        .group_by(Site.provider_name, Site.stage)
        .order_by(Site.provider_name, Site.stage)
    )
    result = await db.execute(stmt)
    rows = result.fetchall()

    # Organize by provider
    timeseries: dict = {}
    for provider_name, stage, site_count, total_mw in rows:
        if provider_name not in timeseries:
            timeseries[provider_name] = {}
        timeseries[provider_name][stage or "unknown"] = {
            "site_count": site_count,
            "total_mw": float(total_mw),
        }

    return CoverageEnvelope(
        data={"data": timeseries, "colors": {}},
        lineage=LineageMeta(
            source_url="sites",
            retrieved_at=datetime.utcnow(),
            parser_version="power-v1.0.0",
            confidence=0.85,
        ),
        coverage=CoverageMeta(pillar="power_timeseries"),
    )


# Canonical buyer rollups for the gw-summary aggregate. A buyer string in
# the source row may be "Microsoft", "Amazon / AWS", "Google / Alphabet" etc;
# we collapse to the parent brand for the dashboard tile.
_BUYER_CANONICALS = ("Microsoft", "Amazon", "Google", "Meta", "Oracle")

# Substring → canonical rollup. Aterio still uses the legacy "Facebook"
# string for Meta-owned campuses; some EDGAR filings reference "Alphabet"
# rather than Google; AWS is the Amazon subsidiary that signs PPAs.
# Frontend `canon()` in PowerTab.tsx mirrors this map — keep them in sync.
_BUYER_ALIASES: dict[str, str] = {
    "facebook": "Meta",
    "alphabet": "Google",
    "aws": "Amazon",
}


def _canonicalize_buyer(buyer: str | None) -> str:
    if not buyer:
        return "Unknown"
    head = buyer.split(" / ")[0].split("/")[0].strip()
    head_lower = head.lower()
    for alias, canon in _BUYER_ALIASES.items():
        if alias in head_lower:
            return canon
    for canon in _BUYER_CANONICALS:
        if canon.lower() in head_lower:
            return canon
    return head


# NOTE: curated_deals table was dropped in migration
# 016_drop_curated_deals (2026-05-07). The `curated` array in the
# response is now sourced from `power_projects` (Aterio) — clean,
# structured rows for hyperscaler customers. SEC EDGAR rows feed the
# `edgar` array as a quality-gated fallback for buckets Aterio doesn't
# cover.


# ---------------------------------------------------------------------------
# Quality gate + bucket key (pure functions for unit testing)
# ---------------------------------------------------------------------------
#
# The SEC EDGAR auto-extraction pipeline produces a long tail of malformed
# rows (raw 10-K boilerplate, JSON blobs, generic "the Venture" buyers, etc).
# These predicates filter that noise out at read time so the dashboard only
# surfaces actionable announcements.

# Headline prefixes that indicate raw filing boilerplate slipped through
# the extractor. Compared case-insensitively after stripping leading
# whitespace. The spec mandates the first 5; the trailing entries cover
# real-world variants observed in the EDGAR feed (e.g. an extractor that
# kept the filing form-type as a leading token: "8-K UNITED STATES …").
_BOILERPLATE_PREFIXES: tuple[str, ...] = (
    "UNITED STATES SECURITIES",
    "FORM 10-",
    "20549 FORM",
    "WASHINGTON, D.C.",
    "SECURITIES AND EXCHANGE COMMISSION",
    "8-K UNITED STATES",
    "8-K WASHINGTON",
    "10-K UNITED STATES",
    "10-Q UNITED STATES",
)

# Substring (anywhere in headline) tokens that practically only appear in
# raw filing boilerplate. We accept a small false-positive risk here in
# exchange for cleaner output, but only on top of the prefix check above.
_BOILERPLATE_SUBSTRINGS: tuple[str, ...] = (
    "PURSUANT TO SECTION 13 OR 15(D)",
    "QUARTERLY REPORT PURSUANT TO SECTION",
    "TABLE OF CONTENTS",
)

# Buyer values that are obvious extractor noise rather than real
# counterparties. The LLM occasionally emits these as buyers when it
# can't disambiguate the filing's "the Company" antecedent.
_NOISE_BUYERS: frozenset[str] = frozenset(
    {
        "trusted foundry",
        "the venture",
        "company",
        "the company",
        "the issuer",
        "registrant",
    }
)


def passes_quality_gate(row: dict[str, Any]) -> tuple[bool, str | None]:
    """Return (ok, reason) for an EDGAR-derived deal dict.

    A row PASSES (returns ``(True, None)``) only if all of the following
    hold:

    * Headline is present, between 20 and 300 chars after stripping.
    * Headline does not start with SEC filing boilerplate
      (`UNITED STATES SECURITIES`, `FORM 10-`, `20549 FORM`,
      `WASHINGTON, D.C.`, `SECURITIES AND EXCHANGE COMMISSION`).
    * Headline does not look like a JSON blob (starts with `{` or `[`).
    * Buyer is non-empty and not in the noise set
      ({Trusted Foundry, the Venture, Company, the Company,
      the Issuer, Registrant}).
    * Has at least ONE of: capacity_mw > 0, energy_source non-empty,
      source_url non-empty.

    On rejection, ``reason`` is a short tag that the caller can
    aggregate for diagnostics (e.g. "boilerplate", "json_shaped",
    "noise_buyer", "no_signal", "headline_length", "no_buyer").
    """
    headline_raw = row.get("headline")
    headline = (headline_raw or "").lstrip()

    if not headline:
        return False, "no_headline"
    if len(headline) < 20 or len(headline) > 300:
        return False, "headline_length"
    if headline[:1] in ("{", "["):
        return False, "json_shaped"
    head_upper = headline.upper()
    for prefix in _BOILERPLATE_PREFIXES:
        if head_upper.startswith(prefix):
            return False, "boilerplate"
    for token in _BOILERPLATE_SUBSTRINGS:
        if token in head_upper:
            return False, "boilerplate"

    buyer = (row.get("buyer") or "").strip()
    if not buyer:
        return False, "no_buyer"
    if buyer.lower() in _NOISE_BUYERS:
        return False, "noise_buyer"

    capacity_mw = row.get("capacity_mw")
    energy_source = (row.get("energy_source") or "").strip()
    source_url = (row.get("source_url") or "").strip()
    has_mw = capacity_mw is not None and capacity_mw > 0
    has_source = bool(energy_source) or bool(source_url)
    if not (has_mw or has_source):
        return False, "no_signal"

    return True, None


# Map an energy_source string to a coarse bucket so Aterio's
# "Natural Gas" and SEC's "natural_gas" collapse together.
def _normalize_energy(value: str | None) -> str:
    if not value:
        return ""
    v = value.lower().strip()
    if "nuclear" in v or "smr" in v:
        return "nuclear"
    if "solar" in v:
        return "solar"
    if "wind" in v:
        return "wind"
    if "storage" in v or "battery" in v or "bess" in v:
        return "storage"
    if "gas" in v:
        return "gas"
    if "coal" in v:
        return "coal"
    if "renewable" in v:
        return "renewable"
    if "mixed" in v:
        return "mixed"
    return v[:24]


# Strip common corporate suffixes so "Meta Platforms, Inc." and "Meta"
# bucket together.
_BUYER_SUFFIX_RE = re.compile(
    r",?\s*\b(inc|corp|corporation|co|llc|ltd|holdings?|platforms|energy|technologies?)\b\.?",
    flags=re.IGNORECASE,
)


def _normalize_buyer(buyer: str | None) -> str:
    if not buyer:
        return ""
    head = buyer.split(" / ")[0].split("/")[0]
    head = _BUYER_SUFFIX_RE.sub("", head)
    return re.sub(r"\s+", " ", head).strip().lower()


def _quarter_of(value: str | date | datetime | None) -> str:
    """Return YYYY-Q? for a date / datetime / ISO string. Empty when unknown."""
    if value is None:
        return ""
    if isinstance(value, str):
        if len(value) < 7:
            return ""
        try:
            year = int(value[0:4])
            month = int(value[5:7])
        except ValueError:
            return ""
    else:
        year = value.year
        month = value.month
    quarter = (month - 1) // 3 + 1
    return f"{year}-Q{quarter}"


def bucket_key(row: dict[str, Any]) -> tuple[str, str, str]:
    """(buyer_normalized, year-quarter, deal_type/energy_source) tuple.

    Used to dedupe: a SEC row whose bucket key matches an Aterio row is
    considered "already covered" and dropped from the edgar array. The
    bucket is intentionally coarse (calendar quarter, normalised buyer,
    coarse energy bucket) so minor LLM phrasing differences don't split
    a single deal into multiple buckets.
    """
    buyer_n = _normalize_buyer(row.get("buyer"))
    qtr = _quarter_of(row.get("announced_date"))
    energy_n = _normalize_energy(row.get("energy_source"))
    return (buyer_n, qtr, energy_n)


def _edgar_row_to_dict(e: EdgarExtraction) -> dict:
    """Surface an EdgarExtraction ORM row in the same dict shape.

    Prefers buyer_canonical / seller_canonical when present (entity-
    resolved or validated raw value); falls back to the raw column.
    Surfaces `flagged_capacity`, `methodology`, `canonical_deal_id`,
    `appearance_count`, and `last_extracted` for the FE drill modal.
    """
    buyer = getattr(e, "buyer_canonical", None) or e.buyer_raw
    seller = getattr(e, "seller_canonical", None) or e.seller_raw
    return {
        "id": f"edgar-{e.id}",
        "buyer": buyer,
        "seller": seller,
        "deal_type": "8-K disclosure",
        "energy_source": e.energy_source,
        "capacity_mw": int(e.capacity_mw) if e.capacity_mw is not None else None,
        "announced_date": e.filing_date.isoformat() if e.filing_date else None,
        "headline": e.excerpt[:160] if e.excerpt else None,
        "excerpt": e.excerpt,
        "source_type": e.form_type,
        "source_url": e.edgar_url,
        "edgar_url": e.edgar_url,
        "confidence": float(e.confidence) if e.confidence is not None else None,
        "data_source": f"SEC EDGAR ({e.form_type})",
        "source": "live",
        "flagged_capacity": bool(getattr(e, "flagged_capacity", False)),
        "methodology": getattr(e, "methodology", None),
        "canonical_deal_id": getattr(e, "canonical_deal_id", None),
        "appearance_count": getattr(e, "appearance_count", 1),
        "last_extracted": e.retrieved_at.isoformat() if e.retrieved_at else None,
        # Track C fields
        "is_power_related": bool(getattr(e, "is_power_related", False)),
        "signing_date": e.signing_date.isoformat() if getattr(e, "signing_date", None) else None,
        "deal_index": int(getattr(e, "deal_index", 0)),
    }


_HYPERSCALER_REGEX = (
    r"(Microsoft|Amazon|AWS|Google|Alphabet|Meta|Facebook|Oracle|"
    r"xAI|Apple|Anthropic|OpenAI|Crusoe|CoreWeave|Lambda|Applied Digital|"
    r"TeraWulf|EdgeConneX|Vantage|Digital Realty|QTS|CyrusOne|STACK|"
    r"Equinix|NTT|Compass|Aligned|DataBank)"
)


async def _fetch_aterio_curated(
    db: AsyncSession, company_filter: str | None
) -> list[dict]:
    """Pull AI/datacenter-relevant rows from `power_projects` (Aterio).

    Aterio is the structured, hand-curated power-project inventory. Rows
    that name a hyperscaler/AI lab/colo as `customer_companies` are the
    canonical source for the "curated" array on the announcements feed.
    Each row maps to the same dict shape as edgar rows so the frontend
    treats them identically.
    """
    where_company = ""
    params: dict[str, Any] = {"hyper_re": _HYPERSCALER_REGEX}
    if company_filter and company_filter != "All":
        # Match either the customer_companies free-text column or the
        # plant/project name in case the customer field is blank.
        where_company = (
            " AND (customer_companies ILIKE :company "
            "      OR project_name ILIKE :company "
            "      OR plant_name ILIKE :company)"
        )
        params["company"] = f"%{company_filter}%"

    sql = text(
        f"""
        SELECT
            aterio_phase_uid,
            customer_companies,
            developer_companies,
            project_name,
            plant_name,
            tot_phase_nameplate_power_mw,
            tot_contracted_power_capacity_mw,
            aterio_plant_energy_source,
            plant_phase_announced_date,
            plant_phase_filing_date,
            plant_phase_stage,
            project_source_url,
            plant_source_url,
            agreement_url,
            agreement_type,
            state_code,
            city_name,
            county_name
        FROM power_projects
        WHERE customer_companies ~* :hyper_re
          {where_company}
        ORDER BY plant_phase_announced_date DESC NULLS LAST
        LIMIT 100
        """
    )
    result = await db.execute(sql, params)
    rows: list[dict] = []
    for r in result.mappings().all():
        # First customer is treated as the buyer; full list is preserved
        # in the seller column so the drill-down can show the chain.
        customers = (r["customer_companies"] or "").strip()
        buyer = customers.split(",")[0].strip() if customers else None
        announced = r["plant_phase_announced_date"] or r["plant_phase_filing_date"]
        capacity_mw = (
            r["tot_phase_nameplate_power_mw"]
            or r["tot_contracted_power_capacity_mw"]
        )
        location_parts = [
            p for p in (r["city_name"], r["county_name"], r["state_code"]) if p
        ]
        headline_bits = [b for b in (r["project_name"], r["plant_name"]) if b]
        headline = " — ".join(headline_bits) if headline_bits else None
        source_url = (
            r["project_source_url"]
            or r["plant_source_url"]
            or r["agreement_url"]
            or ""
        )
        rows.append(
            {
                "id": f"aterio-{r['aterio_phase_uid']}",
                "buyer": buyer,
                "seller": (r["developer_companies"] or "").strip() or None,
                "deal_type": r["agreement_type"] or "Power project (Aterio)",
                "energy_source": r["aterio_plant_energy_source"],
                "capacity_mw": (
                    int(capacity_mw) if capacity_mw is not None else None
                ),
                "location": ", ".join(location_parts) or None,
                "state": r["state_code"],
                "announced_date": (
                    announced.isoformat() if announced else None
                ),
                "status": r["plant_phase_stage"],
                "headline": headline,
                "excerpt": (
                    f"{headline or ''} ({customers})" if customers else headline
                ),
                "source_type": "Aterio",
                "source_url": source_url,
                "edgar_url": None,
                "confidence": 0.95,
                "data_source": "Aterio Energy Project Inventory",
                "source": "live",
                "is_power_related": True,
                "appearance_count": 1,
                # Track C compatibility fields — Aterio rows aren't deal_index
                # aware but the FE expects these keys to be present.
                "signing_date": None,
                "deal_index": 0,
                "flagged_capacity": False,
                "methodology": "Aterio structured inventory",
                "canonical_deal_id": None,
            }
        )
    return rows


@router.get("/announcements")
async def power_announcements(
    company: str = Query(default="All"),
    include_edgar: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
):
    """Power contract announcements: Aterio (primary) + quality-gated SEC EDGAR.

    Merge strategy:
      * Aterio rows from `power_projects` (filtered to hyperscaler/AI-lab
        customers) are the canonical "curated" feed — clean, structured,
        hand-validated.
      * SEC EDGAR rows from `edgar_extractions` are run through
        :func:`passes_quality_gate` to drop boilerplate / JSON-shaped /
        noise-buyer / no-signal extractions.
      * For each surviving SEC row we compute :func:`bucket_key`
        ``(buyer_norm, year-quarter, energy_norm)``. SEC rows whose bucket
        already appears in the Aterio set are dropped (Aterio wins).
      * Both arrays share the same dict shape so the frontend renders
        them with the same `DealRow` component.

    Response shape (preserved for FE compatibility):
        ``{"curated": [...aterio rows...], "edgar": [...gated SEC rows...],
           "gw_summary": {...}, "total_deals": N,
           "last_updated": iso, "data_sources": [...]}``
    """
    # ------------------------------------------------------------------
    # 1. Aterio (primary, structured)
    # ------------------------------------------------------------------
    curated: list[dict] = await _fetch_aterio_curated(db, company)

    # Build the set of bucket keys covered by Aterio. SEC rows landing in
    # the same bucket are dropped to avoid double-counting a deal that
    # already exists in the curated inventory.
    aterio_buckets: set[tuple[str, str, str]] = {
        bucket_key(r) for r in curated
    }

    # ------------------------------------------------------------------
    # 2. SEC EDGAR (quality-gated fallback)
    # ------------------------------------------------------------------
    edgar_deals: list[dict] = []
    if include_edgar:
        ee_stmt = select(EdgarExtraction).where(
            EdgarExtraction.is_power_related.is_(True)
        )
        if company and company != "All":
            ee_stmt = ee_stmt.where(
                (EdgarExtraction.buyer_raw.ilike(f"%{company}%"))
                | (EdgarExtraction.seller_raw.ilike(f"%{company}%"))
                | (EdgarExtraction.buyer_canonical.ilike(f"%{company}%"))
            )
        ee_stmt = ee_stmt.order_by(
            EdgarExtraction.filing_date.desc().nullslast()
        ).limit(500)
        edgar_rows = (await db.execute(ee_stmt)).scalars().all()

        for e in edgar_rows:
            row = _edgar_row_to_dict(e)
            ok, _reason = passes_quality_gate(row)
            if not ok:
                continue
            # Dedup against Aterio: skip if the (buyer, quarter, energy)
            # bucket is already covered.
            if bucket_key(row) in aterio_buckets:
                continue
            edgar_deals.append(row)

    # ------------------------------------------------------------------
    # 3. Per-buyer GW summary (unchanged)
    # ------------------------------------------------------------------
    gw_summary = await _gw_summary_from_db(db)

    # Latest update timestamp: prefer most-recent edgar write; if no
    # edgar rows survived (or include_edgar is False), fall back to
    # today since Aterio is a snapshot import.
    latest_edgar = (
        await db.execute(select(func.max(EdgarExtraction.retrieved_at)))
    ).scalar_one_or_none()
    last_updated = (
        latest_edgar.date().isoformat()
        if latest_edgar
        else datetime.utcnow().date().isoformat()
    )

    data_sources: list[str] = []
    if curated:
        data_sources.append("Aterio Energy Project Inventory")
    if include_edgar and edgar_deals:
        data_sources.append("SEC EDGAR (live LLM extraction, quality-gated)")

    payload = {
        "curated": curated,
        "edgar": edgar_deals,
        "gw_summary": gw_summary,
        "total_deals": len(curated) + len(edgar_deals),
        "last_updated": last_updated,
        "data_sources": data_sources,
    }
    return LineageEnvelope(
        data=payload,
        lineage=LineageMeta(
            source_url="db://power_projects+edgar_extractions",
            retrieved_at=datetime.utcnow(),
            parser_version="power-v2.0.0",
            confidence=0.95,
        ),
    )


async def _gw_summary_from_db(db: AsyncSession) -> dict:
    """Aggregate contracted GW per canonical hyperscaler/AI buyer.

    Unions two sources, with Python-side canonicalization so aliases fold
    correctly:
      * `edgar_extractions` (LLM-extracted SEC filings) — DISTINCT ON
        (canonical_deal_id) latest filing_date so a deal seen in 8-K + 10-Q
        + 10-K counts once. Rows with NULL canonical_deal_id are individual
        ungrouped observations.
      * `power_projects` (Aterio inventory) — rows whose
        `customer_companies` matches a recognized hyperscaler/AI buyer.
        Aterio still uses "Facebook" for Meta campuses; the alias map in
        `_canonicalize_buyer` rolls those into "Meta".

    Both sources are filtered to recognized buyers (`_HYPERSCALER_REGEX`)
    to drop utility/IPP filer noise — e.g. an LLM that extracted
    "Constellation Energy" as buyer from a Calpine acquisition filing.
    Capacity-NULL rows contribute zero to the GW total.
    """
    edgar_sql = text(
        """
        WITH latest AS (
            SELECT DISTINCT ON (canonical_deal_id)
                   canonical_deal_id,
                   COALESCE(buyer_canonical, buyer_raw) AS buyer,
                   energy_source,
                   capacity_mw,
                   filing_date
            FROM edgar_extractions
            WHERE canonical_deal_id IS NOT NULL
              AND capacity_mw IS NOT NULL
              AND COALESCE(buyer_canonical, buyer_raw) ~* :hyper_re
            ORDER BY canonical_deal_id, filing_date DESC NULLS LAST
        ),
        ungrouped AS (
            SELECT NULL::text AS canonical_deal_id,
                   COALESCE(buyer_canonical, buyer_raw) AS buyer,
                   energy_source,
                   capacity_mw,
                   filing_date
            FROM edgar_extractions
            WHERE canonical_deal_id IS NULL
              AND capacity_mw IS NOT NULL
              AND COALESCE(buyer_canonical, buyer_raw) ~* :hyper_re
        )
        SELECT buyer, energy_source, capacity_mw FROM latest
        UNION ALL
        SELECT buyer, energy_source, capacity_mw FROM ungrouped
        """
    )
    aterio_sql = text(
        """
        SELECT
            customer_companies AS buyer,
            aterio_plant_energy_source AS energy_source,
            COALESCE(tot_phase_nameplate_power_mw,
                     tot_contracted_power_capacity_mw) AS capacity_mw
        FROM power_projects
        WHERE customer_companies ~* :hyper_re
          AND COALESCE(tot_phase_nameplate_power_mw,
                       tot_contracted_power_capacity_mw) IS NOT NULL
        """
    )
    try:
        edgar_rows = (
            await db.execute(edgar_sql, {"hyper_re": _HYPERSCALER_REGEX})
        ).all()
        aterio_rows = (
            await db.execute(aterio_sql, {"hyper_re": _HYPERSCALER_REGEX})
        ).all()
    except Exception:
        # Fallback path — schema may not yet have buyer_canonical /
        # canonical_deal_id (pre-migration environment). Use a simpler
        # raw-buyer aggregate so /api/power/gw-summary keeps responding
        # rather than 500-ing.
        legacy = (
            await db.execute(
                select(
                    EdgarExtraction.buyer_raw,
                    EdgarExtraction.energy_source,
                    EdgarExtraction.capacity_mw,
                ).where(EdgarExtraction.capacity_mw.isnot(None))
            )
        ).all()
        edgar_rows = legacy
        aterio_rows = []

    totals: dict[str, dict] = {}
    # Aterio's customer_companies can be comma-separated ("Facebook, Foo").
    # Take the first listed customer — matches `_fetch_aterio_curated`.
    for buyer, energy_source, mw in list(edgar_rows) + [
        ((b or "").split(",")[0].strip() if b else b, es, mw)
        for (b, es, mw) in aterio_rows
    ]:
        canon = _canonicalize_buyer(buyer)
        if canon in ("Unknown", ""):
            continue
        bucket = totals.setdefault(
            canon,
            {
                "gw_total": 0.0,
                "deals": 0,
                "nuclear_gw": 0.0,
                "renewable_gw": 0.0,
                "gas_gw": 0.0,
                "storage_gw": 0.0,
                "other_gw": 0.0,
            },
        )
        gw = float(mw or 0) / 1000.0
        bucket["gw_total"] += gw
        bucket["deals"] += 1
        src = (energy_source or "").lower()
        if "nuclear" in src:
            bucket["nuclear_gw"] += gw
        elif any(r in src for r in ("solar", "wind", "hydro", "geothermal", "renewable")):
            bucket["renewable_gw"] += gw
        elif any(r in src for r in ("natural gas", "natural_gas", "gas")):
            bucket["gas_gw"] += gw
        elif any(r in src for r in ("storage", "battery")):
            bucket["storage_gw"] += gw
        else:
            bucket["other_gw"] += gw
    for k in totals:
        for f in ("gw_total", "nuclear_gw", "renewable_gw", "gas_gw", "storage_gw", "other_gw"):
            totals[k][f] = round(totals[k][f], 2)
    return totals


@router.get("/gw-summary")
async def gw_summary(db: AsyncSession = Depends(get_db)):
    gw = await _gw_summary_from_db(db)
    colors = _colors()
    return LineageEnvelope(
        data={"data": gw, "colors": colors},
        lineage=LineageMeta(
            source_url="db://edgar_extractions",
            retrieved_at=datetime.utcnow(),
            parser_version="db-v1.0.0",
            confidence=0.95,
        ),
    )
