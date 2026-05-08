# PRD — AI Insights v2 Redesign, Phases B / C / D

**Status:** Draft for engineering kickoff
**Date:** 2026-05-07
**Owner:** PM (Strategic Insights Tool)
**Source spec:** `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_spec.md`
**Predecessor:** Phase A (workspace artefacts, `read_workspace`, `GET /api/insights/open-questions`, Alembic post-upgrade hook, APScheduler freshness job) — already shipped, out of scope here.

---

## Overview

This PRD specifies the remaining work to retire the FactPack-driven AI Insights v1 flow and replace it with the agent-driven v2 flow defined in `ai_insights_v2_spec.md`. It scopes:

- **Phase B** — Document retrieval infrastructure: `edgar_passages` + `permit_passages` indexes and the `search_documents` MCP tool. Phase B.1 ships BM25-only; Phase B.2 (pgvector hybrid) is gated on a measured recall miss.
- **Phase C** — New tools (`build_chart`, hardened `query_database`), reordered `persist_insight`, the `synthesis_rules_v2.md` prompt, and the `version="v2"` branch in `agentic_synthesis`.
- **Phase D** — Cutover: frontend "Tracked questions" sidebar, default `version="v2"` on new sessions, deprecation header on v1, and a 2-week soak before removing v1 code paths.

Phase A artefacts are referenced as dependencies. They are not re-described here.

---

## Problem Statement

Per spec §1, the shipping AI Insights flow has five concrete failure modes that v2 must collectively fix. Phases B–D address all of them; Phase A only laid the groundwork.

1. **Shallow insights — agent paraphrases pre-computed SQL.** `hypothesizer.build_factpack` runs 11 hardcoded aggregators and `synthesis_rules.md` discourages drill-down. The agent reformulates rows it was handed instead of discovering anything.
2. **Bar-only charts.** `_chart_from_supporting_rows()` collapses every supporting row set to `{entity → max(value)}`. Stacked, grouped, line, and time-series intents silently degrade to a single scalar per entity because `FactRow` has one `value` field.
3. **Post-hoc chart synthesis.** The agent picks `chart_type` *inside* `persist_insight`; the chart is reverse-engineered from row IDs after the claim is written. The chart shape cannot match the claim by construction.
4. **Amnesiac sessions.** Cross-day dedup is embedding similarity over headlines. There is no journal, no status flips, no "I flagged this 3 days ago, +180 MW since."
5. **No document grounding.** `edgar_extractions` lands as structured columns. The agent cannot cite the actual contract language behind a finding.

Phases B–D fix (1) by enabling drill via `query_database` + `search_documents`, (2) and (3) by making `build_chart` a prerequisite for `persist_insight`, (4) by exposing the OpenClaw memory journal in the prompt and a frontend sidebar, and (5) by adding passage retrieval with citations that resolve to URLs and `retrieved_at` timestamps.

---

## Goals & Non-Goals

### Goals (success criteria from §13)

V2 is shippable when all of the following hold on the 10-scenario golden set and on production traffic during the soak window:

- **G1.** ≥80% of insights cite either a `query_database` row or a `search_documents` passage that was *not* present in the v1 FactPack equivalent.
- **G2.** ≥50% of charts use a non-bar type (stacked, grouped, line, treemap, etc.) when the claim warrants it.
- **G3.** ≥30% of sessions advance ≥1 prior journal entry (verified by `update_memory` calls referencing an `id` returned by `memory_search` at session start).
- **G4.** Latency: p95 wall-clock ≤ 900s; p50 ≤ 480s.
- **G5.** Manual rubric: V2 beats V1 on ≥7/10 scenarios for "specificity + actionability."
- **G6.** Document retrieval recall@8 ≥ 0.85 on the 30-pair golden set (gates B.2).
- **G7.** Every `persist_insight` write includes a `chart_id` from the same session and ≥1 typed citation. Enforced at the tool boundary, not the prompt.

### Non-Goals

- News and Aterio archive in document retrieval (V3).
- Multi-tenant workspace isolation.
- Real-time streaming insights beyond the existing SSE flow.
- Frontend redesign beyond the Tracked Questions sidebar.
- Replacing OpenClaw as the gateway.
- Deletion of v1 code during the soak window (deferred 2 weeks per §8 Phase D).

