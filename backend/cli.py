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
        "epa_echo",
        "tceq",
        "va_permits",
        "socrata_ny",
        "pjm",
        "seed",
        "seed_companies",
        "seed_coverage",
        "all_seeds",
    ]),
)
@click.option("--days-back", default=90, help="For EDGAR: how many days back to fetch")
def ingest(source: str, days_back: int):
    """Run a one-time ingestion for the specified source."""
    asyncio.run(_run_ingest(source, days_back))


async def _run_ingest(source: str, days_back: int):
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
