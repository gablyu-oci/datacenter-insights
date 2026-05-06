# ADR-006: Supply/Demand-Gap Analytical Pattern in the FactPack

**Status:** Accepted
**Date:** 2026-05-05
**Owners:** Architecture, AI Insights
**Predecessors:** `01-prd.md`, `03-architecture.md` (§3 hypothesizer, §10 D1/D2),
`05-prd-addendum-phase4-and-supply-demand.md` (Goal B, FR-B1..B5)

---

## 1. Context

the user asked the daily AI Insights run to surface a class of finding the
existing seven FactPack sections do not produce: residual / uncontracted
generation capacity that OCI's commercial team could go after.
Verbatim: *"XX datacenter/provider is generating XX megawatts but only
partially consumed by some company, so we could potentially contract the
rest — types of findings, not limited to this one question."*

The shipped FactPack (Phases 1-3, see `03-architecture.md` §3.3) covers
movers, permits, anomalies, EDGAR mentions, EPA ECHO records, coverage
gaps, and weekly developer deltas. None of those sections expose the
*supply minus demand* shape the user named. The PRD addendum (Goal B,
FR-B1..B5) scopes four new sections that do:

- `uncontracted_capacity_top_sites` — `EnergyProject` rows with non-null
  `tot_contracted_power_mw` and an empty / null `customer_companies`.
- `concentrated_offtake_sites` — `EnergyProject` rows with exactly one
  `customer_companies` entry whose contracted MW is in the per-state top
  quartile (state-median fallback when n<4 per OQ-B1).
- `capacity_by_developer_with_low_offtake` — developers in the top
  quartile of total contracted MW whose median offtaker count per
  project is <=1.
- `epa_echo_high_mw_no_known_customer` — `GeneratorPermit` rows
  (`source='epa_echo'`) with `rated_mw_total > 50` whose resolved
  company has no matching `EnergyProject` offtaker record.

This ADR records why those four sections are implemented as
deterministic SQL inside `hypothesizer.py` rather than via an agentic
ToolLoop, and what that choice cannot do.

---

## 2. Decision

### 2.1 Implement supply/demand-gap detection as deterministic FactPack sections

The four sections append to `_SECTION_BUILDERS` in
`backend/agents/insights/hypothesizer.py`. Each is a `_safe_query`-
wrapped SELECT capped by `FACT_PACK_MAX_ROWS_PER_SECTION = 12`. The
single existing mega-LLM call consumes them like every other section;
the LLM is told (one new bullet under "Rules:" in `_SYSTEM_PROMPT`) to
frame any insight grounded in these sections as a commercial
opportunity and to cross-reference EDGAR / EPA rows where the FactPack
makes that natural.

This is the same shape as decision **D1** in `03-architecture.md` §10:
the deterministic FactPack + single mega-call (architecture option
**A1**) was chosen for v1 over the agentic option **A2**
(ToolLoopDriver) and the hybrid **A3**.

### 2.2 Why deterministic, not agentic, for *this* pattern

Three reasons, each tied to an existing constraint:

1. **Cost ceiling.** D7 / D10 of the existing decision log fix a hard
   30K-token ceiling per daily run, enforced via static FactPack caps
   (`FACT_PACK_MAX_ROWS_PER_SECTION=12`, `FACT_PACK_MAX_TOTAL_ROWS=60`,
   warn-only `HYPOTHESIZER_TOKEN_CEILING=30_000`). An agentic
   ToolLoopDriver per insight would add unbounded tool-call rounds on
   top of synthesis and would breach that ceiling on a populated day.
   Four extra deterministic SELECTs add zero additional LLM tokens
   beyond the row payload.
2. **Determinism / the user's trust model.** the user opens the tab cold each
   morning and expects the same kind of finding to appear day over day
   when the underlying data has not changed. A ToolLoop's tool-call
   sequence and intermediate reasoning vary across runs even with
   `temperature=0`; the same uncontracted-capacity site can appear, get
   missed, or get phrased very differently. Deterministic SQL means the
   gap is either in the FactPack or it is not, and the LLM cannot
   forget to look.
