# AI Insights v2 — Phases B.1, C, D Test Plan

**Status:** Verification complete
**Date:** 2026-05-07
**Owner:** QA / Test Engineering
**Source PRD:** `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phases_bcd_prd.md`
**Predecessor plan:** Phase A test artefacts (already merged, out of scope here)

---

## Scope

This plan documents the verification approach and test inventory for the work that lands AI Insights v2 across Phases B.1, C, and D. It maps every acceptance criterion in the source PRD to a concrete test, calls out the automated suites that run on every commit, lays out the manual test flow for the new Tracked Questions sidebar, and defines the regression watch-list for the 14-day production soak that begins on the cutover date and ends 2026-05-21.

Out of scope:
- Phase B.2 (pgvector hybrid retrieval) — gated on a real-staging recall measurement and intentionally not built. Synthetic recall@8 = 1.000 on the 30-pair golden set; the gate decision will be re-evaluated against production data, not synthetic.
- Deletion of v1 code paths — gated on the Phase D follow-up runbook, scheduled for 2026-05-21 at the earliest.
- Cron timing / scheduler changes — explicitly unchanged. FRESHNESS.md still rebuilds at 02:00 UTC daily; daily ingest still runs in the 06:00–08:00 UTC window.

### Phase scopes

**Phase B.1 — Document retrieval (BM25):** the `edgar_passages` and `permit_passages` tables, the chunker, the `search_documents` MCP tool, the backfill script, the ingestion wiring, and the synthetic recall measurement.

**Phase C — Synthesis hardening + parallel v2:** the AST-only SQL gate via sqlglot, the hardened `query_database` execution path with `SET LOCAL statement_timeout` and the row cap, the `build_chart` tool with Pydantic-validated encodings, the reordered `persist_insight_v2` (chart-id and citation enforced at the tool boundary), the version-keyed tool registry dispatch, the v2 branch of `agentic_synthesis`, and the `synthesis_rules_v2.md` prompt. Phase A's v1 surface is preserved byte-identically and runs in parallel.

**Phase D — Cutover + UI:** flipping the default version on `POST /api/insights/sessions` from `v1` to `v2`, attaching `Deprecated`, `Sunset`, and `Link` response headers on every v1 session response (POST and GET), the Tracked Questions sidebar in `AIInsightsTab.tsx` with 30s polling and visibility-aware pausing, and the soak-and-gate Phase D follow-up plan.

---

## Test Cases

Tests are listed by file and case name. Counts in parentheses are tests collected. All cases run inside the standard `pytest` suite at `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/tests/` and the standard Vitest suite at `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/frontend/`.

### Phase B.1 — Document retrieval

