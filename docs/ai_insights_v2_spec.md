# AI Insights v2 — Agentic Redesign Spec

**Status:** Draft · **Date:** 2026-05-07 · **Owner:** gabrielle.lyu
**Supersedes:** the FactPack-driven flow currently shipping under `version="v1"`.

---

## 1. Motivation

Current AI Insights output is shallow, repetitive, and visually flat. Three concrete failure modes:

1. **Insights reformulate pre-computed SQL.** `hypothesizer.build_factpack` runs 11 hardcoded aggregators and hands the agent ~100 rows. `synthesis_rules.md:50-52` then *discourages* drill-down (`query_database` is "last resort"). The agent ends up paraphrasing rows it was handed — no novel discovery.
2. **Charts collapse to bar.** `_chart_from_supporting_rows()` (`orchestrator.py:140-214`) groups supporting rows into `{entity → max(value)}`. Every chart becomes one scalar per entity. Stacked / grouped / time-series silently downgrade because `FactRow` has only one `value` field.
3. **Order is inverted.** Agent picks `chart_type` *inside* `persist_insight`; chart is synthesized post-hoc from row IDs. Worked example: Crusoe Wyoming has 720 MW with 360 MW under construction and no named offtaker — the right chart is **site total split by contracted/uncontracted × stage**. Current shape can't render that; it shows DC-1 and DC-2 as two bars.

Plus a structural gap:

4. **Sessions are amnesiac.** Cross-day dedup is embedding-similarity on headlines. There is no cumulative knowledge — the agent can't say "I flagged Crusoe 3 days ago, +180 MW since, upgrading to confirmed."

5. **No document retrieval.** `edgar_extractions` lands as structured columns, not paragraphs. The agent cannot cite the actual contract language behind a finding.

## 2. Current Architecture (brief)

```
POST /api/insights/sessions
        │
        ▼
InsightOrchestrator.run_session()                      backend/agents/insights/orchestrator.py
  ├─ Phase A — Bootstrap
  │   ├─ 8 fixed call_api surveys (gw-summary, l1, l2, anomalies, …)
  │   └─ build_factpack() → 11 SQL aggregators → FactPack (≤132 rows)
  └─ Phase B — Synthesis
      └─ run_agentic_synthesis()                       backend/agents/insights/agentic_synthesis.py
          ├─ system: prompts/synthesis_rules.md
          ├─ user:   {today, session_id, max_insights, factpack_digest, instructions}
          └─ stream: openclaw/forwarder._drive_openclaw_stream
              └─ MCP tools: persist_insight, finalize_session,
                            query_database, run_skill, web_search
```

Root causes of the failure modes above all live in one decision: **the agent's input is a FactPack, and its output binding for charts is `supporting_row_ids` collapsed to entity-scalar.**

## 3. Target Architecture

```
                       ┌─────────────────────────────────────────────────┐
                       │ .openclaw/workspace/  (auto-refreshed artefacts)│
                       │                                                 │
                       │  SCHEMA.md          ← Alembic post-upgrade hook │
                       │  FRESHNESS.md       ← nightly cron (SQL only)   │
                       │  MEMORY.md          ← OpenClaw native (journal) │
                       └─────────────────────────────────────────────────┘
                                            │
                                            │ read at session start
                                            ▼
POST /api/insights/sessions
        │
        ▼
InsightOrchestrator.run_session()  (single-phase, agent-driven)
        │
        ▼
run_agentic_synthesis()
  ├─ system: prompts/synthesis_rules_v2.md
  ├─ user:   { today, session_id, max_insights,
  │           workspace_pointers: [SCHEMA.md, FRESHNESS.md] }
  └─ stream: openclaw/forwarder._drive_openclaw_stream
        │
        ▼
   Tool palette (v2):
   ┌───────────────────────────────────────────────────────────────┐
   │ READ (app-owned MCP)                                          │
   │   read_workspace(file)        → markdown                      │
   │   query_database(sql)         → rows                          │
   │   search_documents(q, source) → passages + citations          │
   │                                                               │
   │ READ (OpenClaw native)                                        │
   │   memory_search(q, category)  → journal hits                  │
   │   memory_get(file, range)     → direct memory read            │
   │                                                               │
   │ BUILD (app-owned MCP)                                         │
   │   build_chart(sql, encoding)  → ChartSpec + chart_id          │
   │                                                               │
   │ WRITE (app-owned MCP)                                         │
   │   persist_insight(... chart_id, citations[])                  │
   │   finalize_session(session_id, status)                        │
   │                                                               │
   │ WRITE (OpenClaw native)                                       │
   │   update_memory(category, fact)  → journal entry              │
   └───────────────────────────────────────────────────────────────┘
```

