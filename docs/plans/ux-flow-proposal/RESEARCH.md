# UX Flow & Information Architecture Research
**Author:** Research Agent
**Date:** 2026-05-19
**Scope:** How comparable competitive-intelligence platforms structure multi-layer
technical data, and what that implies for the strategic-insights-tool's
5-layer (L1 Demand → L5 Capital) framework.

---

## 1. How peer platforms structure their IA

The competitive-intelligence space for hyperscaler / data-center / AI-infra
markets has crystallised around a handful of vendors. Each makes a clear
choice about which of our five layers (L1 Demand · L2 Computing Product ·
L3 Computing System · L4 Physical · L5 Capital & Timeline) it foregrounds,
and which it elides.

**SemiAnalysis – Datacenter Industry Model & AI Networking Model.**
The Datacenter Industry Model is sold as a workbook-style product (Excel
plus interactive views) with a top-level split between (a) facility-level
inventory of ~5,000 sites, (b) hyperscaler-level capex and self-build vs.
leased breakdowns, and (c) supply/demand reconciliation by region. The
AI Networking Model is a *separate* product focused on L3 (NIC, optics,
switch). Importantly, SemiAnalysis bundles L1 demand (accelerator
shipments, sovereign AI initiatives), L4 (power capacity, MW per site)
and L5 (capex by category — Power, Cooling, Facilities) inside one model,
but cleanly separates L2/L3 networking into its own SKU. Their IA choice
is **per-asset-class workbooks**, not a single nav. See:
https://semianalysis.com/datacenter-industry-model/ and
https://semianalysis.com/ai-networking-model/.

**DC Byte.** DC Byte is closest to a pure L4 tool: ~8,000 facilities,
"sweeping global views to minute granular detail," with a *map-first*
primary surface. Their innovation has been adding overlays — power,
fiber, renewables — directly on the map rather than as separate tabs.
This is essentially the "stack metaphor on a single canvas" approach.
They expose L4 deeply but only stub at L1 (demand) and L5 (capital);
see https://www.dcbyte.com/us/analytics/ and
https://www.dcbyte.com/news-blogs/fiber-connectivity-overlay-data-centre-infrastructure/.

**Synergy Research Group (SIA platform).** Synergy ships its
*Hyperscale Market Tracker* as an L5-first product: quarterly capex,
revenues, and 5-year forecasts by operator, with technology-spend
breakouts (compute, storage, networking, software, colo, land, build).
The taxonomy is **by-operator first, then by spend category**. L4 is
present (data-center footprint, critical IT load) but secondary. See
https://www.srgresearch.com/research/hyperscale-market-tracker.

**Dell'Oro Group.** Dell'Oro is the canonical L2/L3 vendor — their
*Data Center IT Capex* tracker segments the world into "Top 4 US Cloud,
Top 4 China Cloud, Top 3 Tier 2 Cloud, Rest-of-Cloud, Telco, Enterprise"
and exposes server, networking and storage shipments. The taxonomy is
**buyer-segment × component**, almost a matrix. Almost no L4 physical or
L1 demand. https://www.delloro.com/market-research/data-center-infrastructure/data-center-capex/.

**JLL & CBRE state-of-the-market reports.** Both are PDF-and-chart
report products (not really platforms), organised geographically: top-4
US markets first (Northern Virginia, Chicago, Atlanta, Phoenix), then
secondary markets, then global. CBRE leads with hyperscale-requirements
narrative; JLL leads with preleasing and capital flows. They are L4-
and L5-heavy, weak on L1/L2/L3. See
https://www.cbre.com/insights/books/north-america-data-center-trends-h2-2025
and https://www.jll.com/en-us/insights/market-outlook/data-center-outlook.

**Newmark.** Like JLL/CBRE but with a stronger "investor / capital
markets" framing — their 2025 U.S. Data Center Market Outlook is
explicitly pitched as L5 (capital flows) wrapped around L4 inventory.
https://www.nmrk.com/insights/market-report/2025-us-data-center-market-outlook.

