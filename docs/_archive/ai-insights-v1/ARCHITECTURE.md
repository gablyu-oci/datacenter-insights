# ARCHITECTURE — AI Insights Tab
**Owner:** Architect · **Stakeholder:** the user (via PM)
**Status:** Draft v0.1 · **Date:** 2026-05-04
**Cross-refs:** [`./PRD.md`](./PRD.md) · [`./RESEARCH.md`](./RESEARCH.md) · [`./SKILL_CONVERSION.md`](./SKILL_CONVERSION.md) · [`./UX.md`](./UX.md) · [`./TASKS.md`](./TASKS.md)
**Parent PRD:** [`/strategic-insights-tool/PRD.md`](../../PRD.md)

> Planning document. Interface signatures, schema sketches, and pseudocode only — no working classes, route bodies, or React components. All concrete code lands in implementation tickets in `TASKS.md`.

---

## A1. Overview & system context

### A1.1 What is being added
A 10th frontend tab (`AI Insights`) plus a single new FastAPI router (`/api/insights`) and one new agent module tree (`backend/agents/insights/`). Everything else — DB, LlmClient, the 9 existing tabs, the 22 existing routers — is reused untouched.

### A1.2 Context diagram (ASCII)

```
                          ┌──────────────────────────────────────────────┐
                          │   Browser (frontend/src)                     │
                          │                                              │
                          │   AIInsightsTab.tsx                          │
                          │     ├─ SessionRunner    (POST /sessions SSE) │
                          │     ├─ InsightCard[]    (consume SSE events) │
                          │     │     └─ InsightChart (ChartSpec v1)     │
                          │     ├─ InsightChatDock  (V2 — POST /chat)    │
                          │     └─ insights/sse.ts  (Last-Event-ID)      │
                          └──────────────────────┬───────────────────────┘
                                                 │ text/event-stream
                                                 ▼
   ┌──────────────────────────────────────────────────────────────────────────────┐
   │ FastAPI · backend/routers/insights.py                                        │
   │   POST /api/insights/sessions          (SSE stream of typed events)          │
   │   GET  /api/insights/sessions/{id}     (status snapshot)                     │
   │   GET  /api/insights/sessions/{id}/insights                                  │
   │   GET  /api/insights/insights/{id}                                           │
   │   POST /api/insights/insights/{id}/chat (V2, SSE)                            │
   │   GET  /api/insights/insights/{id}/chat                                      │
   │   GET  /api/insights/insights/{id}/citations                                 │
   │   POST /api/insights/sessions/{id}/cancel                                    │
   │   POST /api/insights/schedules         (V3)                                  │
   └────────────────┬─────────────────────────────────────────────────────────────┘
                    │ in-process
                    ▼
   ┌──────────────────────────────────────────────────────────────────────────────┐
   │ backend/agents/insights/orchestrator.py · InsightOrchestrator                │
   │  ┌────────────────────────────────────────────────────────────────────────┐  │
   │  │ tool_loop.py · ToolLoopDriver  (12 turns / 4-wide / 120 s budget)      │  │
   │  │                                                                        │  │
   │  │   reuse → backend/llm/client.py · LlmClient.reason() / .embed()        │  │
   │  │                                                                        │  │
   │  │   tool dispatch → tools/{db,router_call,chart_data,                    │  │
   │  │                          web_search,skill,emit}.py                     │  │
   │  └────────────────────────────────────────────────────────────────────────┘  │
   │                                                                              │
   │   safety/sql_gate.py    ── sqlglot AST allowlist                             │
   │   skills/_registry.py   ── 15 converted skill tools (V2 full)                │
   │   specs/chart_spec.py   ── Pydantic ChartSpec v1                             │
   │   specs/sse_events.py   ── typed event payloads                              │
   │   dedup/novelty.py      ── embedding cosine + Jaccard                        │
   │   persistence/models.py ── SQLAlchemy: insight_session, insight, chart, ...  │
   └────────────┬─────────────────────────────────────────────────┬──────────────-┘
                │                                                 │
                ▼                                                 ▼
        ┌────────────────────┐                   ┌─────────────────────────────────┐
        │ OCI Llama Stack    │                   │ Postgres                        │
        │ /v1/chat/completions│                  │  - existing tables (read-only   │
        │ /v1/embeddings     │                   │    role `ai_agent`)             │
        │ instance principal │                   │  - new: insight_session,        │
        └────────────────────┘                   │    insight, chart, citation,    │
                                                 │    agent_message,               │
                                                 │    tool_call_log,               │
                                                 │    skill_invocation,            │
        ┌────────────────────┐                   │    skill_rag_chunk (pgvector)   │
        │ Tavily / Brave     │ ◀─── V2 only ───▶ │    insight_schedule (V3)        │
        │ web search APIs    │                   └─────────────────────────────────┘
        └────────────────────┘
```

### A1.3 Trust boundary summary

| Boundary | Crosses | Protection |
|---|---|---|
| Browser ↔ FastAPI | HTTPS, no auth (V1 internal, per parent PRD §8 D5) | CORS + same-origin in dev |
| FastAPI ↔ LlamaStack | OCI VCN, instance principal | No API key in app config |
| FastAPI ↔ Postgres (agent role) | Local socket / VCN | `ai_agent` role: SELECT only, `statement_timeout=5s`, `CONNECTION LIMIT 4` |
| FastAPI ↔ Postgres (app role) | Local socket / VCN | App role keeps full grants on the new `insight_*` tables (writes those) |
| FastAPI ↔ web-search | HTTPS egress | Tavily primary, Brave fallback; circuit breaker on both |

---

## A2. Backend module layout

