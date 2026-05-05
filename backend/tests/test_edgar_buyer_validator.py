"""Exhaustive coverage for agents.edgar_buyer_validator.validate_buyer.

The validator filters LLM-extraction failure modes (common nouns, XBRL
segment labels, XML noise, empty/null, too-short tokens) BEFORE they
reach the database. These tests lock the rejection contract so future
prompt drift can't silently regress the cleanup layer.
"""
from __future__ import annotations

import pytest

from agents.edgar_buyer_validator import validate_buyer


# A representative canonical-name allow-list. The validator should accept
# any string whose lowercase appears here regardless of length / shape.
KNOWN = {
    "Microsoft",
    "Constellation Energy",
    "Constellation Energy Corporation",
    "Amazon Web Services",
    "Vistra",
}


# ---------------------------------------------------------------------------
# Common-noun rejections
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "Total",
        "Other",
        "Various",
        "Mixed",
        "Data Center",
        "AI",
        "Cloud",
        "Foundry",
    ],
)
def test_common_nouns_are_rejected(raw):
    clean, reason = validate_buyer(raw, KNOWN)
    assert clean is None, f"expected {raw!r} to be rejected, got {clean!r}"
    # Either common_noun or xbrl_segment_label is acceptable; the
    # contract is that the value is rejected and a reason is given.
    assert reason in {"common_noun", "xbrl_segment_label"}, (
        f"unexpected reason {reason!r} for {raw!r}"
    )


# ---------------------------------------------------------------------------
# XBRL segment labels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "DCAI",
        "DSG",
        "CCG",
        "NEX",
        "Client Computing",
        "Networking",
        "Foundry",
        "Advanced Products",
        "Semiconductor Systems",
    ],
)
def test_xbrl_segment_labels_are_rejected(raw):
    clean, reason = validate_buyer(raw, KNOWN)
    assert clean is None, f"expected {raw!r} to be rejected"
    assert reason in {"xbrl_segment_label", "common_noun"}, (
        f"unexpected reason {reason!r} for {raw!r}"
    )


# ---------------------------------------------------------------------------
# XML noise
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "Microsoft<br/>",
        ">company<",
        "<Vistra>",
        "Amazon</p>",
    ],
)
def test_xml_noise_is_rejected(raw):
    clean, reason = validate_buyer(raw, KNOWN)
    assert clean is None
    assert reason == "xml_noise"


# ---------------------------------------------------------------------------
# Empty / whitespace / None
# ---------------------------------------------------------------------------


def test_none_input_is_rejected():
    clean, reason = validate_buyer(None, KNOWN)
    assert clean is None
    assert reason == "null_input"


@pytest.mark.parametrize("raw", ["", "   ", "\t", "\n  \n"])
def test_empty_or_whitespace_is_rejected(raw):
    clean, reason = validate_buyer(raw, KNOWN)
    assert clean is None
    assert reason == "empty"


# ---------------------------------------------------------------------------
# Valid corporate names (positive cases)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "Microsoft",
        "Constellation Energy",
        "Constellation Energy Corporation",
        "Amazon Web Services",
    ],
)
def test_valid_corporate_names_accepted(raw):
    clean, reason = validate_buyer(raw, KNOWN)
    assert clean == raw, f"expected {raw!r} to pass through, got {clean!r}"
    assert reason is None


# ---------------------------------------------------------------------------
# Known tickers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["MSFT", "AAPL", "AMZN", "ORCL"])
def test_known_tickers_pass(raw):
    clean, reason = validate_buyer(raw, KNOWN)
    assert clean == raw
    assert reason is None


# ---------------------------------------------------------------------------
# Allow-list semantics — case-insensitive lookup against known_company_names
# ---------------------------------------------------------------------------


def test_known_company_match_is_case_insensitive():
    # Lowercase form would normally be rejected by the cap-letter heuristic;
    # the canonical allow-list should rescue it.
    known = {"My Tiny Co"}
    # Exact match through allow-list (different case)
    clean, reason = validate_buyer("MY TINY CO", known)
    assert clean == "MY TINY CO"
    assert reason is None


def test_unknown_short_lowercase_string_rejected():
    clean, reason = validate_buyer("xyz", KNOWN)
    assert clean is None
    # Either no_capital_letter or too_short — both are valid rejections.
    assert reason in {"no_capital_letter", "too_short"}


# ---------------------------------------------------------------------------
# Edge cases: too-short, no-capital
# ---------------------------------------------------------------------------


def test_single_lowercase_char_rejected():
    clean, reason = validate_buyer("a", KNOWN)
    assert clean is None
    assert reason == "no_capital_letter"


def test_lowercase_phrase_rejected():
    clean, reason = validate_buyer("lowercase no caps", KNOWN)
    assert clean is None
    assert reason == "no_capital_letter"


def test_short_capitalized_token_rejected_as_too_short():
    # 1 word, len < 4, has cap -> rejected as too_short
    clean, reason = validate_buyer("Ab", KNOWN)
    assert clean is None
    assert reason == "too_short"


def test_two_word_capitalized_short_passes():
    # 2 words always pass the gate even if individually short
    clean, reason = validate_buyer("Co Ab", KNOWN)
    assert clean == "Co Ab"
    assert reason is None


def test_whitespace_around_valid_name_is_stripped():
    clean, reason = validate_buyer("  Microsoft  ", KNOWN)
    assert clean == "Microsoft"
    assert reason is None
