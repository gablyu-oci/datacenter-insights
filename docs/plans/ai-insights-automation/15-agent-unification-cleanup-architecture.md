# 15 — Agent Unification Cleanup Architecture (Phase-5 Follow-up)

**Author:** System Architect
**Date:** 2026-05-06
**Status:** Ready for backend handoff
**Predecessors:**
  - PRD: [`15-agent-unification-cleanup-prd.md`](./15-agent-unification-cleanup-prd.md)
  - Research: [`15-qa-translator-research.md`](./15-qa-translator-research.md)
  - Design lineage: [`14-unified-agent-architecture.md`](./14-unified-agent-architecture.md) §3, §5, §10.1
**Successor:** `15-agent-unification-cleanup-test-evidence.md` (QA, post-merge)

---

## 0. Executive Summary

The unified-agent migration (PRD-13, PRD-14) consolidated chat, daily synthesis, and weekly brief onto OpenClaw + FastMCP. Three call sites and one orphan dispatcher block were not migrated:

1. `POST /api/qa/ask` — datacenter QA panel; today goes through `agents.datacenter_qa.answer_question` which calls `llm_client.reason()` directly.
2. `POST /api/agent/ask` — triangulation tab; today goes through `agents.triangulation_qa.answer_question_stream` which also calls `llm_client.reason()` / `llm_client.chat_stream()` directly.
3. `routers/insights.py:_legacy_chat_handler` (lines 930-1259) — dead, imports `agents.insights.tool_loop` which Phase 5 deleted; reachable only when `settings.openclaw_enabled == 0`.

This spec finishes the migration by:

- Adding a third sibling translator (`translate_qa_chunk` + `QAChunkAccumulator`) to `backend/openclaw/sse_translator.py`.
- Adding a single new QA-lane forwarder `backend/openclaw/qa_forwarder.py` that wraps `_drive_openclaw_stream` and yields QA-shaped SSE bytes.
- Gutting `backend/agents/datacenter_qa.py` and `backend/agents/triangulation_qa.py` down to thin shims that load the prompt, derive the sessionKey, and delegate to `forward_qa`.
- Adding one new MCP tool `propose_qa_chart` (no DB write) to surface chart proposals in the QA lane without requiring `insight_id`.
- Deleting `_legacy_chat_handler`, `_chat_system_prompt`, the `openclaw_enabled` config field, and the dispatcher branch in `routers/insights.py`.
- Versioning the QA system prompt and the triangulation system prompt as `qa_global_rules.md` and `triangulation_rules.md` under `backend/agents/insights/prompts/`.

After this PR ships there is exactly one chat-shaped LLM lane and zero dead branches.

---

## 1. Module Map

### 1.1 New / changed / deleted files

| Status | Path | One-line responsibility |
|---|---|---|
| **NEW** | `backend/openclaw/qa_forwarder.py` | `forward_qa(...)` — QA-lane SSE forwarder; sibling of `forward_chat`; reuses `_drive_openclaw_stream`; yields `data: {qa_event_json}\n\n` bytes. |
| **EXTEND** | `backend/openclaw/sse_translator.py` | Add `QAChunkAccumulator` dataclass + `translate_qa_chunk` function + `QATranslatedEvent` type alias. Chat + synthesis translators untouched. |
| **REPLACE** | `backend/agents/datacenter_qa.py` | Gut body. Keep `answer_question(session, question, history) -> AsyncIterator[QAEvent]` signature. New body delegates to `forward_qa` after loading the prompt + deriving the sessionKey. |
| **REPLACE** | `backend/agents/triangulation_qa.py` | Gut body. Replace public surface with `answer_question(session, question, history=None) -> AsyncIterator[QAEvent]` (NEW signature; see §1.3). The legacy `answer_question_stream` is removed. |
| **NEW** | `backend/agents/insights/prompts/qa_global_rules.md` | The (former) datacenter-QA system prompt body (schema doc + worked examples + style + mechanical rules). Persona stays in SOUL.md. |
| **NEW** | `backend/agents/insights/prompts/triangulation_rules.md` | The (former) triangulation-QA system prompt body (citations + 3-6 sentence cap). |
| **EXTEND** | `backend/mcp_server.py` | Register one new MCP tool `propose_qa_chart` (~10 lines, no DB write). |
| **REWRITE** | `backend/routers/agent.py` | Replace `answer_question_stream` consumer with the same `QAEvent`-aware SSE serialiser used by `routers/qa.py` (single shape across both routers). |
| **DELETE FROM** | `backend/routers/insights.py` | `_legacy_chat_handler` (lines 930-1259); `_chat_system_prompt` (lines 879-901); the dispatcher `if int(getattr(settings, "openclaw_enabled", 0)) == 1:` block (lines 925-927). KEEP `_build_chat_context` (lines 812-877) — still called by `_openclaw_chat_handler` at line 1285. |
| **EDIT** | `backend/config.py` | Remove `openclaw_enabled: int = 1` field (line 61). |
| **EDIT** | `backend/.env.example` | Remove `OPENCLAW_ENABLED=1` line. |
| **EDIT** | `backend/tests/test_openclaw_forwarder.py` | Drop env mutations of `settings.openclaw_enabled` at lines 352/422/463/484/533/590. Drop any test that asserts the rollback flag works (it has no flag now). |
| **EDIT** | `backend/tests/test_v2_chat_isolation.py` | Drop the two `settings.openclaw_enabled` mutations at lines 210/212. |
| **NEW** | `backend/tests/test_qa_router.py` | SSE shape + memory across two POSTs sharing one X-Session-Id + tool-call event surfaces. |
| **NEW** | `backend/tests/test_triangulation_router.py` | Same shape for `/api/agent/ask`. |
| **NEW** | `backend/tests/test_routers_insights_no_legacy_imports.py` | Compile-time guard: `agents.insights.tool_loop` and `llm_client` are absent from the loaded module's transitive imports. |
| **NEW** | `docs/plans/ai-insights-automation/15-extraction-vs-agent-policy.md` | Three-bucket policy (chat-like / extraction / recursive-skill). |
| **EDIT** | `docs/plans/ai-insights-automation/14-unified-agent-architecture.md` | Append "completed at 2026-05-06" appendix listing the 5 migrated call sites. |

### 1.2 The forwarder decision: NEW sibling vs parameterise `forward_chat`