```
backend/
├── routers/
│   └── insights.py                     # HTTP surface — sessions, SSE, insight detail, chat, citations
├── agents/
│   └── insights/
│       ├── __init__.py                 # public exports: InsightOrchestrator, build_tools
│       ├── orchestrator.py             # multi-insight session driver; calls ToolLoopDriver per insight
│       ├── tool_loop.py                # OpenAI function-call loop on top of LlmClient.reason()
│       ├── prompts/
│       │   ├── system_base.md          # base system prompt (≤1500 tokens) — tool list, persona, rules
│       │   ├── survey_user.md          # first user turn: "survey the platform"
│       │   ├── hypothesize_user.md     # second user turn: emit candidate hypotheses
│       │   └── verify_user.md          # per-insight user turn: verify + emit
│       ├── tools/
│       │   ├── __init__.py             # build_tools(ctx) -> (openai_specs, dispatch_map)
│       │   ├── db.py                   # query_database (sqlglot gate, row_hash)
│       │   ├── router_call.py          # call_api (allowlist, in-process TestClient)
│       │   ├── chart_data.py           # get_chart_data (tab/chart_id registry)
│       │   ├── web_search.py           # V2 — Tavily/Brave with breaker
│       │   ├── skill.py                # run_skill (registry dispatch)
│       │   └── emit.py                 # emit_chart, emit_citation
│       ├── skills/
│       │   ├── _registry.py            # name → tool-fn / system-fragment / RAG collection
│       │   ├── _context.py             # SkillContext typed shape (capability matrix)
│       │   ├── programmatic_eda/
│       │   │   ├── __init__.py
│       │   │   ├── tools.py            # ports of scripts/data_overview.py, null_profiler.py, ...
│       │   │   ├── system_fragment.md  # ≤800-token Process distillation
│       │   │   └── rag_chunks.jsonl    # chunked references/ files
│       │   ├── data_quality_audit/...
│       │   ├── time_series_analysis/...
│       │   ├── segmentation_analysis/...
│       │   ├── root_cause_investigation/...
│       │   ├── business_metrics_calculator/...
│       │   ├── insight_synthesis/...
│       │   ├── executive_summary_generator/...
│       │   ├── visualization_builder/...           # prompt-only, no script port
│       │   ├── data_narrative_builder/...          # synthesised — see SKILL_CONVERSION S4.1
│       │   ├── impact_quantification/...
│       │   ├── technical_to_business_translator/...
│       │   ├── cohort_analysis/...                 # V2
│       │   ├── methodology_explainer/...           # V2
│       │   └── peer_review_template/...            # V2
│       ├── specs/
│       │   ├── chart_spec.py           # ChartSpec v1 (Pydantic)
│       │   └── sse_events.py           # typed SSE event Pydantic models
│       ├── safety/
│       │   ├── sql_gate.py             # sqlglot AST allowlist
│       │   └── citation_gate.py        # rationale ⊂ snippet substring check (V2)
│       ├── dedup/
│       │   └── novelty.py              # Jaccard + cosine-similarity dedup
│       ├── persistence/
│       │   ├── models.py               # SQLAlchemy: insight_session, insight, chart, ...
│       │   └── replay.py               # per-session SSE event ring buffer for Last-Event-ID
│       ├── observability/
│       │   ├── logging.py              # structured per-event JSON logger
│       │   └── trace.py                # tool span helpers (writes to tool_call_log)
│       └── schedules/                  # V3
│           └── runner.py               # cron entry; reuses runner.py framework
└── alembic/versions/
    └── 2026_05_xx_add_ai_insights_tables.py
```

| File | One-sentence purpose |
|---|---|
| `routers/insights.py` | HTTP surface — sessions create/list/get, SSE stream, insight detail, chat thread (V2), citation list, cancel. |
| `agents/insights/orchestrator.py` | Multi-insight session driver: bootstrap → hypothesis → per-insight ToolLoopDriver → emit → dedup. |
| `agents/insights/tool_loop.py` | OpenAI-style function-call loop on top of `LlmClient.reason()` with caps + parallel dispatch. |
| `agents/insights/tools/db.py` | `query_database(sql, max_rows=10000)` — sqlglot gate, transaction-scoped timeout, row_hash. |
| `agents/insights/tools/router_call.py` | `call_api(endpoint, method, params)` — endpoint allowlist; in-process app injection. |
| `agents/insights/tools/chart_data.py` | `get_chart_data(tab, chart_id)` — pre-registered tab/chart → router-call mapping. |
| `agents/insights/tools/web_search.py` | V2 — `web_search(query, top_k=5)` with Tavily primary, Brave fallback, breaker. |
| `agents/insights/tools/skill.py` | `run_skill(skill_name, inputs)` — registry dispatch + system fragment + RAG retrieval. |
| `agents/insights/tools/emit.py` | `emit_chart(spec)` and `emit_citation(...)` — validate, persist, fire SSE. |
| `agents/insights/skills/_registry.py` | Name → tool-fn / system-fragment path / RAG collection. |
| `agents/insights/specs/chart_spec.py` | Pydantic ChartSpec v1 with discriminator + JSON-Schema export. |
| `agents/insights/specs/sse_events.py` | Typed SSE event payloads (one model per `event:` name). |
| `agents/insights/safety/sql_gate.py` | sqlglot AST allowlist; raises `UnsafeSqlError`. |
| `agents/insights/persistence/models.py` | SQLAlchemy models for the 7 new tables. |
| `agents/insights/dedup/novelty.py` | Jaccard headline + cosine on `text-embedding-3-large`. |

---

## A3. HTTP API contract

All endpoints under prefix `/api/insights`. **No auth in V1** (matches parent PRD §8 D5). Rate-limit policy uniform: per-IP token bucket of 60 req/min on the FastAPI side (existing `slowapi` pattern in routers reused).

### A3.1 Endpoint table

| # | Method | Path | Body / Query | Response | Errors | Rate |
|---|---|---|---|---|---|---|
| 1 | POST | `/api/insights/sessions` | `{focus?: str, max_insights?: int=7, version: "v1"\|"v2"}` | `text/event-stream` (SSE — see A5) | 400 invalid focus; 503 LlamaStack down; 429 rate-limited | 6/min |
| 2 | GET | `/api/insights/sessions/{id}` | — | `{id, status: "running"\|"complete"\|"failed"\|"cancelled", started_at, finished_at, insights_count, model, errors[]}` | 404 | 60/min |
| 3 | GET | `/api/insights/sessions/{id}/insights` | `?status=complete&limit=10&offset=0` | `{items: Insight[], total}` | 404 | 60/min |
| 4 | GET | `/api/insights/insights/{id}` | — | `Insight` (full body — see A7) | 404 | 60/min |
| 5 | POST | `/api/insights/insights/{id}/chat` (V2) | `{message: str, last_event_id?: str}` | `text/event-stream` (SSE — token, tool_call, chart, citation, done) | 404; 409 if insight not yet complete; 503 | 30/min |
| 6 | GET | `/api/insights/insights/{id}/chat` | `?limit=50&before=msg_id` | `{messages: AgentMessage[]}` | 404 | 60/min |
| 7 | GET | `/api/insights/insights/{id}/citations` | — | `{items: Citation[]}` | 404 | 60/min |
| 8 | POST | `/api/insights/sessions/{id}/cancel` | — | `{ok: true, status: "cancelled"}` | 404; 409 already terminal | 30/min |
| 9 | POST | `/api/insights/schedules` (V3) | `{cron: str, focus?, max_insights?, enabled: bool}` | `Schedule` | 400 cron parse | 30/min |
| 10 | GET | `/api/insights/schedules` (V3) | — | `{items: Schedule[]}` | — | 60/min |

