# 14 — Unified Agent Architecture (OpenClaw Phases 2-5)

**Author:** System Architect
**Date:** 2026-05-06
**Status:** Draft for backend + QA handoff
**Predecessors:** `14-unified-agent-prd.md` (PM), `14-unified-agent-research.md` (Researcher), `13-mcp-migration-architecture.md` (Phase 1, shipped)
**Successor:** `14-unified-agent-test-evidence.md` (QA)

---

## 0. Executive Summary

The strategic-insights-tool runs three LLM workloads (daily synthesis, weekly brief, insight chat) on three divergent code paths. Phase 1 (PRD-13) put chat on OpenClaw + MCP. Phases 2-5 extend the same agent to synthesis and the weekly brief, then delete the legacy paths.

**Approach:** keep OpenClaw as the I/O loop, FastMCP at `/mcp` as the action plane, FastAPI as the audit ledger. No new gateway, no new MCP server, no Postgres migration.

**Blast-radius isolation:**

1. Sibling SSE translator (`translate_synthesis_chunk`) so the chat lane bytes are bit-identical (PRD AC-4 / FR-X.6).
2. Sibling stream driver (`drive_synthesis`) so `forward_chat` keeps its pre/post DB write contract.
3. Server-driven system prompts injected from FastAPI per turn — `.openclaw/openclaw.json` cannot select persona by `sessionKey` (Research §1.2, §5).
4. Three new MCP write-tools (`persist_insight`, `finalize_session`, `persist_brief`) modelled on the existing `emit_chart` shape via a new `_invoke_session` helper that takes `session_id` rather than `insight_id` (Research §1.3, §4).
5. Caps enforced client-side via `asyncio.wait_for` + cooperative break — never `task.cancel()` (Research §3, httpx #1461).
6. Dual-path during Phases 2-4 behind a `SYNTHESIS_MODE=legacy|agentic` flag; flag is removed in Phase 5 along with `OPENCLAW_ENABLED`.

---

## 1. Architectural Principles

### P1. One agent, many sessionKeys

A single agent persona + a single MCP toolbelt service all three workloads. Isolation is per-sessionKey:

| Workload | sessionKey pattern | Lifecycle |
|---|---|---|
| Manual "Run again" synthesis | `manual-{session_id}` | Per click; lives for one run. |
| Daily synthesis cron | `daily-synthesis-YYYYMMDD` | One per UTC day; idempotent. |
| Weekly brief cron | `weekly-brief-YYYYWW` | One per ISO week; idempotent. |
| Insight chat | `insight:{insight_uuid}` | Persists across turns within one insight. |

OpenClaw's session memory store is keyed on `x-openclaw-session-key`; collisions across prefixes are impossible because the prefixes are disjoint string namespaces (Research §1.4 + PRD R6).

### P2. OpenClaw is the I/O loop. FastMCP is the action plane. FastAPI is the audit ledger.

- OpenClaw: orchestrates LLM round-trips, holds the persona's `SOUL.md`, dials `/mcp` over streamable-HTTP.
- FastMCP (`/mcp`): exposes the 7 existing read-tools + 3 new write-tools via a single `@mcp.tool()` registry, all pivoting through `_invoke` / `_invoke_session`.
- FastAPI: owns `ai_session`, `agent_message`, `agent_tool_call`, `ai_insight`, `agent_chart`, `agent_citation`, `brief_run`. Every persisted artefact has its FK back to the parent `ai_session.id`. Tool call audit trail (FR-X.4) is a Phase-1 invariant we extend, not introduce.

### P3. Server-driven sessions (FR-X.1)

`.openclaw/openclaw.json` does NOT support per-`sessionKey` workspace file selection. We therefore inject the per-mode rules from FastAPI as a leading `system` message at request time. SOUL.md is tightened to identity + voice + safety + tool palette ONLY. Per-mode rules live in `backend/agents/insights/prompts/{chat,synthesis,brief}_rules.md`.

This decouples mode-switching from gateway config — the FastAPI side knows the mode (it knows the `sessionKey` it's about to send) and ships the right prompt. Multiple `system` messages compose at the model boundary.

### P4. Client-side caps (FR-2.7, FR-3.3)

OpenClaw exposes no per-session cap. We enforce all three caps in the FastAPI driver:

- **Wall clock 600s:** `asyncio.wait_for(driver_coro, timeout=600)`.
- **Turn cap 12:** counter incremented on each `message_complete` / `finish_reason="tool_calls"`; on trip, cooperative `break` from the SSE drain.
- **Tool cap 30:** counter incremented on each `tool_call_complete`; on trip, same cooperative break.

We **never** `task.cancel()` the httpx stream — this leaks connection-pool slots (httpx issues #1461, #2437). The clean exit path is to set `acc.cap_reached = True`, break the `async for line in response.aiter_lines()` loop, and let `async with client.stream(...)` close the stream as it unwinds.

### P5. SSE wire taxonomy frozen on chat (FR-X.6)

Chat lane bytes are part of the contract today. Synthesis events ride a sibling translator (`translate_synthesis_chunk`) so the chat byte stream is unaffected. Net-new event classes (`InsightStartedEvent`, `ChartEvent`, `InsightCompleteEvent`, `SessionCompleteEvent`) already exist in `agents.insights.specs.sse_events` from V1; we wire them up, not invent them.

### P6. Idempotent writes, no schema migration (FR-X.4 Goal G6)

`ai_session.token_estimate` already exists (Research §6.2 — `agents/insights/db/models.py:62`). All other columns we need are already on `ai_session`, `ai_insight`, `agent_chart`, `agent_message`, `agent_tool_call`, `brief_run`. Index additions on `(session_key, started_at)` are acceptable; data-model changes are not.

---

## 2. Module Map

| New / changed module | Path | Responsibility | Phase |
|---|---|---|---|
| `mcp_server.py` (extend) | `backend/mcp_server.py` | Add 3 new write-tools + `_invoke_session` helper. | 2 (insight + finalize) / 4 (brief) |
| `openclaw/forwarder.py` (refactor) | `backend/openclaw/forwarder.py` | Extract `_drive_openclaw_stream` private helper; `forward_chat` keeps DB-write semantics. | 2 |
| `openclaw/synthesis_driver.py` (NEW) | `backend/openclaw/synthesis_driver.py` | `drive_synthesis(session_id, fact_pack, mode)` — request-body assembly + per-tool-call dispatch + cap counters. | 2 |
| `openclaw/brief_driver.py` (NEW) | `backend/openclaw/brief_driver.py` | `drive_brief(session_id, period_start, period_end)` — same shape, brief-specific. | 4 |
| `openclaw/sse_translator.py` (extend) | `backend/openclaw/sse_translator.py` | Add `SynthesisChunkAccumulator` + `translate_synthesis_chunk`. Lift `_apply_tool_call_deltas` shared helper. | 2 |
| `agents/insights/agentic_synthesis.py` (NEW) | `backend/agents/insights/agentic_synthesis.py` | `run_agentic_synthesis(session_id, mode, target_insight_count)` orchestrator entry point. | 2 |
| `agents/insights/orchestrator.py` (extend) | `backend/agents/insights/orchestrator.py` | `SYNTHESIS_MODE` branch in `run_session()`; keep `_persist_session_start` / `_persist_insight` / `emit_chart_for_insight` as helpers reused by write-tools. | 2 |
| `agents/insights/prompts/synthesis_rules.md` (NEW) | `backend/agents/insights/prompts/synthesis_rules.md` | Per-mode rules injected as leading `system` for synthesis. | 2 |
| `agents/insights/prompts/chat_rules.md` (NEW) | `backend/agents/insights/prompts/chat_rules.md` | Per-mode rules injected for chat (post Phase 5 cleanup; not strictly required pre-5 since SOUL still has chat content). | 5 |
| `agents/insights/prompts/brief_rules.md` (NEW) | `backend/agents/insights/prompts/brief_rules.md` | Per-mode rules injected for brief. | 4 |
| `agents/insights/prompts/__init__.py` (NEW) | `backend/agents/insights/prompts/__init__.py` | `load(name)` lru-cached file reader. | 2 |
| `agents/weekly_brief.py` (rewrite) | `backend/agents/weekly_brief.py` | `generate_weekly_brief()` retargeted to `drive_brief`. `_build_context` stays. | 4 |
| `pipeline/runner.py::_invoke_insights_daily` (rewrite) | `backend/pipeline/runner.py` | Build FactPack, create AISession, call `run_agentic_synthesis(mode="scheduled")`, drain via shared helper. | 3 |
| `routers/insights.py::cost_summary` (NEW route) | `backend/routers/insights.py` | `GET /api/insights/cost-summary?days=7`. | 5 |
| `routers/insights.py` (DELETIONS) | `backend/routers/insights.py` | Delete legacy chat handler + system-prompt builder + dispatcher branch. | 5 |
| `agents/insights/tool_loop.py` (DELETE) | `backend/agents/insights/tool_loop.py` | Whole file. | 5 |
| `agents/insights/hypothesizer.py` (TRIM) | `backend/agents/insights/hypothesizer.py` | Delete `synthesize_insights` + `_coerce_insights` + `_SYSTEM_PROMPT`. Keep `build_factpack`, `InsightOutput`, `_INSIGHT_OUTPUT_SCHEMA`. | 5 |
| `config.py` (TRIM) | `backend/config.py` | Remove `openclaw_enabled` + `synthesis_mode`. Bump `hypothesizer_token_ceiling` 30K → 80K. | 2 (bump) / 5 (flag removal) |
| `.openclaw/workspace/SOUL.md` (TRIM) | `.openclaw/workspace/SOUL.md` | Strip per-insight chat-only language. Identity + voice + safety + tool palette only. | 2 |

---

## 3. New MCP Write-Tools (Phase 2 + 4)

### 3.1 The `_invoke_session` helper

The existing `_invoke()` in `mcp_server.py:141` is hard-wired to validate `insight_id` and call `build_skill_ctx(db, insight_id=...)`. Synthesis-scope tools do not have a parent insight (insights do not yet exist when `persist_insight` is called for the first time). We add a sibling helper:

```python
async def _invoke_session(
    name: str,
    session_id: str,
    args: dict[str, Any],
    *,
    handler: Callable[[AsyncSession, uuid.UUID, dict], Awaitable[dict]],
) -> dict[str, Any]:
    """Invoke a session-scoped write-tool inside a fresh DB session.

    Mirrors `_invoke()` but:
      - validates `session_id` instead of `insight_id`
      - does NOT build a SkillContext (no current-insight)
      - delegates to a per-tool `handler(db, session_uuid, args)` callable
        that does the side effect and returns the JSON result body
      - wraps in the standard {ok, result|error, code} envelope
    """
    try:
        session_uuid = uuid.UUID(session_id)
    except (ValueError, TypeError, AttributeError) as exc:
        return {"ok": False, "error": f"bad_session_id: {exc}", "code": "BAD_INPUT"}

    from db.session import async_session_factory

    db = async_session_factory()
    try:
        result = await handler(db, session_uuid, args)
        await db.commit()
        return {"ok": True, "result": result}
    except _ToolValidationError as exc:
        await _safe_rollback(db)
        return {"ok": False, "error": str(exc), "code": exc.code}
    except Exception as exc:
        logger.exception("mcp.session_invoke_failed", extra={"tool": name})
        await _safe_rollback(db)
        return {"ok": False, "error": str(exc), "code": "TOOL_FAILED"}
    finally:
        try:
            await db.close()
        except Exception:
            pass
```

Difference from `_invoke`:

| | `_invoke` (existing) | `_invoke_session` (new) |
|---|---|---|
| Primary key | `insight_id` (UUID) | `session_id` (UUID) |
| SkillContext | Yes (via `build_skill_ctx`) | No |
| Validation failure code | `TOOL_FAILED` (generic) | `BAD_INPUT` (typed); `DUPLICATE_NOOP`, `MAX_INSIGHTS_EXCEEDED`, `ALREADY_FINALIZED`, `BRIEF_DUPLICATE_PERIOD`, `BRIEF_ALREADY_PERSISTED` for known states |
| Returns insight in result | Whatever the tool body returns | Always small JSON: `{insight_id, idx}` / `{session_id, status, ...}` / `{brief_id, ...}` |

We keep both helpers; `emit_chart` and `emit_citation` still flow through `_invoke()` with `insight_id` because they target a known insight. `persist_insight` is an exception — it CREATES the insight — so it routes through `_invoke_session`.

### 3.2 `persist_insight`

**Pydantic input schema** (mirrors `InsightOutput` at `hypothesizer.py:143`):

```python
class PersistInsightInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str                              # UUID; AISession must exist + status='running'
    index: int                                   # 0-based ordinal within session; monotonic
    headline: str                                # 1..240 chars after strip
    body: str                                    # 1..4000 chars
    confidence_signal: Literal["weak", "moderate", "strong"]
    materiality: Literal["low", "medium", "high"]
    supporting_row_ids: list[str]                # 1..32; filtered against session FactPack
    skills_run: list[str] = Field(default_factory=list)
    chart_type: Optional[str] = None
    chart_y_label: Optional[str] = None
```

**Pydantic output:**

```python
class PersistInsightResult(BaseModel):
    insight_id: str           # UUID of the new ai_insight row
    idx: int                  # echoed back; 1-based ordinal (call number) in session
```

**DB writes:**

- `ai_insight` — INSERT one row. Columns: `id`, `session_id`, `idx`, `headline`, `body`, `confidence`, `materiality`, `supporting_row_ids` (JSONB), `skills_run` (JSONB), `created_at`. Confidence enum mapping (`weak→low`, `moderate→medium`, `strong→high`) mirrors the legacy `_coerce_insights` branch in hypothesizer.
- No `agent_chart` row here — the agent makes a separate `emit_chart(insight_id=...)` call after `persist_insight` returns.

**SSE events on success:** `InsightStartedEvent` (emitted by `translate_synthesis_chunk` at tool_call_started) followed by `InsightCompleteEvent` (at tool_call_complete with the returned `insight_id`).

**Error envelope:**

```json
{"ok": false, "code": "BAD_INPUT", "error": "supporting_row_ids: must be non-empty after FactPack filter"}
{"ok": false, "code": "MAX_INSIGHTS_EXCEEDED", "error": "session has already persisted N+1 insights"}
{"ok": false, "code": "DUPLICATE_NOOP", "error": "headline+row_ids hash already persisted in this session"}
```

**Auth/auth scope:** `session_id` is validated to (a) be a UUID, (b) refer to an existing `ai_session` row, (c) be in `status='running'`. The agent does NOT have to prove which insight — `session_id` is the security boundary. Bearer auth via `StaticBearer` is unchanged.

### 3.3 `finalize_session`

**Input schema:**

```python
class FinalizeSessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    status: Literal["succeeded", "partial", "failed"]
    token_estimate: int                          # >= 0
    reason: Optional[str] = None                 # required if status != "succeeded"
```

**Output:**

```python
class FinalizeSessionResult(BaseModel):
    session_id: str
    status: str
    insights_emitted: int
    duration_ms: int
    budget_status: Optional[str]                 # "normal" | "clipped"
```

**DB writes:** UPDATE `ai_session` SET `status`, `token_estimate`, `finished_at=now()`, `duration_ms`, `insights_emitted = (SELECT count(*) FROM ai_insight WHERE session_id=...)`, `budget_status`, `failure_reason=reason`.

**SSE event on success:** `SessionCompleteEvent`.

**Idempotency:** if the row's `status` is already terminal (`succeeded|partial|failed|complete|clipped`), the call returns `{ok:true, code:"ALREADY_FINALIZED", result: <previously committed result>}`. The driver's wall-clock fallback may also call `finalize_session(status="failed", reason="wall_clock_exceeded")` from outside the agent loop — this is the same idempotency path.

**Error envelope:**

```json
{"ok": false, "code": "BAD_INPUT", "error": "reason required when status != succeeded"}
```

### 3.4 `persist_brief`

**Input:**

```python
class PersistBriefInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str                              # parent AISession with key weekly-brief-YYYYWW
    period_start: date
    period_end: date                             # inclusive; >= period_start; <= +14d
    markdown: str                                # 1..50_000 chars
    model: str
    prompt_version: str                          # e.g. "brief_rules@v1"
```

**Output:**

```python
class PersistBriefResult(BaseModel):
    brief_id: str
```

**DB writes:** INSERT `brief_run` (existing model at `db/models.py:664`). Columns: `id`, `period_start`, `period_end`, `markdown`, `model`, `prompt_version`, `bullet_count` (server-computed), `tokens_in` / `tokens_out` (driver supplies via prompt; nullable), `latency_ms`, `published_at=now()`, `status='succeeded'`.

**SSE event on success:** none directly — `finalize_session` follows in the agent loop; the driver translates that into `SessionCompleteEvent`.

**Idempotency:**

- Per-session: a second `persist_brief` in the same `session_id` returns `{ok:false, code:"BRIEF_ALREADY_PERSISTED"}`.
- Per-period: an existing `brief_run` row with `(period_start, period_end)` and `status='succeeded'` returns `{ok:false, code:"BRIEF_DUPLICATE_PERIOD"}`. If existing row's status is `failed`, it is overwritten in place (UPDATE rather than INSERT).

**Error envelope:**

```json
{"ok": false, "code": "BAD_INPUT", "error": "period_end must be >= period_start and within 14 days"}
{"ok": false, "code": "BRIEF_DUPLICATE_PERIOD", "error": "brief already published for 2026-04-29..2026-05-05"}
{"ok": false, "code": "BRIEF_ALREADY_PERSISTED", "error": "session already persisted a brief"}
```

### 3.5 Tool registration order

Tools register in `mcp_server.py` in this order (read-tools first, write-tools last):

```
query_database, call_api, get_chart_data, web_search, run_skill,    # 5 read-tools
emit_chart, emit_citation,                                            # 2 existing write-tools (insight-scoped)
persist_insight, finalize_session, persist_brief                      # 3 new write-tools (session-scoped)
```

Total: 10 tools post Phase 4.

---

## 4. Agentic Synthesis Driver (Phase 2)

### 4.1 File: `backend/agents/insights/agentic_synthesis.py`

**Public signature:**

```python
async def run_agentic_synthesis(
    *,
    session_id: uuid.UUID,
    fact_pack: FactPack,
    mode: Literal["manual", "scheduled"],
    max_insights: int = 5,
    db: AsyncSession,
    sse_emit: Callable[[BaseEvent], Awaitable[None]] | None = None,
) -> SynthesisResult:
    """Drive one agentic synthesis turn end-to-end.

    Orchestration:
      1. Mark ai_session row status='running' (the orchestrator does this
         before calling us, so we just validate).
      2. Build messages = [
           {"role":"system","content": prompts.load("synthesis_rules")},
           {"role":"user","content": _user_pack(fact_pack, max_insights)},
         ]
      3. Open httpx.AsyncClient.stream against
         {settings.openclaw_gateway_url}/v1/chat/completions
         with x-openclaw-session-key={daily-synthesis-YYYYMMDD|manual-{session_id}}
      4. Drain SSE through translate_synthesis_chunk + SynthesisChunkAccumulator.
      5. For each TranslatedEvent yielded, call sse_emit(...) so the FastAPI
         StreamingResponse can forward to the React client (manual flow only;
         the scheduled flow passes sse_emit=None and we discard).
      6. Track caps in the accumulator; on trip, set acc.cap_reached and
         break out cooperatively.
      7. On normal completion (finalize_session arrived), return
         SynthesisResult(status="succeeded", insights_emitted=N,
                         token_estimate=int).
      8. On wall-clock / cap hit without finalize_session, call finalize_session
         MCP tool *server-side* with status="partial" or "failed" and reason.

    NEVER calls task.cancel().
    """
```

**Body composition (`_user_pack`):**

The full FactPack is NOT inlined in the prompt (FR-2.7). Instead we ship a small digest:

```json
{
  "today": "2026-05-06",
  "target_insight_count": 5,
  "factpack_digest": {
    "section_names": ["top_capacity_movers_24h", ...],
    "row_count_by_section": {"top_capacity_movers_24h": 12, ...},
    "total_rows": 132
  },
  "instructions": "Use query_database / get_chart_data / web_search / run_skill to drill into the FactPack. Persist each insight via persist_insight(session_id='<uuid>', ...). Emit one chart per insight via emit_chart(insight_id=<returned id>, spec=...). When you have <max_insights> insights or run out of evidence, call finalize_session(session_id='<uuid>', status='succeeded', token_estimate=...). Caps: 12 LLM turns, 30 tool calls, 600s wall."
}
```

The agent's own MCP `query_database` tool (already in V1) reads from the live FactPack-equivalent view in Postgres. The fact pack object passed to `run_agentic_synthesis` is held in memory for server-side `_coerce_insights`-equivalent row-id filtering inside `persist_insight` (Research §4.1 — supporting_row_ids filtering).

### 4.2 Cap counters

Held on the `SynthesisChunkAccumulator` (Section 5). The driver short-circuits when any of:

```python
if acc.tool_calls_completed >= 30:
    acc.cap_reached = "tool_cap"
elif acc.turns_completed >= 12:
    acc.cap_reached = "turn_cap"
elif (time.monotonic() - started) > 600:
    acc.cap_reached = "wall_clock"
```

On trip, the driver:

1. Sets `acc.cap_reached`.
2. `break`s out of `async for line in response.aiter_lines()`.
3. Lets `async with client.stream(...)` close (closes the upstream HTTP/2 stream cleanly).
4. Calls `finalize_session(session_id, status="partial" if insights_emitted >= MIN_INSIGHTS else "failed", reason=acc.cap_reached, token_estimate=acc.token_estimate)` directly via the MCP tool path (in-process call; no network round-trip).
5. Emits a synthetic `SessionCompleteEvent(budget_status="clipped")` for the SSE consumer.

### 4.3 Wall-clock guard

`asyncio.wait_for(driver_coro, timeout=600)` lives in the **caller** (`InsightOrchestrator.run_session` for manual; `_invoke_insights_daily` for scheduled). On `TimeoutError`, the caller invokes the same `finalize_session` server-side fallback as cap-trip. The driver's own `finally` block also runs on timeout.

### 4.4 SSE-event flow diagram

```
+---- httpx stream from OpenClaw -------------------------------------+
|                                                                     |
|  data: {choices:[{delta:{content:"Let me look at AWS..."}}]}        |
|     -> assistant text delta                                         |
|     -> ReasoningStepEvent (when no insight active) or               |
|        AssistantMessageTokenEvent (buffered into "current insight") |
|                                                                     |
|  data: {choices:[{delta:{tool_calls:[{id:"tc1",function:{           |
|        name:"query_database",arguments:'{"sql":"SELECT ..."}'}}]}}]}|
|     -> tool_call_started                                            |
|     -> ToolCallEvent("query_database", args_truncated, idx=N)       |
|        (treated like V1 reasoning step for FE rendering)            |
|                                                                     |
|  data: {choices:[{finish_reason:"tool_calls"}]}                     |
|     -> tool_call_complete                                           |
|     -> ToolResultEvent (db query result; OpenClaw round-trips MCP   |
|        and re-sends a follow-up turn -- we don't see the body)      |
|                                                                     |
|  ... agent reasons, eventually:                                     |
|                                                                     |
|  data: {choices:[{delta:{tool_calls:[{function:{name:               |
|        "persist_insight",arguments:'{...}'}}]}}]}                   |
|     -> tool_call_started (name=persist_insight)                     |
|     -> InsightStartedEvent(idx=acc.insight_idx,                     |
|                            headline=parsed_args["headline"][:80])   |
|                                                                     |
|  data: {choices:[{finish_reason:"tool_calls"}]}                     |
|     -> tool_call_complete (persist_insight returned ok)             |
|     -> InsightCompleteEvent(idx, insight_id from result)            |
|     -> acc.current_insight_id = result["insight_id"]                |
|     -> acc.insight_idx += 1                                         |
|     -> acc.insights_emitted += 1                                    |
|                                                                     |
|  data: {... emit_chart(insight_id=acc.current_insight_id, ...) ...} |
|     -> ChartEvent(insight_id, chart_id from result)                 |
|                                                                     |
|  data: {... finalize_session(...) ...}                              |
|     -> SessionCompleteEvent(status, total_insights)                 |
|     -> acc.finished = True; driver breaks loop                      |
|                                                                     |
|  data: [DONE]                                                       |
|     -> idempotent no-op (already finished)                          |
+---------------------------------------------------------------------+
```

**Special case — degraded close:** if the upstream closes with `finish_reason="stop"` and no `finalize_session` tool call was seen, the translator emits a synthetic `SessionCompleteEvent(status="degraded", reason="model_stopped_without_finalize")`. The driver then calls `finalize_session(status="failed", reason="model_stopped_without_finalize")` server-side.

---

## 5. Sibling SSE Translator (Phase 2)

### 5.1 File: `backend/openclaw/sse_translator.py` (extend)

Two coexisting translators in the same module: chat lane uses `translate_chunk(chunk, ChunkAccumulator)`; synthesis lane uses `translate_synthesis_chunk(chunk, SynthesisChunkAccumulator)`. The shared partial-tool-call delta logic is lifted into a private helper `_apply_tool_call_deltas(acc_pending_dict, tc_delta)` that both translators call.

### 5.2 `SynthesisChunkAccumulator`

```python
@dataclass
class SynthesisChunkAccumulator:
    session_id: str                                  # the AISession.id
    target_insight_count: int

    # Same partial-tool-call mechanics as ChunkAccumulator.
    tool_calls_by_index: dict[int, _PendingToolCall] = field(default_factory=dict)
    tool_calls_by_id: dict[str, _PendingToolCall] = field(default_factory=dict)

    # Synthesis-specific bookkeeping.
    insight_idx: int = 0                             # 0-based
    insights_emitted: int = 0
    current_insight_id: Optional[str] = None         # set after persist_insight returns
    chart_idx_within_insight: int = 0

    # Cap counters (Section 4.2).
    turns_completed: int = 0
    tool_calls_completed: int = 0
    token_estimate: int = 0
    cap_reached: Optional[str] = None                # "turn_cap" | "tool_cap" | "wall_clock"

    finalize_seen: bool = False
    finished: bool = False

    # Audit for the agent_message.tool_calls JSONB.
    tool_calls_log: list[dict[str, Any]] = field(default_factory=list)
```

### 5.3 `translate_synthesis_chunk` mapping table

| OpenClaw chunk shape | Action on accumulator | Emitted event(s) |
|---|---|---|
| `delta.content` non-empty AND `current_insight_id is None` | (no state change) | `SurveyingEvent(text=delta)` (buffered, not 1:1) |
| `delta.content` non-empty AND `current_insight_id is not None` | (no state change) | `ReasoningStepEvent(insight_id=..., text=delta)` |
| `delta.tool_calls[i]` first sight w/ `function.name` | populate `_PendingToolCall` via `_apply_tool_call_deltas` | `tool_call_started`-equivalent: see per-tool table below |
| `finish_reason == "tool_calls"` | for each pending: `tool_calls_completed += 1`; per-tool dispatch | per-tool completion event (below) |
| `finish_reason == "stop"` AND `finalize_seen` | `finished=True` | (no extra; finalize already emitted SessionComplete) |
| `finish_reason == "stop"` AND NOT `finalize_seen` | `finished=True; cap_reached="degraded"` | `SessionCompleteEvent(status="degraded")` |
| `finish_reason == "length"` | `cap_reached="length"; finished=True` | `SessionCompleteEvent(status="failed", reason="length")` |
| Gateway error frame (`{"error": ...}`) | `finished=True` | `ErrorEvent(...)` + synthetic `SessionCompleteEvent(status="failed")` |
| `[DONE]` | `finished=True` (idempotent) | (no-op if SessionComplete already emitted) |

**Per-tool-name dispatch on `tool_call_complete`:**

| `tool_name` | On started | On complete | Acc state change |
|---|---|---|---|
| `persist_insight` | `InsightStartedEvent(idx=acc.insight_idx, headline_draft=parsed_args.get("headline","")[:80])` | `InsightCompleteEvent(idx=acc.insight_idx, insight_id=result["insight_id"])` | `current_insight_id = result["insight_id"]; insight_idx += 1; insights_emitted += 1; chart_idx_within_insight = 0` |
| `emit_chart` | (none — chart emits on complete) | `ChartEvent(insight_id=acc.current_insight_id, chart=parsed_spec, idx=chart_idx_within_insight)` | `chart_idx_within_insight += 1` |
| `emit_citation` | (none) | (passive — citation logged but no synthesis event needed; FE renders from DB) | — |
| `finalize_session` | (none) | `SessionCompleteEvent(status=result["status"], insights_emitted=result["insights_emitted"], duration_ms=result["duration_ms"])` | `finalize_seen = True; finished = True` |
| `query_database` | `ToolCallEvent("query_database", args_truncated)` | `ToolResultEvent(ok=result.get("ok",True))` | (counter only) |
| `call_api` | `ToolCallEvent("call_api", ...)` | `ToolResultEvent(...)` | — |
| `get_chart_data` | `ToolCallEvent("get_chart_data", ...)` | `ToolResultEvent(...)` | — |
| `web_search` | `ToolCallEvent("web_search", ...)` | `ToolResultEvent(...)` | — |
| `run_skill` | `ToolCallEvent("run_skill", ...)` | `ToolResultEvent(...)` | — |

### 5.4 Why `_apply_tool_call_deltas` is shared

Both translators have identical code for "first delta sets `id`, second delta sets `function.name`, subsequent deltas accumulate `function.arguments`". Lifting that out keeps both translators tight and means a future bugfix to OpenAI tool-call streaming applies once.

The shared helper signature:

```python
def _apply_tool_call_deltas(
    pending_by_index: dict[int, _PendingToolCall],
    pending_by_id: dict[str, _PendingToolCall],
    tc_delta: dict[str, Any],
) -> _PendingToolCall | None:
    """Mutate the by_index / by_id maps; return the pending row that just
    transitioned from "incomplete" to "ready to emit started"
    (`name + tool_call_id` both set, started_emitted False), else None.
    """
```

### 5.5 Chat lane untouched

The chat lane import line in `forwarder.py` stays:

```python
from .sse_translator import (
    ChunkAccumulator,
    parse_sse_data_field,
    translate_chunk,
)
```

The synthesis driver imports a different set:

```python
from openclaw.sse_translator import (
    SynthesisChunkAccumulator,
    parse_sse_data_field,        # same parser
    translate_synthesis_chunk,
)
```

Zero blast radius on chat (PRD AC-4 / FR-X.6).

---

## 6. Orchestrator Wiring (Phase 2)

### 6.1 `run_session` branch

`backend/agents/insights/orchestrator.py::run_session` (line 273) gets a mode branch right after `_persist_session_start`:

```python
async def run_session(self, filters):
    self._started_monotonic = time.monotonic()
    filters = filters or {}

    try:
        yield self._build_event(SessionStartedEvent, ...)
        await self._persist_session_start(filters)

        # NEW: SYNTHESIS_MODE branch (Phase 2; flag removed in Phase 5).
        mode = os.environ.get("SYNTHESIS_MODE", "agentic")
        if mode == "agentic":
            # Build FactPack server-side (cheap; ~4-5K prompt tokens worth).
            fact_pack = await build_factpack(self.db)
            self._fact_pack = fact_pack

            # Hand off to agentic driver. It yields SSE events back through
            # an async queue we drain into the orchestrator's event stream.
            async for event in self._drive_agentic(
                fact_pack=fact_pack,
                mode="manual" if filters.get("created_by") != "scheduler" else "scheduled",
            ):
                yield event
            return

        # LEGACY path (Phase 5 deletes everything below this line).
        async for ev in self._phase_bootstrap_iter():
            yield ev
        ...
        async for ev in self._phase_hypothesize_iter():
            yield ev
        ...
        async for ev in self._phase_verify_and_synthesize_iter():
            yield ev
```

`_drive_agentic` is a thin generator that calls `run_agentic_synthesis` with an `sse_emit` callback that pushes onto an `asyncio.Queue`, then drains the queue under `asyncio.wait_for(timeout=600)`.

### 6.2 Reused helpers

The agentic loop reaches the DB by calling MCP write-tools, but those tools' bodies still want to share the same persistence shape as V1. We keep these orchestrator helpers but make them callable from the MCP tool layer:

| Helper (orchestrator method) | Used by | Status post-Phase-5 |
|---|---|---|
| `_persist_session_start(filters)` | orchestrator + `run_agentic_synthesis` (for FK setup) | Kept; small refactor to lift into `agents/insights/persistence.py` so MCP tools don't import an orchestrator instance. |
| `_persist_insight(insight_output, ordinal, embed)` | orchestrator (legacy) + `persist_insight` MCP tool | Kept (lifted to module-level function). Same DB write shape. |
| `emit_chart_for_insight(insight_id, chart_spec)` | orchestrator (legacy) + `emit_chart` MCP tool | Already lives in `tools/emit_chart.py`; no change. |

Phase 2 lifts `_persist_session_start` and `_persist_insight` to `agents/insights/persistence.py` so the MCP tool layer doesn't import an orchestrator instance. Phase 5's deletion of the legacy phases doesn't touch persistence — the helpers remain.

---

## 7. Phase 3 — Scheduler Retarget

### 7.1 File: `backend/pipeline/runner.py::_invoke_insights_daily`

The current implementation (line 390) instantiates `InsightOrchestrator` directly and drains its iterator. Phase 3 retargets:

```python
async def _invoke_insights_daily(session) -> dict:
    # 1. Idempotency guard (UNCHANGED — same query as today, line 425-442).
    today = date.today()
    existing = await session.execute(
        select(AISession.id).where(
            AISession.created_by == "scheduler",
            AISession.cron_run_date == today,
            AISession.status.in_(("running", "complete", "succeeded", "partial")),
        )
    )
    if existing.first() is not None:
        return {"fetched": 0, "stored": 0, "skipped": 1, "reason": "idempotency_guard"}

    # 2. Build FactPack server-side BEFORE OpenClaw turn (cheap, deterministic).
    from agents.insights.hypothesizer import build_factpack
    fact_pack = await build_factpack(session)

    # 3. Persist AISession row up front so finalize_session has a target.
    sid = uuid.uuid4()
    session_key = f"daily-synthesis-{today.strftime('%Y%m%d')}"
    ai_session_row = AISession(
        id=sid,
        session_key=session_key,
        status="running",
        started_at=datetime.utcnow(),
        focus="daily-cron",
        created_by="scheduler",
        cron_run_date=today,
        version="v3-agentic",
    )
    session.add(ai_session_row)
    await session.commit()

    # 4. Retry loop (same shape as today: 3 attempts, 60s backoff).
    last_exc = None
    for attempt in range(INSIGHTS_DAILY_MAX_RETRIES + 1):
        try:
            from agents.insights.agentic_synthesis import run_agentic_synthesis

            result = await asyncio.wait_for(
                run_agentic_synthesis(
                    session_id=sid,
                    fact_pack=fact_pack,
                    mode="scheduled",
                    max_insights=5,
                    db=session,
                    sse_emit=None,                        # cron has no SSE consumer
                ),
                timeout=INSIGHTS_DAILY_TIMEOUT_S,         # 600s
            )
            return {
                "fetched": fact_pack.total_rows(),
                "stored": result.insights_emitted,
                "session_id": str(sid),
                "session_key": session_key,
            }
        except asyncio.TimeoutError:
            # Wall-clock fallback: flip session row + finalize via MCP path.
            await _force_finalize(sid, status="failed", reason="wall_clock_exceeded")
            last_exc = TimeoutError("wall_clock_exceeded")
            if attempt < INSIGHTS_DAILY_MAX_RETRIES:
                await asyncio.sleep(INSIGHTS_DAILY_RETRY_SLEEP_S)
                continue
            raise last_exc
        except Exception as exc:
            await _force_finalize(sid, status="failed", reason=str(exc)[:200])
            last_exc = exc
            if attempt < INSIGHTS_DAILY_MAX_RETRIES:
                await asyncio.sleep(INSIGHTS_DAILY_RETRY_SLEEP_S)
                continue
            raise
```

### 7.2 Idempotency

Row pre-creation in step 3 closes the gap that the legacy code had (the legacy guard checks for `status in (running, complete)` AFTER orchestrator creates the row). The Phase 3 version explicitly creates the row, so a duplicate fire on the same day finds the row in `running` (or already terminal) and short-circuits.

### 7.3 Cron schedule unchanged

09:00 UTC, in-process APScheduler, same `JOB_CONFIG["insights_daily"]` block at `runner.py:115`. Only the adapter body changes.

---

## 8. Phase 4 — Weekly Brief Retarget

### 8.1 File: `backend/agents/weekly_brief.py::generate_weekly_brief`

Today (line 142) the function makes one `llm_client.reason()` call. Phase 4 rewrites to:

```python
async def generate_weekly_brief(session) -> BriefRun:
    period_end = datetime.utcnow().date()
    period_start = period_end - timedelta(days=7)

    # 1. Build context (UNCHANGED — _build_context at line 54 stays).
    context = await _build_context(session, period_start)

    # 2. Pre-create AISession row for the brief.
    iso_year, iso_week, _ = period_end.isocalendar()
    session_key = f"weekly-brief-{iso_year}{iso_week:02d}"
    sid = uuid.uuid4()
    session.add(
        AISession(
            id=sid,
            session_key=session_key,
            status="running",
            started_at=datetime.utcnow(),
            focus=f"weekly-brief-{period_start.isoformat()}",
            created_by="scheduler",
            version="weekly_brief_v2_agentic",
        )
    )
    await session.commit()

    # 3. Drive via OpenClaw with brief_rules system prompt + context user msg.
    from openclaw.brief_driver import drive_brief

    result = await asyncio.wait_for(
        drive_brief(
            session_id=sid,
            session_key=session_key,
            period_start=period_start,
            period_end=period_end,
            context=context,
            db=session,
        ),
        timeout=600,
    )

    # 4. drive_brief returns the brief_id once persist_brief was called.
    if result.brief_id is None:
        await _force_finalize(sid, status="failed", reason="no_brief_persisted")
        raise RuntimeError("weekly_brief: agent never called persist_brief")

    row = await session.get(BriefRun, result.brief_id)
    return row
```

### 8.2 `drive_brief` shape

Mirrors `drive_synthesis` (Section 4) with these differences:

- System message: `prompts.load("brief_rules")` instead of synthesis_rules.
- User message: the `_build_context(...)` JSON (week's insights + sites + events + edgar; ~5-10KB).
- Allowed tools: `query_database`, `web_search`, `persist_brief`, `finalize_session`. The agent SHOULD NOT call `persist_insight` or `emit_chart` in a brief session — these are not in the brief's tool palette section of `brief_rules.md` (instructional only; not enforced gateway-side).
- Cap: `target_persists=1`. After `persist_brief`, the agent calls `finalize_session(status="succeeded")`.

### 8.3 Schedule unchanged

Sunday 23:00 UTC, APScheduler. Only the adapter body changes.

---

## 9. Phase 5 — Deletion Checklist (Line-Anchored)

| Symbol | File | Lines | Reason |
|---|---|---|---|
| `_phase_bootstrap_iter` | `backend/agents/insights/orchestrator.py` | ~374-433 | Superseded by agentic loop (FR-5.1 sibling). |
| `_phase_hypothesize_iter` | `backend/agents/insights/orchestrator.py` | ~434-473 | Superseded by agentic loop. |
| `_phase_verify_and_synthesize_iter` | `backend/agents/insights/orchestrator.py` | ~474-700 | Superseded by agentic loop. |
| Legacy branch in `run_session` (the `else` arm after `if mode == "agentic"`) | `backend/agents/insights/orchestrator.py` | ~315-350 (post-Phase-2 layout) | Single code path. |
| `synthesize_insights` | `backend/agents/insights/hypothesizer.py` | 992-end-of-function (~1080) | Replaced by agentic loop (FR-5.2). |
| `_coerce_insights` | `backend/agents/insights/hypothesizer.py` | 951-991 | Coercion now lives in `persist_insight` MCP tool. |
| `_SYSTEM_PROMPT` | `backend/agents/insights/hypothesizer.py` | 906-end-of-string (~950) | Mega-prompt obsolete. |
| `_INSIGHT_OUTPUT_SCHEMA` | `backend/agents/insights/hypothesizer.py` | 858-905 | **KEEP** — reused by `persist_insight` Pydantic validation. |
| `InsightOutput` model | `backend/agents/insights/hypothesizer.py` | 143-156 | **KEEP** — reused by `persist_insight`. |
| `build_factpack` + section builders | `backend/agents/insights/hypothesizer.py` | 60-700 (approx) | **KEEP** — agentic synthesis still pre-builds a FactPack. |
| `tool_loop.py` (entire file) | `backend/agents/insights/tool_loop.py` | all | FR-5.1. |
| `tests/test_tool_loop_wrapper.py` | `backend/tests/test_tool_loop_wrapper.py` | all | Test of deleted module. |
| `tests/test_insights_tool_loop.py` | `backend/tests/test_insights_tool_loop.py` | all | Test of deleted module. |
| `_legacy_chat_handler` | `backend/routers/insights.py` | 930-1265 | FR-5.3. |
| `_chat_system_prompt` | `backend/routers/insights.py` | 879-921 | FR-5.3. |
| `_build_chat_context` | `backend/routers/insights.py` | 812-878 | FR-5.3. |
| `OPENCLAW_ENABLED` dispatcher branch | `backend/routers/insights.py` | 922-928 (the if/return) | FR-5.4 — always-on. |
| `openclaw_enabled` config field | `backend/config.py` | 61 | FR-5.4. |
| `synthesis_mode` config field (if added in Phase 2) | `backend/config.py` | (added Phase 2) | FR-5.6. |
| `OPENCLAW_ENABLED=1` line | `.env.example` | 25 | FR-5.7. |
| References to `openclaw_enabled` in `tests/test_v2_chat_isolation.py` | `backend/tests/test_v2_chat_isolation.py` | 210, 212 | FR-X.7 — env mutation removed. |
| References to `openclaw_enabled` in `tests/test_openclaw_forwarder.py` | `backend/tests/test_openclaw_forwarder.py` | 352, 422, 463, 484, 533, 590 | FR-X.7. |
| `llm/client.py` (if no callers) | `backend/llm/client.py` | conditional | If `synthesize_insights` was the only caller, prune. Likely still has callers (weekly_brief used to import it; post Phase 4 it doesn't); confirm via grep. |

**CI grep gate (FR-5.8):**

```bash
git grep -nE 'ToolLoopDriver|synthesize_insights|_legacy_chat_handler|_chat_system_prompt|_build_chat_context|OPENCLAW_ENABLED|SYNTHESIS_MODE' \
  backend/ \
  -- ':!backend/tests/fixtures/**' ':!backend/tests/golden/**' \
  > /tmp/grep.out
test ! -s /tmp/grep.out
```

Excludes test fixtures and golden recordings (which legitimately contain old strings).

---

## 10. Cross-Cutting Work

### 10.1 SOUL.md split (FR-X.1)

**Keep in `.openclaw/workspace/SOUL.md`** (identity + voice + safety + tool palette ONLY):

| Section | Original lines | Action |
|---|---|---|
| `## Identity` | 1-22 | **KEEP** but strip the "scoped to ONE specific insight at a time" + "Each chat session is keyed by an insight UUID" sentences — those are chat-mode-specific. |
| `## Voice` | 24-51 | KEEP wholesale. Mode-independent. |
| `## Identity rules` | 53-61 | KEEP first two bullets. STRIP the "scoped to this insight" line. |
| `## Schema knowledge` | 63-85 | KEEP wholesale. |
| `## Players` | 87-98 | KEEP wholesale. |
| `## Tool palette` | 100-127 | KEEP. UPDATE to mention 10 tools post Phase 4 (add `persist_insight`, `finalize_session`, `persist_brief` as items 8-10). |
| `## Citation rules` | 129-139 | KEEP. |
| `## Safety rules` | 141-148 | UPDATE: remove "There are no write tools" (no longer true). Replace with "Write tools (`persist_insight`, `emit_chart`, `emit_citation`, `finalize_session`, `persist_brief`) are append-only and validated server-side." |
| `## Out-of-scope redirect` | 150-157 | KEEP for chat mode; will be REMOVED in Phase 5 SOUL trim if mode-specific. Actually keep — applies to all modes ("don't engage with off-topic stuff"). |

**Move into `backend/agents/insights/prompts/chat_rules.md`:**

| Source section | Lines | Notes |
|---|---|---|
| Per-insight grounding contract | 159-176 | The "first system note in each session is the JSON context bundle" + "scoped to current insight" + "if user asks compare to insight X..." |
| First sentence of `## Identity` ("scoped to ONE specific insight at a time. Each chat session is keyed by an insight UUID...") | 8-13 | Move here. |
| First bullet of `## Identity rules` ("scoped to this insight") | (where applicable) | Move here. |

**Move into `backend/agents/insights/prompts/synthesis_rules.md`** (NEW content, written from scratch):

```markdown
# Synthesis mode

You are running a SYNTHESIS session. Your job is to produce {target_insight_count} insights from today's FactPack.

## Workflow

1. Review the FactPack digest in the user message. It tells you which sections have rows.
2. For each insight you produce:
   a. Use `query_database` or `get_chart_data` to drill into a specific section's rows.
   b. Optionally use `web_search` to corroborate (cap: 8 calls per session).
   c. Optionally use `run_skill` for known analysis patterns.
   d. Call `persist_insight(session_id="<uuid>", index=N, headline=..., body=..., supporting_row_ids=[...], confidence_signal=..., materiality=...)`.
   e. Immediately follow with `emit_chart(insight_id=<id from persist_insight>, spec={...})`.
3. After {target_insight_count} insights (or earlier if evidence is exhausted), call `finalize_session(session_id="<uuid>", status="succeeded", token_estimate=N)`.

## Caps

- 12 LLM turns max. Plan ~2 turns per insight: query, then persist.
- 30 tool calls max. Budget: ~5 tool calls per insight × 5 insights + 5 buffer.
- 600s wall clock max.
- 8 web_search calls max per session.

## Stop conditions (first to fire)

- You have called persist_insight {target_insight_count} times AND finalize_session once.
- Tool/turn/wall-clock cap reached — finalize with status="partial" or "failed".
- You see no further evidence — finalize with status="partial".

DO NOT write throwaway scratchpad turns. Be terse internally.
```

**Move into `backend/agents/insights/prompts/brief_rules.md`** (NEW):

```markdown
# Weekly brief mode

You are writing one weekly executive brief covering {period_start}..{period_end}.

## Workflow

1. Read the context JSON in the user message — it has the past week's insights, sites, events, EDGAR mentions.
2. Use `query_database` for any drill-down (e.g. cumulative MW for a specific company over the week).
3. Use `web_search` (cap: 8) for timely external context (e.g. a recent press release that lands a number in the brief).
4. Compose ONE markdown brief, ~600-1200 words, with:
   - Top 3 movers (by capacity / capital / count of new permits)
   - 1-2 anomalies worth surfacing
   - 1 forward-looking watch item
5. Call `persist_brief(session_id="<uuid>", period_start=..., period_end=..., markdown=..., model=..., prompt_version="brief_rules@v1")` exactly once.
6. Call `finalize_session(session_id="<uuid>", status="succeeded", token_estimate=N)`.

## Caps

- 12 LLM turns / 30 tool calls / 600s wall.
- persist_brief: 1 max per session.
```

**Loader: `backend/agents/insights/prompts/__init__.py`:**

```python
from functools import lru_cache
from pathlib import Path

_HERE = Path(__file__).resolve().parent

@lru_cache(maxsize=8)
def load(name: str) -> str:
    """Return the markdown body of prompts/<name>.md.

    Cached for the process lifetime; restart to pick up changes.
    """
    path = _HERE / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {name}")
    return path.read_text(encoding="utf-8")
```

### 10.2 Cost monitoring endpoint (FR-X.3)

**Route:** `GET /api/insights/cost-summary?days=7` (default 7).

**Pydantic response model:**

```python
class CostClassStats(BaseModel):
    sessions: int
    total_tokens: int
    avg_tokens_per_session: float
    p95_tokens_per_session: int

class CostSummary(BaseModel):
    window_days: int
    by_class: dict[Literal["synthesis", "brief", "chat"], CostClassStats]
    as_of: datetime
```

**SQL:**

```sql
SELECT session_key, status, token_estimate
FROM ai_session
WHERE started_at >= now() - interval ':days days'
  AND token_estimate IS NOT NULL;
```

Class derivation in Python:

```python
def _classify(session_key: str) -> str:
    if session_key.startswith("manual-") or session_key.startswith("daily-synthesis-"):
        return "synthesis"
    if session_key.startswith("weekly-brief-"):
        return "brief"
    if session_key.startswith("insight:"):
        return "chat"
    return "other"  # excluded from response
```

P95 computed in Python (volume < 200 rows/week per Research §6).

### 10.3 `HYPOTHESIZER_TOKEN_CEILING` bump (FR-X.2)

`backend/config.py`: `hypothesizer_token_ceiling: int = 80_000` (was 30_000). Warn-only — no abort. Logged as `WARN` when a session's `token_estimate > ceiling`.

The constant in `hypothesizer.py:64` (`HYPOTHESIZER_TOKEN_CEILING = 30_000`) is used only in the legacy `synthesize_insights` body which Phase 5 deletes. Until Phase 5 we read from settings instead of the module-level constant in any new code (keep the legacy module constant alone).

### 10.4 Rollback grace flag

During Phases 2-4: `SYNTHESIS_MODE=legacy|agentic` (default `agentic` once Phase 2 is GA). Setting `legacy` reverts the dispatcher in `orchestrator.run_session` to call `_phase_bootstrap_iter` etc. Once Phase 5 lands, the flag is removed (FR-5.6).

`OPENCLAW_ENABLED` stays as the chat dispatcher gate during Phases 2-4 (it gates `_legacy_chat_handler` vs `_openclaw_chat_handler`). It is removed in Phase 5 (FR-5.4).

---

## 11. Test Boundaries (Where to Mock)

| Test class | What's real | What's mocked |
|---|---|---|
| `test_agentic_synthesis.py` | `run_agentic_synthesis` orchestration logic, cap counters, SSE event mapping. | `httpx.AsyncClient.stream` (canned chat-completion-chunk fixtures); `mcp_server._invoke_session` (canned tool results). |
| `test_drive_openclaw_stream.py` | Shared `_drive_openclaw_stream` helper (extracted from forwarder). | `httpx.AsyncClient.stream`. |
| `test_translate_synthesis_chunk.py` | `translate_synthesis_chunk` + `SynthesisChunkAccumulator` as pure functions. | (none — no I/O.) |
| `test_persist_insight_tool.py` | Real `persist_insight` MCP body against test DB (sqlite or pg testcontainer). | Bearer auth (set env to known value). |
| `test_finalize_session_tool.py` | Real `finalize_session` body against test DB. | (same.) |
| `test_persist_brief_tool.py` | Real `persist_brief` body against test DB. | (same.) |
| `test_insights_daily_agentic.py` | `_invoke_insights_daily` retry + idempotency logic. | `run_agentic_synthesis` (returns canned `SynthesisResult`); `build_factpack` (returns minimal `FactPack`). |
| `test_weekly_brief_agentic.py` | `generate_weekly_brief` + `drive_brief`. | `httpx.AsyncClient.stream`; `mcp_server._invoke_session`. |
| `test_cost_summary.py` | New route handler against test DB. | (none — read-only SQL.) |
| `smoke_unified_agent.py` | Real OpenClaw + real MCP + real DB; mocked LLM via record/replay SSE fixture. | LLM upstream (OCI Llama Stack) replaced with a deterministic fixture replayer. Asserts: ≥3 `persist_insight` rows, ≥1 `query_database` + ≥1 `web_search` in `agent_tool_call`, exactly one `finalize_session` call. |

**Pre-Phase-5 golden SSE recording:** captured by running a canned chat session against the live OpenClaw lane in CI; bytes saved at `backend/tests/golden/chat_sse_v1.bin`. Post Phase 5, the same canned input run against the unified path must produce the same bytes (modulo tool_call_ids and timestamps, which the diff normaliser strips).

---

## 12. Sequencing & Blast-Radius Isolation

| Phase | What ships | Flag default | Rollback path |
|---|---|---|---|
| **Phase 2** | `agentic_synthesis.py`, `synthesis_driver.py`, `translate_synthesis_chunk`, `persist_insight`, `finalize_session`, SOUL split, token ceiling bump, prompts loader. `SYNTHESIS_MODE=agentic` default. | `agentic` | `SYNTHESIS_MODE=legacy` env flip → orchestrator re-enters `_phase_*_iter` paths (still present). One process restart. |
| **Phase 3** | `_invoke_insights_daily` retargeted. | `agentic` | `SYNTHESIS_MODE=legacy` honoured by the same orchestrator dispatch (`run_agentic_synthesis` is gated on the flag). |
| **Phase 4** | `weekly_brief.py` retargeted. `persist_brief` MCP tool. `brief_rules.md`. Sunday cron unchanged. | (independent — uses its own `weekly-brief-` namespace) | Git revert weekly-brief PR. Legacy `weekly_brief.py::generate_weekly_brief` body restored. |
| **Phase 5** | Delete legacy paths. Remove flags. CI grep gate. Cost-summary endpoint. Smoke test. Golden SSE diff. | (no flag) | Git revert deletion PR. Phase-5 is the only PR that breaks rollback by code; gated on **1-week burn-in of Phases 2-4**. |

**Burn-in metric:** during the burn-in week, every day's 09:00 UTC cron must produce ≥3 insights with ≥1 chart and ≥1 citation each (AC-1 + AC-6 mechanically checked). The Sunday brief in the burn-in week must publish a `brief_run` row (AC-3). Three consecutive sub-3-insight runs trigger the AC-10 STOP rule and halt Phase 5.

---

## 13. Open Questions / Decisions to Defer

1. **OQ-A. `_force_finalize` placement.** The driver's wall-clock and cap-trip fallback calls `finalize_session` server-side (in-process). Should that path go through the actual MCP tool body (cleaner; same idempotency rules) or directly UPDATE the `ai_session` row (faster; bypasses MCP layer)? Recommend: through the MCP tool body, called via a thin in-process invoker that does NOT round-trip through OpenClaw. Backend engineer to wire.
2. **OQ-B. SSE event class for synthesis tool errors.** When `persist_insight` returns `{ok:false, code:"BAD_INPUT"}`, the agent gets the error in its next turn and may retry. Do we surface a frontend-visible `ErrorEvent` (could spook the operator) or stay silent and let the FE see the eventual `InsightCompleteEvent` count drop? Recommend: silent for `BAD_INPUT`/`DUPLICATE_NOOP`; surface `ErrorEvent(retryable=true)` for `TOOL_FAILED`.
3. **OQ-C. Manual "Run again" with `mode="manual"` and a stale `daily-synthesis-YYYYMMDD` row.** The manual key is `manual-{session_id}` so they don't collide on the OpenClaw side. But the `/api/insights/latest` resolution returns whichever has the most recent `created_at` — if Karan clicks "Run again" at 09:30 UTC after the cron fired at 09:00 UTC, the manual run wins. This is intended; confirm with PM.
4. **OQ-D. `bullet_count` derivation in `persist_brief`.** The legacy weekly-brief computed `bullet_count = markdown.count("\n- ") + markdown.count("\n* ")`. Move that into the `persist_brief` tool body (server-side, not agent-supplied) for tamper resistance. Backend engineer to confirm.
5. **OQ-E. Token-estimate sourcing.** Research §6.1 prefers `stream_options.include_usage:true` for exact provider counts. OCI Llama Stack support for that field is unverified. Backend engineer to test in dev; fall back to `_accounted_tokens` heuristic if the provider drops the field. The estimate flows from the driver into `finalize_session(token_estimate=N)`.

---

## Appendix A — File Path Index (absolute)

- PRD: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/plans/ai-insights-automation/14-unified-agent-prd.md`
- Research: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/plans/ai-insights-automation/14-unified-agent-research.md`
- This doc: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/plans/ai-insights-automation/14-unified-agent-architecture.md`
- MCP server: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/mcp_server.py`
- Forwarder: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/forwarder.py`
- SSE translator: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/sse_translator.py`
- Orchestrator: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/orchestrator.py`
- Hypothesizer: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/hypothesizer.py`
- Pipeline runner: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/pipeline/runner.py`
- Weekly brief: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/weekly_brief.py`
- Insights router: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/routers/insights.py`
- SOUL: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/.openclaw/workspace/SOUL.md`
- AISession model: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/db/models.py:39`
- BriefRun model: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/db/models.py:664`

---

**End of architecture document.**
