"""
Data sources and agent status endpoints.
Prefix: /api/sources

When MOCK_DATA=1, returns mock source data.
When MOCK_DATA=0, queries ingestion_runs table for real source info.
"""
from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from db.models import IngestionRun
from schemas.common import LineageEnvelope, LineageMeta

MOCK_ENABLED = os.environ.get("MOCK_DATA", "0") == "1"

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("/")
async def sources(db: AsyncSession = Depends(get_db)):
    if MOCK_ENABLED:
        from data.mock_data import get_sources_data, get_agent_status

        return LineageEnvelope(
            data={"sources": get_sources_data(), "agents": get_agent_status()},
            lineage=LineageMeta(
                source_url="mock",
                retrieved_at=datetime.utcnow(),
                parser_version="mock-v1",
                confidence=0.5,
            ),
        )

    # Real DB query: aggregate ingestion_runs by adapter_name
    stmt = (
        select(
            IngestionRun.adapter_name,
            IngestionRun.adapter_version,
            func.max(IngestionRun.started_at).label("last_run_at"),
            func.max(IngestionRun.completed_at).label("last_completed_at"),
            # Most recent status per adapter (via subquery would be ideal,
            # but for simplicity we grab the latest)
            func.sum(IngestionRun.records_stored).label("total_records_stored"),
            func.count(IngestionRun.id).label("run_count"),
        )
        .group_by(IngestionRun.adapter_name, IngestionRun.adapter_version)
        .order_by(IngestionRun.adapter_name)
    )
    result = await db.execute(stmt)
    rows = result.fetchall()

    sources_list = []
    agents_list = []
    for row in rows:
        adapter_name, adapter_version, last_run_at, last_completed_at, total_stored, run_count = row
        sources_list.append(
            {
                "name": adapter_name,
                "version": adapter_version,
                "last_run_at": last_run_at.isoformat() if last_run_at else None,
                "last_completed_at": last_completed_at.isoformat() if last_completed_at else None,
                "total_records_stored": total_stored or 0,
                "run_count": run_count,
            }
        )
        agents_list.append(
            {
                "name": adapter_name,
                "status": "active" if last_completed_at else "unknown",
                "last_run": last_run_at.isoformat() if last_run_at else None,
            }
        )

    # Get the latest run status per adapter for richer agent info
    latest_runs_stmt = (
        select(IngestionRun)
        .order_by(IngestionRun.started_at.desc())
        .limit(20)
    )
    latest_result = await db.execute(latest_runs_stmt)
    latest_runs = latest_result.scalars().all()

    # Override agent status with latest run info
    latest_by_adapter = {}
    for run in latest_runs:
        if run.adapter_name not in latest_by_adapter:
            latest_by_adapter[run.adapter_name] = run

    for agent in agents_list:
        run = latest_by_adapter.get(agent["name"])
        if run:
            agent["status"] = run.status
            if run.error_log:
                agent["last_error"] = str(run.error_log)[:200]

    return LineageEnvelope(
        data={"sources": sources_list, "agents": agents_list},
        lineage=LineageMeta(
            source_url="ingestion_runs",
            retrieved_at=datetime.utcnow(),
            parser_version="sources-v1.0.0",
            confidence=1.0,
        ),
    )


# ---------------------------------------------------------------------------
# /api/sources/overview — curated, three-section view used by the
# Data Sources tab. Hand-curated pipeline + source + agent inventories
# (source of truth for the dashboard) joined to live IngestionRun stats
# for last_run_at / status / row_count where applicable.
#
# Why hand-curated: ingestion_runs.adapter_name is a free-text string set
# per adapter call. Over time it has accumulated (a) duplicate rows for the
# same logical pipeline (multiple `epa_echo` versions, Socrata clones like
# `ny_dec_2wgt_bc53`), (b) cron job tags that aren't ingestion at all
# (`_cache_cleanup`, `_stale_check`, `_coverage_refresh`, …), and (c)
# adapter-id variants (`tceq`, `va_open_data`, `ny_dec` all roll up to
# the single "Permits — State" pipeline). Aggregating that table directly
# produced 28 confusing rows; this endpoint collapses to the 10 real
# pipelines + 8 real agents the platform actually runs.
# ---------------------------------------------------------------------------

