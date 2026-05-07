# Documentation index

This is a living directory. The files below describe the system as it
is shipped today (2026-05-07). Older or replaced documents live under
[`_archive/`](_archive/) and are not authoritative.

## 1. Product & constraints

| # | Document | Purpose |
|---|---|---|
| 1 | [`PRD.md`](PRD.md) | Product spec — goals, users, pillars, phased scope, success metrics. |
| 2 | [`planning/00-DECISIONS-AND-CONSTRAINTS.md`](planning/00-DECISIONS-AND-CONSTRAINTS.md) | Locked decisions, locked tech stack, dataset inventory, EDGAR endpoints, UX hard rule, **role model** (§5.1), **Phase-1 MVP source set** (§5.2). Single source of truth for all constraints. |
| 3 | [`OPEN-TENSIONS.md`](OPEN-TENSIONS.md) | **Read alongside #2.** Trade-offs deliberately deferred (APScheduler vs Dagster, VM filesystem vs Object Storage, rapidfuzz vs multi-signal LLC resolver, Sentinel-2 vs Maxar, Aterio one-time vs licensed feed, transcript-grade GPU inference). Each lists its trigger to revisit. |

## 2. Architecture & tech stack

| # | Document | Purpose |
|---|---|---|
| 4 | [`research/DATA_SOURCE_LANDSCAPE_REPORT.md`](research/DATA_SOURCE_LANDSCAPE_REPORT.md) | Vendor / data-source landscape with cost, cadence, feasibility, ranked recommendations per pillar. |
| 5 | [`planning/02-TECH-STACK-RESEARCH.md`](planning/02-TECH-STACK-RESEARCH.md) | Tech-stack evaluation per area (EDGAR ingestion, permits, transcripts, satellite, storage, entity res, scheduling). Summary Decision Matrix is **locked** per doc #2. |
| 6 | [`planning/03-architecture-design.md`](planning/03-architecture-design.md) | Backend app architecture — APIRouter modules, schema (sites / events / energy_projects / companies / aliases / `site_company_associations` role edges), canonical role-parameterized OCI %-share computation. |
| 7 | [`planning/03-PIPELINE-ARCHITECTURE.md`](planning/03-PIPELINE-ARCHITECTURE.md) | Data-pipeline architecture — adapter contract, per-source adapters, scheduler, full DB schema, data state machine, NoVA Phase-1 cut, **§7.5 Generator-permit pipeline (parallel L4 enrichment with EPA ECHO + state air APIs + multi-signal LLC→parent resolver)**. |
| 8 | [`planning/04-ux-evolution-plan.md`](planning/04-ux-evolution-plan.md) | UX additive plan — Companies tab + Company detail page, Site detail role-breakdown card, OCI %-share KPI tile with **role toggle**, Energy Supply tab, Events Timeline, broken-UI fix list, design tokens, error/empty/loading states. |

## 3. Phase-2 ingestion (shipped)

| Document | Purpose |
|---|---|
| [`planning/PHASE2_RESEARCH.md`](planning/PHASE2_RESEARCH.md) | Authoritative endpoint catalog (URLs, formats, env-var overrides) for ERCOT / MISO / Iowa / Ohio / IR-press-release adapters. The README's "Phase 2 — What's Ingested" section cites this. |
| [`planning/SUPPLIER_VENDOR_SCOPE.md`](planning/SUPPLIER_VENDOR_SCOPE.md) | Vendor curation list (3-7 vendors per tab) for the supplier dropdowns. |

## 4. AI Insights automation + OpenClaw + MCP (shipped)

The synthesis automation, the OpenClaw unified-agent gateway, and the
MCP tool-routing migration are all designed and tracked under
[`plans/ai-insights-automation/`](plans/ai-insights-automation/). Reading
order if you're new to the AI Insights subsystem:

