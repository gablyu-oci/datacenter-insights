# Strategic Insights Tool — UX Flow Proposal

**Author:** Product Design
**Date:** 2026-05-19
**Status:** Draft for review
**Source framework:** `docs/DataCenter Knowledge Layers/` (L1 Demand → L2 Product → L3 System → L4 Physical → L5 Capital & Timeline)

---

## 0. Problem statement

Today the app exposes ~10 sibling tabs in a mostly flat top-nav. The mental model the team actually reasons in is the 5-layer industry framework: demand pulls product, product depends on system, system depends on physical buildout, and the whole stack is paced by capital and lead times. Users currently land on a Data Centers Overview (an L3/L4 view) and have no way to climb up to "why" (L1 Demand) or down to "when" (L5 Capital & Timeline). AI Insights — the highest-value synthesis layer — sits as one tab among many, disconnected from whatever the user is currently looking at.

Goal: restructure navigation, page assignments, and the AI Insights surface so that every screen has an explicit layer identity and every user journey climbs or descends the ladder rather than hopping sideways through unrelated tabs.

---

## 1. Personas

### Persona A — Priya, OCI Strategy Lead (executive consumption)
- **Role:** Reports into the OCI EVP; prepares monthly competitive briefs and quarterly board readouts.
- **Top jobs-to-be-done:**
  1. Tell a one-page story this week about where OCI is gaining/losing vs. AWS, Azure, GCP, Meta, CoreWeave.
  2. Spot inflection points (a competitor's capex acceleration, a permit denial, a power-contract win) before they appear in press.
  3. Defend or attack a narrative with citations she can paste into a deck.
- **Current friction:** Lands on Data Centers Overview, which is granular site rows; has to manually stitch demand context from earnings calls and synthesis from AI Insights. No persistent "what changed this week" surface.
- **Layer affinities:** L1 (demand), L5 (capital pacing), AI Insights drawer. Rarely opens L3/L4 detail.

### Persona B — Marco, OCI Product Manager (pitch builder)
- **Role:** Owns a GPU SKU or a regional capacity offer; builds win/loss decks and pricing positioning.
- **Top jobs-to-be-done:**
  1. Compare OCI's GPU-hour and MW-lease pricing to CoreWeave / Lambda / Azure for a specific instance family.
  2. Quantify the supply ceiling on a competitor (e.g., how many H200s can CoreWeave actually rack by Q3?).
  3. Find an evidence-backed insight to ground a new pitch ("AWS lead times in NoVA are slipping — here's our window").
- **Current friction:** Pricing data does not exist as a first-class page. Supplier supply pages (GPU, NICs, Wafer) are buried in a dropdown and don't connect back to product. Has to flip between Earnings Calls and Companies tabs and re-context-switch.
- **Layer affinities:** L2 (product), L3 (system supply), AI Insights drawer for synthesis.

### Persona C — Dana, OCI Sales Engineer (site-specific lookups)
- **Role:** Embedded with regional sales; gets paged by reps before customer meetings.
- **Top jobs-to-be-done:**
  1. "What is Microsoft doing within 50 mi of Columbus, OH, and when does it energize?"
  2. Verify a specific data center's MW, owner, status, and substation interconnect timeline.
  3. Find the latest news/earnings quote about a specific competitor's regional plan.
- **Current friction:** Data Centers Overview lists everything globally; filtering is shallow. Country Permits is geo-anchored but separate from the site list. No breadcrumb that takes her from a site back up to "what does this mean for the competitor's overall posture?"
- **Layer affinities:** L4 (physical), L5 (timeline), occasionally L1 to read the competitor's own demand framing.

---

## 2. Top user journeys

Each journey is written as: **Entry → Intent → Current path → Current friction → Proposed path (layered IA).**

### Journey 1 — "How is OCI's contracted MW share growing vs. AWS over the last 4 quarters?" (Priya)
1. **Entry:** Monday morning, opens the tool from a Slack link.
2. **Intent:** A trended share-of-MW chart with a one-paragraph narrative she can lift.
3. **Current path:** Lands on Data Centers Overview → filters by owner = AWS → exports a CSV → pivots in Excel → no narrative.
4. **Current friction:** No trend view; no narrative; AI Insights is a separate tab with stale framing.
5. **Proposed path:**
   a. Lands on Home (a new L1→L5 ladder view).
   b. Clicks **L5 Capital & Timeline → Contracted MW Share**.
   c. Sees a 4-quarter stacked-share chart with AWS/Azure/GCP/Meta/Oracle/CoreWeave bands.
   d. AI Insights right-rail auto-filters to L5 and shows "AWS contracted MW grew 14% QoQ — Northern Virginia + Phoenix drove 60% of the delta" with citations.
   e. Click-through on the insight opens the underlying sites in a side drawer (L4 detail) without losing her place on the L5 chart.

### Journey 2 — "Which neoclouds are showing the biggest capex-vs-contracted-power imbalance?" (Priya, Marco)
1. **Entry:** Triggered by a CoreWeave news headline.
2. **Intent:** Identify neoclouds whose announced spend outruns the power they have actually contracted (a tenancy/financing risk signal).
3. **Current path:** Companies tab (mock) → Triangulation tab (mock) → AI Insights tab (no filter for neoclouds).
4. **Current friction:** The cross-layer math (capex from L5, contracted MW from L4) requires manual stitching.
5. **Proposed path:**
   a. Home → **L5 Capital & Timeline → Capex vs. Contracted Power**.
   b. Scatter: x = announced capex YTD, y = contracted MW; bubble color = tenancy %.
   c. Layer ladder highlights L5; clicking a neocloud bubble drills into a per-company panel that surfaces L1 demand framing (earnings quotes), L4 sites, and L5 financing.
   d. AI Insights drawer shows "Neoclouds with imbalance > 1.5σ" pinned card.

### Journey 3 — "Where will AWS exceed grid-interconnect lead times in Northern Virginia?" (Dana, Marco)
1. **Entry:** Sales call prep, customer is asking about NoVA capacity.
2. **Intent:** A map + table of AWS NoVA sites with energization risk vs. promised dates.
3. **Current path:** Data Centers Overview → filter region = NoVA, owner = AWS → switch to Country Permits → no link back.
4. **Current friction:** Permits and sites are decoupled; no lead-time risk score.
5. **Proposed path:**
   a. Home → **L4 Physical → Sites & Substations** (map view, default).
   b. Filter chip: owner = AWS, region = NoVA.
   c. Each site card shows an L5 chip ("Energize ETA Q3-26 · grid lead-time risk: HIGH").
   d. AI Insights drawer auto-filters to L4 NoVA: "Two AWS sites depend on Loudoun-2 substation; PJM queue position implies +2 quarter slip."

### Journey 4 — "What is the GPU-hour pricing gap between OCI and CoreWeave for H200 reserved capacity?" (Marco)
1. **Entry:** Building a competitive pricing slide.
2. **Intent:** A SKU-by-SKU price comparison with a freshness chip and source link.
3. **Current path:** **Does not exist today.** Marco emails the pricing team.
4. **Current friction:** No L2 (product) page at all in the current IA.
5. **Proposed path:**
   a. Home → **L2 Computing Product → Pricing Compare**.
   b. Choose SKU family (H100, H200, B200, MI300X) → reservation term (on-demand / 1y / 3y).
   c. Bar chart per provider; freshness chip per cell; source link opens the original price page or earnings quote.
   d. AI Insights drawer: "OCI is 18% below CoreWeave on H200 3y reserved as of this week."

### Journey 5 — "Why did NVIDIA Data Center revenue grow X% but TSMC packaging didn't?" (Priya, Marco)
1. **Entry:** Earnings week.
2. **Intent:** Understand the disconnect between demand (NVDA top-line) and supply (CoWoS packaging throughput).
3. **Current path:** Earnings Calls tab → Wafer Production (TSMC) tab (in the Supplier dropdown) → no synthesis.
4. **Current friction:** L1 demand and L3 system are in different parts of the nav with no bridge.
5. **Proposed path:**
   a. Home → ladder highlight on **L1 → L3** ("Demand pull vs. supply ceiling").
   b. Dual-axis chart: NVDA DC revenue (L1) vs. TSMC CoWoS wafer-equivalents (L3) over 8 quarters.
   c. Annotations call out inventory build, packaging constraint, advanced-package mix.
   d. AI Insights drawer pins the synthesis: "Demand outran packaging by ~Q in 2026Q1; CoWoS-L ramp closes the gap by 2026Q4."

---

## 3. Proposed information architecture

### 3.1 Top-level model
A persistent **Layer Ladder** is the spine of the IA. It lives as a left rail on desktop (collapsible to icons) and as a top strip on narrow viewports. Every page declares which layer it belongs to; the ladder highlights that layer and dims the others.

```
+----------------------------------------------------------------------+
|  STRATEGIC INSIGHTS                       [search]  [freshness] [me] |
+----+-----------------------------------------------------------+-----+
| L1 |  Breadcrumb: Home / L5 Capital & Timeline / Contracted MW |  A  |
| L2 |-----------------------------------------------------------|  I  |
| L3 |                                                           |     |
| L4 |              <PAGE CONTENT FOR CURRENT LAYER>             |  D  |
| L5 |                                                           |  R  |
|    |                                                           |  A  |
|    |                                                           |  W  |
|    |                                                           |  E  |
|    |                                                           |  R  |
+----+-----------------------------------------------------------+-----+
| Coverage: 22% real · 78% mock     Last refresh: 2026-05-19 09:00 UTC |
+----------------------------------------------------------------------+
```

The left rail is the **Layer Ladder**. The right drawer is the **AI Insights** surface, layer-aware and collapsible. The bottom strip is a global coverage/freshness banner.

### 3.2 Home page wireframe

```
+----------------------------------------------------------------------+
|  Welcome back, Priya.       This week: 14 new insights · 3 critical  |
+----------------------------------------------------------------------+
|  L1  AI DEMAND          "Where AI demand comes from"                 |
|     [card] Hyperscaler capex guidance  [card] Token-volume proxy     |
|     [card] Enterprise adoption tracker                               |
+----------------------------------------------------------------------+
|  L2  COMPUTING PRODUCT  "What customers actually buy"                |
|     [card] GPU-hour pricing  [card] MW-lease pricing  [card] SKU mix |
+----------------------------------------------------------------------+
|  L3  COMPUTING SYSTEM   "What makes the product possible"            |
|     [card] GPU supply  [card] NICs & optics  [card] Chip supply chain|
+----------------------------------------------------------------------+
|  L4  PHYSICAL           "Where it lives in the world"                |
|     [card] Sites map  [card] Power contracts  [card] Country permits |
+----------------------------------------------------------------------+
|  L5  CAPITAL & TIMELINE "How fast and at what cost"                  |
|     [card] Contracted MW share  [card] Time-to-power  [card] Capex   |
+----------------------------------------------------------------------+
```

Each layer band is a horizontally scrollable strip of cards. Every card has a freshness chip, a coverage chip, and a single sparkline. Clicking a card opens that layer's detail page.

### 3.3 Per-layer page wireframe

```
+----------------------------------------------------------------------+
| L5 CAPITAL & TIMELINE — "How fast and at what cost"                  |
| Sub-nav: Contracted MW | Capex vs Power | Time-to-Power | Depreciation|
+----------------------------------------------------------------------+
|  [filter chips: owner, region, quarter window]                       |
|  +------------------------------------------------------------+      |
|  |                  primary chart (full width)                |      |
|  +------------------------------------------------------------+      |
|  +-------------------------+ +------------------------------+        |
|  | secondary table         | | annotation timeline          |        |
|  +-------------------------+ +------------------------------+        |
|                                                                      |
|  Related layers: < L4 Physical (drill down)   > none                  |
+----------------------------------------------------------------------+
```

The "Related layers" footer is critical: every page exposes one-click climbs/descents so the user never has to return to Home to change layer.

### 3.4 Navigation rules
- **Top nav** retires. Replaced by the Layer Ladder + Home + global search.
- **Breadcrumb** always reads `Home / L{n} {Layer} / {Page}`.
- **AI Insights** retires as a top tab and becomes the right drawer (toggle key: `I`). When open, it filters by the current layer; a chip lets the user widen to "all layers".
- **Search** is global; results are grouped by layer.
- **Supplier Insights** dropdown is dissolved; its children move into L3.

---

## 4. Page-by-page recommendations (current tabs)

| Current tab | Action | New home | Rationale |
|---|---|---|---|
| Data Centers Overview | **Rename + split** | L4 → "Sites & Substations" (map default) and L5 → "Contracted MW Share" (trend default) | The current tab conflates physical inventory (L4) with capital/timeline aggregates (L5). |
| AI Insights | **Retire as tab; reposition as right drawer** | Persistent right rail, layer-aware | High-value synthesis must be co-located with the evidence the user is viewing. |
| Power Contracts | **Keep + relocate** | L4 → "Power Contracts" | Power-purchase data is a physical-buildout artifact; it pairs with site rows. |
| GPU Supply (dropdown) | **Promote to L3** | L3 → "GPU Supply" | Supply-side ceiling on the L2 product. |
| NICs & Optics Supply (dropdown) | **Promote to L3** | L3 → "NICs & Optics" | Same layer family as GPU supply. |
| Wafer Production (TSMC) (dropdown) | **Merge** | L3 → "Chip Supply Chain" panel | TSMC wafer + CoWoS packaging is the upstream constraint on GPU supply; keep them together. |
| Country Permits | **Keep + relocate** | L4 → "Country Permits" | Permits are a physical-buildout artifact; pair with sites. |
| Companies | **Rename + relocate** | Cross-cutting "Company Profile" drawer; entry points from any layer | A company is a cross-layer entity, not a layer itself. |
| Triangulation (MOCK) | **Retire from top nav; demote to a labeled experiment under L5** | L5 → "Triangulation (Lab)" | Currently mock and disorients users; preserve as a lab. |
| Data Sources | **Keep; move to footer + settings** | Global footer link | Operational, not analytical; doesn't belong in primary nav. |
| Earnings Calls | **Rename + relocate** | L1 → "Demand Signals — Earnings" | Earnings transcripts are the primary demand-signal source. |

---

## 5. New pages to add (by layer)

### L1 — AI Demand
- **AI Demand Signals** (P0): earnings-derived demand sentiment per hyperscaler (capex guide deltas, "AI" mention count, tone), token-volume proxy from public model-provider usage stats, enterprise-adoption tracker (deal announcements > $50M).
- **Hyperscaler Capex Guidance** (P0): consensus vs. actual capex per quarter with revision arrows.

### L2 — Computing Product
- **Pricing Compare** (P0): GPU-hour, GPU-month, MW-lease, and token-output pricing across OCI / AWS / Azure / GCP / CoreWeave / Lambda. SKU-by-SKU. Each cell carries a freshness chip.
- **SKU Availability Matrix** (P1): which providers offer which SKUs, with reservation terms and waitlists.

### L3 — Computing System
- **Chip Supply Chain** (P0): TSMC wafer-equivalents, CoWoS-S/L/R packaging throughput, HBM3e supply, advanced-substrate yield.
- **Networking Fabric** (P1): NIC + optics supply, scale-up vs. scale-out fabric choices per provider.

### L4 — Physical
- **Sites & Substations** (P0): map default, with substation overlay and interconnect-queue chips.
- **Power Contracts** (P0, existing data): co-located.
- **Country Permits** (P0, existing data): co-located.

### L5 — Capital & Timeline
- **Contracted MW Share** (P0): 4-/8-quarter trended share by owner.
- **Capex vs. Contracted Power** (P0): scatter, tenancy overlay.
- **Time-to-Power & Time-to-Revenue Dashboard** (P0): per-site lead-time distribution from permit → energize → revenue.
- **GPU Depreciation Tracker** (P1): assumed-life vs. actual replacement cadence; sensitivity on hyperscaler margins.

---

## 6. AI Insights re-positioning

**Today:** A top-level tab. The user must leave their current screen to consume synthesis, and the synthesis is not aware of what they were looking at.

**Proposed:** A persistent right drawer ("Insights"), 360–420 px wide on desktop, collapsible to a 32 px vertical strip. Toggle with `I`. Behavior:

1. **Layer-aware filtering.** When the user is on an L4 page, the drawer shows L4-tagged insights first, with a "show all layers" chip.
2. **Entity-aware filtering.** When a filter chip is set (e.g., owner = AWS), the drawer narrows further.
3. **Pinning.** Critical insights pin to the top with a coloured rail.
4. **Subscribe.** Per-layer or per-entity subscribe surfaces the existing weekly cron output.
5. **Save & history.** The existing save/history work plugs in cleanly; the drawer has tabs `Latest | Saved | History`.
6. **Citations always one click away.** Each insight card exposes "view evidence" which opens a side panel anchored to the underlying chart/table.

**Rationale:** Synthesis without context is just a newsletter. Co-location keeps the cognitive distance between "what I'm looking at" and "what it means" near zero, which is the whole point of the tool.

---

## 7. Coverage & freshness UX

Three layered surfaces, from global to atomic:

1. **Global banner (footer strip).** Always shows `Coverage: 22% real · 78% mock · Last refresh: {ISO timestamp}`. Click expands a modal with a per-layer breakdown.
2. **Per-layer scorecard.** On every layer detail page, a compact card above the primary chart: a 5-bar mini-grid where each bar is a sub-page's coverage percent, color-coded green (>70%) / amber (30–70%) / red (<30%).
3. **Per-card freshness chip.** Every card and table cell that depends on data carries a small chip: `LIVE · 2d ago`, `MOCK`, or `STALE · 41d ago`. Mock is rendered with a diagonal-stripe background so it is unmistakable even without reading the label.

Accessibility: never rely on color alone — every chip carries a text label and an icon (filled-circle / hollow-circle / dashed-circle).

---

## 8. Layer ladder microcopy

These taglines appear under each layer label in the ladder and on the Home page. They teach the framework on every navigation.

- **L1 — AI Demand.** "Where AI demand comes from." Hyperscaler capex, enterprise adoption, token consumption.
- **L2 — Computing Product.** "What customers actually buy." GPU-hour pricing, MW leases, managed-token endpoints.
- **L3 — Computing System.** "What makes the product possible." GPUs, networking fabric, the wafer-to-package chain.
- **L4 — Physical.** "Where it lives in the world." Sites, substations, permits, power contracts.
- **L5 — Capital & Timeline.** "How fast and at what cost." Capex pacing, contracted MW share, time-to-power, depreciation.

Tone: declarative, six words or fewer for the headline, one sentence of body. Avoid jargon ("hyperscale", "neocloud", "interconnect") in the tagline itself; use it freely in the body.

---

## 9. Accessibility & dark-mode considerations

The app already uses `#0f172a` (background), `#1e293b` (surface), `#3b82f6` (indigo accent). Extend the token set:

- **Background:** `#0f172a` (app), `#1e293b` (surface), `#0b1220` (drawer/sidebar darker).
- **Foreground:** `#e2e8f0` (primary text), `#94a3b8` (secondary), `#64748b` (tertiary).
- **Accent:** `#3b82f6` (primary action), `#60a5fa` (hover).
- **Layer rails (left-edge color rail per layer, for legibility, not for meaning alone):**
  - L1 `#a78bfa` (violet) — demand
  - L2 `#34d399` (emerald) — product
  - L3 `#f59e0b` (amber) — system/supply
  - L4 `#38bdf8` (sky) — physical
  - L5 `#f472b6` (pink) — capital/time
- **Freshness:** LIVE `#22c55e`, STALE `#f59e0b`, MOCK `#94a3b8` with stripe pattern.
- **Critical insight rail:** `#ef4444`.

Accessibility:
- Minimum contrast 4.5:1 for body text against `#0f172a` and `#1e293b`. The token set above clears AA at 14 px.
- All color-coded chips and rails carry a redundant text label and icon shape; color is never the sole carrier of meaning.
- Layer ladder is keyboard-navigable (`1`–`5` jump to layers, `H` home, `I` toggle insights, `/` focuses search).
- Focus states use a 2 px `#60a5fa` outline with 2 px offset.
- All charts ship an "Open data table" link for screen-reader users.
- Map and scatter plots ship a list-view toggle.
- Respect `prefers-reduced-motion`: ladder transitions and drawer slide-in collapse to instant for those users.

---

## 10. Priority bands

### P0 — must ship to fix the original complaint
- Introduce the Layer Ladder shell (left rail + breadcrumb).
- Move AI Insights to the right drawer with layer-aware filtering.
- Reorganize the existing tabs into L1–L5 mappings (Earnings → L1; GPU/NICs/Wafer → L3; Sites/Power/Permits → L4; Contracted MW + Triangulation lab → L5).
- New Home page with the 5 horizontal layer bands.
- Global coverage banner + per-card freshness chip.
- New pages: L1 Demand Signals, L2 Pricing Compare, L5 Contracted MW Share, L5 Capex vs. Power, L5 Time-to-Power.

**Rationale:** Together these resolve the "flat, L3/L4-dominated nav with orphaned AI Insights" complaint and unlock journeys 1–5.

### P1 — high value, follow-on
- L1 Hyperscaler Capex Guidance page.
- L3 Networking Fabric page; merge of Wafer into Chip Supply Chain panel.
- L5 GPU Depreciation Tracker.
- L2 SKU Availability Matrix.
- Per-layer coverage scorecard above each detail page.
- Company Profile cross-cutting drawer (entry from any layer).
- Subscribe by layer / by entity.

**Rationale:** Deepen each layer once the spine is in place; unlock Marco's and Priya's secondary jobs.

### P2 — nice-to-have, defer
- Layer-pair "bridge" pages (e.g., L1↔L3 demand-vs-supply dual-axis as a first-class page rather than a chart on the L1 page).
- Triangulation Lab redesign (currently mock).
- Saved-view sharing and deck-export.
- Mobile/narrow-viewport polish of the ladder.
- Personalization (per-persona default landing layer).

**Rationale:** Polish and power-user features; pursue after the IA settles and instrumentation tells us which journeys actually dominate.

---

## Appendix A — Open questions for review

1. Do we want the ladder to be left-rail (recommended) or top-strip on desktop? Left-rail preserves vertical scroll for content; top-strip is more discoverable for first-time users.
2. Should AI Insights drawer be open or collapsed by default? Recommendation: open for Priya (strategy lead) persona, collapsed for Dana (sales engineer). Persist per user.
3. Where does Companies live? Recommendation: cross-cutting drawer reachable from any layer (not a layer itself). Confirm with engineering that the existing Companies tab data model supports this.
4. Triangulation: kill or relabel? Recommendation: relabel to "Triangulation (Lab)" inside L5 with a persistent "experimental" badge until real data lands.
5. Do we ship the Layer Ladder behind a feature flag for an A/B against current nav, or hard-cut? Recommendation: hard-cut; the current nav is the complaint.

---

## Appendix B — Out of scope for this document

- Visual design system tokens beyond the additions in section 9.
- Backend data-model changes required to surface per-card freshness (handled by the existing freshness work in `.openclaw/workspace/FRESHNESS.md`).
- Detailed copy for every card; section 8 only covers the layer-level taglines.
- Mobile layout beyond "ladder collapses to top strip".

---

*End of proposal.*
