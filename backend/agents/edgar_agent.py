"""
EDGAR Agent — fetches real 8-K filings from energy counterparties and hyperscalers.
Uses SEC EDGAR public APIs (no key required, rate-limit: 10 req/s).

Phase 0 fixes (H1 + H2):
  - H1: Replace 5 silent except Exception blocks with structured exceptions + logging
  - H2: Convert urllib.request -> httpx.AsyncClient (no blocking sync I/O on FastAPI event loop)
        Wrap edgartools sync calls via asyncio.to_thread() if needed.

Phase 1C will replace regex extraction with LLM (backend/llm/agents/edgar_extractor.py).

Phase 2 (Supplier Insights) — AC1 + AC4:
  * VENDOR_FILERS is now a structured registry of `VendorFiler` records (not a flat
    name->cik dict). Each entry carries the tab category, segment sub-bucket,
    per-vendor SEC `form_types`, an FPI flag, and a free-text note. Downstream
    code that still wants a flat name->cik mapping uses the
    `_flatten_vendor_filers()` shim, preserving the legacy behaviour of
    `TRACKED_FILERS = {**ENERGY_COMPANIES, **HYPERSCALERS, **VENDOR_FILERS}`.
  * The quarterly fetcher (`fetch_real_quarterly_filings_async`) now consults a
    per-CIK form-types map. For energy companies and hyperscalers we keep the
    historical default ("10-K", "10-Q"). For vendor filers we use the registry's
    `form_types` tuple, which lets foreign private issuers (TSMC, ASML, ASE,
    GlobalFoundries) be fetched as 20-F + 6-K. **20-F is treated as the FPI
    equivalent of 10-K, and 6-K as the FPI equivalent of 10-Q.** Vendors whose
    `form_types` is empty (the press-only hyperscaler-silicon entries
    Alphabet/Amazon/Microsoft) are skipped from the quarterly path; they are
    intended to be tracked via the press-release pipeline instead.
  * The 8-K fetcher (`fetch_real_8k_deals_async`) is unchanged: it still
    iterates only ENERGY_COMPANIES + HYPERSCALERS by design.
"""
import asyncio
import json
import logging
import re
import time
import os
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timedelta
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Datacenter Intelligence Platform research@oracle.com",
    "Accept": "application/json",
}
CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_HOURS = 12

# Companies whose 8-K filings signal power deals with hyperscalers
ENERGY_COMPANIES = {
    "Constellation Energy": "0001868275",
    "Talen Energy": "0001839839",
    "NuScale Power": "0001808173",
    "Oklo": "0001849056",
    "X-Energy": None,          # private, no EDGAR
    "Vistra Energy": "0001692819",
    "NextEra Energy": "0001004440",
    "AES Corporation": "0000002178",
    "Dominion Energy": "0000715957",
}

# Hyperscalers — search their 10-K/10-Q for energy commitment disclosures
HYPERSCALERS = {
    "Microsoft":   "0000789019",
    "Amazon":      "0001018724",
    "Alphabet":    "0001652044",
    "Meta":        "0001326801",
    "Oracle":      "0001341439",
}

