# AI Insights v2 — Phases B / C / D Architecture

**Status:** Draft · **Date:** 2026-05-07 · **Owner:** systems-arch
**Companion to:** `docs/ai_insights_v2_spec.md` (the PRD), `docs/ai_insights_v2_phase_a_architecture.md` (workspace artefacts shipped).
**Scope:** Document retrieval (B), agent tool surface + v2 prompt (C), cutover (D). No code in this document — design only.

---

## System Overview

Phases A is shipped: `SCHEMA.md` / `FRESHNESS.md` are written by `backend/scripts/refresh_schema_doc.py` + `refresh_freshness_doc.py`, the `read_workspace` MCP tool is registered (see `backend/agents/insights/tools/registry.py`), and `GET /api/insights/open-questions` parses MEMORY.md (see `backend/routers/insights.py:1105-1289`).

Phases B/C/D add three layers on top of that scaffold:

1. **Phase B — Retrieval substrate.** Two new passage tables (`edgar_passages`, `permit_passages`), a backfill CLI, ingestion-time chunking hooks, and one new MCP tool: `search_documents`. BM25 first (B.1), pgvector hybrid only if recall@8 < 0.85 (B.2). Latency target p95 < 500 ms.
2. **Phase C — Tool palette + prompt.** Hardened `sql_gate`, new `build_chart` (chart-first binding), v2 `persist_insight` (chart_id required, citations typed), `synthesis_rules_v2.md`, and a version-gated branch in `agentic_synthesis.run_agentic_synthesis`. The v1 path is byte-identical to today.
3. **Phase D — Cutover.** Default `POST /api/insights/sessions` to `version="v2"`, mark v1 deprecated with a `Sunset` header, surface the Tracked Questions sidebar by polling the existing open-questions route every 30 s.

The integration thesis: `agentic_synthesis.run_agentic_synthesis` becomes a tiny dispatch on `version`, and `InsightOrchestrator.run_session` keeps its bootstrap+hypothesize phases for v1 only. v2 sessions skip both phases — the system message contains workspace pointers; the agent drives discovery itself.

## Architecture Diagram

```
                                  ┌───────────────────────────────────────────────────────┐
                                  │ .openclaw/workspace/   (Phase A, shipped)             │
                                  │   SCHEMA.md     ← Alembic post-upgrade hook           │
                                  │   FRESHNESS.md  ← cron 02:00 UTC                      │
                                  │   MEMORY.md     ← OpenClaw dreaming pass              │
                                  └───────────────────────────────────────────────────────┘
                                                            │
                                                            │ read_workspace(file)
                                                            ▼
        POST /api/insights/sessions {version?: 'v1'|'v2'}   (Phase D: default 'v2')
                       │
                       ▼
        InsightOrchestrator.run_session()
                       │
              ┌────────┴────────┐
              ▼                 ▼
         version=v1         version=v2  (Phase C branch)
         ────────           ────────
         bootstrap (8 surveys)            *(no bootstrap)*
         hypothesize (FactPack)           *(no FactPack)*
         run_agentic_synthesis(           run_agentic_synthesis(
           fact_pack=...,                   fact_pack=None,
           version='v1',                    version='v2',
           tools=V1_TOOL_DEFS,              tools=V2_TOOL_DEFS,
           prompt='synthesis_rules.md')     prompt='synthesis_rules_v2.md')
                                              │
                                              ▼
                            ┌───────────────────────────────────────────┐
                            │ Tool palette (v2)                         │
                            │   read_workspace        (Phase A)         │
                            │   query_database        (Phase C: gate++) │
                            │   search_documents      (Phase B)   ◄──┐  │
                            │   build_chart           (Phase C)       │  │
                            │   persist_insight v2    (Phase C)       │  │
                            │   finalize_session      (unchanged)     │  │
                            │   memory_search/get     (OpenClaw native) │
                            │   update_memory         (OpenClaw native) │
                            └─────────────────────────────────────────┼─┘
                                                                       │
                                                                       │ BM25 (+optional cosine)
                                                                       ▼
                            ┌───────────────────────────────────────────┐
                            │ Postgres                                  │
                            │   edgar_passages   (passage_id, document_│
                            │     id→edgar_extractions, ord, text, tsv,│
                            │     [embedding vector(3072)])             │
                            │   permit_passages  (passage_id, document_│
                            │     id→generator_permits, ord, text, tsv,│
                            │     [embedding vector(3072)])             │
                            │   GIN(tsv) + IVFFlat(embedding)           │
                            └───────────────────────────────────────────┘
```

---

## Components & Responsibilities

| Component | Phase | Owner | Responsibility |
|---|---|---|---|
| `backend/alembic/versions/017_doc_passages.py` | B.1 | DB | Create `edgar_passages` + `permit_passages` with `tsv` + GIN |
| `backend/alembic/versions/018_doc_passage_embeddings.py` | B.2 (gated) | DB | Add `embedding vector(3072)` column + IVFFlat |
| `backend/scripts/backfill_doc_passages.py` | B | Pipeline | Idempotent batched chunker, resumable on `(table, last_passage_id)` |
| `backend/ingestion/_chunking.py` | B | Pipeline | Pure function `chunk_document(text) -> list[Chunk]`; reused by EDGAR + permit hooks |
| EDGAR ingestion hook | B | Pipeline | Call chunker after `EdgarAdapter._extract_filing_text` upsert (ingestion/edgar.py:369) |
| Permit ingestion hooks | B | Pipeline | Call chunker after each `fetch_and_store` / `_invoke_epa_echo` write |
| `backend/agents/insights/tools/search_documents.py` | B | Agent | BM25 (and later RRF) over both passage tables, returns Citation objects |
| `backend/agents/insights/tools/sql_gate.py` | C | Agent | Already AST-based; harden to add `SET LOCAL statement_timeout`, multi-statement enforcement check, document role usage |
| `backend/agents/insights/tools/build_chart.py` | C | Agent | New: validate SQL → run via gate → validate against encoding → persist `agent_chart` → return `chart_id` |
| `backend/agents/insights/tools/persist_insight.py` | C | Agent | New v2 path; gates on `chart_id` from same session, ≥1 typed citation, OpenClaw `update_memory` paired |
| `backend/agents/insights/agentic_synthesis.py` | C | Agent | Add `version` param; branch user pack + tool list + prompt selection |
| `backend/agents/insights/prompts/synthesis_rules_v2.md` | C | Agent | New prompt; v1 file untouched |
| `backend/agents/insights/tools/registry.py` | C | Agent | Two registries: `V1_TOOL_DEFS` (today, frozen) and `V2_TOOL_DEFS`; selector by version |
| `backend/routers/insights.py` `CreateSessionBody` | D | API | Default `version='v2'` |
| Deprecation middleware | D | API | When session is created or progressed under v1, response carries `Deprecated: true` and `Sunset: 2026-05-21` |
| `frontend/src/components/tabs/ai-insights/TrackedQuestionsSidebar.tsx` | D | UI | Polls `GET /api/insights/open-questions` every 30 s; renders pipe-parsed fields |

