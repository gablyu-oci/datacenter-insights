# ADR-010 — OpenClaw Integration Evaluation for the AI Insights Chat Layer

**Status:** Decided — **SKIP**
**Date:** 2026-05-05
**Authors:** orchestrator (synthesis), researcher, pm, architect
**Stakeholder:** Karan (analyst, primary user)
**Predecessors:**
- `00-index.md` (V1 plan index)
- `03-architecture.md` (current SSE + ToolLoopDriver architecture)
- `08-v1.1-agentic-plan.md` (the alternative path we already have planned)
**Source artifacts (raw, unsynthesized lens outputs):**
- `/tmp/openclaw_research.md` (412 lines — researcher dossier)
- `/tmp/openclaw_pm.md` (286 lines — PM evaluation)
- `/tmp/openclaw_architect.md` (317 lines — architect component map)

---

## §1. Executive summary

We considered adopting **OpenClaw** (https://openclaw.ai/, MIT-licensed,
~369k stars, self-hosted personal-AI gateway) as the chat / agent layer
behind the AI Insights tab's per-insight chat dock — replacing or
augmenting the current `_chat_system_prompt` + `_build_chat_context` +
`ToolLoopDriver` + SSE event-stream stack documented in §03 and
extended in §08. After a three-lens evaluation (research, product,
architecture) the recommendation is unambiguous: **skip — do not
integrate OpenClaw into the AI Insights tab**, and continue with the
V1.1 agentic-driver plan in `08-v1.1-agentic-plan.md`. OpenClaw is a
high-quality, popular project, but its design centre — **one persistent
personal assistant per user, fanned across messenger channels
(WhatsApp / Slack / iMessage / Telegram)** — is the wrong shape for
our problem (multi-thousand per-insight ephemeral scopes, host-
controlled system prompt, host-resident DB-bound tools, charts and
citations as first-class agent outputs, Postgres-greppable audit
trail). The user's claim that OpenClaw would let us delete "manual
scripts to wrap those contexts and prompts" is **false in the strong
reading**: `_build_chat_context` is a domain-model loader joining three
of our own tables and survives any integration; `_chat_system_prompt`
can only be deleted by either provisioning ~2,500 OpenClaw agents
per year (one per insight) or polluting the user-visible transcript
with our context blob — both worse than what we have. The same
underlying LLM (gpt-5.4) is used either way, so no reasoning-quality
lift is mechanistically plausible. Hybrid options (chat-only,
memory-only) yield near-zero net LOC change while adding an out-of-
process service to operate. We should clone the two ideas worth
borrowing (`/compact`-style transcript summarization; JSONL-parallel
audit-log export) into our own stack at a fraction of the cost, and
ship V1.1's agentic driver to close the actual analyst-named gap.

---

## §2. What OpenClaw actually is (researcher)

> Source: `/tmp/openclaw_research.md`. Full quotes and URL citations
> are preserved there; this section is the synthesised digest.

### 2.1 Project identity

- **License:** MIT, GitHub `openclaw/openclaw`.
- **Canonical surfaces:** `openclaw.ai` (marketing) and
  `docs.openclaw.ai` (technical). `openclaw-ai.com/...` is a localised
  mirror; assorted `openclaws.io / getopenclaw.ai / open-claw.bot /
  remoteopenclaw.com` are third-party SEO blogs and **not**
  authoritative.
- **Activity:** Very alive. 369k stars / 47.7k forks / 90+
  contributors as of May 2026. Stable / beta / dev release channels.
- **Origin:** Created by Peter Steinberger (ex-PSPDFKit) in late 2025
  as "Clawdbot / WhatsApp Relay", rebranded "OpenClaw" Jan 2026.
  Steinberger joined OpenAI on 2026-02-14 and announced an
  **independent open-source foundation** would steward the project
  going forward. Foundation legal entity / governance maturity:
  could not determine — docs are silent.

### 2.2 Product shape

OpenClaw is **(b) a self-hostable Gateway product + (c) an SDK /
plugin library**. There is no first-party hosted SaaS — third
parties (Blink Claw, etc.) offer managed hosting on top, but they
are not the project.

Core deployable unit: a self-hosted Gateway process (Node 22 LTS or
24, pnpm workspace, Docker for sandboxing). Users install via
`npm install -g openclaw@latest` and `openclaw onboard
--install-daemon`.

### 2.3 Session, /compact, slash commands, channels

- **Session:** A `sessionKey` identifies a unique chat location
  (`agent:<id>:<channel>:<peer>`). Persisted as **JSONL on disk**
  under `~/.openclaw/agents/<agentId>/sessions/<sessionId>.jsonl`,
  plus a SQLite session-store (WAL).
- **`/compact`:** Operates at the session/transcript level. Pairs
  tool calls with results, can summarise older messages, prune
  transient tool outputs, and "promote important facts into long-
  term memory before clearing them from active context." Does **not**
  rewrite the on-disk JSONL — only the in-memory window sent to the
  LLM.
- **Slash commands:** Product-defined fixed set
  (`/new, /reset, /compact, /status, /context list, /context detail,
  /stop, /send on/off/inherit`). No documented mechanism for users
  to define new ones.
- **Channels:** 23+ adapters — WhatsApp, Telegram, Slack, Discord,
  Signal, iMessage, Microsoft Teams, Google Chat, Matrix,
  Mattermost, Nostr, Twitch, Zalo, IRC, Feishu, LINE, BlueBubbles,
  Synology Chat, Tlon, Nextcloud Talk, WeChat, QQ, plus a "WebChat"
  channel and a generic REST/HTTP surface. **For an embedded SaaS
  use case the only relevant surfaces are WebChat + REST.**

### 2.4 Programmable surface

- **REST API (gateway, ~12 endpoints):** `GET/POST /api/sessions`,
  `POST /api/sessions/:key/messages` (SSE-streamed),
  `GET /api/sessions/:key/history`, `GET/POST /api/cron`,
  `GET/POST /api/hooks`, `GET /api/skills`, `POST /tools/invoke`,
  `GET /api/status`. Auth: Bearer token via `gateway.token`.
