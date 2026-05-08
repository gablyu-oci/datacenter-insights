# AI Insights v2 — Phases B.1 / C / D Final Summary

**Status:** Shipped to default. 14-day soak in progress.
**Cutover date:** 2026-05-07
**Soak ends:** 2026-05-21
**Owner:** Engineering + QA

---

## What shipped, by phase

### Phase B.1 — Document retrieval (BM25)

- **`edgar_passages` and `permit_passages` tables.** Polymorphic `permit_passages.source_kind` with a CHECK constraint, GIN indexes on `tsv`, and a Postgres trigger that maintains `tsv` automatically on insert / update.
- **Chunker.** Tiktoken `cl100k_base` with a word-count fallback, ~300-token windows, ~50-token overlap, deterministic, unicode-safe.
- **`search_documents` MCP tool.** BM25 ranking via `ts_rank_cd(tsv, websearch_to_tsquery('english', query))`. `source` accepts `edgar`, `permits`, or `all`. Citations include source, filing/permit metadata, URL, retrieved-at, passage id. `MAX_K = 50` with truncation flag.
- **Backfill script.** Idempotent, resumable, chunks all existing EDGAR + permit documents.
- **Ingestion wiring.** Every new EDGAR filing and permit PDF writes passages on the same run — no orphans.
- **Synthetic recall.** 30-pair golden set. Synthetic recall@8 = 1.000. Real-corpus measurement is the gate for Phase B.2 and is deferred until staging traffic accumulates.

### Phase C — Synthesis hardening + parallel v2

- **AST-only SQL gate.** `tools/sql_gate.py` parses with sqlglot. Non-SELECT roots, `information_schema`, `pg_catalog`, and DML/DDL rejected at any depth (CTEs, subqueries, multi-part names, quoted identifiers). Constants exported: `QUERY_TIMEOUT_MS = 10_000`, `HARD_ROW_CAP = 5000`.
- **Hardened `query_database`.** `engine.begin()` with `SET LOCAL statement_timeout`, `fetchmany(HARD_ROW_CAP)` plus a probe to set `truncated=True` deterministically.
- **`build_chart` tool.** Pydantic-validated encodings — stacked_bar requires series, line requires temporal x, scatter requires numeric y, bubble requires size, etc. Top-200 downsample by `y desc`. Persists a `ChartSpec` row in `agent_chart` keyed to the originating `session_id`.
- **`persist_insight_v2` tool.** Tool-boundary enforcement (not prompt-only): `chart_id` must exist and be tagged with the same `session_id`; ≥1 typed citation required; headline ≤140 chars. Rejects on violation with typed errors.
- **Migration 018.** Adds nullable `chart_id` (UUID FK), `citations` (JSONB), `open_question_id` (TEXT), and `version` (TEXT default `'v1'`) to `ai_insight`; adds `session_id` to `agent_chart`.
- **Tool registry.** Version-keyed dispatch: `V1_TOOL_DEFS` is byte-identical to legacy; `V2_TOOL_DEFS` adds exactly `build_chart` and `persist_insight_v2` (`search_documents` lives in both).
- **`agentic_synthesis` v2 branch.** Skips the FactPack bootstrap, loads `synthesis_rules_v2.md`, passes workspace pointers (SCHEMA.md / FRESHNESS.md) instead of FactPack digest, registers the v2 tool palette. v1 branch unchanged. Per-session caps unchanged: 60 tool calls, 16 LLM turns, 900s wall clock.
- **Prompt.** `synthesis_rules_v2.md` references the playbook and pre-flight checklist by pointer; does not restate them.

### Phase D — Cutover + UI

- **Default flipped.** `CreateSessionBody.version` default in `routers/insights.py` flipped from `"v1"` to `"v2"` on `POST /api/insights/sessions`.
- **Deprecation surface for v1.** `_v1_deprecation_headers()` helper attaches `Deprecated: true`, `Sunset: Wed, 21 May 2026 00:00:00 GMT`, and `Link: <…>; rel="successor-version"` on every v1 session response (POST and GET). v2 responses are clean.
- **Tracked Questions sidebar.** New components under `frontend/src/components/tabs/ai-insights/tracked-questions/` (`StatusPill`, `TrackedQuestionCard`, `TrackedQuestionsSidebar`, constants, index) plus `hooks/useOpenQuestionsPolling.ts` (30s polling, `visibilitychange` pause). `AIInsightsTab.tsx` integrates an xl rail and a sub-xl drawer; sidebar open/closed persists in `localStorage` under key `ai-insights-sidebar-open`.
- **No deletions.** v1 code paths remain fully reachable for the 2-week soak. `docs/ai_insights_v2_phase_d_followup.md` is the deletion runbook with explicit gate criteria and is scheduled to run on or after 2026-05-21.

---

## Files added / modified

### Backend — added

