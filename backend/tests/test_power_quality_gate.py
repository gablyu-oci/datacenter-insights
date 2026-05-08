"""Unit tests for the power-announcements quality gate + bucket key.

Covers :func:`routers.power.passes_quality_gate` and
:func:`routers.power.bucket_key`. No DB touch — these are pure functions.
"""
from __future__ import annotations

import pytest

from routers.power import bucket_key, passes_quality_gate


# ---------------------------------------------------------------------------
# passes_quality_gate
# ---------------------------------------------------------------------------


def _row(**overrides):
    """Build a minimally-valid SEC-row dict with sane defaults."""
    base = {
        "buyer": "Microsoft",
        "headline": "Microsoft signs 1,200 MW solar PPA with Constellation",
        "capacity_mw": 1200,
        "energy_source": "solar",
        "source_url": "https://www.sec.gov/Archives/edgar/data/000/foo.htm",
        "announced_date": "2026-01-15",
    }
    base.update(overrides)
    return base


def test_passes_quality_gate_happy_path():
    ok, reason = passes_quality_gate(_row())
    assert ok is True
    assert reason is None


@pytest.mark.parametrize(
    "headline",
    [
        "20549 FORM 10-Q QUARTERLY REPORT",
        "FORM 10-K Annual Report Pursuant",
        "UNITED STATES SECURITIES AND EXCHANGE COMMISSION",
        "WASHINGTON, D.C. 20549",
        "SECURITIES AND EXCHANGE COMMISSION Washington",
        "  20549 FORM 10- Q QUARTERLY",       # leading whitespace
        "form 10-q quarterly report",         # case-insensitive
    ],
)
def test_passes_quality_gate_rejects_boilerplate_prefixes(headline):
    ok, reason = passes_quality_gate(_row(headline=headline))
    assert ok is False
    assert reason == "boilerplate"


@pytest.mark.parametrize(
    "headline",
    [
        '{"headline": "GF Trusted Foundry supply chain", "revenue_usd": 6791000000.0}',
        "[1, 2, 3, 'parsed list output']",
    ],
)
def test_passes_quality_gate_rejects_json_blob(headline):
    ok, reason = passes_quality_gate(_row(headline=headline))
    assert ok is False
    assert reason == "json_shaped"


@pytest.mark.parametrize(
    "headline",
    [
        "Tiny",                                  # too short
        "x" * 19,                                # 19 chars — under bound
        "x" * 301,                               # over bound
    ],
)
def test_passes_quality_gate_rejects_bad_length(headline):
    ok, reason = passes_quality_gate(_row(headline=headline))
    assert ok is False
    assert reason in {"headline_length", "no_headline"}


@pytest.mark.parametrize(
    "buyer",
    ["Trusted Foundry", "the Venture", "Company", "the Company", "the Issuer", "Registrant"],
)
def test_passes_quality_gate_rejects_noise_buyer(buyer):
    ok, reason = passes_quality_gate(_row(buyer=buyer))
    assert ok is False
    assert reason == "noise_buyer"


@pytest.mark.parametrize("buyer", [None, "", "   "])
def test_passes_quality_gate_rejects_empty_buyer(buyer):
    ok, reason = passes_quality_gate(_row(buyer=buyer))
    assert ok is False
    assert reason == "no_buyer"


def test_passes_quality_gate_requires_at_least_one_signal():
    # No MW, no energy_source, no source_url -> reject
    ok, reason = passes_quality_gate(
        _row(capacity_mw=None, energy_source=None, source_url=None)
    )
    assert ok is False
    assert reason == "no_signal"


def test_passes_quality_gate_zero_mw_is_not_a_signal():
    # capacity_mw must be > 0 to count
    ok, reason = passes_quality_gate(
        _row(capacity_mw=0, energy_source="", source_url="")
    )
    assert ok is False
    assert reason == "no_signal"


def test_passes_quality_gate_one_signal_is_enough():
    # Only source_url present, no MW, no energy_source -> still passes
    ok, _reason = passes_quality_gate(
        _row(capacity_mw=None, energy_source=None, source_url="https://sec.gov/x")
    )
    assert ok is True


def test_passes_quality_gate_buyer_normalisation_keeps_inc_suffix():
    # "Meta Platforms, Inc." should pass — corporate suffixes are NOT
    # noise. Only the literal noise list rejects.
    ok, _reason = passes_quality_gate(_row(buyer="Meta Platforms, Inc."))
    assert ok is True


# ---------------------------------------------------------------------------
# bucket_key
# ---------------------------------------------------------------------------


def test_bucket_key_collapses_corporate_suffixes():
    a = bucket_key(_row(buyer="Meta Platforms, Inc.", announced_date="2026-01-15", energy_source="nuclear"))
    b = bucket_key(_row(buyer="Meta", announced_date="2026-02-28", energy_source="Nuclear (SMR)"))
    # Same buyer (Meta), same Q1 2026, same nuclear bucket
    assert a == b


def test_bucket_key_respects_quarter_boundaries():
    a = bucket_key(_row(buyer="Microsoft", announced_date="2026-03-31", energy_source="solar"))
    b = bucket_key(_row(buyer="Microsoft", announced_date="2026-04-01", energy_source="solar"))
    # Different quarters — must be different buckets
    assert a != b


def test_bucket_key_normalises_energy_source():
    a = bucket_key(_row(energy_source="Natural Gas"))
    b = bucket_key(_row(energy_source="natural_gas"))
    c = bucket_key(_row(energy_source="gas"))
    # All collapse to the "gas" bucket
    assert a == b == c


def test_bucket_key_handles_null_date():
    k = bucket_key(_row(announced_date=None))
    # Empty quarter token, but key still returns a 3-tuple
    assert isinstance(k, tuple)
    assert len(k) == 3
    assert k[1] == ""
