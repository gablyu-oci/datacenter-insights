# PRD 14 — Unified Agent (OpenClaw Phases 2–5)

**Status:** Draft for architect / backend / QA handoff
**Owner (PM):** Karan (analyst) + platform team
**Date:** 2026-05-06
**Predecessors:** PRD/ADR-13 (MCP migration, shipped), `11-openclaw-deployment.md`, `11b-openclaw-migration-architecture.md`, `11c-openclaw-migration-addendum.md`
**Successor docs:** `14-unified-agent-architecture.md` (architect), `14-unified-agent-test-evidence.md` (QA)

---

## Table of Contents

- [1. Overview](#1-overview)
- [2. Goals & Non-Goals](#2-goals--non-goals)
- [3. User Stories](#3-user-stories)
- [4. Functional Requirements](#4-functional-requirements)
  - [4.1 Phase 2 — Agentic synthesis (FR-2.x)](#41-phase-2--agentic-synthesis-fr-2x)
  - [4.2 Phase 3 — Daily cron through OpenClaw (FR-3.x)](#42-phase-3--daily-cron-through-openclaw-fr-3x)
  - [4.3 Phase 4 — Weekly brief through OpenClaw (FR-4.x)](#43-phase-4--weekly-brief-through-openclaw-fr-4x)
  - [4.4 Phase 5 — Legacy code deletion (FR-5.x)](#44-phase-5--legacy-code-deletion-fr-5x)
  - [4.5 Cross-cutting (FR-X.x)](#45-cross-cutting-fr-xx)
- [5. New MCP Write Tools](#5-new-mcp-write-tools)
- [6. Caps & Cost Discipline](#6-caps--cost-discipline)
- [7. Acceptance Criteria](#7-acceptance-criteria)
- [8. Phased Rollout & Rollback](#8-phased-rollout--rollback)
- [9. Open Questions & Risks](#9-open-questions--risks)
- [10. Out of Scope (Recap)](#10-out-of-scope-recap)
- [11. Glossary](#11-glossary)

---

## 1. Overview

The strategic-insights-tool today runs three distinct LLM workloads on three separate code paths:

1. **Daily synthesis** — `backend/agents/insights/orchestrator.py` builds a FactPack, then calls `hypothesizer.py::synthesize_insights`, which is a single JSON-schema mega-prompt returning 5–10 insights at once. No tool use, no drill-down, no memory.
2. **Weekly brief** — `backend/agents/weekly_brief.py` invokes `llm_client.reason()` once with last week's insights inlined into the prompt. No tool use, no memory.
3. **Insight chat** — `/api/insights/insights/{id}/chat` is dual-laned. With `OPENCLAW_ENABLED=1` the request forwards to OpenClaw on `localhost:7474`, which dials the FastAPI MCP server at `/mcp`. With `=0` it falls back to the in-process `ToolLoopDriver`. The OpenClaw lane works in production today.

Phase 1 (PRD/ADR-13, shipped) made the chat lane agentic on OpenClaw. Phases 2–5 extend that same agent to handle synthesis and the weekly brief, then delete the dual-lane scaffolding.

The product outcome: **one agent persona, one toolbox, one audit trail, one cost knob**. Each insight already has a chat session keyed `insight:<uuid>`. Synthesis runs are keyed `daily-synthesis-YYYYMMDD` (cron) or `manual-{session_id}` (Run again button). Weekly briefs are keyed `weekly-brief-YYYYWW`. Sessions are isolated by sessionKey, but the SAME system prompt and the SAME MCP toolbelt back all of them.

ETL crons (`edgar_daily`, `permits_*`, `anomaly_detection_nightly`, etc.) do not call an LLM and are not in scope.

---

## 2. Goals & Non-Goals

### Goals

- **G1.** Unify all agentic/LLM activity (synthesis, weekly brief, chat) on OpenClaw + MCP. One persona, one toolbox, one audit table.
- **G2.** Replace `synthesize_insights` mega-call with an agentic loop. The agent decides when to call `query_database`, `web_search`, `run_skill`, `get_chart_data`, and persists insights one-by-one via a new `persist_insight` MCP tool.
- **G3.** Retire the legacy `ToolLoopDriver`, the `_legacy_chat_handler`, the `_chat_system_prompt` / `_build_chat_context` helpers, and the `OPENCLAW_ENABLED` dispatcher branch. Single code path post Phase 5.
- **G4.** Cap-driven cost discipline. Every session bounded by turn-count, tool-call count, wall-clock, and a soft 80K-token warning. Cost surfaced via `/api/insights/cost-summary` with a rolling 7-day average.
- **G5.** Zero frontend changes. The SSE wire shape on `/api/insights/insights/{id}/chat` is byte-for-byte unchanged from the React `SessionRunner`'s point of view.
- **G6.** Zero Postgres schema changes. We re-use `ai_session`, `agent_message`, `agent_tool_call`, `ai_insight`, `brief_run`. (Adding indexes only is acceptable; data-model migrations are not.)
- **G7.** Identical public API contracts. `/api/insights/latest`, `/api/insights/sessions/{id}/insights`, `/api/insights/insights/{id}/chat` return the same JSON shape and HTTP status codes pre and post migration.
- **G8.** Unified memory across modalities. The agent uses the OpenClaw session memory store for thread history; chat sessions are scoped per insight, synthesis sessions per run, brief sessions per week.

### Non-Goals

- **NG1.** No new gateway. OpenClaw on `localhost:7474` is the only gateway.
- **NG2.** No new MCP server. The native Python MCP at `/mcp` on the FastAPI app is the only MCP. New tools are added to it.
- **NG3.** No scheduler change. APScheduler remains in-process. Cron jobs invoke OpenClaw via the existing forwarder client; they do not become external jobs.
- **NG4.** No SSE wire taxonomy change. We do not introduce a new envelope versioning scheme or break `assistant_message_token` / `tool_call_*`. Net-new event types (e.g. `insight_started`) ride alongside as additive frames.
- **NG5.** No model change. `oci/openai.gpt-5.4` via Llama Stack stays. `reasoning: false` stays. We do not switch to a reasoning-mode model in this PRD.
- **NG6.** No frontend work. React stays unchanged. If a new SSE frame type is added, the frontend simply ignores it.
- **NG7.** No Postgres data-model migrations.
- **NG8.** No hard dollar enforcement. The 7-day cost dashboard is observability only.

---

## 3. User Stories

> Format: As a [persona], I want [capability] so that [benefit].

- **US-1 (Analyst — Karan).** As an analyst, I want the **"Run again"** button on the AI Insights tab to still produce 3–5 fresh insights with charts and citations, so that my day-of-week briefing flow is unaffected.
- **US-2 (Analyst — Karan).** As an analyst, I want the **daily 09:00 UTC cron** to publish today's insights via the same agentic path, so that what I see on Monday morning matches what I'd get if I clicked "Run again" myself.
- **US-3 (Analyst — Karan).** As an analyst, I want the **weekly brief on Sunday 23:00 UTC** to come out of the same agent (not a separate prompt), so that the brief's voice and citation style match the daily insights.
- **US-4 (Analyst — Karan).** As an analyst, I want to **drill into any insight via chat** with the same memory context the synthesis agent had, so that follow-up questions don't lose the synthesis-time evidence.
- **US-5 (Operator).** As an operator, I want a **rolling 7-day cost dashboard** at `/api/insights/cost-summary` showing token usage per session class (synthesis / brief / chat), so that I can spot a runaway cron before it blows the budget.
- **US-6 (Operator).** As an operator, I want every synthesis run to leave a **trail of `agent_tool_call` rows** (`query_database`, `web_search`, `run_skill`, `persist_insight`), so that I can audit what evidence each insight was built on.
- **US-7 (Developer).** As a developer, I want **one chat handler, one system prompt, one toolbelt**, so that bug fixes don't have to be applied twice (once to legacy, once to OpenClaw).
- **US-8 (Developer).** As a developer, I want a **`SYNTHESIS_MODE=legacy|agentic`** rollback flag during Phases 2–4, so that I can revert to the JSON-schema mega-call within minutes if the agentic loop misbehaves on a Monday morning.
- **US-9 (Developer).** As a developer, I want a **`pytest -k smoke_unified_agent` smoke** that verifies tool calls are visible in `agent_message` + `agent_tool_call` after a synthesis run, so that PR review has a hard signal beyond "looks fine."
- **US-10 (QA).** As QA, I want **AC-driven evidence rows** (insight count, persistence rows, SSE byte-diff vs golden, deleted-symbol grep) collected automatically by a Phase-5 sign-off script, so that the rollout decision is mechanical.

---

## 4. Functional Requirements

Each FR is numbered for traceability. Architect doc must reference these IDs in design sections; QA evidence must reference them in test names.

### 4.1 Phase 2 — Agentic synthesis (FR-2.x)

- **FR-2.1.** A new `run_agentic_synthesis(session_id: UUID, mode: Literal["manual","scheduled"], target_insight_count: int = 5) -> SynthesisResult` orchestrator function MUST exist in `backend/agents/insights/agentic_orchestrator.py` and be the only synthesis entry point used by the manual "Run again" button when `SYNTHESIS_MODE=agentic`.
- **FR-2.2.** `run_agentic_synthesis` MUST open an OpenClaw session with `sessionKey` = `manual-{session_id}` for manual runs and `daily-synthesis-{YYYYMMDD}` for scheduled runs (Phase 3).
- **FR-2.3.** The agent MUST be invoked with the unified system prompt (see FR-X.1) and a single user-turn input pack: today's date, the FactPack summary digest (NOT the full FactPack — the agent pulls detail via `query_database`), the target insight count, and the cap reminders.
- **FR-2.4.** The agent MUST call `persist_insight` for each insight it produces. Each call validates against the existing `InsightOutput` pydantic model in `hypothesizer.py`. Server-side, the MCP tool returns the new `ai_insight.id`.
- **FR-2.5.** The agent MUST call `finalize_session(session_id, status, token_estimate)` exactly once at end of run. The MCP tool flips the `ai_session` row to `status=succeeded|failed|partial` and writes token estimate.
- **FR-2.6.** If the agent persists fewer than `MIN_INSIGHTS_PER_RUN` (default 3) insights when wall-clock or turn-cap hits, the orchestrator MUST mark the session `partial` (not `failed`) and surface in the API response.
- **FR-2.7.** The orchestrator MUST NOT inline the FactPack in the prompt. The FactPack remains queryable via `query_database` / `get_chart_data` so the agent decides what to fetch.
- **FR-2.8.** The orchestrator MUST honor the existing per-run `WEB_SEARCH_PER_RUN=8` cap. The cap is enforced server-side in `web_search` MCP tool, scoped by OpenClaw `sessionKey`.
- **FR-2.9.** A `SYNTHESIS_MODE` env flag (`legacy` | `agentic`, default `agentic` after Phase 2 is GA) MUST control the dispatcher in `routers/insights.py`. While `legacy`, the existing `synthesize_insights` mega-call runs untouched. The flag is REMOVED in Phase 5 (FR-5.6).
- **FR-2.10.** The agentic loop MUST emit additive SSE frames (`insight_started`, `insight_complete`) on the manual run channel for live UX. Frontend ignores unknown frames; this is forward-compatible. (Backend-only deliverable; no FE change.)
- **FR-2.11.** The agent's stop condition is the FIRST of: (a) it has called `persist_insight` `target_insight_count` times AND then called `finalize_session`, (b) 12 LLM turns elapsed, (c) 30 tool-calls elapsed, (d) 600s wall-clock elapsed.

### 4.2 Phase 3 — Daily cron through OpenClaw (FR-3.x)

- **FR-3.1.** The existing APScheduler job `insights_daily` (09:00 UTC) MUST invoke `run_agentic_synthesis(session_id=<new>, mode="scheduled")` instead of the legacy synthesis path.
- **FR-3.2.** The scheduled job MUST tag the new `ai_session` row with `created_by="scheduler"` and `cron_run_date=<today UTC date>` columns (already present on `ai_session`).
- **FR-3.3.** If the cron job's wrapper does not receive a `finalize_session` frame within 600s, the wrapper MUST flip the session row to `status=failed` with a reason `wall_clock_exceeded` and emit a structured log line at WARN.
- **FR-3.4.** Cron-run insights MUST be retrievable by `/api/insights/latest` with no API change — the public endpoint resolves "latest" by `created_at` ordering across both manual and scheduled sessions, which already works today.
- **FR-3.5.** A duplicate-suppression guard MUST prevent the cron firing twice on the same UTC date. If a `daily-synthesis-{YYYYMMDD}` session already exists with `status in (running, succeeded, partial)`, the cron skips with a logged INFO. (Re-run requires the manual button, which uses `manual-{...}` keys.)
- **FR-3.6.** The cron job's exception path MUST NOT crash APScheduler; failures land as `status=failed` rows + a single ERROR log line.

### 4.3 Phase 4 — Weekly brief through OpenClaw (FR-4.x)

- **FR-4.1.** A new MCP tool `persist_brief(period_start: date, period_end: date, markdown: str, model: str, prompt_version: str) -> BriefRun.id` MUST be added to the MCP server (see Section 5).
- **FR-4.2.** A new function `run_agentic_brief(period_start: date, period_end: date) -> BriefRun.id` in `backend/agents/weekly_brief.py` MUST replace the existing single `llm_client.reason()` call.
- **FR-4.3.** The weekly brief session MUST use `sessionKey` = `weekly-brief-{YYYYWW}` (ISO week).
- **FR-4.4.** The agent MUST be allowed to call `query_database` to pull the week's insights, `web_search` to add timely context, and `persist_brief` exactly once at end. Calling `persist_brief` more than once in the same session returns an idempotency error from the MCP tool.
- **FR-4.5.** The Sunday 23:00 UTC APScheduler job `weekly_brief_publish` MUST invoke `run_agentic_brief` instead of the legacy path.
- **FR-4.6.** The brief agent's caps are the same as synthesis (Section 6) except `target_persists=1`. Agent MUST call `finalize_session` after `persist_brief`.
- **FR-4.7.** If `persist_brief` is never called within wall-clock, the cron wrapper marks the brief session `failed` and DOES NOT publish a partial brief to the public API.

### 4.4 Phase 5 — Legacy code deletion (FR-5.x)

- **FR-5.1.** Delete `backend/agents/chat/tool_loop.py` (the `ToolLoopDriver` class) entirely. All imports updated.
- **FR-5.2.** Delete `synthesize_insights` from `backend/agents/insights/hypothesizer.py`. The `InsightOutput` pydantic model STAYS (re-used by `persist_insight` validation).
- **FR-5.3.** Delete `_legacy_chat_handler`, `_chat_system_prompt`, `_build_chat_context` from `backend/routers/insights.py` (or wherever they currently live; greppable symbols).
- **FR-5.4.** Delete the `OPENCLAW_ENABLED` dispatcher branch in the chat endpoint and the corresponding config field in `backend/config.py` (or settings module).
- **FR-5.5.** Delete legacy synthesis tests that exercise the JSON-schema mega-call as a unit. Replace with agentic-loop integration tests that assert tool-call sequence and persisted-row counts. Net test count MUST remain >= 250 (down from 265 baseline; budget for 15 deleted tests).
- **FR-5.6.** Remove the `SYNTHESIS_MODE` env flag and all branches gated by it. Single code path, no flag.
- **FR-5.7.** Remove the `OPENCLAW_ENABLED` env flag from `.env.example`, deployment manifests, and operator runbooks.
- **FR-5.8.** A grep gate in CI MUST fail the build if any of these symbols reappear after Phase 5: `ToolLoopDriver`, `synthesize_insights`, `_legacy_chat_handler`, `_chat_system_prompt`, `_build_chat_context`, `OPENCLAW_ENABLED`, `SYNTHESIS_MODE`.

### 4.5 Cross-cutting (FR-X.x)

- **FR-X.1.** **SOUL.md split.** The current `.openclaw/personas/analyst/SOUL.md` MUST be split into three sibling files OR three labelled sections within one file: `synthesis_rules`, `chat_rules`, `brief_rules`. The agent's system prompt is composed at session-open time based on `sessionKey` prefix (`manual-` / `daily-synthesis-` => synthesis_rules + chat_rules common; `weekly-brief-` => brief_rules + chat_rules common; `insight:` => chat_rules only). The "common" voice/citation rules live once.
- **FR-X.2.** **Token ceiling bump.** Raise `HYPOTHESIZER_TOKEN_CEILING` from 30,000 to 80,000 (warn-only, no abort). Setting lives in `backend/config.py`. The legacy 30K was sized for the mega-prompt; the agentic loop will spread tokens across 12 turns.
- **FR-X.3.** **Cost summary endpoint.** A new `GET /api/insights/cost-summary` MUST return:
  ```json
  {
    "window_days": 7,
    "by_class": {
      "synthesis": {"sessions": int, "total_tokens": int, "avg_tokens_per_session": float, "p95_tokens_per_session": int},
      "brief":     {"sessions": int, "total_tokens": int, "avg_tokens_per_session": float, "p95_tokens_per_session": int},
      "chat":      {"sessions": int, "total_tokens": int, "avg_tokens_per_session": float, "p95_tokens_per_session": int}
    },
    "as_of": "2026-05-06T12:00:00Z"
  }
  ```
  Class is derived from `ai_session.session_key` prefix. Endpoint is read-only, requires the same auth as `/api/insights/latest` (none in current build; matches existing posture).
- **FR-X.4.** **Telemetry parity.** Every OpenClaw turn (synthesis, brief, chat) MUST write `agent_message` and `agent_tool_call` rows with `session_id` matching the parent `ai_session.id`. Existing schema, no migration.
- **FR-X.5.** **Smoke test.** A `pytest -k smoke_unified_agent` test MUST exist in `backend/tests/` that: opens a synthesis session against a mocked OpenClaw, asserts >=3 `persist_insight` calls landed, asserts at least one `query_database` and one `web_search` row in `agent_tool_call`, asserts `finalize_session` called exactly once.
- **FR-X.6.** **Backwards-compat for `/api/insights/insights/{id}/chat`.** SSE wire MUST remain byte-for-byte identical to today's OpenClaw-lane output (a golden recording is captured pre-Phase-5 and diffed in CI).
- **FR-X.7.** **Migration of existing tests.** Tests that today set `OPENCLAW_ENABLED=1` explicitly MUST be cleaned up to remove the env mutation (the flag no longer exists post Phase 5).

---

## 5. New MCP Write Tools

These are added to the existing native Python MCP server at `/mcp` (no new server). Each is callable by the agent via the OpenClaw forwarder with bearer auth. Each is validated server-side and is idempotent within a session.

### 5.1 `persist_insight`

**Signature:**
```
persist_insight(
  insight: dict,                  # validated against InsightOutput pydantic in hypothesizer.py
  supporting_row_ids: list[str]   # opaque IDs from query_database results
) -> {"insight_id": "<uuid>", "ordinal": int}
```

**Validation:**
- `insight` MUST pass `InsightOutput.model_validate(insight)`. Any ValidationError returns a 400-equivalent MCP error with the field-level diff.
- `supporting_row_ids` MUST be non-empty. (No insights without evidence.)

**Idempotency / state:**
- The MCP server keeps a server-side counter `persist_count[session_id]`. If the agent calls `persist_insight` more than `target_insight_count + 1` times in the same session, the call returns an MCP error `MAX_INSIGHTS_EXCEEDED`. The +1 buffer allows for a regenerated insight that replaces a rejected one.
- Returns the new `ai_insight.id` and the 1-based `ordinal` (call number within session).

**Side effects:**
- INSERT into `ai_insight` with `session_id` derived from MCP session context.
- INSERT into `ai_insight_evidence` (or whatever the existing evidence join table is called) for each `supporting_row_id`.

### 5.2 `finalize_session`

**Signature:**
```
finalize_session(
  status: Literal["succeeded", "partial", "failed"],
  token_estimate: int,
  reason: str | None = None
) -> {"ok": true, "session_id": "<uuid>"}
```

**Validation:**
- `token_estimate >= 0`.
- `reason` REQUIRED if `status != "succeeded"`.

**Idempotency / state:**
- A second call in the same session is a no-op that returns the previously-committed result. (Agents sometimes re-emit on retry; we don't want a 500.)

**Side effects:**
- UPDATE `ai_session` SET `status`, `token_estimate`, `ended_at=now()`, `failure_reason=reason`.

### 5.3 `persist_brief`

**Signature:**
```
persist_brief(
  period_start: date,             # ISO date
  period_end: date,               # ISO date, inclusive
  markdown: str,                  # the brief body, ~2-5KB typical
  model: str,                     # e.g. "oci/openai.gpt-5.4"
  prompt_version: str             # e.g. "brief_rules@v1"
) -> {"brief_id": "<uuid>"}
```

**Validation:**
- `period_end >= period_start`.
- `period_end - period_start <= 14 days` (sanity).
- `markdown` non-empty, length <= 50KB.

**Idempotency / state:**
- If `persist_brief` is called twice in the same MCP session, the second call returns MCP error `BRIEF_ALREADY_PERSISTED`.
- If a `BriefRun` row already exists for the same `(period_start, period_end)`, the call returns MCP error `BRIEF_DUPLICATE_PERIOD` UNLESS the existing row has `status=failed` (in which case it overwrites).

**Side effects:**
- INSERT into `brief_run` with `status=succeeded`, `published_at=now()`.

### 5.4 Tool registration

All three are registered in the same MCP module that already hosts `query_database`, `call_api`, `get_chart_data`, `web_search`, `run_skill`, `emit_chart`, `emit_citation`. Total tool count post Phase 4: **10**.

---

## 6. Caps & Cost Discipline

Caps are per OpenClaw session. They apply equally to synthesis, brief, and chat sessions (the persona is the same; the caps are the same).

| Cap | Value | Enforcement | Rationale |
|---|---|---|---|
| LLM turns | **12** max | Hard abort at gateway; agent receives `TURNS_EXCEEDED`. | gpt-5.4 non-reasoning needs room to chain query → think → persist; 12 is enough for 5 insights @ ~2 turns each + 2 buffer. |
| Tool calls | **30** max (down from 40 V1) | Hard abort at gateway. | Discipline. V1 chat rarely exceeded 15; synthesis budget for 5 insights × ~5 tool calls = 25, plus margin. |
| Wall clock | **600 s** | `asyncio.wait_for` outside the agentic loop in the FastAPI handler; cron wrapper has its own 600s timer. | Bounds cron drains; lets us flip to `failed` cleanly. |
| Total tokens | **80,000** | **Warn-only, no abort.** Logged at WARN if exceeded, surfaced in cost dashboard. | Hard cap caused mid-run aborts in V0; warn-only respects user intent. |
| `web_search` calls per session | **8** (existing `WEB_SEARCH_PER_RUN`) | Hard cap server-side in MCP tool. | Brave free-tier RPS protection. |
| `persist_insight` calls per session | `target_insight_count + 1` | Hard cap server-side in MCP tool. | Prevents runaway loops. |
| `persist_brief` calls per session | **1** | Hard cap server-side in MCP tool. | One brief per session. |

**Hard $ cap:** **NOT enforced in code.** Out of scope for this PRD. Surfaced as observability via `/api/insights/cost-summary` (FR-X.3). A future PRD may add per-day token budgets with hard cutoff.

**Cost class derivation:** the cost dashboard partitions by `ai_session.session_key` prefix:
- `manual-*` or `daily-synthesis-*` => `synthesis`
- `weekly-brief-*` => `brief`
- `insight:*` => `chat`

---

## 7. Acceptance Criteria

Each AC has a unique ID. QA evidence doc (`14-unified-agent-test-evidence.md`) MUST include one row per AC with pass/fail + artifact link.

- **AC-1.** Manual "Run again" button on the AI Insights tab (UI unchanged) produces **3–5 insights**, each persisted to `ai_insight`, each with `>= 1` chart and `>= 1` citation. Verified by clicking the button on a clean session and reading `/api/insights/sessions/{id}/insights`.
- **AC-2.** The 09:00 UTC daily cron fires an OpenClaw turn. Within 10 minutes, a row exists in `ai_session` with `created_by="scheduler"`, `cron_run_date=<today UTC>`, `session_key="daily-synthesis-YYYYMMDD"`, and `status in ("succeeded","partial")`. At least one `ai_insight` row references that session.
- **AC-3.** Sunday 23:00 UTC fires `weekly_brief_publish`. Within 10 minutes, a new `brief_run` row exists with the past-week period and `status="succeeded"`, and an `ai_session` row with `session_key="weekly-brief-YYYYWW"` exists.
- **AC-4.** SSE wire shape on `/api/insights/insights/{id}/chat` is byte-for-byte unchanged from frontend POV. A golden SSE recording captured pre-Phase-5 plays back identically post-Phase-5 (modulo tool-call IDs and timestamps, which are normalized in the diff). React `SessionRunner` is unchanged on disk (git diff = 0 lines).
- **AC-5.** `git grep -nE 'ToolLoopDriver|synthesize_insights|_legacy_chat_handler|_chat_system_prompt|_build_chat_context|OPENCLAW_ENABLED|SYNTHESIS_MODE'` returns **zero hits** in `backend/` (excluding archive/docs directories) at Phase-5 sign-off.
- **AC-6.** `agent_message` and `agent_tool_call` rows for a freshly-run synthesis session show: at least 1 `query_database` call, at least 1 `web_search` call, at least 1 `run_skill` call, and N `persist_insight` calls where 3 <= N <= 5. Verified via SQL select on the synthesis `session_id`.
- **AC-7.** `/api/insights/latest`, `/api/insights/sessions/{id}/insights`, `/api/insights/insights/{id}/chat` return **identical JSON shapes** (same keys, same nesting) pre and post migration. Verified by JSON-schema diff on representative recorded responses.
- **AC-8.** `pytest` reports **>= 250 passing** tests. `alembic upgrade head` runs clean. `cd frontend && npm run build` produces a green production build.
- **AC-9.** During Phases 2–4, setting `SYNTHESIS_MODE=legacy` reverts to the JSON-schema mega-call within one process restart, with no data loss. The flag is REMOVED at end of Phase 5; setting it in env after Phase 5 has no effect.
- **AC-10.** **STOP rule.** If 3 consecutive agentic synthesis smoke runs produce **fewer than 3 insights each**, halt the rollout. Open a regression note in `docs/plans/ai-insights-automation/14-unified-agent-regression.md` capturing turn counts, tool-call sequences, and final agent messages. Do NOT proceed to the next phase until the note is closed.
- **AC-11.** `/api/insights/cost-summary` returns the schema in FR-X.3 with non-null counts after at least one synthesis, one brief, and one chat session has been recorded in the prior 7 days.
- **AC-12.** A `pytest -k smoke_unified_agent` smoke test (FR-X.5) passes in CI, asserting tool-call audit trail.

---

## 8. Phased Rollout & Rollback

Each phase is a single PR (or small PR series) gated on its closing ACs. Each rollback is a `git revert <commit>` plus a flag flip; no data migration is required to roll back.

| Phase | Deliverable | Closes ACs | User-visible? | Rollback |
|---|---|---|---|---|
| **2** | Agentic synthesis path behind `SYNTHESIS_MODE=agentic`. Manual "Run again" routes through OpenClaw. New MCP tools `persist_insight` + `finalize_session` shipped. SOUL.md split (FR-X.1). Token ceiling bumped to 80K (FR-X.2). | AC-1, AC-6, AC-9 (partial), AC-12 | Yes (Run again now goes through the new path; insights look the same). Frame additive `insight_started` SSE shows up but FE ignores. | `git revert` the agentic orchestrator PR; set `SYNTHESIS_MODE=legacy`. Legacy `synthesize_insights` still present. |
| **3** | Daily 09:00 UTC cron switched to `run_agentic_synthesis(mode="scheduled")`. Cron-side wall-clock + duplicate-suppression guard. | AC-2 | No (insights appear at the same time, same UI). | `git revert` cron-flip PR. APScheduler reloads the legacy job pointer. `SYNTHESIS_MODE=legacy` honored. |
| **4** | Weekly brief through OpenClaw. New MCP tool `persist_brief`. Sunday 23:00 UTC cron switched. Brief rules section in SOUL. | AC-3 | No (Sunday brief looks the same). | `git revert` brief-flip PR. Legacy `weekly_brief.py::run` path still present until Phase 5. |
| **5** | Legacy code deleted (FR-5.1 through FR-5.8). `SYNTHESIS_MODE` flag removed. `OPENCLAW_ENABLED` flag removed. Grep gate added to CI. `/api/insights/cost-summary` shipped (FR-X.3). Smoke test (FR-X.5) added. Golden SSE recording captured & diffed in CI. | AC-4, AC-5, AC-7, AC-8, AC-9 (full), AC-10, AC-11 | No (single code path; behavior identical). | `git revert` deletion PR. Flag-removed code is restored. **Note:** post Phase 5, there is no `OPENCLAW_ENABLED` env knob — the gateway is required. If OpenClaw is unhealthy, the system fails closed; the Phase-5 revert PR is the rollback. |

**Phase exit criteria:** every AC closed by a phase MUST have evidence captured in `14-unified-agent-test-evidence.md` before the next phase opens.

**Time-boxing:** Phases 2 and 5 are the heaviest (new agent loop, deletions). Phases 3 and 4 are flag-flips on top of Phase 2's foundation and should each be < 1 day of focused work.

---

## 9. Open Questions & Risks

### R-1. gpt-5.4 (non-reasoning) may not converge in 12 turns on a 5-insight target

**Severity:** High
**Likelihood:** Medium
**Mitigation:**
- Start with `target_insight_count=5` (not 8 or 10).
- System prompt includes an explicit **STOP after N insights** instruction with the literal value injected.
- Add a "thinking budget" hint in the prompt: "You have approximately 12 turns. Plan to spend ~2 turns per insight: one to query, one to persist. Do not write throwaway scratchpad turns."
- AC-10 STOP rule (3 consecutive sub-3-insight runs => halt) catches non-convergence early.

### R-2. SSE translator (`sse_translator.py`) may need new event types

**Severity:** Medium
**Likelihood:** High
**Mitigation:**
- Architect doc MUST address whether `insight_started` / `insight_complete` / `chart` synthesis events ride the existing `tool_call_*` taxonomy or are net-new event types.
- Either way, the contract is **additive only**. Frontend ignores unknown event types today (verified). No FE change required either way.
- If new types are added, the golden SSE recording for chat (AC-4) excludes synthesis events from its diff (chat sessions don't emit them).

### R-3. `persist_insight` called more than `max_insights` times

**Severity:** Medium
**Likelihood:** Medium (LLMs over-emit when prompted ambiguously)
**Mitigation:**
- Server-side counter in MCP tool (Section 5.1). Hard cap at `target_insight_count + 1`.
- Counter is keyed by MCP `session_id`, lives in process memory of the FastAPI app. Process restart between synthesis runs is fine; sessions don't span restarts.
- On overflow, MCP tool returns `MAX_INSIGHTS_EXCEEDED` error to the agent, which gpt-5.4 will see and (per the system prompt) treat as a signal to call `finalize_session`.

### R-4. Brave free-tier RPS exceeded across simultaneous synthesis + chat sessions

**Severity:** Medium
**Likelihood:** Medium (Monday morning: cron 09:00 UTC + Karan opens chat at 09:01 UTC)
**Mitigation:**
- Existing `WEB_SEARCH_PER_RUN=8` cap is **per session**, not global. Two concurrent sessions can each spend 8.
- For Phase 5+, consider a global token-bucket on `web_search` (not in scope for this PRD; logged as future work).
- Cron job runs at 09:00 UTC (~ 02:00 PT, ~ 05:00 ET) when interactive chat usage is near zero. Real concurrency risk is low.

### R-5. Cron drains never get a `finalize_session` frame

**Severity:** Medium
**Likelihood:** Low–Medium
**Mitigation:**
- 600s `asyncio.wait_for` in the cron wrapper (FR-3.3, FR-4.7).
- On timeout, wrapper flips the `ai_session` row to `status=failed`, `failure_reason="wall_clock_exceeded"`, and emits a structured WARN log line.
- The next 09:00 UTC cron is unaffected; duplicate-suppression (FR-3.5) only blocks if status is `running|succeeded|partial`, not `failed`. Wait — review: a `failed` row should NOT block the next day's cron. Spec confirms `cron_run_date` is per-day, so the next day's job has a different key and runs cleanly.

### R-6. Unified-memory leakage across session classes

**Severity:** Low–Medium
**Likelihood:** Low
**Mitigation:**
- OpenClaw session memory is keyed by `sessionKey`. Synthesis sessions and chat sessions have different keys (`daily-synthesis-...` vs `insight:...`) and therefore separate memory.
- The architect MUST confirm OpenClaw's session-store backend (sqlite? in-memory dict?) does not key-collide across prefixes.

### R-7. `gpt-5.4` outputting invalid `InsightOutput` JSON to `persist_insight`

**Severity:** Low
**Likelihood:** Medium (the model is fast, not strict)
**Mitigation:**
- `persist_insight` validates with the existing `InsightOutput` pydantic model and returns a structured error to the agent on validation failure.
- The agent has a chance to retry within its turn budget. If it fails 3x in a row, it calls `finalize_session(status="partial")`.
- We do NOT add a JSON-mode constraint at the gateway layer in this PRD — that would require a separate ADR.

### R-8. Cost-summary endpoint is expensive at read time

**Severity:** Low
**Likelihood:** Low
**Mitigation:**
- Query is `SELECT session_key, status, token_estimate FROM ai_session WHERE created_at > now() - interval '7 days'`. Index on `created_at` already exists. Aggregation in Python is fine for the volumes we'll see (< 200 rows/week).

### Open Question — OQ-1
Does OpenClaw's session memory persist across FastAPI restarts? If yes, do we want it to? Architect to document.

### Open Question — OQ-2
Do we want to back-port the agentic loop's tool-call audit trail to existing chat sessions (i.e., is the V1 chat lane already writing to `agent_tool_call`)? If not, the cost dashboard's `chat` class will be undercounted in the first 7 days. Backend to confirm.

### Open Question — OQ-3
Should `persist_brief` markdown be sanitized (HTML strip, link allowlist) before storage? Out of scope here, but flag it for security review post Phase 4.

---

## 10. Out of Scope (Recap)

- **Frontend.** Zero React changes. The SSE wire taxonomy is additive only. New event types are ignored by the existing `SessionRunner`.
- **ETL crons.** `edgar_daily`, `permits_*`, `anomaly_detection_nightly`, and any other non-LLM scheduled job are unchanged. They do not call OpenClaw.
- **Postgres schema migrations.** Index additions are acceptable; data-model changes are not. Re-use `ai_session`, `agent_message`, `agent_tool_call`, `ai_insight`, `brief_run`.
- **New gateway / new MCP server.** OpenClaw on `localhost:7474` and the FastAPI MCP at `/mcp` are the only ones.
- **Scheduler change.** APScheduler stays in-process.
- **Hard dollar cost enforcement.** Observability only via cost-summary endpoint.
- **Model swap.** `oci/openai.gpt-5.4` (`reasoning: false`) stays.
- **Authentication / authz.** No change to existing posture on `/api/insights/*` endpoints.

---

## 11. Glossary

- **OpenClaw.** The agent gateway (claude-dev-team's OpenClaw fork) running at `localhost:7474`, dialing the FastAPI MCP server via streamable-HTTP with bearer auth.
- **MCP server.** Native Python Model-Context-Protocol server mounted at `/mcp` on the FastAPI app. Hosts the agent toolbelt.
- **FactPack.** A pre-computed bundle of structured facts (deals, permits, anomalies) the legacy `synthesize_insights` mega-call took as input. In the agentic path, the FactPack is queryable via `query_database` rather than inlined into the prompt.
- **`InsightOutput`.** The pydantic model in `backend/agents/insights/hypothesizer.py` that defines an insight's shape (title, narrative, charts, citations, supporting rows). Re-used post Phase 5 by `persist_insight` validation.
- **`sessionKey`.** OpenClaw's session-isolation key. Synthesis: `daily-synthesis-YYYYMMDD` or `manual-{session_id}`. Brief: `weekly-brief-YYYYWW`. Chat: `insight:<uuid>`.
- **`SYNTHESIS_MODE`.** Temporary env flag (`legacy` | `agentic`) live during Phases 2–4, removed in Phase 5.
- **`OPENCLAW_ENABLED`.** Existing env flag (`0` | `1`) gating chat dual-lane today; removed in Phase 5.
- **Persona.** The system-prompt + tool-policy bundle in `.openclaw/personas/analyst/`. Phase 2 splits SOUL.md into synthesis / chat / brief sections (FR-X.1).
- **Cost class.** Derived label (`synthesis` | `brief` | `chat`) used by the cost dashboard. Derived from `ai_session.session_key` prefix.

---

**End of PRD-14.**

Hand off to: architect (`14-unified-agent-architecture.md`), backend, QA (`14-unified-agent-test-evidence.md`).
