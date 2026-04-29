"""
EDGAR Agent — fetches real 8-K filings from energy counterparties and hyperscalers.
Uses SEC EDGAR public APIs (no key required, rate-limit: 10 req/s).

Phase 0 fixes (H1 + H2):
  - H1: Replace 5 silent except Exception blocks with structured exceptions + logging
  - H2: Convert urllib.request -> httpx.AsyncClient (no blocking sync I/O on FastAPI event loop)
        Wrap edgartools sync calls via asyncio.to_thread() if needed.

Phase 1C will replace regex extraction with LLM (backend/llm/agents/edgar_extractor.py).
"""
import asyncio
import json
import logging
import re
import time
import os
from pathlib import Path
from datetime import datetime, timedelta

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
    """Fetch 8-K HTML and extract paragraphs mentioning power/energy deals."""
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
        return " ".join(relevant)[:max_chars]
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
                # Material agreements (1.01) and asset acquisitions (2.01) are
                # almost always business-relevant — keep them even when our
                # keyword scrape misses inline language. 7.01 (Reg FD) and
                # 8.01 (Other Events) cover everything from CFO appointments
                # to dividend declarations to stock buybacks; only keep those
                # if the body actually mentions power language.
                strong_signal_item = "1.01" in items_str or "2.01" in items_str

                context = await _extract_power_context(filing["url"])
                await asyncio.sleep(0.12)

                if not context and not strong_signal_item:
                    # Pure 7.01/8.01 filing with no inline power language —
                    # most likely an unrelated press release (officer change,
                    # earnings, share-repurchase, etc.). Skip silently.
                    continue

                excerpt = context or (
                    f"[8-K filed {filing['date']} by {company} (Items {items_str or 'n/a'}); "
                    f"keyword scrape found no inline power language — open the filing for details]"
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