---

## User Stories

### Analyst stories

- **US-A1 (chart shape matches claim).** As an analyst, I want the chart shape to match the claim — so when the agent says "Crusoe Wyoming has 720 MW with 360 MW under construction and no named offtaker," I see a stacked bar of site total split by `contracted/uncontracted × stage`, not two bars labelled DC-1 and DC-2.
- **US-A2 (real document citations).** As an analyst, I want citations that resolve to actual EDGAR / permit passages — with `source`, `filing_type`, `url`, `retrieved_at`, and a `passage_id` that I can click to read the surrounding ~300-token window — not just `supporting_row_ids` pointing at FactPack rows.
- **US-A3 (tracked questions sidebar).** As an analyst, I want a "Tracked questions" sidebar that lists active journal entries with `status` (`watching`, `confirmed`, `disproved`, `stale`), `materiality`, and the latest evidence note — and I want to see status flip across days when the agent finds new evidence.
- **US-A4 (manual hypothesis injection).** As an analyst, I want to type "look into Crusoe Wyoming" in the focus field and have the next session open a journal entry against that prompt.

### Operator stories

- **US-O1 (rollback to v1).** As an operator, I want to roll back to v1 by setting `version="v1"` on the session payload (or flipping a single config flag for default), with no data migration and no frontend redeploy required, for a 2-week soak window.
- **US-O2 (deprecation visibility).** As an operator, I want a `Deprecated` response header on v1 sessions during the soak so we can monitor residual v1 traffic before deletion.

### Engineer stories

- **US-E1 (chart_id + citations enforced).** As an engineer, I want `persist_insight` to reject any call without a `chart_id` produced by `build_chart` in the same session and ≥1 `citation` from `query_database` or `search_documents`. The enforcement lives in the tool, not the prompt.
- **US-E2 (read-only SQL gate).** As an engineer, I want `query_database` to parse SQL to AST (sqlglot), reject anything that is not `SELECT`, reject reads from `information_schema` and `pg_catalog`, enforce a 10s statement timeout and a 5,000-row cap. Regex-based gating is not acceptable.
- **US-E3 (golden-set replay).** As an engineer, I want a `pytest` harness that replays the 10 known scenarios against v2 and produces a diff report (insights, charts, journal mutations) to compare against v1 output.

---

## Acceptance Criteria — Phase B.1 (BM25 document retrieval)

**Scope:** spec §5.3, §8 Phase B.1.

- **B.1.1.** Alembic migration `017_*` creates `edgar_passages(passage_id PK, document_id, text, tsv tsvector, retrieved_at, url, filing_type, company)` and `permit_passages(passage_id PK, document_id, text, tsv tsvector, retrieved_at, url, permit_type, state, county)` with GIN indexes on `tsv`.
- **B.1.2.** Backfill job chunks all existing EDGAR filings (~8K) and permit PDFs (~4K) into ~300-token passages using `tiktoken` (cl100k_base) and populates `tsv` via `to_tsvector('english', text)`. Backfill is idempotent and resumable.
- **B.1.3.** Ongoing ingestion in `backend/ingestion/` writes new passages on every EDGAR / permit ingestion run. No orphan documents.
- **B.1.4.** `search_documents(query, source, k)` MCP tool ranks via `ts_rank_cd(tsv, websearch_to_tsquery('english', query))`; returns `passages[]` with the schema in §5.3 (text, citation block, score). `source` accepts `"edgar"`, `"permits"`, `"all"`.
- **B.1.5.** A 30-pair labelled golden set (`backend/tests/golden/doc_retrieval.jsonl`) exists with `{claim, expected_passage_id, source}` entries. The retrieval test suite reports `recall@8` and `mrr@8`.
- **B.1.6.** Latency: p95 retrieval time < 500ms on a warm pool.
- **B.1.7.** **Gate decision recorded.** A short `docs/phase_b_recall_report.md` records measured `recall@8`. If `recall@8 ≥ 0.85`, B.2 is skipped; otherwise B.2 is triggered.

## Acceptance Criteria — Phase B.2 (pgvector hybrid, gated)

