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
| `chart_spec.schema.json` | JSON Schema export of `ChartSpec`. Generated via `python -m backend.agents.insights.specs.chart_spec` (the module's `__main__` calls `dump_json_schema()`). | Frontend type-codegen (`InsightChart.tsx` validates incoming specs at runtime, optionally via Zod), and the `emit_chart` OpenAI tool spec (referenced via `$ref` per ARCHITECTURE.md A6.6). |
| `sse_events.py` | Pydantic v2 models for the 13 SSE events in ARCHITECTURE.md A5: `session_started`, `surveying`, `insight_started`, `token`, `reasoning_step`, `tool_call`, `tool_result`, `chart`, `citation`, `insight_complete`, `session_complete`, `error`, `ping`. Discriminated `SSEEvent` union + `to_sse_text()` wire-format helper. | The SSE router (`routers/insights.py`), the orchestrator emitter, the replay ring buffer (`persistence/replay.py`), and frontend `insights/sse.ts` (mirror types). |
| `skill_context.py` | Pydantic v2 `SkillContext`, `Capabilities`, `RAGContext`, `RAGRef`. Mirrors the capability matrix in SKILL_CONVERSION.md S4.3. `with_capabilities()` helper for least-privilege overrides. | Every converted skill tool (`agents/insights/skills/<name>/tool.py`), the `run_skill` dispatcher (`tools/skill.py`), and the RAG retriever. |
| `__init__.py` | Re-exports the public symbols. | Anywhere that imports from `backend.agents.insights.specs`. |

## Cross-references

- ARCHITECTURE.md §A4 ratifies ChartSpec v1.
- ARCHITECTURE.md §A5 ratifies the SSE event taxonomy.
- ARCHITECTURE.md §A6.5 + §A9 ratify the `run_skill` dispatcher and the
  ephemeral system-fragment injection that consumes a `SkillContext`.
- SKILL_CONVERSION.md §S1.2 + §S4.3 give the canonical `SkillContext`
  shape and the per-skill capability matrix.
- TASKS.md W0.5, W1.6, W6.3 are the gates that consume these schemas.

## Regenerating the JSON Schema

The on-disk `chart_spec.schema.json` is produced from the Pydantic model:

```
python -m backend.agents.insights.specs.chart_spec
```

Re-run after any change to `chart_spec.py`; the file is checked in so the
frontend type-codegen and the `emit_chart` `$ref` stay in sync without
runtime regeneration.