### A3.2 SSE resume contract (endpoint 1, 5)
- Server emits `id: <monotonic>` on every event so the browser's `EventSource` populates `Last-Event-ID` automatically.
- On reconnect, server replays from `replay.py` ring buffer (capacity 500 events / session).
- If the session has terminated, the buffer is held for 5 minutes after `session_complete`, then GC'd.
- Heartbeat: `event: ping\ndata: {}` every 15 s to defeat proxy idle-timeouts.

### A3.3 Cancellation
Server keeps an `asyncio.Event` per session. POST cancel sets the event; the orchestrator checks at every loop turn and at every tool dispatch boundary; on trip it emits `event: error code=cancelled` then `session_complete` and tears down.

---

## A4. ChartSpec v1 (interface only)

### A4.1 Pydantic interface sketch

```python
# backend/agents/insights/specs/chart_spec.py  -- INTERFACE SKETCH, NOT IMPL
from typing import Literal, Optional, Annotated
from pydantic import BaseModel, Field

ChartType = Literal[
    "line", "bar", "stacked_bar", "grouped_bar",
    "area", "stacked_area",
    "scatter", "pie",
    "sparkline", "kpi_tile",
]
# Maps -> Recharts only. Map-shaped charts (heatmap geo, choropleth) explicitly
# excluded in V1; visualization-builder skill prompt enumerates this closed set.

class DataSourceSpec(BaseModel):
    kind: Literal["db_query", "router_call", "chart_data"]
    sql: Optional[str]
    endpoint: Optional[str]
    params: Optional[dict]
    tab_chart: Optional[dict]          # {"tab": str, "chart_id": str}
    rows: int
    retrieved_at: str                  # ISO8601
    row_hash: str                      # sha256(canonical_sort(rows))

class XEncoding(BaseModel):
    field: str
    type: Literal["category", "time", "quantitative"]
    label: Optional[str]
    tick_format: Optional[str]         # e.g. "%b %Y", "0.0a"

class YEncoding(BaseModel):
    field: str
    type: Literal["quantitative"]
    label: Optional[str]
    tick_format: Optional[str]

class Encoding(BaseModel):
    x: XEncoding
    y: YEncoding
    series: Optional[dict]             # {"field": str}
    color: Optional[dict]              # {"field"?: str, "scheme": "categorical"|"sequential"}
    size: Optional[dict]               # for scatter only

class Annotation(BaseModel):
    type: Literal["line", "band", "point"]
    value: str | float
    label: str

class Styling(BaseModel):
    palette: Literal["oci_brand"] = "oci_brand"
    y_unit: Optional[Literal["GW", "MW", "USD", "count", "%"]]
    y_precision: Optional[int]

class ChartSpec(BaseModel):
    chart_id: str                                         # stable per session
    chart_type: ChartType
    title: str
    subtitle: Optional[str]
    data_source: DataSourceSpec
    data: list[dict]                                      # inline rows; <=500
    encoding: Encoding
    annotations: Optional[list[Annotation]] = None
    styling: Optional[Styling] = None

# Validator constants:
MAX_ROWS_PER_CHART = 500
MAX_SERIES = 8
JSON_SCHEMA_PATH = "backend/agents/insights/specs/chart_spec.schema.json"
```

### A4.2 Constraints (server-enforced at `emit_chart`)

| Constraint | Limit | On violation |
|---|---|---|
| `len(data)` | ≤ 500 rows | `tool_error: chart_too_large` — agent must aggregate |
| Distinct values of `encoding.series.field` | ≤ 8 | `tool_error: too_many_series` |
| `data_source.row_hash` matches recomputed hash on `data` | exact | `tool_error: row_hash_mismatch` (P0 incident if logged repeatedly) |
| `chart_type` ∈ enum | discriminator | Pydantic strict reject |
| Inline-only — no remote refs | n/a | reject |

**Rationale for excluding maps in V1:** Recharts has no map primitive; the existing Power-Map tab uses Leaflet. Adding a map-emit path would force a second renderer family. Deferred to V3 per PRD §6.2 row 26.

---

## A5. SSE event taxonomy

Each event has a stable `event:` name and a JSON `data:` payload. Server emits monotonic `id:` lines for `Last-Event-ID` resume.

| Event name | When | Payload sketch | Frontend consumer | V-phase |
|---|---|---|---|---|
| `session_started` | First byte after orchestrator starts | `{session_id, model, started_at, max_insights}` | `SessionRunner` flips state to running | V1 |
| `surveying` | After bootstrap `call_api` survey, before any insight | `{session_id, candidates_seen: int, message: "Surveying the platform…"}` | `StreamingSkeleton` shows preamble | V1 |
| `insight_started` | Orchestrator picks a candidate | `{insight_id, session_id, index, headline_draft?: str}` | `InsightCard` mounts skeleton | V1 |
| `token` | LLM streams body / headline content | `{insight_id, field: "body"\|"headline", delta: str}` | `InsightCard` appends to body in place | V1 |
| `reasoning_step` | (optional) high-level step name to drive a stepper UI | `{insight_id, step: "EDA"\|"hypothesize"\|"verify"\|"emit"}` | `InsightHeader` step pill | V1 |
| `tool_call` | Loop driver dispatches a tool | `{insight_id, tool_call_id, tool_name, args_truncated: str(<=200), started_at}` | `ToolTrace` appends row | V1 |
| `tool_result` | Tool returns | `{tool_call_id, ok: bool, row_count?: int, latency_ms, error_code?}` | `ToolTrace` updates row | V1 |
| `chart` | `emit_chart` validated and persisted | `{insight_id, chart: ChartSpec}` | `InsightChartFrame` mounts `<InsightChart>` | V1 |
| `citation` | `emit_citation` validated | `{insight_id, citation: WebCitation}` | `InsightCitations` appends | V2 |
| `insight_complete` | Orchestrator finalizes one insight | `{insight_id, headline, confidence, materiality, skills_run[], low_external_support?: bool}` | `InsightCard` switches to final state | V1 |
| `session_complete` | All insights emitted (or budget tripped) | `{session_id, insights_emitted, duration_ms, budget_status: "ok"\|"clipped"}` | `SessionRunner` finalizes | V1 |
| `error` | Recoverable or terminal error | `{insight_id?, code, message, retryable: bool}` | `ErrorState` for terminal; toast + degrade for per-insight | V1 |
| `ping` | Heartbeat every 15 s | `{}` | Ignored (keepalive only) | V1 |

### A5.1 Last-Event-ID resume

```
GET /api/insights/sessions/{id}    Accept: text/event-stream
Last-Event-ID: 73
                ↓
Server: "look up ring-buffer for session id, replay 74…N"
```

Ring buffer is in-process Python deque (≤500 events / session). Across processes (multi-worker uvicorn) it would need Redis — out of V1 scope; we run a single uvicorn worker in dev/dogfood per existing deploy.