# ---------------------------------------------------------------------------
# Vendor registry (Supplier Insights — Phase 2 AC1)
#
# The Supplier Insights dropdown has three tabs (GPU Supply / NICs & Optics /
# Wafer Production & Supply). Each tab needs more than a CIK to render — it
# needs a segment label (for sub-grouping NICs vs optics, foundry vs packaging
# vs equipment), per-vendor SEC form types (TSMC/ASML/ASE/GlobalFoundries are
# foreign private issuers and file 20-F + 6-K instead of 10-K + 10-Q), and a
# notes slot for fiscal-calendar quirks (Credo's April year-end) or special
# cases (the press-only hyperscaler-silicon vendors).
#
# NB on Intel duality: Intel appears as TWO distinct registry entries —
# "Intel-DCAI" (Data Center & AI segment, GPU tab) and "Intel-Foundry" (Intel
# Foundry segment, Wafer tab). Both share CIK 0000050863 because there is
# only one Intel filer with the SEC. The duplicate-CIK case is handled by
# `_flatten_vendor_filers()` (first wins) and by `vendor_filer_by_cik()`
# (returns a list of all entries on a CIK).
#
# Coherent CIK correction: prior code used 0001140536, which actually maps to
# WILLIS TOWERS WATSON PLC. The correct CIK for Coherent Corp. (NASDAQ: COHR,
# the optical components company) is 0000820318, verified via the SEC
# submissions JSON endpoint on 2026-04-30.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VendorFiler:
    """One row in the Supplier Insights vendor registry.

    Fields:
      display_name -- canonical name; used as company label in API responses
                      and UI cards. Two entries may share a CIK (Intel) so
                      the display_name is what disambiguates them.
      cik          -- zero-padded 10-digit SEC CIK (or None for "no EDGAR
                      coverage", though no current entry uses None).
      tab          -- which Supplier Insights tab the vendor belongs to.
      segment      -- sub-bucket within the tab (gpu/nic/optics for tabs
                      gpu+nics_optics; foundry/packaging/equipment for the
                      wafer tab).
      form_types   -- which SEC form codes the quarterly fetcher should pull.
                      Empty tuple means "press-only — skip the EDGAR
                      quarterly path" (used for Alphabet/Amazon/Microsoft
                      under the GPU tab where the in-house silicon revenue is
                      not separately disclosed in the 10-K).
      is_fpi       -- foreign private issuer flag. Implied by form_types
                      containing 20-F/6-K, but explicit is friendlier for
                      review and per-vendor branching.
      notes        -- free-text note shown in the "states_excluded_with_reason"
                      block when no rows materialize for the vendor.
    """

    display_name: str
    cik: str | None
    tab: Literal["gpu", "nics_optics", "wafer"]
    segment: Literal["gpu", "nic", "optics", "foundry", "packaging", "equipment"]
    form_types: tuple[str, ...] = ("10-K", "10-Q")
    is_fpi: bool = False
    notes: str = ""
    # Reporting currency. Default USD. TWD applies to Taiwanese filers
    # (TSMC, ASE Technology) whose 20-F / 6-K disclosures use New Taiwan
    # dollars. The router converts to USD at display time using
    # FX_TO_USD below; raw stored values stay as the extractor pulled them.
    reporting_currency: Literal["USD", "TWD", "EUR"] = "USD"


# Approximate FX rates for converting non-USD reporting currencies at
# display time. Refresh annually; precision isn't critical for chart
# trends, only for absolute readability.
FX_TO_USD: dict[str, float] = {
    "USD": 1.0,
    "TWD": 1.0 / 32.0,   # ~NT$32 = US$1 as of 2026-04-30
    "EUR": 1.07,
}


