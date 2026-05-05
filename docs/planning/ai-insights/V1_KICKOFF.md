# V1 Kickoff — AI Insights Tab
**Date:** 2026-05-04 · **Status:** kickoff · **Owner:** PM
**Cross-refs:** [`./PRD.md`](./PRD.md) · [`./RESEARCH.md`](./RESEARCH.md) · [`./ARCHITECTURE.md`](./ARCHITECTURE.md) · [`./SKILL_CONVERSION.md`](./SKILL_CONVERSION.md) · [`./UX.md`](./UX.md) · [`./TASKS.md`](./TASKS.md)

> One-page briefing for new joiners. Read in 5 minutes; start working.

---

## 1. V1 scope (5 bullets)

- **Tab placement:** new 10th tab `AI Insights`, **rightmost after Sources** (per UX U2.1, TASKS U-Q1).
- **Active skills:** **12** converted skills shipped in 3 waves of 4 across S1/S2/S3 (per PRD §6.3, TASKS T1.1, SKILL §S4.2).
- **Live tools:** **5** — `query_database`, `call_api`, `get_chart_data`, `run_skill`, `emit_chart`. **No** `web_search`, **no** `emit_citation` in V1 (per PRD §8 V1, ARCH A6).
- **Generation mode:** **batch per session** (5–10 insights, dynamic, agent-ranked); **SSE streaming** with typed events + Last-Event-ID resume; **no chat** (per PRD §8 V1, ARCH A5, TASKS T1.1).
- **Charts:** **Recharts only**, **ChartSpec v1** (Pydantic + JSON-Schema); ≥80% of insights ship a non-trivial chart (per PRD §5.2 / G2, ARCH A4, RESEARCH §2.3).

---

## 2. Ratified defaults (immutable baseline — per TASKS §T2)

These were approved 2026-05-04 (gabrielle.lyu@oracle.com). Do not re-debate.

| ID | Item | Ratified value |
|---|---|---|
| R-2 | ChartSpec v1 | Pydantic + JSON-Schema; ratify in W1.6, gates S1 day 1 |
| R-3 | Streaming protocol | SSE with typed `event:` names + Last-Event-ID resume |
| R-5 | Materiality rubric (V1) | Agent self-rate 3-level S/M/L (Karan sign-off on prompt before V2) |
| R-7 | Citation freshness | ≤24 months default; flag-only beyond |
| R-8 | Confidence rubric | low = (rows<50 OR no agree-cite OR stale); high = (rows≥200 AND ≥1 agree-cite AND fresh); else medium |
| P-3 | Chat retention column | V1 alembic adds `delete_after` column (default NULL) — avoids V2 follow-up migration |
| C-1 | Embedding-cosine novelty | 0.85; calibrate against 100 hand-labelled pairs in S2 |
| C-2 | Mid-conversation system-msg | Calibrate gpt-5.4 honouring on S1 day 1; fall back to user-shaped injection if not honoured |
| C-5 | RAG retrieval | k=3; verify per-skill in S1 RAG ingest |
| Tool-loop caps | ToolLoopDriver | **12 turns / 4-wide parallel / 120 s per insight / 480 s per session / 40 calls** (V1) per ARCH A10.2 |
| Dedup | Novelty filter | Jaccard ≥0.7 intra-session + cosine ≥0.85 cross-session (per ARCH A10.3) |
| Skill count | 12 active by V1 end | Ship-order: waves of 4 across S1/S2/S3 (not a hard cap of 6–8) |
| U-Q1 | Tab placement | Rightmost, after Sources |
| U-Q11 | Rating widget | V1: 5-star in kebab; V2: thumb up/down inline |
| Headcount | Option A | Add 2nd backend engineer for W4 wave 2 in S2 |

---

## 3. Workstream order (W0 → W11, per TASKS §T4)

| WS | Scope (one-liner) |
|---|---|
| **W0** | Pre-kickoff prerequisites (DB role, pgvector, sqlglot, ChartSpec schema, agentchat plan, repo scaffold, brand audit) |
| **W1** | Foundations & persistence — alembic migration, 8 new tables + pgvector, SQLAlchemy models, replay ring buffer |
| **W2** | Tool loop & safety — `tool_loop.py`, `sql_gate.py`, in-process router caller, get_chart_data registry, emit_chart |
| **W3** | LlamaStack adapter — reuse `LlmClient`, parallel-tool buffering, `reasoning.effort=medium`, mid-turn system-msg calibration |
| **W4** | Skill conversion — 12 V1 skills × {tool.py + system_fragment + RAG ingest}, 3 waves |
| **W5** | Insight orchestration — bootstrap → hypothesise → verify → emit; novelty filter; dedup |
| **W6** | HTTP API + SSE — `routers/insights.py`, typed events, Last-Event-ID resume, persistence writes |
| **W7** | Frontend foundations — extract `agentchat/` (6 primitives), SSE client, ChartSpec renderer, AIInsightsTab nav registration |
| **W8** | Frontend insights UI — InsightCard, ProvenanceFooter, SurveyingBanner, SkeletonStack, EmptyState/ErrorState, SessionRunner |
| **W9** | Observability & logging — structured per-event JSON, tool_call_log writes, frontend telemetry, user-visible provenance footer |
| **W10** | QA & dogfood — test plan, fixtures, Karan calibration session, success-metric instrumentation |
| **W11** | Docs & demo prep — per-skill READMEs, V1 unveiling demo script, Karan handoff brief |

---

## 4. Critical path (per TASKS §T1.3)

If any node slips a day, the demo slips a day.

