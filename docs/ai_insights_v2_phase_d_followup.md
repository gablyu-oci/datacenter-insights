# AI Insights v2 — Phase D Follow-up: v1 Deletion Plan

**Status:** Plan, not yet executed
**Cutover date:** 2026-05-07 (today — v2 became the default for `POST /api/insights/sessions`)
**Sunset date:** 2026-05-21 (14-day soak per spec §8 Phase D)
**Owner:** gabrielle.lyu

## Why this doc exists

Phase D flipped the default for `POST /api/insights/sessions` from `v1` to `v2`. **v1 code paths remain fully reachable** during a 2-week soak window. Spec §8 calls for deleting v1 once v2 has run cleanly as the default in production. **Do not execute the deletion yet.** Use this document as the runbook on or after 2026-05-21, after the gate criteria below are satisfied.

## Pre-deletion gate criteria

All five must be true before any of the deletions in this document are performed:

1. **Soak elapsed.** ≥ 14 calendar days have passed since 2026-05-07.
2. **Latency.** v2 p95 wall-clock ≤ 900s, p50 ≤ 480s on the production session log over the last 7 days (spec §13).
3. **Bug count.** Zero unresolved bugs filed against v2 in the last 5 days.
4. **Stakeholder sign-off.** Explicit go from gabrielle.lyu in writing.
5. **DB sanity check.** Run before deletion:
   ```sql
   SELECT version, count(*) FROM agent_session GROUP BY version;
   SELECT version, count(*) FROM ai_insight     GROUP BY version;
   ```
   Confirm v1 row counts have stopped growing in the last 5 days. (Existing v1 rows remain readable after deletion — only the codepath that produced them is removed.)

## Files to delete

```
backend/agents/insights/hypothesizer.py
backend/agents/insights/prompts/synthesis_rules.md
```

## Functions / blocks to delete (in-file)

| File | What to remove |
|---|---|
| `backend/agents/insights/orchestrator.py` | `_chart_from_supporting_rows()` and the v1 phase-A bootstrap that calls `build_factpack`. The v2 path already short-circuits both via the `session.version` gate added in Phase C. |
| `backend/agents/insights/agentic_synthesis.py` | The `version == 'v1'` branch of `run_agentic_synthesis`; the FactPack-driven `user_pack` builder; the helper `_factpack_digest`; the parameter `version` becomes a no-op (default `v2`, and v1 raises). |
| `backend/agents/insights/tools/registry.py` | The `V1_TOOL_DEFS` table and the version-keyed dispatch shim added in Phase C — collapse to a single `TOOL_DEFS` table holding the v2 surface. |
| `backend/routers/insights.py` | `_v1_deprecation_headers`, `V1_SUNSET_HTTP_DATE`, the `JSONResponse`-with-headers branches in `create_session` and `get_session`, the `version` field constraint allowing `v1`. After deletion, `version` accepts only `v2` (or the field can be dropped entirely if no client is sending it). |

## Tests to delete

```
backend/tests/test_hypothesizer_factpack.py
backend/tests/test_hypothesizer_supply_demand_sections.py
backend/tests/test_orchestrator_supporting_row_ids.py
```

Plus the v1 portions of the parallel-version tests added in Phase C / D:

| File | What to remove |
|---|---|
| `backend/tests/test_agentic_synthesis_v2.py` | The `test_*_v1_*` cases that assert the v1 branch is byte-identical. |
| `backend/tests/test_registry_v2.py` | The `V1_TOOL_DEFS` snapshot test. |
| `backend/tests/test_phase_d_router_cutover.py` | The two `*_v1_*` tests that assert the Deprecated/Sunset header surface. |

Also grep `backend/tests/` for `factpack` and `synthesis_rules\.md` references and remove or migrate any remaining v1-only assertions:

```bash
grep -rl 'factpack\|synthesis_rules\.md' backend/tests/
```

