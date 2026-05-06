# 14 — Unified Agent Research (OpenClaw Phases 2-5)

**Author:** Researcher
**Date:** 2026-05-06
**Scope:** Phases 2-5 of the OpenClaw unification — server-driven sessions for daily-synthesis & weekly-brief, SSE-event-taxonomy reconciliation, in-session caps, write-only MCP tools, persona/system-prompt strategy, cost monitoring.

**Companion docs:**
- `11b-openclaw-migration-architecture.md`
- `11c-openclaw-migration-addendum.md`
- `13-mcp-migration-architecture.md`
- `14-unified-agent-prd.md` (PM)

---

## §1 — Server-driven OpenClaw sessions for daily-synthesis & weekly-brief

### Background

`backend/openclaw/forwarder.py::forward_chat()` is the only OpenClaw producer today. It is shaped specifically for *interactive* chat: it persists the inbound `user_text` to `agent_message` BEFORE dialling OpenClaw (audit invariant, ARCH 11b §6.1), then opens an SSE stream against `POST /v1/chat/completions` with a single `{"role":"user","content":<text>}` body, hard-codes the session key as `f"{settings.openclaw_session_prefix}{insight_id}"`, and on completion writes one assistant `agent_message` row with `tool_calls` JSONB and the final text.

For Phase 2-5 daily-synthesis / weekly-brief flows the agent runs *headless* (cron-triggered, no frontend). The orchestrator must POST a "FactPack as user message" turn, drain the SSE, and persist the agent's emissions through MCP write-tools (persist_insight, persist_brief, finalize_session). The audit shape is different too: the FactPack JSON should NOT pollute the chat thread (no thread_id at all for synthesis sessions; only AISession + AIInsight + AgentChart).

### Q1.1 — Refactor vs. parametrise `forward_chat`?

`forward_chat` and a synthesis driver share five mechanics:

1. httpx.AsyncClient stream against `POST /v1/chat/completions`.
2. Bearer + `x-openclaw-session-key` headers.
3. Line-by-line SSE drain.
4. `parse_sse_data_field` + `translate_chunk` + `ChunkAccumulator`.
5. Synthetic `MessageCompleteEvent` terminator on abnormal close.

They diverge on FOUR concerns:
- (a) request body composition: synthesis must ship a system message + the FactPack user message; chat ships only the user message;
- (b) pre-call DB write: chat persists the user turn first; synthesis must NOT (the FactPack is not a user message);
- (c) post-call DB write: chat persists exactly one assistant `agent_message`; synthesis persists nothing here (the agent itself calls `persist_insight` MCP write-tools mid-stream);
- (d) accumulator identity: chat has thread_id+message_id; synthesis has session_id only.

Adding `(session_key, system_message_override, user_message, no_db_persistence_of_user_msg)` to `forward_chat` would force every chat caller to pass three extra knobs and would entangle two different audit-row policies inside one async generator.

A cleaner factoring is to extract the shared mechanics into a small private helper (`_drive_openclaw_stream(*, url, headers, body, acc) -> AsyncIterator[TranslatedEvent]`) that yields *parsed events* (not raw bytes) and to keep two thin drivers on top:
- `forward_chat(...)` — chat-specific pre/post DB writes + raw-byte yielding for `StreamingResponse`.
- `drive_synthesis(...)` — synthesis-specific request body assembly + per-tool-call side-effect dispatch.

This keeps the chat lane bit-identical to today's behaviour (PRD R5 wire-contract invariant) and lets the synthesis driver consume *typed events*, which is exactly what the per-tool-call dispatcher needs (Q2 below).

**Recommendation:** Do NOT parametrise `forward_chat`. Extract `_drive_openclaw_stream` (or `_consume_openclaw_sse`) as a sibling helper and add `drive_synthesis` next to `forward_chat`. Keeps the chat lane's blast radius at zero.

### Q1.2 — Where does the SYNTHESIS system prompt live? (a) inject vs. (b) workspace-file selection

`.openclaw/openclaw.json` shows OpenClaw's gateway is configured purely with model providers, MCP servers, and gateway auth/CORS. There is **no** `agents.persona` / `agents.workspaceFile` selector keyed by `sessionKey` prefix. The upstream OpenClaw config docs confirm: per-sessionKey persona file selection is not a documented config feature today.