**Aterio.** Aterio's bet is *signal granularity*, not taxonomy: hourly
updates on permits, rezoning, status changes, sourced from utility
records, satellite imagery, press releases. The platform is effectively
an L4 feed with timestamped change-events; L1/L2/L3 are absent.
https://www.aterio.io/premium/data-centers and
https://knowledge.aterio.io/data-products/real-time-us-development-signals.

**Omdia.** Omdia chose the *opposite* path from SemiAnalysis: instead
of one bundled model, they sell five distinct "Intelligence Services" —
Data Center Capacity & Investment (L4/L5), Data Center Compute (L3),
Data Center Networks (L3), Modular & Micro (L4), and Cloud Stack /
Operations (L2). Each service has its own dashboard. The IA decision
is **one product per layer**.
https://omdia.tech.informa.com/advance-your-business/cloud-and-data-center.

**NVIDIA's "AI Factory" reference dashboards.** These are operational,
not market-intel — Grafana/Prometheus on top of DCGM and NIM metrics,
plus partner-integrated Splunk and Weave dashboards for model and
workload monitoring. They show what an *L1-native* (workload-level)
view looks like and are useful as a contrast: very few competitive-
intel tools expose runtime/workload-layer signals at all.
https://www.nvidia.com/en-us/technologies/enterprise-reference-architecture/
and https://docs.nvidia.com/ai-enterprise/planning-resource/ai-factory-white-paper/latest/ai-factory-overview.html.

**Summary of the landscape:**

| Vendor          | Primary layer | Nav metaphor                  | L1 | L2 | L3 | L4 | L5 |
|-----------------|---------------|-------------------------------|----|----|----|----|----|
| SemiAnalysis    | L4 + L5       | Workbook / sheet              | M  | -  | M  | H  | H  |
| DC Byte         | L4            | Map + overlays                | -  | -  | -  | H  | L  |
| Synergy         | L5            | Operator × category matrix    | -  | -  | M  | M  | H  |
| Dell'Oro        | L2/L3         | Buyer segment × component     | -  | H  | H  | -  | M  |
| JLL / CBRE      | L4/L5         | Geography first               | -  | -  | -  | H  | M  |
| Newmark         | L5            | Capital-flows narrative       | -  | -  | -  | M  | H  |
| Aterio          | L4 (signal)   | Event feed                    | -  | -  | -  | H  | L  |
| Omdia           | per-layer     | One product per layer         | L  | M  | H  | H  | M  |
| NVIDIA AI Fac.  | L1            | Operational dashboard         | H  | M  | M  | L  | -  |

**Key takeaway:** *No public peer platform exposes all five layers in a
single coherent UI.* Most pick one or two layers as the home, and treat
others as overlays, side tabs, or separate products. This is a real
opportunity for the strategic-insights-tool, but it is also the source
of most of the IA risk discussed in §6.

---

## 2. Nav patterns for multi-layer technical intelligence

