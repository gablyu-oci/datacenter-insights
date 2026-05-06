"""OpenClaw forwarder package.

Spec:
  - docs/plans/ai-insights-automation/11a-openclaw-migration-prd.md
  - docs/plans/ai-insights-automation/11b-openclaw-migration-architecture.md
  - docs/plans/ai-insights-automation/11c-openclaw-migration-addendum.md
  - docs/plans/ai-insights-automation/14-unified-agent-architecture.md
  - docs/plans/ai-insights-automation/15-agent-unification-cleanup-architecture.md

Modules:
  - sse_translator: pure functions translating OpenAI-shaped chat
    completion chunks into project event taxonomies
    (`agents.insights.specs.sse_events` for chat / synthesis,
    `schemas.qa` for the QA lane).
  - forwarder: `forward_chat(...)` (chat-lane SSE bytes) and
    `_drive_openclaw_stream(...)` (shared driver consumed by the
    synthesis and brief lanes).
  - qa_forwarder: `iter_qa_events(...)` (QA-lane events) and
    `forward_qa(...)` (QA-lane SSE bytes), both consumed by
    `agents/datacenter_qa.py` and `agents/triangulation_qa.py`.

All chat / QA / synthesis traffic is OpenClaw-only as of ARCH 15.
The legacy in-process `ToolLoopDriver` lane and its rollback flag
were removed at the same time.
"""