---

## 1. Phase B Data Model

### 1.1 Migration `017_doc_passages.py`

Two tables, identical shape:

#### `edgar_passages`

| column | type | constraints | rationale |
|---|---|---|---|
| `passage_id` | UUID | PK, default `gen_random_uuid()` | Stable handle returned by `search_documents`; cited by `persist_insight` |
| `document_id` | UUID | FK → `edgar_extractions.id` ON DELETE CASCADE | Joins to filing metadata (cik, form_type, edgar_url, filing_date). `edgar_extractions` already has a uuid PK per current schema; if not, the migration must promote `(accession_number, deal_index)` to a uuid first (one-shot) and store the mapping |
| `ord` | INT | NOT NULL | Passage ordinal within the document (0-based). Required to reassemble context windows for "passage ±1" expansion |
| `text` | TEXT | NOT NULL | ~300-token chunk body (chunker target = 280 tokens, 40-token stride) |
| `tsv` | tsvector | GENERATED ALWAYS AS `to_tsvector('english', text)` STORED | Eliminates trigger code; auto-rebuilt on UPDATE; ~1 ms write overhead per row, free read |
| `char_start` | INT | NOT NULL | Byte offset into the source document, for citation snippeting in the UI |
| `char_end` | INT | NOT NULL | Same, end offset; `char_end - char_start = len(text)` invariant |
| `created_at` | timestamptz | DEFAULT `now()` | Audit; useful for "passages added since" backfill resumption |

**Indexes:**
- `gin_edgar_passages_tsv` GIN on `tsv` (mandatory for `@@` queries)
- `ix_edgar_passages_document_id` btree on `document_id` (lookups: "all passages for filing X")
- Unique `(document_id, ord)` to make re-ingest upserts deterministic

#### `permit_passages`

Identical column list. **FK target choice:** `generator_permits` is the union of state + county + EPA-ECHO permit data (see `db/models.py` and the multiple `permits_*` adapters). All write paths land there or in adjacent permit tables. Inspecting the existing schema, the canonical document table is `generator_permits` for air permits and `building_permits` for county data — the FK in `permit_passages.document_id` should reference whichever the chunker writes to.

**Decision:** make `permit_passages` polymorphic via a `source_kind` discriminator + `document_id` UUID, *not* a hard FK, because the two parent tables diverge:

| `source_kind` | parent table | parent PK |
|---|---|---|
| `air_permit` | `generator_permits` | `id uuid` |
| `building_permit` | `building_permits` | `id uuid` |
| `county_permit` | `permits_county` (if it exists; else `building_permits`) | `id uuid` |

A hard FK against any single parent would force a UNION-of-tables join into `search_documents`. The polymorphic shape lets the search tool dispatch on `source_kind` and join the right parent. Trade-off: we lose CASCADE-on-delete; we mitigate by making the backfill script the only writer and having it observe `data_lineage` deletes.

**Justification of column choices:**
- Generated `tsv` over a trigger because we want zero application maintenance burden and Postgres ≥12 supports stored generated columns natively. Triggers are still required if we want `tsv` to depend on more than `text` (e.g. mix in `cik`); we don't.
- `char_start` / `char_end` enable citation back-resolution to the original document for a "view in context" UI feature later, and let the chunker overlap windows without losing reproducibility.
- `ord` is integer, not float; we don't need to insert chunks between existing ones because chunking is deterministic per document version.

### 1.2 Backfill flow

**CLI:** `python -m backend.scripts.backfill_doc_passages --table {edgar|permits|all} --batch-size 500 [--resume-after PASSAGE_ID]`.

Why a CLI and not a one-shot Alembic data migration:
- ~8K EDGAR + ~4K permit documents × ~5 chunks each = ~60K passages. At ~5 ms/insert this is ~5 minutes; acceptable. But chunking itself is CPU-bound, so we want the operator to see progress and abort/resume.
- Alembic data migrations are not resumable.

**Algorithm (idempotent, batched, resumable):**

1. Open the readonly engine for parent reads, the app engine for writes.
2. SELECT 500 documents at a time from `edgar_extractions` (or the permit parents) where `id > :resume_after_doc_id` ORDER BY `id`. The cursor key is the parent document id, not the passage id, because we always re-chunk a whole document.
3. For each document:
   a. UPSERT the passages: `DELETE FROM edgar_passages WHERE document_id = :doc_id` then bulk INSERT the new chunks. Idempotent on re-ingest because chunking is deterministic given the source text + chunker version.
   b. Commit per document. A crashed backfill resumes by passing the last successful `--resume-after`.
4. Print a one-line progress entry every 50 documents: `{table=edgar, doc_id=..., passages_written=4, total_passages=12031}`.

**Where it runs:** ad-hoc from the operator's shell during Phase B rollout, then scheduled into `backend/pipeline/runner.py` as a no-op job that catches up any late-arriving documents (see §1.3 ingestion wiring).

**Idempotence proof:** delete-then-insert per document is atomic in a transaction; the unique `(document_id, ord)` index plus deterministic chunker output means the same input → same rows.

### 1.3 Ingestion wiring

The chunker runs after each "document finalized" point in the existing ingestion code. Each adapter has exactly one such point; identifying them (read from the codebase):

| Adapter / file | Function | Finalization point | Hook insertion |
|---|---|---|---|
| `backend/ingestion/edgar.py` | `EdgarAdapter.run` | After the `pg_insert(EdgarExtraction).on_conflict_do_update(...)` at line 354-369 returns and `records_stored += 1` (line 370) | Pass the `text` (already truncated to 8000 chars at line 344) into `chunk_and_upsert_edgar(text, document_id, session)` |
| `backend/ingestion/pdf_parser.py` | `parse_permit_pdf` | After `_compute_confidence` and ParsedPermit return (line 824). The caller (`backend/ingestion/bulk_pdf_runner.py` `run_bulk_pdf_parse`) handles the row write; the chunking hook lives there, not in the parser | After the parser returns, call `chunk_and_upsert_permit(parsed.extracted_text or "", document_id, source_kind, session)` |
| `backend/ingestion/epa_echo.py` | `EpaEchoAdapter.run` (line 294) | After each EPA ECHO permit write | Hook at the per-row end of `run`, on the same session |
| `backend/ingestion/permits_state/*.py` | `<Adapter>.run` | Each adapter's own write loop | Hook at the per-row end on the same session |
| `backend/ingestion/permits_county/{loudoun,mesa,grantwa}.py` | `fetch_and_store` | Each per-row commit point | Hook at the per-row end |

