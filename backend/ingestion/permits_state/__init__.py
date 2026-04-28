"""
State-level permit adapters for building permits and air quality permits.

Each adapter targets a specific state data portal and writes to the
generator_permits table.  Coverage entries are per-state.
"""
from __future__ import annotations

from ingestion.permits_state.va_open_data import VaOpenDataAdapter
from ingestion.permits_state.socrata import SocrataPermitAdapter, SOCRATA_INSTANCES
from ingestion.permits_state.tceq import TceqAdapter

__all__ = [
    "VaOpenDataAdapter",
    "SocrataPermitAdapter",
    "SOCRATA_INSTANCES",
    "TceqAdapter",
]
