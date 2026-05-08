# AI Insights V2 — Phase A Architecture

**Status:** Draft for implementation · **Date:** 2026-05-07 · **Owner:** architect
**Spec:** `docs/ai_insights_v2_spec.md` §4 + §5.1 + §8 (Phase A)
**Audience:** backend agent implementing the 7 deliverables.

Phase A ships the **read-only workspace surface** the V2 synthesis loop depends on:
SCHEMA.md, FRESHNESS.md, the `read_workspace` tool, the open-questions HTTP route,
and the two refresh hooks (Alembic post-upgrade for schema, daily cron for freshness).
No agent-loop or chart changes — those land in Phases B/C.

---

## 1. File-by-file plan

### 1.1 `backend/scripts/refresh_schema_doc.py` (NEW)

- **Purpose.** Introspect `SQLModel.metadata`, query row counts + top-10 samples per
  high-signal table, render `.openclaw/workspace/SCHEMA.md` (per spec §4.1).
- **Public signatures.**
  ```python
  HIGH_SIGNAL_TABLES: list[str]               # see §2 mapping
  PRIMARY_METRIC: dict[str, str | None]       # see §2 mapping
  WORKSPACE_DIR_ENV = "OPENCLAW_WORKSPACE_DIR"

  def workspace_dir() -> pathlib.Path: ...
  async def collect_table_stats(engine) -> list[TableStat]: ...
  def render_markdown(stats: list[TableStat], migration_rev: str | None) -> str: ...
  async def refresh() -> pathlib.Path: ...   # entrypoint; writes SCHEMA.md atomically
  def main() -> None: ...                    # CLI: `python -m scripts.refresh_schema_doc`
  ```
  Where `TableStat` is a small dataclass: `{name, row_count, columns: list[ColumnInfo],
  fks: list[FKInfo], top_rows: list[dict], primary_metric: str | None}`.
- **Invariants / failure modes.**
  - Atomic write: render to `SCHEMA.md.tmp` then `os.replace`; never leave a partial.
  - Tables listed in declaration order *within* the `## Tables` section; tables sorted
    by `row_count DESC` overall (spec §4.1 + §2 below).
  - Top-10 query: `SELECT * FROM <t> ORDER BY <metric> DESC NULLS LAST LIMIT 10` when
    `PRIMARY_METRIC[t]` is set; else `ORDER BY updated_at DESC` if column exists; else
    `ORDER BY created_at DESC`; else `LIMIT 10` unordered.
  - Column values that exceed 80 chars in samples are truncated with `…`.
  - Migration revision header derived from `alembic_version.version_num`; if the table
    is absent (fresh DB), use `"unknown"`.
  - Failure must NOT raise from `refresh()`; logs and returns a path to a
    best-effort partial file. Caller (alembic hook) wraps in try/except too.
  - Skip tables that `SELECT count(*)` raises on (permission, missing).
- **Dependencies.** `db.session.get_readonly_engine` (or sync engine if hook context
  requires sync — see §5), `db.models` (for `SQLModel.metadata`), `sqlalchemy.inspect`.

### 1.2 `backend/alembic/env.py` (EDIT — post-upgrade hook)

- **Purpose.** After every successful online migration, regenerate `SCHEMA.md` so the
  agent's view of the DB never drifts from the live schema.
- **Public signatures (added).**
  ```python
  def _run_post_upgrade_schema_refresh() -> None: ...
  ```
- **Invariants / failure modes.**
  - Hook fires inside `run_migrations_online()` **after** `context.run_migrations()`
    returns, **outside** the transaction (so a refresh failure cannot rollback the
    migration).
  - Wrapped in `try / except Exception`; logs `alembic.post_upgrade.schema_refresh_failed`
    and swallows. Migrations succeed or fail purely on their own merits.
  - Skipped in offline mode (`context.is_offline_mode()` short-circuits).
  - Skipped when `os.getenv("SKIP_SCHEMA_DOC_REFRESH") == "1"` (CI / unit tests).
  - Uses `asyncio.run(refresh())` if the script is async; if `refresh()` is sync, calls
    directly. (Implementation note: `refresh_schema_doc.refresh` is async per §1.1; the
    hook does `asyncio.run(...)`.)
- **Dependencies.** `backend/scripts/refresh_schema_doc.py`. No new imports at module
  top; lazy-import inside the hook so test environments without the script still load
  `env.py` cleanly.

