"""
CLI for manual ingestion runs.

Usage (from the backend/ directory):
    python cli.py ingest --source aterio
    python -m cli ingest --source seed_coverage
    python cli.py verify
"""
import asyncio
import logging
import sys

import click

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("cli")


@click.group()
def cli():
    """Strategic Insights Tool CLI."""
    pass


# ---------------------------------------------------------------------------
# ingest command
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--source",
    required=True,
    type=click.Choice([
        "aterio",
        "edgar",
        "edgar_quarterly",
        "epa_echo",
        "tceq",
        "va_permits",
        "iowa_permits",
        "ohio_permits",
        "socrata_ny",
        "pjm",
        "ercot",
        "miso",
        "press_releases",
        "anomaly_detect",
        "parse_permits",
        "seed",
        "seed_companies",
        "seed_coverage",
        "all_seeds",
    ]),
)
@click.option("--days-back", default=90, help="For EDGAR: how many days back to fetch")
@click.option("--limit", default=500, help="For parse_permits: max permits to process")
@click.option("--llm-cap", default=200, help="For parse_permits: max LLM calls")
def ingest(source: str, days_back: int, limit: int, llm_cap: int):
    """Run a one-time ingestion for the specified source."""
    asyncio.run(_run_ingest(source, days_back, limit, llm_cap))


async def _run_ingest(source: str, days_back: int, limit: int = 500, llm_cap: int = 200):
    from db.session import async_session_factory

    async with async_session_factory() as session:
        if source == "seed":
            from seed.canonical_companies import seed_companies
            from seed.coverage_seed import seed_coverage
            await seed_companies(session)
            await seed_coverage(session)
            await session.commit()
            logger.info("Seeded companies and coverage")

        elif source == "seed_companies":
            from seed.canonical_companies import seed_companies
            await seed_companies(session)
            await session.commit()
            logger.info("Canonical companies seeded.")

        elif source == "seed_coverage":
            from seed.coverage_seed import seed_coverage
            count = await seed_coverage(session)
            await session.commit()
            logger.info("Coverage data seeded (%d rows).", count)

        elif source == "all_seeds":
            from seed.canonical_companies import seed_companies
            from seed.coverage_seed import seed_coverage
            await seed_companies(session)
            await session.commit()
            count = await seed_coverage(session)
            await session.commit()
            logger.info("All seeds completed (%d coverage rows).", count)

        elif source == "aterio":
            # Ensure companies exist before running the Aterio adapter
            from sqlalchemy import select, func
            from db.models import Company
            count = (await session.execute(select(func.count(Company.id)))).scalar()
            if count == 0:
                logger.info("No companies found, seeding first...")
                from seed.canonical_companies import seed_companies
                await seed_companies(session)
                await session.commit()

            import os
            from ingestion.aterio import AterioAdapter
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            adapter = AterioAdapter(
                csv_path=os.path.join(base, "datasets", "data_center_inventory_20260428.csv"),
                events_xlsx_path=os.path.join(
                    base, "datasets", "Data Centers's Data Dictionary (Data Product).xlsx"
                ),
                energy_xlsx_path=os.path.join(
                    base, "datasets", "Energy Project Inventory Data Sample.xlsx"
                ),
            )
            result = await adapter.run(session)
            await session.commit()
            logger.info("Aterio ingestion complete: %s", result)

        elif source == "edgar":
            from ingestion.edgar import EdgarAdapter
            adapter = EdgarAdapter()
            result = await adapter.run(session, days_back=days_back)
            await session.commit()
            logger.info("EDGAR ingestion complete: %s", result)

        elif source == "epa_echo":
            from ingestion.epa_echo import EpaEchoAdapter
            adapter = EpaEchoAdapter()
            result = await adapter.run(session)
            await session.commit()
            logger.info("EPA ECHO ingestion complete: %s", result)

        elif source == "tceq":
            from ingestion.permits_state.tceq import TceqAdapter
            adapter = TceqAdapter()
            result = await adapter.run(session)
            await session.commit()
            logger.info("TCEQ ingestion complete: %s", result)

        elif source == "va_permits":
            from ingestion.permits_state.va_open_data import VaOpenDataAdapter
            adapter = VaOpenDataAdapter()
            result = await adapter.run(session)
            await session.commit()
            logger.info("VA permits ingestion complete: %s", result)

        elif source == "socrata_ny":
            from ingestion.permits_state.socrata import SocrataPermitAdapter, SOCRATA_INSTANCES
            # Run every NY dataset configured in STATE_DATASETS (Title V,
            # State Facility, CATS) sequentially under a shared source label.
            ny_cfgs = [c for c in SOCRATA_INSTANCES if c.state_code == "NY"]
            results = []
            for cfg in ny_cfgs:
                adapter = SocrataPermitAdapter(cfg)
                result = await adapter.run(session)
                await session.commit()
                results.append(result)
                logger.info("NY Socrata (%s) complete: %s", cfg.dataset_id, result)
            logger.info("NY Socrata aggregate: %d datasets run", len(results))

        elif source == "pjm":
            from ingestion.iso.pjm import PjmIsoAdapter
            adapter = PjmIsoAdapter()
            result = await adapter.run(session)
            await session.commit()
            logger.info("PJM ingestion complete: %s", result)

        elif source == "ercot":
            from ingestion.iso.ercot import ErcotIsoAdapter
            adapter = ErcotIsoAdapter()
            result = await adapter.run(session)
            await session.commit()
            logger.info("ERCOT ingestion complete: %s", result)

        elif source == "miso":
            from ingestion.iso.miso import MisoIsoAdapter
            adapter = MisoIsoAdapter()
            result = await adapter.run(session)
            await session.commit()
            logger.info("MISO ingestion complete: %s", result)

        elif source == "iowa_permits":
            from ingestion.permits_state.iowa import IowaPermitAdapter
            adapter = IowaPermitAdapter()
            result = await adapter.run(session)
            await session.commit()
            logger.info("Iowa permits ingestion complete: %s", result)

        elif source == "ohio_permits":
            from ingestion.permits_state.ohio import OhioPermitAdapter
            adapter = OhioPermitAdapter()
            result = await adapter.run(session)
            await session.commit()
            logger.info("Ohio permits ingestion complete: %s", result)

        elif source == "edgar_quarterly":
            from agents.edgar_extractor import run_llm_extraction_quarterly
            result = await run_llm_extraction_quarterly(session, days_back=days_back)
            await session.commit()
            logger.info("EDGAR quarterly (10-K + 10-Q) ingestion complete: %s", result)

        elif source == "press_releases":
            from ingestion.press_releases import PressReleaseAdapter
            adapter = PressReleaseAdapter()
            result = await adapter.run(session)
            await session.commit()
            logger.info("Press release ingestion complete: %s", result)

        elif source == "anomaly_detect":
            from agents.anomaly_detector import detect_anomalies
            result = await detect_anomalies(session)
            await session.commit()
            logger.info("Anomaly detection complete: %s", result)

        elif source == "parse_permits":
            from ingestion.bulk_pdf_runner import run_bulk_pdf_parse
            result = await run_bulk_pdf_parse(session, limit=limit, llm_call_cap=llm_cap)
            await session.commit()
            logger.info("Bulk PDF parse complete: %s", result)


