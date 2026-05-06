# PRD: Migrate AI Insights Chat Agent to OpenClaw

**Status:** Active. Supersedes ADR-010 by user direction (2026-05-05). The skip recommendation is acknowledged; this PRD is the user's ratified counter-decision and the implementation contract for delivering it.
**Owner:** PM (strategic-insights-tool)
**Primary stakeholder:** the user
**Date:** 2026-05-05
**Predecessors:**
- `01-prd.md` (PRD: AI Insights Automation & Real-Data Synthesis)
- `03-architecture.md` (current SSE + ToolLoopDriver architecture, 7 chat tools)
- `10-openclaw-integration-evaluation.md` (ADR-010, status SKIP — superseded here)
- `08-v1.1-agentic-plan.md` (V1.1 agentic-driver plan — unaffected by this migration)

---

## 1. Overview

The AI Insights tab today exposes a per-insight chat dock backed by:

- `_chat_system_prompt(ctx)` — persona and style block + injected
  `INSIGHT CONTEXT (JSON)` per turn (`backend/routers/insights.py`).
- `_build_chat_context(db, insight_id)` — domain-model loader joining
  `AIInsight + AgentChart + AgentCitation`.
- `ToolLoopDriver` (`backend/agents/insights/tool_loop.py`) — OpenAI-style
  tool-loop driver with parallel dispatch (caps: turns=12, parallel=4,
  wall=120s).
- 7 chat tools registered in `backend/agents/insights/tools/registry.py`:
  `query_database`, `call_api`, `get_chart_data`, `web_search`,
  `run_skill`, `emit_chart`, `emit_citation`.
- SSE event taxonomy (`sse_events.py`, 18 event types).
- Postgres-resident persistence: `agent_message`, `agent_tool_call`,
  `agent_chart`, `agent_citation`, `insight_thread`.

This PRD scopes the migration of **the chat path only** to **OpenClaw**
(MIT, self-hosted gateway; see ADR-010 §2 for the project digest).
ADR-010 recommended SKIP. The user has overridden that recommendation
on 2026-05-05. This PRD is the implementation contract for delivering
the override; the trade-offs ADR-010 documented (especially R-OC-1
foundation governance, JSONL-vs-Postgres trace fidelity, and the
OpenAI-compat shim against OCI gpt-5.4) are accepted as known costs.

The synthesis pipeline (daily cron, FactPack, mega-call, dedup) is
**out of scope and untouched** — see `01-prd.md` and `03-architecture.md`
for that path. OpenClaw is exclusively the chat-turn runtime.

---

## 2. Goals & Non-Goals

### 2.1 Goals

- **G1.** Replace `ToolLoopDriver` and the in-process tool-dispatch
  loop on the chat path with **OpenClaw** as the agent runtime,
  preserving today's user-visible behavior to within an SSE-event-
  taxonomy diff of zero.
- **G2.** Keep the synthesis pipeline (daily cron, hypothesizer,
  FactPack, mega LLM call, pgvector dedup) **byte-for-byte unchanged**.
  OpenClaw never enters the cron path.
- **G3.** Single-user analyst tool. One the user, one tab, one OpenClaw
  instance, scoped per-insight via a `sessionKey` (R6).
- **G4.** Provide a feature flag `OPENCLAW_ENABLED` (default 0) so the
  legacy `ToolLoopDriver` path is the rollback target and can be
  re-enabled without redeploy (R9).
- **G5.** Preserve the Postgres `agent_message` / `agent_tool_call` /
  `agent_chart` audit trail via a write-through dual-store pattern: the
  OpenClaw JSONL transcript is the chat runtime's source of truth,
  while a synchronous mirror writes the same turn into our Postgres
  tables for replay, exports, and analyst tooling (R5).
- **G6.** Continue to ground every chat turn in the per-insight context
  (`_build_chat_context`) and the senior-datacenter-analyst persona
  defined in `SOUL.md` (R4).

### 2.2 Non-Goals

- **NG1.** Multi-channel reach (WhatsApp, Slack, iMessage, Telegram,
  Discord, Signal, etc.). OpenClaw ships 23+ channel adapters; we use
  WebChat + REST only.
- **NG2.** Mobile layout. Out of scope for V1 of the analyst tool and
  out of scope here.