We considered three options:

| Option | Pros | Cons |
|---|---|---|
| (a) NEW `qa_forwarder.py` with `forward_qa(...)` (RECOMMENDED) | Sibling pattern matches synthesis-driver lift in arch 14 §4. Zero blast radius on chat. Different SSE wire format isolated. | One more file, ~120 lines. |
| (b) Parameterise `forward_chat` with a `mode` flag | Single forwarder. | Forces a fork inside `forward_chat`'s body for: (i) different SSE wire format (`to_sse_text` vs `data: {json}`), (ii) different DB-write contract (chat persists `agent_message`; QA does not), (iii) different accumulator type. The branches dwarf the shared code. PRD AC-3 + research §5 flag the wire-format risk explicitly. |
| (c) Inline the forwarder inside the agent module | Simplest. | Duplicates `_drive_openclaw_stream` invocation logic across modules; harder to test in isolation. |

**Decision: option (a).** Rationale matches arch 14's choice to add `synthesis_driver.py` as a sibling rather than parameterise `forward_chat`. The chat lane has DB-write semantics this lane does not; the wire formats differ. Sibling isolation outweighs DRY.

### 1.3 The `triangulation_qa` public-surface decision

The current `routers/agent.py` consumes `answer_question_stream(...) -> AsyncIterator[str]` and SSE-frames each delta itself.

| Option | Description |
|---|---|
| (a) Keep `AsyncIterator[str]` | Wrap a `QAEvent` generator inside a thin string-shim that yields only `TextChunkEvent.content`. Lose tool-call / chart / citation visibility on the wire. |
| (b) Promote `routers/agent.py` to consume `QAEvent` directly (RECOMMENDED) | Both routers serialise the same way. Gains tool-call SSE surface end-to-end, which matches PRD US-2.1 ("tool calls work uniformly across the product"). |

**Decision: option (b).** The triangulation tab's frontend is single-purpose (it currently expects plain text `data:` events terminated by `[DONE]`); we keep the wire backwards-compatible by:

- Emitting `TextChunkEvent.content` as `data: <delta>\n\n` (no JSON wrap) for backward-compatibility,
- Suppressing `tool_call` / `tool_result` events on this lane by default (toggle via internal flag in `forward_qa`),
- Adding a final `data: [DONE]\n\n` sentinel.

This keeps the triangulation frontend unchanged while letting the underlying machinery be unified. Long term the frontend should adopt the QA `data: {json}` shape and drop the special case; that is out-of-scope for this PR (NG3).

> **Note for backend engineer.** The `routers/agent.py` rewrite is small (~30 lines). The new shape:
>
> ```
> async for evt in answer_question(session, body.question):
>     if isinstance(evt, TextChunkEvent):
>         yield f"data: {evt.content.replace(chr(10), '\\n')}\n\n"
>     # other event types ignored on this lane
> yield "data: [DONE]\n\n"
> ```

---

## 2. The QA-lane forwarder (`qa_forwarder.py`)

### 2.1 File: `backend/openclaw/qa_forwarder.py`

**Public signature:**

```python
async def forward_qa(
    *,
    question: str,
    history: list[Message],         # schemas.qa.Message; may be empty
    session_key: str,                # e.g. "agent:main:qa:global:abc..."
    system_prompt: str,              # rendered prompt body (from prompts.load)
    db: AsyncSession,                # opened by caller; not closed here
    surface_tool_events: bool = True, # set False for triangulation lane
) -> AsyncIterator[bytes]:
    """Drive one QA-lane turn through OpenClaw and yield SSE bytes.

    Wire format: `data: {json.dumps(qa_event.model_dump(), default=str)}\n\n`.
    Caller's `finally` block in routers/qa.py emits the terminating
    `data: {"type":"done"}\n\n` (DoneEvent). This generator MUST NOT
    emit DoneEvent itself or it doubles up.

    NEVER call `to_sse_text(...)` here — that is the chat-lane wire
    format and would break the frontend `useQA` hook.
    """
```

### 2.2 Body composition

```python
async def forward_qa(...) -> AsyncIterator[bytes]:
    acc = QAChunkAccumulator(session_key=session_key)
    queue: asyncio.Queue[QATranslatedEvent | None] = asyncio.Queue()

    async def on_translated_event(evt):
        # Skip tool_call/tool_result events on the triangulation lane.
        if not surface_tool_events and isinstance(
            evt, (ToolCallEvent, ToolResultEvent)
        ):
            return
        await queue.put(evt)

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for m in (history or [])[-8:]:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": question})

    # Drive on a background task so we can stream events as they arrive.
    drive_task = asyncio.create_task(
        _drive_openclaw_stream(
            session_key=session_key,
            messages=messages,
            on_translated_event=on_translated_event,
            accumulator=acc,
            translator=translate_qa_chunk,
            cap_turns=12,         # smaller than synthesis's 12; same value, named explicitly
            cap_tool_calls=20,    # smaller than synthesis's 30 — QA panel is interactive
            cap_wall_seconds=120, # smaller than synthesis's 600 — interactive UX
        )
    )

    try:
        while True:
            # Poll the queue and the drive task in parallel.
            getter = asyncio.create_task(queue.get())
            done, _pending = await asyncio.wait(
                {getter, drive_task},
                timeout=0.5,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if getter in done:
                evt = getter.result()
                if evt is not None:
                    yield (
                        f"data: {json.dumps(evt.model_dump(), default=str)}\n\n"
                    ).encode("utf-8")
            else:
                getter.cancel()

            if drive_task.done() and queue.empty():
                break

        # Drain the result and surface degraded close as ErrorEvent if needed.
        result = await drive_task
        if result.degraded and result.reason not in (None, "completed"):
            err = ErrorEvent(message=f"qa_lane: {result.reason}")
            yield f"data: {json.dumps(err.model_dump())}\n\n".encode("utf-8")
    except Exception as exc:
        logger.exception("qa_forwarder.failed")
        err = ErrorEvent(message=str(exc))
        yield f"data: {json.dumps(err.model_dump())}\n\n".encode("utf-8")
    finally:
        if not drive_task.done():
            drive_task.cancel()
        # NOTE: caller's `finally` emits DoneEvent — do NOT emit here.
```