- **SDKs:** First-party TypeScript Plugin SDK
  (`tsconfig.plugin-sdk.dts.json`). A `pip install openclaw-sdk`
  is referenced in third-party guides; first-party authority not
  verified.
- **Tool / integration model:** Three extension types — **Skills**
  (markdown `SKILL.md` natural-language contracts that call external
  HTTP), **Plugins** (TypeScript Gateway extensions), **Webhooks**
  (HTTP endpoints external systems POST to). Tools live in the
  Gateway's runtime; calling our Postgres means writing a Skill
  that hits our FastAPI endpoint — an **out-of-process round-trip**.
- **Streaming:** SSE for token streaming, WebSocket for control
  plane (cancel, model-override, tool-confirmation).

### 2.5 Memory & cross-session

- **Storage:** JSONL transcripts per session; SQLite session-store
  with WAL; AgentStore + EnvironmentStore + QueueStore + SecretStore
  + AuditStore; long-term memory is workspace-markdown files
  (`SOUL.md, IDENTITY.md, USER.md`) plus model-written notes.
- **Crucially: there is NO Postgres backend option.** Storage is
  filesystem-and-SQLite. Reading session messages from outside the
  Gateway is officially via the REST API; direct file/SQLite reads
  are unsupported.

### 2.6 Hosting / pricing

- Self-host only. No first-party SaaS, no SLA, no status page, no
  SOC 2 claim.
- Software cost: $0 (MIT). LLM cost is BYO (the project does not
  resell tokens). Self-hosted on OCI Always-Free VM is feasible.
- **Bring-your-own-model:** Built-in providers — Anthropic, OpenAI,
  Gemini, Groq, Qwen, Ollama, vLLM, SGLang — plus a generic "OpenAI-
  compatible" provider. **No first-party OCI Generative AI provider.**
  Pointing at our `gpt-5.4` endpoint requires either an
  OpenAI-completions shim or registering OCI as a custom provider
  (workable, but undocumented and not first-class).

### 2.7 Direct fit-test against AI Insights tab

| Need | Native OpenClaw support? | Verdict |
|---|---|---|
| Per-insight session scoping (~thousands of distinct prompt scopes) | Sessions exist; system prompt is **per-agent** not per-session; per-session tool-allowlist not documented | **Partial; would need a custom plugin** |
| Citation prefetch (5-7 citations attached BEFORE chat starts) | Not a primitive; workarounds are workspace-markdown churn or transcript pollution | **Misfit** |
| Read messages from our Postgres | Black-box JSONL on disk; no Postgres backend option | **Misfit** |
| Bring-your-own model = OCI gpt-5.4 | Only via OpenAI-compatible adapter | **Workable but second-class** |
| Eject path | Trivial (MIT; JSONL portable) | **OK** |

### 2.8 vs. LangGraph / Llama Stack / Vercel AI SDK

- Those are **libraries** that live in our process, with full control
  over storage (Postgres + pgvector), prompts, and tool dispatch.
- OpenClaw is a **gateway product** whose primary novelty —
  "your personal AI on every messenger" — is not what we need.
- OpenClaw's distinctive features (multi-channel adapters, voice
  nodes, iMessage bridging, sandbox-per-group) are entirely unused
  by us.
- The features we'd actually use (SSE streaming, transcript
  compaction, function-calling tools) are commodity and replicable
  in well under 1,000 LOC against LangGraph or Llama Stack with
  Postgres-backed storage.

### 2.9 Risks

1. **Vendor lock-in:** Low contractually (MIT) but moderate
   architecturally (workspace files, plugin TS API, JSONL schema,
   gateway HTTP auth).
2. **SLA / reliability:** None — self-hosted; no status page; EOL
   risk = repository-abandonment risk; foundation governance is
   <3 months old.
3. **Privacy / security:** Self-hosted means data stays local; LLM
   provider terms apply. **One reported red flag:** ~17,000 OpenClaw
   instances discoverable on Shodan (per third-party scan) — operator
   hardening is left to the user.
4. **EOL / export:** JSONL transcripts and SQLite stores are local
   files; trivially exportable. No first-party export CLI.

### 2.10 Researcher's bottom line

> "OpenClaw is a popular, MIT-licensed, self-hostable, single-user
> personal-assistant gateway. Its core value proposition — bring one
> AI assistant to all your messengers, owned by you — is real and
> well-engineered. For embedding as the chat layer of a multi-tenant
> analyst SaaS where each user has thousands of insight-scoped chats,
> where the host backend wants to control the system prompt per
> session, attach citations, and read messages from its own
> Postgres, OpenClaw is a poor architectural fit."

---

## §3. Product evaluation (PM)

> Source: `/tmp/openclaw_pm.md`. The PM lens asks: would adoption
> improve user experience or finding quality? Honest answer: no.

### 3.1 User stories — help / neutral / harm

| Scenario | Verdict | Why |
|---|---|---|
| Karan asks "what does the EDGAR row really say?" → DB tool call. | **Harm (mild)** | We already have `query_database` wired through `sql_gate.validate_sql` with per-insight scope. OpenClaw routes through its tool layer to our DB as a remote tool. Same answer at best, extra hop and a third-party trust boundary at worst. |
| "Show me a 12-month chart of permits in Texas" → `get_chart_data` + `emit_chart`. | **Harm** | Charts are first-class in our pipeline: `emit_chart` writes `agent_chart`, `InsightCard` reads `chart_id`/`spec` directly. OpenClaw is text-channel-first; it has no concept of structured chart artifacts in a session. |
| Switches to a different insight, asks the same question. | **Neutral** | Both today and OpenClaw provide isolation; today via `thread_id` scoped to `insight_id`. Parity, not improvement. |
| Returns tomorrow morning, "what we discussed yesterday". | **Help (small, but misaligned)** | OpenClaw advertises "24/7 context retention". But the unit of memory in our product is the **insight**, not the **user** — and yesterday's insight may already be deduped under `ongoing_of_id`. Cross-day chat memory across different insights is a feature we have **deliberately not** asked for, and we can add it ourselves to `agent_message` if desired. |
| Wants to share a chat with a colleague. | **Neutral** | OpenClaw's docs do not call out export/share. Multi-channel forwarding is not the same as a permalink to a tab card. |
| On-call engineer debugs "why did the agent give that answer?" | **Harm (significant)** | Today: full trace lives in `agent_message` + `agent_tool_call` + `agent_chart` rows tied to `insight_id` / `session_id`. Replay = `SELECT`. With OpenClaw: trace fidelity from Postgres drops to whatever the gateway exposes. JSONL on disk in another process is not the same as a row in our DB. |

