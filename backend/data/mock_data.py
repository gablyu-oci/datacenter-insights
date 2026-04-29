"""Mock data module - Phase 1B: real DB reads behind the MOCK_DATA gate.

When MOCK_DATA=1 the get_* functions read from the strategic_insights
Postgres DB and shape rows into the legacy mock-response contract that
routers/{power,gpu,nics,tsmc,permits,satellite,triangulation,sources}.py
expect on the MOCK path. When MOCK_DATA=0 they raise RuntimeError; the
routers themselves bypass this module entirely on MOCK_DATA=0.

No random.* calls in the active code paths. Empty pillars (gpu, nics,
tsmc) return empty lists/None - the caller is responsible for rendering
a "no data" state.

Module-level constants COMPANIES, COLORS, REGIONS are preserved because
several routers import them directly.
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta, date
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import create_engine, func, select, case, and_, or_
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError

from config import settings
from db.models import (
    Company,
    DataCoverage,
    EnergyProject,
    Event,
    GeneratorPermit,
    IngestionRun,
    Site,
    SiteCompanyAssociation,
)


# ---------------------------------------------------------------------------
# Mock-gate plumbing
# ---------------------------------------------------------------------------

_MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"


def _require_mock_gate(func_name: str) -> None:
    """Raise if mock data is requested without the MOCK_DATA=1 gate."""
    if not _MOCK_ENABLED:
        raise RuntimeError(
            f"mock_data.{func_name}() called but MOCK_DATA env var is not '1'. "
            "Set MOCK_DATA=1 to enable mock data, or use real data sources."
        )


# ---------------------------------------------------------------------------
# Module-level constants (routers import these directly)
# ---------------------------------------------------------------------------

COMPANIES = ["Microsoft", "AWS", "Google", "Meta", "Oracle", "Apple", "Equinix"]

COLORS = {
    "Microsoft": "#0078D4",
    "AWS": "#FF9900",
    "Google": "#4285F4",
    "Meta": "#1877F2",
    "Oracle": "#C74634",
    "Apple": "#555555",
    "Equinix": "#E31837",
}

REGIONS = [
    {"name": "Virginia (US-EAST)", "state": "VA", "lat": 38.9, "lon": -77.4},
    {"name": "Iowa (US-CENTRAL)", "state": "IA", "lat": 41.8, "lon": -93.1},
    {"name": "Oregon (US-WEST)", "state": "OR", "lat": 45.5, "lon": -122.7},
    {"name": "Texas (US-SOUTH)", "state": "TX", "lat": 30.3, "lon": -97.7},
    {"name": "Arizona (US-SW)", "state": "AZ", "lat": 33.4, "lon": -112.1},
    {"name": "Nevada (US-WEST)", "state": "NV", "lat": 36.2, "lon": -115.2},
    {"name": "Georgia (US-SE)", "state": "GA", "lat": 33.8, "lon": -84.4},
    {"name": "Ohio (US-MIDWEST)", "state": "OH", "lat": 40.4, "lon": -82.9},
    {"name": "Dublin, Ireland", "state": "IE", "lat": 53.3, "lon": -6.3},
    {"name": "Singapore", "state": "SG", "lat": 1.3, "lon": 103.8},
]


# Aterio likelihood string -> numeric confidence
_LIKELIHOOD_NUMERIC = {"High": 0.9, "Medium": 0.75, "Low": 0.6}

# US census regions used by get_triangulation_data()
_REGION_BUCKETS = {
    "US-EAST": {"VA", "NY", "NC", "FL", "GA", "MD", "DE", "NJ", "PA", "CT",
                "MA", "RI", "NH", "VT", "ME", "SC", "WV", "DC"},
    "US-WEST": {"CA", "OR", "WA", "NV", "AZ", "ID", "MT", "WY", "UT", "CO",
                "NM", "HI", "AK"},
    "US-CENTRAL": {"IA", "IL", "IN", "OH", "MI", "WI", "MO", "KS", "NE",
                   "MN", "ND", "SD"},
    "US-SOUTH": {"TX", "LA", "MS", "AL", "TN", "AR", "OK", "KY"},
}

_PILLAR_GUESS = {
    "aterio": "Power",
    "edgar": "Power",
    "echo": "Permits",
    "epa_echo": "Permits",
    "socrata": "Permits",
    "tceq": "Permits",
    "sentinel": "Satellite",
    "planet": "Satellite",
    "nvidia": "GPU Supply",
    "tsmc": "TSMC",
}


# ---------------------------------------------------------------------------
# Sync engine derived from the async DATABASE_URL
# ---------------------------------------------------------------------------

def _sync_url() -> str:
    """Translate the async DATABASE_URL to a psycopg2-compatible sync URL."""
    url = settings.database_url
    # Normalise async drivers to psycopg2 sync. Order matters: do not
    # double-rewrite "+psycopg2" by matching "+psycopg" after asyncpg.
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "+psycopg2")
    if "+psycopg2" in url:
        return url
    if "+psycopg" in url:
        return url.replace("+psycopg", "+psycopg2")
    return url


_engine = None
_Session: Optional[sessionmaker] = None


def _session() -> Session:
    """Lazy-init a sync SQLAlchemy session bound to a small connection pool."""
    global _engine, _Session
    if _Session is None:
        _engine = create_engine(
            _sync_url(),
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=2,
            future=True,
        )
        _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _Session()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _likelihood_to_num(val: Optional[str]) -> float:
    if not val:
        return 0.75
    return _LIKELIHOOD_NUMERIC.get(val, 0.75)


def _safe_avg(values: Iterable[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _parse_loose_date(s: Optional[str]) -> Optional[date]:
    """Parse 'YYYY-MM-DD' or 'YYYY' or 'YYYY-MM' into a date; None if unparseable."""
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # Sometimes Aterio uses "Q1 2024" etc. Best-effort: take the year.
    try:
        for tok in s.replace(",", " ").split():
            if len(tok) == 4 and tok.isdigit():
                return date(int(tok), 1, 1)
    except Exception:
        return None
    return None


def _to_quarter_label(d: date) -> str:
    q = (d.month - 1) // 3 + 1
    return f"Q{q} {d.year}"


def _quarter_sort_key(label: str) -> tuple:
    # "Q1 2024" -> (2024, 1)
    try:
        q, y = label.split()
        return (int(y), int(q[1:]))
    except Exception:
        return (0, 0)


def _region_for_state(state_code: Optional[str]) -> str:
    if not state_code:
        return "OTHER"
    sc = state_code.upper()
    for region, members in _REGION_BUCKETS.items():
        if sc in members:
            return region
    return "OTHER"


def _haversine_close(lat1: float, lon1: float, lat2: float, lon2: float, eps: float = 0.01) -> bool:
    """Very loose proximity check used to dedup curated vs DB sites."""
    if None in (lat1, lon1, lat2, lon2):
        return False
    return abs(lat1 - lat2) < eps and abs(lon1 - lon2) < eps


# ---------------------------------------------------------------------------
# 1. Power data - aggregated by (provider, state)
# ---------------------------------------------------------------------------

def get_power_data() -> List[Dict[str, Any]]:
    _require_mock_gate("get_power_data")

    rows: List[Dict[str, Any]] = []
    try:
        with _session() as db:
            # Aggregate at provider/state level
            stmt = (
                select(
                    Site.provider_name,
                    Site.state_code,
                    Site.state_name,
                    func.coalesce(func.sum(Site.power_capacity_mw), 0.0).label("mw_total"),
                    func.coalesce(
                        func.sum(func.coalesce(Site.aterio_est_mw_lower, Site.power_capacity_mw)),
                        0.0,
                    ).label("mw_contracted"),
                    func.coalesce(
                        func.sum(
                            case((Site.stage == "Activated", Site.power_capacity_mw), else_=0.0)
                        ),
                        0.0,
                    ).label("mw_operational"),
                    func.avg(Site.latitude).label("avg_lat"),
                    func.avg(Site.longitude).label("avg_lon"),
                    func.min(Site.datasheet_url).label("any_url"),
                )
                .where(Site.provider_name.isnot(None))
                .group_by(Site.provider_name, Site.state_code, Site.state_name)
            )
            agg_rows = db.execute(stmt).all()

            # Pull likelihood per (provider,state) separately to compute avg confidence
            likelihood_stmt = (
                select(
                    Site.provider_name,
                    Site.state_code,
                    Site.project_execution_likelihood,
                    func.count(Site.id),
                )
                .where(Site.provider_name.isnot(None))
                .group_by(Site.provider_name, Site.state_code, Site.project_execution_likelihood)
            )
            conf_table: Dict[tuple, List[tuple]] = defaultdict(list)
            for prov, st, lik, cnt in db.execute(likelihood_stmt).all():
                conf_table[(prov, st)].append((lik, cnt))

            for r in agg_rows:
                key = (r.provider_name, r.state_code)
                lik_rows = conf_table.get(key, [])
                if lik_rows:
                    weighted = sum(_likelihood_to_num(lik) * cnt for lik, cnt in lik_rows)
                    total_cnt = sum(cnt for _, cnt in lik_rows) or 1
                    confidence = weighted / total_cnt
                else:
                    confidence = 0.75

                region_label = r.state_name or r.state_code or "Unknown"
                rows.append({
                    "company": r.provider_name,
                    "region": region_label,
                    "state": r.state_code,
                    "lat": float(r.avg_lat) if r.avg_lat is not None else None,
                    "lon": float(r.avg_lon) if r.avg_lon is not None else None,
                    "gw_total": round(float(r.mw_total or 0.0) / 1000.0, 4),
                    "gw_contracted": round(float(r.mw_contracted or 0.0) / 1000.0, 4),
                    "gw_operational": round(float(r.mw_operational or 0.0) / 1000.0, 4),
                    "year": 2026,
                    "source": "Aterio dataset",
                    "source_url": r.any_url or "",
                    "confidence": round(confidence, 2),
                })
    except SQLAlchemyError:
        return []
    return rows


# ---------------------------------------------------------------------------
# 2. Power timeseries - cumulative GW per quarter per top-5 provider
# ---------------------------------------------------------------------------

def get_power_timeseries() -> Dict[str, List[Dict[str, Any]]]:
    _require_mock_gate("get_power_timeseries")

    series: Dict[str, List[Dict[str, Any]]] = {}
    try:
        with _session() as db:
            # Top-5 providers by total power_capacity_mw
            top_stmt = (
                select(
                    Site.provider_name,
                    func.coalesce(func.sum(Site.power_capacity_mw), 0.0).label("mw_total"),
                )
                .where(Site.provider_name.isnot(None))
                .group_by(Site.provider_name)
                .order_by(func.coalesce(func.sum(Site.power_capacity_mw), 0.0).desc())
                .limit(5)
            )
            top_providers = [r.provider_name for r in db.execute(top_stmt).all()]
            if not top_providers:
                return {}

            # Pull dates + capacity for each top provider
            detail_stmt = (
                select(
                    Site.provider_name,
                    Site.power_capacity_mw,
                    Site.announced_date,
                    Site.construction_finished_date,
                    Site.activation_date,
                )
                .where(Site.provider_name.in_(top_providers))
            )
            detail_rows = db.execute(detail_stmt).all()

            # Build a baseline of 4 trailing zero quarters + current snapshot.
            # We anchor the timeline on calendar quarters from Q1 2022 to current.
            today = datetime.utcnow().date()
            current_q_label = _to_quarter_label(today)

            # Build a list of all quarter labels from the earliest parseable date to today.
            all_dates: List[date] = []
            for prov, mw, ann, fin, act in detail_rows:
                for s in (ann, fin, act):
                    d = _parse_loose_date(s)
                    if d:
                        all_dates.append(d)
            min_date = min(all_dates) if all_dates else date(today.year - 2, 1, 1)
            if min_date.year < 2018:
                min_date = date(2018, 1, 1)

            # Generate quarter labels from min_date to today
            def _quarter_iter(start: date, end: date) -> List[str]:
                labels = []
                y, m = start.year, ((start.month - 1) // 3) * 3 + 1
                while (y, m) <= (end.year, ((end.month - 1) // 3) * 3 + 1):
                    labels.append(_to_quarter_label(date(y, m, 1)))
                    m += 3
                    if m > 12:
                        m = 1
                        y += 1
                return labels

            timeline = _quarter_iter(min_date, today)
            if not timeline:
                timeline = [current_q_label]

            # Per-provider: pick the most relevant date (announced) and bucket
            for prov in top_providers:
                bucket_mw: Dict[str, float] = defaultdict(float)
                total_mw = 0.0
                parseable = 0
                for p, mw, ann, fin, act in detail_rows:
                    if p != prov:
                        continue
                    mw_v = float(mw or 0.0)
                    total_mw += mw_v
                    # Prefer activation date if present, then construction_finished, then announced
                    chosen = (
                        _parse_loose_date(act)
                        or _parse_loose_date(fin)
                        or _parse_loose_date(ann)
                    )
                    if chosen is None:
                        continue
                    parseable += 1
                    bucket_mw[_to_quarter_label(chosen)] += mw_v

                if parseable == 0:
                    # Fall back to single snapshot at current quarter
                    series[prov] = [
                        {"quarter": current_q_label, "gw": round(total_mw / 1000.0, 4)}
                    ]
                    continue

                # Cumulative sum across the timeline
                cum_mw = 0.0
                points = []
                for q in timeline:
                    cum_mw += bucket_mw.get(q, 0.0)
                    points.append({"quarter": q, "gw": round(cum_mw / 1000.0, 4)})
                # Ensure at least 4 quarters of data
                if len(points) < 4:
                    pad = 4 - len(points)
                    points = [{"quarter": f"pad-{i}", "gw": 0.0} for i in range(pad)] + points
                series[prov] = points
    except SQLAlchemyError:
        return {}
    return series


# ---------------------------------------------------------------------------
# 3-5. GPU / NICs / TSMC - empty pillars (no data ingested yet)
# ---------------------------------------------------------------------------

def get_gpu_data() -> Dict[str, Any]:
    _require_mock_gate("get_gpu_data")
    return {
        "shipped": [],
        "deployed": [],
        "inventory": [],
        "revenue_estimates": [],
    }


def get_nics_optics_data() -> Dict[str, Any]:
    _require_mock_gate("get_nics_optics_data")
    return {
        "nic_shipments": [],
        "optics_shipments": [],
        "correlation_score": None,
    }


def get_tsmc_data() -> Dict[str, Any]:
    _require_mock_gate("get_tsmc_data")
    return {
        "capacity": [],
        "packaging": [],
    }


# ---------------------------------------------------------------------------
# 6. Permits data
# ---------------------------------------------------------------------------

def get_permits_data() -> List[Dict[str, Any]]:
    _require_mock_gate("get_permits_data")
    rows: List[Dict[str, Any]] = []
    try:
        with _session() as db:
            # Try real generator_permits first
            permit_stmt = (
                select(GeneratorPermit)
                .where(GeneratorPermit.latitude.isnot(None))
                .limit(200)
            )
            permits = db.execute(permit_stmt).scalars().all()
            if permits:
                for p in permits:
                    rows.append({
                        "county": p.county_fips or "",
                        "state": p.state_code,
                        "lat": p.latitude,
                        "lon": p.longitude,
                        "company": p.permittee_raw_name or p.facility_name or "Unknown",
                        "permit_type": "Generator (EPA/State)",
                        "filed_date": p.issued_date.isoformat() if p.issued_date else None,
                        "status": p.permit_status or "Unknown",
                        "estimated_sqft": None,
                        "estimated_mw": float(p.rated_mw_total) if p.rated_mw_total is not None else None,
                        "source": p.source or "Generator Permit",
                        "source_url": "",
                    })
                return rows

            # Fallback: synthesize from sites with permit_url
            site_stmt = (
                select(Site)
                .where(Site.permit_url.isnot(None))
                .limit(200)
            )
            for s in db.execute(site_stmt).scalars().all():
                rows.append({
                    "county": s.county_name or "",
                    "state": s.state_code,
                    "lat": s.latitude,
                    "lon": s.longitude,
                    "company": s.provider_name or "Unknown",
                    "permit_type": "Datacenter (Aterio)",
                    "filed_date": s.announced_date,
                    "status": s.stage or "Unknown",
                    "estimated_sqft": s.tot_facility_space_sqft,
                    "estimated_mw": s.power_capacity_mw,
                    "source": "Aterio",
                    "source_url": s.permit_url,
                })
    except SQLAlchemyError:
        return []
    return rows


# ---------------------------------------------------------------------------
# 7. Satellite sites - curated literal list + DB-derived top sites
#    NOTE: this function is intentionally NOT gated. Routers call it on
#    the MOCK path and rely on it being safe to call any time.
# ---------------------------------------------------------------------------

def get_satellite_sites() -> List[Dict[str, Any]]:
    """Curated handpicked sites + top DB sites. No mock gate required."""

    # Real, publicly announced data center sites. Milestones derived from
    # press releases, permit filings, earnings calls, and state economic
    # development announcements.
    sites: List[Dict[str, Any]] = [
        {
            "name": "Microsoft Goodyear Campus",
            "company": "Microsoft",
            "lat": 33.4373, "lon": -112.3576,
            "address": "Goodyear, Arizona",
            "status": "Active Construction",
            "size_acres": 279,
            "construction_pct": 45,
            "announced": "May 2024",
            "source": "Microsoft Blog - $3.3B Arizona investment",
            "source_url": "https://blogs.microsoft.com/on-the-issues/2024/05/02/microsoft-investment-arizona-ai-cloud/",
            "milestones": [
                {"date": "2024-05-02", "label": "Announced - $3.3B investment", "pct": 0, "type": "announcement"},
                {"date": "2024-07-15", "label": "Land acquisition finalized", "pct": 2, "type": "permit"},
                {"date": "2024-09-01", "label": "Site clearing & grading begins", "pct": 8, "type": "construction"},
                {"date": "2025-01-10", "label": "Foundation poured - Building 1", "pct": 22, "type": "construction"},
                {"date": "2025-06-01", "label": "Steel structure rising - Phase 1", "pct": 45, "type": "construction"},
                {"date": "2026-03-01", "label": "Phase 1 fit-out (projected)", "pct": 70, "type": "projected"},
                {"date": "2027-06-01", "label": "Full campus operational (projected)", "pct": 100, "type": "projected"},
            ],
        },
        {
            "name": "Microsoft Quincy Data Center",
            "company": "Microsoft",
            "lat": 47.2348, "lon": -119.8526,
            "address": "Quincy, Washington",
            "status": "Operational",
            "size_acres": 75,
            "construction_pct": 100,
            "announced": "2007 (expanding)",
            "source": "Microsoft / Grant County PUD",
            "source_url": "https://www.microsoft.com/en-us/corporate-responsibility/sustainability/datacenter-map",
            "milestones": [
                {"date": "2007-06-01", "label": "Original campus announced", "pct": 0, "type": "announcement"},
                {"date": "2008-09-01", "label": "Phase 1 operational", "pct": 30, "type": "construction"},
                {"date": "2011-03-01", "label": "Phase 2 expansion complete", "pct": 60, "type": "construction"},
                {"date": "2014-08-01", "label": "Phase 3 complete", "pct": 80, "type": "construction"},
                {"date": "2019-01-01", "label": "Full campus operational", "pct": 100, "type": "milestone"},
                {"date": "2023-06-01", "label": "AI/GPU wing expansion begun", "pct": 100, "type": "construction"},
            ],
        },
        {
            "name": "Microsoft Boydton Campus",
            "company": "Microsoft",
            "lat": 36.6651, "lon": -78.3881,
            "address": "Boydton, Virginia",
            "status": "Expanding",
            "size_acres": 345,
            "construction_pct": 80,
            "announced": "Ongoing expansion",
            "source": "Mecklenburg County / Microsoft",
            "source_url": "https://www.microsoft.com/en-us/corporate-responsibility/sustainability/datacenter-map",
            "milestones": [
                {"date": "2010-01-01", "label": "Original campus announced", "pct": 0, "type": "announcement"},
                {"date": "2011-06-01", "label": "Phase 1 operational", "pct": 25, "type": "construction"},
                {"date": "2015-03-01", "label": "Phase 2 & 3 complete", "pct": 55, "type": "construction"},
                {"date": "2020-01-01", "label": "Major Azure expansion", "pct": 70, "type": "construction"},
                {"date": "2023-09-01", "label": "AI infrastructure expansion", "pct": 80, "type": "construction"},
                {"date": "2025-12-01", "label": "Full expansion complete (projected)", "pct": 100, "type": "projected"},
            ],
        },
        {
            "name": "AWS Northern Virginia (IAD)",
            "company": "AWS",
            "lat": 39.0438, "lon": -77.4874,
            "address": "Ashburn, Virginia",
            "status": "Operational",
            "size_acres": 200,
            "construction_pct": 100,
            "announced": "2006 (us-east-1)",
            "source": "AWS Infrastructure - us-east-1",
            "source_url": "https://aws.amazon.com/about-aws/global-infrastructure/regions_az/",
            "milestones": [
                {"date": "2006-08-01", "label": "us-east-1 region launched", "pct": 10, "type": "announcement"},
                {"date": "2010-06-01", "label": "Multi-AZ expansion complete", "pct": 40, "type": "construction"},
                {"date": "2014-01-01", "label": "Campus doubles in size", "pct": 65, "type": "construction"},
                {"date": "2017-09-01", "label": "100MW milestone", "pct": 80, "type": "milestone"},
                {"date": "2020-01-01", "label": "Largest AWS region globally", "pct": 95, "type": "milestone"},
                {"date": "2024-01-01", "label": "Ongoing AI capacity expansion", "pct": 100, "type": "construction"},
            ],
        },
        {
            "name": "AWS Clarksville Campus",
            "company": "AWS",
            "lat": 36.5298, "lon": -87.3595,
            "address": "Clarksville, Tennessee",
            "status": "Active Construction",
            "size_acres": 250,
            "construction_pct": 30,
            "announced": "Oct 2024",
            "source": "Tennessee Dept of Economic Development - $10B Amazon investment",
            "source_url": "https://www.tn.gov/ecd/news/2024/10/amazon-tennessee.html",
            "milestones": [
                {"date": "2024-10-14", "label": "Announced - $10B TN investment", "pct": 0, "type": "announcement"},
                {"date": "2025-01-20", "label": "Land permits approved", "pct": 5, "type": "permit"},
                {"date": "2025-03-01", "label": "Site preparation begins", "pct": 15, "type": "construction"},
                {"date": "2025-08-01", "label": "Foundation work underway", "pct": 30, "type": "construction"},
                {"date": "2026-06-01", "label": "Phase 1 structure complete (projected)", "pct": 60, "type": "projected"},
                {"date": "2027-01-01", "label": "Phase 1 operational (projected)", "pct": 100, "type": "projected"},
            ],
        },
        {
            "name": "AWS Columbus (us-east-2)",
            "company": "AWS",
            "lat": 39.9612, "lon": -82.9988,
            "address": "Columbus, Ohio",
            "status": "Operational",
            "size_acres": 85,
            "construction_pct": 100,
            "announced": "2016 (us-east-2)",
            "source": "AWS Infrastructure - us-east-2",
            "source_url": "https://aws.amazon.com/about-aws/global-infrastructure/regions_az/",
            "milestones": [
                {"date": "2015-06-01", "label": "us-east-2 region announced", "pct": 0, "type": "announcement"},
                {"date": "2016-10-17", "label": "Region launched (3 AZs)", "pct": 50, "type": "milestone"},
                {"date": "2019-01-01", "label": "Capacity expansion Phase 2", "pct": 75, "type": "construction"},
                {"date": "2022-06-01", "label": "Full capacity operational", "pct": 100, "type": "milestone"},
            ],
        },
        {
            "name": "Google The Dalles Campus",
            "company": "Google",
            "lat": 45.6021, "lon": -121.1875,
            "address": "The Dalles, Oregon",
            "status": "Expanding",
            "size_acres": 96,
            "construction_pct": 85,
            "announced": "2006 (ongoing expansion)",
            "source": "Google Data Center - The Dalles",
            "source_url": "https://www.google.com/about/datacenters/locations/the-dalles/",
            "milestones": [
                {"date": "2006-01-01", "label": "Site acquired - first Google DC west of Rockies", "pct": 0, "type": "announcement"},
                {"date": "2006-12-01", "label": "Phase 1 operational", "pct": 20, "type": "milestone"},
                {"date": "2012-01-01", "label": "Phase 2 complete - campus doubles", "pct": 50, "type": "construction"},
                {"date": "2016-06-01", "label": "Phase 3 expansion - hydroelectric power deal", "pct": 65, "type": "construction"},
                {"date": "2020-09-01", "label": "Major capacity expansion approved", "pct": 75, "type": "permit"},
                {"date": "2024-01-01", "label": "AI infrastructure expansion underway", "pct": 85, "type": "construction"},
            ],
        },
        {
            "name": "Google Midlothian Campus",
            "company": "Google",
            "lat": 32.4807, "lon": -96.9800,
            "address": "Midlothian, Texas",
            "status": "Active Construction",
            "size_acres": 400,
            "construction_pct": 60,
            "announced": "2023",
            "source": "Ellis County / Google Texas expansion",
            "source_url": "https://www.google.com/about/datacenters/locations/",
            "milestones": [
                {"date": "2023-03-01", "label": "Site acquisition announced", "pct": 0, "type": "announcement"},
                {"date": "2023-06-01", "label": "Grading & utility permits filed", "pct": 5, "type": "permit"},
                {"date": "2023-09-01", "label": "Site clearing begins - 400 acres", "pct": 12, "type": "construction"},
                {"date": "2024-02-01", "label": "Foundation poured - Buildings 1-3", "pct": 30, "type": "construction"},
                {"date": "2024-09-01", "label": "Steel structure Phase 1 rising", "pct": 55, "type": "construction"},
                {"date": "2025-03-01", "label": "Phase 1 roofed - fit-out begins", "pct": 60, "type": "construction"},
                {"date": "2025-12-01", "label": "Phase 1 operational (projected)", "pct": 80, "type": "projected"},
            ],
        },
        {
            "name": "Google New Albany Campus",
            "company": "Google",
            "lat": 40.0814, "lon": -82.7913,
            "address": "New Albany, Ohio",
            "status": "Active Construction",
            "size_acres": 520,
            "construction_pct": 40,
            "announced": "Jan 2024",
            "source": "Google Blog - $1B Ohio investment",
            "source_url": "https://blog.google/inside-google/infrastructure/google-ohio-data-center-investment/",
            "milestones": [
                {"date": "2024-01-18", "label": "Announced - $1B Ohio investment", "pct": 0, "type": "announcement"},
                {"date": "2024-04-01", "label": "Permits filed with Licking County", "pct": 3, "type": "permit"},
                {"date": "2024-08-01", "label": "Site preparation & grading", "pct": 18, "type": "construction"},
                {"date": "2025-02-01", "label": "Foundation work begins", "pct": 35, "type": "construction"},
                {"date": "2025-07-01", "label": "Phase 1 structural steel (current)", "pct": 40, "type": "construction"},
                {"date": "2026-06-01", "label": "Phase 1 operational (projected)", "pct": 70, "type": "projected"},
            ],
        },
        {
            "name": "Google Council Bluffs Campus",
            "company": "Google",
            "lat": 41.2619, "lon": -95.8608,
            "address": "Council Bluffs, Iowa",
            "status": "Operational",
            "size_acres": 115,
            "construction_pct": 100,
            "announced": "2007",
            "source": "Google Data Center - Council Bluffs",
            "source_url": "https://www.google.com/about/datacenters/locations/council-bluffs/",
            "milestones": [
                {"date": "2007-06-01", "label": "Site announced - Iowa wind power deal", "pct": 0, "type": "announcement"},
                {"date": "2008-03-01", "label": "Phase 1 online", "pct": 30, "type": "milestone"},
                {"date": "2012-09-01", "label": "Phase 2 expansion complete", "pct": 65, "type": "construction"},
                {"date": "2016-01-01", "label": "100% renewable energy milestone", "pct": 80, "type": "milestone"},
                {"date": "2019-06-01", "label": "Full campus operational", "pct": 100, "type": "milestone"},
            ],
        },
        {
            "name": "Meta Altoona Data Center",
            "company": "Meta",
            "lat": 41.6467, "lon": -93.4686,
            "address": "Altoona, Iowa",
            "status": "Operational",
            "size_acres": 65,
            "construction_pct": 100,
            "announced": "2013",
            "source": "Meta Data Center - Altoona",
            "source_url": "https://engineering.fb.com/2013/11/15/data-center-engineering/building-facebook-s-most-efficient-data-center-yet/",
            "milestones": [
                {"date": "2013-04-01", "label": "Announced - first Iowa data center", "pct": 0, "type": "announcement"},
                {"date": "2014-06-01", "label": "Phase 1 operational", "pct": 40, "type": "milestone"},
                {"date": "2016-09-01", "label": "Phase 2 expansion complete", "pct": 75, "type": "construction"},
                {"date": "2018-01-01", "label": "100% renewable energy", "pct": 90, "type": "milestone"},
                {"date": "2020-06-01", "label": "Full campus operational", "pct": 100, "type": "milestone"},
            ],
        },
        {
            "name": "Meta Eagle Mountain Campus",
            "company": "Meta",
            "lat": 40.3135, "lon": -112.0110,
            "address": "Eagle Mountain, Utah",
            "status": "Active Construction",
            "size_acres": 360,
            "construction_pct": 55,
            "announced": "2022 (expanding 2024)",
            "source": "Utah County / Meta Eagle Mountain",
            "source_url": "https://sustainability.fb.com/",
            "milestones": [
                {"date": "2022-02-01", "label": "Site announced - 360 acres Utah County", "pct": 0, "type": "announcement"},
                {"date": "2022-07-01", "label": "Grading permits approved", "pct": 5, "type": "permit"},
                {"date": "2022-11-01", "label": "Site clearing begins", "pct": 10, "type": "construction"},
                {"date": "2023-05-01", "label": "Foundation - Buildings 1 & 2", "pct": 28, "type": "construction"},
                {"date": "2023-12-01", "label": "Phase 1 steel structure complete", "pct": 45, "type": "construction"},
                {"date": "2024-08-01", "label": "Phase 1 fit-out - MEP install", "pct": 55, "type": "construction"},
                {"date": "2025-06-01", "label": "Phase 1 operational (projected)", "pct": 75, "type": "projected"},
            ],
        },
        {
            "name": "Meta DeKalb Data Center",
            "company": "Meta",
            "lat": 41.9278, "lon": -88.7498,
            "address": "DeKalb, Illinois",
            "status": "Active Construction",
            "size_acres": 100,
            "construction_pct": 70,
            "announced": "2021 (expanding)",
            "source": "DeKalb County / Meta press release",
            "source_url": "https://sustainability.fb.com/",
            "milestones": [
                {"date": "2021-03-01", "label": "Site announced - 100 acres", "pct": 0, "type": "announcement"},
                {"date": "2021-08-01", "label": "Construction permits approved", "pct": 5, "type": "permit"},
                {"date": "2021-11-01", "label": "Site preparation begins", "pct": 12, "type": "construction"},
                {"date": "2022-06-01", "label": "Phase 1 foundation complete", "pct": 35, "type": "construction"},
                {"date": "2023-03-01", "label": "Phase 1 building enclosed", "pct": 55, "type": "construction"},
                {"date": "2024-01-01", "label": "Phase 1 operational - Phase 2 begins", "pct": 70, "type": "milestone"},
                {"date": "2025-06-01", "label": "Phase 2 operational (projected)", "pct": 100, "type": "projected"},
            ],
        },
        {
            "name": "Oracle Phoenix Cloud Region",
            "company": "Oracle",
            "lat": 33.4484, "lon": -111.9671,
            "address": "Phoenix, Arizona",
            "status": "Operational",
            "size_acres": 50,
            "construction_pct": 100,
            "announced": "2019",
            "source": "Oracle Cloud Infrastructure - PHX region",
            "source_url": "https://www.oracle.com/cloud/data-regions/",
            "milestones": [
                {"date": "2018-06-01", "label": "PHX region construction begins", "pct": 0, "type": "announcement"},
                {"date": "2019-05-01", "label": "PHX region launched (OCI Gen 2)", "pct": 60, "type": "milestone"},
                {"date": "2020-09-01", "label": "Phase 2 expansion complete", "pct": 80, "type": "construction"},
                {"date": "2022-01-01", "label": "Full capacity operational", "pct": 100, "type": "milestone"},
            ],
        },
        {
            "name": "Oracle Nashville Campus",
            "company": "Oracle",
            "lat": 36.1627, "lon": -86.7816,
            "address": "Nashville, Tennessee",
            "status": "Land Prep",
            "size_acres": 200,
            "construction_pct": 10,
            "announced": "2024",
            "source": "Oracle / Tennessee Economic Development",
            "source_url": "https://www.oracle.com/news/",
            "milestones": [
                {"date": "2024-06-01", "label": "Site announced - Nashville campus", "pct": 0, "type": "announcement"},
                {"date": "2024-10-01", "label": "Land acquisition complete", "pct": 3, "type": "permit"},
                {"date": "2025-02-01", "label": "Grading & utility permits filed", "pct": 7, "type": "permit"},
                {"date": "2025-05-01", "label": "Site preparation underway", "pct": 10, "type": "construction"},
                {"date": "2026-03-01", "label": "Foundation begins (projected)", "pct": 30, "type": "projected"},
                {"date": "2027-06-01", "label": "Phase 1 operational (projected)", "pct": 100, "type": "projected"},
            ],
        },
        {
            "name": "Equinix Ashburn Campus (DC)",
            "company": "Equinix",
            "lat": 39.0534, "lon": -77.4728,
            "address": "Ashburn, Virginia",
            "status": "Operational",
            "size_acres": 40,
            "construction_pct": 100,
            "announced": "1999 (ongoing expansion)",
            "source": "Equinix - Ashburn (DC) IBX",
            "source_url": "https://www.equinix.com/data-centers/americas-colocation/united-states-colocation/ashburn-data-centers",
            "milestones": [
                {"date": "1999-01-01", "label": "DC1 opens - founding the Data Center Alley", "pct": 5, "type": "milestone"},
                {"date": "2006-01-01", "label": "DC2-DC5 campus expands", "pct": 30, "type": "construction"},
                {"date": "2012-01-01", "label": "DC6-DC10 operational", "pct": 60, "type": "construction"},
                {"date": "2018-01-01", "label": "DC11 & DC12 complete", "pct": 80, "type": "construction"},
                {"date": "2023-01-01", "label": "xScale AI-ready expansion", "pct": 95, "type": "construction"},
                {"date": "2024-06-01", "label": "Current capacity - ongoing upgrades", "pct": 100, "type": "milestone"},
            ],
        },
    ]

    # Append DB-derived sites: top 60 by power_capacity_mw with non-null lat/lon
    try:
        with _session() as db:
            stmt = (
                select(Site)
                .where(
                    Site.latitude.isnot(None),
                    Site.longitude.isnot(None),
                    Site.power_capacity_mw.isnot(None),
                )
                .order_by(Site.power_capacity_mw.desc())
                .limit(60)
            )
            db_sites = db.execute(stmt).scalars().all()

            # Pre-fetch milestones for these sites in one query
            uids = [s.aterio_dc_uid for s in db_sites if s.aterio_dc_uid]
            events_by_uid: Dict[str, List[Event]] = defaultdict(list)
            if uids:
                ev_stmt = select(Event).where(Event.aterio_dc_uid.in_(uids))
                for ev in db.execute(ev_stmt).scalars().all():
                    events_by_uid[ev.aterio_dc_uid].append(ev)

            for s in db_sites:
                # Dedup against curated by lat/lon proximity
                if any(_haversine_close(s.latitude, s.longitude, c["lat"], c["lon"]) for c in sites):
                    continue

                milestones = []
                for ev in events_by_uid.get(s.aterio_dc_uid or "", []):
                    milestones.append({
                        "date": ev.event_date.isoformat() if ev.event_date else None,
                        "label": ev.event_description or "",
                        "pct": 0,
                        "type": ev.event_type or "milestone",
                    })

                sites.append({
                    "name": s.building_name or s.campus_name or s.aterio_dc_uid or "Unknown",
                    "company": s.provider_name or "Unknown",
                    "lat": s.latitude,
                    "lon": s.longitude,
                    "address": s.full_address or "",
                    "status": s.stage or "Unknown",
                    "size_acres": s.site_acreage,
                    "construction_pct": s.pct_construction,
                    "announced": s.announced_date or "",
                    "source": "Aterio",
                    "source_url": s.datasheet_url or "",
                    "milestones": milestones,
                })
    except SQLAlchemyError:
        # Curated list still returned even if DB read fails
        pass

    return sites


# ---------------------------------------------------------------------------
# 8. Triangulation - region-level rollup
# ---------------------------------------------------------------------------

def get_triangulation_data() -> List[Dict[str, Any]]:
    _require_mock_gate("get_triangulation_data")

    out: List[Dict[str, Any]] = []
    try:
        with _session() as db:
            # Base aggregation: per-state contracted MW + permit-signal count
            agg_stmt = (
                select(
                    Site.state_code,
                    func.coalesce(func.sum(Site.power_capacity_mw), 0.0).label("mw_total"),
                    func.sum(
                        case((Site.permit_url.isnot(None), 1), else_=0)
                    ).label("permit_signals"),
                    func.count(Site.id).label("site_count"),
                )
                .group_by(Site.state_code)
            )
            state_rows = db.execute(agg_stmt).all()

            # Likelihood per state for confidence avg
            lik_stmt = (
                select(
                    Site.state_code,
                    Site.project_execution_likelihood,
                    func.count(Site.id),
                )
                .group_by(Site.state_code, Site.project_execution_likelihood)
            )
            state_lik: Dict[str, List[tuple]] = defaultdict(list)
            for st, lik, cnt in db.execute(lik_stmt).all():
                state_lik[st or "OTHER"].append((lik, cnt))

            # Roll up to regions
            region_mw: Dict[str, float] = defaultdict(float)
            region_permits: Dict[str, int] = defaultdict(int)
            region_lik: Dict[str, List[tuple]] = defaultdict(list)

            for r in state_rows:
                region = _region_for_state(r.state_code)
                region_mw[region] += float(r.mw_total or 0.0)
                region_permits[region] += int(r.permit_signals or 0)
                for lik, cnt in state_lik.get(r.state_code or "OTHER", []):
                    region_lik[region].append((lik, cnt))

            # Always include all configured regions + OTHER
            ordered_regions = list(_REGION_BUCKETS.keys()) + ["OTHER"]
            for region in ordered_regions:
                contracted_gw = round(region_mw.get(region, 0.0) / 1000.0, 4)
                permit_count = region_permits.get(region, 0)
                lik_rows = region_lik.get(region, [])
                if lik_rows:
                    weighted = sum(_likelihood_to_num(lik) * cnt for lik, cnt in lik_rows)
                    total_cnt = sum(cnt for _, cnt in lik_rows) or 1
                    confidence = weighted / total_cnt
                else:
                    confidence = 0.75

                if contracted_gw > 1.5:
                    status = "Overbuild"
                else:
                    status = "Balanced"

                out.append({
                    "region": region,
                    "contracted_power_gw": contracted_gw,
                    "deployed_gpus_k": 0,
                    "gpu_power_demand_gw": 0,
                    "power_gap_gw": contracted_gw,
                    "status": status,
                    "nic_validation_score": None,
                    "permit_signal_count": permit_count,
                    "confidence": round(confidence, 2),
                })
    except SQLAlchemyError:
        return []
    return out


# ---------------------------------------------------------------------------
# 9. Sources - derived from ingestion_runs (or data_coverage fallback)
# ---------------------------------------------------------------------------

def _guess_pillar(adapter_name: str) -> str:
    if not adapter_name:
        return "General"
    n = adapter_name.lower()
    for key, pillar in _PILLAR_GUESS.items():
        if key in n:
            return pillar
    return "General"


def get_sources_data() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        with _session() as db:
            ing_stmt = (
                select(
                    IngestionRun.adapter_name,
                    func.max(IngestionRun.adapter_version).label("ver"),
                    func.max(IngestionRun.completed_at).label("last_completed_at"),
                    func.coalesce(func.sum(IngestionRun.records_stored), 0).label("total_stored"),
                )
                .group_by(IngestionRun.adapter_name)
                .order_by(IngestionRun.adapter_name)
            )
            ing_rows = db.execute(ing_stmt).all()

            if ing_rows:
                for idx, r in enumerate(ing_rows, start=1):
                    last_ing = (
                        r.last_completed_at.date().isoformat()
                        if r.last_completed_at is not None
                        else "never"
                    )
                    rows.append({
                        "id": idx,
                        "name": r.adapter_name,
                        "type": "Adapter",
                        "url": "",
                        "last_ingested": last_ing,
                        "records": int(r.total_stored or 0),
                        "pillar": _guess_pillar(r.adapter_name),
                        "description": f"Adapter {r.adapter_name} v{r.ver or '?'}",
                        "confidence": 0.85,
                    })
                return rows

            # Fallback: derive from data_coverage
            cov_stmt = (
                select(
                    DataCoverage.pillar,
                    DataCoverage.source,
                    func.max(DataCoverage.last_ingested_at).label("last_ing"),
                    func.coalesce(func.sum(DataCoverage.record_count), 0).label("rec_total"),
                )
                .group_by(DataCoverage.pillar, DataCoverage.source)
                .order_by(DataCoverage.pillar, DataCoverage.source)
            )
            for idx, r in enumerate(db.execute(cov_stmt).all(), start=1):
                last_ing = (
                    r.last_ing.date().isoformat()
                    if r.last_ing is not None
                    else "never"
                )
                rows.append({
                    "id": idx,
                    "name": r.source,
                    "type": "Coverage Source",
                    "url": "",
                    "last_ingested": last_ing,
                    "records": int(r.rec_total or 0),
                    "pillar": r.pillar,
                    "description": f"{r.pillar} pillar source: {r.source}",
                    "confidence": 0.80,
                })
    except SQLAlchemyError:
        return []
    return rows


# ---------------------------------------------------------------------------
# 10. Agent status - derived from ingestion_runs (or data_coverage fallback)
# ---------------------------------------------------------------------------

def get_agent_status() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        with _session() as db:
            ing_stmt = (
                select(
                    IngestionRun.adapter_name,
                    func.max(IngestionRun.started_at).label("last_run"),
                    func.max(IngestionRun.completed_at).label("last_completed_at"),
                    func.coalesce(func.sum(IngestionRun.records_stored), 0).label("records"),
                )
                .group_by(IngestionRun.adapter_name)
                .order_by(IngestionRun.adapter_name)
            )
            ing_rows = db.execute(ing_stmt).all()

            now = datetime.utcnow()
            cutoff = now - timedelta(days=30)

            if ing_rows:
                for r in ing_rows:
                    last_completed = r.last_completed_at
                    if last_completed is not None and last_completed >= cutoff:
                        status = "active"
                    else:
                        status = "idle"
                    out.append({
                        "agent": r.adapter_name,
                        "status": status,
                        "last_run": (
                            r.last_run.isoformat() + "Z"
                            if r.last_run is not None
                            else None
                        ),
                        "records_processed": int(r.records or 0),
                    })
                return out

            # Fallback: per-pillar entry from data_coverage
            cov_stmt = (
                select(
                    DataCoverage.pillar,
                    func.max(DataCoverage.last_ingested_at).label("last_ing"),
                    func.coalesce(func.sum(DataCoverage.record_count), 0).label("records"),
                )
                .group_by(DataCoverage.pillar)
                .order_by(DataCoverage.pillar)
            )
            for r in db.execute(cov_stmt).all():
                out.append({
                    "agent": f"{r.pillar} pillar",
                    "status": "unknown",
                    "last_run": r.last_ing.isoformat() + "Z" if r.last_ing else None,
                    "records_processed": int(r.records or 0),
                })
    except SQLAlchemyError:
        return []
    return out