### 1.3 `backend/scripts/refresh_freshness_doc.py` (NEW)

- **Purpose.** Compute per-table row-count + Δ7d + Δ24h + max(updated_at), render
  `.openclaw/workspace/FRESHNESS.md` (spec §4.2).
- **Public signatures.**
  ```python
  FRESHNESS_TABLES: list[str]                 # subset of HIGH_SIGNAL_TABLES + a few others
  TIMESTAMP_COLUMN: dict[str, str]            # see §2 mapping

  @dataclass
  class FreshnessRow:
      table: str
      rows: int
      max_ts: datetime | None
      delta_7d: int
      delta_24h: int
      pct_change_7d: float

  async def collect_freshness(engine) -> list[FreshnessRow]: ...
  def render_markdown(rows: list[FreshnessRow], generated_at: datetime) -> str: ...
  async def refresh() -> pathlib.Path: ...    # entrypoint; cron + alembic-free
  def main() -> None: ...                     # CLI
  ```
- **Invariants / failure modes.**
  - Atomic write (same `.tmp` + `os.replace` pattern as §1.1).
  - Sort: rows DESC by `delta_7d` (spec §2 below).
  - "Hot tables" rollup includes any table with `pct_change_7d > 0.05` (i.e. 5% growth
    over current row count in the last 7 days).
  - Δ7d = `count(*) WHERE <ts> >= now() - interval '7 days'`. Same for Δ24h.
  - For tables without a usable timestamp column, Δ7d = Δ24h = `0`, max_ts = `None`,
    pct_change = `0.0`. Still listed in the table.
  - Wall-clock budget: ≤30s total. Each query is `statement_timeout=5s`.
  - Logs `freshness_doc.refresh.{ok,error}` with row-count summary.
- **Dependencies.** Same as §1.1: readonly engine + `db.models`.

### 1.4 `backend/pipeline/runner.py` (EDIT — `freshness_doc_daily` job)

- **Purpose.** Wire `refresh_freshness_doc.refresh()` into APScheduler so FRESHNESS.md
  gets rebuilt every day at 02:00 UTC.
- **Public signatures (added).**
  ```python
  async def run_freshness_doc_job() -> None: ...
  async def _invoke_freshness_doc(session) -> dict: ...
  ```
  And the registry deltas:
  ```python
  JOB_CONFIG["freshness_doc_daily"] = {
      "adapter": "_freshness_doc_refresh",
      "trigger": CronTrigger(hour=2, minute=0),     # 0 2 * * *
      "phase": 3,
  }
  _JOB_FUNCTIONS["freshness_doc_daily"] = run_freshness_doc_job
  ```
- **Invariants / failure modes.**
  - Job id stable: `freshness_doc_daily`. Adapter name stable:
    `_freshness_doc_refresh` (mirrors the `_anomaly_detection`, `_weekly_brief`
    convention).
  - Uses the existing `_run_adapter_job` wrapper → automatic `IngestionRun` audit row
    with `status running → success | failure`.
  - `_invoke_freshness_doc` lazy-imports
    `from scripts.refresh_freshness_doc import refresh`, calls `await refresh()`,
    returns `{"fetched": <table_count>, "stored": 1, "skipped": 0}` on success.
  - Cron 02:00 UTC is *before* the rest of the daily ingest set (06:00–08:00) by
    design — yes, that means FRESHNESS.md reflects yesterday's deltas at the moment
    AI Insights runs at 09:00. This is acceptable; spec §4.2 explicitly tags freshness
    as "post-ingestion" but Phase A treats this as a known wart, not a blocker. (If
    needed, move to 08:30 UTC in a follow-up — single-line config change.)
  - Misfire grace: 3600s (matches other daily jobs; the `coalesce=True` default
    handles missed slots).
- **Dependencies.** `backend/scripts/refresh_freshness_doc.py`.

### 1.5 `backend/agents/insights/tools/read_workspace.py` (NEW)

- **Purpose.** App-owned MCP tool the synthesis agent calls to read workspace
  artefacts (spec §5.1).
- **Public signatures.**
  ```python
  ALLOWED_FILES: frozenset[str] = frozenset({"SCHEMA.md", "FRESHNESS.md"})
  MAX_BYTES: int = 16 * 1024     # 16 KB hard cap

  async def read_workspace(
      file: str,
      ctx: SkillContext | None = None,
  ) -> dict:
      """Returns {ok, content, truncated} or {ok: False, error: <str>}."""
  ```