```
backend/alembic/versions/017_passage_tables.py
backend/alembic/versions/018_*.py                                   (Phase C)
backend/agents/insights/util/chunk_text.py
backend/agents/insights/tools/search_documents.py
backend/agents/insights/tools/build_chart.py
backend/agents/insights/tools/persist_insight_v2.py
backend/agents/insights/prompts/synthesis_rules_v2.md
backend/ingestion/_passages.py
backend/scripts/backfill_document_passages.py
backend/tests/golden/document_retrieval_recall.jsonl
backend/tests/test_migration_017.py
backend/tests/test_chunk_text.py
backend/tests/test_search_documents_tool.py
backend/tests/test_search_documents_recall.py
backend/tests/test_registry_search_documents.py
backend/tests/test_build_chart_tool.py
backend/tests/test_persist_insight_v2.py
backend/tests/test_registry_v2.py
backend/tests/test_agentic_synthesis_v2.py
backend/tests/test_phase_d_router_cutover.py
```

### Backend — modified

```
backend/agents/insights/agentic_synthesis.py        (v2 branch)
backend/agents/insights/tools/registry.py           (V1_/V2_ TOOL_DEFS dispatch)
backend/agents/insights/tools/sql_gate.py           (sqlglot AST)
backend/agents/insights/tools/query_database.py     (timeout + row cap)
backend/ingestion/edgar.py                          (passages emit)
backend/ingestion/bulk_pdf_runner.py                (passages emit)
backend/routers/insights.py                         (default v2 + deprecation headers)
backend/tests/test_insights_sql_gate.py             (AST regression suite extension)
backend/requirements.txt                            (sqlglot, tiktoken)
```

### Frontend — added

```
frontend/src/components/tabs/ai-insights/tracked-questions/StatusPill.tsx
frontend/src/components/tabs/ai-insights/tracked-questions/TrackedQuestionCard.tsx
frontend/src/components/tabs/ai-insights/tracked-questions/TrackedQuestionsSidebar.tsx
frontend/src/components/tabs/ai-insights/tracked-questions/constants.tsx
frontend/src/components/tabs/ai-insights/tracked-questions/index.tsx
frontend/src/components/tabs/ai-insights/hooks/useOpenQuestionsPolling.ts
frontend/src/components/tabs/ai-insights/__tests__/TrackedQuestionsSidebar.test.tsx
```

### Frontend — modified

```
frontend/src/components/tabs/ai-insights/AIInsightsTab.tsx
frontend/src/components/tabs/ai-insights/types.ts
```

### Docs — added

```
docs/ai_insights_v2_phases_bcd_prd.md
docs/ai_insights_v2_phase_b1_report.md
docs/ai_insights_v2_phase_c_report.md
docs/ai_insights_v2_phase_d_followup.md
docs/ai_insights_v2_phases_bcd_test_plan.md
docs/ai_insights_v2_phases_bcd_final_summary.md          (this file)
```

---

## Test counts

```
Backend:    388 passed, 2 skipped, 1 warning  (CLAUDECODE=0 python3 -m pytest backend/tests/ --tb=short -q)
Frontend:    10 passed in 2 files              (cd frontend && npm test -- --run)
```

Net new tests landed across these phases:
- `test_migration_017.py` — 5 (DB-gated)
- `test_chunk_text.py` — 10
- `test_search_documents_tool.py` — 9
- `test_search_documents_recall.py` — 2
- `test_registry_search_documents.py` — 3
- `test_build_chart_tool.py` — 12
- `test_persist_insight_v2.py` — 11
- `test_registry_v2.py` — 10
- `test_agentic_synthesis_v2.py` — 3
- `test_phase_d_router_cutover.py` — 5
- `test_insights_sql_gate.py` extensions — 16 net new AST regression cases
- `TrackedQuestionsSidebar.test.tsx` — 7

The 2 skipped tests are DB-gated regressions in `test_insights_sql_gate.py` (`test_statement_timeout_fires_on_pg_sleep`, `test_row_cap_truncates_at_5000`) that exercise behaviour requiring a live Postgres connection. They are wired and run green in the staging CI pipeline.

---

## Deferred items

### Phase B.2 — pgvector hybrid retrieval (gated, NOT shipped)
- **Trigger:** B.1 recall@8 < 0.85 on the 30-pair golden set against the **real corpus**.
- **Current state:** Synthetic recall@8 = 1.000. Real measurement is deferred until staging traffic accumulates.
- **Owner decision:** PM + tech lead joint review of `docs/ai_insights_v2_phase_b1_report.md` once real recall is measured.
- **If triggered, scope:** pgvector-extension-backed `embedding vector(3072)` columns, IVFFlat indexes, OCI Generative AI `text-embedding-3-large` embeddings, RRF merge of BM25 and cosine ranks. pgvector is already installed via migrations 009 / 013.

### Phase D — v1 deletion (gated, NOT executed)
- **Trigger:** all five gate criteria in `docs/ai_insights_v2_phase_d_followup.md` met on or after 2026-05-21.
- **Gate criteria:** soak elapsed (≥14 days), v2 latency targets met (p95 ≤ 900s, p50 ≤ 480s) over a rolling 7-day window, zero unresolved v2 bugs in the last 5 days, written sign-off from gabrielle.lyu, and DB sanity confirms v1 row counts have stopped growing.
- **Scope when executed:** delete `backend/agents/insights/hypothesizer.py`, `backend/agents/insights/prompts/synthesis_rules.md`, the v1 branch in `agentic_synthesis.py`, the v1 fact-pack tests, and collapse the registry back to a single tool table. Migration 018 is forward-only and is kept; existing v1 rows in `ai_insight` and `agent_session` are preserved for audit.