- **NG3.** Replacing the synthesis pipeline. The 09:00 UTC cron, the
  FactPack, and the mega-call remain ToolLoopDriver-free and OpenClaw-
  free. OpenClaw is chat-only.
- **NG4.** Cross-session memory beyond what OpenClaw natively provides.
  We accept whatever its memory engine offers per-`sessionKey` and we
  do **not** build any custom Postgres-backed cross-session-memory
  layer in V1 of this migration.
- **NG5.** ClawHub-style skill marketplace, self-modifying skills, or
  any operator surface that lets the agent expand its own tool set.
  V1.1 of the chat plan (`08-v1.1-agentic-plan.md`) deliberately
  narrows the tool surface; this migration must not loosen it.
- **NG6.** Slash-command UI for the user (`/compact`, `/reset`, etc.).
  OpenClaw exposes them server-side; we do not surface them in the
  React dock.
- **NG7.** Multi-tenant or per-user agent provisioning. One agent,
  scoped by `sessionKey` per insight.

---

## 3. Background & Problem Statement

### 3.1 Why migrate now

ADR-010 §10 left the door open: "Revisit only on a material change
of product scope". The user has flagged a material change in
direction (2026-05-05) — they want the chat runtime on a public,
MIT-licensed agent gateway instead of a hand-rolled tool loop. The
benefits the user weighs (audit-log JSONL parity, future optionality,
`/compact`-style transcript management as a free side-effect) are
accepted; the costs ADR-010 enumerated are accepted as known.

This PRD does not re-litigate.

### 3.2 What stays load-bearing

The features ADR-010 §3.5 listed as "WE have that OpenClaw might break"
are still load-bearing for the user's workflow and must survive the
migration:

1. Per-insight scoped system prompt (8 KB JSON context blob).
2. Pre-loaded citations in `agent_citation` injected into the system
   prompt before the first turn.
3. `query_database` gated by `sql_gate.validate_sql` running **inside
   our process** on our Postgres.
4. Charts as first-class agent outputs (`agent_chart` rows, joined to
   `InsightCard` on `insight_id`).
5. Reasoning trace in Postgres (`agent_message` + `agent_tool_call`).
6. SSE event taxonomy (`sse_events.py`) — the React dock's contract.

Per R5 we keep all six via the dual-store pattern. The webhook
adapter pattern from ADR-010 §4.5 (Hybrid mode b) is the chosen
integration shape.

---

## 4. Personas & User Stories

All stories are scoped to the user (analyst, single user). User-facing
behavior must be indistinguishable from today's tool-loop path.

### 4.1 Default chat experience is unchanged from the user's POV

> **As the user, opening an insight, I get a chat dock that talks to
> OpenClaw under the hood, indistinguishable from before.**

- Acceptance: same chat dock UI; same SSE event names on the wire;
  same tool-call chips; same citation pills; same chart inline render.
- The transition is invisible. No new banners, no new badges, no
  "Powered by OpenClaw" affordance.

### 4.2 Database queries continue to work, end-to-end

> **As the user, asking "what other Crusoe sites?", the agent fires
> `query_database` via OpenClaw and returns rows.**

- Acceptance: the model's tool call leaves OpenClaw as a webhook to
  our FastAPI; `sql_gate.validate_sql` enforces the SELECT-only AST
  gate; rows come back; the dock renders the tool-call chip and the
  agent's textual answer; an `agent_tool_call` row lands in Postgres.

### 4.3 Multi-turn memory within an insight session

> **As the user, saying "yes" after the agent asked a clarifier,
> OpenClaw remembers the prior turn (memory across turns within an
> insight session).**

- Acceptance: a chat session keyed by `sessionKey =
  "insight:<insight_id>"` (R6) retains prior turn context inside
  OpenClaw. the user saying "yes" or "show me more" resolves correctly
  against the prior assistant turn.
- Out of scope: cross-session memory across distinct `insight_id`
  values. NG4 stands.

### 4.4 Persona is the senior datacenter analyst

> **As the user, asking who-are-you, the agent responds in the senior
> datacenter analyst voice from `SOUL.md`.**

- Acceptance: `SOUL.md` checked into the OpenClaw agent workspace
  contains the same persona text we use today in `_chat_system_prompt`.
- Per-turn, the dynamic context blob from `_build_chat_context`
  arrives as a per-request override (R3) so the persona is not
  duplicated and the per-insight grounding is preserved.

### 4.5 Rollback is a flag flip