**Key shape changes versus v1:**

| Concern | v1 | v2 |
|---|---|---|
| Agent's input | FactPack (≤132 pre-aggregated rows) | Workspace pointers (schema, freshness) + OpenClaw memory |
| Discovery | Discouraged | Required — agent drives SQL + doc search |
| Chart binding | `chart_type` hint, post-hoc synthesis from row IDs | `chart_id` from `build_chart`, prerequisite |
| Cross-run memory | None (embedding dedup only) | OpenClaw memory (`category="open_questions"`) + dreaming |
| Document grounding | None (structured columns only) | `search_documents` over EDGAR + permits |

## 4. Workspace Artefacts

Two app-owned files live in `.openclaw/workspace/` (read via `read_workspace(file)`, 16KB cap per read). The third surface — the agent's open-questions journal — uses OpenClaw's native memory primitives, not a custom file.

### 4.1 `SCHEMA.md`

**Purpose:** Tell the agent what tables, columns, FKs, and *named entities* exist. Replaces the "entity inventory" idea — top-N samples per high-signal table fold in here.

**Refresh trigger:** Alembic post-upgrade hook (`backend/alembic/env.py`). Schema only changes with migrations, so cron is unnecessary.

**Generator:** `backend/scripts/refresh_schema_doc.py` — introspects SQLAlchemy `Base.metadata`, runs `SELECT * … LIMIT 10 ORDER BY <metric> DESC` for each high-signal table.

**Format:**

```markdown
# Schema Digest — generated 2026-05-07T02:00Z (migration 016)

## Tables (28)

### `companies`  (1,247 rows)
| column | type | nullable | fk |
|---|---|---|---|
| id | uuid | no | pk |
| name | text | no | — |
| ticker | text | yes | — |
| total_mw | numeric | yes | — |

**Top 10 by `total_mw`:**
| name | ticker | total_mw |
|---|---|---|
| Microsoft | MSFT | 18,400 |
| Amazon | AMZN | 15,200 |
| Crusoe | — | 720 |
| …

### `sites` (3,891 rows)
…

### `energy_projects` (12,447 rows)
… (FKs: developer_company_id → companies.id, site_id → sites.id)

### `edgar_extractions` (8,221 rows)
…

## High-signal join paths
- companies ←(developer_companies[])― energy_projects ―(site_id)→ sites
- sites ―(state, county)→ generator_permits (source='epa_echo')
- companies ―(cik)→ edgar_extractions
```

High-signal tables (V2 scope): `companies`, `sites`, `energy_projects`, `edgar_extractions`, `generator_permits`, `building_permits`, `power_contracts`, `anomalies`, `data_coverage`. ~30KB markdown total.

### 4.2 `FRESHNESS.md`

**Purpose:** Tell the agent where the deltas are. No reasoning — just metadata.

**Refresh trigger:** Cron, daily 02:00 UTC, post-ingestion. Job: `backend/scripts/refresh_freshness_doc.py`.

**Format:**

```markdown
# Freshness — generated 2026-05-07T02:00Z

| table | rows | max(updated_at) | Δ 7d | Δ 24h |
|---|---|---|---|---|
| energy_projects | 12,447 | 2026-05-06 22:14Z | +312 | +47 |
| edgar_extractions | 8,221 | 2026-05-07 01:48Z | +89 | +12 |
| generator_permits | 4,103 | 2026-05-06 18:00Z | +18 | 0 |
| anomalies | 217 | 2026-05-07 00:30Z | +14 | +3 |
| …

## Hot tables (Δ 7d > 5%)
- energy_projects (+2.6%)
- anomalies (+6.9%)
- edgar_extractions (+1.1%)
```