**Caps rationale.** A QA panel turn is interactive (sub-30s expected); the synthesis defaults (600s wall, 30 tool calls) are too lax for a UX with a "thinking..." spinner. The values 120/12/20 are chosen as ~2× a P95 happy-path turn (~15-25s, ~8 tool calls) plus headroom.

### 2.3 What the caller does (no change to `routers/qa.py`)

The router's `gen()` function already wraps the agent generator in a `try/finally` that emits `DoneEvent`. The change is invisible to it because `answer_question` (the existing import target) keeps its signature — see §4.1.

---

## 3. The QA translator (`translate_qa_chunk`)

### 3.1 File: `backend/openclaw/sse_translator.py` (extend)

Three coexisting translators in the same module:

| Lane | Translator | Accumulator | Wire |
|---|---|---|---|
| Chat | `translate_chunk` (existing, line 178) | `ChunkAccumulator` | `to_sse_text(...)` |
| Synthesis | `translate_synthesis_chunk` (existing, line 472) | `SynthesisChunkAccumulator` | `to_sse_text(...)` |
| **QA (NEW)** | `translate_qa_chunk` | `QAChunkAccumulator` | `data: {qa_event_json}\n\n` |

### 3.2 `QAChunkAccumulator`

```python
@dataclass
class QAChunkAccumulator:
    session_key: str

    # Streaming tool-call partials — same shape as the chat / synthesis
    # accumulators. Inlined per research §3 ("defer the
    # _apply_tool_call_deltas helper lift").
    tool_calls_by_index: dict[int, _PendingToolCall] = field(default_factory=dict)
    tool_calls_by_id: dict[str, _PendingToolCall] = field(default_factory=dict)

    # Citation dedupe via (table, row_id) — same key the legacy generator
    # used at datacenter_qa.py:1224.
    seen_citations: set[tuple[str, Optional[str]]] = field(default_factory=set)

    # Cap counters mirroring SynthesisChunkAccumulator so
    # `_drive_openclaw_stream` can read them through duck-typed getattr.
    cap_counters: dict[str, Any] = field(
        default_factory=lambda: {
            "turns": 0,
            "tool_calls": 0,
            "wall_clock_started_at": None,
        }
    )

    finished: bool = False
```

### 3.3 Mapping table (with field-level pseudocode)

