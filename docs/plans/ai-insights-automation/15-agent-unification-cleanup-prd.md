# 15 — Agent Unification Cleanup PRD (Phase 5 Follow-up)

**Author:** Product Manager
**Date:** 2026-05-06
**Status:** Ready for backend handoff
**Predecessor:** [`14-unified-agent-architecture.md`](./14-unified-agent-architecture.md) — design lineage; this PRD finishes the migration that doc began.
**Successor:** `15-agent-unification-cleanup-test-evidence.md` (QA, after merge)

---

## Overview

Phases 1–5 (PRD-13, PRD-14) consolidated three LLM workloads — insight chat, daily synthesis, and the weekly brief — onto a single agent served by OpenClaw + FastMCP. Two LLM call sites and one orphan dispatcher block were not migrated in that pass:

1. `POST /api/qa/ask` — the floating "Ask the Analyst" chat panel.
2. `POST /api/agent/ask` — the Triangulation Q&A endpoint.
3. A dead `if openclaw_enabled == 1` branch + `_legacy_chat_handler` in `routers/insights.py` (lines 922–1259) that still imports `agents.insights.tool_loop`, a module deleted in Phase 5.

The orphan import is a landmine: any future refactor that exercises that branch crashes at import time. The two remaining direct-`llm_client` call sites mean the unification claim in doc 14 is not yet true on the wire — analyst memory does not span the QA panel and the triangulation tab is unaware of the agent's tool palette.

This PRD covers the final cleanup: migrate the two endpoints onto OpenClaw via the existing `_drive_openclaw_stream` helper, delete the orphan branch, retire the `openclaw_enabled` flag entirely, and document the bright line between the agent lane and the structured-extraction / recursive-skill lanes that intentionally remain on direct `llm_client`.

After this PRD ships, the codebase has exactly one chat-shaped LLM lane.

---

## Goals & Non-Goals

### Goals

- G1. Route `POST /api/qa/ask` through OpenClaw using the shared `_drive_openclaw_stream` helper from `backend/openclaw/forwarder.py`.
- G2. Route `POST /api/agent/ask` (triangulation) through OpenClaw the same way.
- G3. Delete the orphan dispatcher branch and `_legacy_chat_handler` in `routers/insights.py`. One code path, no flag.
- G4. Remove `openclaw_enabled` from `config.py` and `.env.example`. The setting must not exist anywhere except in archived docs.
- G5. Move the long QA system prompt and the triangulation system prompt out of Python source into versioned prompt files under `backend/agents/insights/prompts/`. Persona stays in `SOUL.md`.
- G6. Add three new test files locking in the migration; keep the >=278 baseline green.
- G7. Publish a written policy (`15-extraction-vs-agent-policy.md`) defining the three LLM-call buckets so future contributors know which lane belongs where.

### Non-Goals

- NG1. **Bucket 2 — structured extraction.** `edgar_extractor`, `vendor_supply_extractor`, `pdf_parser` stay on direct `llm_client.extract()`. Chat-completions is the wrong shape for typed-JSON extraction and would pollute analyst session memory with thousands of filing chunks.
- NG2. **Bucket 3 — recursive skill internals.** `skills/peer_review_template`, `skills/methodology_explainer` stay on direct `llm_client.reason()`. They are leaves the agent calls via the MCP `run_skill` tool; routing them back through OpenClaw creates a cycle.
- NG3. **Frontend.** `ChatPanel`, the `useQA` hook, the triangulation panel — no code change. The QAEvent wire taxonomy is preserved exactly.
- NG4. **Schema migration.** Code-only refactor. `alembic upgrade head` must be a no-op.
- NG5. **New OpenClaw features.** No new MCP tools, no new sessionKey lifecycles outside the two added prefixes.

---

## User Stories

### R1. Migrate `POST /api/qa/ask` onto OpenClaw

**US-1.1.** As an analyst using the floating "Ask the Analyst" panel, I want my follow-up question to remember what I asked 30 seconds ago, so that I can iterate without restating context.
- The endpoint forwards through OpenClaw with `sessionKey = agent:main:qa:global:{stable-hash-or-X-Session-Id-or-adhoc}`.
- Two POSTs sharing the same session id share OpenClaw memory.
- The QA panel works without any frontend change.