`W1.1 alembic migration → W1.2 SA models → W2.1 sql_gate → W2.5 ToolLoopDriver → W2.6 emit_chart + ChartSpec v1 → W6.1 SSE router → W7.1 agentchat extraction → W8.2 InsightCard renderer → W10.4 Karan dogfood`

Predecessors: W0.1 (read-only Postgres role) and W0.5 (ChartSpec v1 schema) gate the whole chain (per TASKS §T5.3).

---

## 5. Day-1 unblockers (THE most important section)

Every artifact other workstreams are blocked on. **All due EOD S1 day 1** unless noted.

| # | Artifact | Owner | Due | Blocks | Source |
|---|---|---|---|---|---|
| 1 | **ChartSpec v1 Pydantic model + JSON-Schema** at `backend/agents/insights/specs/chart_spec.schema.json` | Architect / Backend | EOD S1 day 1 | All chart work, all `emit_chart`, all UI below card chrome | TASKS W0.5, ARCH A4, RESEARCH §2.3 |
| 2 | **gpt-5.4 mid-conversation system-msg calibration test** (C-2) — confirm honoured or fall back to user-shaped injection | Backend | EOD S1 day 1 | All skill invocations (W4) and orchestrator (W5) | TASKS W3.4, ARCH A9.4, SKILL C2 |
| 3 | **sqlglot SQL gate skeleton** (`safety/sql_gate.py`) — AST allowlist, fuzz-test scaffolding | Backend | EOD S1 day 1 | `query_database` (W2.2), all DB-touching skills | TASKS W2.1, ARCH A10.1 |
| 4 | **agentchat extraction plan doc** — read 586-line ChatPanel.tsx, list 6 files + diff ranges | Frontend | EOD S1 day 1 | Every frontend insight component (InsightChart, MarkdownMessage, CitationList) | TASKS W0.6, RESEARCH §5.3 |
| 5 | **Read-only Postgres role `ai_agent`** provisioned (`NOSUPERUSER`, `GRANT SELECT`, `CONNECTION LIMIT 4`); `AI_AGENT_DB_URL` secret in env | Infra / Backend | EOD S1 day 1 | All `query_database` execution; gate is moot without role | TASKS W0.1, ARCH A1.3, A10.1 |
| 6 | **pgvector extension enabled** (`CREATE EXTENSION IF NOT EXISTS vector` in alembic) | Backend | EOD S1 day 1 | RAG ingest (W4), all skill RAG retrieval | TASKS W0.2, ARCH A7 |
| 7 | **OCI brand-token audit** — confirm hex values in PowerTab + ChatPanel match U11.5; record U10.3 `#64748b` accessibility exception | Designer + Frontend | EOD S1 day 1 | W7/W8 visual styling | TASKS W0.8, UX U10.3, U11.5 |

Other prerequisites that share day 1: W0.3 LlamaStack smoke test, W0.4 sqlglot dep added, W0.7 repo scaffold (per TASKS §T3).

---

## 6. What this brief does NOT re-decide

- Do **not** re-debate any item in §2 (ratified defaults). All listed values are immutable for V1.
- Do **not** change the ChartSpec v1 contract once published in W0.5. Schema breaking change = re-baseline; route through PM.
- Do **not** modify the 22 existing routers; AI Insights is **strictly additive** (per parent PRD §S5, PRD §3 N4).
- Do **not** introduce a new charting library. **Recharts only** (per PRD §5.2, RESEARCH §2.2).
- Do **not** add `web_search`, `emit_citation`, chat dock, or per-insight chat thread in V1 (V2 scope, per PRD §8, ARCH A14.1).
- Do **not** ship maps in V1/V2 (`geospatial-analysis` deferred V3, per ARCH A4.2 / D9).
- Do **not** add auth, multi-user features, or PDF/email export in V1 (per PRD §3 N8/N9, parent PRD §8 D5).
- Do **not** target tablet/mobile — desktop-first (per UX U2.3, ARCH D10).
- Do **not** convert skills via patterns (b) or (c). Pattern (a) only — each skill = one tool fn under `run_skill` (per SKILL §S1.1, RESEARCH §4).
- Do **not** treat the "6–8 high-confidence skills" line as a cap. **12 active by V1 end**, ship-order in waves (per TASKS T1.1 / P-7).

---

## 7. V1 demo acceptance (per PRD §7 / §8, TASKS §T7)

| # | Criterion | Target |
|---|---|---|
| A1 | Insights per session | **5–10** (dynamic, agent-ranked) — per PRD G1, Q1 |
| A2 | % insights with non-trivial chart | **≥80%** — per PRD G2, Q2 |
| A3 | p50 generation latency | **≤3 min** (DoD: <90 s p50 on 5-insight seed-DB session) — per PRD G5/Q5, TASKS DoD-1 |
| A4 | Hallucinated tables/columns | **0** per 100 sessions — per PRD G6/Q7, TASKS DoD-9 |
| A5 | Karan dogfood usefulness | **≥30%** "useful" (V1 relaxed bar; DoD: ≥3 of 5 in calibration) — per PRD §8 V1 exit, TASKS DoD-8 |
| A6 | Tool-call cap breaches | **≤5 per 100 sessions** — per PRD Q6, TASKS DoD-10 |
| A7 | Cancel + Last-Event-ID resume | works manually end-to-end — per TASKS DoD-5 |
| A8 | Provenance footer renders all 7 PRD §5.6 fields | 100% — per TASKS DoD-2 |
| A9 | All emitted charts validate against ChartSpec v1 + row_hash matches | row_hash mismatch counter = 0 — per TASKS DoD-3 |

Failure on any A-item gates the demo until W10.5 re-prompt cycle closes the gap (1-day buffer in S3).

---

**End of V1_KICKOFF.md.**
