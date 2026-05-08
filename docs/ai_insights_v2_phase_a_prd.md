# AI Insights v2 — Phase A PRD

**Status:** Draft · **Date:** 2026-05-07 · **Owner:** PM
**Canonical spec:** [`docs/ai_insights_v2_spec.md`](./ai_insights_v2_spec.md) (Phase A scope: §8, lines 383–390)

---

## 1. Summary

Phase A delivers the **workspace substrate** that AI Insights v2 will read at session start, plus the read path the synthesis agent and frontend need. Concretely, Phase A ships: (a) two app-owned markdown artefacts written into `.openclaw/workspace/` — `SCHEMA.md` (spec §4.1, lines 106–152) and `FRESHNESS.md` (spec §4.2, lines 154–179); (b) a `read_workspace` MCP tool with a strict allowlist (spec §5.1, lines 233–241); (c) the backend route `GET /api/insights/open-questions` that parses the existing OpenClaw-managed `MEMORY.md` (spec §4.4, lines 216–227); and (d) the wiring that keeps these artefacts fresh — an Alembic post-upgrade hook for `SCHEMA.md` and a daily 02:00 UTC cron entry registered in `backend/pipeline/runner.py`'s `_JOB_FUNCTIONS` map for `FRESHNESS.md`. Phase A does **not** touch synthesis behaviour: no new prompt, no orchestrator changes, no `build_chart`, no `search_documents`, no pgvector, no `persist_insight` v2, and no frontend sidebar. Those land in Phases B/C/D.

## 2. User Stories

1. **Schema digest generator.** *As the synthesis agent, I want a current `SCHEMA.md` describing tables, columns, FKs, and top-N samples for high-signal tables, so that I can plan SQL drills without guessing column names.* (spec §4.1)
2. **Freshness digest generator.** *As the synthesis agent, I want a daily `FRESHNESS.md` listing row counts, `max(updated_at)`, Δ7d, Δ24h, and a "hot tables" rollup, so that I know where today's deltas live.* (spec §4.2)
3. **Workspace reader tool.** *As the synthesis agent, I want a `read_workspace(file)` MCP tool that returns the first 16KB of an allowlisted file with a `truncated` flag, so that I can ingest workspace artefacts without arbitrary filesystem access.* (spec §5.1)
4. **Open-questions API.** *As the frontend sidebar, I want `GET /api/insights/open-questions` to return parsed entries from `MEMORY.md`'s `open_questions` section, so that I can render the "Tracked questions" list in Phase D.* (spec §4.4)
5. **Alembic post-upgrade hook.** *As the synthesis agent, I want `SCHEMA.md` to refresh automatically after every migration, so that the digest never lags the live schema.* (spec §4.1, §8 Phase A bullet 1)
6. **Cron-wired freshness job.** *As the synthesis agent, I want `refresh_freshness_doc.py` to run nightly via the existing pipeline runner, so that `FRESHNESS.md` reflects the most recent ingestion sweep.* (spec §4.2, §8 Phase A bullet 2)
7. **OpenClaw memory plugin verification.** *As the synthesis agent, I want a verification check confirming that `update_memory` and `memory_search` are reachable in synthesis sessions, so that Phase C can rely on the journal being writeable.* (spec §8 Phase A bullet 3)

## 3. Acceptance Criteria (per deliverable)

### D1 — `refresh_schema_doc.py` writes `SCHEMA.md`  (spec §4.1, lines 106–152)
- Script lives at `backend/scripts/refresh_schema_doc.py`.
- Introspects SQLAlchemy `Base.metadata`; emits one `### \`<table>\`` block per table with columns, types, nullability, FKs.
- For each high-signal table (`companies`, `sites`, `energy_projects`, `edgar_extractions`, `generator_permits`, `building_permits`, `power_contracts`, `anomalies`, `data_coverage`), appends a `Top 10 by <metric>` block via `SELECT * … ORDER BY <metric> DESC LIMIT 10`.
- Emits a "High-signal join paths" footer (verbatim format from spec lines 146–149).
- Writes to `.openclaw/workspace/SCHEMA.md`. Total size ≤ ~30KB.
- Header line includes generation timestamp and migration revision: `# Schema Digest — generated <iso> (migration <rev>)`.

### D2 — `refresh_freshness_doc.py` writes `FRESHNESS.md`  (spec §4.2, lines 154–179)
- Script lives at `backend/scripts/refresh_freshness_doc.py`.
- Pure SQL — no model introspection, no LLM calls.
- Emits a single table with columns `table | rows | max(updated_at) | Δ 7d | Δ 24h` for every table that has an `updated_at` column.
- Emits a "Hot tables (Δ 7d > 5%)" rollup (filter on `pct_change > 0.05`).
- Writes to `.openclaw/workspace/FRESHNESS.md`. Size ≤ ~2KB.