# Curated 17-entry vendor registry (matches docs/planning/SUPPLIER_VENDOR_SCOPE.md).
VENDOR_FILERS: dict[str, VendorFiler] = {
    # -- GPU Supply --------------------------------------------------------
    "NVIDIA": VendorFiler(
        display_name="NVIDIA",
        cik="0001045810",
        tab="gpu",
        segment="gpu",
    ),
    "AMD": VendorFiler(
        display_name="AMD",
        cik="0000002488",
        tab="gpu",
        segment="gpu",
    ),
    "Intel-DCAI": VendorFiler(
        display_name="Intel-DCAI",
        cik="0000050863",
        tab="gpu",
        segment="gpu",
        notes="Data Center & AI segment within Intel",
    ),
    "Alphabet": VendorFiler(
        display_name="Alphabet",
        cik="0001652044",
        tab="gpu",
        segment="gpu",
        form_types=(),
        notes="press-only (TPU)",
    ),
    "Amazon": VendorFiler(
        display_name="Amazon",
        cik="0001018724",
        tab="gpu",
        segment="gpu",
        form_types=(),
        notes="press-only (Trainium/Inferentia)",
    ),
    "Microsoft": VendorFiler(
        display_name="Microsoft",
        cik="0000789019",
        tab="gpu",
        segment="gpu",
        form_types=(),
        notes="press-only (Maia)",
    ),

    # -- NICs & Optics Supply ---------------------------------------------
    "Broadcom": VendorFiler(
        display_name="Broadcom",
        cik="0001730168",
        tab="nics_optics",
        segment="nic",
    ),
    "Marvell": VendorFiler(
        display_name="Marvell",
        cik="0001835632",
        tab="nics_optics",
        segment="nic",
    ),
    "Coherent": VendorFiler(
        display_name="Coherent",
        # Verified 2026-04-30: 0000820318 is COHERENT CORP. (ticker COHR);
        # the previously-stored 0001140536 maps to WILLIS TOWERS WATSON PLC.
        cik="0000820318",
        tab="nics_optics",
        segment="optics",
        notes="CIK corrected from 0001140536 (Willis Towers Watson) to 0000820318",
    ),
    "Lumentum": VendorFiler(
        display_name="Lumentum",
        cik="0001633978",
        tab="nics_optics",
        segment="optics",
    ),
    "Credo": VendorFiler(
        display_name="Credo",
        cik="0001807794",
        tab="nics_optics",
        segment="nic",
        notes="fiscal year ends April — normalize to calendar Q in router",
    ),
    "Astera Labs": VendorFiler(
        display_name="Astera Labs",
        cik="0001736297",
        tab="nics_optics",
        segment="nic",
    ),
    "Fabrinet": VendorFiler(
        display_name="Fabrinet",
        cik="0001408710",
        tab="nics_optics",
        segment="optics",
    ),

    # -- Wafer Production & Supply ----------------------------------------
    "TSMC": VendorFiler(
        display_name="TSMC",
        cik="0001046179",
        tab="wafer",
        segment="foundry",
        form_types=("20-F", "6-K"),
        is_fpi=True,
        reporting_currency="TWD",
    ),
    "Intel-Foundry": VendorFiler(
        display_name="Intel-Foundry",
        cik="0000050863",
        tab="wafer",
        segment="foundry",
        notes="Intel Foundry segment (shares CIK with Intel-DCAI)",
    ),
    "GlobalFoundries": VendorFiler(
        display_name="GlobalFoundries",
        cik="0001709048",
        tab="wafer",
        segment="foundry",
        form_types=("20-F", "6-K"),
        is_fpi=True,
    ),
    "Amkor": VendorFiler(
        display_name="Amkor",
        cik="0001047127",
        tab="wafer",
        segment="packaging",
    ),
    "ASE Technology": VendorFiler(
        display_name="ASE Technology",
        cik="0001122411",
        tab="wafer",
        segment="packaging",
        form_types=("20-F", "6-K"),
        is_fpi=True,
        reporting_currency="TWD",
    ),
    "ASML": VendorFiler(
        display_name="ASML",
        cik="0000937966",
        tab="wafer",
        segment="equipment",
        form_types=("20-F", "6-K"),
        is_fpi=True,
    ),
    "Applied Materials": VendorFiler(
        display_name="Applied Materials",
        cik="0000006951",
        tab="wafer",
        segment="equipment",
    ),
}


def _flatten_vendor_filers() -> dict[str, str | None]:
    """Flatten VENDOR_FILERS into a name->cik map for backwards-compat callers.

    Skips duplicate CIKs (first wins) so that the merge into TRACKED_FILERS
    doesn't double-fetch Intel. Vendors with cik=None are still included so
    callers that pre-existed `VendorFiler` see a stable shape.
    """
    seen: set[str] = set()
    out: dict[str, str | None] = {}
    for entry in VENDOR_FILERS.values():
        if entry.cik and entry.cik in seen:
            continue
        if entry.cik:
            seen.add(entry.cik)
        out[entry.display_name] = entry.cik
    return out


def vendor_filers_for_tab(tab: str) -> list[VendorFiler]:
    """Return all VendorFiler entries assigned to the given tab."""
    return [v for v in VENDOR_FILERS.values() if v.tab == tab]


def vendor_filer_by_cik(cik: str) -> list[VendorFiler]:
    """Return all VendorFiler entries on a given CIK.

    Returns a list because Intel (CIK 0000050863) has two registry entries
    (Intel-DCAI on the GPU tab and Intel-Foundry on the Wafer tab).
    """
    return [v for v in VENDOR_FILERS.values() if v.cik == cik]


def edgar_eligible_vendors() -> list[VendorFiler]:
    """Vendors that the EDGAR quarterly fetcher should pull.

    Excludes vendors with cik=None (no EDGAR coverage) and vendors with an
    empty form_types tuple (press-only — Alphabet/Amazon/Microsoft under the
    GPU tab).
    """
    return [v for v in VENDOR_FILERS.values() if v.cik and v.form_types]


# Unified registry. Old constants are kept for backwards-compat callers;
# new code should iterate TRACKED_FILERS or use the helpers above.
TRACKED_FILERS = {**ENERGY_COMPANIES, **HYPERSCALERS, **_flatten_vendor_filers()}