### A5.2 Ordering & interleaving

V1: events for one insight are strictly serial; insights themselves are sequential, so no interleaving. V2 (parallel sub-agents): insights interleave; the `insight_id` is the demultiplex key on the client.

---

## A6. Tool implementations (interfaces only)

Each of the 7 PRD tools below is exposed as an **OpenAI tools-schema entry** in the loop driver's tool list and dispatched by `tool_dispatch[name](args, ctx)`.

### A6.1 `query_database`

```jsonc
// OpenAI tool spec sketch
{
  "type": "function",
  "function": {
    "name": "query_database",
    "description": "Run a single read-only SELECT against the strategic-insights Postgres. Returns rows as JSON.",
    "parameters": {
      "type": "object",
      "properties": {
        "sql": {"type": "string", "description": "Single SELECT statement, Postgres dialect."},
        "max_rows": {"type": "integer", "default": 10000, "maximum": 10000}
      },
      "required": ["sql"]
    }
  }
}
```

```python
# Python signature
async def query_database(
    *, sql: str, max_rows: int = 10_000, ctx: ToolCtx
) -> dict:  # {"rows": list[dict], "row_count": int, "row_hash": str, "schema": list[{name,type}]}
    ...
```

Safety gate path: `safety/sql_gate.py::gate(sql, allowed_tables)` — must succeed before exec. Tx scope: `BEGIN; SET LOCAL statement_timeout=5000; ...; ROLLBACK`. Connection pool: separate pool bound to `ai_agent` role (see RESEARCH §8.2 layer 1).

### A6.2 `call_api`

```jsonc
{
  "type": "function",
  "function": {
    "name": "call_api",
    "description": "Call a registered internal endpoint. Returns the JSON body.",
    "parameters": {
      "type": "object",
      "properties": {
        "endpoint": {"type": "string", "description": "Path, e.g. '/api/triangulation/l2'"},
        "method":   {"type": "string", "enum": ["GET","POST"], "default": "GET"},
        "params":   {"type": "object", "default": {}}
      },
      "required": ["endpoint"]
    }
  }
}
```

```python
async def call_api(*, endpoint: str, method: str = "GET", params: dict | None = None, ctx: ToolCtx) -> dict:
    ...
```

**Endpoint allowlist:** generated at session start by reading the registered routes from `backend/main.py` (the 22 imports in lines 19–40). Initial allowlist excludes write paths (e.g. `agent_router` POSTs that mutate). Stored in `tools/router_call.py::ALLOWED_ENDPOINTS: set[tuple[method,path]]`.

**Why in-process (not real HTTP loopback):** (a) loopback adds ~10 ms × 8 bootstrap calls of latency for no value; (b) avoids round-trip auth/CORS/header concerns; (c) keeps the call inside the same DB transaction context if needed; (d) `httpx.AsyncClient(transport=ASGITransport(app))` (a.k.a. starlette `TestClient` in async form) is the documented pattern for in-process calls. **Document explicitly** in code that this is *not* a real HTTP hop.

### A6.3 `get_chart_data`

```jsonc
{"type":"function","function":{"name":"get_chart_data",
  "description":"Fetch the data behind a known chart on an existing tab.",
  "parameters":{"type":"object","required":["tab","chart_id"],
    "properties":{"tab":{"type":"string"},"chart_id":{"type":"string"}}}}}
```

```python
async def get_chart_data(*, tab: str, chart_id: str, ctx: ToolCtx) -> dict:
    ...
```

**Tab × chart registry (concrete):**

| Tab | Known chart_id | Maps to (`call_api` under the hood) |
|---|---|---|
| `power` | `gw_by_company` | `GET /api/power/gw-summary` |
| `power` | `timeseries_by_company` | `GET /api/power/timeseries?days=180` |
| `gpu` | `vendor_share` | `GET /api/gpu/vendor-share` |
| `permits` | `building_recent` | `GET /api/permits/building?days=180` |
| `permits` | `generator_state` | `GET /api/permits/generator/by-state` |
| `triangulation` | `l1_summary` | `GET /api/triangulation/l1` |
| `triangulation` | `l2_implied_gw` | `GET /api/triangulation/l2` |
| `companies` | `top50_by_gw` | `GET /api/companies/top?metric=gw&limit=50` |
| `events` | `recent_8k` | `GET /api/events/recent?source=8k` |
| `anomalies` | `recent` | `GET /api/anomalies/recent` |
| `coverage` | `freshness_by_pillar` | `GET /api/coverage/freshness` |
| `sites` | `by_state` | `GET /api/sites/by-state` |

Registry is one Python dict; expanding to all 22 routers is incremental.

### A6.4 `web_search` (V2 only)

```jsonc
{"type":"function","function":{"name":"web_search",
  "description":"Search the public web. Returns up to top_k results.",
  "parameters":{"type":"object","required":["query"],
    "properties":{"query":{"type":"string"},"top_k":{"type":"integer","default":5,"maximum":10}}}}}
```

```python
async def web_search(*, query: str, top_k: int = 5, ctx: ToolCtx) -> dict:
    # returns {"results": [{title,url,snippet,retrieved_at}], "provider": "tavily"|"brave"}
    ...
```

**Provider policy (V2):**
- Primary: Tavily (timeout 8 s, retry 1).
- Fallback: Brave (timeout 8 s, retry 1).
- Circuit breaker: 5 consecutive failures on either provider → flip provider for the remainder of the session.
- Snippet truncation: ≤280 chars before persisting.
- Per-session cap: 8 calls (PRD §5.3).
- Agree/disagree judge: separate `gpt-5.4-mini` low-effort call after retrieval; emits one `tag_citation(url, tag, rationale)` tool call per result; rationale must be substring of snippet (gated in `safety/citation_gate.py`).

### A6.5 `run_skill`

```jsonc
{"type":"function","function":{"name":"run_skill",
  "description":"Invoke a converted analytics skill. The dispatcher injects the skill's process fragment + RAG chunks for the next reasoning turn only.",
  "parameters":{"type":"object","required":["skill_name","inputs"],
    "properties":{"skill_name":{"type":"string","enum":[
      "programmatic_eda","data_quality_audit","root_cause_investigation","time_series_analysis",
      "segmentation_analysis","business_metrics_calculator","insight_synthesis",
      "executive_summary_generator","visualization_builder","data_narrative_builder",
      "impact_quantification","technical_to_business_translator",
      "cohort_analysis","methodology_explainer","peer_review_template"]},
    "inputs":{"type":"object"}}}}}
```