`.openclaw/workspace/SOUL.md` is currently the gateway's *standing* persona for any session that lands on it. Today's chat lane sends `messages: [{"role":"user","content":<text>}]` — i.e. ZERO system messages from FastAPI — and relies entirely on SOUL.md.

Two real options:
- **(a) Inject system message from FastAPI side.** Synthesis driver builds `messages: [{"role":"system","content":<SYNTHESIS_RULES.md content>}, {"role":"user","content":<factpack-json>}]`. OpenClaw forwards verbatim to the model. SOUL.md still loads first (gateway-side identity) but the injected `system` follows it. Multiple `system` messages concatenate; the model sees identity (SOUL) + mode rules (SYNTHESIS_RULES). Chat lane stays untouched — no system message — so SOUL.md alone governs chat (or, after Phase 5 cleanup, we can also inject CHAT_RULES.md into chat).
- **(b) Workspace-file routing by sessionKey prefix.** Would require an OpenClaw feature that does not exist today.

**Recommendation:** **(a) — inject from FastAPI.** Concretely: store `SYNTHESIS_RULES.md` under `backend/agents/insights/prompts/synthesis_rules.md`, read once at module import (lru-cached), and pass as the `content` of the leading `system` message in `drive_synthesis`. Tighten SOUL.md to identity + voice + safety only.

### Q1.3 — Write-only MCP tools shape vs. existing read-tools

Existing seven tools in `backend/mcp_server.py` all share one envelope: `{ok: bool, result|error, code}` returned from `_invoke()` which (a) UUID-validates `insight_id`, (b) opens an async DB session, (c) builds a `SkillContext` via `build_skill_ctx`, (d) dispatches via `agents.insights.tools.registry.dispatch`. `emit_chart` / `emit_citation` are already write-tools, so "read vs write" is not actually a structural distinction at the MCP-handler layer.

Concretely, every new write-tool should:
1. Validate `session_id` (and for `persist_insight`, `index`) up front; surface bad-input as `{ok: false, code: "BAD_INPUT"}` rather than a 500.
2. Open a fresh async DB session via the same `async_session_factory` the existing `_invoke` uses. Synthesis sessions do NOT have `insight_id` for these tools — see Q4 schema — so the helper needs to skip the `insight_id` UUID check, OR the new tools should use a separate `_invoke_session` helper that takes `session_id` instead.
3. Run the side effect inside a try/except that rolls back on failure, logs structured, and returns the `{ok: false, code: "TOOL_FAILED"}` envelope.
4. Return a small JSON body. For `persist_insight` the body should include the new `ai_insight.id` so the agent can subsequently call `emit_chart(insight_id=...)` against it (this is the ONLY load-bearing field in the response).

**Recommendation:** Treat `persist_insight` / `persist_brief` / `finalize_session` as direct extensions of the `emit_chart` shape: same auth, same envelope, same `_invoke`-style dispatcher (lift to `_invoke_session(name, session_id, args)` to skip the insight_id requirement; reuse rollback + JSON-envelope logic).

### Q1.4 — OpenAI tool-call chunk shape via OpenClaw

The OpenAI `chat.completion.chunk` shape that streams tool calls is well-documented. `backend/openclaw/sse_translator.py::translate_chunk` ALREADY handles this contract correctly (lines 232-288). OpenClaw's `api: "openai-completions"` provider mode is a passthrough.

**Recommendation:** Keep `translate_chunk` as the single OpenAI-chunk parser; the synthesis driver consumes its `TranslatedEvent` output. Q2 covers how to bridge those events into the legacy synthesis taxonomy.

**Q1 Recommendation (rolled up):** Extract `_drive_openclaw_stream` and add `drive_synthesis` as a sibling to `forward_chat`. Inject SYNTHESIS_RULES via a leading `system` message from FastAPI. Model new write-tools on `emit_chart`. No translator change required.

---

## §2 — SSE event-taxonomy gap (chat lane vs synthesis lane)

### Background

Chat lane today emits 5 translated events: `assistant_message_token`, `tool_call_started`, `tool_call_complete`, `message_complete`, `error`. V1 synthesis lane emits 7 frontend-consumed events: `session_started`, `surveying`, `reasoning_step`, `insight_started`, `chart`, `insight_complete`, `session_complete`.