**US-1.2.** As a backend engineer, I want the QA system prompt versioned as a markdown file alongside the synthesis and brief rules, so that prompt edits are reviewable diffs and not Python string churn.
- The prompt moves to `backend/agents/insights/prompts/qa_global_rules.md`.
- It is loaded server-side and prepended as a leading `system` message when the sessionKey starts with `qa:global:` (per architecture doc 14, P3 — server-driven sessions).
- The persona remains in `.openclaw/SOUL.md`; only the global-QA rules move.

### R2. Migrate `POST /api/agent/ask` (triangulation) onto OpenClaw

**US-2.1.** As an analyst using the Triangulation Q&A tab, I want responses produced by the same agent that powers daily synthesis, so that tool calls (e.g. `get_filings`, `run_skill`) and chart emission work uniformly across the product.
- The endpoint forwards through OpenClaw with `sessionKey = agent:main:triangulation:{stable-topic-id}`.
- The QAEvent wire taxonomy in `schemas/qa.py` is preserved byte-for-byte: `text_chunk`, `tool_call`, `tool_result`, `chart_spec`, `citation`, `error`, `done`.
- Tool-call SSE events surface end-to-end.

**US-2.2.** As a backend engineer, I want the triangulation prompt versioned in `backend/agents/insights/prompts/triangulation_rules.md`, so that prompt iteration follows the same review path as the other modes.

### R3. Delete the orphan dispatcher block and the legacy flag

**US-3.1.** As a backend engineer, I want the dead `if openclaw_enabled == 1` branch + `_legacy_chat_handler` + `_chat_system_prompt` + `_build_chat_context` removed from `routers/insights.py`, so that the next refactor doesn't crash on the deleted `agents.insights.tool_loop` import.
- Lines 922–1259 of `routers/insights.py` collapse to a single forward call through OpenClaw.
- No feature-flag branching remains.

**US-3.2.** As a backend engineer, I want `openclaw_enabled` removed from `config.py` and `.env.example`, so that Settings has no dead knobs.
- `tests/test_v2_chat_isolation.py` and `tests/test_openclaw_forwarder.py` are updated to no longer mutate the setting.
- `git grep -nE 'OPENCLAW_ENABLED|openclaw_enabled' backend/` returns zero hits outside archived docs.

### R4. Lock the migration in with tests

**US-4.1.** As QA, I want `test_qa_router.py` to assert: route exists, returns SSE, memory persists across two POSTs sharing one session id, tool-call SSE events surface. Mocks OpenClaw upstream.

**US-4.2.** As QA, I want `test_triangulation_router.py` to assert the same shape for `POST /api/agent/ask`.

**US-4.3.** As QA, I want `test_routers_insights_no_legacy_imports.py` to import `routers.insights` and assert no transitive import of `agents.insights.tool_loop` or `llm_client`. This is a compile-time guarantee the legacy lane is gone.

### R5. Publish the bucket policy and close out doc 14

**US-5.1.** As a future contributor adding a new LLM call site, I want a written policy telling me whether to route through OpenClaw or call `llm_client` directly, so that I don't relitigate the decision in PR review.
- New doc: `docs/plans/ai-insights-automation/15-extraction-vs-agent-policy.md`.
- Defines three buckets:
  1. **Chat-like / agentic** → OpenClaw (the unified lane). Examples: chat, daily synthesis, weekly brief, qa-global, triangulation.
  2. **Structured extraction (text → JSON schema)** → direct `llm_client.extract()`. Examples: `edgar_extractor`, `vendor_supply_extractor`, `pdf_parser`. Explicitly NOT routed through OpenClaw because chat-completions is the wrong I/O shape and would pollute analyst session memory.
  3. **Recursive skill internals** → direct `llm_client.reason()`. Examples: `skills/peer_review_template`, `skills/methodology_explainer`. These are leaves the agent invokes via the MCP `run_skill` tool; routing them back through OpenClaw creates a cycle.

**US-5.2.** As the architecture-doc owner, I want a "completed at" appendix on `14-unified-agent-architecture.md` listing all migrated call sites: chat, daily synthesis, weekly brief, qa-global, triangulation. So that doc 14 reflects landed reality.

---

## Acceptance Criteria