# ---------------------------------------------------------------------------
# Per-CIK form-types map (Phase 2 AC4)
#
# The quarterly fetcher used to assume every filer reports on 10-K + 10-Q.
# That silently produced 0 rows for foreign private issuers, who file 20-F
# annually and 6-K quarterly instead. Build a map that:
#   * defaults energy companies + hyperscalers to ("10-K", "10-Q"),
#   * uses each VendorFiler's `form_types` for vendor CIKs (which may be
#     ("20-F", "6-K") for FPIs, or () for press-only entries),
#   * unions form_types across multiple vendor entries on the same CIK so
#     Intel's shared CIK ends up listing all of {10-K, 10-Q}.
# Empty tuples are kept (and treated as "skip" by the fetcher) so callers
# can distinguish "no coverage" from "default coverage".
# ---------------------------------------------------------------------------

_DEFAULT_QUARTERLY_FORMS: tuple[str, ...] = ("10-K", "10-Q")


def _build_form_types_map() -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    # Default forms for energy + hyperscaler filers.
    for cik in list(ENERGY_COMPANIES.values()) + list(HYPERSCALERS.values()):
        if cik:
            out[cik] = _DEFAULT_QUARTERLY_FORMS
    # Vendor-specific forms; union when multiple entries share a CIK (Intel).
    for entry in VENDOR_FILERS.values():
        if not entry.cik:
            continue
        existing = out.get(entry.cik, ())
        merged = tuple(sorted(set(existing) | set(entry.form_types)))
        out[entry.cik] = merged
    return out


CIK_FORM_TYPES: dict[str, tuple[str, ...]] = _build_form_types_map()

# Shared async HTTP client — created on first use, reused across calls
_http_client: httpx.AsyncClient | None = None