| # | Document | Status |
|---|---|---|
| 1 | [`plans/ai-insights-automation/00-index.md`](plans/ai-insights-automation/00-index.md) | Index across the AI-Insights plan series. |
| 2 | [`plans/ai-insights-automation/01-prd.md`](plans/ai-insights-automation/01-prd.md) | PRD baseline (synthesis + chat + supply-demand-gap). |
| 3 | [`plans/ai-insights-automation/02-research.md`](plans/ai-insights-automation/02-research.md) · [`03-architecture.md`](plans/ai-insights-automation/03-architecture.md) · [`04-ux.md`](plans/ai-insights-automation/04-ux.md) | Research / architecture / UX foundations. |
| 4 | [`plans/ai-insights-automation/04a-ux-delta-phase4-implementation.md`](plans/ai-insights-automation/04a-ux-delta-phase4-implementation.md) | UX delta: Run-again button, Auto-generated badge. |
| 5 | [`plans/ai-insights-automation/05-prd-addendum-phase4-and-supply-demand.md`](plans/ai-insights-automation/05-prd-addendum-phase4-and-supply-demand.md) · [`06-supply-demand-gap-adr.md`](plans/ai-insights-automation/06-supply-demand-gap-adr.md) | Phase 4 frontend rework + supply/demand-gap pattern. |
| 6 | [`plans/ai-insights-automation/08-v1.1-agentic-plan.md`](plans/ai-insights-automation/08-v1.1-agentic-plan.md) | V1.1 agentic ToolLoopDriver (deferred plan). |
| 7 | [`plans/ai-insights-automation/11-openclaw-deployment.md`](plans/ai-insights-automation/11-openclaw-deployment.md) · [`11a-openclaw-migration-prd.md`](plans/ai-insights-automation/11a-openclaw-migration-prd.md) · [`11b-openclaw-migration-architecture.md`](plans/ai-insights-automation/11b-openclaw-migration-architecture.md) · [`11c-openclaw-migration-addendum.md`](plans/ai-insights-automation/11c-openclaw-migration-addendum.md) · [`12-openclaw-test-plan.md`](plans/ai-insights-automation/12-openclaw-test-plan.md) | OpenClaw gateway deployment + migration. |
| 8 | [`plans/ai-insights-automation/13-mcp-migration.md`](plans/ai-insights-automation/13-mcp-migration.md) (ADR-13) + the four `13-mcp-migration-*.md` companions | MCP server migration. |
| 9 | [`plans/ai-insights-automation/14-unified-agent-prd.md`](plans/ai-insights-automation/14-unified-agent-prd.md) + `14-unified-agent-{research,architecture,smoke}.md` | OpenClaw Phase 2-5 unification (chat + synthesis + brief on one driver). |
| 10 | [`plans/ai-insights-automation/15-agent-unification-cleanup-prd.md`](plans/ai-insights-automation/15-agent-unification-cleanup-prd.md) + `15-{architecture,qa-translator-research,extraction-vs-agent-policy}.md` | Cleanup PRD: drop `openclaw_enabled`, externalize prompts, formalize the LLM-call placement policy. |

The skill-porting reference for `backend/agents/insights/skills/` is
[`planning/ai-insights/SKILL_CONVERSION.md`](planning/ai-insights/SKILL_CONVERSION.md).
The other V1 ai-insights planning docs (PRD / RESEARCH / ARCHITECTURE /
UX / TASKS / V1_KICKOFF / RESEARCH_ADDENDUM / DESIGN_TOKENS_AUDIT) were
superseded by the `plans/ai-insights-automation/` track and now live
under [`_archive/ai-insights-v1/`](_archive/ai-insights-v1/).

## 5. QA / demo / research

| Document | Purpose |
|---|---|
| [`qa/phase-1b-qa-report.md`](qa/phase-1b-qa-report.md) | Phase 1B QA snapshot. |
| [`planning/DEMO_BRIEF_2026-05-01.md`](planning/DEMO_BRIEF_2026-05-01.md) | Frozen artifact of the 2026-05-02 demo (numbers correct as of 2026-05-01). |
| [`planning/STAKEHOLDER_REQUIREMENTS_AUDIT.md`](planning/STAKEHOLDER_REQUIREMENTS_AUDIT.md) | 30-requirement audit snapshot from 2026-04-30. |
| [`research/vitest-setup.md`](research/vitest-setup.md) | Vitest 4.1+ setup recipe for Vite 8 / React 19. |

## 6. Archived (`_archive/`)

Earlier drafts kept for reference. **Do not link to `_archive/` from a living doc — copy the content out instead.**

| Folder / file | Why archived |
|---|---|
| `_archive/ai-insights-v1/` | Eight V1-plan docs (PRD, RESEARCH, ARCHITECTURE, UX, TASKS, V1_KICKOFF, RESEARCH_ADDENDUM_2026-05-04, DESIGN_TOKENS_AUDIT) — superseded by `plans/ai-insights-automation/`. Archived 2026-05-07. |
| `_archive/ai-insights-automation/` | Five executed-and-shipped planning docs (`05-phase2-3-handoff`, `07-qa-test-plan-phase4`, `08-prd-phase4-followups`, `09-arch-phase4-followups`, `10-openclaw-integration-evaluation` whose ADR-010 SKIP decision was reversed by 11a). Archived 2026-05-07. |
| `_archive/requirements.md` | Superseded by `PRD.md`. |
| `_archive/00-master-plan-index.md` / `_archive/00-DATA-PIPELINE-PLAN-INDEX.md` | Stale index files for two parallel doc tracks; this `README.md` replaces both. |
| `_archive/01-architecture-evolution-prd.md` / `_archive/01-DATA-PIPELINE-PRD.md` | Track-specific PRDs; content folded into `PRD.md`. |
| `_archive/02-tech-stack-research.md` (lowercase) | Smaller cousin of `02-TECH-STACK-RESEARCH.md`; matrix preserved in `00-DECISIONS-AND-CONSTRAINTS.md` §2.1. |
| `_archive/04-UX-DATA-STATES.md` | Subset of `04-ux-evolution-plan.md`. |
| `_archive/DATA_INGESTION_ARCHITECTURE.md` | Superseded by `03-PIPELINE-ARCHITECTURE.md`. |