| ID | File | Case | Expected result |
|---|---|---|---|
| B.1-T1 | `backend/tests/test_migration_017.py` | `test_migration_017_tables_exist` (DB-gated, skipped without DATABASE_URL) | Both `edgar_passages` and `permit_passages` exist post-upgrade. |
| B.1-T2 | same | `test_migration_017_gin_indexes_exist` | GIN indexes on `tsv` columns are present on both tables. |
| B.1-T3 | same | `test_migration_017_tsv_trigger_fires_on_insert` | `INSERT INTO edgar_passages` populates `tsv` automatically. |
| B.1-T4 | same | `test_migration_017_polymorphic_check_constraint` | `permit_passages.source_kind` CHECK enforces enum membership. |
| B.1-T5 | same | `test_migration_017_round_trip_idempotent_insert` | Repeated upserts on the same `passage_id` are idempotent. |
| B.1-T6 | `backend/tests/test_chunk_text.py` | `test_empty_input_yields_no_chunks` | Empty / whitespace input returns `[]`. |
| B.1-T7 | same | `test_short_text_produces_one_chunk` | Sub-window text yields exactly one chunk. |
| B.1-T8 | same | `test_long_text_produces_multiple_chunks_with_overlap` | Chunk size ~300 tokens with ~50 overlap. |
| B.1-T9 | same | `test_char_offsets_are_monotonic` | `start_char` strictly increases across chunks. |
| B.1-T10 | same | `test_chunk_text_is_deterministic` | Same input twice produces byte-identical chunks. |
| B.1-T11 | same | `test_invalid_overlap_raises` | `overlap >= window_size` raises `ValueError`. |
| B.1-T12 | same | `test_tokenizer_label_is_recorded` | Returned chunks tag the tokenizer used (`cl100k_base` or `word`). |
| B.1-T13 | same | `test_word_fallback_works_when_tiktoken_missing` | Mocked-absent `tiktoken` falls back to word counting cleanly. |
| B.1-T14 | same | `test_chunk_text_handles_unicode` | Multibyte / surrogate input chunks without panics. |
| B.1-T15 | same | `test_token_count_is_positive` | Every chunk reports `token_count > 0`. |
| B.1-T16 | `backend/tests/test_search_documents_tool.py` | `test_empty_query_is_rejected` | Empty `query` returns a typed `validation_error`. |
| B.1-T17 | same | `test_invalid_source_is_rejected` | `source` outside `{edgar, permits, all}` is rejected. |
| B.1-T18 | same | `test_invalid_k_is_rejected` | `k <= 0` is rejected. |
| B.1-T19 | same | `test_k_above_cap_is_clamped_with_truncated_flag` | `k > MAX_K (50)` clamps to 50 and surfaces `truncated=True`. |
| B.1-T20 | same | `test_edgar_source_shapes_citation_block` | Citation block carries `source`, `filing_type`, `url`, `retrieved_at`, `passage_id`. |
| B.1-T21 | same | `test_permits_source_shapes_citation_block` | Permits citation carries `permit_type`, `state`, `county`. |
| B.1-T22 | same | `test_all_source_merges_and_reranks` | `source="all"` merges by `ts_rank_cd` desc. |
| B.1-T23 | same | `test_search_documents_returns_quickly_under_500ms_synthetic` | Synthetic happy path < 500ms. |
| B.1-T24 | same | `test_db_failure_returns_search_failed` | DB error surfaces as `search_failed`, not 500. |
| B.1-T25 | `backend/tests/test_search_documents_recall.py` | `test_golden_set_loads_and_has_30_pairs` | 30-pair JSONL golden set parses with required fields. |
| B.1-T26 | same | `test_synthetic_recall_at_8_against_seeded_passages` | Synthetic recall@8 = 1.000. |
| B.1-T27 | `backend/tests/test_registry_search_documents.py` | `test_tool_defs_contains_search_documents` | Tool registered in v1+v2 surface. |
| B.1-T28 | same | `test_dispatch_map_contains_search_documents` | Dispatch wiring present. |
| B.1-T29 | same | `test_dispatch_routes_search_documents` | Tool name routes to the function. |

### Phase C — Synthesis hardening + parallel v2

