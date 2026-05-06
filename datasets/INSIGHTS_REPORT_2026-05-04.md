# Datacenter & Power Infrastructure — Strategic Insights
**Source datasets:** `data_center_inventory_20260428.csv` (6,973 facilities), `Energy Project Inventory Data Sample.xlsx` (84 plant phases), `Aterio expanded sample dataset.xlsx` (247-row preview, same schema as inventory), `Data Centers Data Dictionary.xlsx` (metadata)
**Scope:** US (94.8%) + Canada (5.2%). Date generated: 2026-05-04.

---

## Headline numbers

| Metric | Value |
|---|---|
| Facilities tracked | **6,973** |
| Total nominal capacity | **434.6 GW** |
| Active capacity | 47.7 GW (11.0%) |
| Under construction | 57.5 GW (13.2%) |
| Announced (not yet built) | **295.5 GW (68.0%)** |
| Failed (cancelled / withdrawn / not approved) | 24.8 GW (5.7%) |
| **Pipeline ÷ active ratio** | **7.4× — buildout will quadruple the installed base if all delivers** |
| AI-flagged capacity (where flag set) | 173.4 GW (39.9% of total — **undercount**, see DQ note) |
| Behind-the-meter (onsite power) capacity | 135.4 GW (31.1%) |

---

## 1. The capacity wave is real and accelerating

Annual announcement volume by MW capacity:

| Year | MW announced | YoY |
|---|---|---|
| 2022 | 9,116 | — |
| 2023 | 21,655 | 2.4× |
| 2024 | 80,794 | **3.7×** |
| 2025 | **198,864** | **2.5×** |
| 2026 (partial, ~4 months) | 52,594 | on pace for ~157 GW full-year |

**One year (2025) added ~5× the entire active fleet's capacity.** Activations are forecast to peak in **2029 (60.7 GW) and 2030 (37.5 GW)** based on planned activation dates — meaning the grid impact lands hardest in 2028–2031, not now.

---

## 2. Geographic concentration: Texas leads on MW, Virginia on count

**By total capacity (all stages):**

| State | MW | Sites |
|---|---|---|
| **Texas** | **88,397** | 995 |
| **Virginia** | 62,561 | 1,083 |
| Georgia | 30,015 | 444 |
| Ohio | 26,977 | 310 |
| Utah | 20,069 | 155 |
| Arizona | 18,047 | 276 |
| Pennsylvania | 16,344 | 227 |
| Illinois | 15,198 | 236 |
| Alberta (CA) | 13,412 | 109 |
| New Mexico | 11,863 | 81 |

**Read:** Texas is now the #1 datacenter market by MW — overtaking Virginia. Virginia has *more* facilities but smaller average size; Texas is concentrating mega-builds. New Mexico and Utah are emerging hyperscale targets (very high MW/site).

**Grid concentration risk:** PJM Interconnection alone serves **110.7 GW (25.5% of total)**, with ERCOT at 55.2 GW and MISO at 31.1 GW. A single utility — **Virginia Electric & Power Co — carries 29.7 GW**, more than any state outside Texas/Virginia/Georgia.

---

## 3. AI is reshaping facility design — bigger, more concentrated

| Cohort | Avg MW per site | Total MW |
|---|---|---|
| AI-flagged (Y) | **120.3** | 173,370 |
| AI null / unflagged | 53.6 | ~261,000 |

**AI facilities are 2.2× the size of conventional builds.** This is the campus-scale AI training cluster effect (xAI Colossus, Stargate, etc.). Note: 77.7% of records have a *null* AI flag — the true AI share is almost certainly higher than 40%.

**Top AI tenants** (by site count, where end-user is recorded):

| Tenant | AI sites | Notes |
|---|---|---|
| OpenAI | 81 | #1 demand driver |
| **Oracle** | **60** | **#2 — see §6** |
| Anthropic | 58 | |
| AWS | 51 | |
| Microsoft | 40 | |
| Google | 38 | |
| CoreWeave | 28 | |

---

## 4. Behind-the-Meter (BTM) onsite power: the grid bypass

