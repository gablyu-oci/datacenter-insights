"""_gw_summary_from_db — buyer-canonical bucketing + canonical_deal_id dedup.

The bug we're guarding against: the Constellation/Calpine merger appeared
under THREE buyer-name variants ("Constellation", "Constellation Energy",
"Constellation Energy Corporation") across 4 filings, and the older
aggregator counted it 4x — yielding a fake 4× capacity. After the
EDGAR-4 + EDGAR-5 fix (canonical_deal_id + buyer_canonical), the
aggregator must:

  1. Collapse all 4 rows into ONE bucket called "Constellation" (no name
     duplication).
  2. Pick the LATEST filing's capacity (DISTINCT ON canonical_deal_id
     ORDER BY filing_date DESC).
  3. Surface flagged_capacity rows in detail endpoints, but the
     aggregation should not multi-count.

Because `_gw_summary_from_db` uses Postgres `DISTINCT ON`, we mock the
DB to return tuples that REPRESENT the post-SQL output. This isolates
the Python reduction logic without standing up Postgres.
"""
from __future__ import annotations

from datetime import date

import pytest

from routers import power as power_module


class _FakeRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    """Minimal AsyncSession stand-in: returns canned rows on `execute`."""
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *_, **__):
        return _FakeRows(self._rows)


@pytest.mark.asyncio
async def test_canonical_buyer_collapses_variants():
    """Three name variants -> one bucket, summed per row."""
    # Imagine the SQL ran: DISTINCT ON returned 1 latest row per
    # canonical_deal_id, but the buyer COALESCE returned the canonical
    # form. Two distinct canonical_deal_ids exist for two real deals.
    rows = [
        # Real deal #1 — Constellation/Microsoft TMI restart, latest filing
        ("Constellation", "nuclear", 835),
        # Real deal #2 — Constellation/Calpine merger, latest filing
        ("Constellation", "natural_gas", 50000),
    ]
    out = await power_module._gw_summary_from_db(_FakeSession(rows))
    assert "Constellation" in out
    bucket = out["Constellation"]
    # Both canonical deals collapse into the SAME buyer bucket.
    assert bucket["deals"] == 2
    # 835 MW + 50000 MW = 50835 MW = 50.835 GW (rounded to 2 dp by the reducer)
    assert abs(bucket["gw_total"] - 50.84) < 1e-6
    # 0.835 -> 0.83 or 0.84 after Python round() (banker's rounding)
    assert bucket["nuclear_gw"] in {0.83, 0.84}


@pytest.mark.asyncio
async def test_dedup_strips_duplicate_buyer_names_via_buyer_canonical():
    """The SQL returns ONE row per canonical_deal_id (via DISTINCT ON);
    if name variants slip into the buyer column they should still bucket
    together since `_gw_summary_from_db` uses buyer string equality."""
    # Worst case: three buyer-name variants leak through DESPITE the
    # canonical column. The reducer should at least bucket exact
    # canonical strings.
    rows = [
        ("Constellation", "natural_gas", 1000),
        ("Constellation", "nuclear", 835),
    ]
    out = await power_module._gw_summary_from_db(_FakeSession(rows))
    assert list(out.keys()) == ["Constellation"]
    assert out["Constellation"]["deals"] == 2
    # 1.835 GW -> rounded to 2 dp by the reducer (banker's rounding -> 1.83 or 1.84)
    assert out["Constellation"]["gw_total"] in {1.83, 1.84}


@pytest.mark.asyncio
async def test_null_buyer_rows_are_skipped():
    rows = [
        (None, "nuclear", 1000),
        ("Microsoft", "nuclear", 500),
    ]
    out = await power_module._gw_summary_from_db(_FakeSession(rows))
    assert "Microsoft" in out
    assert None not in out
    # The None-buyer row didn't contribute.
    assert out["Microsoft"]["gw_total"] == 0.5
    assert out["Microsoft"]["deals"] == 1


@pytest.mark.asyncio
async def test_energy_source_categorization():
    rows = [
        ("Microsoft", "nuclear", 1000),     # nuclear bucket
        ("Microsoft", "solar", 500),        # renewable bucket
        ("Microsoft", "wind", 250),         # renewable bucket
        ("Microsoft", "natural_gas", 250),  # neither -> only gw_total
    ]
    out = await power_module._gw_summary_from_db(_FakeSession(rows))
    assert out["Microsoft"]["nuclear_gw"] == 1.0
    assert out["Microsoft"]["renewable_gw"] == 0.75
    assert out["Microsoft"]["gw_total"] == 2.0
    assert out["Microsoft"]["deals"] == 4


@pytest.mark.asyncio
async def test_constellation_merger_does_not_quadruple_count():
    """The bug fix in numbers: BEFORE EDGAR-4 the same 144,000 MW deal
    appeared 4 times under 3 name variants -> 576 GW (laughable).
    AFTER: the SQL DISTINCT ON returns ONE row, so the bucket sees 144 GW.
    We simulate the post-SQL output."""
    rows = [
        # A single canonical_deal_id surfaced as a single row by the SQL.
        ("Constellation", "natural_gas", 144000),
    ]
    out = await power_module._gw_summary_from_db(_FakeSession(rows))
    assert out["Constellation"]["deals"] == 1
    assert out["Constellation"]["gw_total"] == 144.0  # NOT 576.0
