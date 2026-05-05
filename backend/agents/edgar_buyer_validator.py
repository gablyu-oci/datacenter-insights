"""Buyer/seller raw-string validator for EDGAR extractions.

Filters out common LLM-extraction failure modes BEFORE the value reaches
the database:
  * common nouns ("total", "various", "data center", "ai")
  * XBRL segment labels Intel-style ("DCAI", "Intel Foundry")
  * XML noise ("<...>", angle brackets)
  * empty / null / whitespace
  * overly-short single-token strings without capitalization

The validator is intentionally conservative: a value that survives the
rejection list is still RAW (the canonicalization layer in
entity_resolution.py handles the company-table mapping). The companion
column `rejected_buyer_raw` preserves the original LLM output so an audit
can answer "what did the model actually emit?".

Public API:
    validate_buyer(raw, known_company_names) -> tuple[str | None, str | None]
        Returns (clean_value, rejection_reason).
        clean_value is None when rejected; rejection_reason is None when accepted.
"""
from __future__ import annotations

import re
from typing import Iterable  # noqa: F401  -- intentionally exposed for typing callers

# Common nouns that LLMs hallucinate as buyer/seller names.
_REJECTED_NOUNS = {
    "total", "other", "various", "mixed", "data center", "ai", "cloud",
    "foundry", "networking", "unknown", "n/a", "none", "tbd",
}

# XBRL segment labels — Intel-style "Data Center & AI", "Intel Foundry"
# and similar internal-segment names that aren't legal-entity buyers.
_SEGMENT_RE = re.compile(
    r"^(Data Center|Advanced Products|Semiconductor Systems|DCAI|DSG|CCG|"
    r"NEX|Client Computing|Networking|Foundry|Intel Foundry|Intel-DCAI)$",
    re.IGNORECASE,
)

# Tickers that pass through even without a longer-form company name match
# (the canonicalizer downstream handles ticker -> company resolution).
_KNOWN_TICKERS = {
    "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "META", "ORCL", "NVDA",
    "AMD", "INTC", "TSM", "IBM", "ASML", "AVGO",
}


def validate_buyer(raw, known_company_names) -> tuple[str | None, str | None]:
    """Return (clean, rejection_reason). clean is None when rejected.

    Args:
      raw: the LLM-emitted string (may be None / empty / nonsense).
      known_company_names: iterable of canonical_name strings already in
                           the companies table; used as an allow-list so
                           legitimate matches always pass even if their
                           form is short.

    Returns:
      (clean_value_or_None, rejection_reason_or_None)
    """
    if raw is None:
        return None, "null_input"
    s = str(raw).strip()
    if not s:
        return None, "empty"
    if "<" in s or ">" in s:
        return None, "xml_noise"
    if s.lower() in _REJECTED_NOUNS:
        return None, "common_noun"
    if _SEGMENT_RE.match(s):
        return None, "xbrl_segment_label"
    # If we recognize it in the canonical companies list, accept directly.
    if any(s.lower() == k.lower() for k in known_company_names):
        return s, None
    if s.upper() in _KNOWN_TICKERS:
        return s, None
    # Heuristic gate: must contain ≥1 capital letter AND (≥2 words OR ≥4 chars).
    has_cap = any(c.isupper() for c in s)
    word_count = len(s.split())
    if not has_cap:
        return None, "no_capital_letter"
    if word_count < 2 and len(s) < 4:
        return None, "too_short"
    return s, None