When the OpenClaw-backed synthesis agent calls `persist_insight` (MCP write-tool), the frontend SessionRunner expects the legacy `insight_started` + `chart` + `insight_complete` events to flow.

### Three options compared

| Option | Where translation lives | Blast radius on chat | Conceptual cost |
|---|---|---|---|
| **A — extend `translate_chunk`** | inside `sse_translator.py` | high — chat consumes whatever this function yields. Even if the chat dock ignores them, the audit-row writer at line 156-162 of `forwarder.py` will see new event class names. | low; one function. |
| **B — sibling `translate_synthesis_chunk(chunk, acc)`** | in `sse_translator.py` next to `translate_chunk` | zero — chat path keeps calling `translate_chunk`; synthesis driver calls the new sibling. | medium; some boilerplate duplication unless lifted into a shared helper. |
| **C — emit synthesis events from inside `persist_insight` body into a per-session asyncio.Queue** | inside MCP tool body + a session→queue dict | zero on the SSE-translator side, but tightly couples the MCP tool to the synthesis driver's event loop. | high — cross-cuts module boundaries; harder to test. |

### Why B is the right choice

- **Chat invariant.** PRD R5 forbids drift. Option A risks silent drift even if the chat dock ignores unknown events.
- **Single-point translation.** The synthesis driver wants to *fan out* tool-calls to side-effect handlers. Option B places that fan-out logic in one place where the test surface is small.
- **Testability.** A sibling translator is a pure function. Easy to test against canned OpenAI chunks.
- **Refactor option.** The `_PendingToolCall` accumulator can be lifted into a shared `_apply_tool_call_deltas(acc, delta)` helper that BOTH translators call.

### Concrete touchpoints

1. New `backend/openclaw/sse_translator.py::translate_synthesis_chunk(chunk, acc) -> list[SynthesisEvent]`.
2. `acc` is `SynthesisChunkAccumulator(session_id, current_insight_idx, current_insight_id, ...)` — tracks which `persist_insight` index is "live" so subsequent `emit_chart` calls within the same insight pair correctly.
3. Tool-name dispatch table:
   - `persist_insight` → on tool-call-complete: emit `InsightStartedEvent(headline_draft=parsed_args.headline)` then `InsightCompleteEvent(...)` from the tool result envelope.
   - `emit_chart` → on tool-call-complete: emit `ChartEvent(insight_id=current_insight_id, chart=parsed_spec)`.
   - `finalize_session` → emit `SessionCompleteEvent(...)` from the tool result.
   - any other tool-call (query_database, call_api, run_skill, web_search) → emit `ReasoningStepEvent` / `ToolCallEvent` so SessionRunner's existing UI treats it like a V1 reasoning step.
4. Synthesis driver yields these synthesised events through `to_sse_text` to the StreamingResponse.

**Q2 Recommendation:** **Option B.** Add `translate_synthesis_chunk` as a sibling to `translate_chunk`. Lift the partial-tool-call accumulator helpers into a shared private function. Chat lane keeps calling `translate_chunk` verbatim — zero blast radius on chat.

---

## §3 — In-session caps (12 turns / 30 tools / 600s)

### Q3.1 — Does OpenClaw config expose per-session caps?

Confirmed against the upstream config reference and the local `.openclaw/openclaw.json`: there is **no per-session turn-cap, tool-cap, or wall-clock cap** configurable at the gateway. The only related lever is provider-level `timeoutSeconds: 300` per single LLM round-trip.

### Q3.2 — Client-side enforcement plan

- **Wall-clock 600s.** `asyncio.wait_for(driver_coro, timeout=600)` wrapper at the call site. On TimeoutError the driver's `finally` block runs and we issue the synthetic `SessionCompleteEvent(budget_status="clipped")` plus `finalize_session` MCP write-tool with reason="wall_clock". The httpx `_OPENCLAW_TIMEOUT` is per-frame read timeout, NOT a session cap.

- **Tool-call cap (30).** Increment a counter in the `SynthesisChunkAccumulator` on every `tool_call_complete`. Once the counter hits 30, set a flag `cap_reached`. After the cap, the driver short-circuits the SSE drain. It then runs ONE final cleanup turn:
  1. POST `/v1/chat/completions` with the prior session_key and a single user message: `"You have reached the 30-tool-call cap for this session. Stop calling tools and emit a final finalize_session(reason='tool_cap') tool call now."`
  2. Drain that follow-up's SSE until `finalize_session` arrives (or its own 30-second mini-timeout fires).
  3. If the cleanup turn itself attempts another tool, block it client-side and just call `finalize_session` server-side.

