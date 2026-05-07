# Documentation index

Eight living documents drive the project. Read in this order; each later doc assumes context from earlier ones.

| # | Document | Purpose |
|---|---|---|
| 1 | [`PRD.md`](PRD.md) | Product spec — goals, users, pillars, phased scope, success metrics. |
| 2 | [`planning/00-DECISIONS-AND-CONSTRAINTS.md`](planning/00-DECISIONS-AND-CONSTRAINTS.md) | Locked decisions, locked tech stack, dataset inventory, EDGAR endpoints, UX hard rule, **role model** (§5.1), **Phase-1 MVP source set** (§5.2). Single source of truth for all constraints. |
| 3 | [`OPEN-TENSIONS.md`](OPEN-TENSIONS.md) | **Read alongside #2.** Trade-offs deliberately deferred (APScheduler vs Dagster, VM filesystem vs Object Storage, rapidfuzz vs multi-signal LLC resolver, Sentinel-2 vs Maxar, Aterio one-time vs licensed feed, transcript-grade GPU inference). Each lists its trigger to revisit. |
| 4 | [`research/DATA_SOURCE_LANDSCAPE_REPORT.md`](research/DATA_SOURCE_LANDSCAPE_REPORT.md) | Vendor / data-source landscape with cost, cadence, feasibility, ranked recommendations per pillar. |
| 5 | [`planning/02-TECH-STACK-RESEARCH.md`](planning/02-TECH-STACK-RESEARCH.md) | Tech-stack evaluation per area (EDGAR ingestion, permits, transcripts, satellite, storage, entity res, scheduling). Summary Decision Matrix is **locked** per doc #2. |
| 6 | [`planning/03-architecture-design.md`](planning/03-architecture-design.md) | Backend app architecture — APIRouter modules, ADRs, migration path from current `main.py`, canonical schema (sites + events + energy_projects + companies + aliases + **`site_company_associations` role edges**), **canonical role-parameterized OCI %-share computation**. |
| 7 | [`planning/03-PIPELINE-ARCHITECTURE.md`](planning/03-PIPELINE-ARCHITECTURE.md) | Data-pipeline architecture — adapter contract, per-source adapters, scheduler, full DB schema, data state machine, NoVA Phase-1 cut, **§7.5 Generator-permit pipeline (parallel L4 enrichment with EPA ECHO + state air APIs + multi-signal LLC→parent resolver)**. |
| 8 | [`planning/04-ux-evolution-plan.md`](planning/04-ux-evolution-plan.md) | UX additive plan — Companies tab + Company detail page, Site detail role-breakdown card, OCI %-share KPI tile with **role toggle**, Energy Supply tab, Events Timeline, broken-UI fix list, design tokens, error/empty/loading states. |

## Archived (`_archive/`)

Eight earlier drafts are kept under `_archive/` for reference but are no longer authoritative. They were superseded after the 2026-04-28 consolidation pass:

- `requirements.md` — superseded by `PRD.md`
- `00-master-plan-index.md` / `00-DATA-PIPELINE-PLAN-INDEX.md` — stale index files for two parallel doc tracks; this `README.md` replaces both
- `01-architecture-evolution-prd.md` / `01-DATA-PIPELINE-PRD.md` — track-specific PRDs; content folded into `PRD.md`
- `02-tech-stack-research.md` (lowercase) — smaller cousin of `02-TECH-STACK-RESEARCH.md`; matrix preserved in `00-DECISIONS-AND-CONSTRAINTS.md` §2.1
- `04-UX-DATA-STATES.md` — subset of `04-ux-evolution-plan.md`
- `DATA_INGESTION_ARCHITECTURE.md` — superseded by `03-PIPELINE-ARCHITECTURE.md`

If you need anything from the archive, copy out — don't link to `_archive/` from a living doc.