---

## Hard constraint — cron timing unchanged

**No scheduler timing was touched in this delivery.**

- FRESHNESS.md still rebuilds at **02:00 UTC daily** via the existing APScheduler job in `backend/main.py` (unmodified).
- Daily ingest pipeline still runs in the **06:00–08:00 UTC** window. EDGAR and permit ingestion continue to call `_passages.py` to maintain the new passage tables, but their schedule is unchanged.
- The Alembic post-upgrade hook in `backend/alembic/env.py` still rebuilds SCHEMA.md after every migration; ordering and trigger conditions unchanged.
- No new cron entries, no APScheduler reconfig, no migration ordering change.

This bullet is the explicit answer to the user's hard constraint and should be the first thing checked in any rollback investigation.

---

## Known limitations

1. **Real-corpus retrieval recall is unmeasured.** The 1.000 recall@8 figure is synthetic and relies on seeded passages aligned with the golden set. Live-corpus measurement during the soak is what gates B.2.
2. **Sidebar staleness is intentional.** Tracked Questions surfaces only entries promoted by OpenClaw's nightly dreaming pass into MEMORY.md; in-flight entries from today's session may not appear until the next sweep. This is a design choice, not a bug — confirm with design before the soak ends if perception drifts.
3. **Per-question drill cap is prompt-only.** No tool-side counter keyed on `open_question_id`; if abuse is observed during the soak, add an enforcement layer.
4. **Citation type for `query_database`.** Persisted as `(sql_hash, row_ids)` for reproducibility; consumers needing the raw SQL can re-resolve from the audit log.
5. **OpenClaw memory plugin is a runtime dependency.** A plugin outage degrades v2 to in-session-only journaling. The degraded path is not unit-tested; production telemetry on `update_memory` failure rate is the watch signal.
6. **Frontend sidebar tests are component-level.** End-to-end click-to-filter behaviour with a live `MEMORY.md` is covered by the manual test plan, not by Vitest.

---

## Rollout / Rollback procedure

### Rollout (already completed on 2026-05-07)

1. Merge the Phase B.1 / C / D PR to `main`.
2. Run `alembic upgrade head` — applies migrations 017 and 018.
3. Run `python backend/scripts/backfill_document_passages.py` once on each environment to populate `edgar_passages` and `permit_passages` from existing documents.
4. Deploy backend and frontend.
5. Confirm:
   - `POST /api/insights/sessions` with no `version` field returns a v2 session.
   - `POST /api/insights/sessions` with `version="v1"` returns a v1 session and the response carries `Deprecated: true`, `Sunset: Wed, 21 May 2026 00:00:00 GMT`, `Link: <…>; rel="successor-version"`.
   - The Tracked Questions sidebar renders in AI Insights.
   - Daily ingest at 06:00–08:00 UTC writes new passage rows (verify by row-count diff on day 2).
   - FRESHNESS.md mtime is within 5 minutes of 02:00 UTC daily.
6. Begin the 14-day soak. Watch the regression watch-list in `docs/ai_insights_v2_phases_bcd_test_plan.md`.

### Rollback — per-session (operator level)

The caller passes `version="v1"` on `POST /api/insights/sessions`. Routes through the byte-identical v1 code path (FactPack + `synthesis_rules.md` + `_chart_from_supporting_rows`). No deploy required.

### Rollback — default (operator level)

Single-line revert: change `CreateSessionBody.version` default in `backend/routers/insights.py` from `"v2"` back to `"v1"`. Restart backend. No DB migration, no frontend deploy. v2 paths remain reachable via explicit `version="v2"`. The Tracked Questions sidebar continues to render against MEMORY.md regardless of session version.

### Rollback — full (engineering level, only if a critical issue emerges)

1. Set `CreateSessionBody.version` default back to `"v1"`.
2. Strip the deprecation headers (`_v1_deprecation_headers` becomes a no-op) so v1 callers do not see warnings during the incident.
3. Open a v2-blocker issue and extend the soak by the time-to-fix.
4. Migrations 017 and 018 are forward-only and are NOT reverted — both are additive and v1 reads do not depend on the new shapes.
5. The passage tables and the `agent_chart.session_id` column remain populated; they are inert from v1's perspective.

The absence of any deletion in this delivery is what makes any rollback cheap. No schema changes to revert, no removed code to restore.

---

## References

- PRD: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phases_bcd_prd.md`
- Spec: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_spec.md`
- Phase A architecture: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phase_a_architecture.md`
- Phase A ops runbook: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phase_a_ops_runbook.md`
- Phase B.1 report: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phase_b1_report.md`
- Phase C report: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phase_c_report.md`
- Phase D follow-up: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phase_d_followup.md`
- Test plan: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phases_bcd_test_plan.md`
