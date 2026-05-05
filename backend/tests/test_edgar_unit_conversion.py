"""MWh-to-MW unit-conversion regression tests (EDGAR-2).

The earlier prompt computed `200_000_000 / 8760 = 22831 MW` from Amazon's
"200 million MWh over 16 years" disclosure — wrong because it skipped
dividing by years. The corrected algorithm divides by both years AND
8760 hours, yielding ~1430 MW continuous-equivalent.

These tests:
  1. Lock the corrected example into the LLM prompt (SYSTEM_PREAMBLE).
  2. Verify the buggy 22831 number is NOT mentioned anywhere.
  3. Pin the arithmetic in `_mine_amazon_energy_commitment_async`.
  4. Verify the `methodology` field round-trips through `_persist_extraction`.
"""
from __future__ import annotations

import inspect

import pytest

from agents.edgar_extractor import (
    EDGAR_SCHEMA,
    SYSTEM_PREAMBLE,
    compute_canonical_deal_id,
)


# ---------------------------------------------------------------------------
# Pure arithmetic checks
# ---------------------------------------------------------------------------


def test_lifetime_conversion_formula():
    """200M MWh lifetime / 16 yr / 8760 h ≈ 1426.94 MW continuous-eq."""
    mwh_lifetime = 200_000_000
    years = 16
    mw = mwh_lifetime / years / 8760
    # Both rounding strategies that the prompt tolerates:
    assert round(mw) in {1427}
    # 200M / 16 / 8760 ≈ 1426.94
    assert 1420 < mw < 1430


def test_buggy_formula_produces_wrong_answer():
    """Regression: dividing by 8760 alone (no /years) gives the OLD bug."""
    bug = int(200_000_000 / 8760)
    assert bug == 22831  # the historical wrong answer
    # And the fixed answer is nowhere near it.
    fixed = int(200_000_000 / 16 / 8760)
    assert fixed != bug
    assert abs(fixed - 1426) < 5


def test_amazon_amazon_snippet_arithmetic():
    """`int(200 * 1_000_000 / 16 / 8760)` is the literal in edgar_agent.py."""
    computed = int(200 * 1_000_000 / 16 / 8760)
    # 200_000_000 / 16 = 12_500_000; / 8760 ≈ 1426.94 -> int = 1426
    assert computed == 1426


# ---------------------------------------------------------------------------
# Prompt content lock — corrected example present, buggy example absent
# ---------------------------------------------------------------------------


def test_prompt_contains_corrected_amazon_example():
    """The fixed prompt must reference ~1.43 GW (or 1430 MW) and 200M MWh / 16 yr."""
    text = SYSTEM_PREAMBLE
    # Either "1.43 GW" or "1430 MW" should show up in the worked example.
    assert "1.43 GW" in text or "1430 MW" in text or "1,430 MW" in text, (
        "corrected Amazon worked example missing from SYSTEM_PREAMBLE"
    )
    assert "200 million" in text or "200M MWh" in text or "200,000,000" in text
    # The 16-year duration is part of the example.
    assert "16 year" in text or "16 yr" in text


def test_prompt_does_not_contain_buggy_22831():
    """The wrong number must not appear in the prompt anywhere."""
    assert "22831" not in SYSTEM_PREAMBLE
    assert "22,831" not in SYSTEM_PREAMBLE


def test_prompt_states_8760_correctly():
    """1 MW continuous = 8760 MWh/year, NOT 8.76 (a unit error)."""
    assert "8760" in SYSTEM_PREAMBLE or "8,760" in SYSTEM_PREAMBLE


# ---------------------------------------------------------------------------
# Schema lock — methodology is a required field
# ---------------------------------------------------------------------------


def test_methodology_field_in_schema():
    assert "methodology" in EDGAR_SCHEMA["properties"]
    assert "methodology" in EDGAR_SCHEMA["required"]
    spec = EDGAR_SCHEMA["properties"]["methodology"]
    assert spec.get("maxLength") == 200


# ---------------------------------------------------------------------------
# edgar_agent._mine_amazon_energy_commitment_async — source-string lock.
# ---------------------------------------------------------------------------


def test_mine_amazon_source_uses_correct_formula():
    """The note string in _mine_amazon_energy_commitment_async must
    divide by both `16` AND `8760` (not just 8760).
    """
    from agents.edgar_agent import _mine_amazon_energy_commitment_async

    src = inspect.getsource(_mine_amazon_energy_commitment_async)
    # Look for "/ 16 / 8760" or "/16/8760" — the corrected divide chain.
    cleaned = src.replace(" ", "")
    assert "/16/8760" in cleaned, (
        "expected the corrected '/ 16 / 8760' formula in the Amazon note. "
        "The bug was '/ 8760' alone."
    )


# ---------------------------------------------------------------------------
# methodology field round-trip through _persist_extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_methodology_truncated_to_200_chars(monkeypatch):
    """`methodology` is sliced to 200 chars before insert."""
    from agents import edgar_extractor as ext

    captured: dict = {}

    class _FakeResult:
        def fetchone(self):
            return (0, 0)
        def fetchall(self):
            return []

    class _FakeSession:
        async def execute(self, stmt, params=None):
            # First call: SELECT MAX(appearance_count). Second call: INSERT.
            if params and "methodology" in params:
                captured.update(params)
            return _FakeResult()

    long_methodology = "X" * 500
    result = {
        "buyer": "Microsoft",
        "seller": "Constellation Energy",
        "capacity_mw": 835,
        "energy_source": "nuclear",
        "headline": "Microsoft signs 835 MW PPA",
        "methodology": long_methodology,
        "signing_date": "2024-09-20",
    }
    out = await ext._persist_extraction(
        _FakeSession(),
        accession="0000000000-00-000000",
        cik_padded="0000000000",
        form_type="8-K",
        filing_date=None,
        edgar_url="https://www.sec.gov/x",
        result=result,
        excerpt_fallback="...",
        confidence=0.9,
        known_company_names={"Microsoft", "Constellation Energy"},
    )
    assert out["ok"] is True
    assert captured.get("methodology") is not None
    assert len(captured["methodology"]) == 200