**1,004 facilities (135.4 GW) flagged for behind-the-meter onsite power generation** — companies are building generation on-site rather than waiting on grid interconnects. **115.2 GW of this is still announced (not yet built).**

Top BTM operators:

| Operator | BTM MW |
|---|---|
| Joule Capital Partners | 11,650 |
| SoftBank Group | 9,990 |
| Nscale | 7,995 |
| Facebook | 6,060 |
| Nexus Data Centers | 4,025 |
| Crusoe | 3,672 |

This signals a structural shift: AI workloads can't wait the 4–7 years for grid interconnect queues. New entrants (Joule, Nscale, Crusoe) are building gas-fired or hybrid power *first*, then datacenters around them.

---

## 5. Energy supply mix (84 plant phases supplying these DCs)

| Tech | Total MW | # plants | Avg MW/plant |
|---|---|---|---|
| **Combined Cycle (gas)** | **32,691** | 20 | 1,635 |
| Simple Cycle (gas) | 11,257 | 12 | 938 |
| Photovoltaic (solar) | 9,741 | 20 | 487 |
| Onshore wind | 8,331 | 8 | 1,041 |
| Battery storage | 6,383 | 13 | 491 |
| Steam turbine | 5,015 | 2 | 2,508 |
| Reciprocating engine | 4,353 | 5 | 871 |
| Offshore wind | 2,640 | 1 | 2,640 |

**Natural gas dominates: 39 of 84 plant phases (46%).** Combined cycle is the workhorse — average plant size is 1.6 GW, much bigger than solar (0.49 GW) or batteries (0.49 GW). This explains the BTM trend — gas turbines deploy in 18–24 months vs. years for grid interconnects.

Storage capacity averages 2.86 GWh per project — substantial multi-hour duration.

---

## 6. Oracle / OCI competitive positioning

**Oracle is asset-light but demand-heavy** — a striking strategic divergence from peers:

| Hyperscaler | Self-built (provider) MW | Colo / leased (end-user) MW | Strategy |
|---|---|---|---|
| Amazon AWS | 27,022 | 0 | Self-build |
| Microsoft | 7,391 | 5,382 | Hybrid |
| Google | 10,894 | 7,192 | Hybrid |
| Facebook | 10,508 | 5,798 | Hybrid |
| **Oracle** | **0** | **6,357** (59 sites) | **Pure tenant** |
| OpenAI | 0 | 7,799 (67 sites) | Pure tenant |
| Anthropic | 0 | 6,642 (51 sites) | Pure tenant |

**Oracle's footprint (where Oracle is end-user, all stages):** 69 facilities, 6,760 MW
- 80% of capacity is **under construction** (5,441 MW) — massive ramp underway
- Active: 403 MW, Announcement: 916 MW
- **Geographic:** Texas dominates (48 sites, 2,987 MW), then Michigan (3 sites, 1,398 MW), Wisconsin (4 sites, 1,300 MW), New Mexico (4 sites, 900 MW), Utah (3 sites, 175 MW)
- **Hosting partners:** Vantage Data Centers (16 sites, 2,847 MW), Crusoe (32 sites, 1,200 MW), Related Digital (3 sites, 1,398 MW), BorderPlex Digital Assets (4 sites, 900 MW)

**Strategic implications:**
1. Oracle ranks **#2 globally in AI-tenant facility count** (60 sites, behind only OpenAI's 81) — strong AI demand position despite zero self-build.
2. Heavy dependence on Vantage and Crusoe creates **partner concentration risk** — these two host >60% of Oracle's leased capacity.
3. Oracle has effectively skipped the Virginia (FB/AWS/MSFT stronghold) and Northern California regions; Texas is the bet.
4. With 80% under construction, Oracle's *active* capacity will roughly **17× by activation completion** — most aggressive ramp curve in this dataset.

---

## 7. Pipeline execution risk

| Likelihood (announcement only) | MW | Sites | Avg MW |
|---|---|---|---|
| High | 149,578 | 1,560 | 95.9 |
| Medium | 120,906 | 1,299 | 93.1 |
| Low | 24,981 | 236 | 105.9 |
| Null | (the rest) | | |

