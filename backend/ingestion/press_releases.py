"""
Investor-Relations press-release scraper — Phase 2 (AC3).

Scrapes the public press-release index of each tracked hyperscaler /
energy / chip-vendor company, filters to releases that mention power,
datacenter, capacity, MW/GW, or PPAs, and persists into the
`press_releases` table.

Defensive design:
  * Each company config has a list of `index_urls` (up to 2). Most IR
    sites publish a JSON feed under /press-releases or
    /api/news; we hit those preferentially because HTML structure is
    fragile. If JSON parsing fails we fall back to a generic anchor-tag
    HTML extractor.
  * Per AC3 we run on a 6-hour cron (call-site decides). Each release is
    de-duped by source_url unique constraint.
  * No paid feeds are used; everything here is the company's own public
    IR HTML/JSON.

Public entry point:
    class PressReleaseAdapter:
        async def run(self, session) -> dict
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
import stamina
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import (
    DataCoverage, DataLineage, IngestionRun, PressRelease,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-company config
# ---------------------------------------------------------------------------

# 17 tracked companies. Each entry maps canonical name to one or more
# IR press-release sources. Prefer RSS (machine-readable, stable) over
# HTML scrape; the scraper falls through if RSS is unreachable. URLs
# below are sourced from each company's IR/RSS hub (see
# docs/planning/PHASE2_RESEARCH.md).
IR_TARGETS: list[dict] = [
    {"company": "Microsoft",            "kind": "rss",
     "urls": ["https://news.microsoft.com/feed/"]},
    {"company": "Amazon",               "kind": "html",
     "urls": ["https://ir.aboutamazon.com/news-release/default.aspx"]},
    {"company": "Alphabet",             "kind": "html",
     "urls": ["https://abc.xyz/investor/news/"]},
    {"company": "Meta",                 "kind": "rss",
     "urls": ["https://investor.atmeta.com/rss/news-releases.xml"]},
    {"company": "Oracle",               "kind": "rss",
     "urls": ["https://www.oracle.com/corporate/press/rss/rss-pr.xml"]},
    {"company": "Apple",                "kind": "html",
     "urls": ["https://www.apple.com/newsroom/"]},
    {"company": "NVIDIA",               "kind": "rss",
     "urls": ["https://nvidianews.nvidia.com/releases.xml"]},
    {"company": "Broadcom",             "kind": "html",
     "urls": ["https://investors.broadcom.com/news-releases"]},
    {"company": "Coherent",             "kind": "html",
     "urls": ["https://www.coherent.com/company/investor-relations/financial-releases"]},
    {"company": "Lumentum",             "kind": "html",
     "urls": ["https://investor.lumentum.com/financial-news-releases/default.aspx"]},
    {"company": "TSMC",                 "kind": "html",
     "urls": ["https://pr.tsmc.com/english/news"]},
    {"company": "Constellation Energy", "kind": "html",
     "urls": ["https://investors.constellationenergy.com/news-releases"]},
    {"company": "Talen Energy",         "kind": "html",
     "urls": ["https://ir.talenenergy.com/news-events/news-releases"]},
    {"company": "Vistra Energy",        "kind": "html",
     "urls": ["https://investor.vistracorp.com/news"]},
    {"company": "NextEra Energy",       "kind": "html",
     "urls": ["https://www.investor.nexteraenergy.com/news-and-events/news-releases/2026"]},
    {"company": "Dominion Energy",      "kind": "html",
     "urls": ["https://news.dominionenergy.com/news-releases"]},
    {"company": "AES Corporation",      "kind": "html",
     "urls": ["https://www.aes.com/investors/news-events"]},
    {"company": "NuScale Power",        "kind": "html",
     "urls": ["https://www.nuscalepower.com/press-releases"]},
    {"company": "Oklo",                 "kind": "html",
     "urls": ["https://oklo.com/investors/news/default.aspx"]},
]


# Keywords that indicate the release is on-topic for our pillar.
_KEYWORDS = re.compile(
    r"data\s*center|datacenter|hyperscale|cloud|colocation|"
    r"\bgw\b|\bmw\b|\bppa\b|power\s*purchase|"
    r"interconnect|substation|transmission|"
    r"nuclear|smr|small\s*modular|"
    r"behind.the.meter|"
    r"compute|gpu",
    re.I,
)

# Anchor-tag href pattern that looks like a press release.
_HREF_RE = re.compile(r'href="([^"#]+)"', re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_DATE_RE = re.compile(
    r"(20\d{2})[\-/](0?[1-9]|1[0-2])[\-/](0?[1-9]|[12]\d|3[01])"
)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class PressReleaseAdapter:
    adapter_name = "Investor Relations Press Releases"
    adapter_id = "ir_press_releases"
    adapter_version = "1.0.0"
    pillar = "press_releases"
    source_id = "ir_press_releases"
    declared_status = "partial"

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(3)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=60.0, write=10.0, pool=15.0),
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "strategic-insights-tool/1.0 (research; contact: research@oracle.com)"
                    ),
                    "Accept": "text/html,application/json,application/xhtml+xml",
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @stamina.retry(on=httpx.TransportError, attempts=2, wait_initial=1.0)
    async def _fetch(self, url: str) -> str:
        async with self._semaphore:
            await asyncio.sleep(0.4)
            client = await self._get_client()
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                logger.warning("ir_press.fetch_failed url=%s err=%s", url, exc)
                return ""
            if resp.status_code >= 400:
                logger.warning("ir_press.fetch_status url=%s code=%s",
                               url, resp.status_code)
                return ""
            return resp.text or ""

    # ------------------------------------------------------------------
    # Parsing — JSON first, HTML anchor fallback
    # ------------------------------------------------------------------

    def _parse_rss(self, body: str, base_url: str) -> list[dict]:
        """Parse RSS/Atom XML body, returning a list of {url, title, published}."""
        if not body or "<" not in body:
            return []
        from xml.etree import ElementTree as ET
        try:
            # Strip BOM
            if body.startswith("\ufeff"):
                body = body[1:]
            root = ET.fromstring(body)
        except ET.ParseError:
            return []

        out: list[dict] = []
        # Atom: <entry>; RSS: <item>
        for ns_local in ("item", "{http://www.w3.org/2005/Atom}entry", "entry"):
            entries = root.findall(f".//{ns_local}")
            if entries:
                for e in entries:
                    title = ""
                    link = ""
                    pub = None
                    for child in e:
                        tag = child.tag.split("}", 1)[-1].lower()
                        text_val = (child.text or "").strip()
                        if tag == "title":
                            title = text_val
                        elif tag == "link":
                            href = child.attrib.get("href")
                            link = href if href else text_val
                        elif tag in ("pubdate", "published", "date"):
                            pub = text_val
                        elif tag == "description" and not title:
                            title = text_val[:200]
                    if link and title:
                        out.append({
                            "url": urljoin(base_url, link),
                            "title": title.strip()[:500],
                            "published": pub,
                        })
                if out:
                    return out
        return out

    def _parse_json_feed(self, body: str, base_url: str) -> list[dict]:
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return []
        # Hunt for a list-of-articles shape under common keys.
        items = None
        if isinstance(payload, dict):
            for k in ("items", "data", "articles", "results", "releases"):
                v = payload.get(k)
                if isinstance(v, list):
                    items = v
                    break
        if items is None and isinstance(payload, list):
            items = payload
        if not items:
            return []
        out: list[dict] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            url = (it.get("url") or it.get("link") or it.get("permalink")
                   or it.get("href"))
            title = it.get("title") or it.get("headline") or it.get("name")
            published = (it.get("published") or it.get("date")
                         or it.get("publishedAt") or it.get("publish_date"))
            if url and title:
                out.append({
                    "url": urljoin(base_url, url),
                    "title": str(title).strip(),
                    "published": str(published) if published else None,
                })
        return out

    def _parse_html_anchors(self, body: str, base_url: str) -> list[dict]:
        if not body:
            return []
        out: list[dict] = []
        seen: set[str] = set()
        # Extract every anchor href; pick those that look like press releases
        # (path includes "press", "news", "release", or a YYYY date).
        for href in _HREF_RE.findall(body):
            href_l = href.lower()
            if any(skip in href_l for skip in (
                "javascript:", "mailto:", "#", ".pdf", ".jpg", ".png", ".css",
                ".js?",
            )):
                continue
            if not (
                "press" in href_l or "release" in href_l or "news" in href_l
                or "newsroom" in href_l or "announcement" in href_l
                or _DATE_RE.search(href_l)
            ):
                continue
            full = urljoin(base_url, href)
            if full in seen:
                continue
            seen.add(full)
            out.append({"url": full, "title": "", "published": None})
            if len(out) >= 80:  # cap per page
                break
        return out

    async def _enrich_release(self, item: dict) -> dict:
        """Fetch the release page itself to capture its <title> and any
        published date in the URL slug or page header. Cheap and best-effort.
        """
        if item.get("title") and item.get("published"):
            return item
        body = await self._fetch(item["url"])
        if not body:
            return item
        if not item.get("title"):
            m = _TITLE_RE.search(body)
            if m:
                item["title"] = re.sub(r"\s+", " ", m.group(1)).strip()[:500]
        if not item.get("published"):
            m = _DATE_RE.search(item["url"]) or _DATE_RE.search(body[:8192])
            if m:
                item["published"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        # Capture a short excerpt for the modal
        excerpt_match = re.search(
            r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"']([^\"']+)[\"']",
            body, re.I,
        )
        if excerpt_match:
            item["excerpt"] = excerpt_match.group(1)[:1000]
        return item

    @staticmethod
    def _matched_terms(text: str) -> list[str]:
        terms: set[str] = set()
        for kw, label in (
            (r"data\s*center|datacenter", "datacenter"),
            (r"hyperscale", "hyperscale"),
            (r"\bgw\b", "GW"),
            (r"\bmw\b", "MW"),
            (r"\bppa\b|power\s*purchase", "PPA"),
            (r"interconnect", "interconnect"),
            (r"nuclear|smr|small\s*modular", "nuclear"),
            (r"colocation|colo", "colo"),
            (r"\bgpu\b", "GPU"),
        ):
            if re.search(kw, text, re.I):
                terms.add(label)
        return sorted(terms)

    @staticmethod
    def _to_date(s: Optional[str]) -> Optional[date]:
        if not s:
            return None
        m = _DATE_RE.search(s)
        if not m:
            return None
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(self, session: AsyncSession) -> dict:
        run_record = IngestionRun(
            adapter_name=self.adapter_id,
            adapter_version=self.adapter_version,
            started_at=datetime.utcnow(),
            status="running",
            trigger="manual",
        )
        session.add(run_record)
        await session.flush()

        records_fetched = 0
        records_stored = 0
        records_skipped = 0
        errors: list[dict] = []

        skipped_companies: list[dict] = []
        try:
            for target in IR_TARGETS:
                company = target["company"]
                kind = target.get("kind", "html")
                company_stored_before = records_stored
                try:
                    for index_url in target["urls"]:
                        body = await self._fetch(index_url)
                        if not body:
                            continue
                        if kind == "rss":
                            items = self._parse_rss(body, index_url)
                        else:
                            items = self._parse_json_feed(body, index_url)
                        if not items:
                            items = self._parse_html_anchors(body, index_url)
                        if not items:
                            continue
                        records_fetched += len(items)

                        # Limit per-company per-index scrape so a giant page
                        # doesn't blow our wall-time budget.
                        items = items[:30]

                        for it in items:
                            try:
                                it = await self._enrich_release(it)
                            except Exception as exc:
                                logger.warning("ir_press.enrich_failed: %s", exc)

                            title = it.get("title") or ""
                            excerpt = it.get("excerpt") or ""
                            text_blob = f"{title}\n{excerpt}"
                            if not _KEYWORDS.search(text_blob):
                                records_skipped += 1
                                continue

                            published = self._to_date(it.get("published"))
                            terms = self._matched_terms(text_blob)
                            try:
                                stmt = pg_insert(PressRelease).values(
                                    company_canon=company,
                                    source_url=it["url"][:1024],
                                    title=title[:500] or "(no title)",
                                    summary=excerpt[:1000] or None,
                                    excerpt=excerpt or None,
                                    matched_terms=",".join(terms)[:300] or None,
                                    published_date=published,
                                    parser_version=self.adapter_version,
                                    retrieved_at=datetime.utcnow(),
                                )
                                stmt = stmt.on_conflict_do_update(
                                    index_elements=["source_url"],
                                    set_={
                                        "title": stmt.excluded.title,
                                        "summary": stmt.excluded.summary,
                                        "excerpt": stmt.excluded.excerpt,
                                        "matched_terms": stmt.excluded.matched_terms,
                                        "published_date": stmt.excluded.published_date,
                                        "retrieved_at": stmt.excluded.retrieved_at,
                                    },
                                )
                                await session.execute(stmt)
                                records_stored += 1
                            except Exception as exc:
                                logger.error("ir_press.upsert_error url=%s err=%s",
                                             it.get("url"), exc)
                                errors.append({"url": it.get("url"), "error": str(exc)})
                except Exception as exc:
                    # Per AC3: a single broken IR scraper (404, layout
                    # change, anti-bot block, parser exception) must not
                    # fail the whole run. Log and skip the company.
                    logger.warning(
                        "ir_press.company_skipped company=%s err=%s",
                        company, exc,
                    )
                    skipped_companies.append({
                        "company": company,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    continue
                if records_stored == company_stored_before:
                    skipped_companies.append({
                        "company": company,
                        "error": "no_on_topic_releases_found",
                    })

            await self._write_coverage(session, records_stored)
            await self._write_lineage(session, run_record.id, records_stored)

            run_record.status = "success" if records_stored or not errors else "partial_failure"
            run_record.completed_at = datetime.utcnow()
            run_record.records_fetched = records_fetched
            run_record.records_stored = records_stored
            run_record.records_skipped = records_skipped
            err_payload: dict = {}
            if errors:
                err_payload["errors"] = errors[:50]
            if skipped_companies:
                err_payload["skipped_companies"] = skipped_companies
            run_record.error_log = err_payload or None
            await session.flush()
        except Exception as exc:
            run_record.status = "failure"
            run_record.completed_at = datetime.utcnow()
            run_record.error_log = {"fatal": str(exc)}
            await session.flush()
            logger.error("ir_press.run_fatal_error: %s", exc)
            raise
        finally:
            await self.close()

        return {
            "adapter": self.adapter_id,
            "status": run_record.status,
            "records_fetched": records_fetched,
            "records_stored": records_stored,
            "records_skipped": records_skipped,
            "skipped_companies": skipped_companies,
        }

    async def _write_coverage(self, session: AsyncSession, n: int) -> None:
        stmt = pg_insert(DataCoverage).values(
            pillar=self.pillar, state_code="ALL", source=self.source_id,
            coverage_status=self.declared_status, record_count=n,
            last_ingested_at=datetime.utcnow(), freshness_sla_hours=24,
            notes="IR press releases scraped from each company's public newsroom",
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_coverage_pillar_state_source",
            set_={
                "coverage_status": stmt.excluded.coverage_status,
                "record_count": stmt.excluded.record_count,
                "last_ingested_at": stmt.excluded.last_ingested_at,
                "updated_at": datetime.utcnow(),
            },
        )
        await session.execute(stmt)

    async def _write_lineage(self, session: AsyncSession, run_id: int, n: int) -> None:
        if n <= 0:
            return
        stmt = pg_insert(DataLineage).values(
            table_name="press_releases",
            record_id=run_id,
            ingestion_run_id=run_id,
            source_url="multiple-ir-pages",
            retrieved_at=datetime.utcnow(),
            parser_version=self.adapter_version,
            confidence=0.55,
            transformation={"method": "ir_press_release_scrape"},
        )
        await session.execute(stmt)