# Pipelines: one entry per distinct ingestion file under backend/ingestion/.
# adapter_keys lists every adapter_name string the pipeline is known to write
# to ingestion_runs under, so we can roll up duplicate/versioned rows.
# dest_table is the primary DB table the pipeline writes to (used for
# row_count fallback when ingestion_runs has nothing useful).
_PIPELINES: list[dict] = [
    {
        "key": "aterio_csv",
        "name": "Aterio Datacenter Inventory",
        "description": "Loads the Aterio data-center CSV (6,973 sites, 73 columns) into the sites table and synthesizes timeline events.",
        "source_system": "Aterio",
        "source_url": "https://aterio.io",
        "adapter_keys": ["aterio_csv"],
        "dest_table": "sites",
    },
    {
        "key": "aterio_power",
        "name": "Aterio Energy Project Inventory",
        "description": "Loads the Aterio Energy Project xlsx (1,695 generation projects) into energy_projects.",
        "source_system": "Aterio",
        "source_url": "https://aterio.io",
        "adapter_keys": ["aterio_power"],
        "dest_table": "energy_projects",
    },
    {
        "key": "edgar_8k",
        "name": "SEC EDGAR — 8-K filings",
        "description": "Pulls 8-K material-event filings for tracked hyperscalers and energy counterparties; LLM extracts power-deal terms into edgar_extractions.",
        "source_system": "SEC EDGAR",
        "source_url": "https://www.sec.gov/edgar",
        "adapter_keys": ["edgar"],
        "dest_table": "edgar_extractions",
    },
    {
        "key": "edgar_quarterly",
        "name": "SEC EDGAR — 10-K / 10-Q / 20-F",
        "description": "Pulls quarterly/annual filings (incl. 20-F + 6-K for foreign private issuers); LLM extracts power and vendor-supply signals.",
        "source_system": "SEC EDGAR",
        "source_url": "https://www.sec.gov/edgar/searchedgar/companysearch",
        "adapter_keys": ["edgar_quarterly"],
        "dest_table": "edgar_extractions",
    },
    {
        "key": "epa_echo",
        "name": "EPA ECHO — Air Permits",
        "description": "Federal Title V / generator air-permit baseline for NAICS 518210 (Data Processing) facilities; PDFs cascaded through the document parser.",
        "source_system": "EPA ECHO",
        "source_url": "https://echo.epa.gov/tools/web-services",
        "adapter_keys": ["epa_echo"],
        "dest_table": "generator_permits",
    },
    {
        "key": "permits_state",
        "name": "Permits — State (TCEQ, NY DEC, VA, OH, IA)",
        "description": "State Socrata / open-data endpoints that publish generator and air permits at higher fidelity than EPA ECHO.",
        "source_system": "State Open Data Portals",
        "source_url": "https://www.tceq.texas.gov/permitting/air",
        "adapter_keys": [
            "permits_state",
            "tceq",
            "ny_dec",
            "va_open_data",
            # legacy / dev-clone tags kept here so they roll up cleanly
            "ny_dec_2wgt_bc53",
            "ny_dec_4n3a_en4b",
            "ny_dec_f4rp_2kvy",
        ],
        "dest_table": "generator_permits",
    },
    {
        "key": "permits_county",
        "name": "Permits — County (Loudoun VA, Mesa AZ, Grant WA)",
        "description": "County-level building permits for known data-center alleys; written to building_permits.",
        "source_system": "County Open Data Portals",
        "source_url": "https://solutions.loudoun.gov/lcpublic/",
        "adapter_keys": ["permits_county"],
        "dest_table": "building_permits",
    },
    {
        "key": "iso_queues",
        "name": "ISO Generator Interconnection Queues (PJM / MISO / ERCOT)",
        "description": "Interconnection-queue snapshots from PJM, MISO, and ERCOT; MW under study/contract are folded into energy_projects.",
        "source_system": "PJM / MISO / ERCOT",
        "source_url": "https://www.pjm.com/markets-and-operations/etools/oasis/system-information/generator-interconnection-queue",
        "adapter_keys": ["pjm_iso"],
        "dest_table": "energy_projects",
    },
    {
        "key": "ir_press_releases",
        "name": "IR Press Releases",
        "description": "Hyperscaler / energy / chip-vendor IR pages scraped for releases mentioning power, MW/GW, datacenter, or PPA terms.",
        "source_system": "Investor-Relations Sites",
        "source_url": "https://news.microsoft.com/feed/",
        "adapter_keys": ["ir_press_releases"],
        "dest_table": "press_releases",
    },
    {
        "key": "pdf_parser",
        "name": "Permit PDF Parser (cascade)",
        "description": "3-stage cascade (pdfplumber → OCR → LLM vision) that pulls MW, fuel type, and unit counts from generator-permit PDFs.",
        "source_system": "Internal pipeline",
        "source_url": "https://www.epa.gov/enforcement/echo-data-downloads",
        "adapter_keys": ["pdf_parser_bulk"],
        "dest_table": "generator_permits",
    },
]

