# 15 — QA-lane Translator Research

**Author:** Research Agent
**Date:** 2026-05-06
**Status:** Input for architect (sibling of 15-agent-unification-cleanup-prd.md)
**Predecessor (design lineage):** `14-unified-agent-architecture.md` §5 (sibling-translator pattern).

---

## Research Question

What is the cleanest extension pattern for adding a third translator to `backend/openclaw/sse_translator.py` that maps OpenClaw `chat.completion.chunk` frames into the **frozen** `QAEvent` discriminated union (`schemas/qa.py`) consumed by the frontend `useQA` hook, without disturbing the chat-lane (`translate_chunk`) or synthesis-lane (`translate_synthesis_chunk`) translators?

---

## Options Considered

### Option A — Sibling translator named `translate_qa_chunk` + `QAChunkAccumulator` (RECOMMENDED)

- Mirrors the existing naming pattern: `translate_chunk` (chat) and `translate_synthesis_chunk` (synthesis).
- Lives in the same `sse_translator.py` file, below the synthesis translator.
- Introduces a new accumulator dataclass tailored to QA's needs (small: per-tool args buffer, per-tool name, citation-dedupe set, chart-spec-already-emitted flag, finished flag).
- Returns `list[QATranslatedEvent]` where the union is `TextChunkEvent | ToolCallEvent | ToolResultEvent | ChartSpecEvent | CitationEvent | DoneEvent | ErrorEvent`.
- Reused via the existing `_drive_openclaw_stream` helper (`forwarder.py` line 319) — that helper is already driver-agnostic on `accumulator`/`translator`.

### Option B — Reuse `ChunkAccumulator` and post-translate

- Map chat-lane events to `QAEvent` shapes after `translate_chunk` returns.
- Rejected: `QAEvent.tool_call.args` is a `dict`, not a 200-char `args_truncated` string — information is lost. `ChartSpecEvent` and `CitationEvent` have no analogue in the chat-lane union, so chart and citation surfacing is impossible.

### Option C — Lift a shared `_apply_tool_call_deltas` helper, then add the QA translator

- Architecturally cleaner; reduces ~30 lines of triplicated buffer logic.
- Rejected for now: ARCH §5.4 already proposed this lift, and the synthesis translator silently inlined the duplicate. Touching the chat-lane to introduce a helper is a higher-blast-radius change. Defer to a dedicated refactor PR.

---

## Recommendation

Adopt **Option A**. Concretely:

### 1. Naming

- **Translator function:** `translate_qa_chunk(chunk, acc) -> list[QATranslatedEvent]`
- **Accumulator dataclass:** `QAChunkAccumulator`
- **Type alias:** `QATranslatedEvent = TextChunkEvent | ToolCallEvent | ToolResultEvent | ChartSpecEvent | CitationEvent | DoneEvent | ErrorEvent`

This matches the existing `translate_chunk` / `ChunkAccumulator` and `translate_synthesis_chunk` / `SynthesisChunkAccumulator` pairs.

### 2. Mapping table: OpenAI `chat.completion.chunk` → `QAEvent`