| ID | File | Case | Expected result |
|---|---|---|---|
| C-T1 | `backend/tests/test_insights_sql_gate.py` | `test_accepts_simple_select` | Basic `SELECT` accepted. |
| C-T2 | same | `test_accepts_select_with_join_groupby_orderby` | Standard analytical SQL accepted. |
| C-T3 | same | `test_rejects_ddl_dml[INSERT … / UPDATE … / DELETE … / DROP …]` | Parametrized: every DML/DDL form rejected. |
| C-T4 | same | `test_rejects_pg_table_reference` | `pg_*` tables blocked. |
| C-T5 | same | `test_rejects_cte_referencing_pg_table` | CTE that hides a `pg_*` reference still rejected. |
| C-T6 | same | `test_rejects_multi_statement` | Stacked statements rejected. |
| C-T7 | same | `test_rejects_phase_c_ddl_dml[CREATE / ALTER / GRANT / REVOKE / TRUNCATE]` | Parametrized: each rejected. |
| C-T8 | same | `test_rejects_information_schema_unqualified_table` | `information_schema.*` rejected even without schema prefix. |
| C-T9 | same | `test_rejects_pg_catalog_in_subquery` | `pg_catalog` rejected when buried in a subquery. |
| C-T10 | same | `test_rejects_three_part_db_information_schema` | `db.information_schema.tables` rejected. |
| C-T11 | same | `test_rejects_quoted_mixed_case_information_schema` | `"Information_Schema"."Tables"` rejected. |
| C-T12 | same | `test_rejects_pg_user` | Built-in `pg_user` view rejected. |
| C-T13 | same | `test_exports_phase_c_constants` | `QUERY_TIMEOUT_MS = 10_000` and `HARD_ROW_CAP = 5000` exported. |
| C-T14 | same | `test_attaches_limit_when_missing` | Gate appends `LIMIT 5000` if absent. |
| C-T15 | same | `test_statement_timeout_fires_on_pg_sleep` (DB-gated) | `pg_sleep(15)` aborts at 10s with the typed timeout error. |
| C-T16 | same | `test_row_cap_truncates_at_5000` (DB-gated) | Driver-level row cap kicks in at 5000 with `truncated=True`. |
| C-T17 | `backend/tests/test_build_chart_tool.py` | `test_stacked_bar_without_series_rejected` | Encoding compatibility enforced. |
| C-T18 | same | `test_pie_with_series_rejected` | Pie cannot carry a series. |
| C-T19 | same | `test_line_with_categorical_x_rejected` | Line chart requires temporal x. |
| C-T20 | same | `test_scatter_with_categorical_y_rejected` | Scatter requires numeric y. |
| C-T21 | same | `test_bubble_without_size_rejected` | Bubble requires `size`. |
| C-T22 | same | `test_encoding_field_missing_from_columns` | Referenced encoding column must exist in result set. |
| C-T23 | same | `test_sql_gate_rejects_pg_catalog` | `build_chart` honours the SQL gate. |
| C-T24 | same | `test_sql_gate_rejects_drop` | Same — DDL blocked. |
| C-T25 | same | `test_empty_result_rejected` | Cannot persist a chart over zero rows. |
| C-T26 | same | `test_happy_path_emits_chart_id_and_persists` | Returns `{chart_id, chart_spec}` and writes `agent_chart` with `session_id`. |
| C-T27 | same | `test_downsample_when_over_threshold` | >200 rows → top-200 by `y desc`, `truncated=True`. |
| C-T28 | same | `test_unsupported_chart_type` | Unknown `chart_type` rejected. |
| C-T29 | `backend/tests/test_persist_insight_v2.py` | `test_db_required` | Engine required. |
| C-T30 | same | `test_session_id_required` | Missing session id rejected. |
| C-T31 | same | `test_chart_id_required` | Missing `chart_id` rejected (boundary, not prompt). |
| C-T32 | same | `test_citations_required_empty_list` | Empty citations rejected (boundary, not prompt). |
| C-T33 | same | `test_headline_too_long` | `headline > 140` rejected. |
| C-T34 | same | `test_session_not_found` | Unknown session rejected. |
| C-T35 | same | `test_session_closed` | Cannot write to a finalized session. |
| C-T36 | same | `test_chart_not_found` | Unknown `chart_id` rejected. |
| C-T37 | same | `test_chart_session_mismatch` | Chart from a different session rejected. |
| C-T38 | same | `test_citation_unresolved` | Citation pointing at a non-existent passage rejected. |
| C-T39 | same | `test_happy_path_inserts_v2_insight_and_binds_chart` | Writes `ai_insight` row with `chart_id`, `citations`, `version='v2'`. |
| C-T40 | `backend/tests/test_registry_v2.py` | `test_v1_tool_defs_unchanged` | V1 tool surface byte-identical to legacy. |
| C-T41 | same | `test_v1_tool_defs_alias_matches_legacy_TOOL_DEFS` | Backwards-compatible alias preserved. |
| C-T42 | same | `test_v1_does_not_contain_v2_only_tools` | Sealed surface — no v2 leakage. |
| C-T43 | same | `test_v2_is_strict_superset_of_v1` | V2 = V1 ∪ {build_chart, persist_insight_v2 (search_documents already in v1)}. |
| C-T44 | same | `test_v2_adds_exactly_build_chart_and_persist_insight_v2` | The diff is exactly two tools. |
| C-T45 | same | `test_build_chart_spec_required_fields` | Required argument schema exposed. |
| C-T46 | same | `test_persist_insight_v2_spec_required_fields` | Required argument schema exposed. |
| C-T47 | same | `test_every_v2_tool_has_a_dispatcher` | No dangling tool defs. |
| C-T48 | same | `test_dispatch_includes_v2_only_entries` | New dispatchers wired. |
| C-T49 | same | `test_v2_tool_defs_are_json_serialisable` | Round-trips JSON. |
| C-T50 | `backend/tests/test_agentic_synthesis_v2.py` | `test_v1_loads_synthesis_rules_md_and_includes_factpack` | v1 unchanged. |
| C-T51 | same | `test_v2_loads_synthesis_rules_v2_and_omits_factpack` | v2 loads `synthesis_rules_v2.md` and passes workspace pointers (no FactPack). |
| C-T52 | same | `test_v2_caps_unchanged` | 60 tool calls / 16 LLM turns / 900s — same as v1. |