```python
async def run_skill(*, skill_name: str, inputs: dict, ctx: ToolCtx) -> dict:
    # 1. Look up registry: get tool_fn, fragment_path, rag_collection
    # 2. Optionally call deterministic Python (e.g. programmatic_eda runs df.describe())
    # 3. Retrieve top-3 RAG chunks (cosine search on skill_rag_chunk filtered by skill_name)
    # 4. Return structured JSON; orchestrator/tool_loop arranges system fragment for next turn
    ...
```

Safety: enum-restricted skill_name (no arbitrary skill loading). The next turn sees an injected ephemeral system message — never pinned (see A9).

### A6.6 `emit_chart`

```jsonc
{"type":"function","function":{"name":"emit_chart",
  "description":"Emit a final chart for the current insight. Validated against ChartSpec v1.",
  "parameters":{"$ref":"backend/agents/insights/specs/chart_spec.schema.json"}}}
```

```python
async def emit_chart(*, spec: ChartSpec, ctx: ToolCtx) -> dict:
    # 1. Pydantic strict validate
    # 2. Re-compute row_hash from spec.data; reject on mismatch with data_source.row_hash
    # 3. Persist Chart row + write SSE event(chart, ...)
    # 4. Return {chart_id, ok}
    ...
```

### A6.7 `emit_citation` (V2)

```jsonc
{"type":"function","function":{"name":"emit_citation",
  "description":"Emit a web citation for the current insight.",
  "parameters":{"type":"object",
    "required":["url","title","snippet","agree_or_disagree","rationale","search_query"],
    "properties":{"url":{"type":"string"},"title":{"type":"string"},
      "snippet":{"type":"string","maxLength":280},
      "agree_or_disagree":{"type":"string","enum":["agree","disagree","context"]},
      "rationale":{"type":"string"},
      "search_query":{"type":"string"}}}}}
```

```python
async def emit_citation(*, url, title, snippet, agree_or_disagree, rationale, search_query, ctx) -> dict:
    # safety/citation_gate.py: rationale must be substring of snippet (case-insensitive,
    # whitespace-normalized). For agree/disagree, snippet must contain a number (regex).
    # On fail: tool_error citation_unsupported_rationale.
    ...
```

---

## A7. Data model (Postgres)

ER (text):

```
insight_session 1 ── n insight ── 1 chart
insight_session 1 ── n agent_message
insight 1 ── n citation                (V2)
insight 1 ── n agent_message            (per-insight chat thread)
insight_session 1 ── n tool_call_log
insight_session 1 ── n skill_invocation
insight (or session) 1 ── n skill_rag_chunk        (vector store, per skill)
insight_schedule 1 ── n insight_session             (V3)
```

### A7.1 Table summaries

`insight_session`
| Column | Type | Idx | FK |
|---|---|---|---|
| id (PK) | uuid | pk | — |
| status | text | btree | — |
| started_at | timestamptz | btree | — |
| finished_at | timestamptz | — | — |
| model | text | — | — |
| focus | text | — | — |
| max_insights | int | — | — |
| version | text | — | — |
| insights_emitted | int | — | — |
| duration_ms | int | — | — |
| budget_status | text | — | — |
| created_by | text | — | — |
| schedule_id | uuid | btree | insight_schedule.id (V3) |

`insight`
| Column | Type | Idx | FK |
|---|---|---|---|
| id (PK) | uuid | pk | — |
| session_id | uuid | btree | insight_session.id |
| index | int | — | — |
| headline | text | — | — |
| body | text | — | — |
| confidence | text | — | — |
| materiality | text | — | — |
| skills_run | jsonb | gin | — |
| low_external_support | bool | — | — |
| headline_embedding | vector(3072) | ivfflat | — (pgvector) |
| created_at | timestamptz | btree | — |

`chart`
| Column | Type | Idx | FK |
|---|---|---|---|
| id (PK) | text (chart_id) | pk | — |
| insight_id | uuid | btree | insight.id |
| spec | jsonb | — | — |
| data_source | jsonb | — | — |
| row_hash | text | — | — |
| created_at | timestamptz | — | — |

`citation` (V2)
| Column | Type | Idx | FK |
|---|---|---|---|
| id (PK) | uuid | pk | — |
| insight_id | uuid | btree | insight.id |
| url | text | btree | — |
| title | text | — | — |
| snippet | text | — | — |
| agree_or_disagree | text | — | — |
| rationale | text | — | — |
| search_query | text | — | — |
| retrieved_at | timestamptz | — | — |
| provider | text | — | — |

`agent_message`
| Column | Type | Idx | FK |
|---|---|---|---|
| id (PK) | uuid | pk | — |
| session_id | uuid | btree | insight_session.id |
| insight_id | uuid (nullable) | btree | insight.id |
| role | text | — | (assistant/user/tool/system) |
| content | text | — | — |
| tool_calls | jsonb | — | — |
| tool_call_id | text | — | — |
| created_at | timestamptz | — | — |

`tool_call_log`
| Column | Type | Idx | FK |
|---|---|---|---|
| id (PK) | uuid | pk | — |
| session_id | uuid | btree | insight_session.id |
| insight_id | uuid (nullable) | btree | insight.id |
| tool_name | text | btree | — |
| args | jsonb | — | — |
| ok | bool | — | — |
| error_code | text | — | — |
| started_at | timestamptz | — | — |
| latency_ms | int | — | — |
| token_estimate | int | — | — |

`skill_invocation`
| Column | Type | Idx | FK |
|---|---|---|---|
| id (PK) | uuid | pk | — |
| insight_id | uuid | btree | insight.id |
| skill_name | text | btree | — |
| inputs_hash | text | — | — |
| outputs | jsonb | — | — |
| latency_ms | int | — | — |
| created_at | timestamptz | — | — |

`skill_rag_chunk` (single table, filtered by skill_name — see SKILL_CONVERSION §S6)
| Column | Type | Idx | FK |
|---|---|---|---|
| id (PK) | uuid | pk | — |
| skill_name | text | btree | — |
| source_path | text | — | — |
| chunk_index | int | — | — |
| text | text | — | — |
| embedding | vector(3072) | ivfflat | — |
| token_count | int | — | — |
| content_hash | text | — | — |

`insight_schedule` (V3)
| Column | Type | Idx | FK |
|---|---|---|---|
| id (PK) | uuid | pk | — |
| cron | text | — | — |
| focus | text | — | — |
| max_insights | int | — | — |
| enabled | bool | — | — |
| last_run_session_id | uuid | — | insight_session.id |
| created_at | timestamptz | — | — |

Migration: alembic revision under `backend/alembic/versions/2026_05_xx_add_ai_insights_tables.py`. pgvector extension assumed already enabled (used elsewhere) — if not, the same revision runs `CREATE EXTENSION IF NOT EXISTS vector`.

---

## A8. Orchestration & control flow

### A8.1 V1 sequential flow (pseudocode, ≤30 lines)

