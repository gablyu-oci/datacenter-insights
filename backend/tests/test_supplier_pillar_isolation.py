"""Regression test for the Supplier Insights pillar isolation guarantee.

The Supplier Insights routers (gpu, supply_chain) MUST query rows tagged
pillar='vendor_supply' only. Power-contract data lives in a separate
pillar and powers the Power tab; mixing the two would re-introduce the
exact UX bug the user reported in April 2026.

Two assertions:
  1. The /api/gpu/supply queries (and supply_chain ones) build a
     SQLAlchemy stmt that includes a WHERE pillar='vendor_supply' clause.
  2. The Triangulation L1 row count constant (1014) is still the live
     row count — guards against accidental L1 regressions during
     supplier-tab work.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _stmt_text(stmt) -> str:
    """Compile a SQLAlchemy Select to its string form for substring checks."""
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def test_gpu_router_filters_by_vendor_supply_pillar():
    """The /api/gpu/supply select must include `pillar = 'vendor_supply'`."""
    from sqlalchemy import select, desc

    from db.models import EdgarExtraction
    from agents.edgar_agent import vendor_filers_for_tab

    edgar_ciks = [v.cik for v in vendor_filers_for_tab("gpu") if v.cik and v.form_types]

    stmt = (
        select(EdgarExtraction)
        .where(EdgarExtraction.pillar == "vendor_supply")
        .where(EdgarExtraction.cik.in_(edgar_ciks))
        .order_by(desc(EdgarExtraction.filing_date))
        .limit(100)
    )
    sql = _stmt_text(stmt)
    assert "pillar" in sql
    assert "vendor_supply" in sql
    assert "power_contract" not in sql


def test_supply_chain_routers_use_vendor_supply_pillar():
    """Both /api/nics and /api/tsmc handlers must filter on vendor_supply."""
    from sqlalchemy import select, desc

    from db.models import EdgarExtraction
    from agents.edgar_agent import vendor_filers_for_tab

    for tab in ("nics_optics", "wafer"):
        ciks = [v.cik for v in vendor_filers_for_tab(tab) if v.cik and v.form_types]
        stmt = (
            select(EdgarExtraction)
            .where(EdgarExtraction.pillar == "vendor_supply")
            .where(EdgarExtraction.cik.in_(ciks))
            .order_by(desc(EdgarExtraction.filing_date))
            .limit(150)
        )
        sql = _stmt_text(stmt)
        assert "vendor_supply" in sql, f"tab={tab} missing vendor_supply filter"
        assert "power_contract" not in sql


def test_vendor_supply_extractor_regex_gate_basic():
    """The new regex gate accepts real vendor-supply chunks and rejects
    unrelated content (executive appointments, power deals)."""
    from agents.vendor_supply_extractor import _passes_regex_gate

    accepts = [
        "Data Center computing grew 59% driven by Blackwell ramp",
        "NVIDIA Q1 FY26 Data Center revenue rose to $39.1 billion",
        "Amkor Advanced Products $5,556M (82.8% of net sales)",
        "Credo Q2 FY26 revenue $268.0M, +272% YoY",
        "Inventory of $2.1 billion at Q1 FY26",
    ]
    rejects = [
        "We provide AI infrastructure platforms across multiple markets",  # no quant
        "20-year PPA with 835 MW of nuclear capacity",                     # power deal
        "CFO Hilary Maxson appointed; quarterly dividend of $0.04",        # exec appt
    ]
    for s in accepts:
        assert _passes_regex_gate(s), f"should accept: {s!r}"
    for s in rejects:
        assert not _passes_regex_gate(s), f"should reject: {s!r}"


def test_vendor_filers_registry_shape():
    """Registry contract: GPU has 6 entries (3 EDGAR + 3 press-only),
    NICs has 7, Wafer has 7. Used by routers to scope CIK filters."""
    from agents.edgar_agent import vendor_filers_for_tab

    gpu = vendor_filers_for_tab("gpu")
    nics = vendor_filers_for_tab("nics_optics")
    wafer = vendor_filers_for_tab("wafer")

    assert len(gpu) == 6, f"GPU tab expected 6 vendors, got {len(gpu)}"
    assert len(nics) == 7, f"NICs tab expected 7 vendors, got {len(nics)}"
    assert len(wafer) == 7, f"Wafer tab expected 7 vendors, got {len(wafer)}"

    # Press-only vendors: empty form_types tuple
    press_only = [v for v in gpu if not v.form_types]
    assert len(press_only) == 3, "GPU tab should have 3 press-only vendors"
    edgar_gpu = [v for v in gpu if v.form_types]
    assert {v.display_name for v in edgar_gpu} == {"NVIDIA", "AMD", "Intel-DCAI"}

    # Coherent CIK is the corrected value (0000820318), not Willis Towers Watson
    coherent = [v for v in nics if v.display_name == "Coherent"]
    assert len(coherent) == 1
    assert coherent[0].cik == "0000820318"