Cheap — ~2KB. Pure SQL. The "hot tables" rollup is a single `WHERE pct_change > 0.05` filter.

### 4.3 Open-questions journal — via OpenClaw memory

**Purpose:** The agent's own research journal. Makes runs cumulative.

**Mechanism:** **No custom file, no custom tool.** Uses OpenClaw's native memory plugin (already configured for this project per `SOUL.md:260-285`). The agent writes journal entries via `update_memory(category="open_questions", fact=...)` and recalls them via `memory_search(q, category="open_questions")` / `memory_get`.

**Why this shape:** OpenClaw memory is markdown-backed (`MEMORY.md` + `memory/YYYY-MM-DD.md`), SQLite-indexed, hybrid-search aware, and has a built-in dreaming pass that promotes durable items to `MEMORY.md` on a schedule. We get cross-session recall, semantic search, and lifecycle management for free.

**Entry format (one fact per `update_memory` call, ≤200 chars — OpenClaw's per-fact cap):**

```
<id> | <status> | <materiality> | <one-line summary or evidence note>
```

Examples:

```
update_memory(category="open_questions", fact=
  "q_crusoe-wy-uncontracted | watching | high | 720MW Wyoming, 360MW construction, no offtaker — watch for 8-K naming hyperscaler")

update_memory(category="open_questions", fact=
  "q_crusoe-wy-uncontracted | watching | high | 2026-05-07: +120MW DC-2 stage=construction; still no offtaker in EDGAR")

update_memory(category="open_questions", fact=
  "q_qts-virginia-rampdown | disproved | low | originally flagged 2026-05-02; permit data shows expected pause not cancellation")
```

The pipe-delimited convention (`id | status | materiality | note`) keeps facts parseable for the frontend sidebar (§4.4) without inventing a new schema.

**Status values:** `watching`, `confirmed`, `disproved`, `stale`.

**Lifecycle:** OpenClaw's dreaming pass promotes high-recall, durable entries from short-term store to `MEMORY.md`. Disproved/stale entries naturally decay — no custom archive logic needed.

**At session start:** the agent calls `memory_search("", category="open_questions", limit=20)` to surface active journal entries, then decides which to advance or open.

### 4.4 Frontend sidebar — backend route reads `MEMORY.md`

The "Tracked questions" sidebar (Phase D) reads from `.openclaw/workspace/MEMORY.md` via a new backend route:

```
GET /api/insights/open-questions
  → [{ id, status, materiality, latest_note, last_seen_iso }, ...]
```

**Implementation:** parse `MEMORY.md` (markdown with section headers per category), filter to the `open_questions` section, split each fact line on `|` to extract structured fields, group by `id` keeping the most recent note as `latest_note`.

**Tradeoff:** MEMORY.md only contains entries promoted by OpenClaw dreaming. In-flight entries from today's session may not appear until the nightly dreaming sweep. Acceptable for V2 — the sidebar is "what's durable," not "what just happened." If staleness becomes an issue, add a backend route that shells out to `openclaw memory search` for live data.

## 5. Tool Contracts

All tools follow the existing MCP shape (`backend/agents/insights/tools/registry.py`). Wrap with `SkillContext`.

### 5.1 `read_workspace(file: str) → {ok, content, truncated}`

```python
async def read_workspace(file: Literal["SCHEMA.md", "FRESHNESS.md"],
                         ctx: SkillContext) -> dict:
    """Read a workspace artefact. Returns first 16KB; truncated=True if longer."""
```

Cheap; no SQL. Allowlist enforced — no arbitrary path traversal. Note: the journal is read via OpenClaw's native `memory_search` / `memory_get`, not this tool.

### 5.2 `query_database(sql: str, params: dict) → {ok, rows, row_count, truncated}`

```python
async def query_database(sql: str, params: dict | None = None,
                         ctx: SkillContext) -> dict:
    """Read-only SQL. Hardened by sql_gate.py:
       - parses to AST, rejects non-SELECT
       - rejects writes to information_schema, pg_catalog
       - 10s statement timeout
       - 5,000 row cap (truncated=True if exceeded)
       - schema-scoped to public.* + listed views
    """
```

Existing `tools/sql_gate.py` is the starting point — needs hardening (see §10).

### 5.3 `search_documents(query: str, source: str, k: int) → {ok, passages}`

```python
async def search_documents(query: str,
                           source: Literal["edgar", "permits", "all"],
                           k: int = 8,
                           ctx: SkillContext) -> dict:
    """Passage retrieval over EDGAR filings + permit PDFs.
       Returns:
         passages: [{
           text: str,            # ~300 token window
           citation: {
             source: "edgar" | "permits",
             company: str | None,  # for edgar, resolved via cik
             filing_type: str | None, # 8-K / 10-K / building / generator
             url: str,
             retrieved_at: ISO8601,
             passage_id: str,
           },
           score: float,
         }]
    """
```

**New backing infra (Phase B):**
- Embedding model: `text-embedding-3-large` via OCI Generative AI (matches existing dedup).
- Index: pgvector tables `edgar_passages_v` and `permit_passages_v` with `(passage_id, document_id, text, embedding)`.
- Ingestion: piggyback on existing EDGAR + permit ingestion to chunk text → embed → upsert.
- Hybrid retrieval: BM25 (Postgres `tsvector`) + cosine, `RRF` merge.

### 5.4 `build_chart(sql, encoding, title) → {ok, chart_id, chart_spec}`

```python
async def build_chart(
    sql: str,
    encoding: {
        "chart_type": ChartType,            # one of 16 in chart_spec.py
        "x": {field: str, type: str, label: str | None},
        "y": {field: str, type: str, label: str, unit: str | None},
        "series": {field: str} | None,      # for stacked/grouped/multi-line
        "facet": {field: str} | None,       # small multiples
    },
    title: str,
    subtitle: str | None = None,
    ctx: SkillContext,
) -> dict:
    """Run sql via sql_gate, validate result against encoding, persist
    a ChartSpec row in agent_chart, return chart_id + full ChartSpec.

    Validation:
      - sql must return columns matching encoding fields
      - row count ≤ 200 (else truncated=True, top-200 by y desc)
      - chart_type compatible with encoding (e.g. stacked_bar requires series)

    The returned ChartSpec is what InsightChart.tsx renders verbatim.
    No post-hoc synthesis.
    """
```

**This is the central change.** The agent is now responsible for declaring chart shape and the data behind it. `_chart_from_supporting_rows()` is deleted.

### 5.5 `persist_insight(...)` — reordered

```python
async def persist_insight(
    session_id: str,
    insight: {
        "headline": str,           # ≤140
        "body": str,               # 1-3 sentences
        "confidence_signal": Literal["weak", "moderate", "strong"],
        "materiality": Literal["low", "medium", "high"],
    },
    chart_id: str,                 # MUST come from build_chart in same session
    citations: list[Citation],     # at least one — passage_id from search_documents
                                   #               or row_ids from query_database
    open_question_id: str | None = None,  # if this advances a journal entry
    ctx: SkillContext,
) -> dict:
```

Removes: `chart_type`, `chart_y_label`, `supporting_row_ids` (replaced by typed `citations[]`).

### 5.6 Journal mutation — OpenClaw native, no custom tool

Use OpenClaw's built-in `update_memory(category="open_questions", fact="...")`. Format per §4.3. No app-side tool, no migration, no file-locking — OpenClaw's memory plugin owns persistence and indexing.

### 5.7 `finalize_session(...)` — unchanged

## 6. Prompt — `synthesis_rules_v2.md` outline

Replace, don't patch. Old `synthesis_rules.md` is incompatible with the new tool surface (it instructs the agent to *avoid* drilling).

**Sections:**
1. **Role.** "You are running a SYNTHESIS turn. Your job is to discover, defend, and persist insights about hyperscaler datacenter / power buildout vs OCI."
2. **Workflow (must-do).**
   - Read `SCHEMA.md` and `FRESHNESS.md` via `read_workspace`.
   - Recall active journal entries via `memory_search("", category="open_questions", limit=20)`.
   - Decide: advance N existing open questions, open M new ones (target N+M = max_insights).
   - For each target:
     - Drill via `query_database` and/or `search_documents` until you have a defensible claim.
     - Call `build_chart` with the SQL + encoding that supports the claim.
     - Call `persist_insight` with the chart_id + citations.
     - Call `update_memory(category="open_questions", fact=...)` with a status flip and/or evidence note (format per §4.3).
   - Call `finalize_session` exactly once.
3. **OCI lens.** (Carry over from v1 — frame as offtake / competitive / customer-acquisition implication for Oracle.)
4. **Chart palette.** Reference `SOUL.md §"Chart palette"`. Pick the type that fits the claim, not the data shape you happen to have.
5. **Budget.** 30 tool calls, 12 turns, 600s wall (raised — see §9).
6. **Hard rules.**
   - Every `persist_insight` MUST have a `chart_id` from this session.
   - Every `persist_insight` MUST have ≥1 `citation` from `query_database` OR `search_documents`.
   - Every `persist_insight` MUST be paired with at least one `update_memory(category="open_questions", ...)` call (advancing or opening an entry).
   - Plain-text replies are dropped.

## 7. SSE Event Flow

Mostly unchanged. Two deltas:

- `ChartEvent.data.chart` is now the spec returned by `build_chart`, not a synthesized post-hoc spec. Same `ChartSpec` schema — frontend doesn't change.
- The "Tracked questions" sidebar (Phase D) reads from `GET /api/insights/open-questions` (§4.4), which parses `MEMORY.md`. No new SSE event needed — the sidebar polls/refreshes independently of the session stream.

## 8. Migration Plan (incremental — no big-bang cutover)

The orchestrator already supports `version="v1"|"v2"` (see `routers/insights.py` `CreateSessionBody`). Use the version flag for cutover.

### Phase A — Workspace artefacts (1-2 days)
- [ ] `refresh_schema_doc.py` + Alembic post-upgrade hook → writes `.openclaw/workspace/SCHEMA.md`
- [ ] `refresh_freshness_doc.py` + cron → writes `.openclaw/workspace/FRESHNESS.md`
- [ ] Verify OpenClaw memory plugin is configured for the agent (already enabled per `SOUL.md`); confirm `update_memory` / `memory_search` are reachable from synthesis sessions.
- [ ] `read_workspace` MCP tool (allowlist: `SCHEMA.md`, `FRESHNESS.md`)
- [ ] `GET /api/insights/open-questions` — parses `.openclaw/workspace/MEMORY.md`, filters `open_questions` section, splits pipe-delimited facts (§4.4)

**Validation:** files exist, are well-formed, schema generator handles new migrations, sample `update_memory` write surfaces in `MEMORY.md` after dreaming sweep.

### Phase B — Doc retrieval infra (1-2d BM25, +2d if pgvector needed)

**B.1 — BM25 first (1-2 days):**
- [ ] Alembic: `edgar_passages` + `permit_passages` tables (`passage_id`, `document_id`, `text`, `tsv tsvector`, GIN index)
- [ ] Backfill: chunk existing EDGAR filings (~8K) and permit PDFs (~4K) into ~300-token passages; populate `tsv` via `to_tsvector('english', text)`
- [ ] Wire chunking into ongoing ingestion (`backend/ingestion/`)
- [ ] `search_documents` MCP tool — BM25-only via `ts_rank_cd(tsv, websearch_to_tsquery(...))`
- [ ] Run golden set (30 labelled {claim, expected_passage} pairs)

**B.2 — Add pgvector hybrid (gated, +2 days):** *only if B.1 recall@8 < 0.85.* pgvector extension already installed (migrations 009, 013).
- [ ] Add `embedding vector(3072)` column + IVFFlat index on both passage tables
- [ ] Backfill embeddings via OCI Generative AI (`text-embedding-3-large`)
- [ ] Wire embedding into ingestion pipeline
- [ ] Switch `search_documents` to RRF merge (BM25 + cosine)

**Validation:** retrieval latency p95 < 500ms; recall@8 ≥ 0.85 on the 30-pair golden set.

### Phase C — New tools + v2 prompt (2-3 days)
- [ ] Harden `tools/sql_gate.py` (parser-based, not regex; statement timeout; row cap)
- [ ] `build_chart` MCP tool + `_chart_from_supporting_rows()` deletion path
- [ ] `persist_insight` v2 schema (parallel to v1)
- [ ] `synthesis_rules_v2.md` (uses native `update_memory` / `memory_search` for journal — no custom journal tool)
- [ ] `agentic_synthesis.run_agentic_synthesis(version="v2")` branch

**Validation:** golden-set replay — 10 known scenarios produce non-trivially better insights than v1 (rubric: claim specificity, chart shape match, journal advancement). Manual eval.

### Phase D — Cutover (1 day)
- [ ] Frontend: surface "Tracked questions" sidebar — polls `GET /api/insights/open-questions`
- [ ] Default `POST /sessions` to `version="v2"`
- [ ] Mark v1 deprecated (`Deprecated` response header on v1 sessions)
- [ ] After 2 weeks of v2 default: delete `hypothesizer.py`, `_chart_from_supporting_rows`, `synthesis_rules.md`, v1 fact-pack tests

## 9. Cost & Latency

**Per-session budget changes:**

| Resource | v1 | v2 | Δ |
|---|---|---|---|
| Wall-clock | 480s | **900s** | +420s |
| Tool calls | 40 | **60** | +20 |
| LLM turns | 12 (synthesis) | 16 | +4 |
| Output insights | 5-10 | 5-7 | -2-3 |

**Why:**
- Each insight now costs ~3-5 tool calls (workspace read + 1-2 SQL + 0-1 doc search + build_chart + persist_insight + update_memory) instead of 1 (`persist_insight` from FactPack).
- Workspace reads are cheap (~50ms). SQL p95 should be <2s. Doc search p95 <500ms. `build_chart` p95 <2s.
- Total per-session model cost estimate: **2.5× v1** at the same insight count. Reducing insight count to 5-7 brings the multiplier to ~1.8×.

**Cache strategy:** workspace artefacts are cacheable (Anthropic prompt caching, 5-min TTL). All three artefacts in the system message → cache hits across same-day sessions.

## 10. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| SQL injection / write via `query_database` | Med | High | Parser-based gate (sqlglot); reject DML/DDL at AST level; statement timeout; read-only DB role |
| Schema drift between SCHEMA.md and DB | Low | Med | Alembic post-upgrade hook is the only writer; on mismatch, fail closed with `coverage_gap` |
| Agent infinite-drills (chasing a non-finding) | Med | Med | Tool-call cap (60) + per-question drill cap (8 calls/question); prompt guidance to give up |
| Journal grows unbounded in OpenClaw memory | Low | Low | Dreaming pass scores recall + diversity; disproved/stale entries naturally decay. No custom archival needed. |
| OpenClaw memory plugin unavailable / misconfigured | Low | Med | Phase A validation gate; if down, fall back to in-session-only journaling (entries live for one session only — degraded but functional) |
| Doc retrieval recall is poor | Med | High | Phase B validation gate; fall back to `query_database`-only flow if recall@8 < 0.7 |
| Cost blowup | Med | Med | Wall budget + tool cap are hard ceilings; insight count reduced; prompt caching |
| Frontend breaks on new ChartSpec shapes | Low | Med | `build_chart` validates encoding compatibility; `InsightChart.tsx` already supports 16 types |

## 11. Open Questions (for stakeholders)

1. **Doc retrieval source priority.** Phase B has 8K EDGAR + 4K permits. Do we also want news / Aterio archive in scope, or punt? *(Recommend: scope to EDGAR + permits for V2; news is V3.)*
2. **Journal visibility.** Surface to the user as a "Tracked questions" sidebar (Phase D), or keep agent-internal? *(Recommend: surface via `GET /api/insights/open-questions`, accepting the dreaming-delay tradeoff for entries not yet promoted to `MEMORY.md`.)*
3. **Reflection step.** Mid-loop the agent calls `update_memory` per insight. OpenClaw's nightly dreaming pass already does end-of-day consolidation (promotes durable entries, scores recall). Do we *also* want an explicit end-of-session reflection LLM call before dreaming runs? *(Recommend: skip for V2 — let dreaming do it; revisit if entries take too long to surface.)*
4. **Multi-tenant.** This spec assumes single-tenant. If we add per-user workspaces, OpenClaw memory is already namespaced per agent; we'd just instantiate one OpenClaw agent per user. *(Out of scope for V2.)*
5. **Manual hypothesis injection.** Should the user be able to type "look into Crusoe Wyoming" and have it open a new journal entry? *(Yes — V2 honours `focus` param by calling `update_memory(category="open_questions", fact="q_<slug> | watching | medium | <focus>")` before the loop runs.)*

## 12. Out of Scope

- Real-time streaming insights (current SSE flow stays).
- Multi-tenant workspace isolation.
- Insight scheduling / proactive alerts (separate `cron`-driven mode exists in v1; carries over unchanged).
- Frontend redesign beyond the Tracked Questions sidebar.
- Replacing OpenClaw as the gateway. The model behind it can change; the gateway stays.

## 13. Success Criteria

V2 is shippable when:
- ≥80% of insights cite either a `query_database` row or a `search_documents` passage that was *not* in the prior FactPack equivalent.
- ≥50% of charts use a non-bar type (stacked / grouped / line / treemap / etc.) when the claim warrants it (judged on the 10-scenario golden set).
- ≥30% of sessions advance ≥1 prior journal entry (verified by `update_memory` calls referencing an `id` returned by `memory_search` at session start). Proves the journal is load-bearing.
- p95 wall-clock ≤ 900s; p50 ≤ 480s.
- Manual rubric on golden set: V2 beats V1 on ≥7/10 scenarios for "specificity + actionability."

---

**Appendix A — File touch list (Phase C)**

| File | Action |
|---|---|
| `backend/agents/insights/orchestrator.py` | Drop bootstrap phase; collapse to single-phase agent loop. Delete `_chart_from_supporting_rows`. |
| `backend/agents/insights/hypothesizer.py` | Delete after Phase D. |
| `backend/agents/insights/agentic_synthesis.py` | Replace `user_pack` with workspace pointers; gate on `version`. |
| `backend/agents/insights/prompts/synthesis_rules.md` | Keep for v1; new file `synthesis_rules_v2.md`. |
| `backend/agents/insights/tools/registry.py` | Register `read_workspace`, `search_documents`, `build_chart`; update `persist_insight` shape. (No custom journal tool — agent uses OpenClaw native `update_memory` / `memory_search`.) |
| `backend/agents/insights/tools/sql_gate.py` | Harden — parser-based. |
| `backend/agents/insights/tools/build_chart.py` | New. |
| `backend/agents/insights/tools/search_documents.py` | New. |
| `backend/agents/insights/tools/read_workspace.py` | New. |
| `backend/scripts/refresh_schema_doc.py` | New. |
| `backend/scripts/refresh_freshness_doc.py` | New. |
| `backend/alembic/env.py` | Post-upgrade hook → `refresh_schema_doc.py`. |
| `backend/alembic/versions/017_*.py` | New: `edgar_passages` + `permit_passages` (B.1, BM25); add `embedding` column later in B.2 if needed. |
| `backend/routers/insights.py` | New route: `GET /api/insights/open-questions` parses `.openclaw/workspace/MEMORY.md`. |
| `frontend/src/components/tabs/ai-insights/AIInsightsTab.tsx` | Add Tracked Questions sidebar (Phase D), polls the new route. |
| `frontend/src/components/tabs/ai-insights/InsightChart.tsx` | No change (renders any 16-type ChartSpec). |