- **Invariants / failure modes.**
  - Allowlist: any `file` not in `ALLOWED_FILES` →
    `{"ok": False, "error": "file_not_allowed", "detail": {"file": file}}`.
    No path-traversal possible — input is matched as a literal string before any
    `Path` join.
  - Workspace dir resolution: `os.environ.get("OPENCLAW_WORKSPACE_DIR")` falls back
    to `<project_root>/.openclaw/workspace`. Project root = three `parents` up from
    `backend/agents/insights/tools/read_workspace.py`.
  - Read mode: open in binary, read up to `MAX_BYTES + 1` bytes. If returned len >
    `MAX_BYTES`, slice to `[:MAX_BYTES]` and set `truncated=True`. Decode UTF-8 with
    `errors="replace"`.
  - Missing file → `{"ok": False, "error": "file_not_found", "detail": {"file": file}}`.
    (Distinct from `file_not_allowed` so callers can tell the difference.)
  - Read failure (permission, IO) → `{"ok": False, "error": "read_failed",
    "detail": {"reason": str(exc)}}`. Never raises out of the tool.
  - No SQL, no I/O beyond a single file read. p99 latency ≤ 50 ms.
- **Dependencies.** `..specs.skill_context.SkillContext` (signature only — `ctx` is
  unused in Phase A, kept for parity with other tools).

### 1.6 `backend/agents/insights/tools/registry.py` (EDIT — register read_workspace)

- **Purpose.** Expose the new tool to the LLM via the OpenAI function spec and route
  invocations through the dispatch map.
- **Public signatures.** No new functions; two structural edits.
  - **Edit 1 — `TOOL_DEFS` append:**
    ```python
    {
        "type": "function",
        "function": {
            "name": "read_workspace",
            "description": (
                "Read a workspace artefact (SCHEMA.md or FRESHNESS.md). "
                "Returns the first 16KB; truncated=True if longer. "
                "Cheap, read-only — call at session start to orient."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "enum": ["SCHEMA.md", "FRESHNESS.md"],
                    },
                },
                "required": ["file"],
                "additionalProperties": False,
            },
        },
    },
    ```
  - **Edit 2 — `_DISPATCH` entry:** `"read_workspace": read_workspace`.
  - **Edit 3 — `dispatch()` branch:**
    ```python
    if name == "read_workspace":
        return await fn(args_dict.get("file", ""), ctx if accepts_ctx else None)
    ```
- **Invariants / failure modes.**
  - Both edits land together — registering in `TOOL_DEFS` without `_DISPATCH`
    would yield `{"ok": False, "error": "unknown_tool"}` at runtime.
  - `enum` in the function spec is a hint to the model; the tool itself still
    enforces the allowlist (defence-in-depth).
- **Dependencies.** `.read_workspace` (new file).

### 1.7 `backend/routers/insights.py` (EDIT — `GET /api/insights/open-questions`)

- **Purpose.** Frontend "Tracked questions" sidebar reads MEMORY.md, parses the
  open_questions section (spec §4.4), returns the structured journal.
- **Public signatures (added).**
  ```python
  class OpenQuestion(BaseModel):
      id: str
      status: str
      materiality: str
      latest_note: str
      last_seen_iso: str

  @router.get(
      "/open-questions",
      response_model=list[OpenQuestion],
      summary="Parsed open_questions journal from .openclaw/workspace/MEMORY.md",
  )
  async def list_open_questions() -> list[OpenQuestion]: ...
  ```
- **Invariants / failure modes.** See §3 below for the parsing contract.
  - Missing file → `[]` (200 OK).
  - Missing section → `[]` (200 OK).
  - Malformed line (wrong number of `|` parts) → silently skip, log
    `open_questions.parse_skip` once per request with a count.
  - In-process TTL cache: 60s, keyed on file `mtime_ns`. Implementation: a single
    module-level `_OQ_CACHE: tuple[int, float, list[OpenQuestion]] | None`
    (mtime_ns, expires_at, value); recompute when expired or mtime changed.
- **Dependencies.** `pathlib`, `re`, `datetime` — no new imports beyond what
  the router already has. New private helper `_parse_memory_md(text: str) ->
  list[OpenQuestion]` in the same module (keeps the route file self-contained).