### Phase D — Cutover + UI

| ID | File | Case | Expected result |
|---|---|---|---|
| D-T1 | `backend/tests/test_phase_d_router_cutover.py` | `test_post_sessions_default_is_v2_no_deprecated_header` | New sessions default to v2 with no deprecation surface. |
| D-T2 | same | `test_post_sessions_explicit_v1_carries_deprecated_and_sunset` | Explicit `version="v1"` → `Deprecated: true`, `Sunset: Wed, 21 May 2026 00:00:00 GMT`, `Link` rel="successor-version". |
| D-T3 | same | `test_post_sessions_explicit_v2_no_deprecated_header` | Explicit v2 has no deprecation surface. |
| D-T4 | same | `test_get_session_v1_row_carries_deprecated_header` | GET on a v1 session re-emits the deprecation headers. |
| D-T5 | same | `test_get_session_v2_row_has_no_deprecated_header` | GET on a v2 session is clean. |
| D-T6 | `frontend/.../TrackedQuestionsSidebar.test.tsx` | `renders the loading skeleton on first paint` | Pre-fetch UI is a skeleton, not a flash. |
| D-T7 | same | `renders parsed list of OpenQuestion items as cards` | Cards render id, status, materiality, latest note, last seen. |
| D-T8 | same | `color-codes status pills with the spec-mandated Tailwind classes` | Status colors match SOUL palette. |
| D-T9 | same | `renders the empty state when the API returns []` | Empty state copy renders. |
| D-T10 | same | `renders an error state with a Retry button on fetch failure` | Failure surface offers retry. |
| D-T11 | same | `sorts by status -> materiality -> recency desc` | Sort order matches spec. |
| D-T12 | same | `polls every 30s and pauses when document is hidden` | 30s polling + `visibilitychange` pause. |

---

## Coverage Matrix — Acceptance Criteria → Test

Each row maps a PRD acceptance criterion to the smallest test that closes it. DB-gated tests run on machines with `DATABASE_URL`; on CI without one they are skipped (currently 2 skipped per backend run).

### Phase B.1

| AC | Description | Closing test(s) |
|---|---|---|
| B.1.1 | Migration creates both passage tables with GIN on `tsv`, polymorphic CHECK on `permit_passages.source_kind` | B.1-T1, B.1-T2, B.1-T4 |
| B.1.2 | Backfill chunker uses tiktoken cl100k_base, ~300 token windows, idempotent | B.1-T6..T15 (chunker), B.1-T5 (idempotency) — backfill script itself is a one-shot operational tool; rerun verified by idempotent insert test |
| B.1.3 | Ongoing ingestion writes new passages on every run, no orphans | Wired via `backend/ingestion/_passages.py` and the edits to `edgar.py` / `bulk_pdf_runner.py`; covered indirectly by B.1-T3 (trigger) and the ingestion test surface in `backend/tests/` (existing edgar/permit ingestion tests still green in the 388-pass run) |
| B.1.4 | `search_documents` returns ts_rank_cd-ranked passages with citation block; source ∈ {edgar, permits, all} | B.1-T16..T24 |
| B.1.5 | 30-pair golden set exists; recall@8 / mrr@8 reported | B.1-T25, B.1-T26 |
| B.1.6 | p95 retrieval < 500ms on warm pool | B.1-T23 (synthetic), validated against real pool in soak telemetry |
| B.1.7 | Gate decision recorded in `docs/ai_insights_v2_phase_b1_report.md` | Manual artefact — present at `docs/ai_insights_v2_phase_b1_report.md`. Synthetic recall@8 = 1.000; B.2 deferred pending real-staging measurement. |

### Phase C