**Trigger condition:** B.1 `recall@8 < 0.85` on the 30-pair golden set. **If recall ≥ 0.85, this phase is not built.**

- **B.2.1.** Alembic migration adds `embedding vector(3072)` to `edgar_passages` and `permit_passages` with IVFFlat indexes (`lists` tuned to row count). pgvector extension is already installed (migrations 009, 013).
- **B.2.2.** Backfill embeds all passages via OCI Generative AI `text-embedding-3-large` (already provisioned). Backfill is batched, retriable, and rate-limit aware.
- **B.2.3.** Ongoing ingestion embeds new passages.
- **B.2.4.** `search_documents` returns Reciprocal Rank Fusion (RRF) merge of BM25 ranks and cosine ranks.
- **B.2.5.** Latency: p95 < 500ms with hybrid retrieval.
- **B.2.6.** Re-measure: `recall@8 ≥ 0.85` on the 30-pair golden set, recorded in `docs/phase_b_recall_report.md`.
- **B.2.7.** Fallback rule: if hybrid `recall@8 < 0.7`, raise an alert; do not block Phase C, but route the residual gap to a follow-up.

## Acceptance Criteria — Phase C (new tools + v2 prompt)

**Scope:** spec §5, §6, §8 Phase C. Runs in parallel with B; can ship before B.2 completes.

- **C.1 (sql_gate hardened).** `tools/sql_gate.py` parses with sqlglot, rejects anything other than `SELECT` at AST level, rejects access to `information_schema` and `pg_catalog`, scopes to `public.*` plus an explicit view allowlist, enforces 10s statement timeout (`SET LOCAL statement_timeout`) and a 5,000-row cap with `truncated=True` flag. Negative tests cover DDL, DML, CTE-with-write, set returning function abuse, and schema-qualified leaks.
- **C.2 (build_chart tool).** `tools/build_chart.py` accepts `(sql, encoding, title, subtitle?)`, runs SQL through `sql_gate`, validates that returned columns match `encoding.x`, `encoding.y`, optional `series`, optional `facet`. Validates that `chart_type` is compatible with the encoding (e.g. `stacked_bar` requires `series`). Caps at 200 rows (top-200 by `y desc`, `truncated=True`). Persists a `ChartSpec` row in `agent_chart` and returns `{chart_id, chart_spec}`.
- **C.3 (persist_insight v2).** New schema accepts `(insight, chart_id, citations[], open_question_id?)`. Removes `chart_type`, `chart_y_label`, `supporting_row_ids`. Tool-level enforcement:
  - `chart_id` must exist in `agent_chart` and be tagged with the same `session_id`.
  - `citations[]` must contain ≥1 entry whose `passage_id` exists in `edgar_passages` / `permit_passages` OR whose `row_ids` resolve through `query_database` audit log.
  - Rejects on violation with a typed error.
- **C.4 (`_chart_from_supporting_rows` deletion path).** v2 path does not call `_chart_from_supporting_rows`. v1 path retains it until Phase D cleanup.
- **C.5 (synthesis_rules_v2.md).** New file (replace, not patch). Encodes workflow from §6: read `SCHEMA.md` + `FRESHNESS.md`, recall journal via `memory_search`, drill, `build_chart`, `persist_insight`, `update_memory`, `finalize_session`. Hard rules per §6: every `persist_insight` has `chart_id` + ≥1 citation; every insight is paired with at least one `update_memory(category="open_questions", ...)`; plain-text replies are dropped. References `SOUL.md` chart palette.
- **C.6 (orchestrator v2 branch).** `agentic_synthesis.run_agentic_synthesis(version="v2")` skips bootstrap, builds the user message with workspace pointers (`SCHEMA.md`, `FRESHNESS.md`) instead of FactPack digest, and registers the v2 tool palette. v1 branch unchanged.
- **C.7 (budget).** Per-session caps: 60 tool calls, 16 LLM turns, 900s wall. Per-question drill cap of 8 tool calls. Workspace artefacts placed in the system message with Anthropic prompt caching enabled.
- **C.8 (golden-set replay).** Manual eval on 10 scenarios produces non-trivially better insights than v1 on the rubric in G5. Diff report written to `docs/phase_c_eval_report.md`.

## Acceptance Criteria — Phase D (cutover)