- **Turn cap (12).** Increment on each `message_complete` AND each `finish_reason == "tool_calls"`. Same cleanup procedure as the tool-cap.

### Q3.3 — How to tell OpenClaw to stop?

OpenAI-style streaming has no "cancel this generation" frame. Replicate the `forward_chat` pattern: set `acc.cap_reached = True`, break the SSE loop, exit the `async with client.stream(...)` context manager (closes the connection cleanly). Avoid `task.cancel()` to prevent httpx connection-pool leaks (httpx issues #1461, #2437).

**Q3 Recommendation:** Enforce all three caps client-side. Wall-clock via `asyncio.wait_for(driver, 600)`; turn/tool caps via accumulator counters + clean break + cleanup turn. NEVER use `task.cancel()` to stop the stream.

---

## §4 — New MCP write-tools

### Q4.1 — `persist_insight`

**Input schema (Pydantic):**

| Field | Type | Notes |
|---|---|---|
| `session_id` | `str` (UUID) | Validated; session must exist and status='running'. |
| `index` | `int` | 0-based ordinal within the session. |
| `headline` | `str` | <=240 chars; required. |
| `body` | `str` | Markdown-tolerant; <=4000 chars. |
| `confidence_signal` | `Literal["weak","moderate","strong"]` | Mapped server-side to `confidence` enum (low/medium/high) using same mapping as `_coerce_insights`. |
| `materiality` | `Literal["low","medium","high"]` | Stored verbatim. |
| `supporting_row_ids` | `list[str]` | Subjected to the same `_coerce_insights` filter — drop any row_id not in the session's FactPack. Reject if filtered list is empty. |
| `skills_run` | `list[str]` | Default `[]`. |
| `chart_type` | `Optional[str]` | Hint for deterministic chart builder. |
| `chart_y_label` | `Optional[str]` | Same. |

(Schema mirrors `InsightOutput` in `hypothesizer.py:143-155`.)

**Output:** `{ok, result: {insight_id, idx}, code?, error?}`

**Persistence:** writes one `ai_insight` row.

**Idempotency:** session-scoped in-memory dedupe set on `sha256(session_id, headline_normalised, supporting_row_ids_sorted)[:16]`. On collision: `{ok: true, code: "DUPLICATE_NOOP"}`. DB-side unique constraint on `(session_id, idx)` is the durable backstop.

**Validation:** `_coerce_insights` parity; headline non-empty after strip; confidence_signal enum match; index monotonic per session.

### Q4.2 — `emit_chart` (existing tool, refinement)

No new tool. `emit_chart(insight_id, spec)` already validates and recomputes row_hash. The synthesis translator captures the call and synthesises a `ChartEvent`. Confirm `build_skill_ctx` accepts a freshly-minted insight_id without falling back to a "current insight" sentinel.

### Q4.3 — `finalize_session`

**Input:**

| Field | Type | Notes |
|---|---|---|
| `session_id` | `str` (UUID) | Required. |
| `reason` | `Literal["normal","tool_cap","turn_cap","wall_clock","error"]` | Driver supplies cap-reason. |
| `token_estimate` | `Optional[int]` | Sum of prompt + completion across all turns. |
| `notes` | `Optional[str]` | Persisted to `ai_session.focus` if focus is null. |

**Output:** `{ok, result: {session_id, status, insights_emitted, duration_ms, budget_status}, code?, error?}`

**Persistence:** updates `ai_session` in place (`finished_at`, `status` = "complete"|"clipped", `duration_ms`, `insights_emitted` (counted from `ai_insight`), `budget_status`, `token_estimate`).

**Idempotency:** if status already terminal, `{ok: true, code: "ALREADY_FINALIZED"}`.

### Q4.4 — `persist_brief`

I could not locate a `BriefRun` SQLModel directly in `db/models.py`. **Action for architect:** confirm canonical persistence model (likely lives in `backend/db/models.py` next to `EnergyProject`, etc., not the agents-specific `db/models.py`). Tentative shape:

| Field | Type | Notes |
|---|---|---|
| `session_id` | `str` (UUID) | Parent AISession. |
| `period_start` | `date` | Inclusive. |
| `period_end` | `date` | Inclusive. |
| `markdown` | `str` | Brief markdown body. |
| `model` | `str` | Model id used. |
| `prompt_version` | `str` | "weekly_brief_v2_agentic". |
| `bullet_count` | `int` | Driver-computed. |
| `tokens_in` / `tokens_out` | `int` | From driver accounting. |
| `latency_ms` | `int` | Wall-clock of the LLM session. |

**Idempotency:** `(period_start, period_end)` unique; collision → return existing brief id with `code: "DUPLICATE_NOOP"`.

### Q4.5 — Authorization

The bearer scheme in `backend/mcp_server.py::StaticBearer` is sufficient. No additional ACL needed.

**Q4 Recommendation:** Three new write-tools modelled on `emit_chart`. Add `_invoke_session(name, session_id, args)` helper for session-scope tools. Idempotency via in-memory per-session dedupe set + DB unique constraints. `_coerce_insights`-equivalent row_id filter inside `persist_insight`.

---

## §5 — SOUL.md split

### The collision

`SOUL.md` today contains:
- Identity: "Datacenter & Power Analyst" (mode-independent).
- Voice rules: terse, no hedging (mode-independent).
- "Scoped to ONE specific insight at a time" (chat-mode only — wrong for synthesis).
- "Each chat session is keyed by an insight UUID and opens with a system note" (chat-mode only).
- Tool palette (mode-independent).
- "Per-insight grounding contract" with the JSON context bundle assumption (chat-mode only).

For synthesis sessions the agent is given a *FactPack* and produces 3-5 insights. The "scoped to one insight" rule is actively wrong.

### Three options

**(a) Workspace per prefix.** Requires upstream OpenClaw feature that doesn't exist.
**(b) One SOUL.md with a sessionKey-prefix mode switch.** Works without code changes but mixes two opposing modes.
**(c) Inject right system prompt from FastAPI at request time.**
- SOUL.md = identity + voice + safety + tool palette ONLY (mode-independent).
- `chat_rules.md` = "scoped to one insight, opens with insight context bundle" — injected by `forward_chat` as leading `system` message (post-Phase 5 cleanup).
- `synthesis_rules.md` = "produce 3-5 insights from this FactPack, call persist_insight + emit_chart + finalize_session" — injected by `drive_synthesis`.

### Compatibility with `forward_chat`

`forward_chat` lines 117-121 ship `messages: [{"role":"user","content":user_text}]` — no system message. Adding a leading `system` message is a one-line change. OpenClaw's `api: "openai-completions"` passes messages through verbatim; multiple system messages compose normally.

**Q5 Recommendation:** **Option (c).** Tighten SOUL.md to identity + voice + safety + tool palette only. Move per-mode rules into `backend/agents/insights/prompts/{chat,synthesis}_rules.md`. Inject the appropriate file as a leading `system` message from FastAPI in both lanes. No OpenClaw config change required.

---

## §6 — Cost monitoring shape

### Q6.1 — Where do token counts come from?

Three candidates:

1. **Provider response (best).** OCI Llama Stack is OpenAI-compatible. Set `stream_options: {include_usage: true}` in the request body; the FINAL chunk carries `{"usage": {"prompt_tokens", "completion_tokens", "total_tokens"}}`. Verify OCI Llama Stack supports this; if yes, exact tokens per turn.
2. **`_accounted_tokens` helper** (`hypothesizer.py:940-948`) — already computes `{prompt, completion, total}` from a `turn` object. Today just `print()`-ed.
3. **Heuristic** — `len(prompt)/4 + len(completion)/4` as fallback.

**Recommendation:** (1) with (3) as fallback.

### Q6.2 — Schema: `ai_session.token_estimate`?

**It already exists.** `backend/agents/insights/db/models.py:62`:

```python
# Phase 2 (migration 013): post-flight token accounting (D7).
token_estimate: Optional[int] = Field(default=None)
```

Action: verify the column exists in the live dev DB (`\d ai_session` quick check). If shipped, no new migration needed. Otherwise:

```sql
ALTER TABLE ai_session ADD COLUMN IF NOT EXISTS token_estimate INTEGER NULL;
```

(idempotent; no backfill).

### Q6.3 — `/api/insights/cost-summary` shape

```
GET /api/insights/cost-summary?days=7

Response:
{
  "window_days": 7,
  "model": "oci/openai.gpt-5.4",
  "totals": {
    "sessions": int,
    "tokens_total": int,
    "tokens_avg_per_session": float,
    "duration_ms_avg": int
  },
  "rolling_avg_tokens_per_day": [
    {"date": "2026-04-30", "sessions": 3, "tokens": 412345}, ...
  ],
  "top_sessions_by_tokens": [
    {"session_id": "...", "started_at": "...", "tokens": 78340, "version": "v3"}
  ]
}
```

Implementation: SELECT from `ai_session` WHERE `started_at >= now() - interval '7 days'` and `token_estimate IS NOT NULL`. Group by `date(started_at)`. Volume is small (1-3 sessions/day), so Python computation is fine.

**Q6 Recommendation:** No new migration needed (column exists). `finalize_session` MCP tool persists `token_estimate`. `/api/insights/cost-summary` is a small SQL + JSON shape over `ai_session`.

---

## §G — Final Recommendations Table

| Question | Decision | Rationale | Touchpoints |
|---|---|---|---|
| Q1.1 — Refactor `forward_chat`? | NO. Extract `_drive_openclaw_stream` helper + add `drive_synthesis` sibling. | Chat and synthesis differ on body composition, pre/post DB writes, accumulator identity. | `backend/openclaw/forwarder.py` (extract helper); new `backend/openclaw/synthesis_driver.py`. |
| Q1.2 — System prompt placement | (a) Inject from FastAPI as leading `system` message. | OpenClaw config does not support per-sessionKey workspace selection. Composes cleanly with SOUL.md. | `drive_synthesis` body builder; `backend/agents/insights/prompts/synthesis_rules.md` (new). |
| Q1.3 — Write-tool template | Model on `emit_chart`. | Already a write-tool. Same envelope, same auth, same dispatcher. | `backend/mcp_server.py`: add `_invoke_session` helper + 3 new `@mcp.tool()` handlers. |
| Q1.4 — OpenAI tool-call chunk shape | Confirmed; `translate_chunk` already handles it correctly. | Existing translator matches the OpenAI streaming spec. | None. |
| Q2 — Synthesis SSE translator | Option B: sibling `translate_synthesis_chunk`. | Zero blast radius on chat (PRD R5). Single translation point. | `backend/openclaw/sse_translator.py`. |
| Q3 — Caps enforcement | Client-side. `asyncio.wait_for(driver, 600)`; turn (12) + tool (30) counters; clean break + cleanup turn; never `task.cancel()`. | OpenClaw exposes no per-session caps. httpx pool integrity requires clean break-out. | `drive_synthesis` driver loop; `SynthesisChunkAccumulator`. |
| Q4 — New write-tools schema | `persist_insight`, `finalize_session`, `persist_brief`. Idempotency via in-memory per-session dedupe + DB uniqueness. `_coerce_insights`-style row_id filter. | Mirrors `InsightOutput` shape; preserves validation parity with hypothesizer. | `backend/mcp_server.py`; `backend/db/models.py` (BriefRun confirmation). |
| Q5 — SOUL split | Option (c). Tighten SOUL.md to identity-only; per-mode rules in `prompts/{chat,synthesis}_rules.md` injected by FastAPI. | OpenClaw has no per-sessionKey workspace switch. Mode rules belong with the code that knows the mode. | `.openclaw/workspace/SOUL.md` (slim); `backend/agents/insights/prompts/*.md` (new); `forward_chat` + `drive_synthesis`. |
| Q6 — Cost monitoring | No new migration needed — `ai_session.token_estimate` already exists (migration 013). `finalize_session` writes it. New `/api/insights/cost-summary` route. | `db/models.py:62` has the column. | `finalize_session` MCP tool; new cost-summary route. |

---

### Sources

- [OpenAI Chat Completions streaming events](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events)
- [OpenAI cookbook — How to stream completions](https://github.com/openai/openai-cookbook/blob/main/examples/How_to_stream_completions.ipynb)
- [OpenClaw Gateway Configuration](https://openclaw-ai.com/en/docs/gateway/configuration)
- [HTTPX async stream early-close discussion #2550](https://github.com/encode/httpx/discussions/2550)
- [HTTPX async stream cancel pool issue #1461](https://github.com/encode/httpx/issues/1461)