| AC | Description | Closing test(s) |
|---|---|---|
| C.1 | `sql_gate.py` is sqlglot-AST-based; rejects DDL/DML, `information_schema`, `pg_catalog`; 10s timeout; 5000-row cap with `truncated=True` | C-T1..T16 |
| C.2 | `build_chart` validates encoding, runs SQL through gate, persists chart row | C-T17..T28 |
| C.3 | `persist_insight` v2 enforces `chart_id` (same session), ≥1 citation, headline ≤140, at the tool boundary | C-T29..T39 |
| C.4 | `_chart_from_supporting_rows` not called on v2 path; v1 path retains it | Verified by C-T51 (v2 omits FactPack), C-T50 (v1 unchanged), and the absence of `_chart_from_supporting_rows` references in the v2 dispatch |
| C.5 | `synthesis_rules_v2.md` exists; references playbook + preflight | C-T51 (loads `synthesis_rules_v2.md`); file present at `backend/agents/insights/prompts/synthesis_rules_v2.md` |
| C.6 | `agentic_synthesis` v2 branch: skips bootstrap, passes workspace pointers, registers v2 tool palette | C-T51, C-T52 |
| C.7 | Per-session caps unchanged: 60 tool calls, 16 LLM turns, 900s wall | C-T52 |
| C.8 | Golden-set replay diff report | Manual artefact — `docs/ai_insights_v2_phase_c_report.md`; ongoing replay during soak is part of the regression watch-list below |

### Phase D

| AC | Description | Closing test(s) |
|---|---|---|
| D.1 | Tracked Questions sidebar polls `GET /api/insights/open-questions`; cards show id/status/materiality/latest_note/last_seen; status badges color-coded; clicking filters | D-T6..T12 (rendering, sort, polling); click-filter is wired in `AIInsightsTab.tsx` and exercised manually per the manual-test section below |
| D.2 | `POST /api/insights/sessions` defaults to v2; explicit v1 still works | D-T1, D-T2, D-T3 |
| D.3 | v1 sessions return `Deprecated`, `Sunset`, `Link` headers | D-T2, D-T4 |
| D.4 | Operator rollback via single config flag | Documented in `docs/ai_insights_v2_phase_d_followup.md` "Rollback plan"; verified by D-T2 (explicit v1 path remains functional). The flag is the `version` field in `CreateSessionBody.default`; flipping the default is a one-line change. |
| D.5 | Per-session telemetry (version, tool_call_count, wall_clock_ms, …) | Telemetry emission is wired in the orchestrator; dashboard panels are an ops artefact. Watch-list below makes these the soak success signal. |
| D.6 | 14-day soak with G1–G5 met before any v1 deletion | Tracked by `docs/ai_insights_v2_phase_d_followup.md`; soak ends 2026-05-21. NO deletions executed in this run. |
| D.7 | Post-soak cleanup is a separate ticket | Tracked by `docs/ai_insights_v2_phase_d_followup.md`. |

---

## Edge Cases & Negative Tests

The negative coverage that is already in the suite, called out so it's not lost across phases:

- **SQL injection / privilege escalation:** every DML and DDL form (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `CREATE`, `ALTER`, `GRANT`, `REVOKE`, `TRUNCATE`), multi-statement payloads, CTE-hidden `pg_*` references, three-part-name `db.information_schema.tables`, quoted mixed-case `"Information_Schema"` — all rejected by `sql_gate.py`.
- **Resource exhaustion:** `pg_sleep(15)` aborts at 10s; result sets larger than 5,000 rows truncate with the typed flag.
- **Tool boundary contract:** `persist_insight_v2` rejects missing/foreign `chart_id`, empty citations, unresolved citations, closed sessions, and oversized headlines.
- **Encoding sanity:** `build_chart` rejects encoding/chart-type mismatches (`stacked_bar` without `series`, `line` with categorical x, `scatter` with categorical y, `bubble` without size, `pie` with series), missing columns, empty result sets, and unsupported types.
- **Search input validation:** `search_documents` rejects empty query, invalid source, non-positive `k`, clamps `k > 50`, and surfaces DB failure as `search_failed` rather than HTTP 500.
- **Cutover header bleed:** v2 sessions never carry `Deprecated`/`Sunset` (D-T1, D-T3, D-T5).
- **Sidebar failure modes:** loading skeleton, empty state, fetch error with retry — all rendered.

