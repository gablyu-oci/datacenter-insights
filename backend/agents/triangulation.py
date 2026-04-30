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

import json
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


# ---------------------------------------------------------------------------
# L2 (Compute Demand) modeling assumptions
# ---------------------------------------------------------------------------
# These are the dials of the model. Karan will push back on each;
# that's the point. Document any change in git blame.
H100_AVG_POWER_W      = 700      # H100 typical TDP (watts)
B200_AVG_POWER_W      = 1000     # B200 typical TDP (watts)
AVG_BLENDED_POWER_W   = 850      # 50/50 H100/B200 blended for 2025
AVG_GPU_PRICE_USD     = 35_000   # blended H100/B200 ASP (USD)
UTILIZATION_PCT       = 0.60     # AI workload utilization assumption
OVERHEAD_MULTIPLIER   = 1.4      # PUE + networking + cooling overhead

# Hyperscaler subset — the five companies we believe are the dominant
# H100/B200 buyers. Utilities (Constellation, Talen, Vistra) are
# excluded because they sell power, not consumers of compute.
HYPERSCALER_SUBSET = ["Microsoft", "Amazon", "Google", "Oracle", "Meta"]
# gw-summary stores Google rows under "Google" already; curated_deals
# uses both "Google" and "Google / Alphabet". We treat Alphabet as an
# alias of Google when bucketing for L2.
_HYPERSCALER_ALIASES: dict[str, str] = {
    "alphabet": "Google",
    "google / alphabet": "Google",
    "amazon / aws": "Amazon",
    "aws": "Amazon",
}


def _canon_hyperscaler(buyer: Optional[str]) -> Optional[str]:
    """Map a curated_deals buyer string to one of HYPERSCALER_SUBSET, or None.

    First strip composite buyers ("Amazon / Microsoft / Google" → first
    name only, since the deal is jointly attributed and we can't split MW
    further without source data). Then check direct match and aliases.
    """
    if not buyer:
        return None
    head = buyer.split(" / ")[0].split("/")[0].strip()
    head_low = head.lower()
    # Direct hyperscaler match
    for canon in HYPERSCALER_SUBSET:
        if canon.lower() == head_low:
            return canon
    # Alias match against the full buyer string (lowercase)
    full_low = buyer.strip().lower()
    for needle, canon in _HYPERSCALER_ALIASES.items():
        if needle in full_low:
            return canon
    return None