```
async def run_session(req):
  emit('session_started')
  ctx = SessionCtx(session_id=new_uuid(), focus=req.focus, ...)
  bootstrap = await call_api_parallel(SURVEY_ENDPOINTS)        # 8 calls, parallel
  emit('surveying', candidates_seen=summarize(bootstrap))

  # ToolLoopDriver turn 1: EDA + hypothesize
  candidates = await tool_loop.run(
    system=load_base_system(), user=HYPOTHESIZE_PROMPT.format(bootstrap=bootstrap),
    tools=AGENT_TOOLS, caps=ToolCaps(max_calls=8, max_turns=4))
  candidates = filter_novel(candidates, novelty_threshold_cosine=0.85)
  candidates = candidates[: req.max_insights]                  # rank by materiality+novelty

  for i, hyp in enumerate(candidates):
    if cancelled: break
    emit('insight_started', insight_id=ins_id(i), index=i)
    result = await tool_loop.run(
      system=load_base_system(), user=VERIFY_PROMPT.format(hyp=hyp, ctx=ctx),
      tools=AGENT_TOOLS, caps=ToolCaps(max_calls=10, max_turns=8))
    if result.emitted_chart_ok and result.headline_unique(ctx.emitted_headlines):
      ctx.persist_insight(result)
      emit('insight_complete', ...)

  emit('session_complete', insights_emitted=len(ctx.emitted), duration_ms=ctx.elapsed)
```

### A8.2 Parallelism deltas

| Phase | V1 | V2 |
|---|---|---|
| Bootstrap survey | parallel up to 4-wide (already) | same |
| Hypothesis pass | sequential single loop | same |
| Per-insight verify | **sequential** across insights, parallel-tools-within-turn | **parallel sub-agents** — one task per insight, fan-out N=5, joined at session_complete |
| SSE multiplex | linear (one at a time) | demuxed by `insight_id` |

Forward-compat hook for V2: tool-loop driver returns from `run()` early per insight; orchestrator already holds a list — V2 just swaps the `for` for `asyncio.gather`.

---

## A9. Skill registry & system-prompt composition

### A9.1 The risk
If all 12 V1 skills' Process fragments are pinned in the system prompt, system-side context blows past ~3 K tokens just on dormant skills, leaving little room for tool result transcripts. Empirically the orchestrator sees ~12 turns × ≤4 tool results — at ~1 K tokens/result that's 48 K tokens of *dynamic* context already. Don't add static fat.

### A9.2 Strategy

| Layer | Token budget | Loaded when |
|---|---|---|
| Base system prompt (`prompts/system_base.md`) | ≤1500 tokens | Always |
| Tool list (OpenAI function specs only — names + 1-line description) | ~600 tokens | Always |
| Skill `description` (one-line per skill, the SKILL.md frontmatter) | ~200 tokens | Always (helps the model pick the right skill) |
| **Skill Process fragment** | ≤800 tokens | **Only when `run_skill(skill_name=X)` is called** |
| RAG chunks (top-3, ≤500 tokens each) | ≤1500 tokens | Same as fragment |

### A9.3 Composition rule (ephemeral injection)

When the agent calls `run_skill(skill_name=X)`, the dispatcher:

1. Records the `tool_call_id`.
2. Returns the deterministic preprocessing JSON as the *tool result*.
3. **Injects an ephemeral system-shaped message immediately after the tool result** — using OpenAI's allowance for multiple system messages mid-conversation: `{"role":"system", "content": "[skill:X process]\n<800-token distillation>\n\n[references]\n<RAG chunks>"}`.
4. The next assistant turn sees this injection in context.
5. **The injection is NOT pinned across turns:** when the agent makes its *next-but-one* call, the dispatcher omits the injection. (Gist: a turn-bounded system message, not a sticky one.)

OpenAI Chat Completions accepts multiple `system` messages. Per RESEARCH §12 there's a small risk that `gpt-5.4` treats a mid-conversation system message as a user message. Mitigation: a single calibration test in Sprint 1 — assert the model honours the injection by prefixing the fragment with `"You are now operating with skill [X] guidance:"` and observing the next turn references that guidance.

### A9.4 Fallback if mid-conversation system messages are ignored
Fold the fragment into the *user-shaped* turn that follows: `{"role":"user", "content": f"<<skill-process>>\n{fragment}\n<<end-skill-process>>\n\n{actual_user_prompt}"}`. Log which mode is in use; observable via `skill_invocation.outputs.fragment_mode`.

---

## A10. Safety & guardrails

### A10.1 SQL AST gate (sqlglot)

| Allowed | Disallowed |
|---|---|
| `SELECT` (root only) | `INSERT`, `UPDATE`, `DELETE`, `MERGE` |
| `WITH` / CTEs (so long as inner is SELECT) | `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `GRANT`, `REVOKE` |
| `JOIN` (INNER/LEFT/RIGHT/FULL) | `COPY`, `dblink`, `lo_import`, `lo_export` |
| Aggregates (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`, `STDDEV`, `VAR_*`) | `pg_sleep`, `pg_read_server_files`, `pg_terminate_backend` |
| Window funcs (`OVER (PARTITION BY ... ORDER BY ...)`) | Multi-statement (`;` between two stmts) |
| String/date functions on the allowlist (`LOWER`, `UPPER`, `COALESCE`, `DATE_TRUNC`, `EXTRACT`, `NOW`, `TO_CHAR`, `CAST`, `LENGTH`) | `pg_*` table refs (any name starting `pg_`); `information_schema.*` (use the snapshot endpoint instead) |
| Tables in the dynamically-discovered allowlist (= `information_schema.tables` filtered to public schemas at session start) | Anything outside the allowlist |
| `LIMIT n` (forced if absent) | `OFFSET 0` exploitation patterns |

Function-call allowlist enforced via `exp.Anonymous` walk; unknown function name → reject. `WITH RECURSIVE` allowed but capped via the `LIMIT` injection.

### A10.2 Tool-loop limits

| Limit | Value | Trip behaviour |
|---|---|---|
| Max loop turns | 12 | `tool_error: turn_budget` → clean session_complete |
| Max parallel tool calls per turn | 4 | extra calls in same turn dropped + logged |
| Total wall-clock budget | 120 s per insight; 480 s per session | budget_status="clipped" |
| Max tool calls per session | 40 (V1) / 80 (V2) | drop & error |
| SSE heartbeat | 15 s | passive |

### A10.3 Hallucination defenses