async def _get_http_client() -> httpx.AsyncClient:
    """Get or create the shared async HTTP client."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            headers=HEADERS,
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0),
            follow_redirects=True,
        )
    return _http_client


async def _async_fetch(url: str, is_json: bool = True) -> dict | str:
    """Async HTTP fetch using httpx. Replaces blocking urllib.request."""
    client = await _get_http_client()
    resp = await client.get(url)
    resp.raise_for_status()
    content = resp.text
    return json.loads(content) if is_json else content


def _html_to_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&[a-z#0-9]+;", " ", text)
    return re.sub(r"\s+", " ", text)


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def _load_cache(key: str):
    p = _cache_path(key)
    if p.exists():
        age = datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)
        if age < timedelta(hours=CACHE_TTL_HOURS):
            return json.loads(p.read_text())
    return None


def _save_cache(key: str, data):
    _cache_path(key).write_text(json.dumps(data, indent=2))


async def _get_submissions(cik: str) -> dict:
    key = f"submissions_{cik}"
    cached = _load_cache(key)
    if cached:
        return cached
    data = await _async_fetch(f"https://data.sec.gov/submissions/CIK{cik}.json")
    _save_cache(key, data)
    return data


_RELEVANT_8K_ITEMS = (
    "1.01",  # Entry into a Material Definitive Agreement
    "2.01",  # Completion of Acquisition or Disposition of Assets
    "7.01",  # Reg FD Disclosure (often used for power-deal announcements)
    "8.01",  # Other Events (commonly used for PPAs / capacity disclosures)
)


async def _get_material_8ks(cik: str, company_name: str, since: str = "2023-01-01") -> list:
    """Return 8-K filings with power-deal-relevant items since `since`.

    Originally filtered to Item 1.01 only (Material Agreements); broadened to
    cover the four 8-K item codes that hyperscalers + utilities most commonly
    use for power-deal disclosures. Item 8.01 (Other Events) and 7.01 (Reg FD)
    are the dominant patterns for PPA / capacity announcements.
    """
    try:
        data = await _get_submissions(cik)
    except httpx.HTTPStatusError as e:
        logger.error(
            "edgar.submissions_http_error",
            extra={"cik": cik, "company": company_name, "status": e.response.status_code},
        )
        return []
    except httpx.TimeoutException:
        logger.error("edgar.submissions_timeout", extra={"cik": cik, "company": company_name})
        return []
    except Exception as e:
        logger.error(
            "edgar.submissions_unexpected_error",
            extra={"cik": cik, "company": company_name, "error_class": type(e).__name__, "error": str(e)},
        )
        return []

    f = data.get("filings", {}).get("recent", {})
    forms   = f.get("form", [])
    dates   = f.get("filingDate", [])
    accs    = f.get("accessionNumber", [])
    docs    = f.get("primaryDocument", [""] * len(forms))
    items   = f.get("items", [""] * len(forms))
    results = []
    for form, date, acc, doc, item in zip(forms, dates, accs, docs, items):
        if form == "8-K" and date >= since and any(it in str(item) for it in _RELEVANT_8K_ITEMS):
            acc_path = acc.replace("-", "")
            cik_num = cik.lstrip("0")
            url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_path}/{doc}"
            results.append({
                "company": company_name,
                "form": form,
                "date": date,
                "url": url,
                "items": item,
            })
    return results


async def _extract_power_context(url: str, max_chars: int = 6000) -> str:
    """Fetch 8-K HTML and extract paragraphs mentioning power/energy deals.

    Two-tier behavior:
    1. Keyword-match sentences are preferred (cheap pre-filter that gives the
       downstream LLM concentrated context).
    2. When no keywords match, fall back to the first `fallback_chars` of the
       cleaned filing body so the LLM classifier has actual content to judge
       relevance from. Without this, a placeholder excerpt would always
       classify as "not power-related" by default — producing systematic
       false negatives on filings whose power language doesn't match our
       narrow keyword list.
    """
    try:
        html = await _async_fetch(url, is_json=False)
        text = _html_to_text(html)
        keywords = [
            "nuclear", "power purchase", "gigawatt", "megawatt",
            "energy agreement", "microsoft", "amazon", "google", "meta",
            "artificial intelligence", "data center", "hyperscale",
        ]
        sentences = re.split(r"(?<=[.!?])\s+", text)
        relevant = []
        for s in sentences:
            s = s.strip()
            if len(s) > 60 and any(k in s.lower() for k in keywords):
                relevant.append(s)
        if relevant:
            return " ".join(relevant)[:max_chars]
        # Keyword-miss fallback: hand the LLM a leading slice of the body.
        # 4000 chars is enough to cover the cover page + Item descriptions
        # on a typical 8-K, which is what the classifier needs.
        fallback_chars = 4000
        return text[:fallback_chars] if text else ""
    except httpx.HTTPStatusError as e:
        logger.warning(
            "edgar.filing_fetch_http_error",
            extra={"url": url, "status": e.response.status_code},
        )
        return ""
    except httpx.TimeoutException:
        logger.warning("edgar.filing_fetch_timeout", extra={"url": url})
        return ""
    except Exception as e:
        logger.error(
            "edgar.filing_fetch_unexpected_error",
            extra={"url": url, "error_class": type(e).__name__, "error": str(e)},
        )
        return ""


def _parse_mw_from_text(text: str) -> int | None:
    """Extract first MW/GW figure from text (regex — Phase 1C replaces with LLM)."""
    match = re.search(
        r"([\d,]+(?:\.\d+)?)\s*(?:-\s*)?"
        r"(gigawatt|GW|megawatt|MW)\b",
        text, re.I
    )
    if not match:
        return None
    val = float(match.group(1).replace(",", ""))
    unit = match.group(2).lower()
    return int(val * 1000) if "g" in unit else int(val)


async def fetch_real_8k_deals_async(since: str = "2023-06-01") -> list[dict]:
    """
    Async version: Fetch real 8-K filings from energy counterparties,
    extract power deal context. Returns list of structured deal dicts.
    """
    cache_key = f"real_8k_deals_{since.replace('-', '')}"
    cached = _load_cache(cache_key)
    if cached:
        return cached

    deals = []
    # Iterate BOTH energy companies (sellers / utilities / IPPs) AND
    # hyperscalers (buyers). The previous version skipped hyperscalers
    # entirely, missing every Amazon / Microsoft / Oracle / Meta 8-K.
    all_filers = {**ENERGY_COMPANIES, **HYPERSCALERS}
    for company, cik in all_filers.items():
        if cik is None:
            continue
        try:
            filings = await _get_material_8ks(cik, company, since)
            await asyncio.sleep(0.12)  # respect EDGAR rate limit
            # Increased from 6 → 15: hyperscalers file frequently and we want
            # the recent slice. Older filings are still naturally bounded by
            # the `since` parameter.
            for filing in filings[:15]:
                items_str = str(filing.get("items") or "")
                # We previously gated 7.01/8.01 filings on a keyword-scrape
                # match. That produced false negatives (real PPAs filed under
                # 7.01 with non-standard language got dropped). Now the LLM
                # classifier in edgar_extractor.py handles relevance — the
                # fetcher pulls the candidate slate; the classifier decides.
                # We still scrape inline keywords so we can pre-fill an excerpt
                # and a parsed MW where possible (cheap and useful when it works).
                context = await _extract_power_context(filing["url"])
                await asyncio.sleep(0.12)

                excerpt = context or (
                    f"[8-K filed {filing['date']} by {company} (Items {items_str or 'n/a'}); "
                    f"keyword scrape found no inline power language — LLM classifier will decide relevance]"
                )
                is_tech_related = any(kw in (context or "").lower() for kw in [
                    "microsoft", "amazon", "google", "meta", "oracle",
                    "artificial intelligence", "data center", "hyperscale",
                    "tech", "nuclear", "restart", "clean energy"
                ])
                mw = _parse_mw_from_text(context) if context else None
                deals.append({
                    "source_company": company,
                    "date": filing["date"],
                    "form": "8-K",
                    "items": items_str,
                    "edgar_url": filing["url"],
                    "capacity_mw": mw,
                    "excerpt": excerpt[:600],
                    "is_tech_related": is_tech_related,
                    "data_source": "SEC EDGAR 8-K",
                    "confidence": 0.90,
                })
        except httpx.HTTPStatusError as e:
            logger.error(
                "edgar.8k_batch_http_error",
                extra={"company": company, "cik": cik, "status": e.response.status_code},
            )
            continue
        except httpx.TimeoutException:
            logger.error("edgar.8k_batch_timeout", extra={"company": company, "cik": cik})
            continue
        except Exception as e:
            logger.error(
                "edgar.8k_batch_unexpected_error",
                extra={"company": company, "cik": cik, "error_class": type(e).__name__, "error": str(e)},
            )
            continue

    # Also mine Amazon 10-K for energy contract totals
    try:
        amzn_deal = await _mine_amazon_energy_commitment_async()
        if amzn_deal:
            deals.append(amzn_deal)
    except httpx.HTTPStatusError as e:
        logger.error("edgar.amazon_10k_http_error", extra={"status": e.response.status_code})
    except httpx.TimeoutException:
        logger.error("edgar.amazon_10k_timeout")
    except Exception as e:
        logger.error(
            "edgar.amazon_10k_unexpected_error",
            extra={"error_class": type(e).__name__, "error": str(e)},
        )

    _save_cache(cache_key, deals)
    return deals


async def _mine_amazon_energy_commitment_async() -> dict | None:
    """Async version: Extract Amazon's disclosed energy contract totals from latest 10-K."""
    cache_key = "amazon_energy_10k"
    cached = _load_cache(cache_key)
    if cached:
        return cached

    data = await _get_submissions("0001018724")
    f = data.get("filings", {}).get("recent", {})
    for form, date, acc, doc in zip(f.get("form", []), f.get("filingDate", []),
                                     f.get("accessionNumber", []), f.get("primaryDocument", [""] * 999)):
        if form == "10-K":
            acc_path = acc.replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/1018724/{acc_path}/{doc}"
            try:
                html = await _async_fetch(url, is_json=False)
                text = _html_to_text(html)
                m = re.search(
                    r"([\d,]+)\s+million\s+megawatt.hours?.{0,300}(?:approximately|duration|years?)",
                    text, re.I
                )
                if m:
                    mwh_m = float(m.group(1).replace(",", ""))
                    snippet = text[m.start(): m.start() + 500]
                    result = {
                        "source_company": "Amazon",
                        "buyer": "Amazon / AWS",
                        "date": date,
                        "form": "10-K",
                        "edgar_url": url,
                        "capacity_mw": None,
                        "energy_contract_mwh_million": mwh_m,
                        "excerpt": snippet,
                        "is_tech_related": True,
                        "data_source": "SEC EDGAR 10-K",
                        "confidence": 0.95,
                        "note": f"{int(mwh_m)}M MWh contracted over ~16 years ≈ {int(mwh_m/16/8.76):.0f} GW avg",
                    }
                    _save_cache(cache_key, result)
                    return result
            except httpx.HTTPStatusError as e:
                logger.error(
                    "edgar.amazon_10k_filing_http_error",
                    extra={"url": url, "status": e.response.status_code},
                )
                break
            except httpx.TimeoutException:
                logger.error("edgar.amazon_10k_filing_timeout", extra={"url": url})
                break
            except Exception as e:
                logger.error(
                    "edgar.amazon_10k_filing_unexpected_error",
                    extra={"url": url, "error_class": type(e).__name__, "error": str(e)},
                )
                break
    return None