**Top-tab (current strategic-insights-tool pattern).** Cheap to build,
discoverable, but flattens hierarchy — every tab is peers, so users
can't tell that L4 (Power Contracts, Country Permits) is "one layer"
vs. L2/L3 (Supplier Insights). Works up to ~7 tabs; the current tool
already has 9. Per Nielsen-Norman's taxonomy guidance, a taxonomy with
more than ~7 levels of depth or breadth at one node creates cognitive
overhead (https://www.nngroup.com/articles/taxonomy-101/).

**Sidebar with grouped sections.** Lets us *show* the L1–L5 grouping
explicitly. Scales to 20+ items. Cost: vertical space; mobile-hostile.
Most enterprise SaaS (Linear, Stripe, Datadog) defaults here for this
reason.

**Layered drill-down ("stack").** AWS-console-style: pick a layer, then
a service inside it, then an instance. Honest about hierarchy, but slow
for cross-layer questions ("show me everything about Meta") because
every cross-cut requires either a saved view or a fresh drill.

**Bloomberg-style command bar.** The Bloomberg Terminal hides ~35,000
functions behind a 4-letter mnemonic command line and "panels" the
user can tile arbitrarily. Bloomberg's CTO has stated explicitly that
the design strategy is to "conceal complexity… across thousands of
functions, across domains and asset classes" so the user experiences
a seamless workflow (https://www.bloomberg.com/company/stories/how-bloomberg-terminal-ux-designers-conceal-complexity/).
Power-user-friendly; brutal onboarding. Good fit only once internal
users are dense and recurring.

**Notion-style breadcrumb hierarchy.** Everything is a page; the
hierarchy is implicit in URL and crumb trail. Great for *documents*,
poor for *dashboards* — users lose sense of which dimension they're
slicing.

**Recommendation seed (developed in §5):** for five layers, the
sidebar-with-grouping pattern is the structural backbone; a Bloomberg-
style command/quick-jump bar is the power-user accelerator; the
top-tab pattern should be retired or demoted to *intra-layer* tabs
inside each section.

---

## 3. Specific UX patterns we need

### 3a. Share-of-wallet / share-of-supply across many vendors per layer

The platform will repeatedly need to answer "of layer X, how is supply
split across N vendors?" — e.g., NIC suppliers per hyperscaler, GPU
allocation, power-purchase counterparties. Three workable patterns:

- **Stacked / 100% bar charts ordered by total magnitude** — the
  Synergy and Dell'Oro standard. Cheap, scannable, and the right
  baseline.
- **Marimekko / Mosaic** — width = total spend, height = share. Useful
  when both magnitude and share matter (e.g., total GPU spend × share
  by vendor). Good for executive briefings.
- **Small multiples of donut/bar per hyperscaler** — a 4×N grid where
  each cell shows one customer's vendor split. Slow to read but the
  best for direct visual diff. See small-multiples guidance at
  https://www.juiceanalytics.com/writing/parallel-coordinates.

Anti-patterns to avoid: pie charts with >5 slices; word clouds; any
chart that hides "unknown / unattributed" share. Given the ~78% mock-
data caveat, **every share chart must reserve a visible "uncertain"
band** rather than rounding it away.

### 3b. AI/LLM insights as a sidecar (not a peer tab)

The current `AI Insights` tab competes with layer tabs for top-level
real estate. Modern AI-dashboard guidance is converging on the
**copilot side-panel** pattern: AI insights live in a persistent right-
side rail that knows the user's current layer/filter context and emits
ranked narrative blocks ("what changed", anomalies, hypotheses)
alongside — not instead of — the human-curated dashboard. See
https://medium.muz.li/how-to-design-an-ai-assistant-users-actually-use-81b0fc7dc0ec
and https://www.databricks.com/product/business-intelligence/ai-bi-dashboards
for the Databricks AI/BI take, which embeds AI in context.

Concrete recipe:

- Persistent right rail (collapsible), 320–400px wide.
- Rail content is *context-bound* to the active layer and filters
  (player, region, time window).
- Each AI insight has: a one-line claim, a confidence chip, a "trace"
  affordance (which SQL / which docs / which session it came from),
  and a "pin to dashboard" action that converts the narrative into a
  human-curated card.
- A separate `/insights` route still exists for the cron-generated
  weekly report (see MEMORY: weekly cadence, Mon 09:00 UTC), but it's
  reached via a "weekly digest" button on the rail, not via a top-tab.

### 3c. Coverage, freshness and provenance (because 78% is mock)

This is the single biggest credibility risk and warrants its own
design language. From Smashing Magazine's "UX Strategies for Real-Time
Dashboards" (https://www.smashingmagazine.com/2025/09/ux-strategies-real-time-dashboards/),
the standard pattern is a **Data Freshness Indicator** widget — last-
updated timestamp, sync status pill, manual refresh button — present
on every dashboard surface. Additional patterns we need:

- **Stale data should *look* stale** — desaturate, dashed borders, or
  a "Data as of 2026-04-22" stamp on every card. Live data is the
  default visual; cached/mock is the visually-degraded variant.
- **Provenance tag per data point**: a small badge on each card —
  `LIVE` (live API), `CACHED` (last good fetch), `MOCK` (seeded
  estimate), `LLM` (model-generated). The current 78% mock proportion
  must be surfaced, not hidden.
- **Coverage meter per layer**: at the top of each layer landing, a
  thin progress bar "L4 Physical: 41 of 60 tracked sites have live
  power data" — borrowed from AI-ML dashboard explainability patterns
  (https://thefinch.design/ux-best-practices-ai-ml-data-visualization-dashboards/).
- **"What changed" annotations** on timeline charts — see same source.
  This pairs especially well with our weekly cadence: every Monday's
  AI-Insights run can drop annotations onto the relevant timelines.

---

## 4. Recommended visualization patterns by layer

| Layer | Question typically asked | Recommended primary viz | Backup viz |
|------|--------------------------|--------------------------|------------|
| **L1 Demand** | "Which workloads / customers / regions are driving GPU-hour demand?" | Stacked area over time + scenario fan-chart | Sankey: workload → cluster → region |
| **L2 Computing Product** | "How is GPU/CPU/NIC pricing & availability moving?" | Small-multiples line charts per SKU; one row per vendor | Heatmap (SKU × quarter) of $/GPU-hour |
| **L3 Computing System** | "Who builds with what (NVL72 vs. Trainium vs. MI300 racks)?" | Marimekko of system-mix per hyperscaler | Sankey: chip → rack → operator |
| **L4 Physical** | "Where is power/permits/water binding?" | Choropleth (state-level) + bubble overlay (site MW) | Timeline gantt for permits |
| **L5 Capital & Timeline** | "Where is $ flowing and when does it land?" | Waterfall (capex by category) and Sankey (source → site → MW online) | Forward-curve fan chart |
| **Cross-layer triangulation** | "Does Meta's L5 capex match L4 site MW and L3 chip orders?" | Parallel-coordinates scorecard or radar | Per-player one-pager |

Choropleth-vs-bubble caveat: choropleths assume roughly equal-area
regions; for US state data centers that breaks down badly (Virginia
dominates). Use a **bubble map for site capacity** and a choropleth
only for normalized metrics (MW per GW grid, permits per capita).
Best-practice sourcing: https://dataviz.unhcr.org/chart-types/geospatial/
and https://www.data-to-viz.com/graph/bubblemap.html.

Parallel-coordinates is the right tool for cross-layer triangulation
when N players is 5–20 — exactly our hyperscaler + neocloud universe.
See https://www.juiceanalytics.com/writing/parallel-coordinates for
when it works and when to fall back to small multiples.

---

## 5. Recommended navigation taxonomy

**Argument:** of the three options — by-Layer, by-Player, by-Region —
no peer platform actually uses pure layer-first. SemiAnalysis bundles
layers per *asset class*. Synergy and Newmark go *player-first*.
DC Byte, JLL, CBRE, Aterio go *geography-first*. Omdia is the closest
to layer-first, but only by selling each layer as a separate SKU.

The strategic-insights-tool's competitive edge is **cross-layer
reasoning** (L5 capex must match L4 MW must match L3 chip orders must
match L1 demand). That argues *against* a pure player or geo nav,
because those slice horizontally and hide cross-layer mismatches.

**Recommended hybrid: Layer × Player matrix as nav backbone, with
Region and Time as global filters.**

Concrete shape:

- **Left sidebar grouped by Layer.** Top group "L1 Demand", then L2
  Compute Product, L3 Compute System, L4 Physical, L5 Capital. Each
  group expands to 2–4 sub-pages (e.g., L3 → GPU Supply, NIC/Optics,
  Foundry/TSMC; L4 → Sites, Power Contracts, Permits).
- **Global filter strip** at top: Player (multi-select hyperscaler
  + neocloud), Region (US/EU/APAC/MEA), Time window. Filters persist
  across layer navigation. This is what gives us the "Player view"
  for free without committing a top-level axis to it.
- **A `/player/{ticker}` route** that re-aggregates *all* layers for
  one player on one page — this is the "single company view" escape
  hatch described in §6. The existing `Companies` tab is the seed
  for this.
- **A Bloomberg-style command bar** (Cmd-K) for power users: `META L4`,
  `VST capex`, `H200 supply` — jumps directly to the right
  layer+player+filter state. Bloomberg's own UX argument (concealing
  complexity, https://www.bloomberg.com/company/stories/how-bloomberg-terminal-ux-designers-conceal-complexity/)
  applies here: the matrix gives us 5 layers × ~15 players × 4 regions =
  ~300 cells, and a command bar is the only humane way to navigate
  that.
- **Triangulation as a top-level destination, not a tab inside a
  layer.** This is where parallel-coordinates / scorecard views live;
  it's also where the OCI competitive narrative gets surfaced.

This matches what Synergy quietly does inside SIA (operator × category
matrix) and what Omdia does across SKUs, while keeping the user inside
one app.

---

## 6. Risks of forcing the 5-layer model

A layered taxonomy hurts when the user's mental model is *not* layered.
Cases to design around:

1. **Single-company view.** An analyst answering "what's Meta doing?"
   does not want to traverse five layer tabs and re-filter to Meta in
   each. The peer-platform evidence (Synergy's operator-first IA;
   CBRE's Q&A reports that lead with hyperscaler-by-hyperscaler
   narrative) shows this is the dominant workflow for ~50% of
   sessions. Mitigation: a first-class `/player/{ticker}` page that
   re-shows every layer in collapsible sections for that one player.

2. **Single-region view.** Local-permit and grid-constraint questions
   are inherently geographic; forcing them through L4 → Permits → filter
   by region adds friction. Mitigation: a `/region/{slug}` route that
   mirrors the player page.

3. **Cross-layer events.** "ERCOT just curtailed; what does that
   mean?" cuts L4 (grid) → L1 (workload availability) → L5 (capex
   timing). No single layer page is correct. Mitigation: the AI-
   Insights sidecar is *exactly* the surface for these events; it
   should be cross-layer-by-default. Also: a dedicated `/triangulation`
   destination as in §5.

4. **Taxonomy drift over time.** Per Earley
   (https://www.earley.com/insights/why-information-taxonomy-must-represent-landscape-business)
   and the Optimal Workshop taxonomy guide
   (https://www.optimalworkshop.com/blog/how-to-develop-a-taxonomy-for-your-information-architecture),
   no single navigational structure survives 2+ years of product
   evolution; "there is no single way to look at all information."
   The implication: bake in the ability to add a sixth or seventh
   layer (e.g., L6 Regulatory, L7 Workforce) without renumbering, and
   keep URL slugs semantic (`/physical/...`) not numeric
   (`/l4/...`).

5. **The "mock data tax."** A layered IA *exposes* coverage gaps in
   each layer cell. With ~78% mock today, half the cells will look
   empty. This is healthy long-term (it focuses ingestion work) but
   short-term it can erode user trust. Mitigation: the freshness/
   provenance system in §3c is non-optional; coverage meters per
   layer become the engineering scoreboard.

6. **Onboarding cliff.** Layered models reward repeat use and punish
   first-time visitors. Karan's feedback loop is internal, so this is
   tolerable, but any external demo will need a "guided tour" entry
   point that shows the cross-layer narrative on a single curated
   player (probably Meta or CoreWeave) before exposing the matrix.

---

## 7. Net recommendation (one paragraph)

Adopt a **Layer × Player hybrid** with the layers as a grouped left
sidebar, Player/Region/Time as persistent global filters, a Bloomberg-
style command-bar for power users, a first-class `/player` and
`/region` view as escape hatches from the layered taxonomy, and the
AI Insights output relocated from a peer top-tab into a persistent,
context-aware right-rail sidecar. Visualizations per layer follow the
table in §4. Every card carries a provenance badge and freshness stamp;
every layer landing carries a coverage meter that names the mock-vs-
live ratio. The Triangulation page becomes the headline destination
that demonstrates the cross-layer value of the tool — this is what no
peer platform currently delivers.

---

## References

- SemiAnalysis Datacenter Industry Model — https://semianalysis.com/datacenter-industry-model/
- SemiAnalysis AI Networking Model — https://semianalysis.com/ai-networking-model/
- DC Byte Analytics platform — https://www.dcbyte.com/us/analytics/
- DC Byte Fiber Connectivity Overlay — https://www.dcbyte.com/news-blogs/fiber-connectivity-overlay-data-centre-infrastructure/
- Synergy Research Hyperscale Market Tracker — https://www.srgresearch.com/research/hyperscale-market-tracker
- Dell'Oro Data Center IT Capex — https://www.delloro.com/market-research/data-center-infrastructure/data-center-capex/
- CBRE North America Data Center Trends H2 2025 — https://www.cbre.com/insights/books/north-america-data-center-trends-h2-2025
- JLL 2026 Global Data Center Outlook — https://www.jll.com/en-us/insights/market-outlook/data-center-outlook
- Newmark 2025 US Data Center Market Outlook — https://www.nmrk.com/insights/market-report/2025-us-data-center-market-outlook
- Aterio US Data Centers product — https://www.aterio.io/premium/data-centers
- Aterio Real-Time Development Signals — https://knowledge.aterio.io/data-products/real-time-us-development-signals
- Omdia Cloud & Data Center suite — https://omdia.tech.informa.com/advance-your-business/cloud-and-data-center
- NVIDIA Enterprise Reference Architectures — https://www.nvidia.com/en-us/technologies/enterprise-reference-architecture/
- NVIDIA Enterprise AI Factory white paper — https://docs.nvidia.com/ai-enterprise/planning-resource/ai-factory-white-paper/latest/ai-factory-overview.html
- Bloomberg Terminal UX (concealing complexity) — https://www.bloomberg.com/company/stories/how-bloomberg-terminal-ux-designers-conceal-complexity/
- Smashing Magazine, UX Strategies for Real-Time Dashboards — https://www.smashingmagazine.com/2025/09/ux-strategies-real-time-dashboards/
- Finch, UX Best Practices for AI/ML Data Visualisation Dashboards — https://thefinch.design/ux-best-practices-ai-ml-data-visualization-dashboards/
- Muzli, How to Design an AI Assistant — https://medium.muz.li/how-to-design-an-ai-assistant-users-actually-use-81b0fc7dc0ec
- Databricks AI/BI Dashboards — https://www.databricks.com/product/business-intelligence/ai-bi-dashboards
- Juice Analytics on parallel-coordinates — https://www.juiceanalytics.com/writing/parallel-coordinates
- Data-to-Viz, bubble maps — https://www.data-to-viz.com/graph/bubblemap.html
- UNHCR Data Viz Standards — choropleth — https://dataviz.unhcr.org/chart-types/geospatial/
- Nielsen Norman Group, Taxonomy 101 — https://www.nngroup.com/articles/taxonomy-101/
- Optimal Workshop, How to develop a taxonomy for your IA — https://www.optimalworkshop.com/blog/how-to-develop-a-taxonomy-for-your-information-architecture
- Earley, Information Taxonomy Must Represent the Landscape of the Business — https://www.earley.com/insights/why-information-taxonomy-must-represent-landscape-business