### D3 — `read_workspace` MCP tool  (spec §5.1, lines 233–241)
- Lives at `backend/agents/insights/tools/read_workspace.py`.
- Signature: `async def read_workspace(file: Literal["SCHEMA.md", "FRESHNESS.md"], ctx: SkillContext) -> dict`.
- Allowlist enforced at the type level **and** at runtime — anything outside the literal raises before disk access.
- Rejects path traversal (`..`, absolute paths, symlinks escaping `.openclaw/workspace/`).
- Returns `{ok: bool, content: str, truncated: bool}`; `content` is capped at 16,384 bytes; `truncated=True` if the file is longer.
- Registered in `backend/agents/insights/tools/registry.py`.

### D4 — `GET /api/insights/open-questions`  (spec §4.4, lines 216–227)
- Route added to `backend/routers/insights.py`.
- Reads `.openclaw/workspace/MEMORY.md`, locates the `open_questions` section header, and parses each fact line on `|` into `{id, status, materiality, latest_note, last_seen_iso}`.
- Multiple entries with the same `id` collapse to one record using the most recent note as `latest_note`.
- Returns `[]` (200) when the section is missing or empty — never 500.
- Response schema matches spec line 222 exactly.

### D5 — Alembic post-upgrade hook  (spec §4.1 line 110; §8 Phase A bullet 1)
- `backend/alembic/env.py` invokes `refresh_schema_doc.py` after a successful `upgrade` against a non-empty target.
- Hook is a no-op on `downgrade` and on `--sql` offline mode.
- Failure of the hook does **not** fail the migration (logged as a warning; schema digest is best-effort).

### D6 — Cron wiring in `_JOB_FUNCTIONS`  (spec §4.2 line 158; §8 Phase A bullet 2)
- A new entry in `_JOB_FUNCTIONS` inside `backend/pipeline/runner.py` maps a job name (e.g. `refresh_freshness_doc`) to the script's entrypoint.
- Scheduled daily at 02:00 UTC, post-ingestion.
- Job emits a structured log line on success/failure compatible with the existing runner conventions.

### D7 — OpenClaw memory plugin verification  (spec §8 Phase A bullet 3)
- A verification step (script or test) confirms `update_memory(category="open_questions", fact=...)` succeeds and that the entry surfaces via `memory_search("", category="open_questions")` in a synthesis session context.
- Documented in the Phase A validation log; no code changes to the OpenClaw plugin itself.

## 4. Definition of Done

- [ ] Files on disk: `backend/scripts/refresh_schema_doc.py`, `backend/scripts/refresh_freshness_doc.py`, `backend/agents/insights/tools/read_workspace.py`, plus the new route in `backend/routers/insights.py`.
- [ ] First successful runs produce `.openclaw/workspace/SCHEMA.md` and `.openclaw/workspace/FRESHNESS.md` matching the formats in spec §4.1 / §4.2.
- [ ] `alembic upgrade head` on a fresh DB triggers a `SCHEMA.md` refresh; the file's header migration revision matches `alembic current`.
- [ ] The freshness job appears in `_JOB_FUNCTIONS` in `backend/pipeline/runner.py` and is reachable via the runner CLI.
- [ ] Unit tests cover: `read_workspace` allowlist + truncation, `MEMORY.md` parser (well-formed, missing section, malformed line), schema-doc generator on a tiny fixture metadata, freshness-doc generator against a seeded test DB.
- [ ] Integration check: `GET /api/insights/open-questions` returns 200 with parsed entries when `MEMORY.md` contains a sample `open_questions` section, and 200 with `[]` when it does not.
- [ ] Phase A validation gate from spec line 390 is met (artefacts exist, are well-formed, schema generator handles new migrations, sample `update_memory` write surfaces in `MEMORY.md` after dreaming sweep).

## 5. Out of Scope

Phase A explicitly does not deliver, and pull requests must not touch:

- **Phase B** — `search_documents` MCP tool, EDGAR/permit passage chunking + ingestion, `edgar_passages` / `permit_passages` tables, BM25/`tsvector` indexes, pgvector embeddings, OCI Generative AI calls (spec §5.3 lines 259–287; §8 Phase B lines 392–407).
- **Phase C** — `build_chart` MCP tool, `persist_insight` v2 schema, `synthesis_rules_v2.md`, `agentic_synthesis.run_agentic_synthesis(version="v2")` branching, `sql_gate.py` parser-based hardening, deletion of `_chart_from_supporting_rows()` (spec §5.4–5.5 lines 289–340; §8 Phase C lines 409–416).
- **Phase D** — Frontend "Tracked questions" sidebar in `AIInsightsTab.tsx`, defaulting `POST /sessions` to `version="v2"`, `Deprecated` header on v1, deletion of `hypothesizer.py` / `synthesis_rules.md` / v1 fact-pack tests (spec §8 Phase D lines 418–422).
- **Do NOT modify** in Phase A: `backend/agents/insights/hypothesizer.py`, the phase logic in `backend/agents/insights/orchestrator.py`, or `backend/agents/insights/prompts/synthesis_rules.md`. Phase A is read-only with respect to synthesis behaviour.
- Out of scope for v2 entirely (spec §12, lines 463–469): real-time streaming insights, multi-tenant workspace isolation, proactive alert scheduling, broader frontend redesign, replacing OpenClaw as the gateway.