**Scope:** spec §8 Phase D.

- **D.1 (frontend sidebar).** `AIInsightsTab.tsx` renders a "Tracked questions" sidebar that polls `GET /api/insights/open-questions` (Phase A route). Each row shows `id`, `status`, `materiality`, `latest_note`, `last_seen_iso`. Status badges color-coded per SOUL palette. Clicking an entry filters the insights feed to that `open_question_id`.
- **D.2 (default v2).** `POST /api/insights/sessions` defaults `version` to `"v2"`. Explicit `version="v1"` still works.
- **D.3 (deprecation header).** v1 sessions return a `Deprecated: true` response header and `Sunset: <2-week ISO date>`.
- **D.4 (operator rollback).** Flipping a single config flag (`AI_INSIGHTS_DEFAULT_VERSION=v1`) reverts default to v1 with no redeploy. Documented in the ops runbook.
- **D.5 (telemetry).** Per-session metrics emitted: `version`, `tool_call_count`, `wall_clock_ms`, `insights_count`, `non_bar_chart_pct`, `journal_advance_count`, `citation_count_per_insight`. Dashboard panel exists.
- **D.6 (soak window).** v2 is the default for ≥14 calendar days with success criteria G1–G5 met on production traffic before any v1 deletion. The v1 code path remains intact (orchestrator bootstrap phase, `hypothesizer.py`, `_chart_from_supporting_rows`, `synthesis_rules.md`, v1 fact-pack tests) for the entire soak.
- **D.7 (post-soak cleanup, separate ticket).** After the soak, a follow-up PR deletes v1 artefacts. Tracked but not part of this PRD's "done" definition.

---

## Out of Scope

- News and Aterio archive in document retrieval — V3.
- Multi-tenant workspace isolation — separate roadmap.
- Deletion of v1 code paths — deferred 2 weeks per spec §8 Phase D; tracked as a separate post-soak ticket.
- End-of-session reflection LLM call — OpenClaw nightly dreaming pass handles consolidation; revisit if entries take too long to surface.
- Replacing OpenClaw or its memory plugin.
- Schema changes to `agent_chart` beyond what `build_chart` requires.
- Frontend redesign beyond the sidebar.

---

## Dependencies

### Phase A artefacts (already shipped)

- `backend/scripts/refresh_schema_doc.py` — writes `.openclaw/workspace/SCHEMA.md`.
- `backend/scripts/refresh_freshness_doc.py` — writes `.openclaw/workspace/FRESHNESS.md`.
- Alembic post-upgrade hook in `backend/alembic/env.py`.
- APScheduler freshness job (daily 02:00 UTC).
- `read_workspace` MCP tool (allowlist: `SCHEMA.md`, `FRESHNESS.md`).
- `GET /api/insights/open-questions` route — parses `MEMORY.md`, returns structured journal entries.

### External / infra

- **OCI Generative AI `text-embedding-3-large`** — already provisioned; used by existing dedup. Required for B.2 only.
- **pgvector** — already installed via migrations 009 and 013. Required for B.2 only.
- **sqlglot** — required for C.1 (parser-based SQL gate). Add to `backend/requirements.txt`.
- **tiktoken** — required for B.1 chunking (~300-token windows). Add to `backend/requirements.txt`.
- **OpenClaw memory plugin** — already configured per `SOUL.md:260-285`. v2 prompt depends on `update_memory` and `memory_search` being reachable from synthesis sessions. Validated in Phase A.
- **Anthropic prompt caching** — used to amortize workspace artefact reads across same-day sessions.

### Internal touchpoints

- `backend/agents/insights/orchestrator.py`, `agentic_synthesis.py`, `tools/registry.py`, `tools/sql_gate.py`.
- `backend/routers/insights.py` (already extended in Phase A).
- `frontend/src/components/tabs/ai-insights/AIInsightsTab.tsx`, `InsightChart.tsx`.

---

## Risks & Mitigations

Per spec §10. Phase-relevant risks called out below.