| OpenClaw chunk shape | Action on `acc` | Emitted `QATranslatedEvent` |
|---|---|---|
| `delta.content` non-empty | (no state change) | `TextChunkEvent(content=str(delta))` |
| `delta.tool_calls[i]` first-sight (id+name known, not started) | populate `_PendingToolCall`; mark `started_emitted=True` | `ToolCallEvent(tool_name=name, args=_safe_parse_args(buffer))` — args is `{}` if buffer is mid-stream JSON |
| `delta.tool_calls[i]` continued (more `arguments` chars) | append to `pending.args_buffer` only | (none) |
| `finish_reason == "tool_calls"` | `cap_counters["turns"] += 1`; for each pending tool: `cap_counters["tool_calls"] += 1`; mark `completed_emitted=True` | per-tool dispatch (table below) |
| `finish_reason == "stop"` | `acc.finished = True` | (none — caller's `finally` emits `DoneEvent`) |
| `finish_reason in ("length", "content_filter")` | `acc.finished = True` | `ErrorEvent(message=f"truncated_or_filtered: {reason}")` |
| Gateway error frame (`{"error": ...}`, no `choices`) | (none) | `ErrorEvent(message=str(error.message))` |
| `[DONE]` sentinel | `acc.finished = True` | (none — idempotent no-op) |

**Per-tool dispatch on `tool_call_complete`:**

| `tool_name` | Emitted events | Validation |
|---|---|---|
| `query_database` / `call_api` / `get_chart_data` / `web_search` / `run_skill` | `ToolResultEvent(tool_name=name, summary="ok", row_count=0)` | (none — the QA translator never sees the MCP result body; placeholder summary is honest) |
| `propose_qa_chart` | `ToolResultEvent(tool_name="propose_qa_chart", summary="ok", row_count=0)` THEN attempt `ChartSpec.model_validate(parsed_args)`. On success: emit `ChartSpecEvent(**parsed_args)`. On `ValidationError`: log WARNING with `tool_call_id` + the validation errors, emit nothing. | strict |
| `emit_citation` | `ToolResultEvent(...)` THEN attempt `Citation.model_validate(parsed_args)`. On success: build dedupe key `(table, row_id)`; if already in `acc.seen_citations`, skip. Else add and emit `CitationEvent(**parsed_args)`. | strict |

> **Note on citation surfacing.** Per research §A and §B, the legacy datacenter QA never emitted via an `emit_citation` MCP tool — it parsed `_citation` keys out of query result rows. The OpenClaw-routed QA lane *does not see those rows server-side* (the gateway round-trips MCP). So in V1 of this migration, **CitationEvents are not surfaced on the QA wire**; the agent's prose is instructed to drop source URLs as inline Markdown links per the existing `qa_global_rules.md` body. The `emit_citation` branch above is wired for forward-compatibility — it activates if and only if the agent decides to call that tool. See §4 for the explicit decision.

### 3.4 Edge cases (from research §3)

- **Partial JSON args buffer at first-sight.** `ToolCallEvent.args` is required to be a `dict`. Use `_safe_parse_args(buffer)` → returns `{}` on parse failure; emit `ToolCallEvent(tool_name=name, args={})` rather than blocking the started event.
- **Malformed `propose_qa_chart` spec.** Wrap `ChartSpec.model_validate` in try/except. On failure: log + skip `ChartSpecEvent`. Do NOT raise — that would poison the stream.
- **Multiple `propose_qa_chart` calls in one stream.** Allow; the frontend renders the latest. (Legacy already emitted at most one.)
- **Empty `label` or `table` on `emit_citation`.** Drop silently — `Citation.label` / `Citation.table` are required by the schema; the `model_validate` already rejects.
- **`[DONE]` arriving before `finish_reason="stop"`.** Mark `acc.finished = True`; emit nothing. The caller's `finally` emits `DoneEvent`.

### 3.5 The `_apply_tool_call_deltas` helper lift

**Decision: defer (per research §3).**

The 3-way lift now requires touching `translate_chunk` (the byte-frozen chat lane). PRD AC-3 forbids byte-level changes there. We inline the ~25 lines of delta accumulation in `translate_qa_chunk` to match what the synthesis translator already does. File a follow-up issue: "lift `_apply_tool_call_deltas` once we have a frozen golden test harness for all three lanes."

---

## 4. MCP tool decision (research §A unblocker)

### 4.1 The question

Legacy `datacenter_qa` proposes charts; it does NOT write a `agent_chart` row (the proposal is captured in-process and emitted on the SSE wire only). The chat lane's `emit_chart` MCP tool requires `insight_id` because it persists. For QA-global there is no parent insight.

### 4.2 Options

| Option | Description | Risk |
|---|---|---|
| **(a)** Add a NEW `propose_qa_chart` MCP tool — accepts the chart spec, no DB write, returns `{ok: true}`. | Cleanest. Read-only. No touch of existing tools. | Low. |
| (b) Modify `emit_chart` to accept `insight_id=None` and skip the DB write. | Reuses existing tool. | Touches a frozen chat-lane tool; failure mode is silent (charts not persisted in chat lane if anyone passes None by accident). |
| (c) Skip the MCP tool entirely; have the prompt instruct the agent to embed a fenced ```chart-spec JSON block in its assistant text and parse server-side. | Simplest — no MCP touch. | New wire convention; breaks agent uniformity (the model would learn a different idiom for QA than for synthesis chat). |

**Decision: option (a).** Recommended in research §A. Cleanest path; no risk to existing tools.

### 4.3 New MCP tool: `propose_qa_chart`

```python
@mcp.tool()
async def propose_qa_chart(
    chart_type: str,
    x: str,
    y: str,
    series: list[dict[str, Any]],
    title: str,
    source_table: str,
    breakdown_by: Optional[str] = None,
    reasoning: Optional[str] = None,
) -> dict[str, Any]:
    """Propose a chart for the QA-global lane (no DB write).

    The QA-lane SSE translator captures the args buffer at
    tool_call_complete time and emits a ChartSpecEvent from those
    args. No agent_chart row is created — QA-global has no parent
    insight to attach to.

    Returns: {"ok": True} so the agent's tool-loop terminates cleanly.
    """
    return {"ok": True}
```

Register at the bottom of `mcp_server.py`'s tool list (after `persist_brief`) so the tool registration order documented in arch 14 §3.5 stays append-only.

### 4.4 Citation strategy

**Decision: do NOT surface CitationEvents on the QA wire in V1.**

Rationale:
- The legacy `datacenter_qa.answer_question` did surface `CitationEvent`s — but only by parsing `_citation` keys from query result rows. With OpenClaw, the agent never sees those rows directly.
- The legacy `triangulation_qa.answer_question_stream` does NOT emit any citations of its own — it instructs the model to embed a "Sources:" footer in prose.
- The simplest forward path is to instruct the QA agent (in `qa_global_rules.md`) to drop source URLs as Markdown links inline (which the existing prompt already does) and rely on the chat-lane `emit_citation` tool only when QA later gains a parent insight.
- The translator's `emit_citation` branch (§3.3) is wired for forward-compatibility: it activates if/when the agent calls the tool, but neither prompt instructs it to.

The `propose_qa_citation` companion tool from research §B is **not** added in this PR. Defer to a follow-up if a use case appears.

---

## 5. SessionKey derivation

### 5.1 QA-global lane

```python
def _qa_session_key(question: str, x_session_id_header: Optional[str]) -> str:
    """Build the OpenClaw sessionKey for one QA-global turn.

    Resolution order (matches PRD R1 + research §4):
      1. X-Session-Id request header if non-empty (UUID v4 expected).
      2. blake2b(question.encode("utf-8"), digest_size=8).hexdigest().
    """
    if x_session_id_header and x_session_id_header.strip():
        return f"agent:main:qa:global:{x_session_id_header.strip()}"
    fallback = hashlib.blake2b(
        question.encode("utf-8"), digest_size=8
    ).hexdigest()  # 16 hex chars
    return f"agent:main:qa:global:{fallback}"
```

The header is read in `routers/qa.py` and passed through to `agents.datacenter_qa.answer_question` via a new optional `x_session_id` parameter (default `None` keeps the existing test surface intact).

### 5.2 Triangulation lane

```python
def _triangulation_session_key(
    question: str, x_session_id_header: Optional[str]
) -> str:
    if x_session_id_header and x_session_id_header.strip():
        return f"agent:main:triangulation:{x_session_id_header.strip()}"
    fallback = hashlib.blake2b(
        question.encode("utf-8"), digest_size=8
    ).hexdigest()
    return f"agent:main:triangulation:{fallback}"
```

> **Documentation note.** Without a sticky session id from the frontend, every POST is effectively single-turn — each new first-question hash builds a fresh OpenClaw memory store. PRD OQ-1 calls this out; backend engineer to document inline in the router docstring.

### 5.3 How the keys flow into `_drive_openclaw_stream`

`forward_qa(session_key=..., ...)` passes the resolved key directly. `_drive_openclaw_stream` writes it as the `x-openclaw-session-key` header on the upstream POST.

---

## 6. Prompt files

### 6.1 What stays in SOUL.md (per arch 14 §10.1, no change)

- `## Identity` (mode-agnostic identity sentence)
- `## Voice`
- `## Schema knowledge`
- `## Players`
- `## Tool palette` (now includes 11 tools post this PR — adds `propose_qa_chart`)
- `## Citation rules`
- `## Safety rules`
- `## Out-of-scope redirect`

### 6.2 `qa_global_rules.md` (NEW) — sections

The backend engineer copies the body of `datacenter_qa.py:_build_system_prompt` (lines 354-485) into this file, with these adjustments:

| Section | Source | Notes |
|---|---|---|
| Header (1 line) | NEW | "# QA-global mode" |
| `## Style` | source `═══ STYLE ═══` block | Verbatim. |
| `## Tools` | source `═══ EXECUTION & TOOLS ═══` block | UPDATE the `propose_chart` reference to `propose_qa_chart`. Remove "the user does NOT see this layer" line — it's instructional carry-over. |
| `## Schema` | source `═══ SCHEMA ═══` (the `_describe_schema_for_llm()` output) | Paste the rendered text, not the helper. The helper stays in `datacenter_qa.py` for now (still used to build the system prompt at module-load time, see §7.1). |
| `## Worked Examples` | source `═══ WORKED EXAMPLES ═══` block | Verbatim, four examples. |
| `## Mechanical Rules` | source `═══ MECHANICAL RULES ═══` block | Verbatim minus the persona-leaning first sentence. |
| (NEW final section) | from research §F | "## Conversation memory: the OpenClaw gateway holds your last turns under your sessionKey. Treat the prior assistant message as already-known context; do not restate it." |
| (NEW final section) | from research §D | "## Stop condition: after at most 3 tool-call rounds, write the final answer in prose. The user sees only your prose + the chart you proposed; do not narrate tool calls." |
| (NEW final section) | from research §E | "## Scope inference hint: when the user names a state by full name, translate to two-letter code; when they name an operator by alias (`MSFT`, `GCP`), translate to canonical (`Microsoft`, `Google`)." (This compensates for `_augment_query_args` no longer running server-side.) |

### 6.3 `triangulation_rules.md` (NEW) — sections

The backend engineer copies `triangulation_qa.SYSTEM_PROMPT` (lines 128-133) into this file. Total ~20 lines:

| Section | Source | Notes |
|---|---|---|
| `# Triangulation mode` | NEW | |
| `## Style` | source SYSTEM_PROMPT | Verbatim — "concise 3-6 sentences plus a 'Sources:' list". |
| `## Tools` | NEW (1 paragraph) | "Available MCP read tools: query_database, call_api, get_chart_data, web_search, run_skill. No write tools in this mode — answer in prose only." |
| `## Conversation memory` | NEW | Same paragraph as qa_global_rules.md §last. |

### 6.4 The loader

`backend/agents/insights/prompts/__init__.py` already exists per arch 14 §10.1 (`load(name) -> str`, lru-cached). No new code; the QA forwarder calls:

```python
from agents.insights.prompts import load as load_prompt
system_prompt = load_prompt("qa_global_rules")        # or "triangulation_rules"
```

---

## 7. Replacement bodies

### 7.1 `backend/agents/datacenter_qa.py` (REPLACE)

After the rewrite the file is ~80 lines. What stays vs what goes:

| Symbol | Action |
|---|---|
| `_TABLE_MODELS`, `_SCHEMA_WHITELIST` | DELETE — these were only consumed by `_describe_schema_for_llm` and `_tool_query`; the schema description now lives statically inside `qa_global_rules.md`. |
| `_describe_schema_for_llm`, `_table_columns`, `_column_python_type` | DELETE. |
| `_ALLOWED_OPS`, `TOOLS`, `_AGG_TABLES`, `_COLUMN_ALIASES`, `_resolve_column`, `_query_needs_company_join` | DELETE — tool surface is now MCP-side. |
| `_US_STATES`, `_PROVIDER_ALIASES`, `_infer_scope_from_question`, `_augment_query_args` | DELETE — scope augmentation moves into the prompt as instructional text (§6.2). |
| `_citation_for_row`, `_coerce_for_json`, `_row_to_dict`, `_build_metric_expr`, `_apply_where`, `_tool_query` | DELETE. |
| `dispatch_tool`, `_is_error_envelope`, `_result_rows`, `_result_summary`, `_build_chart_event_from_proposal` | DELETE. |
| `_build_system_prompt`, `SYSTEM_PROMPT` (module constant) | DELETE — replaced by `prompts.load("qa_global_rules")` at call time. |
| `answer_question(session, question, history) -> AsyncIterator[QAEvent]` | KEEP signature; new body is a ~30-line delegator (§7.1.1). |

#### 7.1.1 New `answer_question` body (sketch)

```python
async def answer_question(
    session: AsyncSession,
    question: str,
    history: list[Message] | None = None,
    *,
    x_session_id: Optional[str] = None,
) -> AsyncIterator[QAEvent]:
    """Stream a QA answer from the unified OpenClaw agent.

    Signature is preserved for routers/qa.py compatibility. The optional
    x_session_id kwarg lets the router thread an X-Session-Id header
    through to OpenClaw memory keying.
    """
    question = (question or "").strip()
    if not question:
        yield ErrorEvent(message="Please provide a question.")
        return

    system_prompt = prompts.load("qa_global_rules")
    session_key = _qa_session_key(question, x_session_id)

    # Hand off to the QA forwarder. forward_qa yields SSE-encoded bytes;
    # we re-parse them back into QAEvent objects so routers/qa.py's existing
    # `event.model_dump()` call still works.
    async for raw_bytes in forward_qa(
        question=question,
        history=history or [],
        session_key=session_key,
        system_prompt=system_prompt,
        db=session,
        surface_tool_events=True,
    ):
        # raw_bytes is `b"data: {json}\n\n"`. Strip + parse.
        line = raw_bytes.decode("utf-8").strip()
        if not line.startswith("data:"):
            continue
        try:
            payload = json.loads(line[len("data:"):].strip())
        except json.JSONDecodeError:
            continue
        # Re-validate against the QAEvent union to preserve the contract
        # the router expects.
        from pydantic import TypeAdapter
        adapter = TypeAdapter(QAEvent)
        try:
            yield adapter.validate_python(payload)
        except Exception:
            logger.warning("datacenter_qa.invalid_qa_event", extra={"payload": payload})
```

> **Optimisation note.** The encode-decode-encode round-trip is wasteful but keeps the public contract of `answer_question` intact. A follow-up can split `forward_qa` into a `forward_qa_events(...) -> AsyncIterator[QAEvent]` core + a thin SSE-encoding wrapper for the router. Defer.

### 7.2 `backend/agents/triangulation_qa.py` (REPLACE)

Same pattern. After the rewrite the file is ~50 lines.

| Symbol | Action |
|---|---|
| `TOOLS`, `SYSTEM_PROMPT` | DELETE. |
| `_tool_search_sites`, `_tool_list_events`, `_tool_list_energy_projects`, `_tool_list_edgar_extractions`, `dispatch_tool` | DELETE. |
| `answer_question_stream(session, question) -> AsyncIterator[str]` | DELETE. New public surface is `answer_question(session, question, history=None, *, x_session_id=None) -> AsyncIterator[QAEvent]` (signature parity with datacenter_qa). |

#### 7.2.1 New `answer_question` body (sketch)

```python
async def answer_question(
    session: AsyncSession,
    question: str,
    history: list[Message] | None = None,
    *,
    x_session_id: Optional[str] = None,
) -> AsyncIterator[QAEvent]:
    question = (question or "").strip()
    if not question:
        yield ErrorEvent(message="Please provide a question.")
        return

    system_prompt = prompts.load("triangulation_rules")
    session_key = _triangulation_session_key(question, x_session_id)

    async for raw_bytes in forward_qa(
        question=question,
        history=history or [],
        session_key=session_key,
        system_prompt=system_prompt,
        db=session,
        surface_tool_events=False,    # triangulation lane suppresses tool-call SSE
    ):
        # ... same parse-and-yield pattern as datacenter_qa
```

### 7.3 `backend/routers/agent.py` (REWRITE)

```python
from agents.triangulation_qa import answer_question

@router.post("/ask")
async def ask(body: AskBody, request: Request):
    x_session_id = request.headers.get("X-Session-Id")

    async def gen():
        async with async_session_factory() as session:
            try:
                async for evt in answer_question(
                    session, body.question, x_session_id=x_session_id
                ):
                    if isinstance(evt, TextChunkEvent):
                        # Backward-compat wire for the existing triangulation FE:
                        # plain `data: <delta>\n\n` lines (no JSON wrap).
                        delta = evt.content.replace("\n", "\\n")
                        yield f"data: {delta}\n\n"
                    elif isinstance(evt, ErrorEvent):
                        yield f"data: {_json.dumps({'error': evt.message})}\n\n"
                    # other event types ignored on this lane
                yield "data: [DONE]\n\n"
            except Exception as exc:
                logger.exception("agent.ask.stream_failed")
                yield f"data: {_json.dumps({'error': str(exc)})}\n\n"
                yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
```

---

## 8. Orphan-block deletion plan (R3)

The exact line ranges in `routers/insights.py`:

| Lines | Symbol | Action | Rationale |
|---|---|---|---|
| 812-877 | `_build_chat_context` | **KEEP** | Called by `_openclaw_chat_handler` at line 1285 (`ctx_payload = await _build_chat_context(...)`). Even though the result variable is currently unused downstream (it's bound and discarded), the call has the side effect of validating the insight exists (raises `HTTPException(404)` if not). Removing the call would break the 404 deterministic-prelude that the OpenClaw lane relies on. |
| 879-901 | `_chat_system_prompt` | **DELETE** | Only used by `_legacy_chat_handler:966`. The OpenClaw lane reads the system prompt from `chat_rules.md` per arch 14 §10.1. |
| 922-928 | dispatcher branch (`if int(getattr(settings, "openclaw_enabled", 0)) == 1: ... return _openclaw_chat_handler(...)`) | **REPLACE with single direct call** | Collapse to `return await _openclaw_chat_handler(insight_id, request, body)`. PRD US-3.1. |
| 930-1259 | `_legacy_chat_handler` | **DELETE** | Imports `agents.insights.tool_loop` (deleted in Phase 5). Currently a landmine. |

After deletion the dispatcher reads simply:

```python
@router.post("/insights/{insight_id}/chat", responses={...})
async def post_insight_chat(insight_id, request, body):
    """Per-insight chat — OpenClaw lane only (PRD 15 R3)."""
    return await _openclaw_chat_handler(insight_id, request, body)
```

### 8.1 Verification: `_build_chat_context` is needed by the OpenClaw lane

Reading `_openclaw_chat_handler` (lines 1267-1329):

- Line 1285: `ctx_payload = await _build_chat_context(db_session, insight_id)  # noqa: F841`
- The `# noqa: F841` flag confirms the result is intentionally discarded.
- The function does two things: (a) `select(AIInsight).where(...)` — raises 404 if no insight — and (b) builds a payload for the prompt context.
- The OpenClaw lane builds its own context server-side via `chat_rules.md`, so item (b) is unused. Item (a) is duplicated three lines later (line 1290-1294) where `select(AIInsight)` is run again to fetch `parent_session_id`.

**Conclusion: `_build_chat_context` is technically redundant in the OpenClaw lane** — but removing it is out of scope for this PR (PRD R3 explicitly says "delete `_legacy_chat_handler`, `_chat_system_prompt`, and the dispatcher branch"; it does NOT mandate deleting `_build_chat_context`). Mark with a `# TODO(post-15)` and address in a separate cleanup PR.

> **Actionable for backend engineer:** keep `_build_chat_context` for now; add an inline TODO comment referencing this section.

---

## 9. config.py + .env.example cleanup

### 9.1 `backend/config.py`

DELETE the field at line 61:

```diff
-    openclaw_enabled: int = 1
```

KEEP `openclaw_gateway_url`, `openclaw_gateway_token`, `agent_tools_bearer`, `llama_stack_api_key`, `openclaw_session_prefix`, `synthesis_mode` (the synthesis_mode flag is in scope for arch-14 Phase 5 but not this PR), `hypothesizer_token_ceiling`.

### 9.2 `backend/.env.example`

DELETE the `OPENCLAW_ENABLED=1` line (line 25).

### 9.3 Affected tests

`backend/tests/test_openclaw_forwarder.py` lines 352, 422, 463, 484, 533, 590 — each is a `monkeypatch.setattr(settings, "openclaw_enabled", X)` mutation. Audit per-test:

| Test (line) | Current intent | Post-PR action |
|---|---|---|
| 352 | Assert OpenClaw lane is selected when flag=1 | DELETE the test entirely (no flag, no branch). |
| 422 | Assert legacy lane is selected when flag=0 | DELETE the test entirely (legacy lane gone). |
| 463 | Same as 422 (different scenario) | DELETE. |
| 484 | Same as 352 (different scenario) | Convert to a "lane is reachable" test that drops the monkeypatch. |
| 533 | Tests the dispatcher routes correctly | DELETE — dispatcher is gone. |
| 590 | Tests the rollback path | DELETE — rollback path is gone. |

`backend/tests/test_v2_chat_isolation.py` lines 210, 212 — same pattern. Drop the monkeypatch lines; the test's substantive assertion (chat lane isolation from V2 features) is unaffected.

> **Test count delta.** Estimated: -4 to -6 tests deleted (those that exercised the rollback path), +3 new tests (§10), net positive (~278 → ~278+3-5 = ~276-281). PRD AC-4 requires ≥278+3 = 281; if delete-count exceeds 3, backend engineer must add equivalent positive-path coverage to maintain the floor.

---

## 10. Test plan (pointer only)

Detailed test cases written by QA agent in a sibling doc; this section is pointer-only.

| Test file | Asserts |
|---|---|
| `backend/tests/test_qa_router.py` | (1) `POST /api/qa/ask` returns 200 + `text/event-stream`. (2) Body produces ≥1 `text_chunk` event + a final `done` event. (3) Two POSTs sharing one `X-Session-Id` header send the same `x-openclaw-session-key` upstream (mock OpenClaw + assert header). (4) When the agent calls `propose_qa_chart`, a `chart_spec` event surfaces. (5) Tool-call SSE events surface end-to-end. |
| `backend/tests/test_triangulation_router.py` | (1) `POST /api/agent/ask` returns 200 + `text/event-stream`. (2) Body produces plain `data: <delta>\n\n` lines + final `[DONE]`. (3) Two POSTs sharing one `X-Session-Id` send the same `x-openclaw-session-key`. (4) Tool-call events are NOT surfaced (`surface_tool_events=False`). |
| `backend/tests/test_routers_insights_no_legacy_imports.py` | (1) `import routers.insights as ri; assert "agents.insights.tool_loop" not in sys.modules` after import. (2) Walk `ri.__dict__` for any `llm_client` reference; assert none. (3) `assert not hasattr(ri, "_legacy_chat_handler")`. (4) `assert not hasattr(ri, "_chat_system_prompt")`. |
| (existing) `test_openclaw_forwarder.py` | Trim per §9.3. |
| (existing) `test_v2_chat_isolation.py` | Trim per §9.3. |

Mock boundary: `httpx.AsyncClient.stream` (canned `chat.completion.chunk` fixtures). The same fixture style as `test_translate_synthesis_chunk.py` already uses.

---

## 11. Migration policy doc placement (R5)

### 11.1 New file: `docs/plans/ai-insights-automation/15-extraction-vs-agent-policy.md`

Body sections (the backend engineer drafts the prose; this is the structure):

```markdown
# 15 — Extraction vs Agent vs Recursive-Skill Policy

**Date:** 2026-05-06
**Status:** Active policy. Future contributors: read this before adding any new LLM call site.

## Bucket 1 — Chat-like / agentic
ROUTE: through OpenClaw + MCP (the unified lane).
Examples: insight chat (`/api/insights/{id}/chat`), daily synthesis cron,
weekly brief cron, qa-global panel (`/api/qa/ask`), triangulation
(`/api/agent/ask`).
REASON: multi-turn memory, tool palette, session-key isolation,
audit-trail wiring already in place.

## Bucket 2 — Structured extraction (text → JSON schema)
ROUTE: direct `llm_client.extract()`.
Examples: `agents/edgar_extractor.py`, `agents/vendor_supply_extractor.py`,
`pipelines/pdf_parser.py`.
REASON: chat-completions is the wrong I/O shape — these calls produce
typed JSON from a single prompt-response, not a conversation. Routing
them through OpenClaw would (a) pollute analyst session memory with
thousands of filing chunks, (b) lose the typed-output guarantees the
extract() helper provides via response_format/json_schema, (c) add a
gateway round-trip on a hot path that's already at request-throughput
limits.

## Bucket 3 — Recursive skill internals
ROUTE: direct `llm_client.reason()`.
Examples: `agents/skills/peer_review_template.py`,
`agents/skills/methodology_explainer.py`.
REASON: these are leaves the agent invokes via the MCP `run_skill`
tool. Routing them back through OpenClaw creates a cycle —
agent → MCP → run_skill → llm_client(via OpenClaw) → MCP → ... — that
the gateway is not designed to short-circuit.

## Decision flowchart for new call sites
1. Does this LLM call hold conversational state across multiple
   user-visible turns? → Bucket 1 (OpenClaw).
2. Does this LLM call produce a typed JSON object from a single prompt
   that the rest of the pipeline reads as data? → Bucket 2 (extract).
3. Is this LLM call invoked from inside a skill that the agent picks
   via run_skill? → Bucket 3 (reason).
4. None of the above? Open a design ticket.
```

### 11.2 Appendix to `14-unified-agent-architecture.md`

Append at the end of the doc:

```markdown
---

## Migration completion (2026-05-06)

All chat-shaped LLM call sites are unified on OpenClaw + FastMCP:

| Call site | Phase | sessionKey prefix |
|---|---|---|
| `/api/insights/{id}/chat` | Phase 1 (PRD 13) | `agent:main:insight:{uuid}` |
| Daily synthesis cron | Phase 2/3 (PRD 14) | `agent:main:daily-synthesis-{YYYYMMDD}` |
| Weekly brief cron | Phase 4 (PRD 14) | `agent:main:weekly-brief-{YYYYWW}` |
| `/api/qa/ask` | Phase 5-followup (PRD 15) | `agent:main:qa:global:{x-session-id-or-hash}` |
| `/api/agent/ask` (triangulation) | Phase 5-followup (PRD 15) | `agent:main:triangulation:{x-session-id-or-hash}` |

Companion: see [`15-extraction-vs-agent-policy.md`](./15-extraction-vs-agent-policy.md)
for the bucket policy keeping new extraction / recursive-skill call sites
off the agent lane.
```

---

## 12. Risks & Mitigations

| ID | Risk | Mitigation |
|---|---|---|
| R-A | Wire-taxonomy drift on the QA lane (frontend `useQA` breaks). | `test_qa_router.py` asserts the exact event-type set against `QAEvent.__args__`. |
| R-B | Session-memory bleed across users when no X-Session-Id is sent. | `_qa_session_key` falls back to `blake2b(question)` — distinct first messages get distinct memory. PRD R-B documented; backend engineer adds inline router docstring. |
| R-C | Re-encode/re-decode round-trip in `answer_question` (§7.1.1) loses fidelity. | Pydantic `TypeAdapter(QAEvent).validate_python` round-trip is canonical; logged WARNING on validation failure. Follow-up issue to split `forward_qa` into events + bytes layers. |
| R-D | `propose_qa_chart` validation failures silently drop charts. | WARNING log with `tool_call_id` + validation errors. Operator sees in logs; user just sees no chart. Acceptable for V1. |
| R-E | Triangulation FE wire-format compat regression (we now go through `QAEvent` internally). | `routers/agent.py` keeps the plain `data: <delta>\n\n` + `[DONE]` shape; only `TextChunkEvent` + `ErrorEvent` reach the wire. Test asserts no JSON-wrapped events leak. |
| R-F | Caps too tight (120s wall) for slow upstream. | Configurable through `forward_qa` defaults; QA agent should follow up if P95 latency approaches the cap. |
| R-G | Citation surfacing dropped (decision §4.4). | The QA prompt instructs inline Markdown links; the legacy citation panel was rarely rendered. Surface CitationEvents in a follow-up if user feedback demands it. |

---

## 13. Open questions / decisions to defer

1. **OQ-1.** Lifting `_apply_tool_call_deltas` into a shared helper across all three translators. Defer (research §3 + §3.5 above) until the chat lane has a frozen golden test harness.
2. **OQ-2.** Whether the QA lane should request a stricter MCP tool palette (e.g., disable `emit_insight` family). Per arch 14 §1, OpenClaw does not support per-sessionKey tool restriction. Treat as instructional in `qa_global_rules.md`'s `## Tools` section only.
3. **OQ-3.** Splitting `forward_qa` into a `forward_qa_events()` + thin SSE-bytes wrapper to drop the encode-decode-encode round-trip in `answer_question` (§7.1.1). Defer to a follow-up perf-cleanup PR.
4. **OQ-4.** Whether to add `propose_qa_citation` MCP tool to surface CitationEvents on the QA wire. Defer (§4.4); revisit if user feedback demands it.
5. **OQ-5.** Removing `_build_chat_context` from `routers/insights.py` once the OpenClaw lane no longer needs it as a 404-prelude (§8.1). Defer to a separate cleanup PR.
6. **OQ-6.** Migrating the triangulation FE to consume `QAEvent` JSON shape (instead of plain text deltas) so the wire format unifies. NG3 of PRD; track separately.

---

## 14. Ready for backend handoff — checklist

- [ ] Read this doc + §1 module map end-to-end.
- [ ] Confirm `propose_qa_chart` registration in `mcp_server.py` does not break the existing tool-discovery contract with OpenClaw (smoke-test gateway tool list).
- [ ] Implement `QAChunkAccumulator` + `translate_qa_chunk` in `backend/openclaw/sse_translator.py`. Run translator unit tests against canned chunk fixtures.
- [ ] Implement `backend/openclaw/qa_forwarder.py::forward_qa`. Lock the wire format (single-line `data: {json}\n\n`) — do NOT call `to_sse_text`.
- [ ] Create `backend/agents/insights/prompts/qa_global_rules.md` from `datacenter_qa.py:_build_system_prompt` body per §6.2 mapping.
- [ ] Create `backend/agents/insights/prompts/triangulation_rules.md` from `triangulation_qa.SYSTEM_PROMPT` per §6.3.
- [ ] Byte-diff old vs new rendered QA system prompt; reviewer signs off (PRD R-D).
- [ ] Replace `agents/datacenter_qa.py` body with the §7.1.1 sketch. Verify `routers/qa.py` is unchanged (signature parity).
- [ ] Replace `agents/triangulation_qa.py` body with the §7.2.1 sketch. Rewrite `routers/agent.py` per §7.3.
- [ ] Delete from `routers/insights.py`: `_chat_system_prompt`, `_legacy_chat_handler`, the dispatcher branch (per §8 line ranges). KEEP `_build_chat_context` with a TODO comment.
- [ ] Delete `openclaw_enabled` field from `config.py` and `OPENCLAW_ENABLED` line from `.env.example`.
- [ ] Trim `tests/test_openclaw_forwarder.py` and `tests/test_v2_chat_isolation.py` per §9.3.
- [ ] Add `tests/test_qa_router.py`, `tests/test_triangulation_router.py`, `tests/test_routers_insights_no_legacy_imports.py`.
- [ ] Run `git grep -nE 'tool_loop|OPENCLAW_ENABLED|openclaw_enabled' backend/` — must be 0 hits outside test fixtures + archived docs (PRD AC-3).
- [ ] Run pytest: total ≥ 281 (PRD AC-4), 0 regressions.
- [ ] `alembic upgrade head` is a no-op (PRD AC-5).
- [ ] Write `docs/plans/ai-insights-automation/15-extraction-vs-agent-policy.md` per §11.1.
- [ ] Append the migration-completion appendix to `14-unified-agent-architecture.md` per §11.2.
- [ ] Smoke test: open the QA panel, ask "How much MW does Microsoft have in Virginia?", verify (a) text answer streams, (b) chart appears, (c) follow-up question remembers context (passes same `X-Session-Id`).
- [ ] Smoke test: open the Triangulation tab, ask a question, verify plain-text streaming + `[DONE]` terminator (FE backwards-compat).

---

## Appendix A — File Path Index (absolute)

- This doc: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/plans/ai-insights-automation/15-agent-unification-cleanup-architecture.md`
- PRD: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/plans/ai-insights-automation/15-agent-unification-cleanup-prd.md`
- Research: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/plans/ai-insights-automation/15-qa-translator-research.md`
- Design lineage: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/plans/ai-insights-automation/14-unified-agent-architecture.md`
- Forwarder (extends): `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/forwarder.py`
- SSE translator (extends): `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/sse_translator.py`
- QA-lane forwarder (NEW): `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/openclaw/qa_forwarder.py`
- QA schemas (frozen): `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/schemas/qa.py`
- QA router: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/routers/qa.py`
- Triangulation router: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/routers/agent.py`
- Datacenter QA agent (REPLACE): `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/datacenter_qa.py`
- Triangulation QA agent (REPLACE): `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/triangulation_qa.py`
- MCP server (extends): `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/mcp_server.py`
- Insights router (deletions): `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/routers/insights.py`
- Settings (deletion): `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/config.py`
- Env example: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/.env.example`
- Prompts loader: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/prompts/__init__.py`
- New prompt: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/prompts/qa_global_rules.md`
- New prompt: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/backend/agents/insights/prompts/triangulation_rules.md`
- New policy doc: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/plans/ai-insights-automation/15-extraction-vs-agent-policy.md`

---

**End of architecture document.**