| Defense | Mechanism |
|---|---|
| Schema discovery snapshot | At session start, snapshot `information_schema.tables` filtered to public schemas; expose to agent as a static tool result so it doesn't have to guess table names (PRD G6) |
| Row-hash | Every chart's `data_source.row_hash` is recomputed from `data` and compared to the persisted hash from the originating tool call (hash kept in `tool_call_log`). Mismatch → reject + P0 incident counter |
| Citation rationale substring | `safety/citation_gate.py` enforces `rationale ⊆ snippet` (case-insensitive, whitespace-normalized) |
| Citation number presence | For `agree`/`disagree`, snippet must contain a number (`\d+\.?\d*\s*(GW\|MW\|%\|\$)`); else downgraded to `context` |
| Novelty dedup | Jaccard ≥ 0.7 on token-normalized headline (intra-session) + cosine ≥ 0.85 on `text-embedding-3-large` of headline+body (cross-session, 30-day window) |
| Peer review (V2) | `peer_review_template` skill called pre-emit per insight; agent self-reviews against {specific, supported, non-trivial, material} and either passes or revises |

### A10.4 Cost & budget

LlamaStack token cost is zero (instance principal). Latency is the cost.

| Knob | V1 | V2 |
|---|---|---|
| `reasoning.effort` (orchestrator) | `medium` | `medium` |
| `reasoning.effort` (judge — agree/disagree) | n/a | `low` |
| `reasoning.effort` (peer_review) | n/a | `low` |
| Web-search calls | 0 | ≤ 8/session |
| `query_database` calls | ≤ 20/session | ≤ 30/session |

---

## A11. Observability

### A11.1 Server

| Stream | Where | Cardinality |
|---|---|---|
| Structured JSON log | `observability/logging.py` — one line per SSE event emitted, keyed by `session_id`, `insight_id` | high |
| Tool spans | `tool_call_log` table — one row per tool dispatch with latency, ok, error_code, token estimate | medium |
| Skill spans | `skill_invocation` table — one row per `run_skill` call with inputs hash, outputs JSON, latency | medium |
| Agent message log | `agent_message` table — full transcript per session (debugging) | high |

### A11.2 Frontend telemetry

| Metric | Captured by |
|---|---|
| Insight render time (skeleton mount → final state) | `InsightCard` `useEffect` timestamps |
| Chart render time (chart event → recharts mounted) | `InsightChartFrame` instrument |
| Chat time-to-first-token (V2) | `InsightChatDock` |
| SSE reconnect events | `insights/sse.ts` |

Sent to existing telemetry endpoint (no new infra; piggy-back on `routers/events.py`).

### A11.3 the user-facing observability

Per PRD §5.6, the per-card *provenance footer* is the user-visible observability surface: data sources used, skills run, confidence, materiality, generated_at, model, session_id. The `InsightProvenanceFooter` component reads from the persisted `Insight` record + linked `Chart` + `tool_call_log` summary. There is no separate observability dashboard for V1 — the provenance footer *is* the observability view for users.

---

## A12. Frontend module layout

```
frontend/src/components/
├── agentchat/                          # NEW — per RESEARCH R5, 6 primitives extracted from ChatPanel.tsx
│   ├── MarkdownMessage.tsx             # react-markdown wrap + dark-theme styles (lines 21–85 of ChatPanel)
│   ├── chartTheme.ts                   # PIE_COLORS, TOOLTIP_STYLES, fmt() (lines 89–102)
│   ├── InsightChart.tsx                # Generalised renderer; dispatch on ChartSpec.chart_type
│   ├── ToolTrace.tsx                   # Collapsible tool-call list (lines 250–271)
│   ├── CitationList.tsx                # Generalised — DB cite OR WebCitation (V2 shape)
│   ├── AgentMessage.tsx                # Composes above into assistant bubble
│   └── index.ts                        # barrel
├── ChatPanel.tsx                       # SHRUNK to consume agentchat/ primitives
├── tabs/
│   └── AIInsightsTab.tsx               # NEW — registered in App.tsx nav as 10th tab
├── insights/                           # NEW
│   ├── SessionRunner.tsx               # "Generate" button + run state + cancel
│   ├── InsightCard.tsx                 # Outer card; mounts skeleton on insight_started
│   ├── InsightHeader.tsx               # Title + chips (confidence, materiality, low_external_support)
│   ├── InsightChartFrame.tsx           # Wraps <InsightChart spec={...}>
│   ├── InsightCitations.tsx            # Web citations with agree/disagree pill (V2)
│   ├── InsightChatDock.tsx             # V2 — docked chat per insight (NOT a FAB)
│   ├── InsightProvenanceFooter.tsx     # Per PRD §5.6
│   ├── EmptyState.tsx                  # No sessions yet
│   ├── ErrorState.tsx                  # Terminal failure
│   ├── StreamingSkeleton.tsx           # "Surveying the platform…" preamble
│   ├── chartSpecRenderer.tsx           # ChartSpec.chart_type → Recharts switch (dispatch table only)
│   └── sse.ts                          # Typed SSE client + Last-Event-ID
└── App.tsx                              # MODIFIED — registers AIInsightsTab in nav (additive only)
```

### A12.1 Dispatch table (chartSpecRenderer.tsx — sketch)

| `chart_type` | Recharts primitive(s) |
|---|---|
| `line` | `<LineChart><Line /></LineChart>` |
| `bar` | `<BarChart><Bar /></BarChart>` |
| `stacked_bar` | `<BarChart><Bar stackId="a">…</Bar></BarChart>` (multi) |
| `grouped_bar` | `<BarChart>` with multiple `<Bar>`, no stackId |
| `area` | `<AreaChart><Area /></AreaChart>` |
| `stacked_area` | `<AreaChart>` multi `<Area stackId>` |
| `scatter` | `<ScatterChart><Scatter /></ScatterChart>` |
| `pie` | `<PieChart><Pie /></PieChart>` (truncate ≥8 slices) |
| `sparkline` | `<LineChart>` with axes off, height 32 |
| `kpi_tile` | non-chart card with primary number |

### A12.2 Where the chat lives (V2)

`InsightChatDock` is **docked into the bottom of the insight card**, not a floating FAB (which is what `ChatPanel.tsx` is, for the global Q&A widget). One-click "Discuss" expands the dock; messages stream into the same card. This is a UX hook for the designer (A15).

---

## A13. Error handling & recovery

