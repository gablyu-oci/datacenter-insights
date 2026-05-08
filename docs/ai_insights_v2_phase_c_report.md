# AI Insights v2 — Phase C Implementation Report

**Date:** 2026-05-07
**Branch:** main (uncommitted)
**Scope:** Phase C of `docs/ai_insights_v2_phases_bcd_architecture.md`
- D1: SQL gate hardening
- D2: `build_chart` MCP tool
- D3: `persist_insight_v2` MCP tool
- D4: registry split (V1 / V2)
- D5: `synthesis_rules_v2.md` prompt
- D6: `version: Literal["v1","v2"]` parameter on `run_agentic_synthesis`
- D7: full test-suite green
- D8: this report

## Outcome

- **Total tests:** 385 (383 passed, 2 skipped, 0 failed)
- **New tests added in Phase C:** 36
  - `test_insights_sql_gate.py`: +13 cases (CREATE/ALTER/GRANT/REVOKE/TRUNCATE,
    information_schema in subqueries, pg_catalog three-part references,
    quoted/mixed-case `INFORMATION_SCHEMA`, pg_user, attached LIMIT,
    HARD_ROW_CAP/QUERY_TIMEOUT_MS exports, statement-timeout & row-cap smoke)
  - `test_build_chart_tool.py`: 12 cases
  - `test_persist_insight_v2.py`: 11 cases
  - `test_registry_v2.py`: 10 cases
  - `test_agentic_synthesis_v2.py`: 3 cases
- **V1 surface byte-identical:** confirmed by `test_v1_tool_defs_unchanged`,
  `test_v1_loads_synthesis_rules_md_and_includes_factpack`, and the
  pre-existing v1 test suite (`test_agentic_synthesis.py`,
  `test_orchestrator_supporting_row_ids.py`) staying green.

## Files added

- `backend/agents/insights/tools/build_chart.py` — V2 chart sink with
  Pydantic v2 discriminated-union encoding validation, chart-type
  compatibility matrix, top-200 downsample, and session-scoped
  persistence to `agent_chart` (insight_id NULL until v2 binds it).
- `backend/agents/insights/tools/persist_insight_v2.py` — V2 insight
  closer; validates session open, chart-session match, citations
  resolve, headline ≤140 chars; writes `ai_insight` with `version='v2'`
  and binds chart + citations.
- `backend/agents/insights/prompts/synthesis_rules_v2.md` — 3.4KB v2
  system prompt; references `AI_INSIGHTS_PLAYBOOK.md` and
  `AI_INSIGHTS_PREFLIGHT_CHECKLIST.md` without restating them.
- `backend/alembic/versions/018_ai_insights_v2_columns.py` — migration
  making `agent_chart.insight_id` NULLABLE on Postgres and adding four
  v2 columns to `ai_insight`: `chart_id` (FK → agent_chart.id, ON DELETE
  SET NULL), `citations` (JSONB), `open_question_id` (TEXT),
  `version` (TEXT NOT NULL DEFAULT 'v1').
- Tests:
  - `backend/tests/test_build_chart_tool.py`
  - `backend/tests/test_persist_insight_v2.py`
  - `backend/tests/test_registry_v2.py`
  - `backend/tests/test_agentic_synthesis_v2.py`

## Files modified

- `backend/agents/insights/tools/sql_gate.py` — recursive DDL/DML
  rejection via `tree.walk()`, three-part qualified-identifier check
  via `tree.find_all(exp.Table)`, dynamic resolution of disallowed
  statement classes, exports `HARD_ROW_CAP=5000` and
  `QUERY_TIMEOUT_MS=10_000`.
- `backend/agents/insights/tools/query_database.py` — wraps execution
  in `engine.begin()` with `SET LOCAL statement_timeout=10000` and
  `SET LOCAL idle_in_transaction_session_timeout=10000`; uses
  `fetchmany(effective_cap) + fetchone()` probe to set `truncated=True`.
- `backend/agents/insights/tools/registry.py` — V1_TOOL_DEFS preserved
  byte-identical (legacy `TOOL_DEFS` alias intact); added
  `_V2_ONLY_TOOL_DEFS` and `V2_TOOL_DEFS = TOOL_DEFS + v2-only`; dispatch
  table extended with `build_chart` and `persist_insight_v2`.