async def nvidia_data_center_latest(session) -> tuple[Optional[dict], Optional[str]]:
    """Pull the most recent NVIDIA Data Center segment row from
    edgar_extractions(pillar='vendor_supply', cik='0001045810').

    Returns (payload_dict, period_end_iso). payload_dict has keys
    period_end, revenue_usd, inventory_usd, etc. (decoded from the
    JSON-packed `excerpt` column the same way the GPU router does).
    Returns (None, None) if no qualifying row exists.
    """
    NVIDIA_CIK = "0001045810"
    try:
        rows = (await session.execute(
            text(
                """
                SELECT excerpt, filing_date
                FROM edgar_extractions
                WHERE pillar = 'vendor_supply'
                  AND cik = :cik
                  AND excerpt IS NOT NULL
                ORDER BY filing_date DESC NULLS LAST
                """
            ),
            {"cik": NVIDIA_CIK},
        )).all()
    except Exception as exc:
        logger.warning("triangulation_l2.nvidia_query_failed", extra={"error": str(exc)})
        return (None, None)

    candidates: list[tuple[Optional[str], Optional[str], dict]] = []
    for excerpt, filing_date in rows:
        try:
            payload = json.loads(excerpt) if excerpt else {}
        except (ValueError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            continue
        if (payload.get("segment_name") or "").strip().lower() != "data center":
            continue
        if payload.get("revenue_usd") in (None, 0):
            continue
        period_end = payload.get("period_end")
        filing_iso = filing_date.isoformat() if filing_date else None
        candidates.append((period_end, filing_iso, payload))

    if not candidates:
        return (None, None)

    # Sort: period_end DESC NULLS LAST, then filing_date DESC.
    candidates.sort(
        key=lambda t: (t[0] is not None, t[0] or "", t[1] or ""),
        reverse=True,
    )
    period_end, filing_iso, payload = candidates[0]
    effective_period = period_end or filing_iso
    return (payload, effective_period)


async def contracted_gw_map(session) -> dict[str, float]:
    """Return {hyperscaler_canonical: contracted_gw} for the L2 subset,
    sourced from curated_deals via the same SQL pattern as
    routers.power._gw_summary_from_db (sums capacity_mw, divides by 1000).

    Only keys in HYPERSCALER_SUBSET are returned. Composite buyers
    (e.g. "Amazon / Microsoft / Google") are attributed to the first
    listed buyer only — splitting MW across joint buyers is not
    supported without authoritative deal-allocation data.
    """
    try:
        rows = (await session.execute(
            text(
                """
                SELECT buyer, COALESCE(SUM(capacity_mw), 0) AS mw
                FROM curated_deals
                WHERE capacity_mw IS NOT NULL
                  AND capacity_mw > 0
                  AND buyer IS NOT NULL
                GROUP BY buyer
                """
            )
        )).all()
    except Exception as exc:
        logger.warning("triangulation_l2.curated_query_failed", extra={"error": str(exc)})
        return {}

    totals: dict[str, float] = {h: 0.0 for h in HYPERSCALER_SUBSET}
    for buyer, mw in rows:
        canon = _canon_hyperscaler(buyer)
        if canon is None:
            continue
        totals[canon] = totals.get(canon, 0.0) + float(mw or 0.0) / 1000.0

    # Strip zero entries so callers can detect "no data" vs "real zero".
    return {k: round(v, 2) for k, v in totals.items() if v > 0}


async def compute_l2(session) -> dict:
    """Compute L2 — compute-demand layer.

    Translates NVIDIA's most recent Data Center segment revenue into an
    inferred GPU-units count and an inferred deployable-compute GW
    estimate, then distributes that GW across the hyperscaler subset
    proportionally to their contracted_gw from curated_deals. The gap
    between contracted_gw and implied_compute_gw is the surfaced signal
    ("shipping ≠ deployment, the gap is the signal").

    Returns a dict shaped to fit a CoverageEnvelope.data field:
        {
          period_end, nvidia_dc_revenue_usd, nvidia_inventory_usd,
          inferred_units_total, inferred_compute_gw,
          assumptions: {...},
          per_hyperscaler_share: [{company, contracted_gw,
              implied_compute_gw, gap_gw, status, share_fraction}, ...]
        }

    On absence of NVIDIA data, returns the same shape with zeros and
    an empty per_hyperscaler_share list.
    """
    payload, period_end = await nvidia_data_center_latest(session)
    contracted_map = await contracted_gw_map(session)

    assumptions = {
        "avg_gpu_price_usd": AVG_GPU_PRICE_USD,
        "avg_blended_power_w": AVG_BLENDED_POWER_W,
        "utilization_pct": UTILIZATION_PCT,
        "overhead_multiplier": OVERHEAD_MULTIPLIER,
        "h100_avg_power_w": H100_AVG_POWER_W,
        "b200_avg_power_w": B200_AVG_POWER_W,
    }

    if payload is None or not payload.get("revenue_usd"):
        return {
            "period_end": period_end,
            "nvidia_dc_revenue_usd": None,
            "nvidia_inventory_usd": None,
            "inferred_units_total": 0,
            "inferred_compute_gw": 0.0,
            "assumptions": assumptions,
            "per_hyperscaler_share": [],
        }

    revenue_usd = int(payload["revenue_usd"])
    inventory_usd = payload.get("inventory_usd")
    inventory_usd_int = int(inventory_usd) if inventory_usd is not None else None

    inferred_units_total = int(revenue_usd / AVG_GPU_PRICE_USD)
    # Watts -> GW: divide by 1e9.
    inferred_compute_gw_raw = (
        inferred_units_total
        * AVG_BLENDED_POWER_W
        * UTILIZATION_PCT
        * OVERHEAD_MULTIPLIER
    ) / 1e9
    inferred_compute_gw = round(inferred_compute_gw_raw, 1)

    subset_total_gw = sum(contracted_map.get(h, 0.0) for h in HYPERSCALER_SUBSET)

    per_hyperscaler_share: list[dict] = []
    for company in HYPERSCALER_SUBSET:
        contracted_gw = round(contracted_map.get(company, 0.0), 2)
        if subset_total_gw > 0:
            share_fraction = contracted_gw / subset_total_gw
        else:
            share_fraction = 0.0
        # Distribute against the *rounded* headline so per-company
        # implied figures sum back to inferred_compute_gw exactly to
        # within float precision (test_math_basic asserts < 0.01).
        implied_compute_gw = round(inferred_compute_gw * share_fraction, 4)
        gap_gw = round(contracted_gw - implied_compute_gw, 2)
        status = "overcontracted" if gap_gw > 0 else "undercontracted"
        per_hyperscaler_share.append({
            "company": company,
            "contracted_gw": contracted_gw,
            "implied_compute_gw": implied_compute_gw,
            "gap_gw": gap_gw,
            "status": status,
            "share_fraction": round(share_fraction, 4),
        })

    return {
        "period_end": period_end,
        "nvidia_dc_revenue_usd": revenue_usd,
        "nvidia_inventory_usd": inventory_usd_int,
        "inferred_units_total": inferred_units_total,
        "inferred_compute_gw": inferred_compute_gw,
        "assumptions": assumptions,
        "per_hyperscaler_share": per_hyperscaler_share,
    }