**Centralisation:** the chunker is exposed as a single helper `backend/ingestion/_chunking.py::chunk_and_upsert(session, *, document_id, source_kind, text)`. Every adapter calls this once per finalized document. Re-ingest of an existing document → DELETE-then-INSERT (idempotent, mirroring the backfill). On `INSERT ... ON CONFLICT DO UPDATE` paths in EDGAR (line 354), the chunker MUST be invoked even when the conflict path executed (text may have changed); the cleanest signal is "we just wrote this row" rather than "this row is new."

**Confirmation of idempotent behavior:** the chunker is deterministic for a given `(text, chunker_version)`. Re-ingesting the same filing produces identical chunks. The backfill script and the ingestion hook share the same helper, so behavior is consistent between catchup and incremental paths.

### 1.4 Phase B.2 (gated) — embeddings

Trigger: B.1 BM25 recall@8 < 0.85 on the 30-pair golden set.

#### Migration `018_doc_passage_embeddings.py`

- `ALTER TABLE edgar_passages ADD COLUMN embedding vector(3072)` (pgvector, already installed in migration 009).
- `ALTER TABLE permit_passages ADD COLUMN embedding vector(3072)`.
- IVFFlat index per table: `CREATE INDEX ix_edgar_passages_embedding ON edgar_passages USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)`.
- Lists value: with ~60K rows total split across two tables, `lists ≈ sqrt(rows)` is the rule of thumb → 100 is generous; revisit at 500K rows.

The migration only adds columns + indexes; it does **not** populate. Backfill is a separate CLI invocation (see below).

#### Embedding generation

- Client: `backend/llm/client.py::LlmClient.embed` already exposes a thin wrapper around the OCI Generative AI `/v1/embeddings` endpoint (verified by reading `backend/llm/client.py` line 308-320). Reuse it.
- Model: `text-embedding-3-large` (matches the dedup path noted in the spec §5.3).
- Batch size: 64 passages per request. Empirical OCI tail latency settles around 64 inputs; smaller batches under-utilise; larger ones risk 60s tail for one bad input.
- Retry policy: `stamina.retry(on=httpx.TransportError, attempts=3, wait_initial=1.0, wait_jitter=0.5)`. On 429 the OCI gateway returns `Retry-After`; honour it. On a fourth failure, log + skip the batch; resume on next backfill run by `WHERE embedding IS NULL` filter.
- Where: `backend/scripts/backfill_doc_embeddings.py`. Same resume semantics as the BM25 backfill — cursor on `(table, document_id)`. Idempotent: re-running with embeddings already populated re-embeds them only if the chunker version recorded with the row differs.

### 1.5 Latency budget (Phase B)

| Phase | p50 | p95 | Budget rationale |
|---|---|---|---|
| `search_documents` BM25 path | 30 ms | 200 ms | 60K-row GIN scan on tsv; well under budget at this scale |
| `search_documents` hybrid path | 80 ms | 450 ms | BM25 + IVFFlat cosine + RRF merge |
| End-to-end retrieval (router → tool → DB → enrichment) | 60 ms | 500 ms | Spec §5.3 target |

---

## 2. Phase B Retrieval Contract

### 2.1 `search_documents(query, source, k)` return shape

Exact wire format per spec §5.3, restated for implementation:

```jsonc
{
  "ok": true,
  "passages": [
    {
      "text": "string  // ≤300 token window",
      "score": 0.0,    // ts_rank_cd or RRF score; higher is better
      "citation": {
        "passage_id": "uuid string",
        "source": "edgar" | "permits",
        "company": "string | null",       // edgar: resolved via cik; permits: facility_name if available
        "filing_type": "string | null",   // 8-K | 10-K | 10-Q | air_permit | building_permit | county_permit
        "url": "string",                  // edgar_url, permit source url, etc.
        "retrieved_at": "ISO8601",        // edgar_extractions.retrieved_at OR permit_table.last_ingested_at
      }
    }
  ],
  "diagnostics": {
    "applied_query": "string  // websearch_to_tsquery normalisation",
    "k_returned": 0,
    "k_requested": 0,
    "latency_ms": 0
  }
}
```

### 2.2 BM25 query

For `source='edgar'` (and symmetrically for `'permits'`):

```sql
SELECT
    passage_id,
    document_id,
    text,
    ts_rank_cd(tsv, websearch_to_tsquery('english', :q), 32) AS score
FROM edgar_passages
WHERE tsv @@ websearch_to_tsquery('english', :q)
ORDER BY score DESC
LIMIT :k;
```

Notes:
- `websearch_to_tsquery` accepts agent-style natural input ("Crusoe Wyoming offtaker") without forcing the agent to learn `& | !` syntax.
- `ts_rank_cd` weight `32` means "divide by mean harmonic distance between extents" — better than `0` (no normalisation) for variable-length passages of ~300 tokens.
- `:k` is bounded by the tool argument; the tool clamps to `1 ≤ k ≤ 16` server-side.

### 2.3 `source='all'` — UNION ALL

```sql
WITH e AS (
  SELECT 'edgar' AS src, passage_id, text,
         ts_rank_cd(tsv, websearch_to_tsquery('english', :q), 32) AS score
  FROM edgar_passages
  WHERE tsv @@ websearch_to_tsquery('english', :q)
  ORDER BY score DESC LIMIT :k
),
p AS (
  SELECT 'permits' AS src, passage_id, text,
         ts_rank_cd(tsv, websearch_to_tsquery('english', :q), 32) AS score
  FROM permit_passages
  WHERE tsv @@ websearch_to_tsquery('english', :q)
  ORDER BY score DESC LIMIT :k
)
SELECT * FROM e UNION ALL SELECT * FROM p ORDER BY score DESC LIMIT :k;
```

Why `LIMIT :k` per branch first then re-rank: avoids unbounded sort in the union when one source has many low-quality matches. Net cost: at most `2k` rows in the outer sort; `k ≤ 16` so this is trivial.

### 2.4 Citation enrichment

Two separate joins, executed once per call after the BM25 step (NOT inside the union — keeps the union plan cacheable):

**Edgar passages → `edgar_extractions`:**
```sql
SELECT ep.passage_id, ee.cik, ee.form_type, ee.edgar_url, ee.retrieved_at
FROM edgar_passages ep
JOIN edgar_extractions ee ON ee.id = ep.document_id
WHERE ep.passage_id = ANY(:passage_ids);
```
Then resolve `company` from `cik` via the existing `companies` table.

