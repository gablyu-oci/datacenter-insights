"""compute_canonical_deal_id() — buyer/seller/capacity/quarter bucketing.

The canonical deal id is a 16-char SHA-1 prefix used to dedup multiple
filings reporting the SAME real-world deal (the Constellation/Microsoft
TMI restart appears in 8-Ks, 10-Qs, and 10-Ks). Bucketing rules:

  - buyer / seller   normalized via _normalize_party (corp-suffix strip)
  - capacity_mw      rounded to nearest 100 MW
  - signing_date     bucketed to calendar quarter

These tests pin the bucket boundaries.
"""
from __future__ import annotations

from datetime import date

import pytest

from agents.edgar_extractor import _normalize_party, compute_canonical_deal_id


# ---------------------------------------------------------------------------
# _normalize_party
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected_substring",
    [
        ("Microsoft Corporation", "microsoft"),
        ("Microsoft Corp.", "microsoft"),
        ("The Microsoft Co.", "microsoft"),
        ("Constellation Energy", "constellation"),
        ("Constellation Energy Corporation", "constellation"),
    ],
)
def test_normalize_party_strips_corp_noise(raw, expected_substring):
    out = _normalize_party(raw)
    # Whatever the canonical form is, "energy" / "corp" / "corporation" /
    # "the" / "co" should be gone.
    assert expected_substring in out
    for noise in ("corp", "corporation", "company"):
        assert noise not in out
    # Energy is stripped per the regex
    if "energy" in raw.lower():
        assert "energy" not in out


def test_normalize_party_handles_none_and_empty():
    assert _normalize_party(None) == ""
    assert _normalize_party("") == ""


# ---------------------------------------------------------------------------
# Variants of buyer name produce same key
# ---------------------------------------------------------------------------


def test_buyer_name_variants_collapse_to_same_key():
    """Constellation / Constellation Energy / Constellation Energy Corporation
    are the SAME buyer for dedup purposes. Same capacity, same quarter,
    same seller -> identical canonical_deal_id.
    """
    seller = "Microsoft"
    cap = 835
    d = date(2024, 9, 20)
    a = compute_canonical_deal_id("Constellation", seller, cap, d)
    b = compute_canonical_deal_id("Constellation Energy", seller, cap, d)
    c = compute_canonical_deal_id("Constellation Energy Corporation", seller, cap, d)
    assert a == b == c


# ---------------------------------------------------------------------------
# Capacity bucket (100 MW)
# ---------------------------------------------------------------------------


def test_capacity_within_100mw_bucket_collapses():
    """835 and 850 both round to 800 (nearest 100). They share a key."""
    d = date(2024, 9, 20)
    a = compute_canonical_deal_id("Constellation", "Microsoft", 835, d)
    b = compute_canonical_deal_id("Constellation", "Microsoft", 850, d)
    assert a == b


def test_capacity_in_different_bucket_yields_different_key():
    """835 -> 800; 950 -> 1000. Different keys."""
    d = date(2024, 9, 20)
    a = compute_canonical_deal_id("Constellation", "Microsoft", 835, d)
    b = compute_canonical_deal_id("Constellation", "Microsoft", 950, d)
    assert a != b


# ---------------------------------------------------------------------------
# Quarter bucket
# ---------------------------------------------------------------------------


def test_dates_in_same_quarter_collapse():
    """Sept 1 and Sept 30 both Q3 2024."""
    a = compute_canonical_deal_id("Constellation", "Microsoft", 835, date(2024, 9, 1))
    b = compute_canonical_deal_id("Constellation", "Microsoft", 835, date(2024, 9, 30))
    assert a == b


def test_quarter_boundary_sept_30_vs_oct_1_match():
    """signing_date is intentionally NOT in the key (see edgar_extractor.py:63)
    so the same deal restated across quarterly filings collapses to one ID."""
    a = compute_canonical_deal_id("Constellation", "Microsoft", 835, date(2024, 9, 30))
    b = compute_canonical_deal_id("Constellation", "Microsoft", 835, date(2024, 10, 1))
    assert a == b


def test_year_boundary_yields_same_key():
    """Same deal mention across calendar-year boundary still collapses — date
    is excluded from the hash by design."""
    a = compute_canonical_deal_id("Constellation", "Microsoft", 835, date(2024, 12, 31))
    b = compute_canonical_deal_id("Constellation", "Microsoft", 835, date(2025, 1, 1))
    assert a == b


# ---------------------------------------------------------------------------
# Buyer/seller order matters
# ---------------------------------------------------------------------------


def test_buyer_seller_order_matters():
    forward = compute_canonical_deal_id(
        "Microsoft", "Constellation Energy", 835, date(2024, 9, 20),
    )
    reverse = compute_canonical_deal_id(
        "Constellation Energy", "Microsoft", 835, date(2024, 9, 20),
    )
    assert forward != reverse


# ---------------------------------------------------------------------------
# Missing fields
# ---------------------------------------------------------------------------


def test_missing_buyer_returns_none():
    out = compute_canonical_deal_id(None, "Microsoft", 835, date(2024, 9, 20))
    assert out is None


def test_missing_seller_returns_key_with_unknown_bucket():
    out = compute_canonical_deal_id("Microsoft", None, 835, date(2024, 9, 20))
    assert out is not None
    assert isinstance(out, str)
    assert len(out) == 16


def test_missing_capacity_returns_key_with_unknown_bucket():
    out = compute_canonical_deal_id("Microsoft", "Constellation", None, date(2024, 9, 20))
    assert out is not None
    assert len(out) == 16


def test_missing_date_returns_key_with_unknown_bucket():
    out = compute_canonical_deal_id("Microsoft", "Constellation", 835, None)
    assert out is not None
    assert len(out) == 16


# ---------------------------------------------------------------------------
# Stability — identical inputs yield identical output
# ---------------------------------------------------------------------------


def test_canonical_deal_id_is_deterministic():
    args = ("Microsoft", "Constellation Energy", 835, date(2024, 9, 20))
    assert compute_canonical_deal_id(*args) == compute_canonical_deal_id(*args)
