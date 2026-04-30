# Phase 2 Research Notes — 2026-04-29

Authoritative URLs / dataset IDs the Phase 2 ingestion adapters point at.
This file is the source of truth for endpoint changes; if a URL drifts,
update here first then propagate to the adapter (or override via env var).

## A. ISO/RTO interconnection-queue feeds

| ISO | URL | Format | Notes |
|---|---|---|---|
| ERCOT | https://www.ercot.com/misapp/servlets/IceDocListJsonWS?reportTypeId=15933 | JSON listing of XLSX files (GIS Report, reportTypeId 15933). Each item gives a `doclookupId` consumed by https://www.ercot.com/misdownload/servlets/mirDownload?doclookupId={id} to fetch the XLSX. Human landing page: https://www.ercot.com/mp/data-products/data-product-details?id=pg7-200-er | Updated monthly. Starting March 2026 the GIS bundle also includes the Transmission Interconnection Costs Report. |
| MISO  | https://giqueue.misoenergy.org/PublicGiQueueMap/index.html (interactive); canonical landing https://www.misoenergy.org/planning/resource-utilization/GI_Queue/ | XLSX (full queue exported from the Interactive Queue page; CDN-hosted file under cdn.misoenergy.org with a versioned filename — link is regenerated, so scrape the GI_Queue page for the current `cdn.misoenergy.org/.../GI%20Queue*.xlsx` href) | Refreshed roughly monthly; the public map/queue updates as projects move through DPP cycles. |
| PJM (existing) | https://www.pjm.com/pjmfiles/media/planning/queues-data/PlanningQueues.xml | Bulk XML (root `<Projects>`) | Already shipped in Phase 1.5; reference adapter for the Phase 2 work. |

### Adapter env-var overrides
- `ERCOT_GIS_URL` — pin a specific xlsx URL to skip the listing resolution.
- `MISO_QUEUE_URL` — pin a specific xlsx URL.
- `MISO_LANDING_URL` — override the page we scrape for the latest xlsx href.

## B. State permit APIs

| State | URL | Format | Notes |
|---|---|---|---|
| IA | https://data.iowa.gov/resource/8bwn-bk39.json (Socrata SODA v2 endpoint for "State Permitting and Air Reporting System – Construction Permits"; CSV variant: https://data.iowa.gov/resource/8bwn-bk39.csv) | JSON / CSV (Socrata API, supports SoQL `$where`, `$limit`, `$order`) | Sourced from Iowa DNR SPARS; updated as new construction permits are finalized. No app token required for low-volume reads. |
| OH | https://epa.ohio.gov/divisions-and-offices/air-pollution-control/permitting/issued-air-permits (search HTML) plus open-data portal https://data-oepa.opendata.arcgis.com/ (ArcGIS Hub — datasets exposed as ArcGIS REST FeatureServer + GeoJSON/CSV downloads) | HTML form (issued-permits search) + ArcGIS REST/GeoJSON via Open Data portal | No data.ohio.gov dataset for air permits as of Apr 2026. The current `OhioPermitAdapter` defaults to `data.ohio.gov` Socrata; if/when an Ohio EPA ArcGIS Hub dataset gives a clean GeoJSON URL it should be substituted via `OHIO_SODA_BASE` + a different adapter strategy. |
| VA (existing) | data.virginia.gov CKAN datastore_search | JSON | Already shipped in Phase 1.5; CKAN-based, not Socrata. |
| TX (existing) | TCEQ Title V air permits | XML/HTML | Already shipped. |
| NY (existing) | data.ny.gov Socrata (Title V, State Facility, CATS) | JSON | Already shipped. |

### Adapter env-var overrides
- `IOWA_SODA_RESOURCE` — Socrata 4-4 ID (default `8bwn-bk39`).
- `OHIO_SODA_RESOURCE` — Socrata 4-4 ID.
- `OHIO_SODA_BASE` — Socrata base URL.
- `SOCRATA_APP_TOKEN` — optional, raises rate limits.

## C. IR press-release feeds (19 companies)