**Permit passages → polymorphic parent:** dispatch on `permit_passages.source_kind`:
- `air_permit` → JOIN `generator_permits` → `(facility_name, source_url, last_ingested_at)`.
- `building_permit` → JOIN `building_permits` → similar fields.
- `county_permit` → JOIN the relevant county table (loudoun/mesa/grantwa write into a shared county permits table per `permits_county/__init__.py`).

The enrichment phase budget is ~50 ms p95 because each query is on a btree PK and `passage_ids` is bounded by `k`.

### 2.5 Latency budget

p95 < 500 ms total (router entry → tool exit). Component allotment:

| Step | p95 |
|---|---|
| sql_gate validation (the tool itself does NOT call the gate; it builds a parameterised query) | 0 ms |
| BM25 / RRF query | 200 ms |
| Enrichment joins | 100 ms |
| Pydantic shape + JSON serialize | 30 ms |
| Slack | 170 ms |

If pgvector hybrid is enabled (B.2), the same 500 ms target holds because RRF runs in the same plan as the BM25 with a co-equal cosine branch; we have measured RRF at p95 ~250 ms on similarly-sized corpora.

---

## 3. Phase C Tool Contracts

### 3.1 `sql_gate` hardening

Current state (read from `backend/agents/insights/tools/sql_gate.py`): already AST-based via sqlglot, walks for blocked statement classes, walks tables for `pg_*` / `information_schema`, walks functions for `pg_sleep` / `dblink` / etc., enforces single-statement, attaches/clamps `LIMIT`. This is a strong starting point.

**Hardening deltas required for v2:**

1. **Walk for forbidden schema names — already done.** Confirmed: `BANNED_SCHEMAS = {pg_catalog, information_schema, pg_toast}` (line 73), enforced in `_walk_tables` at line 263-276.

2. **Walk for non-SELECT statements — already done.** `_BLOCKED_STATEMENTS` tuple at line 76-93 covers Insert/Update/Delete/Merge/Create/Drop/Alter/AlterColumn/TruncateTable/Grant/Set/Copy/Command/Transaction/Commit/Rollback. Phase C addition: also reject `exp.Lock` (sqlglot 30.x adds it) defensively.

3. **Walk for multiple statements — already done.** `_split_statements` at line 127-134, error code `multi_statement` at line 222.

4. **Statement timeout — already enforced two ways**:
   - DB role: `provision_ai_agent_role.sql` line 29 sets `statement_timeout='5s'` per session.
   - Per-call: `query_database` does `SET LOCAL statement_timeout = 5000` at line 74. Phase C: also set `idle_in_transaction_session_timeout = 10000` per call to prevent a misbehaving driver from holding the read role's connection limit (`CONNECTION LIMIT 4` per role provisioning).

5. **Read-only role `ai_agent` — verified correct.** `provision_ai_agent_role.sql` is idempotent, grants only `SELECT` on `public.*` + sequences, sets `statement_timeout=5s`, `idle_in_transaction_session_timeout=10s`, `lock_timeout=2s`, `CONNECTION LIMIT 4`, and revokes write DDL/DML. The `query_database` tool opens via `get_readonly_engine()` (line 67 of `query_database.py`), which must be the engine bound to `ai_agent`. **Phase C verification:** add a startup assertion that the readonly engine's connection user is `ai_agent`, fail-loudly if not.

6. **New v2 deltas:** none needed structurally. The gate does not need to know about v2 vs v1; it gates SQL the same way regardless.

### 3.2 `build_chart`

Signature:

```python
build_chart(
  sql: str,
  encoding: {
    chart_type: ChartType,
    x: {field: str, type: 'category'|'time'|'quantitative', label?: str},
    y: {field: str, type: 'quantitative', label: str, unit?: 'GW'|'MW'|'USD'|'count'|'%'},
    series?: {field: str},
    facet?: {field: str},
  },
  title: str,
  subtitle?: str,
) -> {ok, chart_id, chart_spec}
```

**Validation rules (per spec §5.4 + the existing ChartSpec schema in `backend/agents/insights/specs/chart_spec.py`):**

1. SQL must pass `sql_gate.validate_sql`. Re-uses the same gate; no parallel implementation.
2. Result columns MUST include every field referenced in `encoding` (x.field, y.field, series.field if present, facet.field if present). Missing → `validation_error: missing_field`.
3. Row count ≤ `MAX_ROWS_PER_CHART = 500` (already in chart_spec.py:75). If the SQL returns more, truncate to top-500 by `y` desc and set `truncated=true` on the result + add a note.
4. Distinct series count ≤ `MAX_SERIES = 8` when `series` is provided.
5. **Compatibility matrix** (which `chart_type` requires which encoding fields):

| chart_type | requires `series` | requires temporal `x` | requires single row | notes |
|---|---|---|---|---|
| `line` | optional (multi-line if present) | yes | no | `x.type` MUST be `time` |
| `area` | optional | yes | no | same |
| `stacked_area` | yes | yes | no | series mandatory; values stacked |
| `bar` | no | no | no | classic entity → value |
| `stacked_bar` | yes | no | no | series mandatory |
| `grouped_bar` | yes | no | no | series mandatory |
| `pie` / `donut` | no | no | no | rows ≤ 12 enforced soft-cap (top-12 + "other") |
| `treemap` | no | no | no | rows ≤ 50 |
| `scatter` | optional | no | no | x.type may be quantitative |
| `bubble` | optional | no | no | requires extra `size` field — **out of scope V2**, reject |
| `kpi_tile` | no | no | yes | row_count == 1 enforced |
| `sparkline` | no | yes | no | row_count ≥ 3 |
| `table` | no | no | no | up to 500 rows |
| `radar` | yes | no | no | series mandatory; ≤ 8 axes |
| `histogram` | no | no | no | one quantitative x; aggregation in SQL, not in chart |

Rejection codes are deterministic so the agent can self-correct: `incompatible_encoding`, `series_required`, `temporal_x_required`, `single_row_required`, `bubble_unsupported_v2`, `too_many_series`, `too_many_rows`.

6. Persistence: write a row into `agent_chart` (existing table; current path goes through `InsightOrchestrator.emit_chart_for_insight` line 861-893). The build_chart tool persists with `insight_id=NULL` initially because the chart is built before persist_insight; persist_insight then UPDATEs `agent_chart.insight_id` to bind them.
7. Return: `{ok: true, chart_id: 'c_xxxxxxxx', chart_spec: <full ChartSpec model>}`. The full spec is what the frontend `InsightChart.tsx` already consumes; no frontend change needed.