# ---------------------------------------------------------------------------
# AC1 (Phase 2): 10-K + 10-Q multi-form ingestion.
#
# 8-Ks are short and event-driven; 10-K/10-Q are long (50-500KB cleaned text)
# and need chunking. We split on standard SEC section markers (Item 1, Item 7
# MD&A, Item 8 Financial Statements, etc.); when no markers are found we fall
# back to fixed-size 3000-char windows with 200-char overlap. Each chunk is
# yielded as its own filing-shaped dict so the downstream LLM extractor can
# classify and merge per chunk.
# ---------------------------------------------------------------------------

# Legacy constant retained for any external callers that imported it. New
# code should use the per-CIK CIK_FORM_TYPES map (built above from the
# vendor registry, energy companies, and hyperscalers).
_QUARTERLY_FORMS = _DEFAULT_QUARTERLY_FORMS
_ITEM_SECTION_RE = re.compile(
    r"\bItem\s+\d+[A-Z]?\b\.?",
    re.IGNORECASE,
)


def _chunk_long_filing(text: str, max_chars: int = 6000) -> list[str]:
    """Split a long filing's cleaned text into LLM-sized chunks.

    Strategy:
      1. Split on /\bItem\s+\d+[A-Z]?\b/ markers. Group adjacent sections to
         pack each chunk close to max_chars without exceeding it.
      2. If fewer than 3 markers found (corrupt / non-SEC HTML), fall back
         to fixed 3000-char windows with 200-char overlap.
      3. Special case: if markers exist but are all clustered in the last
         10% of the text (Intel's iXBRL 10-Q has all Items in a trailing
         cross-reference table), the marker-based split would discard the
         actual MD&A. Fall back to fixed-window chunking in that case.
    """
    if not text:
        return []

    markers = list(_ITEM_SECTION_RE.finditer(text))
    # Detect the iXBRL-trailing-Items pattern: every marker sits in the
    # last 10% of the text. Treat that as "no useful markers".
    if markers and all(m.start() >= int(0.9 * len(text)) for m in markers):
        markers = []

    if len(markers) >= 3:
        # Slice between markers
        sections: list[str] = []
        starts = [m.start() for m in markers] + [len(text)]
        for i in range(len(markers)):
            s = text[starts[i]: starts[i + 1]].strip()
            if s:
                sections.append(s)
        # Pack sections into chunks
        chunks: list[str] = []
        buf = ""
        for s in sections:
            if len(buf) + len(s) + 2 <= max_chars:
                buf = (buf + "\n\n" + s) if buf else s
            else:
                if buf:
                    chunks.append(buf)
                # If a single section itself exceeds max_chars, hard-split it
                while len(s) > max_chars:
                    chunks.append(s[:max_chars])
                    s = s[max_chars - 200:]  # 200-char overlap
                buf = s
        if buf:
            chunks.append(buf)
        return chunks

    # Fallback: fixed-size windows with overlap
    window = 3000
    overlap = 200
    chunks = []
    i = 0
    while i < len(text):
        chunks.append(text[i: i + window])
        if i + window >= len(text):
            break
        i += window - overlap
    return chunks