# Sources: one or more underlying source systems per pipeline. URLs all
# resolve to a real, public homepage / API entry point.
_SOURCES: list[dict] = [
    {"pipeline": "aterio_csv",      "name": "Aterio Datacenter Inventory CSV",     "url": "https://aterio.io"},
    {"pipeline": "aterio_power",    "name": "Aterio Energy Project Inventory",      "url": "https://aterio.io"},
    {"pipeline": "edgar_8k",        "name": "SEC EDGAR — 8-K filings",              "url": "https://www.sec.gov/edgar/searchedgar/currentevents"},
    {"pipeline": "edgar_quarterly", "name": "SEC EDGAR — 10-K / 10-Q",              "url": "https://www.sec.gov/edgar/searchedgar/companysearch"},
    {"pipeline": "edgar_quarterly", "name": "SEC EDGAR — 20-F / 6-F (foreign filers)", "url": "https://www.sec.gov/forms"},
    {"pipeline": "epa_echo",        "name": "EPA ECHO Air Facility Search",         "url": "https://echodata.epa.gov/echo/air_rest_services.metadata"},
    {"pipeline": "permits_state",   "name": "TCEQ Air New Source Review",           "url": "https://www.tceq.texas.gov/permitting/air"},
    {"pipeline": "permits_state",   "name": "NY DEC Title V & State Facility",      "url": "https://www.dec.ny.gov/permits-licenses/permits"},
    {"pipeline": "permits_state",   "name": "Virginia Open Data Portal",            "url": "https://data.virginia.gov/"},
    {"pipeline": "permits_state",   "name": "Ohio EPA Open Data",                   "url": "https://epa.ohio.gov/divisions-and-offices/air-pollution-control"},
    {"pipeline": "permits_state",   "name": "Iowa DNR / Open Data",                 "url": "https://data.iowa.gov/"},
    {"pipeline": "permits_county",  "name": "Loudoun County, VA permits",           "url": "https://solutions.loudoun.gov/lcpublic/"},
    {"pipeline": "permits_county",  "name": "Mesa, AZ open data",                   "url": "https://data.mesaaz.gov/"},
    {"pipeline": "permits_county",  "name": "Grant County, WA",                     "url": "https://www.grantcountywa.gov/"},
    {"pipeline": "iso_queues",      "name": "PJM Generator Interconnection Queue",  "url": "https://www.pjm.com/markets-and-operations/etools/oasis/system-information/generator-interconnection-queue"},
    {"pipeline": "iso_queues",      "name": "MISO Generator Interconnection Queue", "url": "https://www.misoenergy.org/planning/resource-utilization/GIQ/"},
    {"pipeline": "iso_queues",      "name": "ERCOT GIS Reports",                    "url": "https://www.ercot.com/gridinfo/resource"},
    {"pipeline": "ir_press_releases", "name": "Microsoft Source (RSS)",             "url": "https://news.microsoft.com/feed/"},
    {"pipeline": "ir_press_releases", "name": "Amazon IR Newsroom",                 "url": "https://ir.aboutamazon.com/news-release/default.aspx"},
    {"pipeline": "ir_press_releases", "name": "Alphabet IR",                        "url": "https://abc.xyz/investor/news/"},
    {"pipeline": "pdf_parser",      "name": "Title V permit PDFs (EPA / state)",    "url": "https://echo.epa.gov/tools/data-downloads"},
]