Failure modes specifically NOT covered automatically and accepted as known risks:
- Real-document recall on the live corpus — synthetic-only in CI; real measurement happens during soak (B.1.7 gate re-evaluation).
- Long-running production sessions hitting the 900s wall — soak telemetry catches this.
- OpenClaw memory plugin outage — graceful-degradation path is documented but not unit-tested.

---

## Manual Test Plan — Tracked Questions Sidebar

The sidebar's automated coverage is in `frontend/src/components/tabs/ai-insights/__tests__/TrackedQuestionsSidebar.test.tsx`. The end-to-end behaviour requires a running backend with `MEMORY.md` populated and is documented here.

**Setup:**
1. Backend running locally with a populated `.openclaw/workspace/MEMORY.md` (Phase A artefact).
2. Frontend dev server pointed at it.
3. Open AI Insights tab in a viewport ≥ xl (1280px+) for the rail variant; resize below xl to validate the drawer.

**Test flow:**

| ID | Scenario | Steps | Expected |
|---|---|---|---|
| M-1 | Rail renders on first paint | Open AI Insights tab | Skeleton flashes briefly, then cards render. No empty flash. |
| M-2 | Cards reflect MEMORY.md | Inspect card content | Each card carries `id`, `status` pill, `materiality`, latest note, `last_seen_iso` formatted. |
| M-3 | Sort order | Scroll the list | Order is status → materiality → `last_seen_iso` desc. |
| M-4 | Status colour | Inspect each pill | Watching = amber, confirmed = green, disproved = red, stale = grey, per SOUL palette. |
| M-5 | Click-to-filter | Click a card | Insights feed below filters to that `open_question_id`. Click "Clear filter" returns to full list. |
| M-6 | Polling | Wait 30s with the tab visible | Network tab shows `GET /api/insights/open-questions` every 30s. |
| M-7 | Visibility pause | Switch to a different tab for 60s | No background fetch happens; on return, polling resumes. |
| M-8 | localStorage persistence | Toggle the sidebar closed; reload | Sidebar respects `ai-insights-sidebar-open=false` from localStorage. |
| M-9 | Drawer at <xl | Resize to 1024px | Sidebar collapses to a drawer with a toggle button; clicking opens an overlay. |
| M-10 | Empty state | Empty MEMORY.md (rename file) | Sidebar shows the empty state copy, no error. |
| M-11 | Fetch error | Stop backend mid-session | Error state with Retry button appears; clicking Retry re-fetches when backend returns. |
| M-12 | v1 session deprecation banner | Start a session with explicit `version="v1"` via curl | Response carries `Deprecated: true`, `Sunset: Wed, 21 May 2026 00:00:00 GMT`, and `Link: <…>; rel="successor-version"`. |

---

## Regression Watch-List for the 14-day Soak (2026-05-07 → 2026-05-21)

Monitor these in production. Deletion of v1 code paths is gated on all five being green for 5 consecutive days.

### Latency (PRD G4)
- **v2 p95 wall-clock ≤ 900s**, **p50 ≤ 480s** rolling 7-day window. Source: per-session telemetry `wall_clock_ms` aggregated by `version`.
- Alert if p95 > 900s for any single day.

### Error rate
- v2 session error rate (failed-or-empty insight write) < 5% per day.
- Tool-call error rate (typed tool failures over total tool calls) < 2% per day.
- Alert on any spike of `chart_session_mismatch`, `citation_unresolved`, or `search_failed` errors — those indicate prompt drift or DB drift.

### Insight quality (PRD G1–G3, G7)
- **G1.** ≥80% of v2 insights cite at least one row or passage absent from the legacy v1 FactPack equivalent. Source: `ai_insight.citations` JSONB joined against the v1 FactPack snapshot.
- **G2.** ≥50% of v2 charts use a non-bar chart_type when the claim warrants it. Source: `agent_chart.chart_type` distribution.
- **G3.** ≥30% of v2 sessions advance ≥1 prior journal entry. Source: `update_memory` audit trail joined against `memory_search` audit trail at session start.
- **G7.** 100% of v2 `persist_insight` writes carry a `chart_id` from the same session and ≥1 typed citation. Source: tool-boundary metric — should already be 100% by construction (C-T39 enforces it). Any drop below 100% is a bug.