| Failure | Detection | Response |
|---|---|---|
| Stream disconnect mid-session | `EventSource.onerror` | Browser auto-reconnects with `Last-Event-ID`; server replays from ring buffer |
| `query_database` timeout (>5 s) | Postgres aborts via `statement_timeout` | Tool returns `tool_error: db_timeout`; agent gets it as a tool result, may retry up to 2× per insight |
| `query_database` AST gate fail | sqlglot parse | `tool_error: unsafe_sql` — agent sees the rule violated and reformulates |
| `query_database` row cap exceeded | `len(rows) > max_rows` | `tool_error: too_many_rows` — agent must aggregate / `LIMIT` |
| `call_api` not in allowlist | `tools/router_call.py` | `tool_error: endpoint_not_allowed` |
| `web_search` provider timeout (V2) | httpx timeout | Try fallback provider once; on second fail, return `tool_error: web_search_unavailable`; agent may emit insight with `low_external_support` flag |
| Both web-search providers fail | breaker | `low_external_support=true` on the emitted insight; no incident |
| `emit_chart` row_hash mismatch | server validator | `tool_error: row_hash_mismatch`; agent retries with a fresh fetch (max 2×) |
| `emit_citation` rationale not in snippet | `citation_gate.py` | `tool_error: citation_unsupported_rationale` |
| LlamaStack 5xx | `httpx.HTTPError` from `LlmClient.reason()` | Retry once with jitter; on second fail, terminate session with `error: llm_unavailable` |
| Frontend: invalid ChartSpec arrives | Zod parse on the client | Render JSON viewer + "chart unavailable for this insight" message; rest of card stays |
| Frontend: SSE message order off | event id gap | Buffer events, request resume via reconnect with `Last-Event-ID = last_seen` |
| Cancel during tool dispatch | `asyncio.Event` poll between dispatches | Emit `error code=cancelled` then `session_complete` |

Per-insight retry budget: **2 retries per tool per insight**, then the insight is dropped (with an error event), and the orchestrator continues to the next candidate. A session never terminates because one insight failed.

---

## A14. V2 / V3 deltas

### A14.1 V2 deltas

| Component | Change |
|---|---|
| `tools/web_search.py` | Net new — Tavily/Brave clients + breaker |
| `tools/emit.py` | Add `emit_citation` |
| `safety/citation_gate.py` | Net new — substring + number-presence check |
| `agents/insights/orchestrator.py` | Add per-insight web-search step + agree/disagree judge subprocess |
| `agents/insights/skills/` | Add 3 skills: `cohort_analysis`, `methodology_explainer`, `peer_review_template` |
| `routers/insights.py` | Add `POST /insights/{id}/chat` (SSE) and `GET /insights/{id}/chat`; add `GET /insights/{id}/citations` |
| `persistence/models.py` | `citation` table starts being written; per-insight `agent_message` rows |
| Frontend `insights/InsightChatDock.tsx` | Net new |
| Frontend `insights/InsightCitations.tsx` | Net new |
| ToolLoopDriver | Pivot to **parallel-sub-agents** option for the per-insight phase (forward-compat hook landed in V1) |

### A14.2 V3 deltas

| Component | Change |
|---|---|
| `agents/insights/schedules/runner.py` | Net new — cron entry; reuse existing `runner.py` framework |
| `routers/insights.py` | Add `POST /schedules`, `GET /schedules` |
| `persistence/models.py` | `insight_schedule` table |
| Frontend | Subscribe button (UI scaffold landed in V2) wires to backend; insight-diff renderer compares current vs `last_run_session_id` insights via embedding nearest-neighbor + same canonical claim type |
| Optional | `geospatial_analysis` skill if Recharts gains a map primitive or if we accept a Leaflet-based emit path |

### A14.3 V1 forward-compat hooks

- `ToolLoopDriver.run()` returns per-insight; orchestrator already iterates a list — V2 swaps `for` for `asyncio.gather()` with one task per insight.
- `Insight.headline_embedding` column populated in V1 even though dedup only uses it intra-session — V3 cross-session diff already has the index.
- SSE events include `insight_id` from V1 (interleaving safe) — V2 parallelism is wire-compatible.
- ChartSpec v1 has `data_source` provenance from V1 — V3 diff compares row_hash + data_source between runs.
- `agent_message` table stores per-insight chats from V1 schema even if V1 doesn't use it — V2 just starts writing.

---

## A15. Open issues for designer + PM

### A15.1 For the designer

| # | Issue |
|---|---|
| D1 | Streaming vs loading: do we show token-streaming body text mid-card, or wait until `insight_complete` and reveal? RECOMMENDED: stream tokens but with a low-contrast "drafting" treatment until `insight_complete` fires |
| D2 | Where does the chat dock live? Bottom of the card (architect rec), modal, side-rail? PRD §5.4 implies in-card; confirm visual treatment |
| D3 | Citation hover-card vs inline: PRD §5.3 implies inline pills (agree/disagree), but rationale + URL is too much for a pill — designer to decide hover vs expanded row |
| D4 | Skeleton hierarchy: when `insight_started` arrives without tokens yet, what skeleton appears? (suggest header + body shimmer + chart-shaped placeholder) |
| D5 | "Surveying the platform…" preamble UX — single banner above all cards? Replaced by first card when ready? |
| D6 | Provenance footer placement: collapsed by default (one summary line) vs always-expanded? Recommended: collapsed with chevron |
| D7 | `low_external_support` flag: how prominently to surface? PRD §5.3 says visible. Pill in header? |
| D8 | Cancel UX: during a session, is there a single Cancel button or per-insight pause? V1 single Cancel is enough |
| D9 | Map-shaped insights deferred to V3 — designer should know not to design any map UI for V1/V2 |
| D10 | Mobile? Tool is internal desktop-first; no mobile target in V1/V2 |

### A15.2 For PM

| # | Issue |
|---|---|
| P1 | **Confirm V1 ships without chat.** PRD §8 V1 list excludes chat. ARCHITECTURE assumes this. |
| P2 | OQ8 confidence rubric — provisional thresholds: low = (rows < 50 OR no agree-cite OR source older than freshness band); medium = otherwise; high = (rows ≥ 200 AND ≥1 agree-cite AND fresh). PM to ratify before V1 demo. |
| P3 | OQ10 chat retention — `agent_message` is unbounded in V1 schema; if PM picks 90-day retention, add a `delete_after` column or run a sweep job |
| P4 | Skill-conversion delta (see SKILL_CONVERSION §S4.1): the PRD-named drops `forecasting`, `outlier-detection`, `pricing-analysis`, etc. don't exist in the installed catalog. PM should confirm the set of 15 keeps maps to actually-installed skills and acknowledge that some PRD §6 drops are vacuous |
| P5 | OQ11 reconciliation: installed catalog has 33 skills (excl. `dev-team`). 15 keeps confirmed; 18 not-kept. Several "not-kept" are *non-analytical* (analysis-documentation, schema-mapper-docs, context-packager) — fine to defer/never. PM to acknowledge |
| P6 | Materiality scoring rubric (OQ5) — V1 ships agent-self-rate via prompt; PM to label 50 sample insights post-V1 to seed a V2 rubric |
| P7 | Cite freshness (OQ7) — recommend ≤24 month default; flag-only beyond that, do not auto-reject |

---

**End of ARCHITECTURE.md.**