# ---------------------------------------------------------------------------
# vendor-supply-extract command (Phase 2 — Supplier Insights AC3 + AC5)
#
# Runs the parallel vendor-supply LLM extractor over EDGAR-eligible vendors
# (the curated registry in agents/edgar_agent.py::VENDOR_FILERS, restricted
# to entries with a CIK and non-empty form_types). Distinct from the power
# extractor (`ingest --source edgar_quarterly`): rows land with
# pillar='vendor_supply' and parser_version='vendor_supply_v1'.
# ---------------------------------------------------------------------------

@cli.command(name="vendor-supply-extract")
@click.option(
    "--since",
    default="2024-01-01",
    help="ISO date floor for filings (default 2024-01-01).",
)
@click.option(
    "--limit",
    default=None,
    type=int,
    help="Cap on distinct accessions across all vendors (default no cap).",
)
def vendor_supply_extract(since: str, limit: int | None):
    """Run the LLM vendor-supply extractor over EDGAR-eligible vendors."""
    asyncio.run(_run_vendor_supply_extract(since, limit))


async def _run_vendor_supply_extract(since: str, limit: int | None):
    from db.session import async_session_factory
    from agents.vendor_supply_extractor import run_vendor_supply_extraction

    async with async_session_factory() as session:
        counters = await run_vendor_supply_extraction(
            session, since=since, limit=limit
        )
    print("vendor-supply-extract counters:")
    for k, v in counters.items():
        print(f"  {k}: {v}")


# ---------------------------------------------------------------------------
# verify command
# ---------------------------------------------------------------------------

@cli.command()
def verify():
    """Run verification queries after ingestion."""
    asyncio.run(_run_verify())


async def _run_verify():
    from db.session import async_session_factory
    from sqlalchemy import text

    queries = [
        ("Sites count", "SELECT COUNT(*) FROM sites"),
        ("Events count", "SELECT COUNT(*) FROM events"),
        ("Energy projects count", "SELECT COUNT(*) FROM energy_projects"),
        ("Companies count", "SELECT COUNT(*) FROM companies"),
        (
            "Role distribution",
            "SELECT role, COUNT(*) FROM site_company_associations GROUP BY role ORDER BY COUNT(*) DESC",
        ),
        (
            "Coverage top 20",
            "SELECT pillar, state_code, coverage_status, record_count "
            "FROM data_coverage ORDER BY record_count DESC LIMIT 20",
        ),
        ("EDGAR extractions", "SELECT COUNT(*) FROM edgar_extractions"),
    ]

    async with async_session_factory() as session:
        for label, query in queries:
            try:
                result = await session.execute(text(query))
                rows = result.fetchall()
                print(f"\n{label}:")
                for row in rows:
                    print(f"  {row}")
            except Exception as e:
                print(f"\n{label}: ERROR - {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
