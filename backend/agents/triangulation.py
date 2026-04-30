"""
Triangulation engine — Layer 1 (contracted power, GW per company × geo).

Phase 2 implementation. L1 is the only layer we can compute today; L2-L4
are gated on paid data:

    L1  Contracted Power     ✅ this module — sites + curated_deals + edgar
    L2  GPU Compute Demand   ❌ requires NVIDIA shipment data ($)
    L3  NIC/Optics Signals   ❌ requires Coherent/Lumentum order data ($)
    L4  Permit Ground Truth  ❌ requires Shovels.ai county permits ($)

L1 math:
    For each (company_canon, state_code) pair, sum disclosed
    contracted-power MW across three sources, then convert to GW:
      * sites.power_capacity_mw       (Aterio CSV; provider_name → company)
      * curated_deals.capacity_mw     (hand-verified; buyer → company)
      * edgar_extractions.capacity_mw (LLM-extracted; buyer_raw → company)

    Confidence rises with the number of corroborating sources.

Public entry point:
    async def compute_l1(session) -> list[dict]
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical company normalization
# ---------------------------------------------------------------------------

# Canonical names for the hyperscaler / utility set that the rest of the
# tool tracks. We collapse any string that contains one of these tokens
# (case-insensitive) into the canonical form so "Microsoft Corporation",
# "MSFT", "Microsoft Corp." all roll up to "Microsoft".
_CANON_TOKENS: list[tuple[str, str]] = [
    ("Microsoft", "microsoft"),
    ("Amazon", "amazon"),
    ("Amazon", "aws"),
    ("Alphabet", "alphabet"),
    ("Alphabet", "google"),
    ("Meta", "meta platforms"),
    ("Meta", " meta "),
    ("Meta", "facebook"),
    ("Oracle", "oracle"),
    ("Apple", "apple"),
    ("Constellation Energy", "constellation"),
    ("Talen Energy", "talen"),
    ("NuScale Power", "nuscale"),
    ("Oklo", "oklo"),
    ("Vistra Energy", "vistra"),
    ("NextEra Energy", "nextera"),
    ("AES Corporation", "aes corp"),
    ("AES Corporation", " aes "),
    ("Dominion Energy", "dominion"),
    ("Broadcom", "broadcom"),
    ("Coherent", "coherent"),
    ("Lumentum", "lumentum"),
    ("NVIDIA", "nvidia"),
    ("TSMC", "tsmc"),
    ("TSMC", "taiwan semiconductor"),
]

_SUFFIX_RE = re.compile(
    r"\b(inc\.?|corp\.?|corporation|company|co\.?|llc|ltd\.?|holdings?|"
    r"plc|n\.v\.|nv|sa|s\.a\.|gmbh|ag)\b\.?",
    re.IGNORECASE,
)


def canonicalize(name: Optional[str]) -> Optional[str]:
    """Return the canonical company form, or None for empty/garbage input."""
    if not name:
        return None
    s = " " + name.strip().lower() + " "
    # Token-match against the curated list (longest token first reduces
    # ambiguity, but our tokens are mostly distinct so iteration order is
    # acceptable).
    for canon, token in _CANON_TOKENS:
        if token in s:
            return canon
    # Fallback: strip suffixes, title-case the rest, return as-is.
    cleaned = _SUFFIX_RE.sub("", name).strip().rstrip(",").strip()
    return cleaned or None


# ---------------------------------------------------------------------------
# Pillar pulls
# ---------------------------------------------------------------------------

async def _pull_sites(session) -> list[tuple[str, str, float]]:
    """(company_raw, state_code, mw_total) from sites.power_capacity_mw."""
    rows = await session.execute(
        text(
            """
            SELECT provider_name, state_code, COALESCE(SUM(power_capacity_mw), 0) AS mw
            FROM sites
            WHERE power_capacity_mw IS NOT NULL
              AND power_capacity_mw > 0
              AND provider_name IS NOT NULL
              AND state_code IS NOT NULL
            GROUP BY provider_name, state_code
            """
        )
    )
    return [(r[0], r[1], float(r[2] or 0.0)) for r in rows]


async def _pull_curated(session) -> list[tuple[str, str, float]]:
    """(buyer, state, mw) from curated_deals.capacity_mw."""
    rows = await session.execute(
        text(
            """
            SELECT buyer, COALESCE(state, 'ALL') AS st,
                   COALESCE(SUM(capacity_mw), 0) AS mw
            FROM curated_deals
            WHERE capacity_mw IS NOT NULL
              AND capacity_mw > 0
              AND buyer IS NOT NULL
            GROUP BY buyer, state
            """
        )
    )
    return [(r[0], r[1] or "ALL", float(r[2] or 0.0)) for r in rows]


async def _pull_edgar(session) -> list[tuple[str, str, float]]:
    """(buyer_raw, 'ALL', mw) from edgar_extractions.

    edgar_extractions has no state column, so we bucket everything as 'ALL'
    until we wire entity resolution to the sites table.
    """
    rows = await session.execute(
        text(
            """
            SELECT buyer_raw, COALESCE(SUM(capacity_mw), 0) AS mw
            FROM edgar_extractions
            WHERE capacity_mw IS NOT NULL
              AND capacity_mw > 0
              AND buyer_raw IS NOT NULL
            GROUP BY buyer_raw
            """
        )
    )
    return [(r[0], "ALL", float(r[1] or 0.0)) for r in rows]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _aggregate(
    sites_rows: list[tuple[str, str, float]],
    curated_rows: list[tuple[str, str, float]],
    edgar_rows: list[tuple[str, str, float]],
) -> dict[tuple[str, str], dict]:
    """Group all 3 pillars into a {(company, state): bucket} dict."""
    buckets: dict[tuple[str, str], dict] = {}

    def _bucket(company: str, state: str) -> dict:
        canon = canonicalize(company) or "Unknown"
        key = (canon, state.upper() if state else "ALL")
        if key not in buckets:
            buckets[key] = {
                "sites_mw": 0.0,
                "sites_count": 0,
                "deals_mw": 0.0,
                "deals_count": 0,
                "edgar_mw": 0.0,
                "edgar_count": 0,
            }
        return buckets[key]

    for company, state, mw in sites_rows:
        b = _bucket(company, state)
        b["sites_mw"] += mw
        b["sites_count"] += 1
    for company, state, mw in curated_rows:
        b = _bucket(company, state)
        b["deals_mw"] += mw
        b["deals_count"] += 1
    for company, state, mw in edgar_rows:
        b = _bucket(company, state)
        b["edgar_mw"] += mw
        b["edgar_count"] += 1

    return buckets


def _compute_confidence(b: dict) -> float:
    """Confidence rises with corroboration: 0.50 base, +0.15 if ≥2 sources,
    +0.10 if ≥3 sources. Caps at 0.85.
    """
    contributing = sum(
        1 for k in ("sites_mw", "deals_mw", "edgar_mw") if b[k] > 0
    )
    score = 0.50
    if contributing >= 2:
        score += 0.15
    if contributing >= 3:
        score += 0.10
    return round(min(score, 0.85), 2)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def compute_l1(session) -> list[dict]:
    """Compute L1 contracted-power totals.

    Returns a list of records, sorted by gw_total descending:
        [{"company": "Microsoft",
          "state": "VA",
          "gw_total": 1.23,
          "sources": [{"type": "sites", "count": 12, "mw": 800.0},
                      {"type": "deals", "count": 1,  "mw": 430.0}],
          "confidence": 0.65}, ...]
    """
    try:
        sites_rows = await _pull_sites(session)
    except Exception as exc:
        logger.warning("triangulation.sites_query_failed", extra={"error": str(exc)})
        sites_rows = []
    try:
        curated_rows = await _pull_curated(session)
    except Exception as exc:
        logger.warning("triangulation.curated_query_failed", extra={"error": str(exc)})
        curated_rows = []
    try:
        edgar_rows = await _pull_edgar(session)
    except Exception as exc:
        logger.warning("triangulation.edgar_query_failed", extra={"error": str(exc)})
        edgar_rows = []

    buckets = _aggregate(sites_rows, curated_rows, edgar_rows)

    records: list[dict] = []
    for (company, state), b in buckets.items():
        total_mw = b["sites_mw"] + b["deals_mw"] + b["edgar_mw"]
        if total_mw <= 0:
            continue
        sources = []
        if b["sites_mw"] > 0:
            sources.append({"type": "sites", "count": b["sites_count"], "mw": round(b["sites_mw"], 1)})
        if b["deals_mw"] > 0:
            sources.append({"type": "deals", "count": b["deals_count"], "mw": round(b["deals_mw"], 1)})
        if b["edgar_mw"] > 0:
            sources.append({"type": "edgar", "count": b["edgar_count"], "mw": round(b["edgar_mw"], 1)})
        records.append({
            "company": company,
            "state": state,
            "gw_total": round(total_mw / 1000.0, 2),
            "sources": sources,
            "confidence": _compute_confidence(b),
        })

    records.sort(key=lambda r: r["gw_total"], reverse=True)
    return records