| OpenClaw chunk field | QAEvent variant | Notes |
|---|---|---|
| `delta.content` non-empty | `TextChunkEvent(content=delta)` | 1:1 stream of natural-language deltas. |
| `delta.tool_calls[i]` first sight (id + name known) | `ToolCallEvent(tool_name=name, args=parsed_partial_args)` | Emit ONCE per `tool_call_id`, gated by a `started_emitted` flag on the pending struct. `args` must be a `dict` (`QAEvent` schema); use `_safe_parse_args(buffer)` and fall back to `{}` if the partial buffer isn't valid JSON yet. |
| `delta.tool_calls[i]` continued (more `arguments` chars) | (none — accumulate only) | Buffered for emit-on-complete. |
| `finish_reason == "tool_calls"` | For each pending tool: `ToolResultEvent(tool_name, summary="ok", row_count=0)`; if tool name is `emit_chart` → also `ChartSpecEvent(...)`; if tool name is `emit_citation` → also `CitationEvent(...)`. | We do NOT see the MCP tool result body server-side in this lane. Document honestly that `summary="ok"` and `row_count=0` are placeholders. |
| `finish_reason == "stop"` or sentinel `[DONE]` | (none from translator) | Caller (`routers/qa.py` `gen()` `finally`) emits `DoneEvent`. Translator must NOT emit `DoneEvent` itself or it doubles up. |
| Gateway `error` frame (`{"error":{...}}` with no `choices`) | `ErrorEvent(message=...)` | Mirrors the chat translator's gateway-error branch. |
| `finish_reason` in `("length", "content_filter")` | `ErrorEvent(message="truncated_or_filtered: <reason>")` | Treat as soft errors so the frontend's `useQA` hook surfaces them. |

#### Surfacing chart and citation events from tool args (the synthesis pattern)

Because the chat lane never sees MCP tool result bodies, mirror what `translate_synthesis_chunk` does for `persist_insight`: peek into the **completed** `args_buffer` of `emit_chart` / `emit_citation` calls at `finish_reason="tool_calls"` time and synthesise our QA event from the args themselves:

- `emit_chart` args look like `{chart_type, x, y, series, title, source_table, breakdown_by?, reasoning?}` — these are exactly the fields `ChartSpecEvent` carries. Validate via `ChartSpec.model_validate(args)` inside a try; on `ValidationError` log and skip (emit nothing for that call rather than poisoning the stream).
- `emit_citation` args look like `{table, row_id?, source_url?, label}` — directly maps to `CitationEvent`. Add the `(table, row_id)` tuple to `acc.seen_citations` to dedupe.

#### Edge cases