# Agents: real LLM-driven or analytic agents that show up in the product.
# Pruned from the 28 ingestion_runs.adapter_name rows by removing:
#   - 7 cron-job rows (`_anomaly_detection`, `_cache_cleanup`,
#     `_coverage_refresh`, `_freshness_doc_refresh`, `_insights_daily`,
#     `_stale_check`, `_weekly_brief`) — these are scheduler tags, not
#     agents. The work they trigger is still surfaced (anomaly_detector,
#     weekly_brief, insights orchestrator) under its real agent name.
#   - 6 ingestion-adapter rows (`aterio_csv`, `edgar`, `epa_echo`, ...) —
#     these are pipelines, listed in the Pipelines section above.
#   - 3 dev-clone Socrata rows (`ny_dec_2wgt_bc53`, `ny_dec_4n3a_en4b`,
#     `ny_dec_f4rp_2kvy`) — duplicates of `ny_dec`, already rolled up.
#   - duplicate-version rows (`epa_echo` v1.0/1.1/1.2, `edgar` v1.0/2.0,
#     `pjm_iso` x2, `tceq` x2, `va_open_data` x2) — same agent, multiple
#     parser versions. Latest version is reported for each.
#
# Net: 28 raw rows → 8 distinct LLM/analytic agents.
_AGENTS: list[dict] = [
    {
        "name": "EDGAR Power Extractor",
        "description": "Reads 8-K / 10-K / 10-Q filings and extracts power-deal counterparties, MW capacity, and methodology into edgar_extractions.",
        "used_by": "Power tab",
        "model": "oci/openai.gpt-5.4-mini",
    },
    {
        "name": "EDGAR Vendor-Supply Extractor",
        "description": "Parallel pass over filings that pulls hardware-supply signals (segment revenue, inventory, purchase commitments) for chip & networking vendors.",
        "used_by": "GPU Supply / TSMC tabs",
        "model": "oci/openai.gpt-5.4-mini",
    },
    {
        "name": "Parent Resolver",
        "description": "Resolves an LLC permittee name (e.g. \"Vadata, Inc.\") to its hyperscaler parent using SEC Exhibit 21 + OpenCorporates + ISO queue + LLM web search, with confidence aggregation.",
        "used_by": "Permits tab",
        "model": "oci/openai.gpt-5.4 (LLM signal) — deterministic when other signals corroborate",
    },
    {
        "name": "Anomaly Detector",
        "description": "Z-score detector over 12-week trailing windows for PJM queue MW, permit filings (VA/NY), and EDGAR capacity. Flags >2σ deviations.",
        "used_by": "Sidebar / Brief",
        "model": "deterministic (no LLM)",
    },
    {
        "name": "Weekly Brief Agent",
        "description": "OpenClaw agentic turn over the 7-day context (sites, events, EDGAR, energy projects). Persists to brief_runs every Sunday 23:00 UTC.",
        "used_by": "Brief tab",
        "model": "openclaw/default (oci/openai.gpt-5.4)",
    },
    {
        "name": "Datacenter Q&A Agent",
        "description": "Schema-aware Q&A over the SQL warehouse. Streams text, tool calls, citations, and chart specs to the chat dock.",
        "used_by": "Q&A chat dock (global)",
        "model": "openclaw/default (oci/openai.gpt-5.4)",
    },
    {
        "name": "Triangulation Q&A Agent",
        "description": "Narrower Q&A lane scoped to triangulating power vs. permit vs. queue evidence for a single buyer or site.",
        "used_by": "Triangulation tab",
        "model": "openclaw/default (oci/openai.gpt-5.4)",
    },
    {
        "name": "AI Insights Orchestrator",
        "description": "v2 agentic session driver: bootstraps via call_api, then delegates to run_agentic_synthesis. The agent grounds claims with search_documents + query_database and persists each insight + chart through MCP write-tools.",
        "used_by": "AI Insights tab",
        "model": "oci/openai.gpt-5.4 (reasoning) + oci/openai.gpt-5.4-mini (extraction)",
    },
]


