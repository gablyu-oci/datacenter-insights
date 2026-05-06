# TASKS — AI Insights Tab (V1 prioritized breakdown)
**Owner:** PM (round 2 consolidation) · **Stakeholder:** the user
**Status:** Draft v0.2 · **Date:** 2026-05-04
**Cross-refs:** [`./PRD.md`](./PRD.md) · [`./RESEARCH.md`](./RESEARCH.md) · [`./ARCHITECTURE.md`](./ARCHITECTURE.md) · [`./SKILL_CONVERSION.md`](./SKILL_CONVERSION.md) · [`./UX.md`](./UX.md)

> Pure planning. Consolidates the prior 5 docs into a sprint-ready V1 task list. No implementation code.

---

## T1. Summary

### T1.1 V1 scope (restated)

| Item | V1 value |
|---|---|
| Insights per session | 5–10 (dynamic, agent-ranked) |
| Charts | Required ≥80% of insights, **ChartSpec v1** only, Recharts-rendered |
| Chat | **NO** (V2) |
| Web search & citations | **NO** (V2) |
| Active skills | **12** in V1 (per PRD §6.3 / SKILL_CONVERSION §S4.2 keep-15 minus 3 V2-deferred: cohort, methodology-explainer, peer-review-template). The architect's reconciliation reading "6–8" reflects the *high-confidence-first* ship plan inside Sprint 1 — see T2/P-7. **PM ratifies: 12 skills active by end of V1; ship in waves of 4 across S1/S2/S3.** |
| Persistence | 7 new tables + pgvector RAG store |
| Streaming | SSE with typed events + Last-Event-ID resume |
| Auth | None (per parent PRD §8 D5) |

### T1.2 V1 estimate