---

## 2. Data model decisions

### 2.1 Primary-metric column per high-signal table

Picked from `backend/db/models.py` per the spec § 2 instruction. When no obvious
single-column metric exists, fall back to `updated_at` then `created_at`.

| Table | Primary metric | Notes |
|---|---|---|
| `sites` | `power_capacity_mw` | indexed; canonical "selected MW" |
| `power_projects` | `tot_phase_nameplate_power_mw` | per-phase nameplate MW |
| `energy_projects` | `tot_contracted_power_mw` | contracted MW |
| `edgar_extractions` | `capacity_mw` | extracted contract size |
| `generator_permits` | `rated_mw_total` | summed unit nameplate |
| `building_permits` | `valuation_usd` | best proxy; fall back to `issued_date DESC` if NULL-heavy |
| `companies` | *(none — no MW field on the row)* | order by `updated_at DESC` |
| `anomalies` | `z_score` | bigger \|z\| = more material |
| `data_coverage` | `record_count` | |
| `events` | *(none)* | order by `event_date DESC` |
| `press_releases` | *(none)* | order by `published_date DESC` |
| `transcript_metrics` | `numeric_value` | NULL-heavy; OK to fall back |
| `power_deal_links` | `match_score` | |
| `brief_runs` | *(none)* | order by `generated_at DESC` |
| `ingestion_runs` | `records_stored` | |

`HIGH_SIGNAL_TABLES` for `SCHEMA.md` = the 9 tables called out in spec §4.1 plus
`power_projects`, `power_deal_links`, `events`, `press_releases` (these have direct
analytic value). The full set: `companies, sites, energy_projects, power_projects,
edgar_extractions, generator_permits, building_permits, power_deal_links, anomalies,
events, press_releases, data_coverage`.

### 2.2 SCHEMA.md ordering

- Top-level table list sorted by `row_count DESC`.
- Within each table block, columns rendered in **declaration order** (i.e. the order
  they appear in the SQLModel class — pulled from `__table__.columns` which preserves
  this).
- FKs called out in a "**FKs:**" line below the column table, with arrow syntax:
  `developer_company_id → companies.id`. SQLModel doesn't always declare formal
  FKs (some are implicit via `_id` columns), so the generator uses a static
  `KNOWN_FKS` map alongside `inspect(engine).get_foreign_keys()` and unions them.

### 2.3 FRESHNESS.md ordering

- Rows sorted by `delta_7d DESC` (largest absolute delta first).
- Hot tables rollup: `pct_change_7d = delta_7d / max(row_count, 1)`. Include any
  table where `pct_change_7d > 0.05`.
- Format hot-table line: `- <table> (+<pct:.1f>%)`.

---

## 3. MEMORY.md parsing contract

Input file: `.openclaw/workspace/MEMORY.md` (resolved via the same workspace-dir
helper as §1.5).

Parser steps (must match exactly):

1. **Locate section.** Compile
   `re.compile(r'^\s*##\s+open[_\s]+questions\b.*$', re.IGNORECASE | re.MULTILINE)`.
   Take the matched header's end offset; the section runs until the next `^##\s` or
   EOF. Section header tolerates `## Open Questions`, `## open_questions`,
   `## OPEN QUESTIONS`, `##  open_questions extra trailing text`.
2. **Bullet extraction.** Within the section body, iterate lines. A "bullet" is a
   non-empty line where `lstrip()` starts with `- ` (hyphen + space). Strip the
   leading `- `.
3. **Pipe split.** Split the remaining text on `\s*\|\s*` (regex: any pipe, with
   optional surrounding whitespace). Expect **exactly 4 parts**: `id`, `status`,
   `materiality`, `note`. Wrong count → skip the line.
4. **Trailing date suffix.** On `note`, run
   `re.search(r"\s*_<(\d{4}-\d{2}-\d{2})>_\s*$", note)`. If matched: strip the
   suffix from the displayed `latest_note` and parse the captured date as
   `YYYY-MM-DDT00:00:00+00:00` → `last_seen_iso`. If not matched: fall back to
   the file's `mtime` rendered as ISO-8601 UTC.
5. **Group by id.** A given `id` may appear multiple times. The "winner" is the
   entry with the largest `last_seen_iso` (string compare works because ISO-8601
   sorts lexicographically); ties broken by document order (later wins).