**Score:** 2 harm, 2 neutral, 2 small help on adjacent (not requested)
features. **Not a clean win.**

### 3.2 Quality of replies

The model is the same (gpt-5.4). Mechanistically, "smarter" can only
come from better prompt construction, better tool routing, better
memory, or better grounding.

**Possible help:**
- Better tool routing on ambiguous prompts, **if** OpenClaw's router
  is genuinely better-tuned than our `ToolLoopDriver`. Unverified.
- `/compact`-style summarisation on long threads (we don't currently
  have).

**Likely degradations:**
- **Less specialised system prompt.** Our `_chat_system_prompt`
  injects ~6-8 KB of grounded preamble per turn — headline, body,
  skills_run, confidence/materiality, compact chart spec, citations
  with `agree_or_disagree` rationale. A generic OpenClaw persona
  will not know to do this; we would rebuild the same preamble as
  a skill and pay the round-trip.
- **Worse citation grounding.** We pre-run web search at insight
  creation and persist `agent_citation` rows so the chat starts
  already grounded. OpenClaw's chat surface is conversational-first;
  pre-loaded structured citations are not a native concept.
- **Looser tool surface.** Today we deliberately gate `query_database`
  through `sql_gate.validate_sql`. The V1.1 plan goes further: it
  explicitly **withholds** `run_skill`, `emit_chart`, `emit_citation`,
  `web_search` from the agentic driver. Re-platforming on OpenClaw
  means re-litigating that allow-list against an external runtime
  that advertises "self-modifying skills" — a direction we have
  actively chosen not to take.
- **Persona bleed.** OpenClaw is built around a customised persona;
  we want a deterministic data analyst, not a personality.

**Net:** Same model, worse grounding, looser tools, no clear
quality upside.

### 3.3 Quality of FINDINGS (the daily 5-7 insights)

Findings are produced by an APScheduler cron running a deterministic
SQL → mega-LLM-call pipeline. **No part of OpenClaw fits into this
path:**

- It would not help build the FactPack (7 SQL queries against our
  Postgres).
- It would not help with the mega-call (one `llm_client.reason`
  with JSON-schema `response_format`).
- It would not help dedup (pgvector cosine vs last 14 days).
- It would not help SSE fan-out (FastAPI-internal).

The only loose fit is "pipe the cron output to Karan's Slack via
OpenClaw" — explicitly out-of-scope.

### 3.4 Features OpenClaw offers we don't have