- **Total V1 dev-days: 56** (sum of T6 cells; see T1.4 confidence range)
- **Confidence range: 50–66 dev-days**, treating 56 as the median.
- **Calendar:** 1 backend engineer + 1 frontend engineer + 0.4 designer + 0.2 PM ≈ **3 sprints × 2 weeks = 6 calendar weeks**, including a 0.5-week dogfood/calibration tail in Sprint 3.
- **Buffer:** 15% explicit (sprint capacity 20 dev-days/sprint × 3 = 60; we're loaded at 56; the 4-day delta is the buffer).

### T1.3 Critical path (must-not-slip chain)

`W1.1 Read-only Postgres role → W1.2 Alembic migration → W2.1 SQL gate → W2.5 ToolLoopDriver → W2.6 emit_chart + ChartSpec v1 schema → W6.1 SSE router → W7.1 agentchat extraction → W8.2 InsightCard renderer → W10.4 the user dogfood`

If any of those slip a day, the demo slips a day. Everything else is parallelizable.

### T1.4 Confidence levers

| Lever | Likely effect on total |
|---|---|
| Skill conversion fidelity (PRD R4) blows past 0.5 days/skill | +6 dev-days |
| ChartSpec v1 needs an unforeseen Recharts adapter (heatmap, stacked-area edge) | +2 dev-days |
| pgvector or Postgres role provisioning blocked on infra | +2 dev-days (calendar, not effort) |
| LlamaStack instance principal misconfigured in prod path | +1 dev-day |
| the user calibration finds <30% useful → re-prompt cycle | +3 dev-days (already partly in T6 W11) |

---

## T2. Decisions to ratify before kickoff (PM hand-off)

> **✅ Ratification log — 2026-05-04 (gabrielle.lyu@oracle.com)**
>
> All proposed defaults in the table below are **approved**. Specifically:
>
> | ID | Approved value |
> |---|---|
> | R-2 | Adopt ChartSpec v1 sketch (Pydantic + JSON-Schema) — ratify in W1.6, gates S1 day 1 |
> | R-3 | SSE with typed `event:` names + Last-Event-ID — gates S1 day 1 |
> | R-5 | V1: agent self-rate 3-level S/M/L. **the user sign-off still required for rubric prompt before V2.** |
> | R-6 | V1: cold per session. V3: cross-session embedding novelty |
> | R-7 | Citation freshness ≤24 months default; flag-only beyond |
> | R-8 | Confidence: low = (rows<50 OR no agree-cite OR stale); high = (rows≥200 AND ≥1 agree-cite AND fresh); else medium |
> | R-9 | V3 cron: Sun 23:30 UTC (or Mon 00:30 UTC, ops to finalise) |
> | R-10 | Chat thread retention 90 days |
> | P-3 | V1 alembic adds `delete_after` column with default NULL (avoids V2 follow-up migration) |
> | C-1 | Embedding-cosine novelty threshold 0.85; calibrate against 100 hand-labeled pairs in S2 |
> | C-2 | Calibrate gpt-5.4 mid-conversation system-message handling on S1 day 1 (ticket W3.4); fall back to user-shaped injection if not honored |
> | C-3 | ARIMA `(1,1,1)` default; auto-ARIMA on 3 fixtures (V2) |
> | C-4 | peer-review-template target 70–85% pass rate (V2) |
> | C-5 | RAG retrieval k=3; verify per-skill in S1 RAG ingest |
> | U-Q1 | AI Insights tab placement: **rightmost**, after Sources |
> | U-Q11 | V1: 5-star rating in kebab menu. V2: thumb up/down inline |
> | Skill count | "12 active by V1 end" interpreted as **ship-order** (waves of 4 across S1/S2/S3), not a hard cap of 6–8 |
>
> **Headcount (resolved 2026-05-04):** **Option A — add 2nd backend engineer** for W4 wave 2 in S2. V1 stays on the 6-week target. Action: PM/Eng Lead to identify the second body before end of S1.
>
> **All Open items above are now Ratified.**

---

Single ratification table consolidating PRD OQ1–OQ11, ARCHITECTURE A15.2 P1–P7 + designer D1–D10, SKILL_CONVERSION S11, UX U14.

| ID | Question | Proposed default | Who decides | Deadline | Status |
|---|---|---|---|---|---|
| **R-1** | Web-search provider (PRD OQ1) | Tavily primary, Brave fallback (per RESEARCH §1.3) | PM + Eng Lead | Before S2 | **Resolved by RESEARCH** — V2 only |
| **R-2** | ChartSpec v1 schema (PRD OQ2) | Adopt ChartSpec v1 sketch (RESEARCH §2.3 / ARCH §A4) | Architect | **Before S1 day 1** | **Resolved** — ratify Pydantic+JSON-Schema in W1.6 |
| **R-3** | Streaming protocol (PRD OQ3) | SSE with typed `event:` names + Last-Event-ID (RESEARCH §6) | Architect | **Before S1 day 1** | **Resolved** |
| **R-4** | Skill conversion path (PRD OQ4) | Pattern (a) — each skill = one tool fn under `run_skill` (RESEARCH §4 / SKILL §S1.1) | Skill engineer | S1 day 1 | **Resolved** |
| **R-5** | Materiality scoring rubric (PRD OQ5) | V1: agent self-rate via prompt (3-level S/M/L). PM labels 50 samples post-V1 to seed V2. | PM + the user | **End of S2** | **Open** — needs the user sign-off on rubric prompt |
| **R-6** | Cross-session insight uniqueness (PRD OQ6) | V1: cold per session. V3 cron uses cross-session embedding novelty. | PM | Before V3 | Deferred (not V1-blocking) |
| **R-7** | Citation freshness window (PRD OQ7) | ≤24 months default, flag-only beyond | PM + the user | Before S2 | Deferred |
| **R-8** | Confidence rubric thresholds (PRD OQ8) | low = (rows<50 OR no agree-cite OR source past freshness band); high = (rows≥200 AND ≥1 agree-cite AND fresh); else medium (per ARCH P2) | Architect + PM | **Before S3** | **Open** — must ratify pre-demo |
| **R-9** | V3 cron timing (PRD OQ9) | Sun 23:30 UTC OR Mon 00:30 UTC (defer until V3) | Ops | Before V3 | Deferred |
| **R-10** | Chat thread retention (PRD OQ10) | 90-day retention; `delete_after` column on `agent_message` | PM | Before S2 (V2) | Deferred |
| **R-11** | Skill catalog reconciliation (PRD OQ11) | Final keep-15 confirmed against installed catalog (SKILL §S4.1). 18 dropped-installed + 16 vacuous-PRD-named. | Skill engineer | **Resolved** in SKILL_CONVERSION | **Resolved** |
| **P-1** | V1 ships without chat (ARCH P1) | Yes — chat is V2 | PM | **Before S1** | **Confirmed by PM** in this doc |
| **P-3** | Chat retention column shape (ARCH P3) | Deferred to V2 schema patch — V1 alembic still adds the column with default NULL to avoid a follow-up migration | Architect | S1 | **Open (low risk)** |
| **P-4** | Vacuous-skill-drop acknowledgement (ARCH P4) | PM acknowledges 16 PRD-named drops never existed; no further action | PM | Before S1 | **Acknowledged** |
| **P-5** | OQ11 reconciliation acknowledgement (ARCH P5) | PM acknowledges 33-skill catalog vs PRD §6 cut | PM | Before S1 | **Acknowledged** |
| **P-7** | Cite freshness default (ARCH P7) | ≤24 months default | PM | Before S2 | Deferred |
| **D-1** | Streaming-token treatment (ARCH D1 / UX U7.5) | Stream tokens, low-contrast `#94a3b8` "drafting", snap to white on `insight_complete` | Designer | S1 | **Resolved by UX U3.2 / U7.5** |
| **D-2** | Chat dock placement (ARCH D2 / UX U6.1) | In-card slide-down dock | Designer | Before S2 (V2) | **Resolved by UX U6** |
| **D-3** | Citation hover vs inline (ARCH D3 / UX U5.2) | Hover-card | Designer | Before S2 (V2) | **Resolved** |
| **D-4** | Skeleton hierarchy (UX U7.2) | Header solid → headline shimmer → chart skeleton frame → caption shimmer → footer shimmer | Designer | S1 | **Resolved** |
| **D-5** | Surveying preamble UX (UX U7.4) | Single banner above all cards; replaced by first card on insight 1 complete | Designer | S1 | **Resolved** |
| **D-6** | Provenance footer default (UX U3.5) | Collapsed; chevron expands | Designer | S1 | **Resolved** |
| **D-7** | low_external_support visibility (UX U3.4) | Pill in card header (V2 only) | Designer | Before S2 | **Resolved** |
| **D-8** | Cancel UX (UX U9.5) | Single page-level Cancel; no per-insight pause; Esc cancels | Designer | S1 | **Resolved** |
| **D-9** | Map shapes deferred (ARCH D9) | No map UI in V1/V2; geospatial-analysis skill deferred | Designer | n/a | **Acknowledged** |
| **D-10** | Mobile target (ARCH D10) | Desktop-only; tablet/mobile best-effort | PM + Designer | Before S1 | **Acknowledged** |
| **C-1** | Embedding-cosine novelty threshold (SKILL C1) | Start at 0.85; calibrate against 100 hand-labelled pairs in S2 | Skill engineer | S2 | Open |
| **C-2** | Mid-conversation system-msg honoured by gpt-5.4 (SKILL C2 / ARCH A9) | Calibrate in S1; fallback to user-shaped injection | Backend | S1 | **Open — calibration ticket W3.4** |
| **C-3** | ARIMA order for time-series-analysis (SKILL C3) | Default `(1,1,1)`; auto-ARIMA on 3 fixtures | Skill engineer | S2 | Deferred to V2 (not V1 path) |
| **C-4** | peer-review-template strictness (SKILL C4) | Target 70–85% pass rate | Skill engineer | V2 | Deferred |
| **C-5** | RAG retrieval k=3 budget (SKILL C5) | Verify per-skill in S1 RAG ingest | Skill engineer | S1 | **Open** |
| **U-Q1** | Tab nav placement (UX U14 Q1) | Rightmost, after Sources | PM | **Before S1** | **Open — fast** |
| **U-Q2** | Max headline length (UX Q2) | 80 chars (truncate at 78 + ellipsis) | PM | S1 | **Resolved (default)** |
| **U-Q3** | Materiality label form (UX Q3) | `[S/M/L]` | PM | S1 | **Resolved (default)** |
| **U-Q4** | Default card sort order (UX Q4) | Agent's materiality+novelty rank | PM | S1 | **Resolved (default)** |
| **U-Q5** | Fixed vs dynamic insight count (UX Q5) | Dynamic 5–10; UI reads M from `session_complete` | PM | S1 | **Resolved (default)** |
| **U-Q6** | Confidence label form (UX Q6) | `conf: high` | PM | S1 | **Resolved (default)** |
| **U-Q7** | Generated-time format (UX Q7) | Relative in header; absolute in provenance footer | PM | S1 | **Resolved (default)** |
| **U-Q8** | Cancel during streaming partial chart (UX Q8) | Discard chart; keep headline + subtitle | PM | S1 | **Resolved (default)** |
| **U-Q9** | Sessions retention in dropdown (UX Q9) | Last 20 | PM | S2 | Deferred |
| **U-Q10** | Share-link expiry (UX Q10) | 30-day with renew (V3) | PM | V3 | Deferred |
| **U-Q11** | In-card per-insight rating widget (UX Q11) | V1: 5-star in kebab. V2: thumb up/down inline. | PM + the user | **Before S2** | **Open — instruments G4** |
| **U-tokens** | Platform-wide token migration vs tab-local | Tab-local in V1; platform-wide migration is a separate cleanup ticket | PM | S1 | **Resolved (default)** |

**Top 3 unresolved items that block S1:**
1. **U-Q1** — tab nav placement (PM call, 5 minutes).
2. **R-2 / R-3** — ratify ChartSpec v1 + SSE event taxonomy at the schema level so frontend can stub against it on day 1.
3. **C-2** — confirm gpt-5.4 honours mid-turn system messages, or commit to user-shaped injection (W3.4).

---

## T3. Pre-kickoff prerequisites

Each prerequisite is a task in T6 (W0.x). They must all be ✓ before S1 day 1.

| ID | Task | Owner | Size | Notes |
|---|---|---|---|---|
| W0.1 | Read-only Postgres role `ai_agent` provisioned (`NOSUPERUSER NOCREATEDB NOCREATEROLE`, GRANT SELECT on public schema, `CONNECTION LIMIT 4`); secret in env (`AI_AGENT_DB_URL`) | Infra/Backend | 0.5 | Blocks W2.1 |
| W0.2 | pgvector extension confirmed enabled (or `CREATE EXTENSION IF NOT EXISTS vector` in alembic) | Backend | 0.5 | Blocks W4 RAG ingest |
| W0.3 | LlamaStack reachable from prod backend; `oci/openai.gpt-5.4` + `oci/openai.text-embedding-3-large` smoke-tested via existing `LlmClient` | Backend | 0.5 | Blocks W3 |
| W0.4 | `sqlglot` added to `backend/pyproject.toml` (+ `statsmodels` flagged for time-series-analysis; deferred to W4) | Backend | 0.5 | Blocks W2.1 |
| W0.5 | ChartSpec v1 Pydantic model + JSON-Schema published at `backend/agents/insights/specs/chart_spec.schema.json` | Backend | 1.0 | **Gates ALL frontend chart work** |
| W0.6 | Frontend `agentchat/` extraction kickoff — read `ChatPanel.tsx` 586 lines + design extraction plan (RESEARCH §5.3) | Frontend | 0.5 | Can start in parallel after W0.5 |
| W0.7 | Repo structure stub: empty `backend/agents/insights/` tree (per ARCH A2), empty `frontend/src/components/insights/` + `agentchat/` trees, alembic scaffold | Joint | 0.5 | Mechanical |
| W0.8 | OCI brand-token audit: confirm hex values in PowerTab + ChatPanel match U11.5 table; record accessibility deltas (U10.3 `#64748b` exception) | Designer + Frontend | 0.5 | Blocks W7/W8 visual styling |
| **Total prerequisites** | | | **4.5 dev-days** | One sprint week of pre-S1 work split across roles |

---

## T4. Workstreams (V1)

| WS | Name | Rationale | Owner role | Implements |
|---|---|---|---|---|
| **W0** | Pre-kickoff prerequisites | Get the ground under everyone before S1 day 1 | Mixed | T3 |
| **W1** | Foundations & Persistence | Alembic migration, 8 new tables + pgvector index, SQLAlchemy models | Backend | ARCH A2 / A7 |
| **W2** | Tool Loop & Safety | `tool_loop.py`, `sql_gate.py`, in-process router caller, get_chart_data registry, emit_* | Backend | ARCH A6 / A10 |
| **W3** | LlamaStack Adapter | LlmClient reuse, ToolLoopDriver, parallel-tool-call buffering, `reasoning.effort` policy, mid-turn system-msg calibration | Backend | RESEARCH §3 / ARCH A9 |
| **W4** | Skill Conversion | Per-skill: tool.py + system_fragment.md + RAG ingest. **12 V1 skills** in 3 waves | Skill engineer (Backend) | SKILL §S4 / §S5 / §S6 |
| **W5** | Insight Orchestration | `orchestrator.py` (bootstrap → hypothesise → verify → emit), novelty filter, dedup | Backend | ARCH A8 / RESEARCH §9 |
| **W6** | HTTP API + SSE | `routers/insights.py`, SSE event emission, Last-Event-ID resume, persistence writes | Backend | ARCH A3 / A5 |
| **W7** | Frontend Foundations | `agentchat/` extraction (6 primitives), SSE client, ChartSpec renderer, AIInsightsTab registration | Frontend | RESEARCH §5 / ARCH A12 / UX U2 |
| **W8** | Frontend Insights UI | InsightCard, ProvenanceFooter, SurveyingBanner, SkeletonStack, EmptyState, ErrorState, SessionRunner | Frontend | UX U3 / U7 / U8 |
| **W9** | Observability & Logging | per-session structured logs, tool_call_log writes, frontend telemetry hooks, the user-facing provenance footer (V1's user-visible observability surface) | Backend + Frontend | ARCH A11 |
| **W10** | QA & Dogfood | test plan, fixture insights, the user calibration session, success-metric instrumentation | PM + Eng | PRD §7 / SKILL §S9 |
| **W11** | Docs & Demo prep | per-skill README, V1 unveiling demo script, the user handoff brief | PM | — |

---

## T5. Dependency graph

### T5.1 ASCII DAG (critical path bolded with `**`)

```
                        ┌─ W0.6 agentchat extract plan ──┐
                        │                                │
W0.1 db role ──┐        ▼                                ▼
W0.2 pgvector ─┼──▶ **W0.5 ChartSpec v1 schema** ───┬─▶ **W7.1 agentchat extract**
W0.3 llmstack ─┤                                   │       │
W0.4 sqlglot ──┘        │                          │       ▼
                        │                          │   W7.2..W7.6 frontend foundations
                        │                          │       │
                        ▼                          ▼       ▼
                  **W1.1 alembic migration** ─┬─▶ W1.2..1.5 SA models
                                              │
                                              ├─▶ **W2.1 sql_gate** ─▶ **W2.2 db tool**
                                              │                        │
                                              ├─▶ W2.3 router_call    ├─▶ **W2.5 ToolLoopDriver** ─┐
                                              │                        │     ▲                     │
                                              ├─▶ W2.4 chart_data reg ┤     │                     ▼
                                              │                        │   W3.1..W3.4 LLM adapter ─▶ **W2.6 emit_chart**
                                              ├─▶ W4.0 skill scaffold ─▼     │                     │
                                              │       │                       │                     │
                                              │       ├─▶ W4.1..W4.4 skills wave 1 ──▶ **W5.1 orchestrator** ──▶ **W6.1 SSE router**
                                              │       ├─▶ W4.5..W4.8 skills wave 2 ─────────┘                          │
                                              │       └─▶ W4.9..W4.12 skills wave 3 ─────────────────────────────┐    │
                                              │                                                                    │    │
                                              ├─▶ W6.2 cancel + last-event-id ───────────────────────────────────┴────┤
                                              │                                                                         │
                                              └─▶ W9.x logging/observability  ◀──────────────────────────────────────┘
                                                                                                                         │
   W7.1 agentchat extract ──▶ W7.2 sse client ─┬─▶ W7.3 ChartSpec renderer ─▶ **W8.2 InsightCard** ─┬─▶ W8.3..W8.7 ─┬─▶ W8.8 SessionRunner
                                                │                                                    │              │
                                                └─▶ W7.4..W7.6 primitives ──────────────────────────┘              │
                                                                                                                     │
                                       ┌─────────────────────────────────────────────────────────────────────────────┘
                                       ▼
                                **W10.4 the user dogfood** ──▶ W11.x docs + demo
```

### T5.2 Parallelizable strands

- **W4 (skill conversion) can mostly parallelize** once W2/W3 land. Each of the 12 skills is a 0.5–1 dev-day task, mostly independent. Skill waves are sequenced for risk-buy-down (highest-confidence first), not for technical dependencies.
- **W7/W8 (frontend) can stub the SSE stream** locally while W6 is being built. A fixture-driven SSE server stub (W7.2 deliverable) lets the cards be built end-to-end against synthetic data before the real backend stream lights up.
- **W9 (observability)** is end-to-end and can land last per surface (logging on W6 day, telemetry on W8 day).

### T5.3 Blocking nodes

| Node | What blocks it | What it blocks |
|---|---|---|
| **W0.5 ChartSpec v1 schema** | R-2 ratification | All chart work, all `emit_chart` work, the entire UI pipeline below the card chrome |
| **W0.1 read-only DB role** | Infra ticket + secret | All `query_database` execution; the safety gate is moot without the role |
| **W7.1 agentchat extraction** | Read of ChatPanel.tsx + extract plan | Every frontend insight component (`InsightChart`, `MarkdownMessage`, `CitationList`) |
| **W2.5 ToolLoopDriver** | W3.1–W3.3 (LlamaStack adapter buffering) | The orchestrator (W5) and ALL skill invocations |
| **W6.1 SSE router** | W2.5 + W5.1 | All frontend integration tests; demo |

### T5.4 Stub-able nodes

| Real node | Stub | Used by |
|---|---|---|
| W6.1 SSE router | `frontend/src/insights/sse.fixture.ts` — replays a fixed sequence of typed events | W7/W8 building UI before backend lights up |
| W2.2 db tool | Fake row generator returning seeded fixtures | W4 skill smoke tests |
| W4 skills | Stub returning `{ok: true, output: <golden>}` | W5 orchestrator scaffold |

---

## T6. Task breakdown table (THE CORE DELIVERABLE)

**Sizing rules:** 1 dev-day = 1 focused day, experienced engineer. Half-day rounding. Max 5/task; bigger tasks split. **Total: 56 dev-days for V1 across 3 sprints.**

Sprint allocation: **S1** = foundations + scaffolds + skills wave 1; **S2** = orchestrator + UI + skills wave 2; **S3** = polish + dogfood + skills wave 3 + demo.

| ID | WS | Task | Owner | Size | Depends on | Sprint | Acceptance criteria | Maps to |
|---|---|---|---|---|---|---|---|---|
| W0.1 | W0 | Provision read-only Postgres role `ai_agent` + env secret | Infra/Backend | 0.5 | — | S1 | `psql` connect with role; `INSERT` denied; `SELECT` allowed | ARCH A1.3, A10.1 |
| W0.2 | W0 | Confirm/enable pgvector extension | Backend | 0.5 | — | S1 | `SELECT * FROM pg_extension WHERE extname='vector'` returns row | ARCH A7 |
| W0.3 | W0 | LlamaStack smoke test from prod backend | Backend | 0.5 | — | S1 | `LlmClient.reason()` returns; `embed()` returns 3072-dim vector | RESEARCH §3.1 |
| W0.4 | W0 | Add `sqlglot` to `pyproject.toml` | Backend | 0.5 | — | S1 | `pip show sqlglot` succeeds in dev image | RESEARCH §0 |
| W0.5 | W0 | Publish ChartSpec v1 Pydantic model + JSON-Schema export | Backend | 1.0 | R-2 ratified | S1 | Schema file at known path; round-trip test (model→json-schema→sample→model) green | RESEARCH §2.3, ARCH A4 |
| W0.6 | W0 | Read ChatPanel.tsx + write agentchat extraction plan doc | Frontend | 0.5 | — | S1 | One-page plan listing 6 files + diff ranges | RESEARCH §5.3 |
| W0.7 | W0 | Repo structure stub (backend + frontend trees, alembic scaffold) | Joint | 0.5 | — | S1 | Empty modules with __init__.py + barrel exports importable | ARCH A2, A12 |
| W0.8 | W0 | OCI brand-token audit | Designer + FE | 0.5 | — | S1 | Confirmed-hex table inlined in PR; U10.3 `#64748b` exception documented | UX U10.3, U11.5 |
| W1.1 | W1 | Alembic migration: 8 new tables + pgvector index | Backend | 2.0 | W0.2 | S1 | `alembic upgrade head` succeeds on fresh DB; ER matches ARCH A7 | ARCH A7 |
| W1.2 | W1 | SQLAlchemy models for `insight_session`, `insight`, `chart` | Backend | 1.0 | W1.1 | S1 | Model round-trip: create → flush → re-fetch matches | ARCH A2, A7 |
| W1.3 | W1 | SQLAlchemy models for `agent_message`, `tool_call_log`, `skill_invocation` | Backend | 1.0 | W1.1 | S1 | as above | ARCH A7 |
| W1.4 | W1 | SQLAlchemy model for `skill_rag_chunk` (pgvector column) | Backend | 0.5 | W1.1 | S1 | `embedding` column accepts list-of-3072-floats and round-trips | ARCH A7, SKILL §S6 |
| W1.5 | W1 | SQLAlchemy model for `citation` table (V2 stub-row in V1) | Backend | 0.5 | W1.1 | S1 | model importable; no V1 writes | ARCH A14.1 |
| W1.6 | W1 | Replay ring buffer (`persistence/replay.py`) for Last-Event-ID resume | Backend | 1.0 | W1.2 | S2 | 500-event deque per session; resume test passes | ARCH A5.1 |
| W1.7 | W1 | Code review checkpoint — schema | Backend | 0.5 | W1.1–W1.5 | S1 | PR approved by 2 reviewers | — |
| W2.1 | W2 | `safety/sql_gate.py` (sqlglot AST allowlist) | Backend | 1.5 | W0.4 | S1 | Allow-list / disallow-list cases all green; fuzz test rejects 100 hostile SQLs | ARCH A10.1 |
| W2.2 | W2 | `tools/db.py` — `query_database` with role + statement_timeout + row cap + row_hash | Backend | 1.0 | W0.1, W2.1 | S1 | 10-row-cap test, 5s timeout test, row_hash determinism test all green | ARCH A6.1 |
| W2.3 | W2 | `tools/router_call.py` — endpoint allowlist + in-process ASGITransport | Backend | 1.0 | W0.7 | S1 | 12 known endpoints (per ARCH A6.3 table) returnable; non-allowlisted endpoint rejected | ARCH A6.2 |
| W2.4 | W2 | `tools/chart_data.py` — tab × chart_id registry (12 entries, per ARCH A6.3) | Backend | 0.5 | W2.3 | S1 | All 12 entries return shape; unknown tab/chart returns `endpoint_not_allowed` | ARCH A6.3 |
| W2.5 | W2 | `tool_loop.py` — ToolLoopDriver (12-turn cap, 4-wide parallel, wall-clock budget) | Backend | 3.0 | W3.1–W3.3 | S2 | Mock-LLM driven test: 3 parallel `query_database` calls dispatched concurrently; cap trips correctly | RESEARCH §3.2, ARCH A6, A10.2 |
| W2.6 | W2 | `tools/emit.py` — `emit_chart` with strict Pydantic + row_hash recompute + persist | Backend | 1.5 | W0.5, W1.2 | S2 | row_hash mismatch returns `tool_error: row_hash_mismatch`; valid spec persists | ARCH A6.6 |
| W2.7 | W2 | `tools/skill.py` — `run_skill` dispatcher (registry lookup + ephemeral system fragment) | Backend | 1.5 | W4.0 | S2 | Calling `run_skill('programmatic_eda', ...)` injects fragment exactly once for next turn | RESEARCH §4, ARCH A6.5, A9.3 |
| W2.8 | W2 | Tool dispatch wiring — `build_tools(ctx)` factory | Backend | 0.5 | W2.2–W2.7 | S2 | Returns 5 OpenAI specs + dispatch map; signature stable | ARCH A2 |
| W3.1 | W3 | Reuse `LlmClient.reason()`/`embed()`; add streaming tool-call buffer helper | Backend | 1.0 | W0.3 | S1 | Re-assembles partial `delta.tool_calls` chunks into completed call objects | RESEARCH §3.3 |
| W3.2 | W3 | `reasoning.effort` policy (`medium` orchestrator, `low` for V2 judge stubs) | Backend | 0.5 | W3.1 | S1 | Effort flag wired into `LlmClient.reason()` invocation | RESEARCH §3.3 |
| W3.3 | W3 | Parallel-tool-calls handling (max 4/turn) | Backend | 0.5 | W3.1 | S1 | Test: model emits 3 tool_calls; all 3 dispatched concurrently | RESEARCH §3.3 |
| W3.4 | W3 | Calibrate mid-conversation system-msg honouring (C-2) | Backend | 0.5 | W3.1 | S1 | Either: gpt-5.4 honours injection (default); OR fall back to user-shaped wrapper documented in `skill_invocation.outputs.fragment_mode` | ARCH A9.4, SKILL C2 |
| W4.0 | W4 | Skill registry scaffold (`skills/_registry.py`, `_context.py`, `cli.py reindex`) | Backend | 1.0 | W0.7, W1.4 | S1 | 12 names registered; capability matrix typed; CLI lists skills | SKILL §S3, §S4.3, §S6.3 |
| W4.1 | W4 | **Wave 1** — `programmatic_eda`: tool.py + 5 ported scripts + system_fragment + RAG ingest + smoke test | Skill eng | 1.5 | W4.0 | S1 | S9 smoke test green; key-stat within ±5% of source | SKILL §S4.2 row 1, §S5.5, §S7.2 |
| W4.2 | W4 | **Wave 1** — `data_quality_audit`: tool.py + 5 ported scripts + fragment + RAG + smoke | Skill eng | 1.5 | W4.0 | S1 | as above | SKILL row 2 |
| W4.3 | W4 | **Wave 1** — `time_series_analysis`: tool.py + ts_analyzer port + statsmodels dep + fragment + RAG + smoke | Skill eng | 1.5 | W4.0 | S1 | ARIMA(1,1,1) forecast horizon=0 default; smoke test on `power/timeseries` fixture | SKILL row 4, S11.2 |
| W4.4 | W4 | **Wave 1** — `segmentation_analysis`: tool.py + segment.py port + fragment + RAG + smoke | Skill eng | 1.0 | W4.0 | S1 | k-means without sklearn; smoke test on `companies` top-50 | SKILL row 5 |
| W4.5 | W4 | **Wave 2** — `business_metrics_calculator`: tool.py + power-domain metric library override + fragment + RAG + smoke | Skill eng | 1.5 | W4.0 | S2 | 5 power-domain metrics computable; smoke on `triangulation/l2` | SKILL row 6, S11.4 |
| W4.6 | W4 | **Wave 2** — `root_cause_investigation`: tool.py + drilldown port + fragment + RAG + smoke | Skill eng | 1.0 | W4.0 | S2 | Smoke: canned anomaly + 3 segment axes returns ranked drilldowns | SKILL row 3 |
| W4.7 | W4 | **Wave 2** — `insight_synthesis` (prompt-only) | Skill eng | 0.5 | W4.0 | S2 | Output schema valid; 5 fabricated findings → 5 structured insights | SKILL row 7 |
| W4.8 | W4 | **Wave 2** — `visualization_builder` (prompt-only + JSON-schema validator) | Skill eng | 1.0 | W0.5 | S2 | Recommends valid `chart_type` for 4 data shapes; never recommends `map` in V1 | SKILL row 9, S11.1 |
| W4.9 | W4 | **Wave 3** — `executive_summary_generator` (prompt-only) | Skill eng | 0.5 | W4.0 | S3 | 5-line exec summary on 5 fabricated insights | SKILL row 8 |
| W4.10 | W4 | **Wave 3** — `data_narrative_builder` (prompt-only) | Skill eng | 0.5 | W4.0 | S3 | Stitch insight + chart + caption into 1-paragraph body; no jargon | SKILL row 10 |
| W4.11 | W4 | **Wave 3** — `impact_quantification` (prompt-only) | Skill eng | 0.5 | W4.0 | S3 | Returns `{impact_value, range_lo, range_hi, basis}` valid | SKILL row 11 |
| W4.12 | W4 | **Wave 3** — `technical_to_business_translator` (prompt-only) | Skill eng | 0.5 | W4.0 | S3 | 5 paired technical/exec golden tests pass | SKILL row 12 |
| W4.13 | W4 | RAG ingest pipeline + per-skill embeddings (`cli.py reindex --all`) | Skill eng | 1.0 | W4.1–W4.4 | S2 | ~75 chunks embedded; cosine retrieval k=3 returns sensible chunks (eyeballed) | SKILL §S6 |
| W4.14 | W4 | Skill fidelity regression harness (`tests/agents/insights/skills/`) | Skill eng | 1.0 | W4.1–W4.4 | S2 | pytest runs 12 smoke tests; CI integration | SKILL §S9 |
| W5.1 | W5 | `orchestrator.py` — V1 sequential flow (bootstrap → hypothesise → verify → emit) | Backend | 3.0 | W2.5, W2.6, W2.7 | S2 | Mock-LLM scripted run produces 3 insights end-to-end with valid charts | ARCH A8.1 |
| W5.2 | W5 | `dedup/novelty.py` — Jaccard + cosine on `text-embedding-3-large` | Backend | 1.0 | W3.1 | S2 | Dedups 0.7 Jaccard or 0.85 cosine; 100-pair labelled fixture green-on-most | RESEARCH §9, ARCH A10.3 |
| W5.3 | W5 | Bootstrap survey (`call_api_parallel(SURVEY_ENDPOINTS)`) | Backend | 0.5 | W2.3 | S2 | 8 endpoints called concurrently; results aggregated in <3s | ARCH A8.1 |
| W5.4 | W5 | Schema discovery snapshot (`information_schema.tables`) into agent context | Backend | 0.5 | W0.1 | S2 | Agent system prompt sees a static "available tables" block | ARCH A10.3 |
| W6.1 | W6 | `routers/insights.py` POST /sessions SSE endpoint | Backend | 2.0 | W5.1 | S2 | Curl test emits typed events with `event:` + `id:` + `data:` lines | ARCH A3.1, A5 |
| W6.2 | W6 | GET endpoints (3, 4) + cancel (8) + Last-Event-ID resume on reconnect | Backend | 1.5 | W6.1, W1.6 | S3 | Disconnect mid-stream → reconnect with last id → server replays missing events | ARCH A3.1, A3.2 |
| W6.3 | W6 | SSE event Pydantic models + emission helpers | Backend | 1.0 | W6.1 | S2 | All 12 V1 event types validated on emit; payload conforms | ARCH A5 |
| W6.4 | W6 | Persistence writes wired (insight_session, insight, chart, agent_message, tool_call_log, skill_invocation) | Backend | 1.0 | W1.2, W1.3, W6.1 | S2 | After a session run: every event has a corresponding DB row; idempotent | ARCH A11.1 |
| W6.5 | W6 | Heartbeat (15s `event: ping`) + 5-min replay TTL | Backend | 0.5 | W6.1 | S3 | EventSource stays open across 5min idle; ring buffer GC'd after 5min | ARCH A5.1 |
| W7.1 | W7 | Extract `agentchat/MarkdownMessage.tsx` + `chartTheme.ts` | Frontend | 1.0 | W0.6 | S1 | ChatPanel still renders; no regressions on `npm test` | RESEARCH §5.3, ARCH A12 |
| W7.2 | W7 | Extract `agentchat/InsightChart.tsx` (generalised; back-compat with V0 `series` shape) | Frontend | 1.5 | W0.5, W7.1 | S1 | Renders all 10 ChartSpec.chart_type values; ChatPanel V0 chart still works | RESEARCH §5.3, UX U4 |
| W7.3 | W7 | Extract `agentchat/ToolTrace.tsx` + `CitationList.tsx` (dual-shape: DB cite + V2 WebCitation) | Frontend | 1.0 | W7.1 | S1 | Both shapes render; ChatPanel unchanged behaviourally | RESEARCH §5.3 |
| W7.4 | W7 | Extract `agentchat/AgentMessage.tsx` + `index.ts` barrel | Frontend | 0.5 | W7.1, W7.3 | S1 | ChatPanel.tsx imports from `agentchat/` only | RESEARCH §5.3 |
| W7.5 | W7 | `insights/sse.ts` — typed SSE client with Last-Event-ID + auto-reconnect | Frontend | 1.0 | W6.3 (or fixture) | S2 | Stub-server test: 12-event sequence consumed in correct order; reconnect resumes | ARCH A5 |
| W7.6 | W7 | SSE fixture-server stub for offline frontend dev | Frontend | 0.5 | W6.3 | S1 | Replays a fixed JSON file as SSE; lets W8 be built before W6.1 lands | T5.4 |
| W7.7 | W7 | `tabs/AIInsightsTab.tsx` registered in `App.tsx` nav (rightmost; resolves U-Q1) | Frontend | 0.5 | W0.7, U-Q1 | S1 | New tab visible in nav; existing tabs unchanged | UX U2.1 |
| W7.8 | W7 | `frontend/src/styles/insightTokens.ts` — consolidated token module | Frontend | 0.5 | W0.8 | S1 | Imported by AI Insights components; existing tabs untouched | UX U11.7 |
| W7.9 | W7 | Frontend code-review checkpoint | Frontend | 0.5 | W7.1–W7.4 | S1 | PR approved by 2 reviewers | — |
| W8.1 | W8 | `insights/StreamingSkeleton.tsx` + surveying preamble | Frontend | 1.0 | W7.5 | S2 | Skeleton hierarchy per UX U7.2; reduced-motion variant | UX U7.2, U7.4, D-4, D-5 |
| W8.2 | W8 | `insights/InsightCard.tsx` (header, headline, subtitle, chart frame, caption, KPI strip, reasoning toggle) | Frontend | 2.5 | W7.2, W8.1 | S2 | All E1–E11 elements per UX U3.2; streaming "drafting" treatment | UX U3, D-1 |
| W8.3 | W8 | `insights/InsightChartFrame.tsx` (wraps `<InsightChart>`, adds caption + underlying-data link modal) | Frontend | 1.0 | W7.2 | S2 | All 4 sizing rules per UX U4.2; empty/zero-data state per U4.5 | UX U4 |
| W8.4 | W8 | `insights/InsightProvenanceFooter.tsx` (collapsed default; expand chevron; 7 fields) | Frontend | 1.0 | W8.2 | S2 | All 7 PRD §5.6 fields rendered; skill chips animate (or static under reduced-motion) | UX U3.5, D-6 |
| W8.5 | W8 | `insights/EmptyState.tsx` + `ErrorState.tsx` + cancelled-banner | Frontend | 1.0 | W8.2 | S2 | EE1–EE10 cases per UX U8 covered | UX U8, D-8 |
| W8.6 | W8 | `insights/SessionRunner.tsx` (Run button + cancel + state machine) | Frontend | 1.5 | W7.5, W8.2 | S2 | Start → cancel → restart loop works; focus-management per UX U9.2 | UX U2.4, U9 |
| W8.7 | W8 | Keyboard shortcuts + ARIA-live regions + reduced-motion variants | Frontend | 1.0 | W8.6 | S3 | All UX U9.1 shortcuts work; axe-core scan clean on a sample card | UX U9, U10 |
| W8.8 | W8 | Permalink + Copy-as-Markdown + kebab menu | Frontend | 0.5 | W8.2 | S3 | Permalink resolves via hash deep-link (UX U9.3) | UX U3.6, U9.4 |
| W8.9 | W8 | Per-insight 5-star rating widget (in kebab; instruments G4) | Frontend | 0.5 | W8.2, U-Q11 | S3 | Click writes a `tool_call_log` row with `event=user_rating` | PRD §7.2, U-Q11 |
| W9.1 | W9 | `observability/logging.py` (structured JSON per SSE event) | Backend | 0.5 | W6.1 | S2 | Each event tagged with `session_id` + `insight_id` | ARCH A11.1 |
| W9.2 | W9 | `observability/trace.py` + tool_call_log writer | Backend | 0.5 | W6.4 | S2 | Every tool dispatch produces a `tool_call_log` row with latency | ARCH A11.1 |
| W9.3 | W9 | Frontend telemetry hooks (insight render time, chart render time, SSE reconnects) | Frontend | 0.5 | W8.2 | S3 | Posts to existing `/api/events` endpoint | ARCH A11.2 |
| W10.1 | W10 | V1 test plan doc | PM | 0.5 | — | S2 | One page: surface, fixtures, dogfood protocol | PRD §7 |
| W10.2 | W10 | 3 fixture insights (golden) for end-to-end smoke test | PM + Eng | 1.0 | W5.1 | S2 | Frozen DB snapshot + expected `insights[]` shape; CI-runnable | SKILL §S9.3 |
| W10.3 | W10 | Success-metric instrumentation review (link each PRD §7 metric to a task; see T11) | PM | 0.5 | — | S3 | T11 table green | PRD §7 |
| W10.4 | W10 | **the user calibration session 1** (5 dogfood sessions; rate insights) | PM + the user | 1.0 | W6.1, W8.2 | S3 | ≥30% useful per PRD §8 V1 exit; capture failure modes | PRD §8 V1 exit |
| W10.5 | W10 | Re-prompt cycle based on the user feedback (orchestrator system prompt tuning) | Backend + PM | 1.0 | W10.4 | S3 | Post-tune dogfood: ≥3 of 5 useful (DoD) | PRD §8 V1 exit, T7 |
| W10.6 | W10 | Latency budget verification (5-insight session p50 < 90s) | Backend | 0.5 | W6.1, W5.1 | S3 | p50 < 90s on 10 trial sessions; report attached | PRD §7.1 Q5, ARCH A10.4 |
| W11.1 | W11 | Per-skill README (12 skills) — one paragraph + smoke fixture pointer | Skill eng | 1.0 | W4.1–W4.12 | S3 | One README per `skills/<name>/`; linked from registry | — |
| W11.2 | W11 | V1 demo script for the user unveiling | PM | 0.5 | W10.4 | S3 | 7-step click-through script; pre-recorded fallback | — |
| W11.3 | W11 | the user-facing handoff brief (what's V1, what's coming, how to read provenance) | PM | 0.5 | W10.4 | S3 | 1-page brief shared in advance | — |
| **TOTAL** | | | | **56.0** | | | | |

### T6.1 Sprint allocation totals

| Sprint | Tasks (count) | Dev-days | Notes |
|---|---|---|---|
| **S1 (foundations + scaffolds + skills wave 1)** | 25 | 19.5 | All W0 + most of W1/W2/W3 + W7 extraction + 4 skills |
| **S2 (orchestrator + UI + skills wave 2)** | 25 | 23.0 | W2.5/W2.6/W2.7 + W4 wave 2 + W5 + W6 + W8 backbone + W9 logging |
| **S3 (polish + dogfood + skills wave 3 + demo)** | 17 | 13.5 | W4 wave 3 + W6.2/W6.5 + W8.7–W8.9 + W10 + W11 |
| **Total** | 67 | **56.0** | Within 60-day capacity (3 × 20) → **4 dev-day buffer** |

### T6.2 Per-role load (rough)

| Role | Days | Notes |
|---|---|---|
| Backend (incl. skill engineer) | ~38 | One person can do this in 6 weeks at ~6.3 days/week effective |
| Frontend | ~13 | One person at ~2.2 days/week — comfortable |
| Designer | ~1 | W0.8 + ad-hoc reviews |
| PM | ~3.5 | Calibration + decisions + demo + ratifications |

---

## T7. Definition of Done — V1

Crisp checklist for the the user-facing V1 acceptance gate.

| # | Criterion | Owner verifier | Pass signal |
|---|---|---|---|
| DoD-1 | 5 insights generated from seed DB in **< 90 s p50** per session | Backend (W10.6) | 10/10 trial sessions <90 s p50 |
| DoD-2 | Each card shows headline + materiality chip + chart + provenance footer (7 fields) | Frontend (W8.2/W8.4) | Visual QA + axe-core clean |
| DoD-3 | Each chart has `row_hash` provenance and validates against ChartSpec v1 JSON-Schema | Backend (W2.6) | All emitted charts persisted with `row_hash`; mismatch counter = 0 in dogfood |
| DoD-4 | Per-card "skills used" chips render and are correct | Frontend (W8.4) | Chip set ⊆ actual `skill_invocation` rows for that insight |
| DoD-5 | Cancel + resume (Last-Event-ID) works | Backend + FE (W6.2/W7.5) | Manual disconnect-and-resume test green |
| DoD-6 | No chat dock, no web-search affordance, no citation row visible (V1 hides those affordances) | Frontend (W8) | Visual QA + grep on rendered DOM |
| DoD-7 | Lighthouse-ish a11y baseline: keyboard navigation works end-to-end; ARIA-live preamble announces session events | Frontend (W8.7) | UX U10.4 keyboard flow runs to completion; axe-core finds zero serious issues |
| DoD-8 | the user dogfood: **≥ 3 of 5 insights judged "useful or insightful"** in calibration session (W10.4 + W10.5) | PM + the user | Captured in `tool_call_log` with `event=user_rating` |
| DoD-9 | Zero hallucinated tables/columns across 20 dogfood sessions (PRD G6) | Backend (W2.1) | sqlglot allowlist log shows zero rejections of valid SELECTs and 100% rejection of out-of-allowlist refs |
| DoD-10 | Latency caps respected (12-turn loop, 4-wide parallel, 480s session, 48-call max) (PRD §5.1) | Backend (W2.5) | Cap-trip counter ≤ 5 per 100 sessions in dogfood |

If any DoD item fails the V1 demo bar, the demo is gated until W10.5 re-prompt cycle closes the gap (within the 1-day re-prompt allocation).

---

## T8. V2 backlog (high-level)

Sized at S/M/L. **Status legend:** ✅ shipped (Track B, 2026-05-04) · 🟡 partial · ⏳ deferred to V2.1 / V3.

| ID | Item | Size | Status | Notes |
|---|---|---|---|---|
| V2-01 | Web search tool — **Brave primary** (no Tavily fallback in V2) + circuit breaker (3 fails / 60 s → 5 min open) + 8-call/session cap + 280-char snippet truncation + graceful `web_search_unavailable` SSE event | M | ✅ | `backend/agents/insights/tools/web_search.py`. Brave-primary is a kickoff override of RESEARCH §1.3 (Tavily was research-time default). |
| V2-02 | `emit_citation` tool — substring/whitespace-normalised rationale gate, GW/MW/%/$ numeric-token check (downgrades to tag=`context` with warning), 280-char snippet ceiling, URL HEAD reachability | M | ✅ | `backend/agents/insights/tools/emit_citation.py`. Persister callback hook surfaced; `low_external_support` flip to be implemented in chat-router persister (V2.1). |
| V2-03 | Agree/disagree judge sub-call (gpt-5.4-mini, low effort, strict-JSON) | M | ✅ | `judge_citations()` in `web_search.py`. |
| V2-04 | Per-insight chat dock + `POST /insights/{insight_id}/chat` SSE + `GET /insights/{id}/chat` history + `GET /insights/{id}/citations` | L | ✅ | `backend/routers/insights.py`; `frontend/src/components/tabs/ai-insights/InsightChatDock.tsx`. ToolLoopDriver constructed with `max_turns=12, max_parallel_tool_calls=4, wall_budget_seconds=45`. |
| V2-05 | Cohort-analysis skill conversion (full pandas/numpy port; visualizer NOT ported) | M | ✅ | `backend/agents/insights/skills/cohort_analysis/`. |
| V2-06 | Methodology-explainer skill (prompt-only, deterministic fallback) | S | ✅ | `backend/agents/insights/skills/methodology_explainer/`. |
| V2-07 | Peer-review-template skill — verdict enum `pass`/`revise`/`reject` (broader than kickoff's pass/revise — defensive default `revise` on parse error) | M | ✅ | `backend/agents/insights/skills/peer_review_template/`. |
| V2-08 | Parallel sub-agents per insight (`asyncio.gather`) — forward-compat hook landed in V1 | M | ⏳ | ARCH A8.2 — deferred to V2.1. |
| V2-09 | Citation hover-cards + agree/disagree pill row (shape-redundant ✓/✗/◐ glyphs, 300×auto, 300 ms hover/0 ms focus mount, Esc dismiss) | M | ✅ | `CitationHoverCard.tsx`, `CitationPill.tsx`. |
| V2-10 | "Regenerate this insight" + "Report as wrong" kebab actions | S | ⏳ | Deferred. |
| V2-11 | Right rail (≥1480 px viewport) with session summary | S | ⏳ | Deferred. |
| V2-12 | `low_external_support` card chip + emit logic | S | ✅ | Pill landed in V1 (`LowSupportPill`); emit logic in `emit_citation.py`. Per-insight ≥2-citations rollup persister: V2.1. |
| V2-13 | Inline thumb-up/down quick-rate (instruments G4 better) | S | ⏳ | Deferred. |
| V2-14 | `query-validation` skill (S10.3) folded into SQL gate | S | ⏳ | Deferred. |
| V2-15 | Subscribe button UI scaffold (no backend wiring yet) | S | ✅ | `SubscribeButton.tsx` — toast "V3 — coming soon" 3 s. |
| V2-16 | Tool-call cap raise: insight discovery 12×4=48 → **20×4=80**; chat stays 12×4=48 | XS | ✅ | `tool_loop.py::DEFAULT_MAX_TURNS = 20`; chat router constructs ToolLoopDriver explicitly with `max_turns=12`. |
| V2-17 | SSE event taxonomy V2 additions: `web_search_unavailable`, `assistant_message_token`, `tool_call_started`, `tool_call_complete`, `message_complete` | XS | ✅ | `specs/sse_events.py` (13 → 18 events; discriminated `SSEEvent` Union extended). |
| V2-18 | Skill registry expansion 12 → **15** | XS | ✅ | `skills/__init__.py::ALL_SKILL_NAMES`; `tools/run_skill.py::ALL_SKILLS` (`V1_SKILLS` retained as alias). |
| V2-19 | Alembic 011 migration: `insight_thread`, `insight_subscription`, `agent_message.thread_id` FK + index, `ai_insight.citation_count`, `ai_insight.web_search_calls` | S | ✅ | `backend/alembic/versions/011_v2_chat_and_citations.py`. SQL dry-run clean. |
| V2-20 | Frontend feature-flag probe (`isV2Enabled` via `/api/health` → fallback `VITE_AI_INSIGHTS_V2`) | XS | ✅ | `AIInsightsTab.tsx`. Threads through to `InsightCard`. |
| V2-21 | V2 pytest suite (web_search circuit breaker, citation tagging, chat isolation, peer-review thresholds, cohort matrix shape, methodology rendering) — 27 tests | S | ✅ | `backend/tests/test_v2_*.py`; 27 passed in 1.71 s. |

---

## T9. V3 backlog

| ID | Item | Size | Notes |
|---|---|---|---|
| V3-01 | Cron schedule runner (`schedules/runner.py`) + UI list | M | ARCH A2, A14.2 |
| V3-02 | Insight-diff renderer (canonical claim match across runs; Δ chip) | L | UX U13.2 |
| V3-03 | Subscribe / notify (in-product banner + optional email) | M | PRD G10 |
| V3-04 | Geospatial-analysis skill (if Recharts gains map OR Leaflet emit path) | L | PRD §6.2 row 26 |
| V3-05 | Audit history page (full skill+tool trace per insight) | M | PRD §5.5 power-user |
| V3-06 | Scheduled emails to the user (weekly digest) | S | parent PRD §10 alignment |
| V3-07 | RBAC (multi-user; auth integration) | L | parent PRD §8 D5 deferred |
| V3-08 | Share-by-link (short-link mint + 30-day expiry) | M | UX U9.4 |
| V3-09 | Cross-session embedding novelty filter | S | RESEARCH §9 |
| V3-10 | Power-user mode (full skill-call trace expander) | M | PRD §5.5 |

---

## T10. Risks & mitigations (V1-specific)

Cross-doc consolidation. Probability/impact: low/med/high.

| ID | Risk | Prob | Impact | Mitigation | Early-warning signal |
|---|---|---|---|---|---|
| RV-1 | **ChartSpec v1 instability** — agent emits malformed specs | med | high | Pydantic strict validation at `emit_chart`; row_hash check; agent retry up to 2× per insight. Hard JSON-Schema gate. | `row_hash_mismatch` or `chart_validation_error` rate >5% in dogfood |
| RV-2 | **sqlglot allowlist gaps** — false positives blocking valid SELECTs OR false negatives letting through write-shaped SQL | med | high | Fuzz test with 100 hostile + 100 valid SELECTs; read-only DB role is the second line of defense; tx-scoped statement_timeout is the third | `unsafe_sql` rate >10% (false positive) or any UPDATE/DELETE row reaching gate |
| RV-3 | **LlamaStack quota / rate-limit** even though no $ cost | low | med | Token-name correctness (`max_completion_tokens`); 1× retry with jitter on 5xx; parallel-tool cap 4; sequential per-insight (V1) | 5xx rate >5% OR sustained 429 |
| RV-4 | **Skill conversion fidelity drift** (PRD R4) — Llama-Stack-tuned skills disagree with Claude-Code originals | high | med | S9 smoke harness per skill; ship in 3 waves with highest-confidence first (W4 wave 1); per-skill golden statistic ±5% | Smoke test failures or the user flags "weird" skill output in dogfood |
| RV-5 | **the user-perceived "smartness"** — insights too obvious or too generic | med | high | (a) Non-trivial filter in dedup; (b) the user calibration session at end of S3 with re-prompt budget (W10.5); (c) materiality+novelty rank prefers `[L]` | <3 of 5 useful in calibration; the user flagging "I knew that already" >3× |
| RV-6 | **ChatPanel extraction regresses existing chat** | low | high | Keep V0 `series` shape back-compat in `<InsightChart>`; `ChatPanel.tsx` is consumer-only of `agentchat/`; FE code review checkpoint W7.9 | Visual diff or snapshot test fail on existing ChatPanel |
| RV-7 | **Latency overruns >120s/session** hurting demo | med | med | Parallel bootstrap calls (W5.3); stream insights as they finish; `medium` reasoning effort; per-insight 120s soft cap clips early | p50 >90s on the W10.6 verification day |
| RV-8 | **Mid-conversation system-msg ignored by gpt-5.4** (C-2) — skill fragments don't influence next turn | low | high | W3.4 calibration; documented user-shaped fallback (ARCH A9.4); fragment_mode logged in skill_invocation | Skill output ignores fragment guidance in W3.4 calibration |
| RV-9 | **Provisioning slip** (DB role, pgvector) | low | med | W0.1/W0.2 are explicitly week-zero tasks owned by infra; backend can't start safely without them | Day 3 of S1 and W0.1 still open |
| RV-10 | **Prompt injection via ingested data** (PRD R10) | low | med | Tool outputs are JSON, not raw text concatenation. Skill prompts treat data as values. V1 spot-audit during dogfood. | Any insight headline echoes injected text; investigate W10.4 |
| RV-11 | **Hallucinated table/column refs** (PRD G6) | med | high | Schema discovery snapshot in agent context (W5.4); sqlglot allowlist; live `information_schema` filter at session start | Any rejected SQL referencing non-existent table |
| RV-12 | **Replay buffer pressure** (multi-worker uvicorn) | low | low | V1 deploys single uvicorn worker (matches existing dev/dogfood); flag for V2 if scale-out lands | n/a in V1 |

---

## T11. Success-metric instrumentation

Mapping each PRD §7 metric to the task that instruments it. **Every metric has at least one instrumenting task.**

| PRD ID | Metric | V1 target | Instrumenting task(s) | Storage |
|---|---|---|---|---|
| Q1 | Insights per session | 5–10 | W6.4 (persist), W10.6 (verify) | `insight_session.insights_emitted` |
| Q2 | % insights with non-trivial chart | ≥80% | W2.6 (every emit logged), W10.4 (manual review) | `chart` table + dogfood notes |
| Q5 | p50/p95 generation latency | ≤3 / ≤8 min | W9.1 (logging), W10.6 (verification) | `insight_session.duration_ms` |
| Q6 | Tool-call cap breaches/100 sessions | ≤5 | W2.5 (caps enforced), W9.2 (tool_call_log) | `tool_call_log` |
| Q7 | Hallucinated table/column refs/100 sessions | 0 | W2.1 (sql_gate), W9.2 | `tool_call_log.error_code='unsafe_sql'` aggregation |
| Q8 | Dedup rejects/session | ≤2 | W5.2 (novelty.py), W9.1 | `insight_session` log entries |
| **G4** | **the user ≥40% useful (V1: ≥30%; DoD: 3 of 5)** | ≥30% (V1 relaxed bar) | **W8.9 (5-star widget)**, W10.4 (calibration), W10.5 (re-prompt) | `tool_call_log` rows with `event=user_rating` |
| G5 | Generation completes ≤3 min p50 / ≤8 min p95 | as Q5 | (same as Q5) | (same) |
| G6 | Zero hallucinated tables/columns | 0 | (same as Q7) | (same) |

**No metric is uninstrumented.** Q3, Q4, Q9 are V2 metrics (web citations + chat engagement) and are explicitly out of V1.

---

## T12. Cross-references

- [`./PRD.md`](./PRD.md) — V1 scope, OQ1–OQ11, success metrics §7, phased rollout §8.
- [`./RESEARCH.md`](./RESEARCH.md) — Provider picks (Tavily), ChartSpec v1, ToolLoopDriver contract, skill-conversion pattern, ChatPanel reuse, SSE taxonomy.
- [`./ARCHITECTURE.md`](./ARCHITECTURE.md) — Module layout A2, HTTP API A3, ChartSpec A4, SSE events A5, tools A6, data model A7, orchestration A8, skill registry A9, safety A10, observability A11, frontend A12, error handling A13, V2/V3 deltas A14, designer/PM open issues A15.
- [`./SKILL_CONVERSION.md`](./SKILL_CONVERSION.md) — Per-skill mapping S4, script-port playbook S5, RAG playbook S6, system-fragment composition S7, fidelity test plan S9, drop list S10, open issues S11.
- [`./UX.md`](./UX.md) — Personas U1, page layout U2, card anatomy U3, chart styling U4, citations U5, chat dock U6, loading/streaming U7, error states U8, interactions U9, accessibility U10, tokens U11, U14 open questions.

---

**End of TASKS.md.**
