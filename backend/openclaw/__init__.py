"""OpenClaw chat-runtime forwarder package.

Spec:
  - docs/plans/ai-insights-automation/11a-openclaw-migration-prd.md
  - docs/plans/ai-insights-automation/11b-openclaw-migration-architecture.md
  - docs/plans/ai-insights-automation/11c-openclaw-migration-addendum.md

Modules:
  - sse_translator: pure functions translating OpenAI-shaped chat
    completion chunks (the on-the-wire shape OpenClaw emits per
    ADDENDUM 11c §B) into the project's existing SSE event taxonomy
    (`agents.insights.specs.sse_events`).
  - forwarder: async function `forward_chat(...)` that POSTs the
    user message to OpenClaw's `/v1/chat/completions`, streams the
    SSE response, runs each chunk through the translator, and
    write-throughs to Postgres `agent_message`.

This package is the OpenClaw lane of the chat path. The legacy
in-process `agents.insights.tool_loop.ToolLoopDriver` lane is the
rollback target (per PRD R9) and is not removed.
"""