| Feature | Want for analyst tool? | Why |
|---|---|---|
| Multi-channel reach (Slack, WhatsApp, iMessage, Signal, Telegram, Discord) | **No** | Karan does triage in a desktop tab with charts and citation pills. WhatsApp truncates everything material. |
| `/compact` summarisation | **No (chats aren't long enough)** | `CHAT_MAX_TURNS=12`, `CHAT_HISTORY_LIMIT=50`. Most threads are 2-4 turns. |
| Cross-session memory | **Maybe (small)** | Unit of memory in our product is insight, not user. Add ourselves in 1-2 days if needed. |
| Slash commands | **No** | Karan is an analyst, not a CLI power user. |
| Persona / agent customisation | **No** | Single user, single persona ("scoped to ONE specific insight"). |
| Mobile nodes (camera + voice) | **No** | Out of scope ("No mobile layout"). |
| ClawHub community skill marketplace | **No** | We deliberately **narrow** the agent surface; a marketplace pulls the wrong direction. |
| Web Control UI dashboard | **Neutral** | Duplicates a slice of our existing tab. |
| Self-modifying skills | **No (actively dangerous)** | Security-review nightmare for tools that hit our Postgres. V1.1 goes the opposite direction. |

**Score:** 0 strong yeses, 1 maybe, the rest no.

### 3.5 Features WE have that OpenClaw might break

1. Per-insight scoped system prompt (`_chat_system_prompt(context)`
   injects 6-8 KB of structured insight context per turn).
2. Pre-loaded citations (`_build_chat_context` reads `agent_citation`
   rows directly and inlines them into the system prompt).
3. Direct DB-bound tools (`query_database` is in-process FastAPI
   talking to our Postgres with `sql_gate.validate_sql`; from
   OpenClaw's Gateway, our DB is a remote tool over HTTP).
4. Charts as first-class agent outputs (`emit_chart` writes
   `agent_chart`; the React `InsightCard` joins on
   `agent_chart.insight_id`).
5. Reasoning trace persistence (every tool call writes
   `agent_message` + `agent_tool_call` rows scoped to `thread_id` +
   `session_id`).
6. Audit trail in our DB (compliance / internal review reads our
   tables directly).
7. SSE fan-out contract with the tab (`InsightChatDock.tsx` consumes
   a strict event taxonomy).

**Seven tightly-coupled features at risk for ~zero in-scope analyst
benefit.**

### 3.6 Acceptance criteria for "OpenClaw helped"

| # | Criterion | Realistic Before | Realistic After | Note |
|---|---|---|---|---|
| AC1 | p50 chat-turn latency | ~6-10 s | ~8-14 s | OpenClaw adds a hop. |
| AC2 | p95 chat-turn latency | ≤45 s (PRD §5.4 budget, met) | likely ≥50 s | Wall-budget tightens. |
| AC3 | % of replies that cite a real DB row | ~70% | uncertain; depends on remote tool routing | Regression risk if <60%. |
| AC4 | Trace replay fidelity | 100% (single SQL) | partial (depends on Gateway export) | Hard regression risk. |
| AC5 | Karan satisfaction over N=10 chats | unknown baseline | needs **≥+0.5 points** | Only criterion that could justify. |
| AC6 | Chart render success rate | ~95% | likely ≤50% in v1 | Hard regression. |
| AC7 | Cross-session memory recall | n/a | claim-only; needs eval | Net-new but unrequested. |
| AC8 | Eng effort to ship parity | 0 | 4-8 dev-weeks | Pure cost. |

For OpenClaw to win: **AC5 ≥ +0.5 stars AND zero regression on AC1,
AC4, AC6.** High bar with no plausible mechanism.

### 3.7 V1.1 deprioritisation cost

V1.1 work we'd skip if we redirect engineering:
`agentic_driver.py`, `drill_down`, `row_get`, `cross_section_join`,
`list_factpack_sections`, `POST /api/insights/agentic`.

- **For OpenClaw over V1.1:** outsources the loop runtime;
  potentially smarter routing on ambiguous questions; multi-channel
  reach as a free side-effect (out of scope).
- **For V1.1 over OpenClaw:** closes the **named** gap from
  ADR-006 §3 ("X MW generated, only partially consumed by some
  company") that V1's deterministic catalogue can't pre-imagine;
  reuses existing tool surface, SSE taxonomy, persistence tables,
  dedup pool — zero new audit gaps; tools are explicitly **narrowed**
  (V1.1 §2.1) — opposite of OpenClaw's pull; opt-in human-watched,
  leaving the 09:00 cron deterministic.

**Karan gets more value from V1.1.**

### 3.8 PM verdict

**Skip.** OpenClaw is a well-built personal-assistant gateway aimed
at consumer multi-channel chat. Our product is a single-user,
single-tab, data-grounded competitive-intel surface where the
highest-value features are exactly the ones OpenClaw doesn't
natively support. The features OpenClaw would bring are either
out-of-scope (mobile, notifications) or solving problems we don't
have (short chats, single user, single insight scope). Same
underlying LLM, so no quality lift is even mechanistically
plausible. Spend the same engineering weeks on V1.1.

---

## §4. Architectural evaluation (architect)

> Source: `/tmp/openclaw_architect.md`. The architect lens asks:
> simplify or complicate? And: is the user's "no manual scripts"
> claim true?

### 4.1 Component-by-component map

The current chat path is enumerated below with explicit verdicts.
The user's claim that OpenClaw lets us delete `_chat_system_prompt`
and `_build_chat_context` is the most consequential one — addressed
explicitly.

| Current component | What it does today | OpenClaw: replace / keep / augment | Confidence | Notes |
|---|---|---|---|---|
| `_chat_system_prompt(ctx)` (`backend/routers/insights.py` ~877-898, ~22 lines) | Static persona + style block, then appends `INSIGHT CONTEXT (JSON):` followed by `json.dumps(context)[:8000]`. Built fresh on every turn. | **KEEP** (cannot replace cleanly) | High | OpenClaw's system prompt lives in agent config (SOUL.md / config). It is **per-agent**, not per-request. We cannot inject 8 KB of dynamic per-insight JSON into a static SOUL.md without either creating one OpenClaw agent per insight (~2,500/yr) or shipping the JSON as the user message itself — which contaminates the user-visible transcript. |
| `_build_chat_context(db, insight_id)` (`insights.py` ~810-875, ~65 lines) | Reads `AIInsight`, `AgentChart`, `AgentCitation` from Postgres and returns a typed dict (headline, body, skills_run, confidence, materiality, chart_compact, citations). | **KEEP** | High | This is **our domain model**, joined across three tables. OpenClaw has no notion of `AIInsight` or `AgentChart`; we'd still write this exact function. The user's claim is wrong here: this is not a "manual script", it is the data-loading layer. |
| 8000-char prompt-truncation cap | Hard cap on per-turn prompt growth so chart `data_source` blobs cannot blow our token budget. | **KEEP** | High | OpenClaw's compaction operates on conversation history, not on an externally injected context blob. |
| `ToolLoopDriver` (`tool_loop.py`, 242 lines) | OpenAI-style while-loop: turn = await llm_call; if no tool_calls return; else dispatch in parallel (cap 4) and append tool messages. Caps: `max_turns=12, max_parallel=4, wall=120s`. | **REPLACE — partially** | Medium | OpenClaw has its own agent loop. If we delegate chat turns we shed ~242 LOC. But the orchestrator's V1/V2 insight-discovery path **also** uses ToolLoopDriver; that path is a server-side scheduled job, not a chat. So at most one of the two callers migrates. |
| 6 chat tools (`query_database`, `call_api`, `get_chart_data`, `web_search`, `run_skill`, `emit_chart`, `emit_citation`) | Async functions touching our Postgres, internal `/api/` routers, our chart store, our skill library, Brave Search, our citation persistence. Dispatched in-process. | **AUGMENT (wrap as webhooks); cannot replace** | High | OpenClaw's "Tools Invoke API" is HTTP. Tools execute either in OpenClaw's runtime (no path to our Postgres) or via webhooks back to our backend — the only viable shape. Every tool gets a thin webhook adapter. The tool **bodies** do not shrink. |
| `sql_gate.validate_sql` (AST gate inside `query_database`) | Parses the model's SQL via sqlglot, enforces SELECT-only, blocks dangerous statements, caps row count. | **KEEP** | Very High | Security control on our DB. Must run inside our process. OpenClaw never sees the SQL. |
| SSE event taxonomy (`sse_events.py`, 401 lines, 18 event types) | Discriminated Pydantic union with strict schema, wire-format helper, `event_id`/`seq`/`ts` triple for replay. | **KEEP** (mostly); could trim 4 chat-specific events | Medium-High | The chat-only events are 4 of 18. Insight discovery still needs the other 14. The frontend would have to consume two different SSE shapes (worse, not better). |
| `to_sse_text(event)` serializer | Renders Pydantic event into `id:/event:/data:` SSE wire format. | **KEEP** | Very High | Trivial helper; cost of removing it is dominated by having two SSE protocols on the frontend. |
| `agent_message` persistence (write at `insights.py` ~1191-1213) | Postgres rows with `(session_id, insight_id, thread_id, seq, role, content, tool_calls, delete_after)`. FK to `ai_session` and `insight_thread`. | **KEEP** (unless full replacement) | High | OpenClaw stores transcripts as JSONL files at `~/.openclaw/agents/<id>/sessions/<sid>.jsonl` — filesystem, not RDBMS. Our backend, exports, and analyst tooling all expect Postgres rows. |
| `agent_tool_call` persistence (in `agent_message.tool_calls` JSONB) | Reconstructs tool-chip UI on history load. | **KEEP** | High | JSONL on disk in another process is not equivalent to a queryable JSONB column. |
| `agent_chart` persistence | One row per emitted ChartSpec including `row_hash`, `data_source`, full `spec` JSONB. | **KEEP — non-negotiable** | Very High | Chat dock fetches charts back via `GET /api/insights/.../chat -> messages[].charts`. OpenClaw has no concept of typed-chart artifacts. |
| `agent_citation` persistence | Per-insight web citations (URL + snippet + agree/disagree + rationale). Pre-loaded **before** chat starts. | **KEEP — non-negotiable** | Very High | Pre-load is the load-bearing detail (see §4.4). |
| `InsightThread` + chat history loader (recently fixed reverse-iter loader at `insights.py` ~1057-1075) | `_get_or_create_thread` per insight; on POST chat the last 20 messages are pulled from `agent_message` filtered by `thread_id`. | **REPLACE in concept**, but lose Postgres-side analytics | Medium-High | OpenClaw's session model is channel-tied; mapping per-insight onto it is abuse of the abstraction. |
| `InsightChatDock.tsx` (1146 lines) | Per-insight slide-down chat UI; SSE parser; tool-call chips; chart and citation rendering inline. Talks **only** to `/api/insights/insights/{id}/chat`. | **AUGMENT or REPLACE** | High | If full-replacement, the dock either talks to OpenClaw directly (CORS, auth, network reachability) or proxies through our backend (no LOC saved). |
| `llm.client` (gpt-5.4 wiring, `MODELS["reasoning"]`) | Authenticated OCI Generative AI client returning `{content, tool_calls, model, tokens}`. | **KEEP** if we keep ToolLoopDriver; **DROP from chat path** if full-replace and OpenClaw drives the LLM | Medium | OpenClaw needs an OCI custom-provider shim — non-trivial; abandoning OCI auth for chat likely fails compliance. |

**Direct response to the user's claim** ("we don't need manual
scripts to wrap those contexts and prompts"): **false in the strong
reading, partially-true only in a trivial sense.**

- **Strong reading** ("delete `_chat_system_prompt` and
  `_build_chat_context`"): **false.** OpenClaw has no notion of
  `AIInsight`, `AgentChart`, or `AgentCitation`. The 65-line
  `_build_chat_context` joining three of our tables remains
  essential; the 22-line `_chat_system_prompt` is replaced only via
  pathological agent-per-insight provisioning or transcript
  pollution.
- **Weak reading** ("the SSE/queue/while-loop wrapper code shrinks"):
  partially true. Hybrid (b) sheds ~500 LOC of looping plumbing —
  but adds ~550 LOC of webhook adapters and SSE translation. Net
  flat to slightly negative.

### 4.2 Critical tool-call routing question

Our analyst chat **must** query our Postgres in our network. The
DB sits inside the same VCN as the FastAPI app and is not
internet-reachable.

```
Case A — OpenClaw runs tools in their runtime (INFEASIBLE for us)
  Browser --HTTPS--> OpenClaw service --LLM--> tool_call=query_database
                            |
                            v
                   OpenClaw worker: runs the tool
                            |
                            X--- cannot reach our Postgres
                            X--- cannot import our sql_gate
                            X--- has no auth to OCI / our /api

Case B — OpenClaw routes tool calls via webhook (ONLY VIABLE)
  Browser --HTTPS--> OpenClaw service --LLM--> tool_call=query_database
                            |
                            v
                   OpenClaw: POST {our backend}/oc-tool/query_database
                            |
                            v
                   FastAPI handler: validate_sql -> Postgres -> JSON
                            |
                            v
                   OpenClaw: append tool result, next LLM turn
```

Per OpenClaw's docs Case B is the supported architecture. Even
co-located on the same host, the path is
`OpenClaw process -> HTTP -> FastAPI process -> Postgres`. That is
**one extra in-process boundary and one extra serialization per
tool call** vs today's direct in-process `dispatch(name, args, ctx)`.

### 4.3 Per-insight scope

Today every chat session is bound to a single insight by:

1. URL path `/insights/{insight_id}/chat` carries the insight id.
2. `_build_chat_context(db, insight_id)` joins
   `AIInsight + AgentChart + AgentCitation`.
3. `_chat_system_prompt(ctx)` packs that joined context into a
   system prompt.
4. `SkillContext.insight_id` propagates the scope into every tool
   call.

**Can OpenClaw express "this session has THIS system prompt only
and these 5 tools"?** Per their docs the system prompt is configured
**per-agent** (SOUL.md + config), tools are also per-agent, and
sessions are scoped per-channel-and-peer, not per-system-prompt.
Three options:

- **One OpenClaw agent per insight** — pathological. ~7 insights/day
  × 365 = ~2,500 distinct agents/year, each with its own SOUL.md
  and an 8 KB context blob. OpenClaw's docs do not suggest this
  scale of agent count is supported; we'd need a programmatic
  agent-lifecycle API for which there is no public surface.
- **One agent + dynamic prompt override per request** — would
  require either an undocumented per-request prompt-override field
  or smuggling context as the first user message (transcript
  pollution; visible to user; harder to audit).
- **One agent + a `load_context` tool** — viable, but it just
  relocates `_build_chat_context` behind a tool call, paying the
  HTTP round-trip every turn.

**Verdict:** OpenClaw's primitives do not natively model "thousands
of distinct prompt scopes that share a tool list".

### 4.4 Pre-loaded citations

Today the flow is:

1. During insight synthesis, `emit_citation` writes rows into
   `agent_citation` keyed by `insight_id`. **The chat session does
   not exist yet.**
2. Hours later, the dock fetches `GET /api/insights/.../chat`,
   returning `messages[].citations`.
3. On every chat POST, `_build_chat_context` re-reads citations
   and bakes them into the system prompt.

**Does OpenClaw support "session opens with N citations preloaded"?**
Their docs describe memory engines (builtin / Honcho / QMD /
LanceDB / wiki) and a Context Engine, but pre-loaded citations
are **not** a documented primitive. Workarounds (stuff into
user-message preface, or `lookup_citations(insight_id)` tool every
turn) are worse than what we have.

### 4.5 Three integration architectures

#### (a) FULL REPLACEMENT — OpenClaw replaces our chat layer end-to-end

```
+--------+      +-----------+         +-----------+        +----------+
|Browser |--SSE-| OpenClaw  |--LLM--> |   OCI/    |        |  Brave   |
|  Dock  |<-----| (gateway) |<--------|  GPT-5.4  |        |  Search  |
+--------+      +--+--+--+--+         +-----------+        +----+-----+
                   |  |  |                                      ^
            tool   |  |  | tool result                          |
            call   v  |  |                                      |
       +-----------+  |  |                                      |
       | webhook   |  |  |                                      |
       |  layer    |--+--+--------------------------------------+
       | (NEW)     |
       +-----+-----+
             |
             v
       +-----------+        +--------------+
       |  FastAPI  |------->|   Postgres   |
       |  (slim)   |        +--------------+
       +-----------+

Tables we DROP:
   - agent_message  (transcript moves to OpenClaw JSONL files)
   - insight_thread (replaced by OpenClaw session ids)
   - agent_message.tool_calls JSONB

Tables we KEEP:
   - ai_insight, ai_session, agent_chart, agent_citation

NEW infra:
   - OpenClaw service process (self-hosted, must be HA)
   - JSONL transcript filesystem (must be backed up; new RPO/RTO target)
   - 6 webhook endpoints (one per tool) on FastAPI
   - Per-insight OpenClaw agent provisioning + GC pipeline
   - CORS / auth shim between browser and OpenClaw
   - OCI custom-provider shim
```

#### (b) HYBRID-CHAT-ONLY — OpenClaw behind our backend

```
+--------+      +----------+      +-----------+      +-----------+
|Browser |--SSE-| FastAPI  |----> | OpenClaw  |--LLM-|  GPT-5.4  |
|  Dock  |<-----| (proxy)  |<-----| (sidecar) |<-----+-----------+
+--------+      +--+-------+      +----+------+
                   |                   |
                   |                   v
                   |             tool call (webhook back to FastAPI)
                   v
              +---------+
              |Postgres |
              +---------+

KEEP: all current persistence, all SSE event names on the wire,
      InsightChatDock.tsx, sql_gate.validate_sql.
REMOVE: ToolLoopDriver inner loop (~242 LOC), event-queue plumbing
        in post_insight_chat (~180 LOC).
ADD:    OpenClaw client adapter, SSE event translator (OpenClaw ->
        our taxonomy), webhook adapters for the 6 tools.
```

#### (c) HYBRID-CROSS-SESSION-ONLY — only OpenClaw's memory

```
+--------+      +----------+      +-----------+
|Browser |--SSE-| FastAPI  |--LLM-|  GPT-5.4  |
|  Dock  |<-----| (today)  |<-----+-----------+
+--------+      +-+--+-----+
                  |  ^ memory r/w
                  v  |
              +------+------+
              |  OpenClaw   |   (used ONLY as a memory store)
              |  memory eng |
              +------+------+
                     v
              +-------------+
              |  Postgres   |   (still primary; OC is derived)
              +-------------+

Everything else stays exactly as today.
```

### 4.6 LOC delta estimate

Reference LOC counts from the repo:
- `_chat_system_prompt`: 22
- `_build_chat_context`: 65
- `post_insight_chat` body: ~330 (lines ~900-1237)
- `tool_loop.py`: 242
- `tools/registry.py`: 301
- `sse_events.py`: 401
- `InsightChatDock.tsx`: 1146

| Mode | Removed | Added | Net | Plus operational cost |
|---|---|---|---|---|
| **(a) Full replacement** | ~660 LOC (`_chat_system_prompt`, most of `post_insight_chat`, `tool_loop.py`, 4 SSE events, `agent_message` writes, history loader) | ~930 LOC (OpenClaw client, agent provisioner, 6 webhooks w/ sql_gate, SSE translator, JSONL backup, GC sweeper) | **+270 LOC** | New external service to operate |
| **(b) Hybrid chat-only** | ~500 LOC (`tool_loop.py`, event-queue plumbing, registry glue) | ~550 LOC (OpenClaw client, SSE translator, 6 webhook adapters w/ auth) | **+50 LOC** | Sidecar process |
| **(c) Memory-only** | ~0 | ~80-120 LOC (memory client, hooks) | **+100 LOC** | None |

**In none of the three modes does the user's claim manifest as a
real LOC win.**

### 4.7 Failure mode analysis

| Outage | (a) FULL REPLACEMENT | (b) HYBRID-CHAT | (c) MEMORY-ONLY |
|---|---|---|---|
| OpenClaw down 1 h | Chat 100% down. Insight render unaffected. | Chat 100% down. Insight render unaffected. | Chat dock degraded — falls back to no cross-session memory; functional. |
| OpenClaw down 1 day | Same + reconciliation when it returns. | Same. | Trivial. |
| OpenClaw EOL'd | **Catastrophic.** Transcripts + tool traces in JSONL. Must build importer + rewrite frontend. ~3-4 weeks. | **Bounded.** `agent_message` is source of truth; restore ToolLoopDriver from git. ~1 week. | **Trivial.** Disable memory client. ~1 day. |
| SSE re-attach during outage | Re-attach goes to OpenClaw and fails. Today's per-process replay buffer cannot rescue it. | Re-attach works against our proxy; in-flight turn is lost. | Unaffected. |

Reliability degrades monotonically as we adopt more of OpenClaw.

### 4.8 Latency / data residency / cost path

**Today (one hop):**

```
Browser --(1)--> FastAPI --(2)--> OCI GPT-5.4
   ^               |
   |               +--(3)--> Postgres (in-VCN)
   +---SSE---------'
```
Network hops: 1. Tool calls: in-process Python.
Serializations per turn: ~3.

**With OpenClaw full replacement:**

```
Browser --(1)--> OpenClaw --(2)--> OCI GPT-5.4
   ^                |
   |                +-(3)-> webhook -> FastAPI -(4)-> Postgres
   +---SSE---'
```
Network hops on chat path: 2.
Per tool call: +1 HTTP round-trip and +2 serializations.
Per chat turn with N tool calls: 1 + N extra hops, 2N extra
serializations.

**Conversation data lives in TWO places** in mode (a): tool results
in Postgres, transcript in OpenClaw JSONL on disk. **Compliance:**
if the environment is OCI-region-pinned, OpenClaw must run in the
same region; running it elsewhere splits data residency.

Mode (b) keeps conversation data residency in Postgres — wins on
compliance.

**Cost:** OpenClaw is open-source (no markup), but operational
cost (extra service to monitor, patch, scale) is real.

### 4.9 Architect verdict

**Net-complicate** for full replacement; **net-neutral to mildly
negative** for hybrid chat-only; cross-session-memory-only is the
only mode where OpenClaw might add net value, and even that is a
thin win over `agent_message` + pgvector. The user's claim is
false in its strong reading.

---

## §5. Three options compared

| Aspect | (a) Full replacement | (b) Hybrid chat-only | (c) Cross-session memory only | (d) Skip — proceed with V1.1 |
|---|---|---|---|---|
| Net LOC delta | +270 | +50 | +100 | 0 (no change to chat) |
| New process to operate | Yes (OpenClaw HA) | Yes (sidecar) | Yes (sidecar) | No |
| Replaces `_chat_system_prompt`? | Only via pathology | No | No | n/a |
| Replaces `_build_chat_context`? | No | No | No | n/a |
| Replaces ToolLoopDriver? | Yes | Yes | No | No |
| Tools resident in our process? | No (webhook) | No (webhook) | Yes | Yes |
| Chart artifacts first-class? | Reinvent contract | Same as today | Same as today | Same as today |
| Pre-loaded citations supported natively? | No | n/a (we still preload) | n/a | Yes |
| Trace replay fidelity (Postgres-readable)? | Lost | Preserved | Preserved | Preserved |
| Compliance / data residency | Splits across two stores | Single store | Single store | Single store |
| EOL risk if OpenClaw dies | Catastrophic | Bounded (~1 wk) | Trivial | None |
| User-facing benefit | Negative-to-neutral | Neutral | "yesterday we discussed…" | Closes V1.1 ADR-006 §3 gap |
| Eng cost | 4-8 dev-weeks | 2-4 dev-weeks | 1-2 dev-weeks | already on backlog |
| Reversibility | Low (export + rewrite) | Medium | High | n/a |

---

## §6. Decision matrix

Each option is scored 1-5 (5 = best for us). Lower is worse. Weights
reflect the importance of each criterion to this product (analyst
tool, single user, in-app dock, gpt-5.4 unchanged).

| Criterion | Weight | (a) Full | (b) Hybrid chat | (c) Memory only | (d) Skip + V1.1 |
|---|---|---|---|---|---|
| Cost (dev-weeks) | 3 | 1 | 3 | 4 | 5 |
| Reply quality impact | 5 | 2 | 3 | 3 | 4 |
| Trace / audit fidelity | 5 | 1 | 4 | 5 | 5 |
| Lock-in / reversibility | 4 | 2 | 4 | 5 | 5 |
| Operability (one fewer service is better) | 3 | 1 | 2 | 3 | 5 |
| Compliance / data residency | 3 | 2 | 4 | 4 | 5 |
| Closes Karan-named feature gap | 5 | 1 | 1 | 1 | 5 |
| Future optionality (multi-channel, mobile) | 2 | 4 | 4 | 2 | 1 |
| **Weighted total** | **30** | **52** | **86** | **102** | **130** |

(Computed as Σ weight × score. Range 30-150.)

Even mode (c) — the most defensible OpenClaw scenario — comes in
at 102 vs 130 for the do-nothing-on-OpenClaw alternative. The full-
replacement scenario scores 52, less than half of the skip option.

---

## §7. Recommendation with reasoning

**Recommendation: SKIP. Do not adopt OpenClaw for the AI Insights
tab in any of modes (a), (b), or (c). Continue with the V1.1
agentic-driver plan in `08-v1.1-agentic-plan.md`.**

Reasoning, in order of weight:

1. **Same model, no quality lift.** The underlying LLM is OCI
   gpt-5.4 in either world. No mechanism in OpenClaw — not its
   router, not its memory engine, not its `/compact` — can produce
   smarter answers than the model is already capable of. The lever
   that actually moves reply quality is *better grounding*: more
   relevant context, sharper tools, pre-fetched citations. We
   already do all three; OpenClaw makes them harder, not easier.
2. **Architectural fit is poor on the load-bearing details.**
   OpenClaw's session model is per-channel-per-peer, not per-
   insight. Its system prompt is per-agent, not per-request. Its
   tools execute in its runtime, not ours. Its storage is filesystem
   JSONL, not Postgres. Each of those is a tax we'd pay forever.
3. **The user's "no manual scripts" claim does not survive
   inspection.** `_build_chat_context` is a 65-line domain-model
   loader joining three of our tables; OpenClaw cannot replace it
   because OpenClaw doesn't know our schema. `_chat_system_prompt`
   is a 22-line composer; OpenClaw can replace it only by either
   provisioning thousands of agents per year or polluting the
   user-visible transcript.
4. **Net LOC is neutral or negative across all three integration
   modes.** Full replacement is +270 LOC plus a new HA service.
   Hybrid is +50 LOC plus a sidecar. Memory-only is +100 LOC plus
   a sidecar. None of these is a simplification.
5. **Audit and compliance regress.** Today every tool call is a
   row in our DB; replay is a `SELECT`. Mode (a) splits transcripts
   onto a filesystem in another process — a hard regression for
   trace fidelity, exports, and analyst tooling. Mode (b) is
   bounded but adds a sidecar to monitor.
6. **V1.1 closes a Karan-named gap; OpenClaw does not.** ADR-006 §3
   names a specific finding-quality gap ("X MW generated, only
   partially consumed by some company") that V1's deterministic
   catalogue cannot pre-imagine. V1.1's agentic driver targets
   exactly this. Redirecting engineering to OpenClaw does nothing
   for that gap.
7. **Foundation governance is <3 months old.** OpenClaw's creator
   joined OpenAI on 2026-02-14 and handed stewardship to a new
   foundation. Foundation maturity is unproven. EOL risk is
   non-trivial for a system we'd embed at the chat-layer level.

The two ideas worth borrowing from OpenClaw's playbook are:
(i) `/compact`-style transcript summarization, and
(ii) JSONL-parallel audit-log export. Both are tractable in our own
stack at <500 LOC each (see §9).

---

## §8. If we adopt it: phased rollout plan

This section is included for completeness; the recommendation is
to skip. If a future change of constraints (e.g. multi-channel
notifications become a real requirement, or we go multi-tenant
SaaS) flips the decision, this is the suggested order.

### Phase A — pilot mode (c) memory-only (lowest risk)

- Stand up an OpenClaw sidecar inside the FastAPI deployment.
- Wire only the memory hooks: read-on-context-build,
  write-on-message-complete.
- Gate behind a feature flag (`AI_INSIGHTS_USE_OPENCLAW_MEMORY=1`).
- Eval criteria: does Karan find cross-session memory recall
  useful in N=20 chats over 2 weeks?
- Rollback: feature-flag off, re-deploy. Zero code rollback.

### Phase B — pilot mode (b) hybrid chat-only

- Only if Phase A delivers measurable user value.
- Build the SSE event translator, OpenClaw client adapter, 6
  webhook adapters for the existing tools.
- Keep `agent_message` as source of truth; OpenClaw is an in-line
  cache, not the system of record.
- Eval criteria: AC1 (p50 latency) regression <20%; AC4 (trace
  fidelity) ≥ 95%; AC5 (Karan satisfaction) ≥ +0.5.
- Rollback: feature-flag back to direct ToolLoopDriver path.

### Phase C — full replacement, mode (a)

- Only if Phase B clears all three eval criteria over a full
  month.
- Provision-per-insight agent lifecycle pipeline, JSONL backup
  job, migration tooling for `agent_message` → JSONL or vice
  versa.
- Migrate `InsightChatDock.tsx` to either OpenClaw direct
  (CORS/auth) or proxy.
- Bake compliance review (data residency split).

**No phase commits to the next.** Each is independently shippable
and rollbackable. The first phase to fail eval ends the program.

### Risk register for adoption

- **R-OC-1.** Foundation governance fails / project EOLs within
  12 months. Mitigation: stay in mode (b) where rollback is ~1
  dev-week.
- **R-OC-2.** OCI custom-provider shim breaks on `gpt-5.4` schema
  drift. Mitigation: pin shim version; monitor in CI.
- **R-OC-3.** JSONL transcript backup misses an RPO. Mitigation:
  RTO/RPO drill in Phase A before any data lives only in JSONL.
- **R-OC-4.** Tool-call latency over webhook breaches AC1.
  Mitigation: keep OpenClaw co-located with FastAPI; loopback
  network; no TLS terminator between them.

---

## §9. If we skip it: features worth cloning

Even though we are not adopting OpenClaw, two features it ships
are genuinely useful and are tractable in our own stack. These are
recorded as future enhancements but **not blocking for V1.1**.

### 9.1 `/compact`-style transcript summarization

- **What:** When a chat thread exceeds N tokens (or M turns),
  summarise the older half into a single synthetic
  `role=system,content=<summary>` message and elide the original
  rows from the prompt (but **keep them in `agent_message`** so the
  audit trail is complete).
- **Why we want it:** Per the PM, our threads today are 2-4 turns
  median, but the V1.1 agentic driver may extend that. A compact
  pass keeps prompt tokens bounded without losing context.
- **How:** A pure Python function called from `post_insight_chat`
  before the LLM round-trip. ~150-300 LOC including tests.
- **Where it lives:** new `backend/agents/insights/compact.py`.
- **What we explicitly do NOT clone:** OpenClaw's
  workspace-markdown long-term memory (SOUL.md / IDENTITY.md /
  USER.md). Our equivalent is `agent_message` + `agent_citation` +
  `agent_chart` already.

### 9.2 JSONL-parallel audit-log export

- **What:** A nightly job that exports every `agent_message` from
  yesterday into a JSONL file in object storage. One JSONL per
  thread.
- **Why we want it:** Cheap, durable, human-greppable backup and
  feeds external eval / analytics pipelines without granting
  read-access to Postgres.
- **How:** APScheduler `JOB_CONFIG` entry, ~80 LOC plus an
  Alembic-touched index on `(thread_id, seq)` if not already
  present.
- **Where it lives:** `backend/pipeline/runner.py` +
  new `backend/pipeline/export_jsonl.py`.

### 9.3 Things we do NOT clone

For the record:

- **Multi-channel adapters** (WhatsApp, Telegram, etc.) — out of
  scope for an analyst desktop tool. If notifications ever become
  a requirement, evaluate then.
- **ClawHub-style skill marketplace** — security-risk for a tool
  surface that touches our DB.
- **Self-modifying skills** — the V1.1 plan deliberately tightens
  the tool surface; this would loosen it.
- **Per-agent persona / `SOUL.md` / `IDENTITY.md`** — single user,
  single persona; the file-on-disk contract has no advantage over
  a Python constant.
- **`POST /tools/invoke` operator-access surface** — explicitly a
  full-access surface; we already have route-level auth.

---

## §10. Decision

**Decision: SKIP.** No OpenClaw integration in any mode. Continue
with V1.1 as planned. Borrow ideas §9.1 and §9.2 as future
enhancements; do not block V1.1 on them. Revisit only on a
material change of product scope (multi-tenant SaaS; multi-channel
notifications as a hard requirement; cross-session memory becoming
a Karan-named requirement with a measurable success criterion).

**Owner:** AI Insights team.
**Sign-off requested from:** Karan (PM stakeholder).
**Next step:** kick off V1.1 Phase 0 (driver scaffolding +
`drill_down` tool) per `08-v1.1-agentic-plan.md`.

---

*End of ADR-010.*
