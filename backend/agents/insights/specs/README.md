# `backend/agents/insights/specs/` — schema contracts

> **DO NOT MODIFY without arch sign-off.** These files are the wire and
> capability contracts between the AI Insights orchestrator, every tool
> implementation, the persistence layer, and the frontend type-codegen
> pipeline. Breaking changes here ripple to every consumer simultaneously.
> Architect must approve any field add/remove/rename or capability flip.

## Index

| File | What it is | Who imports it |
|---|---|---|
| `chart_spec.py` | Pydantic v2 `ChartSpec` v1 + sub-models (`DataSource`, `Encoding`, `Annotation`, `Styling`, axis-encoding sub-models). Hard caps: 500 rows / chart, 8 series, `chart_id` regex, kind-spec discriminator, sha256 row hash. | Backend orchestrator (`agents/insights/orchestrator.py`), `tools/emit.py`, persistence (`persistence/models.py` jsonb shape), the `run_skill` `visualization-builder` dispatcher, and the frontend type-codegen step (consumes `chart_spec.schema.json`). |
| `chart_spec.schema.json` | JSON Schema export of `ChartSpec`. Generated via `python -m backend.agents.insights.specs.chart_spec` (the module's `__main__` calls `dump_json_schema()`). | Frontend type-codegen (`InsightChart.tsx` validates incoming specs at runtime, optionally via Zod), and the `emit_chart` OpenAI tool spec (referenced via `$ref`). |
| `sse_events.py` | Pydantic v2 models for the SSE events emitted by the orchestrator: `session_started`, `surveying`, `insight_started`, `token`, `reasoning_step`, `tool_call`, `tool_result`, `chart`, `citation`, `insight_complete`, `session_complete`, `error`, `ping`. Discriminated `SSEEvent` union + `to_sse_text()` wire-format helper. | The SSE router (`routers/insights.py`), the orchestrator emitter, the OpenClaw SSE translator (`backend/openclaw/sse_translator.py`), and frontend `insights/sse.ts` (mirror types). |
| `skill_context.py` | Pydantic v2 `SkillContext`, `Capabilities`, `RAGContext`, `RAGRef`. Per-skill capability matrix; `with_capabilities()` helper for least-privilege overrides. | Every converted skill tool (`agents/insights/skills/<name>/tool.py`), the `run_skill` dispatcher (`tools/run_skill.py`), and the RAG retriever. |
| `__init__.py` | Re-exports the public symbols. | Anywhere that imports from `backend.agents.insights.specs`. |

## Cross-references

The original V1 architecture and skill-porting docs that this directory
implements were superseded after the OpenClaw / MCP migration; the
historical sections still exist in the archive for context:

- ChartSpec v1, the SSE event taxonomy, and the `run_skill` dispatcher
  with ephemeral system-fragment injection were ratified in
  [`docs/_archive/ai-insights-v1/ARCHITECTURE.md`](../../../../docs/_archive/ai-insights-v1/ARCHITECTURE.md)
  §§A4, A5, A6.5–A6.6, A9.
- The `SkillContext` shape and per-skill capability matrix come from
  [`docs/planning/ai-insights/SKILL_CONVERSION.md`](../../../../docs/planning/ai-insights/SKILL_CONVERSION.md)
  §§S1.2, S4.3 — still live as the canonical mapping.
- Today's authoritative architecture for the agent + tool plane is
  [`docs/plans/ai-insights-automation/14-unified-agent-architecture.md`](../../../../docs/plans/ai-insights-automation/14-unified-agent-architecture.md)
  and the MCP wire contract in
  [`docs/plans/ai-insights-automation/13-mcp-migration-architecture.md`](../../../../docs/plans/ai-insights-automation/13-mcp-migration-architecture.md).

## Regenerating the JSON Schema

The on-disk `chart_spec.schema.json` is produced from the Pydantic model:

```
python -m backend.agents.insights.specs.chart_spec
```

Re-run after any change to `chart_spec.py`; the file is checked in so the
frontend type-codegen and the `emit_chart` `$ref` stay in sync without
runtime regeneration.