async def _get_quarterly_filings(
    cik: str,
    company_name: str,
    since: str,
    allowed_forms: tuple[str, ...] = _DEFAULT_QUARTERLY_FORMS,
) -> list[dict]:
    """Return periodic-report filings since `since` for one CIK.

    `allowed_forms` is the explicit set of SEC form codes to accept. Defaults
    to ("10-K", "10-Q") for backwards compatibility, but callers should pass
    the per-CIK tuple from CIK_FORM_TYPES so foreign private issuers (TSMC,
    ASML, ASE, GlobalFoundries) get their 20-F + 6-K filings picked up. If
    `allowed_forms` is empty the function returns [] without making a
    submissions request — that's how press-only vendors are skipped.
    """
    if not allowed_forms:
        return []
    try:
        data = await _get_submissions(cik)
    except httpx.HTTPStatusError as e:
        logger.error(
            "edgar.quarterly_submissions_http_error",
            extra={"cik": cik, "company": company_name, "status": e.response.status_code},
        )
        return []
    except Exception as e:
        logger.error(
            "edgar.quarterly_submissions_error",
            extra={"cik": cik, "company": company_name, "error": str(e)},
        )
        return []

    f = data.get("filings", {}).get("recent", {})
    forms = f.get("form", [])
    dates = f.get("filingDate", [])
    accs = f.get("accessionNumber", [])
    docs = f.get("primaryDocument", [""] * len(forms))
    out = []
    for form, date, acc, doc in zip(forms, dates, accs, docs):
        if form in allowed_forms and date >= since:
            acc_path = acc.replace("-", "")
            cik_num = cik.lstrip("0")
            url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{acc_path}/{doc}"
            out.append({
                "company": company_name,
                "form": form,
                "date": date,
                "url": url,
            })
    return out