> **As the user, when `OPENCLAW_ENABLED=0`, my chat experience is bit-
> for-bit the old `ToolLoopDriver` path (rollback).**

- Acceptance: with the env var off, the chat router calls
  `ToolLoopDriver` directly as it does today. No OpenClaw process is
  contacted. SSE event taxonomy is identical. Postgres writes are
  identical. The flag flip is the only operator-facing rollback
  ritual.

### 4.6 Operator stories (informational)

- **As an operator, I want the OpenClaw process to run as a
  co-located sidecar reachable on loopback so tool-call latency does
  not blow AC1.**
- **As an operator, I want a daily JSONL backup job for the OpenClaw
  workspace so an OpenClaw EOL incident is recoverable.**
- **As an operator, I want every Postgres `agent_message` row to
  carry the OpenClaw `sessionKey` and turn id so I can correlate the
  two stores during an incident.**

---

## 5. Functional Requirements

The user has supplied R1-R9 as ratified scope. The following F-items
map 1:1.

### F1. OpenClaw co-located gateway (R1)

A single OpenClaw gateway process runs as a sidecar to the FastAPI
app, reachable on loopback (no TLS terminator between them) per
ADR-010 §8 R-OC-4 mitigation. Auth uses Bearer token via
`gateway.token`. The model provider is OCI `gpt-5.4` via the
OpenAI-compatible adapter (R7). No multi-channel adapters are
enabled — WebChat + REST only.

### F2. Feature-flagged dispatch (R9)

The chat POST handler in `backend/routers/insights.py` reads
`OPENCLAW_ENABLED`. When 1, the handler delegates the turn to the
OpenClaw client adapter; when 0, it falls back to the existing
`ToolLoopDriver` code path. The two paths are mutually exclusive per
turn. There is no shadow / dual-fire mode.

### F3. Per-insight session scoping via `sessionKey` (R6)

Each insight maps to a stable OpenClaw session keyed
`sessionKey = "insight:<insight_id>"`. One shared OpenClaw agent
serves all insights; per-request scoping is achieved by (a) the
per-session `sessionKey`, (b) a per-request system-prompt override
carrying the dynamic insight-context JSON, and (c) the per-session
tool allowlist already implied by our 7 chat tools. No per-insight
agent provisioning is performed (the per-agent option from ADR-010
§4.3 is rejected).

### F4. Persona via `SOUL.md`; per-turn grounding via override (R3, R4)

The persona text matching the existing `_chat_system_prompt` static
block is committed to the OpenClaw agent's `SOUL.md`. The dynamic
8 KB JSON context produced by `_build_chat_context(db, insight_id)`
is injected as a per-request system-prompt override on every turn.
`_build_chat_context` itself is unchanged — it is still a 65-line
join across `AIInsight + AgentChart + AgentCitation` and remains
in our process.

### F5. Tool routing via webhooks (R2)

The 7 chat tools (`query_database`, `call_api`, `get_chart_data`,
`web_search`, `run_skill`, `emit_chart`, `emit_citation`) are
exposed to OpenClaw as webhooks served by FastAPI under
`/oc-tool/<tool_name>`. OpenClaw invokes tools via webhook back into
our process; the tool **bodies** are unchanged from today, including
the in-process `sql_gate.validate_sql` gate on `query_database`.
Webhook auth is a shared secret carried in a header. Loopback only.

### F6. Write-through dual-store persistence (R5)

For every chat turn:

- The user message, the LLM response, every tool call, and every
  tool result are written to OpenClaw's JSONL transcript by OpenClaw
  itself.
- Synchronously, our adapter writes the same turn into Postgres:
  `agent_message` (role, content, `tool_calls` JSONB, `seq`,
  `thread_id`, `session_id`), `agent_tool_call` rows where applicable,
  `agent_chart` for any `emit_chart` invocation, `agent_citation` for
  any `emit_citation` invocation. The `sessionKey` and the OpenClaw
  turn id are stored alongside so the two stores are joinable.
- On webhook handler error, the user-facing turn fails and the
  partial Postgres write is rolled back; OpenClaw's JSONL may show
  the in-progress turn. Reconciliation policy is "Postgres wins" —
  see Open Question OQ3.

### F7. SSE event-taxonomy preservation (R8)

