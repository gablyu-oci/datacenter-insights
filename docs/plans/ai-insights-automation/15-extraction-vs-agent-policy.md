# Extraction vs Agent vs Tool — Code Placement Policy

This is the canonical lookup that decides where a new piece of code
should live in the strategic-insights-tool backend. It exists because
ARCH 14 / 15 unified all "talking to an LLM" call-sites onto OpenClaw,
which means the boundary between "deterministic extractor", "agent",
and "MCP tool" is the only structural distinction left in the
codebase. New work that gets the bucket wrong tends to drift towards
duplicating tool-loops or smuggling persistence into the wrong layer.

## The three buckets

### Bucket A — Deterministic extractor

A program that turns inbound bytes into rows. Always synchronous from
the caller's perspective (although it may use async I/O for HTTP /
DB), runs on a cron / one-shot pipeline (not a request thread), and
emits database rows that the rest of the platform consumes.

What lives here:
- HTML / PDF text extraction: `agents/insights/extractors/`,
  `agents/edgar_extractor.py`, `agents/vendor_supply_extractor.py`.
- Document parsers: `pdf_parser.py`, `text_chunker.py`.
- Pipeline runners that fold extraction outputs into DB tables:
  `pipeline/runner.py`, `pipeline/edgar_pipeline.py`.

Rules:
- MUST NOT drive an LLM with tool-calling. If a deterministic extract
  benefits from a single LLM call (e.g. summarisation), use a one-shot
  prompt via `llm.client.llm_client.chat()` — no tool loop, no
  streaming.
- MUST be idempotent on re-run.
- MUST NOT depend on `agents.insights.specs.sse_events` or any chat /
  QA event schema.

### Bucket B — Agent

A streaming LLM-backed reasoner that runs inside a request handler
(or a long-lived background task) and uses MCP tools to reach data.
Agents always go through OpenClaw — no agent ever spins up its own
tool-loop in-process.

What lives here:
- Chat lane: `routers/insights.py::_openclaw_chat_handler` ->
  `openclaw/forwarder.py::forward_chat`.
- QA-global: `agents/datacenter_qa.py::answer_question` ->
  `openclaw/qa_forwarder.py::iter_qa_events`.
- Triangulation: `agents/triangulation_qa.py::answer_question_stream`
  -> `openclaw/qa_forwarder.py::iter_qa_events`.
- Synthesis: `agents/insights/agentic_synthesis.py::run_agentic_synthesis`
  -> `openclaw/forwarder.py::_drive_openclaw_stream` (direct).
- Weekly brief: `agents/weekly_brief.py` ->
  `openclaw/forwarder.py::_drive_openclaw_stream` (direct).

Rules:
- MUST go through OpenClaw. New agents call either `forward_chat`
  (chat-lane SSE bytes), `iter_qa_events` (QA-lane events), or
  `_drive_openclaw_stream` (raw event callback) — never roll a fourth
  driver.
- Persona MUST live in `agents/insights/prompts/<name>.md` and be
  loaded with `prompts.load_prompt(name)`.
- Memory namespace MUST be a fresh slug — see ARCH 14 Appendix B for
  the in-use list.
- The agent module is a thin shim; tool dispatch belongs to MCP.

### Bucket C — MCP tool

A small, named function exposed over MCP (`backend/mcp_server.py`)
that an agent can call. Tools are typed via Pydantic / JSON-Schema and
either query data, emit a frontend signal, or persist a row.

What lives here:
- Read tools: `query_database`, `call_api`, `get_chart_data`,
  `web_search`, `run_skill`.
- Write tools (chat lane only): `emit_chart`, `emit_citation`,
  `persist_insight`, `finalize_session`, `persist_brief`.
- QA-only signal tool: `propose_qa_chart` (NO DB write — the
  translator validates and emits a `ChartSpecEvent`).

Rules:
- Each tool body in `mcp_server.py` is a one-line shim that delegates
  to `agents/insights/tools/<name>.py`. Don't put logic in the shim.
- Tools MUST NOT call OpenClaw — that would loop.
- Tools MAY assume an authenticated MCP context (the bearer is
  enforced at the FastMCP middleware layer).
- A new tool needs all of: a docstring (becomes the LLM-visible spec),
  a Pydantic args model where applicable, and a row in the
  `tool_call_log` table on call.

## Decision flowchart

When adding a new piece of code:

1. Does it talk to an LLM with tool-calling, on a per-request basis,
   to produce a streaming response? -> **Bucket B (agent)**.
2. Does it run on a schedule / one-shot to ingest bytes -> rows?
   -> **Bucket A (extractor)**.
3. Does an agent need a new way to read or signal something?
   -> **Bucket C (MCP tool)**.
4. Otherwise it is plain library code (`db/`, `schemas/`,
   `agents/insights/`).

## Anti-patterns to avoid

- **Smuggling persistence into a translator.** The QA translator
  emits events; it does NOT write rows. (Compare: synthesis
  `persist_insight` is a real MCP tool with a DB write.)
- **Building a fourth forwarder.** If you need a new agent lane,
  parameterise `_drive_openclaw_stream` (cap settings, namespace,
  surface filter); don't fork.
- **Putting an LLM call into an extractor.** Either use a one-shot
  prompt (no tool loop) or move the work into a Bucket B agent.
- **Deleting the chat lane's `to_sse_text` in favour of the QA-lane
  framing (or vice-versa).** The two are wire-incompatible — see ARCH
  14 Appendix B and the QA translator's header note.

## Cross-references

- `docs/plans/ai-insights-automation/14-unified-agent-architecture.md`
- `docs/plans/ai-insights-automation/15-agent-unification-cleanup-architecture.md`
- `docs/plans/ai-insights-automation/15-qa-translator-research.md`