| Risk | Phase | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| SQL injection / write via `query_database` | C | Med | High | Parser-based gate (sqlglot); reject DML/DDL at AST level; statement timeout; read-only DB role. Negative tests required. |
| Doc retrieval recall is poor | B | Med | High | B.2 gate at recall@8 < 0.85; if hybrid still <0.7, fall back to `query_database`-only flow and raise alert. |
| Agent infinite-drills | C | Med | Med | Tool-call cap (60) + per-question drill cap (8) + prompt guidance to give up. |
| Cost blowup | C, D | Med | Med | Wall budget + tool cap are hard ceilings; insight count reduced to 5–7; prompt caching on workspace artefacts. |
| OpenClaw memory plugin unavailable / misconfigured | C, D | Low | Med | Phase A validation gate; degraded mode falls back to in-session-only journaling. |
| Frontend breaks on new ChartSpec shapes | D | Low | Med | `build_chart` validates encoding compatibility; `InsightChart.tsx` already supports 16 types. |
| Schema drift between SCHEMA.md and DB | C | Low | Med | Alembic post-upgrade hook is the only writer (Phase A); on mismatch, fail closed with `coverage_gap`. |
| Journal grows unbounded in OpenClaw memory | D | Low | Low | Dreaming pass scores recall + diversity; disproved/stale entries naturally decay. |

### Rollback Plan

The orchestrator already supports `version="v1"|"v2"` in `routers/insights.py CreateSessionBody`. Rollback is per-session and per-default:

1. **Per-session rollback.** Caller passes `version="v1"` on `POST /api/insights/sessions`. Routes through the existing v1 code path (FactPack + `synthesis_rules.md` + `_chart_from_supporting_rows`).
2. **Default rollback.** Set `AI_INSIGHTS_DEFAULT_VERSION=v1` in environment. Restart backend. No DB migration, no frontend deploy.
3. **Soak guarantee.** v1 code paths (`hypothesizer.py`, `_chart_from_supporting_rows`, `synthesis_rules.md`, v1 tool registry shape, v1 fact-pack tests) remain untouched for ≥14 calendar days after Phase D ships. Deletion is a separate PR after soak.
4. **Data compatibility.** v2 writes new shapes to `agent_chart` and `insight_citations`. v1 reads do not depend on these new tables. v1 → v2 transition is forward-only at the row level; no v2-only column is required on legacy `insight` rows.
5. **Frontend compatibility.** Sidebar gracefully handles an empty `MEMORY.md` (Phase A guarantee). Sidebar disappearing on rollback is acceptable; no other frontend regression expected.

---

## Open Questions

1. **B.2 trigger ownership.** Who owns the call on whether B.1 recall @ 0.84 means "ship anyway" vs "build B.2"? Recommend: PM + tech lead joint review on the `phase_b_recall_report.md` artefact.
2. **Citation surface in UI.** When an insight has 3+ citations, do we show all in the provenance footer or top-2 with "+N more"? (Frontend detail; can defer to D implementation.)
3. **Sidebar staleness tolerance.** The sidebar reads `MEMORY.md`, which only contains entries promoted by OpenClaw dreaming. In-flight entries from today's session may not appear until the nightly sweep. Acceptable for V2 — the sidebar is "what's durable," not "what just happened." Confirm with design before D.1.
4. **Per-question drill cap.** §10 mitigation says 8 calls/question. Is this enforced in the prompt only, or do we need a tool-side counter keyed on `open_question_id`? Recommend: prompt-only for V2; revisit if abuse is observed.
5. **Citation type for `query_database`.** §5.5 says citations may be `row_ids` from `query_database`. Do we persist the SQL itself for audit, or just the row IDs? Recommend: persist `(sql_hash, row_ids)` so the row reference is reproducible.
6. **Golden set ownership.** Who curates and maintains the 30-pair retrieval golden set and the 10-scenario insight golden set? Recommend: PM owns scenario list; analyst-in-residence owns labelling; engineering owns the test harness.

---

## References

- Spec: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_spec.md` (§1, §3, §5, §6, §7, §8, §10, §13)
- Method: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/workspace/AI_INSIGHTS_PLAYBOOK.md`
- Pre-flight: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/workspace/AI_INSIGHTS_PREFLIGHT_CHECKLIST.md`
- Phase A PRD: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phase_a_prd.md`
- Phase A architecture: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phase_a_architecture.md`
- Phase A ops runbook: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phase_a_ops_runbook.md`