6. **Output ordering.** Sort the final list by `last_seen_iso DESC`, then `id ASC`
   for deterministic output.
7. **Empty cases.** File missing → `[]`. Section missing → `[]`. Section present
   but no parseable bullets → `[]`. All return `200 OK`.

Status / materiality values are **not** validated against an enum in Phase A — the
route trusts the journal author. (Phase D may add validation against
`{"watching", "confirmed", "disproved", "stale"}` × `{"low", "medium", "high"}`.)

---

## 4. `read_workspace` tool contract (recap)

Already specified in §1.5; explicit invariants for review:

- **Allowlist:** literal `frozenset({"SCHEMA.md", "FRESHNESS.md"})`. Anything else →
  `{"ok": False, "error": "file_not_allowed"}`. No `Path` join happens until after
  the allowlist check, so traversal vectors (`../`, abs paths, symlinks pointed
  outside workspace) are structurally impossible.
- **Workspace dir:** `OPENCLAW_WORKSPACE_DIR` env override, else
  `<project_root>/.openclaw/workspace`. Project root computed by walking up from
  `__file__` to find `.openclaw/` (or hard-coded `parents[4]` — pick one and
  document; recommended: env-only with a sensible default constant computed once
  at module import).
- **16 KB cap:** read at most `16384 + 1` bytes; if `len > 16384`, truncate and
  set `truncated=True`. Bytes-level cap (not chars), so multi-byte UTF-8 at the
  boundary is allowed to mojibake — use `errors="replace"` on decode.
- **Return shape:** `{ok: True, content: str, truncated: bool}` on success.
  Error variant: `{ok: False, error: str, detail?: dict}`. Matches spec §5.1.
- **Registration:** both `TOOL_DEFS` (OpenAI spec, with `enum` on `file`) and
  `_DISPATCH` map. Test: round-trip a tool_call payload through `dispatch()`
  with `name="read_workspace"`, assert it reaches `read_workspace()` not the
  fallback.

---

## 5. Alembic hook design

```text
run_migrations_online()
  └─ engine.connect()
       └─ context.configure(...)
            └─ context.begin_transaction()
                 └─ context.run_migrations()        ← migration body
       (transaction committed here)
  └─ _run_post_upgrade_schema_refresh()             ← NEW, outside transaction
```

- Hook runs **after** the `with` block of `begin_transaction()` exits cleanly. Do
  not put it inside the transaction — a failed refresh would silently roll back
  the migration.
- Wrapped in `try / except Exception as exc: logger.warning(...)`.
- Skipped via two early-returns:
  ```python
  if context.is_offline_mode(): return
  if os.getenv("SKIP_SCHEMA_DOC_REFRESH") == "1": return
  ```