### Document retrieval (PRD G6 / B.1.7 gate)
- recall@8 on the 30-pair golden set against the real live corpus. Synthetic = 1.000; real measurement is the gate criterion for B.2.
- p95 retrieval latency < 500ms.

### v1 traffic
- v1 session counts trending toward zero. The `Deprecated`/`Sunset` headers should drive integrators off v1.
- Alert if v1 traffic is non-decreasing on day 7+ — indicates a stuck client.
- DB sanity check (PRD Phase D follow-up §"Pre-deletion gate criteria"):
  ```sql
  SELECT version, count(*) FROM agent_session GROUP BY version;
  SELECT version, count(*) FROM ai_insight     GROUP BY version;
  ```

### Cron / ingest invariants (hard constraint)
- FRESHNESS.md mtime should be within the daily window of 02:00 UTC ± 5 min. Any drift = scheduler misconfiguration.
- Daily ingest pipeline (EDGAR + permits) completes between 06:00 and 08:00 UTC. Passage-table row counts should grow daily.
- **No code in this delivery touches scheduler timing**; this monitor exists only to confirm nothing else regressed.

---

## Performance Benchmarks

| Surface | Target | Verification |
|---|---|---|
| `search_documents` (warm pool, k=8, source=all) | p95 < 500ms | Synthetic in B.1-T23; real-corpus measurement during soak |
| `query_database` statement timeout | hard 10s ceiling | C-T15 (pg_sleep regression, DB-gated) |
| `query_database` row cap | hard 5000 ceiling | C-T16 (DB-gated) |
| `build_chart` downsample | top-200 by y desc | C-T27 |
| Synthesis session wall clock | p95 ≤ 900s, p50 ≤ 480s | Telemetry — soak watch-list |
| Sidebar polling cadence | 30s when visible, 0 when hidden | D-T12 |

---

## Security Checklist

- [x] **SQL gate is AST-based, not regex.** sqlglot parses; non-SELECT roots rejected; `information_schema` and `pg_catalog` blocked at any depth (C-T1..T14).
- [x] **Read-only DB role / statement timeout.** `SET LOCAL statement_timeout = 10000` on every query (C-T15, exported constant in C-T13).
- [x] **Row cap.** Driver-level `fetchmany(5000)` plus probe to set `truncated=True` (C-T16).
- [x] **Search input validation.** Empty query, invalid source, non-positive `k`, oversized `k` — all rejected (B.1-T16..T19).
- [x] **Tool-boundary enforcement, not prompt-only.** `chart_id` and citation presence are validated in Python on every `persist_insight_v2` call (C-T29..T38).
- [x] **Session scope on charts.** Charts from foreign sessions cannot be bound to insights (C-T37).
- [x] **Citation resolution.** Citations must resolve to a real passage row or row-id audit log entry (C-T38).
- [x] **No secret material in passages.** Backfill chunks public EDGAR / permit text only; no credentialed sources are ingested in this scope (Phase A non-goal preserved).
- [x] **Deprecation surface for v1 clients.** `Deprecated`, `Sunset`, `Link` headers are set on every v1 session response (D-T2, D-T4) so integrators are warned before the eventual deletion.
- [x] **Forward-compatible rollback.** No destructive schema changes; v1 columns preserved on `ai_insight`; v1 rows continue to read correctly post-cutover.

---

## Suite Status

```
Backend (CLAUDECODE=0 python3 -m pytest backend/tests/ --tb=short -q):
  388 passed, 2 skipped, 1 warning in ~9s

Frontend (cd frontend && npm test -- --run):
  2 files, 10 tests passed
```

The two skipped backend tests are DB-gated regressions (statement timeout, row cap) that require a live `DATABASE_URL`. They run in the staging CI pipeline against a real Postgres.

---

## References

- PRD: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phases_bcd_prd.md`
- Phase B.1 report: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phase_b1_report.md`
- Phase C report: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phase_c_report.md`
- Phase D follow-up: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phase_d_followup.md`
- Final summary: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phases_bcd_final_summary.md`