## Code to keep but update

- `backend/agents/insights/db/models.py` — keep the v1 columns on `ai_insight` (`chart_type`, `chart_y_label`, `supporting_row_ids`). They will hold historical v1 rows. Document them as "legacy, written by v1 only, do not write from v2" in the model docstring.
- Migration 018 — keep. Adds the v2 columns and is forward-looking only.
- Existing v1 rows in `agent_session` and `ai_insight` — leave intact for audit trail. The frontend renderers must continue to read v1 rows correctly (they do: `chart_y_label` is optional in the frontend types).

## Deletion runbook

Run these commands in order once the gate criteria pass:

```bash
# 1. DB sanity check (read the output, do not skip).
psql "$DATABASE_URL" -c "SELECT version, count(*) FROM agent_session GROUP BY version;"
psql "$DATABASE_URL" -c "SELECT version, count(*) FROM ai_insight     GROUP BY version;"

# 2. Delete v1 source files.
git rm backend/agents/insights/hypothesizer.py
git rm backend/agents/insights/prompts/synthesis_rules.md

# 3. Delete v1 tests.
git rm backend/tests/test_hypothesizer_factpack.py
git rm backend/tests/test_hypothesizer_supply_demand_sections.py
git rm backend/tests/test_orchestrator_supporting_row_ids.py

# 4. Hand-edit (use your IDE) the files in §"Functions / blocks to delete"
#    and §"Code to keep but update". Each is a surgical removal — no
#    refactor at this step.

# 5. Run the suite. Should still be ≥ 380 passed.
CLAUDECODE=0 python3 -m pytest backend/tests/ --tb=short

# 6. Run the frontend suite (no frontend changes are required, but the
#    Tracked-questions sidebar tests still need to be green).
cd frontend && npm test -- --run

# 7. Commit.
git commit -m "Phase D follow-up: delete v1 AI Insights code paths

Spec §8 Phase D — 14-day soak elapsed; v2 has been the default since
2026-05-07 and stakeholder sign-off (gabrielle.lyu) is recorded.
"
```

## Rollback plan if v2 has problems during the soak

If a critical issue emerges between 2026-05-07 and 2026-05-21:

1. Flip `CreateSessionBody.version` default back to `"v1"` (one-line change).
2. Keep the `Deprecated`/`Sunset` headers off until the issue is resolved.
3. Open a v2-blocker issue and extend the soak by the time-to-fix.

The absence of any deletion in this run is what makes that rollback cheap — no schema changes required, no removed code to restore.

## Migration concerns

There are **no schema migrations** required for the deletion. Migration 018 (Phase C) added v2 columns as nullable; Phase A artefacts (SCHEMA.md, FRESHNESS.md, MEMORY.md) are file-system only. Existing v1 rows continue to read correctly because the v1 columns are not dropped.

If at some later point we want to also remove the v1 columns themselves, that is a **separate** archive-and-truncate migration that must be planned with stakeholder approval and is explicitly **out of scope** for the soak deletion.

## Out of scope for this follow-up

- Removing OpenClaw chat handlers (§5 of `routers/insights.py` — `/insights/{id}/chat`). Those are V2 chat surfaces, not the v1 SYNTHESIS surfaces this doc tracks.
- Compaction or archival of historical v1 rows.
- Frontend cleanup for v1-only fields (`chart_y_label`, etc) — leave for a later UI-tidy pass.

## Cross-references

- `docs/ai_insights_v2_spec.md` §8 Phase D
- `docs/ai_insights_v2_phases_bcd_prd.md` § Phase D acceptance criteria
- `docs/ai_insights_v2_phases_bcd_architecture.md` § Phase D
- `docs/ai_insights_v2_phase_c_report.md` § v1 byte-identity confirmation

---

**Reminder:** This document is a *plan*. As of 2026-05-07, no deletions have occurred. v1 sessions remain fully functional and well-supported.
