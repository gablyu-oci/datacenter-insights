"""
Permits endpoints.
Prefix: /api/permits

When MOCK_DATA=0, queries generator_permits table for real data.
When MOCK_DATA=1, returns mock permit data.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import timedelta

from db.session import get_db
from db.models import BuildingPermit, Company, GeneratorPermit
from schemas.common import CoverageEnvelope, CoverageMeta, LineageMeta

MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"

# Phase 1.5: data-center-relevant fuel types (per PRD §5)
DATACENTER_FUEL_TYPES = {"diesel", "natural_gas", "dual_fuel"}

router = APIRouter(prefix="/api/permits", tags=["permits"])


def _clean_url(u: Optional[str]) -> Optional[str]:
    """Strip CR/LF/whitespace/control chars from a URL.

    Some upstream feeds (notably TCEQ) embed `\\r` mid-URL which yields
    HTTP 000 when curled and breaks browsers. URLs never carry legitimate
    whitespace, so we scrub it here.
    """
    if not u:
        return None
    cleaned = re.sub(r"[\s\x00-\x1f\x7f]+", "", u)
    return cleaned or None


def _is_self_named_autoresolve(parent_name: Optional[str], permittee_raw: Optional[str]) -> bool:
    """Return True if the joined parent name is just a near-duplicate of
    the original permittee_raw_name (i.e. a self-resolution that
    masquerades as parent resolution).

    Example: permittee "AGRI DRAIN CORP" got auto-resolved to a Company
    row literally named "AGRI DRAIN CORP" -- that's not a real parent
    resolution and the UI should suppress it.
    """
    if not parent_name or not permittee_raw:
        return False
    a = re.sub(r"[^a-z0-9]+", "", parent_name.lower())
    b = re.sub(r"[^a-z0-9]+", "", permittee_raw.lower())
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 6 and (a in b or b in a):
        return True
    return False


def _permit_to_dict(p: GeneratorPermit, parent_name: Optional[str] = None) -> dict:
    """Convert GeneratorPermit model to dict, optionally with joined parent name.

    Two enrichments happen here at read-time so the UI doesn't show a wall
    of bare LLC names + null source links:

      1. source_url fallback. The parent_resolver agent stores it in
         raw_payload.source_url for the sources that have a row-level
         deep link (TCEQ, VA Open Data). For the others we construct a
         deterministic URL from the row's identifiers:
           epa_echo  -> https://echo.epa.gov/detailed-facility-report?fid={frs_id}
           pjm       -> the PJM new-services queue main page (queue is
                         not row-addressable, but better than null)

      2. resolved_company_name fallback. The parent_resolver hasn't run
         against the PJM dataset (3,631 rows = 87% of the table), so most
         PJM rows have no canonical. As a quick visible win, do a
         keyword match on the raw permittee name -- if it contains a
         hyperscaler / OCI / known-canonical token, surface that.
    """
    d = {}
    for col in GeneratorPermit.__table__.columns:
        val = getattr(p, col.name, None)
        if isinstance(val, (datetime, date)):
            val = val.isoformat()
        d[col.name] = val

    # ── 1. resolved_company_name (suppress self-named auto-resolutions) ──
    # The DB has 500+ epa_echo rows where resolved_company_id points at
    # an auto-created Company row whose canonical_name == the permittee
    # itself ("AGRI DRAIN CORP" -> "AGRI DRAIN CORP"). That's not a real
    # parent resolution. Detect and suppress, then fall back to the
    # keyword-derived parent if one matches.
    keyword_parent = _keyword_canonical(p.permittee_raw_name)
    if parent_name and not _is_self_named_autoresolve(parent_name, p.permittee_raw_name):
        d["resolved_company_name"] = parent_name
    elif keyword_parent:
        d["resolved_company_name"] = keyword_parent
    else:
        d["resolved_company_name"] = None

    # ── 2. source_url with per-source fallback ────────────────────────
    # The previous fallback for PJM rows pointed every row at
    # https://www.pjm.com/planning/services-requests/services-queue --
    # which 302s through to a content-less SharePoint asset and is not
    # row-addressable. PJM rows DO carry per-row PDF deep links inside
    # raw_payload (FacilitiesStudy, FeasibilityStudy, SystemImpactStudy,
    # Interim-InterconnectionService-...). We prefer those in order.
    raw = d.get("raw_payload") or {}
    raw_url = raw.get("source_url") if isinstance(raw, dict) else None
    fallback_url: Optional[str] = None
    src = (p.source or "").lower()
    if not raw_url:
        if src == "epa_echo" and p.frs_id:
            fallback_url = f"https://echo.epa.gov/detailed-facility-report?fid={p.frs_id}"
        elif src == "pjm" and isinstance(raw, dict):
            # Order matters: ISA / construction agreement first (most
            # legally-meaningful), then study PDFs in reverse chronology.
            for k in (
                "Interim-InterconnectionService-GenerationInterconnectionAgreement",
                "ConstructionServiceAgreement",
                "UpgradeConstructionServiceAgreement",
                "SystemImpactStudy",
                "FacilitiesStudy",
                "FeasibilityStudy",
            ):
                v = raw.get(k)
                if not isinstance(v, str) or not v.startswith("http"):
                    continue
                # Reject placeholder URLs like
                # "https://www.pjm.com/pjmfiles/N/A" that PJM stores when a
                # document hasn't been posted yet.
                tail = v.rstrip("/").rsplit("/", 1)[-1].lower()
                if tail in ("n/a", "na", "tba", "tbd", ""):
                    continue
                if v.lower().endswith("/n/a") or "/n/a/" in v.lower():
                    continue
                fallback_url = v
                break
            # Last resort: the PJM new-services queue landing page. It's
            # not row-addressable, but it's a real, navigable page (200) --
            # better than null. We avoid the deprecated planning-api
            # endpoint which 404s.
            if not fallback_url:
                fallback_url = (
                    "https://www.pjm.com/planning/services-requests/services-queue"
                )
        elif src == "tceq" and p.source_permit_id:
            fallback_url = (
                f"https://www.tceq.texas.gov/permitting/air/newsourcereview/"
                f"airpermits-pendingpermit-apps#{p.source_permit_id}"
            )
    d["source_url"] = _clean_url(raw_url or fallback_url or d.get("source_url"))
    return d


# Quick canonical-keyword lookup so rows without a parent_resolver match
# still surface the obvious hyperscaler / OCI affiliation. Order matters
# (most-specific first); first match wins.
_CANONICAL_KEYWORDS: tuple[tuple[str, str], ...] = (
    # ── Hyperscalers + their permitting LLCs (SEC Exhibit 21) ─────────
    ("microsoft",        "Microsoft"),
    ("msft",             "Microsoft"),
    ("azure",            "Microsoft"),
    ("amazon",           "Amazon"),
    (" aws ",            "Amazon"),  # padded to avoid "AWSON"
    ("vadata",           "Amazon"),  # AWS Exhibit 21 shell
    ("ads-c01",          "Amazon"),  # AWS internal facility code
    ("google",           "Google"),
    ("alphabet",         "Google"),
    ("raiden",           "Google"),  # Google Exhibit 21 LLC
    ("bowman dev",       "Google"),  # Bowman Development LLC -> Google
    ("meta ",            "Meta"),
    ("facebook",         "Meta"),
    ("mfnw",             "Meta"),    # Meta Exhibit 21 LLC
    ("starbelt",         "Meta"),    # Meta Exhibit 21 LLC
    ("oracle",           "Oracle"),
    ("apple",            "Apple"),
    # ── PJM Transmission Owner / utility codes (case-insensitive) ─────
    # PJM permittee_raw_name is often a project name and TransmissionOwner
    # an abbreviation -- catch the obvious ones so the user sees who is
    # actually behind the project.
    ("pseg",             "PSEG"),
    ("pepco",            "Exelon"),         # PEPCO is an Exelon subsidiary
    ("peco",             "Exelon"),         # PECO Energy is Exelon
    ("comed",            "Exelon"),
    ("exelon",           "Exelon"),
    ("dominion",         "Dominion Energy"),
    ("vistra",           "Vistra"),
    ("nextera",          "NextEra Energy"),
    ("fpl ",             "NextEra Energy"),
    ("constellation",    "Constellation Energy"),
    ("talen",            "Talen Energy"),
    ("entergy",          "Entergy"),
    ("duke ener",        "Duke Energy"),
    ("duke energy",      "Duke Energy"),
    ("southern co",      "Southern Company"),
    ("georgia power",    "Southern Company"),
    ("alabama power",    "Southern Company"),
    ("aep ",             "American Electric Power"),
    ("american electric","American Electric Power"),
    ("firstenergy",      "FirstEnergy"),
    ("first energy",     "FirstEnergy"),
    ("ppl ",             "PPL"),
    ("ppl electric",     "PPL"),
    ("berkshire hath",   "Berkshire Hathaway Energy"),
    ("midamerican",      "Berkshire Hathaway Energy"),
    ("nv energy",        "Berkshire Hathaway Energy"),
    ("tva ",             "TVA"),
    ("tennessee valley", "TVA"),
    # ── Met-Ed / Penelec / Penn Power (FirstEnergy subs) ──────────────
    (" me ",             "FirstEnergy"),     # PJM short code for Met-Ed
    ("met-ed",           "FirstEnergy"),
    ("penelec",          "FirstEnergy"),
    ("penn power",       "FirstEnergy"),
    # ── JCP&L (FirstEnergy NJ sub) and Delmarva ───────────────────────
    ("jcpl",             "FirstEnergy"),
    ("jcp&l",            "FirstEnergy"),
    (" dpl ",            "Exelon"),          # Delmarva Power -> Exelon
    ("delmarva",         "Exelon"),
    ("bge ",             "Exelon"),          # Baltimore Gas & Electric
    # ── Generation companies and SMR / advanced reactor vendors ───────
    ("nuscale",          "NuScale Power"),
    ("oklo",             "Oklo"),
    ("x-energy",         "X-energy"),
    ("xenergy",          "X-energy"),
    ("kairos",           "Kairos Power"),
    ("terrapower",       "TerraPower"),
)


def _keyword_canonical(raw: Optional[str]) -> Optional[str]:
    """Best-effort canonical name when the parent_resolver agent hasn't
    matched the row. Returns None if no keyword hits, so the UI keeps
    showing the raw name unmolested in that case.
    """
    if not raw:
        return None
    s = f" {raw.lower()} "  # pad for whole-word matching of "aws"/"meta"
    for needle, canon in _CANONICAL_KEYWORDS:
        if needle in s:
            return canon
    return None


@router.get("/")
async def permits_list(
    state: Optional[str] = Query(None, description="Filter by state code"),
    source: Optional[str] = Query(None, description="Filter by permit source (epa_echo, tceq, etc.)"),
    fuel_type: Optional[str] = Query(
        None,
        description=(
            "Comma-separated fuel types (diesel,natural_gas,dual_fuel). "
            "Empty/omitted -> all fuel types."
        ),
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
):
    if MOCK_ENABLED:
        from data.mock_data import get_permits_data, COLORS

        return CoverageEnvelope(
            data={"data": get_permits_data(), "colors": COLORS},
            lineage=LineageMeta(
                source_url="mock",
                retrieved_at=datetime.utcnow(),
                parser_version="mock-v1",
                confidence=0.5,
            ),
            coverage=CoverageMeta(pillar="permits"),
        )

    # Real DB query -- LEFT JOIN companies to resolve parent name in one trip.
    query = (
        select(GeneratorPermit, Company.canonical_name)
        .outerjoin(Company, Company.id == GeneratorPermit.resolved_company_id)
    )
    count_query = select(func.count(GeneratorPermit.id))

    if state:
        query = query.where(GeneratorPermit.state_code == state.upper())
        count_query = count_query.where(GeneratorPermit.state_code == state.upper())
    if source:
        query = query.where(GeneratorPermit.source == source)
        count_query = count_query.where(GeneratorPermit.source == source)

    # Fuel-type filter -- comma-separated list. Default: no filter (all rows).
    # Real-world fuel_type values are mixed-case and may be semicolon-joined
    # (e.g. PJM emits "Natural Gas; Other"), so we match each requested fuel
    # via case-insensitive substring (ILIKE %fuel%) and OR the predicates.
    # Map our canonical hints to upstream substrings.
    FUEL_HINT_MAP = {
        "diesel": ["diesel", "oil"],
        "natural_gas": ["natural gas", "methane"],
        "dual_fuel": ["dual fuel", "dual-fuel"],
    }
    requested_fuels: Optional[list[str]] = None
    if fuel_type:
        requested_fuels = [f.strip().lower() for f in fuel_type.split(",") if f.strip()]
        if requested_fuels:
            patterns: list[str] = []
            for f in requested_fuels:
                patterns.extend(FUEL_HINT_MAP.get(f, [f]))
            ilike_clauses = [
                GeneratorPermit.fuel_type.ilike(f"%{p}%") for p in patterns
            ]
            query = query.where(or_(*ilike_clauses))
            count_query = count_query.where(or_(*ilike_clauses))

    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    query = query.order_by(GeneratorPermit.id.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    rows = result.all()

    # States for coverage metadata
    states_result = await db.execute(
        select(GeneratorPermit.state_code)
        .where(GeneratorPermit.state_code.isnot(None))
        .distinct()
    )
    states_included = sorted([r[0] for r in states_result.fetchall() if r[0]])

    # Distinct sources (for the citation footer)
    sources_result = await db.execute(
        select(GeneratorPermit.source)
        .where(GeneratorPermit.source.isnot(None))
        .distinct()
    )
    sources_included = sorted([r[0] for r in sources_result.fetchall() if r[0]])

    return CoverageEnvelope(
        data={
            "data": [_permit_to_dict(p, parent_name) for (p, parent_name) in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "fuel_types_requested": requested_fuels,
            "sources_included": sources_included,
        },
        lineage=LineageMeta(
            source_url="generator_permits",
            retrieved_at=datetime.utcnow(),
            parser_version="permits-v1.1.0",
            confidence=0.85,
        ),
        coverage=CoverageMeta(
            pillar="permits",
            states_included=states_included,
        ),
    )


def _building_permit_to_dict(p: BuildingPermit) -> dict:
    """Serialize a BuildingPermit row, ISO-encoding date/datetime fields."""
    d = {}
    for col in BuildingPermit.__table__.columns:
        val = getattr(p, col.name, None)
        if isinstance(val, (datetime, date)):
            val = val.isoformat()
        d[col.name] = val
    return d


@router.get("/building")
async def permits_building(
    county: Optional[str] = Query(None, description="Filter by county name (case-insensitive)"),
    state: Optional[str] = Query(None, description="Filter by 2-letter state code"),
    days: int = Query(180, ge=1, le=3650, description="Window for issued_date (days back from today)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
):
    """County-level US building-permit feed (the user-fixes AC3).

    Backed by the building_permits table populated by
    ingestion/permits_county adapters (Loudoun VA, Mesa AZ, etc.).
    Distinct from /api/permits/datacenter, which serves the
    generator_permits table.
    """
    cutoff = date.today() - timedelta(days=days)

    query = select(BuildingPermit)
    count_query = select(func.count(BuildingPermit.id))

    # issued_date may be null (Loudoun outlines have no date) -- include
    # those rows by OR-ing on a null check so the dataset isn't silently
    # zeroed out for window-less sources.
    date_filter = or_(
        BuildingPermit.issued_date.is_(None),
        BuildingPermit.issued_date >= cutoff,
    )
    query = query.where(date_filter)
    count_query = count_query.where(date_filter)

    if state:
        query = query.where(BuildingPermit.state == state.upper())
        count_query = count_query.where(BuildingPermit.state == state.upper())
    if county:
        query = query.where(BuildingPermit.county.ilike(f"%{county}%"))
        count_query = count_query.where(BuildingPermit.county.ilike(f"%{county}%"))

    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    query = query.order_by(
        BuildingPermit.issued_date.desc().nullslast(),
        BuildingPermit.id.desc(),
    ).offset(offset).limit(page_size)
    result = await db.execute(query)
    rows = result.scalars().all()

    states_result = await db.execute(
        select(BuildingPermit.state).where(BuildingPermit.state.isnot(None)).distinct()
    )
    states_included = sorted([r[0] for r in states_result.fetchall() if r[0]])

    # Freshness: row has been retrieved within the last 14 days = ok,
    # otherwise stale; if the table is empty, unknown.
    freshness_status: str = "unknown"
    most_recent = (await db.execute(
        select(func.max(BuildingPermit.retrieved_at))
    )).scalar()
    if most_recent is not None:
        age = datetime.utcnow() - most_recent
        freshness_status = "ok" if age <= timedelta(days=14) else "stale"

    return CoverageEnvelope(
        data={
            "data": [_building_permit_to_dict(p) for p in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        lineage=LineageMeta(
            source_url="db://building_permits",
            retrieved_at=datetime.utcnow(),
            parser_version="building-permits-v1",
            confidence=0.85,
        ),
        coverage=CoverageMeta(
            pillar="building_permits",
            states_included=states_included,
            freshness_status=freshness_status,
        ),
    )


@router.get("/datacenter")
async def permits_datacenter(
    state: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
):
    """Convenience endpoint pre-filtered to data-center-relevant fuel types.
    Equivalent to /?fuel_type=diesel,natural_gas,dual_fuel."""
    return await permits_list(
        state=state,
        source=None,
        fuel_type=",".join(sorted(DATACENTER_FUEL_TYPES)),
        page=page,
        page_size=page_size,
        db=db,
    )