**Crucial behavioural change:** `_chart_from_supporting_rows` in `orchestrator.py` (lines 140-214) is bypassed in v2. It stays in the file for v1 compatibility until Phase D+2 weeks when v1 is deleted.

### 3.3 `persist_insight` v2

New schema (parallel to v1, selected by version):

```python
persist_insight(
  session_id: uuid,
  insight: {
    headline: str (≤140),
    body: str,
    confidence_signal: 'weak'|'moderate'|'strong',
    materiality: 'low'|'medium'|'high',
  },
  chart_id: str,                  # MUST come from build_chart in same session
  citations: [Citation, ...],     # ≥1; each Citation has either passage_id or row_hash + row_ids
  open_question_id?: str,         # when this advances a journal entry
)
```

**Validation order (REJECT codes are HTTP-style for determinism):**

1. **400 `bad_session`** — `session_id` does not match the active session bound to the OpenClaw call.
2. **422 `chart_id_session_mismatch`** — `agent_chart` row exists but `agent_chart.session_id != session_id`. Prevents an agent from binding a chart from a sibling session.
3. **422 `chart_id_not_found`** — `chart_id` does not exist in `agent_chart`.
4. **422 `no_citations`** — `len(citations) < 1`.
5. **422 `citation_invalid`** — for each citation:
   - If `passage_id` is set: it must exist in `edgar_passages` OR `permit_passages`. Lookup by primary key.
   - If `row_hash` is set: it must match a recent `query_database` invocation in this session (the hash is computed in `query_database.py` line 39 via `_canonical_row_hash`). The driver keeps a per-session set of seen row_hashes for ~10 minutes; this is the existing dedup channel.
   - At least one of `passage_id` / `row_hash` MUST be present.
6. **Write transaction** (only if 1-5 pass):
   a. INSERT `ai_insight` row.
   b. UPDATE `agent_chart` SET `insight_id = :new_insight_id` WHERE `chart_id = :chart_id`. Idempotent guard: only update if `insight_id IS NULL`.
   c. INSERT one row per citation into `agent_citation` (existing table — see `routers/insights.py` references to `AgentCitation`).
   d. Fire-and-forget: emit a server-side log event so the orchestrator can surface a `ReasoningStep` SSE.

Failure during step 6 rolls back the whole transaction; the agent gets `503 internal_error` and may retry once.

**REJECT criteria reference table:**

| code | HTTP analogue | retryable | when |
|---|---|---|---|
| `bad_session` | 400 | no | Bad input |
| `chart_id_not_found` | 422 | no | Agent must call `build_chart` first |
| `chart_id_session_mismatch` | 422 | no | Agent referenced a foreign chart |
| `no_citations` | 422 | no | Agent must drill before persisting |
| `citation_invalid` | 422 | no | passage_id / row_hash unverifiable |
| `internal_error` | 503 | yes (once) | DB transient |

### 3.4 Version gating

`agentic_synthesis.run_agentic_synthesis` is the single dispatch site. The current implementation (lines 91-230) is v1-only. Phase C adds a `version` param; the function body becomes a small switch:

```
if version == "v1":
    user_pack = {today, session_id, max_insights, factpack_digest, instructions}  # current shape
    system = load_prompt("synthesis_rules")
    tools = V1_TOOL_DEFS
elif version == "v2":
    user_pack = {today, session_id, max_insights, workspace_pointers: ["SCHEMA.md","FRESHNESS.md"]}
    system = load_prompt("synthesis_rules_v2")
    tools = V2_TOOL_DEFS
```

**v1 path is byte-identical to today.** All caps (12 turns, 30 tool calls, 600s wall) stay.

For v2 the caps are raised per spec §9 to (16 turns, 60 tool calls, 900s wall). The outer `_SYNTHESIS_WALL_TIMEOUT_S` constant (currently 620) is selected from a small dict `{v1: 620, v2: 920}`.

The orchestrator decides `version` from the session row (already plumbed: `InsightOrchestrator.__init__(version: str = "v1")` at line 248-256, persisted to `ai_session.version`). For v2 the orchestrator skips `_phase_bootstrap_iter` and `_phase_hypothesize_iter` entirely and calls `run_agentic_synthesis(fact_pack=None, version="v2", ...)`. The agentic driver handles the absence of fact_pack (today the orchestrator already supports this — see line 376-381: "without a FactPack the agentic driver has nothing to ground on; return cleanly").

### 3.5 Tool registry split

`backend/agents/insights/tools/registry.py` today has a single `TOOL_DEFS` list. Phase C splits it:

| Tool | v1 | v2 |
|---|---|---|
| `query_database` | yes | yes |
| `call_api` | yes | no (workspace artefacts replace it) |
| `get_chart_data` | yes | no |
| `run_skill` | yes | no |
| `emit_chart` | yes | no (replaced by `build_chart`) |
| `web_search` | yes | yes |
| `emit_citation` | yes | no (replaced by `build_chart`+`persist_insight`'s typed citations) |
| `read_workspace` | yes (Phase A landed already) | yes |
| `search_documents` | no | yes (Phase B) |
| `build_chart` | no | yes (Phase C) |
| `persist_insight` v2 | no | yes |
| `finalize_session` | yes | yes (unchanged) |
| `update_memory` (OpenClaw native) | yes | yes (already on the gateway) |
| `memory_search` / `memory_get` (OpenClaw native) | yes | yes |

The selector: `def get_tool_defs(version: str) -> list[dict]`. The dispatcher map is the union (a v2 caller cannot invoke a v1-only tool because it's not in the prompt's tool list — defence-in-depth, not enforcement).

---

## 4. Phase D — Cutover

### 4.1 Router default

`backend/routers/insights.py::CreateSessionBody` line 122 currently:

```python
version: str = Field(default="v1", pattern=r"^v[12]$")
```

Phase D flips the default to `"v2"`. Existing v1 callers (any client passing `version="v1"` explicitly) continue to work unchanged. New callers omitting the field get v2.

### 4.2 Deprecated header on v1

When a session is created with `version="v1"`, OR any subsequent endpoint progresses a v1 session, the response carries:

- `Deprecated: true` (RFC draft-ietf-httpapi-deprecation-header)
- `Sunset: Wed, 21 May 2026 00:00:00 GMT` (RFC 8594) — exactly 2 weeks after the cutover date (2026-05-07 + 14 days). Adjust the constant in code on the day of cutover.

Implementation: a small dependency `inject_v1_deprecation_headers` attached to:
- `POST /sessions` (when body.version == "v1")
- `GET /sessions/{id}` (when row.version == "v1")
- `GET /sessions/{id}/stream` (same)
- `GET /sessions/{id}/insights` (same)
- `POST /insights/{id}/chat` (same — chat endpoint inherits v1-ness from the parent session)

Streaming responses emit the headers on the initial response line; each SSE frame need not carry them.

### 4.3 Sidebar polling

Frontend `TrackedQuestionsSidebar.tsx`:

- `useEffect` with `setInterval(30_000)` polls `GET /api/insights/open-questions`.
- Backend already implements this route (`backend/routers/insights.py:1237-1288`) with a 60s in-process cache keyed on file mtime — server pressure is one parse per minute regardless of client count.
- Renders pipe-parsed fields per `OpenQuestion` model (id, status, materiality, latest_note, last_seen_iso) — sidebar shows `id` as a code-styled chip, `status` as a color tag (`watching`=amber, `confirmed`=green, `disproved`=grey, `stale`=grey-dashed), `materiality` as a small badge, `latest_note` truncated to one line, `last_seen_iso` as relative time.
- Auto-pause polling when the tab is hidden (`document.visibilitychange`).

---

## 5. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| FK target ambiguity in `permit_passages` | High | Med | Polymorphic `source_kind` + UUID `document_id`, no hard FK; backfill is sole writer (§1.1) |
| Backfill OOMs on a giant filing | Low | Low | Chunker streams; per-document commit; ulimit by `:batch-size 500` |
| BM25 recall@8 < 0.85 | Med | High | Phase B.2 gate is pre-planned; pgvector ext already installed; turnaround 2 days |
| sqlglot upgrade renames classes | Med | Med | Already pinned `sqlglot>=30,<31` in requirements; gate test suite (golden SQL) covers each `_BLOCKED_STATEMENTS` class |
| Agent loops on `build_chart` validation_error | Med | Med | Validation errors include the exact missing field name; per-chart attempts capped at 3 in the agent prompt; total tool calls capped at 60 |
| Agent forgets to call `update_memory` | Med | Low | Hard rule in `synthesis_rules_v2.md` §6: "every persist_insight MUST be paired with at least one update_memory call." Cap-trip on second offence reduces the per-session insights without breaking the run |
| v2 cutover breaks an unknown caller | Low | High | Deprecation header alerts integrators; `version="v1"` continues to work for the 2-week sunset window; `Sunset` header is machine-readable |
| OpenClaw memory plugin unavailable | Low | Med | Phase A validation gate already exists; v2 sessions fall back to in-session-only journaling — degraded but functional |
| Sidebar staleness (in-flight entries not in MEMORY.md until dreaming sweep) | High | Low | Document the constraint to users; if it bites, add a live read path that shells `openclaw memory search` (out of scope V2) |
| `agent_chart.insight_id` nullable race | Low | Low | UNIQUE constraint not enforced on `(insight_id)` because chart is created before insight; the build_chart→persist_insight flow is sequential within a single tool-loop turn so race is impossible in practice |
| Citation `row_hash` set goes stale across long sessions | Low | Low | Driver expires hashes after 10 minutes — beyond the 900s session wall — so this can't happen within a session |

---

## 6. File Touch List (deltas to spec Appendix A)

The spec Appendix A lists Phase C only. Phases B and D add the following on top:

### Phase B (new files)

| File | Action | Rationale |
|---|---|---|
| `backend/alembic/versions/017_doc_passages.py` | NEW | `edgar_passages` + `permit_passages` tables, GIN(tsv), unique(document_id, ord) |
| `backend/alembic/versions/018_doc_passage_embeddings.py` | NEW (gated, B.2) | `embedding vector(3072)` + IVFFlat |
| `backend/scripts/backfill_doc_passages.py` | NEW | Resumable batched chunker over existing documents |
| `backend/scripts/backfill_doc_embeddings.py` | NEW (gated) | Batched embedder over passages where embedding IS NULL |
| `backend/ingestion/_chunking.py` | NEW | Pure `chunk_document(text) -> list[Chunk]` + `chunk_and_upsert(session, ...)` |
| `backend/ingestion/edgar.py` | EDIT | One call to `chunk_and_upsert` after the pg_insert at line 369 |
| `backend/ingestion/epa_echo.py` | EDIT | Same hook |
| `backend/ingestion/permits_state/{tceq,va_open_data,iowa,ohio,socrata}.py` | EDIT | Same hook (each `run`) |
| `backend/ingestion/permits_county/{loudoun,mesa,grantwa}.py` | EDIT | Same hook in `fetch_and_store` |
| `backend/ingestion/bulk_pdf_runner.py` | EDIT | Hook after `parse_permit_pdf` returns successfully |
| `backend/agents/insights/tools/search_documents.py` | NEW | The MCP tool |
| `backend/agents/insights/tools/registry.py` | EDIT | Register `search_documents`; split into v1/v2 tool lists |
| `backend/tests/test_search_documents.py` | NEW | Golden 30-pair recall set + latency assertion |
| `backend/tests/test_chunker.py` | NEW | Determinism + idempotency tests |
| `backend/tests/test_backfill_doc_passages.py` | NEW | Resumability test (kill mid-run, restart, identical state) |

### Phase C (already in spec Appendix A — restated and extended)

Spec Appendix A entries kept verbatim; we add:

| File | Action |
|---|---|
| `backend/agents/insights/tools/persist_insight.py` | NEW (v2 path — file does not exist today; persist_insight is in OpenClaw forwarder side, but v2 needs an app-side tool that performs the validation order in §3.3) |
| `backend/agents/insights/tools/build_chart.py` | NEW |
| `backend/agents/insights/specs/skill_context.py` | EDIT — add `version: 'v1'\|'v2'` to `SkillContext` so tools can branch on it |
| `backend/agents/insights/orchestrator.py` | EDIT — when `self.version == "v2"`, skip `_phase_bootstrap_iter` + `_phase_hypothesize_iter`; pass `fact_pack=None, version="v2"` to `run_agentic_synthesis` |
| `backend/tests/test_build_chart.py` | NEW — chart_type compatibility matrix tests |
| `backend/tests/test_persist_insight_v2.py` | NEW — REJECT-code coverage |
| `backend/tests/test_agentic_synthesis_v2_branch.py` | NEW — version dispatch test |

### Phase D

| File | Action |
|---|---|
| `backend/routers/insights.py` `CreateSessionBody` | EDIT — `version: str = Field(default="v2", ...)` |
| `backend/routers/insights.py` (multiple endpoints) | EDIT — attach `Deprecated`/`Sunset` headers when responding under v1 |
| `frontend/src/components/tabs/ai-insights/TrackedQuestionsSidebar.tsx` | NEW — 30s polling, parsed pipe fields |
| `frontend/src/components/tabs/ai-insights/AIInsightsTab.tsx` | EDIT — slot the new sidebar |
| `backend/tests/test_v2_default_version.py` | NEW — round-trip POST /sessions returns v2 row |
| `backend/tests/test_v1_deprecation_headers.py` | NEW — header presence test |

---

## 7. Rollout Sequence (engineer-facing)

The dependency graph between phases is permissive — B and C can ship in parallel after the migration lands, and D depends on both. Concrete order:

**Week 1 — Phase B.1 lands first:**

1. `017_doc_passages.py` migration. Run on staging.
2. `_chunking.py` helper (pure function, no DB).
3. `backfill_doc_passages.py` CLI. Run on staging; verify ~60K rows.
4. Wire chunker into `ingestion/edgar.py` first (highest-volume adapter); verify a fresh ingestion appends new passages without duplicating old ones.
5. Wire chunker into the remaining adapters (epa_echo, permits_state/*, permits_county/*, bulk_pdf_runner). All 8 adapters can be parallelised across engineers — they all call the same helper.
6. `tools/search_documents.py` BM25-only path; register in `registry.py`.
7. Run the 30-pair golden recall test. **Decision gate:** if recall@8 ≥ 0.85, skip B.2. Otherwise proceed to step 8.
8. (Gated) `018_doc_passage_embeddings.py` + `backfill_doc_embeddings.py`. Switch `search_documents` to RRF.

**Week 1 in parallel — Phase C scaffolding (does not block on B):**

9. Harden `sql_gate.py` per §3.1 (most checks already there; add startup assertion for `ai_agent` role).
10. `tools/build_chart.py` — depends only on the existing `chart_spec.py` and `query_database`. Tests via the chart_type compatibility matrix.
11. `tools/persist_insight.py` v2 — depends on `agent_chart`, `agent_citation`, and the row_hash set from `query_database`. Stub the `passage_id` existence check; complete it once Phase B.1 lands `edgar_passages` / `permit_passages`.
12. `prompts/synthesis_rules_v2.md` — author the prompt; do not wire it in yet.
13. `agentic_synthesis.run_agentic_synthesis` — add the `version` param and the v2 branch; v1 behaviour unchanged. Ship behind a feature flag (`settings.ai_insights_v2_enabled = False` until ready).
14. `orchestrator.py` — branch on version; v2 skips bootstrap/hypothesize.

**Week 2 — integration + Phase D:**

15. End-to-end smoke: create a v2 session via `POST /sessions {version:"v2"}`. Run on a manual session; observe agent reading SCHEMA + FRESHNESS, drilling via query_database, calling search_documents, building one chart, persisting one insight, and writing one open_questions journal entry.
16. Run the 10-scenario golden eval (spec §13). Manual rubric on V2 vs V1.
17. Phase D: flip `CreateSessionBody.version` default to `"v2"`. Add deprecation headers. Land sidebar.
18. T+14d: delete v1 (`hypothesizer.py`, `_chart_from_supporting_rows`, `synthesis_rules.md`, v1 fact-pack tests, `emit_chart`, `emit_citation`).

**Critical-path notes for the engineer:**

- B.1 migration MUST land before step 11 can complete (persist_insight needs the passage tables to validate `passage_id`).
- C steps 10-12 do not block on each other; assign in parallel.
- D step 17 is reversible: flipping the default back to v1 takes one line change. Keep v1 healthy until T+14d.

---

## Sequence Diagrams

### v2 Session Lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant FE as Frontend
    participant API as routers/insights.py
    participant ORCH as InsightOrchestrator
    participant SYN as agentic_synthesis
    participant OC as OpenClaw gateway
    participant AG as Agent (LLM)
    participant FS as .openclaw/workspace
    participant MEM as OpenClaw memory
    participant DB as Postgres (ai_agent role)
    participant PASS as edgar_passages / permit_passages

    FE->>API: POST /sessions {version:'v2'}
    API->>ORCH: run_session(version='v2')
    Note over ORCH: skip bootstrap + hypothesize (v2)
    ORCH->>SYN: run_agentic_synthesis(fact_pack=None, version='v2')
    SYN->>OC: stream open with workspace_pointers
    OC->>AG: system=synthesis_rules_v2.md, user={pointers}

    AG->>OC: tool_call read_workspace(SCHEMA.md)
    OC->>FS: read SCHEMA.md (16KB cap)
    FS-->>AG: markdown
    AG->>OC: tool_call read_workspace(FRESHNESS.md)
    FS-->>AG: markdown

    AG->>OC: tool_call memory_search('', open_questions, k=20)
    OC->>MEM: search journal
    MEM-->>AG: top 20 entries

    loop per insight target
        AG->>OC: tool_call query_database(SQL)
        OC->>DB: SET LOCAL statement_timeout=5000; SELECT ...
        DB-->>AG: rows + row_hash
        opt drill via documents
            AG->>OC: tool_call search_documents(q, source, k=8)
            OC->>PASS: BM25 (+ optional cosine)
            PASS-->>AG: passages + citations
        end
        AG->>OC: tool_call build_chart(SQL, encoding, title)
        OC->>DB: SQL via gate
        DB-->>OC: rows
        OC-->>AG: {chart_id, chart_spec}
        AG->>OC: tool_call persist_insight(chart_id, citations[], ...)
        OC->>DB: validate chart→session, citations exist; INSERT ai_insight + UPDATE agent_chart
        AG->>OC: tool_call update_memory(open_questions, fact)
        OC->>MEM: append journal entry
    end

    AG->>OC: tool_call finalize_session(complete)
    SYN-->>ORCH: SynthesisResult
    ORCH-->>API: session_complete SSE
    API-->>FE: stream end
```

### `search_documents` BM25 Path

```mermaid
sequenceDiagram
    autonumber
    participant AG as Agent
    participant TOOL as search_documents.py
    participant DB as Postgres
    participant ENR as enrichment join

    AG->>TOOL: search_documents(query, source='all', k=8)
    TOOL->>TOOL: clamp k to [1,16]; sanitise query
    Note over TOOL,DB: source='all' branch (UNION ALL)
    TOOL->>DB: WITH e AS (... LIMIT k), p AS (... LIMIT k) SELECT * UNION ALL ORDER BY score LIMIT k
    DB-->>TOOL: passages [(passage_id, src, score, text), ...]
    TOOL->>ENR: enrich(passages)
    ENR->>DB: JOIN edgar_extractions for src='edgar' passage_ids
    ENR->>DB: JOIN parent permit table by source_kind for src='permits' passage_ids
    DB-->>ENR: citation metadata
    ENR-->>TOOL: passages with citation block
    TOOL-->>AG: {ok, passages:[...], diagnostics:{latency_ms, k_returned}}
```

### `build_chart` → `persist_insight` Chain

```mermaid
sequenceDiagram
    autonumber
    participant AG as Agent
    participant BC as build_chart
    participant GATE as sql_gate
    participant QDB as query_database
    participant CHART as agent_chart
    participant PI as persist_insight (v2)
    participant INS as ai_insight
    participant CIT as agent_citation
    participant PASS as edgar_passages / permit_passages

    AG->>BC: build_chart(sql, encoding, title)
    BC->>GATE: validate_sql(sql)
    GATE-->>BC: ValidatedSQL or SqlGateError
    BC->>QDB: execute validated_sql
    QDB-->>BC: rows + row_hash
    BC->>BC: validate columns vs encoding; chart_type compatibility
    alt validation fails
        BC-->>AG: {ok:false, code:'incompatible_encoding'|...}
    else ok
        BC->>CHART: INSERT (chart_id, session_id, insight_id=NULL, spec, data_source, row_hash)
        BC-->>AG: {ok:true, chart_id, chart_spec}
    end

    AG->>PI: persist_insight(session_id, insight, chart_id, citations[])
    PI->>CHART: SELECT session_id WHERE chart_id=:chart_id
    alt mismatch or missing
        PI-->>AG: 422 chart_id_session_mismatch / chart_id_not_found
    end
    loop per citation
        alt citation.passage_id set
            PI->>PASS: SELECT 1 WHERE passage_id=:pid
        else citation.row_hash set
            PI->>PI: lookup row_hash in per-session set
        end
        opt none verifiable
            PI-->>AG: 422 citation_invalid
        end
    end
    PI->>INS: INSERT ai_insight
    PI->>CHART: UPDATE insight_id WHERE chart_id=:chart_id AND insight_id IS NULL
    PI->>CIT: INSERT agent_citation rows
    PI-->>AG: {ok:true, insight_id}
```

---

## ADRs (key decisions)

### ADR-001: BM25 first, pgvector hybrid only on recall miss

**Decision:** ship Phase B in two stages. B.1 is BM25-only via `tsvector` + `websearch_to_tsquery`. B.2 (cosine + RRF) ships only if recall@8 < 0.85 on a 30-pair golden set.

**Status:** accepted.

**Context:** EDGAR + permits corpora are ~60K passages. BM25 is a good baseline for capacity-keyword-dense queries ("Crusoe Wyoming offtaker"). Embedding backfill is ~1 hour at 64-batch and adds operational complexity.

**Consequences:** if B.1 hits the bar we save ~2 days. If not, the migration path is clean: add column + index + a `WHERE embedding IS NULL` backfill, then flip the tool to RRF. No schema rework.

### ADR-002: Polymorphic `permit_passages.document_id` with `source_kind`

**Decision:** `permit_passages` does not have a hard FK. Instead, `(source_kind, document_id)` is enforced by application code (the chunker is the sole writer).

**Status:** accepted.

**Context:** the permit ecosystem has three parent tables (`generator_permits`, `building_permits`, county tables). A polymorphic FK isn't expressible in PostgreSQL without inheritance or a UNION-of-tables view; both add more complexity than they save.

**Consequences:** lose CASCADE on parent deletes; backfill has to observe `data_lineage` deletions. The chunker centralises writes so this is a single point of discipline.

### ADR-003: Generated `tsv` column over trigger

**Decision:** `tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED`.

**Status:** accepted.

**Context:** Postgres ≥12 supports stored generated columns. Triggers were the historical answer.

**Consequences:** zero application maintenance. If we later want a multi-column tsv (e.g. mix `cik` into `text`) we'd switch back to a trigger; today, single-column is fine.

### ADR-004: Chart-first ordering — `build_chart` returns `chart_id`, `persist_insight` requires it

**Decision:** the agent MUST call `build_chart` before `persist_insight`; `persist_insight` rejects on missing or session-mismatched `chart_id`.

**Status:** accepted.

**Context:** v1's `_chart_from_supporting_rows` synthesised a chart from row IDs after the fact. This collapsed all charts to bar (orchestrator.py:140-214). The chart shape MUST be the agent's choice and the data MUST be queried explicitly.

**Consequences:** agent runs cost ~1 extra tool call per insight. Worth it: charts now match claims (stacked, time-series, etc.). Per-session insight count drops from 5-10 to 5-7 — accepted trade-off.

### ADR-005: Default `version="v2"` with 2-week sunset on v1

**Decision:** Phase D flips the default. v1 stays available with `Deprecated: true` and `Sunset: 2026-05-21` headers for 14 days, then is deleted.

**Status:** accepted.

**Context:** the orchestrator already plumbs `version` end to end; the only change is one default literal. The sunset window matches the spec §8 plan.

**Consequences:** any client passing `version="v1"` explicitly continues to work for 2 weeks; clients omitting the field get v2 immediately. Headers are machine-readable for any integrators using OpenAPI spec inspection.

### ADR-006: v1 path is byte-identical until T+14d delete

**Decision:** the Phase C branch is purely additive in `agentic_synthesis.run_agentic_synthesis`. Existing v1 prompts, tools, and fact_pack code paths are not touched.

**Status:** accepted.

**Context:** v1 is in production daily-cron use today. Any change risks a regression.

**Consequences:** brief duplication of code paths. Cleanup is scheduled at T+14d (spec §8 Phase D bullet).

---

## Files Relevant to This Architecture

- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phases_bcd_architecture.md (this document)
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_spec.md (PRD)
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/ai_insights_v2_phase_a_architecture.md (Phase A predecessor)
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/tools/sql_gate.py (gate to harden in C)
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/tools/registry.py (split in C)
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/tools/query_database.py (reused by build_chart)
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/agentic_synthesis.py (version branch in C)
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/orchestrator.py (skip phases for v2)
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/specs/chart_spec.py (validation source-of-truth for build_chart)
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/scripts/provision_ai_agent_role.sql (role used by query_database)
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/routers/insights.py (D: default + headers; existing /open-questions parser at line 1237)
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/alembic/versions/013_ai_insight_embedding_vector.py (pgvector reference)
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/ingestion/edgar.py (chunker hook at line 369)
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/ingestion/pdf_parser.py (chunker hook caller path)
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/ingestion/epa_echo.py
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/ingestion/permits_state/*.py
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/ingestion/permits_county/{loudoun,mesa,grantwa}.py
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/pipeline/runner.py (catch-up scheduling for backfill)
- /home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/llm/client.py (LlmClient.embed for B.2 backfill)