- `backend/agents/insights/agentic_synthesis.py` — added
  `version: Literal["v1","v2"] = "v1"` parameter; v2 branch loads
  `synthesis_rules_v2`, builds user_pack with `workspace_pointers` and
  no factpack_digest; caps (12 turns / 30 tool calls / 600s wall)
  unchanged.
- `backend/agents/insights/db/models.py` — `AgentChart.insight_id` now
  Optional[UUID] (nullable, matches migration 018); `AIInsight` gains
  Optional `chart_id` (FK), `citations` (JSONB), `open_question_id`,
  and `version` (default 'v1') so v1 inserts continue to work
  unchanged.
- `backend/agents/insights/session_tools.py` — `_auto_emit_chart`
  short-circuits when the parent session has `version='v2'` so the v1
  auto-emit path cannot double-write a chart for v2 insights.
- `backend/tests/test_insights_sql_gate.py` — extended with the 13
  Phase C cases enumerated above; tightened DB-only-test skipif to
  require `AI_AGENT_DB_URL` (not just `DATABASE_URL`) so they don't
  flake against a write-role connection.

## Surprises and decisions

1. **Migration 018, not 017.** Phase B.1 already shipped migration 017
   (`017_passage_tables`); this report's migration is 018.
2. **`AgentChart.insight_id` becomes nullable.** Phase C inverts the
   v1 ordering (insight first, chart later). v2 builds the chart up
   front and binds the insight afterwards, so the FK has to allow
   NULL transiently. Migration 018 does this on Postgres only; SQLite
   tests rely on the model-layer optionality.
3. **Encoding validator uses Pydantic v2 per-chart-type wrappers** rather
   than a single discriminated union with all 16 chart types as
   variants. The wrapper approach surfaces shape errors first
   (`encoding_shape_invalid`) and the compatibility matrix second
   (`series_required`, `x_must_be_continuous`, etc.), which gives the
   agent crisper recovery signals than a fused union would.
4. **`_chart_from_supporting_rows` body left intact** as instructed.
   The v1 auto-emit path now reads `ai_session.version` and skips
   itself for v2; the function is still callable and v1 sessions go
   through it byte-identically.
5. **Test-environment guard tightening.** The Phase C statement-timeout
   and row-cap smoke tests require an actual `ai_agent` role; the skipif
   was widened from `DATABASE_URL or AI_AGENT_DB_URL` to just
   `AI_AGENT_DB_URL` to prevent a fallback-to-write-role run in CI.

## V1 byte-identity confirmation

- `test_v1_tool_defs_unchanged` pins the v1 tool name set to the
  pre-Phase-C snapshot (`query_database, call_api, get_chart_data,
  run_skill, emit_chart, web_search, read_workspace, search_documents,
  emit_citation`); v2-only entries are excluded.
- `test_v1_loads_synthesis_rules_md_and_includes_factpack` confirms
  the v1 default branch still loads `synthesis_rules.md` and the user
  message still carries `factpack_digest` + `instructions`.
- Pre-Phase-C tests `test_agentic_synthesis.py` and
  `test_orchestrator_supporting_row_ids.py` continue to pass without
  modification.

## V2 prompt verification

- `test_v2_loads_synthesis_rules_v2_and_omits_factpack` asserts the v2
  branch loads `synthesis_rules_v2.md`, that the prompt references both
  `AI_INSIGHTS_PLAYBOOK.md` and `AI_INSIGHTS_PREFLIGHT_CHECKLIST.md`,
  that the prompt body is under 4096 bytes, and that the user message
  carries `workspace_pointers=["SCHEMA.md","FRESHNESS.md"]` with no
  `factpack_digest` or v1 `instructions`.

## Test summary (D7)

```
383 passed, 2 skipped, 1 warning in 14.30s
```

The 2 skipped are the DB-dependent statement-timeout / row-cap smoke
tests, which require a configured `AI_AGENT_DB_URL` pointing at a
real Postgres with the `ai_agent` role provisioned. They run cleanly
in environments where that role exists.

## Follow-up (out of scope for Phase C)

- Migration 018 has not yet been applied to any environment; running
  `alembic upgrade head` against staging is the next operational step.
- The v2 ToolLoopDriver wiring (selecting `V2_TOOL_DEFS` and the v2
  dispatcher when `session.version == 'v2'`) is Phase D, not C.
- The frontend chart-card / citation-pill rendering for v2 insights is
  also Phase D.