3. **Unattended scheduled execution.** The 09:00 UTC cron run has no
   human in the loop. ToolLoop guardrails (tool-call cap, retry policy,
   citation gating, termination heuristics) are exercised in V2 chat
   where an analyst is watching SSE and can cancel. The daily run
   cannot be cancelled mid-flight by a human; we want the synthesis
   step to be a single call that either succeeds, parses, persists, or
   fails cleanly via `ErrorEvent(code="synthesis_parse_failed")`
   (per architecture §4.5 step 4 / D2).

This re-confirms D1 ("A1 deterministic FactPack + mega LLM call") and
D2 ("one mega call producing `{insights:[...]}`") for the new pattern.
A3 (hybrid drill-down) remains the v1.1 migration target.

### 2.3 Tie-in to A1 architecture: zero new surface area

The four sections require:

- No orchestrator changes. `_phase_bootstrap_iter` still calls
  `build_factpack(db)`; it just receives 11 sections instead of 7.
- No new tool calls, no new ToolLoop, no V2 chat changes.
- No SSE protocol changes, no router changes, no schema migration
  (per addendum AC-A1).
- No new HTTP routes.

The total diff is: four new builder coroutines, four entries in
`_SECTION_BUILDERS`, one bullet in `_SYSTEM_PROMPT`'s "Rules:" block,
and tests. The pattern is intentionally the smallest possible
extension to the in-tree precedent.

---

## 3. Consequences / Limits

What this approach buys:

- Reproducible commercial-opportunity surfacing keyed on schema-coded
  shapes (uncontracted MW, single-offtaker concentration, developer
  concentration, EPA ECHO orphans).
- Zero token-budget regression. Each section adds at most 12 rows to
  the input FactPack; the global `FACT_PACK_MAX_TOTAL_ROWS=60` keeps
  the prompt input bounded (the architect must verify the combined
  bound at implementation time per addendum NFR-B1; trim or raise the
  cap if 11 sections * 12 rows exceeds 60 in practice).
- Unattended-safe behaviour. `_safe_query` already swallows per-section
  errors into `error=<short>, rows=[]`; a column rename or missing
  table on one section does not poison the daily run.

What this approach cannot do:

- It only surfaces structurally-coded gaps. "Find ANY interesting
  opportunity I have not pre-imagined" is precisely what the
  deterministic path rules out — by design, the pattern catalogue is
  the catalogue. Truly open-ended exploration needs the agentic V1.1
  path (the deferred A3 hybrid in D2 of `03-architecture.md` §10).
- It is only as good as `customer_companies` and `developer_companies`
  population. If those columns are sparse or shaped unexpectedly
  (OQ-B2: scalar array vs JSONB vs delimited text vs join table), the
  sections will be empty without flagging the underlying data gap.
  Mitigated by the existing `coverage_gaps` section.
- The state-quartile fallback to median for n<4 (OQ-B1) is a heuristic;
  a state with 5-6 rows still produces a noisy quartile cutoff. The
  ADR accepts this as good-enough for v1 and revisits if false
  positives dominate.

This trade-off is explicit: we ship a narrow, deterministic version of
the user's named pattern now; we defer open-ended gap-mining to the
agentic V1.1 path.

---

## 4. Alternatives Considered

### A. Agentic ToolLoopDriver per insight

Run the ToolLoopDriver (V2 chat infrastructure) inside the daily run,
letting the LLM call exploratory tools (e.g. `query_energy_projects`,
`query_edgar_extractions`, `cross_reference_offtakers`) and surface
gaps from raw exploration.

**Rejected for v1.** Three blockers: (a) cost — exceeds the 30K-token
ceiling and adds non-trivial wall-clock; (b) non-determinism — the user
cannot trust that today's "uncontracted Vistra site #4" will reappear
tomorrow; (c) latency / cancellation — the daily cron has no
human-in-the-loop guardrail and cannot tolerate tool-loop runaway.
Revisit as the A3 hybrid in V1.1 once we have ~30 days of v1 baseline
to compare against.