- **Partial JSON args buffer at first-sight time.** `ToolCallEvent.args` is required to be a `dict`. Use `_safe_parse_args` and emit `args={}` if the buffer is mid-stream JSON. The QA frontend tolerates this (it's already lenient for early `tool_call` previews).
- **Malformed `emit_chart` spec** (e.g., missing `source_table`, `chart_type` not in literal set). Wrap `ChartSpec.model_validate` in try/except. On failure, skip the `ChartSpecEvent` and proceed; do NOT raise. Log at WARNING with the validation errors and the tool_call_id.
- **Multiple `emit_chart` calls in one stream.** The current QA agent emits at most one chart proposal; for safety, allow multiple but the frontend will render the last one.
- **`emit_citation` with empty `label` or empty `table`.** Drop the citation silently — `CitationEvent.label` is required and the frontend renders nothing useful for empty cells.
- **Citation dedupe.** Use the same `(table, row_id)` tuple key the legacy generator uses (line 1224 of `datacenter_qa.py`).
- **Sentinel `[DONE]` arriving before `finish_reason="stop"`.** Mark `acc.finished = True`; emit nothing. Caller's `finally` covers `DoneEvent`.

### 3. Shared-helper extraction question

**Recommendation: defer. Inline the tool-call delta accumulation in `translate_qa_chunk`, matching `translate_synthesis_chunk`.**

Rationale:

- ARCH 14 §5.4 proposed lifting `_apply_tool_call_deltas` already; the synthesis translator chose to duplicate instead, signalling that the team prioritised sibling-isolation over DRY.
- A 3-way lift now requires touching `translate_chunk` (the byte-frozen chat lane). PRD AC-4 forbids byte-level changes there.
- The duplication is ~25 lines per translator. Acceptable cost for blast-radius discipline.
- File a follow-up issue: "lift `_apply_tool_call_deltas` once we have three call sites and a frozen test harness."

### 4. SessionKey hashing

Spec calls for `agent:main:qa:global:{stable-hash-of-history-or-conversation-id}` with an `X-Session-Id` header from the frontend, and a fallback hash of the first user message.

**Recommendation: `hashlib.blake2b(first_user_message.encode("utf-8"), digest_size=8).hexdigest()` (16 hex chars).**

Why blake2b over sha256:

- ~2x faster on short strings (the typical first message is < 1 KB).
- Native digest_size parameter — no slicing footgun.
- Same constant-time properties; not that it matters here.
- sha256 is also fine; difference is cosmetic.

**Security analysis:**

- This is a **session-memory key**, not a security boundary. OpenClaw uses it to scope conversation memory.
- A collision means two different first messages produce the same key, so two conversations would share memory. Worst case: cross-talk between two unrelated user sessions.
- Frontend-supplied `X-Session-Id` (UUID v4) is the primary path and gives 122 bits of entropy — collisions are astronomical.
- The hash fallback only triggers when the frontend forgets to send `X-Session-Id`. With 64-bit blake2b, the birthday-collision probability at 1M sessions is ~2.7e-8 — acceptable for a memory-keying use case.
- **No PII risk:** the hash is one-way; first-message content is not recoverable from the key. The key itself is logged in OpenClaw access logs but contains no plaintext.

Conclusion: blake2b-64 is sufficient. Accept-X-Session-Id-or-fallback-hash is the right isolation mechanism.

### 5. SSE encoder question

The QA lane uses a **different wire format** from the chat/synthesis lanes:

- **QA wire** (`routers/qa.py` line 38): `f"data: {json.dumps(event.model_dump(), default=str)}\n\n"` — single-line `data:` + double newline.
- **Chat/synthesis wire** (`agents.insights.specs.sse_events.to_sse_text`): multi-line `id:`, `event:`, `data:` framing.

**The QA lane MUST keep its single-line `data:` shape.** The frontend `useQA` hook depends on it. Do NOT use `to_sse_text(evt)` in any QA-lane code path.

Concretely, the new QA forwarder (or whatever calls `translate_qa_chunk` inside `_drive_openclaw_stream`) must pass an `on_translated_event` callback that performs:

```python
yield f"data: {json.dumps(evt.model_dump(), default=str)}\n\n"
```

and NOT `yield to_sse_text(evt).encode()`.

Add a doc comment to `translate_qa_chunk` explicitly calling this out — it's the most likely place a future maintainer will copy/paste from `forward_chat` and break the wire contract.

### 6. Risks / unknowns / red flags

#### A. MCP tool surface — `emit_chart` is insight-scoped (highest risk)

The legacy QA agent (`datacenter_qa.py`) uses bespoke tools: `query` (parameterised SQL builder over a small whitelist of tables) and `propose_chart` (in-process; returns a chart spec but does NOT write to DB). Migrating to OpenClaw means using the MCP-side tools `query_database` and `emit_chart`.

- **`emit_chart`'s DB write requires `insight_id`.** For ad-hoc QA chats there is no parent insight; the MCP `_invoke()` helper validates `insight_id` is a UUID of an existing `ai_insight` row. A QA-global session has neither.

**Recommended path (architect to confirm):**
- Add a NEW MCP **read-only** tool `propose_qa_chart` that accepts the same args shape as `emit_chart` but does NOT require `insight_id` and does NOT write to DB. The translator captures the args buffer at `tool_call_complete` time and emits `ChartSpecEvent` from those args. No DB row is ever created.
- Mention this tool in `qa_global_rules.md` so the agent prefers it over `emit_chart` in QA-global sessions.
- Triangulation does not propose charts, so no analogous tool is needed there.

#### B. Citation surfacing

The legacy generator extracts citations from `_citation` keys embedded in query result rows. With OpenClaw, the agent never sees these rows directly — the gateway round-trips MCP. Two paths:

- The MCP `query_database` tool result body includes `_citation` per row, AND the agent then calls an explicit `emit_citation` tool. Requires prompt-engineering discipline (call out in `qa_global_rules.md`).
- For QA-global, `emit_citation` may also be insight-scoped today. If so, mirror the `propose_qa_chart` pattern with a `propose_qa_citation` tool. Architect to verify.

#### C. Dispatcher-driven event ordering is lost

Legacy emits `ToolCallEvent → execute → ToolResultEvent → CitationEvent → ChartSpecEvent → TextChunkEvent...`. With OpenClaw, ordering is dictated by OpenAI streaming chunks. The frontend `useQA` hook should be ordering-tolerant; verify before shipping.

#### D. Three-pass synthesis collapses to one pass

Legacy code does Pass 1 (tool calls) then Pass 2 (synthesis stream). OpenClaw's chat-completions endpoint will do this implicitly via the agentic loop, but the model needs prompt-level instruction to "answer the user after all tool calls" — otherwise it may emit text mid-tool-loop and never stream the final synthesis. Mitigate in the QA prompts file.

#### E. Scope augmentation lives in the QA agent

`_augment_query_args` (datacenter_qa.py:1196) injects scope inference. With OpenClaw, this logic must live in the MCP `query_database` handler or in the system prompt. If neither, scope-implicit queries break silently. Recommend adding the scope-inference hint to `qa_global_rules.md` as instructional text ("when the user names a state by full name, translate to two-letter code; when the user names an operator by alias, translate to canonical").

#### F. History-vs-session-memory double-count

Legacy uses `history[-8:]`. OpenClaw with session memory may keep longer context. Decide whether `X-Session-Id`-keyed memory replaces explicit history-passing, or supplements it. Recommend: pass only the new user message + rely on OpenClaw memory; ignore the `history` field on `AskRequest` for the OpenClaw lane (deprecation path: leave the field, ignore it).

#### G. Error-frame shape difference

`schemas.qa.ErrorEvent` carries only `message`. The chat-lane `ErrorEvent` carries `code`, `message`, `retryable`, `insight_id`. When translating, drop the extras — but log them at WARNING so ops can correlate to the gateway error.

---

## Key References

- `backend/openclaw/sse_translator.py` — current two translators (chat at line 178; synthesis at line 472).
- `backend/openclaw/forwarder.py` — `_drive_openclaw_stream` shared driver at line 319 (already accumulator/translator-agnostic; reusable for QA lane).
- `backend/schemas/qa.py` — frozen `QAEvent` discriminated union the frontend `useQA` hook depends on.
- `backend/routers/qa.py` — current SSE encoder; `gen()`'s `finally` clause owns `DoneEvent` emission.
- `backend/agents/datacenter_qa.py` lines 1122-1298 — legacy `answer_question` generator showing emit ordering and citation/chart synthesis logic.
- ARCH 14 §5 — synthesis-lane translator design (sibling pattern this RFC mirrors).

---

## Top recommendations (3 bullets)

- **Add `translate_qa_chunk` + `QAChunkAccumulator` as a sibling translator** (matches existing naming), inline the tool-call-delta accumulation (defer the `_apply_tool_call_deltas` helper lift for a separate refactor), and reuse the existing `_drive_openclaw_stream` driver — never call `to_sse_text` in the QA lane (keep the single-line `data: {json}\n\n` wire format the frontend `useQA` hook depends on).
- **Surface `ChartSpecEvent` and `CitationEvent` by parsing the completed `args_buffer` of `emit_chart` / `emit_citation` (or `propose_qa_chart` / `propose_qa_citation`) tool calls at `finish_reason="tool_calls"` time** (the same pattern `translate_synthesis_chunk` uses for `persist_insight`); validate args via `ChartSpec.model_validate` and skip on failure; let the caller's existing `finally` clause emit `DoneEvent`.
- **Biggest red flag to resolve before coding: `emit_chart` is insight-scoped and writes to DB** — introduce a read-only `propose_qa_chart` MCP tool (and possibly `propose_qa_citation`) so QA-global chats don't create orphan rows. Use `blake2b(first_message, digest_size=8).hexdigest()` as the `X-Session-Id` fallback.