| Company | URL | scraper_kind |
|---|---|---|
| Constellation Energy | https://investors.constellationenergy.com/news-releases | html |
| Talen Energy | https://ir.talenenergy.com/news-events/news-releases | html |
| NuScale Power | https://www.nuscalepower.com/press-releases | html |
| Oklo | https://oklo.com/investors/news/default.aspx | html |
| Vistra Energy | https://investor.vistracorp.com/news | html |
| NextEra Energy | https://www.investor.nexteraenergy.com/news-and-events/news-releases/2026 | html |
| AES Corporation | https://www.aes.com/investors/news-events | html |
| Dominion Energy | https://news.dominionenergy.com/news-releases | html |
| Microsoft | https://news.microsoft.com/feed/ | rss |
| Amazon | https://ir.aboutamazon.com/news-release/default.aspx | html |
| Alphabet | https://abc.xyz/investor/news/ | html |
| Meta | https://investor.atmeta.com/rss/news-releases.xml | rss |
| Oracle | https://www.oracle.com/corporate/press/rss/rss-pr.xml | rss |
| Broadcom | https://investors.broadcom.com/news-releases | html |
| Coherent Corp | https://www.coherent.com/company/investor-relations/financial-releases | html |
| Lumentum | https://investor.lumentum.com/financial-news-releases/default.aspx | html |
| NVIDIA | https://nvidianews.nvidia.com/releases.xml | rss |
| Apple | https://www.apple.com/newsroom/ | html |
| TSMC | https://pr.tsmc.com/english/news | html |

### Implementation notes
- Talen, NuScale, Vistra, NextEra, Lumentum, Coherent — all use Q4 Inc. /
  GCS-Web style IR templates. These render server-side HTML cards with
  stable selectors (`.module_item`, `.wd_item`, etc.); a single anchor-
  pattern pass per page works.
- Amazon's `/news-release/default.aspx` is also Q4 Inc.; same selector family.
- Alphabet's `abc.xyz/investor/news/` uses a custom JS-rendered list — the
  AEM feed at `https://abc.xyz/investor/news/_jcr_content.feed` is a
  fallback if anchor scraping returns empty.
- NVIDIA also offers per-category feeds at
  `https://nvidianews.nvidia.com/cats/{category}.xml` if subsetting is
  desired (e.g., `data-center`, `corporate`).

### Filtering
Releases are persisted only when at least one keyword from
`{datacenter, hyperscale, GW, MW, PPA, interconnect, nuclear, SMR, colo,
GPU}` matches the title or meta description. See
`backend/ingestion/press_releases.py::_KEYWORDS`.

## D. Paid-data gaps (NOT addressed in Phase 2)

These remain blocked on commercial procurement:
- L2 Triangulation: NVIDIA shipment data (paid)
- L3 Triangulation: Coherent / Lumentum order books (paid)
- L4 Triangulation: Shovels.ai county building permits (paid)
- Aterio licensed datacenter feed (paid)
- FMP / OpenCorporates entity resolution (paid)
- Planet / Maxar satellite (paid)
- Bloomberg / NewsAPI structured news (paid)

## Sources
- ERCOT GIS Report data product page: https://www.ercot.com/mp/data-products/data-product-details?id=pg7-200-er
- MISO GI Queue landing: https://www.misoenergy.org/planning/resource-utilization/GI_Queue/
- MISO Public GI Queue Map: https://giqueue.misoenergy.org/PublicGiQueueMap/index.html
- Iowa SPARS Construction Permits dataset (8bwn-bk39): https://data.iowa.gov/Regulation/State-Permitting-and-Air-Reporting-System-Construc/8bwn-bk39
- Ohio EPA Issued Air Permits: https://epa.ohio.gov/divisions-and-offices/air-pollution-control/permitting/issued-air-permits
- Ohio EPA Open Data (ArcGIS Hub): https://data-oepa.opendata.arcgis.com/
- Microsoft Source RSS: https://news.microsoft.com/feed/
- Oracle press release RSS: https://www.oracle.com/corporate/press/rss/rss-pr.xml
- NVIDIA Newsroom RSS: https://nvidianews.nvidia.com/releases.xml
- Meta IR email & RSS: https://investor.atmeta.com/resources/email-alerts-and-rss/
- Constellation IR RSS hub: https://investors.constellationenergy.com/shareholder-services/rss-feeds
- Dominion Energy IR RSS hub: https://investors.dominionenergy.com/rss-feeds/
- AES IR RSS hub: https://www.aes.com/investors/rss-feeds/default.aspx
- Broadcom IR RSS hub: https://investors.broadcom.com/rss-feeds