def _classify_status(last_run_at: datetime | None, last_status: str | None) -> str:
    """ok if last run < 7d ago and status was success-ish; stale if older;
    error if the latest run row recorded a failure."""
    if last_status and last_status.lower() in {"failure", "error", "partial_failure"}:
        return "error"
    if last_run_at is None:
        return "stale"
    age = datetime.utcnow() - last_run_at
    if age.days >= 7:
        return "stale"
    return "ok"


@router.get("/overview")
async def sources_overview(db: AsyncSession = Depends(get_db)):
    """Three-section view used by the Data Sources tab.

    Shape:
        {
          "pipelines": [...],   # one per real ingestion pipeline
          "sources":   [...],   # underlying source per pipeline (1..N)
          "agents":    [...],   # real LLM/analytic agents only
        }
    """
    # Aggregate ingestion_runs once; we'll look up per-pipeline below.
    runs_stmt = (
        select(
            IngestionRun.adapter_name,
            func.max(IngestionRun.started_at).label("last_run_at"),
            func.sum(IngestionRun.records_stored).label("rows_total"),
        )
        .group_by(IngestionRun.adapter_name)
    )
    runs_rows = (await db.execute(runs_stmt)).fetchall()
    by_adapter: dict[str, dict] = {
        r.adapter_name: {
            "last_run_at": r.last_run_at,
            "rows_total": int(r.rows_total or 0),
        }
        for r in runs_rows
    }

    # Latest status per adapter (most recent run row).
    latest_status: dict[str, str] = {}
    latest_stmt = (
        select(IngestionRun.adapter_name, IngestionRun.status, IngestionRun.started_at)
        .order_by(IngestionRun.started_at.desc())
    )
    for adapter_name, status, _started in (await db.execute(latest_stmt)).fetchall():
        latest_status.setdefault(adapter_name, status)

    # Build pipelines list — fold all adapter_keys into one row.
    pipelines_out: list[dict] = []
    for p in _PIPELINES:
        last_run: datetime | None = None
        rows = 0
        last_status: str | None = None
        for k in p["adapter_keys"]:
            agg = by_adapter.get(k)
            if not agg:
                continue
            if agg["last_run_at"] and (last_run is None or agg["last_run_at"] > last_run):
                last_run = agg["last_run_at"]
                last_status = latest_status.get(k)
            rows += agg["rows_total"]

        # If ingestion_runs gave us no useful row count (some pipelines do
        # not record records_stored) fall back to a SELECT count(*) on the
        # destination table.
        if rows == 0 and p.get("dest_table"):
            try:
                from sqlalchemy import text as _text
                r = await db.execute(_text(f"select count(*) from {p['dest_table']}"))
                rows = int(r.scalar_one() or 0)
            except Exception:
                pass

        pipelines_out.append({
            "key": p["key"],
            "name": p["name"],
            "description": p["description"],
            "source_system": p["source_system"],
            "source_url": p["source_url"],
            "last_run_at": last_run.isoformat() if last_run else None,
            "status": _classify_status(last_run, last_status),
            "row_count": rows,
        })

    return LineageEnvelope(
        data={
            "pipelines": pipelines_out,
            "sources": _SOURCES,
            "agents": _AGENTS,
        },
        lineage=LineageMeta(
            source_url="ingestion_runs + curated registry",
            retrieved_at=datetime.utcnow(),
            parser_version="sources-overview-v1.0.0",
            confidence=1.0,
        ),
    )