### B. New top-level agent dedicated to gap-detection

Stand up a parallel agent (e.g. `agents/gap_finder.py`) with its own
prompt, its own tool registry, and its own scheduler entry feeding
either `ai_insight` rows or a sibling `gap_insight` table.

**Rejected.** Premature. The pattern is small enough — four SELECTs and
one prompt bullet — to live in the existing FactPack. A second agent
duplicates infrastructure (orchestrator, persistence, dedup, SSE) for
no benefit. Revisit only if gap-detection grows past ~10 sections or
needs a separate cadence.

### C. Defer entirely to V1.1

Wait until the agentic A3 hybrid lands, then implement gap-detection
through the agentic path.

**Rejected.** the user has named the pattern explicitly and has named the
example shape (uncontracted MW). We can ship a deterministic version
now without blocking on the V1.1 effort, and the deterministic version
becomes a regression-test floor for whatever the agentic V1.1 path
produces later.

---

## 5. Recommended Follow-ups

- **Nameplate vs contracted MW in `EnergyProject`.** Today only
  `tot_contracted_power_mw` is stored. The "X MW generated, only
  partially consumed" framing is materially tighter when the
  hypothesizer can compare nameplate (capacity available) against
  contracted (capacity sold). Enrich the EDGAR extractor to write a
  `nameplate_mw` column (or a sibling extraction field) so a future
  section can compute `nameplate - contracted` directly. Until then
  `uncontracted_capacity_top_sites` is a proxy.
- **Agentic drill-down (A3 hybrid, D2 in the existing log).** Add a
  ToolLoop-driven follow-up so an analyst on the AI Insights tab can
  click a gap insight and ask "go deeper on this site"; the
  ToolLoopDriver fans out targeted queries (recent permits at the
  site, EDGAR mentions of the developer, EPA ECHO history) and
  produces a second-tier insight scoped to that one site. This is the
  V1.1 migration target; deterministic v1 stays the default daily
  surface.
- **`gap_score` numeric column on insights.** Add a nullable
  `gap_score: float` to `ai_insight` populated when the supporting
  rows come from the four new sections. The UI sorts by opportunity
  size (e.g. uncontracted MW absolute) so the morning feed leads with
  the largest commercial gap. Defer until at least a week of
  populated runs makes the scoring distribution visible.

---

## 6. Implementation Notes

Pointers only — no code in this ADR.

- Each section uses `_safe_query` (existing helper, lines ~154-165 of
  `hypothesizer.py`). Per-section cap respects
  `FACT_PACK_MAX_ROWS_PER_SECTION=12`; the global
  `FACT_PACK_MAX_TOTAL_ROWS=60` trim already runs in `build_factpack`.
- The four sections append to `_SECTION_BUILDERS` (currently a list of
  seven 3-tuples at lines 482-504). Order does not matter for
  correctness but place the new sections at the end so the existing
  ordering-sensitive tests do not need to change.
- `_SYSTEM_PROMPT` (currently lines 625-642) gets exactly one new
  bullet inside the "Rules:" block instructing the LLM to frame
  insights grounded in the four new sections as commercial
  opportunities and to cross-reference EDGAR / EPA rows where the
  FactPack makes that natural. The wrapper rules around `_utcnow`,
  `_today_utc`, `_coerce_insights`, and the rest of the prompt
  scaffolding are not modified (PRD addendum FR-B5, AC-B2).
- Tests:
  - One unit test per section asserting `[]` against an empty
    table (hits `_safe_query` exception or empty-result branch).
  - One unit test per section against synthetic fixture rows
    asserting populated `FactRow`s with the documented row-dict
    keys.
  - One prompt-snapshot test asserting the literal substring
    `SUPPLY/DEMAND GAPS` appears exactly once inside `_SYSTEM_PROMPT`
    and that the surrounding wrapper rules are byte-identical to
    their pre-change form (per addendum AC-B2).
  - End-to-end: `build_factpack(db)` returns 11 sections by name.

---

*End of ADR-006.*