The OpenClaw client adapter translates OpenClaw's native SSE/WS
event stream into our existing 18-event taxonomy
(`backend/agents/insights/specs/sse_events.py`). The browser dock
contract does not change. Tool-call chips, chart inline renders, and
citation pills continue to render from the same event shapes.

### F8. Citations pre-loaded before first turn (R3)

`emit_citation` runs during synthesis (cron path) and writes
`agent_citation` rows keyed by `insight_id`. When OpenClaw opens a
new chat session for that insight, the per-request system-prompt
override (F4) bakes those citations into the prompt so the agent
starts grounded. OpenClaw's native memory engines are not used for
citation pre-load — that is done in our process.

### F9. Backups and EOL safety (R5 secondary)

A daily APScheduler job copies the OpenClaw workspace
(`~/.openclaw/agents/<id>/sessions/*.jsonl` plus the SQLite session-
store) to object storage. Postgres remains the system of record; the
JSONL backup is an extra durability layer aligned with ADR-010 §9.2.

---

## 6. Non-Functional Requirements

### NFR1. Latency

- p50 chat-turn latency target: ≤ 1.5x today's baseline.
- p95 chat-turn latency target: ≤ 2x today's baseline (≤ 90s).
- Acknowledged that ADR-010 §3.6 AC1/AC2 said "ADR-010 expected
  20-40% regression". This PRD ratifies the regression budget.

### NFR2. Availability

- OpenClaw down: chat is 100% down on the OpenClaw lane. Insight
  render unaffected. Operator flips `OPENCLAW_ENABLED=0` to restore
  chat via the legacy lane (R9).
- Synthesis cron unaffected by OpenClaw availability (NG3).

### NFR3. Observability

- Each turn emits structured logs keyed by `(insight_id, session_key,
  turn_id, agent_message.id)`.
- An OpenClaw webhook latency histogram is emitted per tool.
- An `OPENCLAW_ENABLED` flag value is logged at chat-handler entry.

### NFR4. Backward compatibility

- The SSE event taxonomy on the wire is unchanged.
- Postgres schemas (`agent_message`, `agent_tool_call`, `agent_chart`,
  `agent_citation`, `insight_thread`) are unchanged or extended only
  additively (new nullable columns for `session_key` and OpenClaw
  turn id).
- The legacy `ToolLoopDriver` path is preserved indefinitely as the
  rollback target.

### NFR5. Security

- `sql_gate.validate_sql` runs inside our process (F5). OpenClaw
  never sees raw SQL.
- Webhook endpoints require a shared-secret header; loopback bind
  only; no public exposure.
- `POST /tools/invoke` on OpenClaw is firewalled off. ClawHub
  marketplace is disabled (NG5).

---

## 7. Acceptance Criteria

Each row is testable. Mirrors the user's ACCEPTANCE block; tightened
where needed for testability.

### AC1. Chat turn round-trips through OpenClaw when flag is on

- With `OPENCLAW_ENABLED=1`, posting a chat turn results in a
  request landing on the OpenClaw gateway (verified by gateway log).
- The reply renders in the dock.
- `agent_message` rows for the turn exist in Postgres with
  `session_key="insight:<insight_id>"`.

### AC2. Chat turn round-trips through ToolLoopDriver when flag is off

- With `OPENCLAW_ENABLED=0`, no request reaches the OpenClaw
  gateway.
- The dock behaves identically to today.
- The Postgres rows for the turn are written via the legacy code path.

### AC3. `query_database` is gated by `sql_gate.validate_sql` in both lanes