**Failed/withdrawn capacity by state** (sites that won't materialize):

| State | Withdrawn MW |
|---|---|
| Virginia | 8,405 |
| Georgia | 2,737 |
| Arizona | 1,856 |
| Texas | 1,600 |
| Florida | 1,000 |

Virginia leads withdrawn capacity 3× over any other state — likely community/permitting opposition saturation. **The "Data Center Alley" is showing signs of build-out friction.**

Construction-stage progress is bimodal: median 20% complete, but 25% are <10% (just broke ground) and 25% are >85% (almost done). No middle ground — projects either stall early or push through to commissioning.

---

## 8. Mega-projects (≥500 MW per facility)

Only 10 facilities exceed 500 MW each. Notable:

| Provider | Facility | State | MW | Stage | AI? |
|---|---|---|---|---|---|
| EnergiAcres | Ernsberger Rd | Ohio | 900 | **Not Approved/Withdrawn** | — |
| xAI | Colossus 2 (Phase 3) | Mississippi | 700 | Construction | Y |
| Stream Data Centers | Texas Critical Phase 3 | Texas | 550 | Announcement | Y |
| Facebook | Kansas City (Land Bank) | Missouri | 540 | Land Bank | — |
| (Undisclosed) | Arizona AI DC × 3 | Arizona | 500 each | Announcement | Y |
| (Undisclosed) | Voyager / Nobles | Texas | 500 each | Announcement | Y |
| Cipher Mining | Barber Lake (Phase 2) | Texas | 500 | Announcement | Y (Fluidstack tenant) |

The largest single confirmed-build is **xAI Colossus 2 in Mississippi (700 MW, under construction)**. Nine of the top-10 mega-projects are AI-flagged.

---

## 9. Data quality findings (caveats for analysts)

1. **AI flag missing on 77.7% of records** (5,418 nulls). Real AI capacity likely 25–40% higher than the 173 GW shown.
2. **PUE (energy efficiency) data on only 6.1%** (426 facilities) — too sparse for benchmarking by region/operator.
3. **Project cost on only 19.3%** (1,346 facilities), and the top 10 most-expensive entries are all **SoftBank Stargate buildings each tagged at $500B** — this is a campus-program total being copy-pasted across 17 individual buildings, not real per-building cost. Filter or aggregate before using.
4. **Provider public/private classification has case inconsistency**: 9 entries show lowercase `private` instead of `Private` — minor cleanup needed.
5. **Three capacity fields exist with different coverage** — `SELECTED_POWER_CAPACITY_MW` (90.5%) is the cleanest single field; `PROV_PUB_TOT_POWER_CAPACITY_MW` (48%) is useful for cross-validation but sparse.
6. **52% null on `BAL_AUTH_SUBREGION_NAME`** — sub-grid analysis (e.g., Virginia's NOVA vs other PJM zones) is weak.
7. **`ESTIMATED_ACTIVE_DATE_BY` is a source field** ("Aterio", "Provider", "Utility", "Developer") — *not* a date. Don't use it for forward-pipeline year analysis.
8. **`Company Not Disclosed`** is the largest "provider" by both count (1,355 sites) and MW (111.8 GW = 26%). Quarter of the market is anonymous — limits provider-level competitive cuts.

---

## Recommended follow-ups (ranked)

1. **Provider-level Oracle ramp tracking** — given 80% of Oracle capacity is under construction, watching `PCT_CONSTRUCTION_STATUS` monthly for Vantage/Crusoe Texas sites is the single highest-signal input for OCI capacity planning.
2. **Virginia withdrawal trend** — are *new* announcements still flowing into VA, or is the market saturating? Compare 2024 vs 2025 announced MW for VA only.
3. **BTM build-out validation** — 115 GW announced BTM is the most uncertain bucket. Cross-reference against `Energy Project Inventory` to confirm matching gas turbine projects exist in the same counties.
4. **Cohort analysis on 2024 vs 2025 announcements** — is the 2025 cohort skewing larger (mega-AI) or just more numerous? Drives whether the buildout is "many small" or "few mega".
5. **Improve AI flag completeness** — train a classifier on building names + end-users to fill the 78% null. Would unlock real AI-share-by-region metrics.