- Bridge async/sync: `refresh()` is async (uses the project's async engine).
  Hook does `asyncio.run(refresh_schema_doc.refresh())`. If the alembic
  process already has a running loop (rare in CLI), fall back to
  `asyncio.new_event_loop().run_until_complete(...)`.
- The hook must NOT change the migration's exit code on refresh failure. Tests
  in CI set `SKIP_SCHEMA_DOC_REFRESH=1` to keep alembic-only test runs fast.

---

## 6. Cron wiring design (recap)

- **Job id:** `freshness_doc_daily`. Trigger: `CronTrigger(hour=2, minute=0)`.
- **Adapter name:** `_freshness_doc_refresh` (leading underscore = internal job,
  matches `_anomaly_detection` / `_weekly_brief`).
- **`run_freshness_doc_job()`** is a thin wrapper:
  ```python
  async def run_freshness_doc_job() -> None:
      await _run_adapter_job("_freshness_doc_refresh", _invoke_freshness_doc)
  ```
- **`_invoke_freshness_doc(session)`** lazy-imports the script and invokes it:
  ```python
  async def _invoke_freshness_doc(session) -> dict:
      from scripts.refresh_freshness_doc import refresh
      path = await refresh()
      return {"fetched": 0, "stored": 1, "skipped": 0, "path": str(path)}
  ```
  The `session` param is unused by the script (it opens its own engine) but is
  required by the `_run_adapter_job` contract.
- **`JOB_CONFIG`** + **`_JOB_FUNCTIONS`** entries added per §1.4. Misfire grace
  inherits the default 3600s branch in `create_scheduler()`.

---

## 7. Open-questions route shape (recap)

- Path: `GET /api/insights/open-questions`. Mounted on the existing
  `router = APIRouter(prefix="/api/insights", tags=["insights"])`.
- Response: `list[OpenQuestion]` (Pydantic model defined in §1.7). FastAPI handles
  serialization; no SSE.
- Cache: 60s in-process TTL keyed on file mtime. Trivial — kept because the
  frontend may poll this every 30s for the sidebar.
- No auth changes (existing routes are unauth in dev).

---

## 8. Test plan stub

All tests live under `backend/tests/`.

- **`test_refresh_schema_doc.py`** (unit)
  - Spin up an in-memory SQLite via `sqlalchemy.ext.asyncio.create_async_engine(
    "sqlite+aiosqlite:///:memory:")`.
  - Create 2-3 fake tables (`companies` minimal: `id`, `canonical_name`, `ticker`;
    `sites`: `id`, `power_capacity_mw`, `provider_name`).
  - Call `await refresh_schema_doc.refresh()` against a tmp workspace dir
    (set `OPENCLAW_WORKSPACE_DIR=<tmp>`).
  - Compare against `tests/golden/SCHEMA.md.golden`. Replace the
    `generated <timestamp>` line with `<TS>` before diff.
- **`test_refresh_freshness_doc.py`** (unit)
  - Same in-memory SQLite. Insert rows with varied `created_at` / `updated_at` so
    Δ7d/Δ24h are deterministic.
  - Compare against `tests/golden/FRESHNESS.md.golden`.
- **`test_open_questions_route.py`** (endpoint)
  - Use `httpx.AsyncClient(app=app)`.
  - Set `OPENCLAW_WORKSPACE_DIR` to a tmp dir; write a fixture `MEMORY.md` with
    a known `## open_questions` section containing 3 bullets (one with date suffix,
    one without, one malformed).
  - Assert: 200 OK, length 2 (malformed dropped), correct `last_seen_iso`,
    correct `latest_note` ordering.
  - Second test: missing file → `[]`. Missing section → `[]`.
- **`test_read_workspace_tool.py`** (unit)
  - `await read_workspace("SCHEMA.md")` against a tmp workspace.
  - Cases: file present (truncated=False), file >16KB (truncated=True),
    file missing (`error="file_not_found"`), file `"../etc/passwd"`
    (`error="file_not_allowed"`).
- **`test_registry_dispatch.py`** (unit, edit)
  - Add a case asserting `dispatch("read_workspace", {"file": "SCHEMA.md"}, ctx)`
    routes to the new tool function.
- **Regression.** `pytest backend/tests` should remain green. Skipping the alembic
  hook in CI via `SKIP_SCHEMA_DOC_REFRESH=1` keeps the migration test suite
  unaffected.

---

## 9. Risks & Mitigations (Phase A only)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Alembic hook breaks CI migration runs | Med | High | `SKIP_SCHEMA_DOC_REFRESH=1` in CI env; hook wrapped in try/except |
| Schema introspection too slow on large DBs | Low | Med | Per-table queries are `LIMIT 10` + a single `count(*)`; total budget < 30s |
| FRESHNESS.md cron lands before daily ingest | High | Low | Acknowledged; deltas reflect prior day. Move to 08:30 UTC as follow-up if needed |
| MEMORY.md parser brittle to OpenClaw format change | Med | Med | Skip-on-malformed + log; section detection is regex-tolerant; integration test with real fixture |
| read_workspace used as a path-traversal vector | Low | High | Literal-string allowlist BEFORE any `Path` join; no user-controlled segments |
| Hot-table threshold (5%) noisy or missing real growth | Med | Low | Configurable via module constant; tune after observation |

---

## Files (absolute paths)

- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/scripts/refresh_schema_doc.py` (NEW)
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/scripts/refresh_freshness_doc.py` (NEW)
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/tools/read_workspace.py` (NEW)
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/alembic/env.py` (EDIT)
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/pipeline/runner.py` (EDIT)
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/tools/registry.py` (EDIT)
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/routers/insights.py` (EDIT)
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/workspace/MEMORY.md` (READ-only consumer)
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/workspace/SCHEMA.md` (NEW, generated)
- `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/workspace/FRESHNESS.md` (NEW, generated)