async def _fetch_and_chunk(filing: dict) -> list[dict]:
    """Fetch a 10-K/10-Q HTML, clean to text, return one filing-dict per chunk.

    Each output dict mirrors the 8-K dict shape so it can flow through the
    same downstream extractor — but with `chunk_index` / `chunk_count` set
    so the merger knows which rows came from the same accession.
    """
    try:
        html = await _async_fetch(filing["url"], is_json=False)
        text = _html_to_text(html)
    except Exception as e:
        logger.warning(
            "edgar.quarterly_fetch_failed",
            extra={"url": filing["url"], "error": str(e)},
        )
        return []

    chunks = _chunk_long_filing(text)
    if not chunks:
        return []

    out = []
    for idx, chunk in enumerate(chunks):
        mw = _parse_mw_from_text(chunk)
        out.append({
            "source_company": filing["company"],
            "date": filing["date"],
            "form": filing["form"],
            "items": "",
            "edgar_url": filing["url"],
            "capacity_mw": mw,
            "excerpt": chunk[:6000],
            "is_tech_related": True,
            "data_source": f"SEC EDGAR {filing['form']}",
            "confidence": 0.90,
            "chunk_index": idx,
            "chunk_count": len(chunks),
        })
    return out


async def fetch_real_quarterly_filings_async(since: str = "2024-01-01") -> list[dict]:
    """Fetch 10-K + 10-Q filings across TRACKED_FILERS, chunked.

    Returns a flat list where each entry is one chunk. Chunks from the same
    accession share `edgar_url` and a unique (chunk_index, chunk_count)
    pair, letting the downstream extractor merge classification results
    per accession.
    """
    cache_key = f"real_quarterly_{since.replace('-', '')}"
    cached = _load_cache(cache_key)
    if cached:
        return cached

    all_chunks: list[dict] = []
    # Cap filings per company so a noisy filer can't dominate the budget.
    PER_FILER_CAP = 6   # ≈ 1 10-K + 4 10-Qs since 2024 + buffer

    for company, cik in TRACKED_FILERS.items():
        if cik is None:
            continue
        # Per-CIK form-types lookup (defaults to 10-K/10-Q for energy +
        # hyperscalers, 20-F/6-K for FPI vendors, () for press-only vendors).
        allowed_forms = CIK_FORM_TYPES.get(cik, _DEFAULT_QUARTERLY_FORMS)
        if not allowed_forms:
            # Press-only vendor (e.g. Alphabet/Amazon/Microsoft as
            # hyperscaler-silicon entries): skip the EDGAR quarterly path
            # entirely — those are tracked via the press-release pipeline.
            continue
        try:
            filings = await _get_quarterly_filings(cik, company, since, allowed_forms)
            await asyncio.sleep(0.12)
            for filing in filings[:PER_FILER_CAP]:
                chunks = await _fetch_and_chunk(filing)
                all_chunks.extend(chunks)
                await asyncio.sleep(0.12)
        except Exception as e:
            logger.error(
                "edgar.quarterly_batch_error",
                extra={"company": company, "error": str(e)},
            )
            continue

    _save_cache(cache_key, all_chunks)
    return all_chunks


def fetch_real_8k_deals(since: str = "2023-06-01") -> list[dict]:
    """
    Sync wrapper for backward compatibility with existing main.py callers.
    Runs the async version via asyncio. If already in an event loop
    (e.g. called from FastAPI), use fetch_real_8k_deals_async() directly.
    """
    cache_key = f"real_8k_deals_{since.replace('-', '')}"
    cached = _load_cache(cache_key)
    if cached:
        return cached

    try:
        loop = asyncio.get_running_loop()
        # We're inside an event loop — can't use asyncio.run().
        # Use asyncio.to_thread to run a sync wrapper that creates its own loop.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, fetch_real_8k_deals_async(since))
            return future.result(timeout=120)
    except RuntimeError:
        # No running event loop — safe to use asyncio.run()
        return asyncio.run(fetch_real_8k_deals_async(since))
