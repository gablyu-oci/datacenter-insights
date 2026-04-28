"""
Source-agnostic ingestion adapter contract per section 2 of pipeline architecture.

Every data-source adapter (EDGAR, Aterio CSV, EIA, permits, etc.) must
implement this protocol so the orchestrator can call fetch -> normalize ->
upsert -> write_lineage -> write_coverage in a uniform loop.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DataSourceAdapter(Protocol):
    """Every adapter must implement this interface."""

    # ---- identity ----------------------------------------------------------

    @property
    def adapter_name(self) -> str:
        """Human-readable name, e.g. 'edgar_8k'."""
        ...

    @property
    def adapter_id(self) -> str:
        """Unique slug used in ingestion_runs.adapter_name, e.g. 'edgar_8k'."""
        ...

    @property
    def adapter_version(self) -> str:
        """SemVer string tracked in ingestion_runs.adapter_version."""
        ...

    @property
    def pillar(self) -> str:
        """Data pillar this adapter contributes to (e.g. 'energy_deals')."""
        ...

    @property
    def source_id(self) -> str:
        """Canonical source identifier written to lineage rows."""
        ...

    @property
    def declared_status(self) -> str:
        """Self-reported readiness: 'live', 'beta', 'stub'."""
        ...

    @property
    def coverage_scope(self) -> str:
        """Geographic or topical scope, e.g. 'federal' or 'state:TX'."""
        ...

    # ---- pipeline stages ---------------------------------------------------

    async def fetch(self) -> list[dict]:
        """Pull raw records from the upstream source (API, file, scrape)."""
        ...

    async def normalize(self, raw: list[dict]) -> list[dict]:
        """Transform raw dicts into the canonical shape expected by upsert."""
        ...

    async def upsert(self, session, records: list[dict]) -> int:
        """
        Persist normalised records into the target table(s).

        Parameters
        ----------
        session : AsyncSession
            Active SQLAlchemy async session (caller manages commit/rollback).
        records : list[dict]
            Output of normalize().

        Returns
        -------
        int
            Number of rows written or updated.
        """
        ...

    async def write_lineage(self, session, run_id: int, record_count: int) -> None:
        """Write per-record audit rows into data_lineage."""
        ...

    async def write_coverage(self, session) -> None:
        """Upsert a row into data_coverage for this adapter's scope."""
        ...