- A prompt that would induce a non-SELECT query (e.g., "delete the
  Crusoe rows") is rejected with the same error message in both
  flag positions.
- The rejection event surfaces in the dock as today.

### AC4. Persona answers come from `SOUL.md`

- "who are you?" returns the senior datacenter analyst persona text.
- Removing `SOUL.md` from the OpenClaw agent workspace and re-running
  the prompt returns a generic answer (negative test).

### AC5. Per-insight scoping holds across turns

- Two distinct insights opened in two browser tabs do not leak
  context between sessions.
- A "yes" reply to the assistant's clarifier in tab A is resolved
  against tab A's prior turn, not tab B's.

### AC6. Pre-loaded citations are available on the first turn

- A new chat session on an insight that has 5 citations resolves a
  prompt like "list the citations" by enumerating them on turn 1
  with no additional tool call needed.

### AC7. Charts render as first-class artifacts

- A prompt that triggers `emit_chart` produces an `agent_chart` row
  in Postgres and an inline chart render in the dock.
- The chart's `row_hash` and `spec` JSONB are populated as today.

### AC8. Trace replay fidelity from Postgres alone

- An on-call engineer can fully reconstruct an OpenClaw-lane chat
  turn from `agent_message + agent_tool_call + agent_chart` rows
  alone, without reading OpenClaw JSONL.
- (R-OC-1 mitigation: this is the primary durability bet.)

### AC9. Rollback in under 60 seconds

- Starting from a steady-state OpenClaw lane, the operator sets
  `OPENCLAW_ENABLED=0` (config reload, no redeploy) and within 60
  seconds the next chat turn flows through `ToolLoopDriver`.

### AC10. Synthesis pipeline unaffected

- A 09:00 UTC scheduled run completes successfully with both
  `OPENCLAW_ENABLED=0` and `OPENCLAW_ENABLED=1`.
- The `ai_session.cron_run_date` row, FactPack, mega-call, dedup,
  and emitted insights are byte-for-byte identical regardless of
  flag value.

### AC11. JSONL backup completes nightly

- The daily backup job in F9 fires once per UTC day, completes, and
  produces a non-empty archive in object storage.

---

## 8. Out of Scope (Explicit)

Mirrors the user's OUT OF SCOPE block.

- **Multi-channel.** WhatsApp, Slack, iMessage, Telegram, Discord,
  Signal, Teams, Matrix, Mattermost, Nostr, Twitch, Zalo, IRC,
  Feishu, LINE, BlueBubbles, Synology Chat, Tlon, Nextcloud Talk,
  WeChat, QQ. Disabled in OpenClaw config.
- **Mobile layout.** Same as V1 of the analyst tool.
- **Replacing the synthesis pipeline.** The cron path stays on the
  hand-rolled deterministic FactPack + mega-call architecture
  documented in `01-prd.md` and `03-architecture.md`. OpenClaw is
  chat-only.
- **Cross-session memory beyond OpenClaw native.** No custom pgvector
  memory layer. We accept whatever OpenClaw's per-`sessionKey` memory
  engine provides.
- **ClawHub marketplace and self-modifying skills.** Tool surface is
  fixed at the 7 chat tools. The V1.1 plan continues to narrow it.
- **Slash-command UI in the dock.** Server-side slash commands are
  inert from the user's POV.
- **Per-insight OpenClaw agent provisioning.** R6 fixes one shared
  agent + `sessionKey` scoping.
- **Removal of `_build_chat_context`.** It is the domain-model loader;
  it stays.
- **Removal of the legacy `ToolLoopDriver` path.** It is the rollback
  target. Removal is gated on a future decision after a stable run on
  OpenClaw.

---

## 9. Risks

PRD risks R1-R5 from `01-prd.md` are unaffected (they cover synthesis,
not chat). The migration introduces these chat-path risks; mitigations
are in scope for the implementation plan.

### R-OC-1. Foundation governance immaturity

ADR-010 §2.9 R-OC-1 still applies. OpenClaw's foundation is <3
months old as of 2026-05-05; EOL risk is non-trivial.
**Mitigation:** Postgres dual-store (F6) makes us recoverable in
~1 dev-week if OpenClaw EOLs (ADR-010 §4.7 mode-b row). The legacy
`ToolLoopDriver` lane is preserved indefinitely as the rollback
target (F2).

### R-OC-2. Llama Stack / OpenAI-compat shim mismatch against OCI gpt-5.4

OpenClaw has no first-party OCI provider. Pointing at OCI requires
the OpenAI-compatible adapter or a custom provider shim. Schema
drift on `gpt-5.4` (tool-calling format, response_format, streaming
chunks) can break chat without warning.
**Mitigation:** pin shim version; add a CI smoke test that issues a
real tool-call against the gateway and asserts our event-taxonomy
translation succeeds; alerting on shim parse-error rate >1%.

### R-OC-3. Trace-fidelity drift between JSONL and Postgres

OpenClaw is the chat-runtime source of truth (its JSONL is what the
LLM sees on the next turn). Our Postgres mirror is the audit and
analyst-tooling source of truth. If the two drift, AC8 fails
silently.
**Mitigation:** synchronous write-through (F6); a nightly
reconciliation job that compares `(session_key, turn_count)` between
OpenClaw and Postgres and alerts on mismatch.

### R-OC-4. Webhook latency adds a hop per tool call

Per ADR-010 §4.8 a tool call now traverses
`OpenClaw -> HTTP -> FastAPI -> Postgres`. Each tool call is one
extra round-trip and two extra serializations vs the in-process
dispatch.
**Mitigation:** loopback co-location, no TLS terminator between the
two processes, per-tool latency histogram (NFR3), AC1 latency budget
explicitly relaxed.

### R-OC-5. SOUL.md / per-request override interaction

The user-visible persona must be `SOUL.md`. The per-turn dynamic
context (8 KB JSON) must arrive as a per-request override without
contaminating the user-visible transcript (ADR-010 §4.3 was explicit
on this misfit).
**Mitigation:** if OpenClaw's per-request system-prompt override is
not supported in the version we deploy, fall back to a `load_context`
tool call invoked at session start (ADR-010 §4.3 option 3). This
adds a turn-0 webhook hop but is functional. Decide at integration
time.

### R-OC-6. SSE re-attach during OpenClaw outage

A mid-stream OpenClaw crash leaves the dock with a half-rendered
turn. Today's per-process replay buffer cannot rescue it because
the source-of-truth event stream lives in OpenClaw.
**Mitigation:** the dock retries the in-flight turn from the user
side on disconnect; in-flight tool-result-but-no-final-text turns
are surfaced as a generic `ErrorEvent(code="oc_disconnect")`. Same
behavior pattern as today for any LLM provider hiccup.

### R-OC-7. `OPENCLAW_ENABLED` flag drift between processes

If multiple FastAPI workers read the env var at boot and one is
out of date, traffic splits between lanes inconsistently.
**Mitigation:** rolling restart on flag change documented as part
of the rollback runbook; a startup log line confirms the value;
optional config-reload signal in V1.1.

---

## 10. Open Questions

### OQ1. Agent provisioning model — one shared vs one-per-insight

**User decision (R6):** one shared OpenClaw agent + `sessionKey`
scoping per insight. Documented here for the trade-off.

- **Chosen (one shared + sessionKey):** ~7 sessions/day, no agent
  lifecycle pipeline, persona is single source of truth in `SOUL.md`,
  per-turn grounding via per-request override. Risk: if OpenClaw's
  override is not supported, fall back to `load_context` tool (R-OC-5).
- **Rejected (one agent per insight):** ADR-010 §4.3 estimate of
  ~2,500 agents/year, no public agent-lifecycle API, persona drift
  risk across many `SOUL.md` files. Operationally infeasible.
- **Rejected (one agent + transcript-pollution context):** ADR-010
  §4.3 option 2; pollutes user-visible transcript and complicates
  audit.

Decision is closed for V1; revisit only if R-OC-5 falls back to the
`load_context` tool and that path costs >300ms per session-open.

### OQ2. `_build_chat_context` truncation cap

Today's 8000-char cap on the JSON context blob is a hard token-
budget protection. OpenClaw's per-request override may have its own
size limits documented or undocumented.
**Decision needed:** confirm cap is preserved as-is, or tighten if
OpenClaw's override field caps below 8000 chars.

### OQ3. Reconciliation policy on dual-store divergence

If a webhook handler succeeds (Postgres write) but the OpenClaw
turn-completion ack is lost, the JSONL transcript and Postgres can
diverge.
**Proposal:** Postgres wins. The next user turn re-reads the
prior assistant turn from Postgres and replays it as a synthetic
OpenClaw user message before the new prompt. This costs one extra
LLM token block per recovery.
**Decision needed:** confirm "Postgres wins" or pick an alternative
(e.g., OpenClaw wins; eject the session and start fresh).

### OQ4. Whether to keep `ToolLoopDriver` indefinitely or sunset it

R9 mandates `OPENCLAW_ENABLED=0` is bit-for-bit the old path. After
N weeks of stable OpenClaw operation we may want to remove the
legacy lane to reduce surface area.
**Proposal:** keep indefinitely until R-OC-1 governance question
resolves (12-month maturity bar). Re-evaluate in V2 of this PRD.
**Decision needed:** confirm "keep indefinitely" or commit to a
sunset date.

### OQ5. OpenClaw deployment topology

Sidecar in the same container, sidecar in the same pod, separate
co-located VM, etc. Latency budget (NFR1) requires loopback;
operability prefers separation.
**Proposal:** start as a sidecar process in the same VM, supervised
by systemd, bound on `127.0.0.1:<port>`. Reassess in production.
**Decision needed:** architect to pick at integration time.

### OQ6. Webhook auth model

Shared secret in a header is simplest. mTLS is more secure but
operationally heavier on a single-VM deployment.
**Proposal:** shared secret rotated quarterly; loopback bind
guarantees no over-the-wire exposure.
**Decision needed:** confirm shared secret or pick mTLS.

### OQ7. JSONL backup retention

F9 is daily; ADR-010 §9.2 suggested object-storage parking. Length
of retention drives storage cost.
**Proposal:** 90 days, mirroring `01-prd.md` OQ3 retention.
**Decision needed:** confirm or pick alternative.

---

## 11. Success Metrics

- **Primary:** the user opens an insight chat dock on N=10 consecutive
  days with `OPENCLAW_ENABLED=1` and reports parity with the legacy
  experience (no degradation in answer quality, citation grounding,
  or chart render success).
- **Reliability:** ≥ 95% of OpenClaw-lane chat turns succeed end-
  to-end without falling back. Tracked via webhook-handler logs.
- **Latency:** p95 chat-turn latency stays inside NFR1 over a
  rolling 7-day window.
- **Trace fidelity:** Postgres-only replay reconstructs 100% of
  OpenClaw-lane turns over a sampled 50-turn audit (AC8).
- **Rollback:** at least one drilled `OPENCLAW_ENABLED=0` flip
  completes inside 60 seconds (AC9).
- **Synthesis isolation:** 0 cron runs degraded by OpenClaw
  availability (AC10).

---

## 12. Rollout Plan (informational)

The architect will turn this into a sequenced build plan. Five
phases, each independently shippable behind `OPENCLAW_ENABLED=0`.

1. **Phase A — Sidecar + shim.** Stand up the OpenClaw sidecar on
   loopback. Wire the OpenAI-compat shim against OCI `gpt-5.4`. CI
   smoke test for tool-call schema (R-OC-2).
2. **Phase B — `SOUL.md` + per-request override.** Commit the persona;
   verify per-request override path (R-OC-5). Decide F4 fallback
   `load_context` tool if needed.
3. **Phase C — Webhook adapters for the 7 tools.** One handler per
   tool under `/oc-tool/<name>`. Reuse the existing tool bodies; do
   not change `sql_gate.validate_sql`.
4. **Phase D — Dual-store write-through + SSE translator.** Adapter
   serializes OpenClaw events into our 18-event taxonomy. Postgres
   mirror writes synchronously per turn.
5. **Phase E — Flag flip + JSONL backup + reconciliation.** Default
   `OPENCLAW_ENABLED=0`; flip to 1 in staging; observe; flip in prod.
   Daily backup job lands. Reconciliation alarm wired.

Each phase has a corresponding acceptance subset:

- Phase A: AC1 wire path verified.
- Phase B: AC4 persona + AC6 citations.
- Phase C: AC3 SQL gate + AC7 charts.
- Phase D: AC8 Postgres replay.
- Phase E: AC2 / AC9 / AC10 / AC11.

---

## 13. References

- `01-prd.md` — synthesis PRD, untouched here.
- `03-architecture.md` — current chat architecture and 7 chat tools.
- `08-v1.1-agentic-plan.md` — V1.1 chat plan that narrows the tool
  surface; this migration must not loosen it.
- `10-openclaw-integration-evaluation.md` — ADR-010, status SKIP.
  This PRD supersedes that recommendation by user direction.
- OpenClaw docs: `docs.openclaw.ai` (per ADR-010 §2.1, the
  authoritative surface).
- Backend touch-points (informational, names current at HEAD May 2026):
  - `backend/routers/insights.py` — chat handler dispatch.
  - `backend/agents/insights/tool_loop.py` — legacy lane.
  - `backend/agents/insights/tools/registry.py` — 7 chat tools.
  - `backend/agents/insights/specs/sse_events.py` — 18-event taxonomy.
  - `backend/agents/insights/db/models.py` — `agent_message`,
    `agent_tool_call`, `agent_chart`, `agent_citation`,
    `insight_thread`.
- Frontend touch-points (informational):
  - `frontend/src/components/tabs/ai-insights/InsightChatDock.tsx` —
    SSE consumer; contract unchanged.

---

*End of PRD.*