- **AC-1.** `POST /api/qa/ask` produces SSE events that pass-through OpenClaw end-to-end. The frontend "Ask the Analyst" panel works without a frontend code change. The QAEvent taxonomy in `schemas/qa.py` is unchanged.
- **AC-2.** `POST /api/agent/ask` does the same for triangulation.
- **AC-3.** `git grep -nE 'tool_loop|OPENCLAW_ENABLED|openclaw_enabled' backend/` returns 0 hits in non-archive locations (test fixtures excluded).
- **AC-4.** Backend pytest count >= 278 + 3 new test files (281+); 0 regressions.
- **AC-5.** `alembic upgrade head` is clean (no migration; this is a code-only refactor).
- **AC-6.** Two new prompt files exist under `backend/agents/insights/prompts/` (`qa_global_rules.md`, `triangulation_rules.md`) and are loaded server-side per sessionKey prefix, consistent with architecture doc 14 §P3.
- **AC-7.** New policy doc `15-extraction-vs-agent-policy.md` is committed and linked from `14-unified-agent-architecture.md`.
- **AC-8.** `routers/insights.py` no longer contains `_legacy_chat_handler`, `_chat_system_prompt`, `_build_chat_context`, or any feature-flag branch on `openclaw_enabled`.

---

## Out of Scope

- Migrating Bucket 2 (`edgar_extractor`, `vendor_supply_extractor`, `pdf_parser`). They stay on `llm_client.extract()`.
- Migrating Bucket 3 (`skills/peer_review_template`, `skills/methodology_explainer`). They stay on `llm_client.reason()`.
- Frontend code changes. `ChatPanel`, `useQA`, the triangulation panel are untouched. The wire taxonomy is preserved.
- Database migrations. Code-only.
- New MCP tools, new sessionKey lifecycles beyond `qa:global:*` and `triangulation:*`, or any change to OpenClaw gateway config in `.openclaw/openclaw.json`.
- Performance tuning of the new lanes (cap tuning, prompt-token reduction). Tracked separately.

---

## Open Questions

- **OQ-1. QA sessionKey stability.** The spec proposes `agent:main:qa:global:{stable-hash-or-X-Session-Id-or-adhoc}`. Confirm the resolution order: (a) `X-Session-Id` request header if present, else (b) hash of `(user_id, route)` if user is authenticated, else (c) per-request adhoc UUID (effectively memoryless). Backend to pick one and document inline.
- **OQ-2. Triangulation topic-id source.** "Stable topic id" needs a concrete derivation. Likely the triangulation entity/topic primary key already on the request body — backend to confirm and pin in the router.
- **OQ-3. Prompt-loader caching.** The two new prompt files load on every request today via the synthesis/brief pattern. Confirm the existing prompt loader memoizes file reads in dev/prod (it does for `chat_rules.md`); if not, this PRD does not introduce regression.
- **OQ-4. SOUL.md scope check.** Architecture doc 14 §P3 says SOUL.md is identity + voice + safety + tool palette only. Verify nothing QA-specific or triangulation-specific has crept into SOUL.md since Phase 5; if it has, move it into the new per-mode rules files as part of this PR.
- **OQ-5. Test fixture exclusion for AC-3.** The grep guard excludes `tests/fixtures/`. Confirm no production-loaded fixture references the dead flag — if any do, they must be updated, not excluded.

---

## Risks

- **R-A. Wire-taxonomy drift.** The QAEvent taxonomy in `schemas/qa.py` is consumed by the frontend. Any drift breaks "Ask the Analyst" silently. Mitigation: the new `test_qa_router.py` asserts exact event-type set; CI fails on drift.
- **R-B. Session-memory bleed.** Two analysts hitting `qa:global` from the same browser session could share a sessionKey and see each other's history if the resolver picks the wrong identity dimension. Mitigation: OQ-1 must be resolved before merge; document the answer in the router docstring.
- **R-C. Orphan deletion ripple.** Deleting `_build_chat_context` may surface other call sites that quietly imported it. Mitigation: `test_routers_insights_no_legacy_imports.py` plus a one-shot `git grep` sweep before merge.
- **R-D. Prompt regression.** Moving the QA system prompt from Python string to markdown file risks whitespace/escaping drift that subtly changes model behavior. Mitigation: byte-diff the rendered prompt before/after; reviewer signs off on the diff.

---

## Cross-References

- Design lineage: [`14-unified-agent-architecture.md`](./14-unified-agent-architecture.md) — sessionKey scheme (§P1), server-driven prompts (§P3), client-side caps (§P4), SSE wire taxonomy (§P5).
- Phase-1 chat migration: [`13-mcp-migration-architecture.md`](./13-mcp-migration-architecture.md).
- Implementation hook: `backend/openclaw/forwarder.py::_drive_openclaw_stream` (extracted in Phase 2; both new endpoints reuse it unchanged).
- Policy successor (created by this PRD): `15-extraction-vs-agent-policy.md`.
