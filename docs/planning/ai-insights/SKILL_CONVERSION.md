# SKILL_CONVERSION — Claude-Code Skills → Llama-Stack Tool Functions
**Owner:** Skill engineer · **Stakeholder:** Karan (via PM)
**Status:** Draft v0.1 · **Date:** 2026-05-04
**Cross-refs:** [`./PRD.md`](./PRD.md) · [`./RESEARCH.md`](./RESEARCH.md) · [`./ARCHITECTURE.md`](./ARCHITECTURE.md) · [`./TASKS.md`](./TASKS.md)

> Planning document. Schemas, signatures, and pseudocode only. No implementation code lands here.

---

## S1. Overview

### S1.1 Strategy (carried forward from RESEARCH §4)

Adopted: **pattern (a) — each skill = one OpenAI tool function (namespaced under the single platform tool `run_skill(skill_name, inputs)`)**, with Process loaded as an *ephemeral* system fragment only when invoked, deterministic Python (the skill's `scripts/`) called as the body of the tool, and `references/` chunked into a per-skill RAG store.

Rejected (RESEARCH §4):
- Pattern (b) sub-agents — recursive agent calls disallowed (PRD §5.1).
- Pattern (c) prompt-stuff all skills — token waste + drift.

### S1.2 One-way port

```
~/.claude/skills/<skill_name>/                  ──[port]──▶  backend/agents/insights/skills/<skill_name>/
   SKILL.md   (frontmatter + Process)                            tool.py             (function callable from run_skill)
   scripts/*.py (stdlib + pandas + numpy)                        system_fragment.md  (≤800-token Process distillation)
   references/*.md                                               rag_chunks.jsonl    (chunked + embedded references/)
   assets/* (templates)                                          assets/             (copy-through if used; mostly unused)
```

The source tree is **read-only**. Every conversion writes new files under `backend/agents/insights/skills/`. Re-running the conversion is idempotent (controlled by `SKILL.md` content-hash).

### S1.3 Per-skill artifacts

| Output file | Required | Notes |
|---|---|---|
| `tool.py` | yes | Async function `skill_<name>(*, inputs, ctx) -> Output`. Wraps deterministic preprocessing if any. |
| `system_fragment.md` | yes | ≤800 tokens. Distilled Process steps, Claude-Code-isms removed. |
| `rag_chunks.jsonl` | if `references/` non-empty | One line per chunk; embedded by an offline indexer command. |
| `inputs.py` | yes | Pydantic `<Skill>Inputs` model. |
| `outputs.py` | yes | Pydantic `<Skill>Output` model. |
| `assets/` | if templates used | Copy-through verbatim. Mostly empty in our list because we don't render Claude-Code report templates. |

---

## S2. Source-skill anatomy

A representative skill (verified by reading `programmatic-eda`, `data-quality-audit`, `time-series-analysis`, `visualization-builder`, `insight-synthesis` SKILL.md files) is shaped like:

| Section | Format | Example |
|---|---|---|
| Frontmatter | YAML — `name`, `description` | `name: programmatic-eda` |
| `# When to use` | bulleted predicates | "You receive a new dataset and need to understand its shape and quality" |
| `# Process` | Numbered steps. Each step often references a `scripts/<file>.py` to run | "1. Load and overview — run `scripts/data_overview.py`…" |
| `# Inputs the skill needs` | required + optional list | "Required: dataset path (CSV / Parquet / Excel) or DataFrame already in scope" |
| `# Output` | template files + console output | "`assets/eda_report_template.md` (filled)…" |

**`scripts/` conventions:**
- Pure Python.
- Stdlib + `pandas` + `numpy` only (rule confirmed across the catalog; `time-series-analysis` extends with `statsmodels`/ARIMA — that's an exception we'll address per-skill).
- argv-driven; output goes to stdout (often JSON or a markdown table).
- File-path-centric: scripts assume `--input data.csv` style I/O.

**`references/`:** prose markdown, ~2–10 KB each. Stable enough to embed once per release.

**`assets/`:** templates the skill fills out (`.md`, `.html`, `.yaml`). Most are Claude-Code-specific report shapes we don't reuse — see S5.

**Why "stdlib + pandas + numpy ONLY" matters:** the FastAPI side already has `pandas` and `numpy` in `backend/requirements.txt`. **No new Python deps needed for V1**, except `statsmodels` (for `time-series-analysis` ARIMA) and the existing `sqlglot` (for the SQL gate). `pgvector`/`psycopg` are already in the stack.

---

## S3. Target-runtime anatomy

### S3.1 LlamaStack tool surface
Per ARCHITECTURE A6.5, the agent's *only* tool for skill access is `run_skill(skill_name, inputs)`. The `skill_name` is an enum (closed set of 15). The dispatcher (`tools/skill.py`) looks up the skill in `skills/_registry.py` and calls the underlying `tool.py::skill_<name>(inputs, ctx)`.

This means the *agent* sees one tool but in practice has 15 *namespaced subroutines*. Token cost benefit: only one tool spec in the always-on tool list, not 15.

### S3.2 Inputs / outputs
Both typed via Pydantic (one model per skill, declared in the skill's `inputs.py` + `outputs.py`). The dispatcher serializes inputs to JSON before the model call (so it appears in the OpenAI function-call args), parses outputs back to JSON for the model to chain with.

### S3.3 System fragment — ephemeral injection
Per ARCHITECTURE A9.3: when `run_skill(X)` is called, a `{"role":"system"}` message containing the X process fragment + top-3 RAG chunks is inserted into the conversation between the tool result and the next assistant turn. Not pinned. Removed on the turn after.

### S3.4 RAG store
Per ARCHITECTURE A7 + S6 below: single `skill_rag_chunk` pgvector table with `skill_name` as a filter column. Embedding model `oci/openai.text-embedding-3-large` (already in `backend/llm/client.py`'s `MODELS`).

---

## S4. Per-skill mapping table (THE CORE DELIVERABLE)

### S4.1 Reconciliation against installed catalog

The PRD §6 cut assumed a "standard data-analytics skill catalog" not directly enumerable at PRD time. Now that we've enumerated `~/.claude/skills/`:

**Installed: 33 data-analytics skills + `dev-team` (excluded).** Specifically:
```
ab-test-analysis, analysis-assumptions-log, analysis-documentation,
analysis-planning, analysis-qa-checklist, analysis-retrospective,
business-metrics-calculator, cohort-analysis, context-packager,
dashboard-specification, data-catalog-entry, data-narrative-builder,
data-quality-audit, executive-summary-generator, funnel-analysis,
impact-quantification, insight-synthesis, methodology-explainer,
metric-reconciliation, metric-reconciliation-docs, peer-review-template,
programmatic-eda, query-validation, root-cause-investigation,
schema-mapper, schema-mapper-docs, segmentation-analysis,
semantic-model-builder, sql-to-business-logic,
stakeholder-requirements-gathering, technical-to-business-translator,
time-series-analysis, visualization-builder
```

**Deltas vs PRD §6:**

| PRD-named | Installed? | Action |
|---|---|---|
| `programmatic-eda` | yes | keep |
| `data-quality-audit` | yes | keep |
| `root-cause-investigation` | yes | keep |
| `time-series-analysis` | yes | keep |
| `segmentation-analysis` | yes | keep |
| `cohort-analysis` | yes | keep V2 |
| `business-metrics-calculator` | yes | keep |
| `insight-synthesis` | yes | keep |
| `executive-summary-generator` | yes | keep |
| `visualization-builder` | yes | keep (prompt-only port) |
| `data-narrative-builder` | yes | keep |
| `impact-quantification` | yes | keep |
| `methodology-explainer` | yes | keep V2 |
| `technical-to-business-translator` | yes | keep |
| `peer-review-template` | yes | keep V2 |
| `ab-test-analysis` | yes (installed) | drop (PRD §6: no A/B context) |
| `funnel-analysis` | yes (installed) | drop (PRD §6: no funnel) |
| `statistical-test-selection` | **not installed** | drop (vacuous — never existed) |
| `correlation-vs-causation` | **not installed** | drop (vacuous) |
| `sql-query-builder` | **not installed** (closest: `query-validation`, `sql-to-business-logic`) | PRD-listed as drop; agree |
| `dashboard-design` | **not installed** (closest: `dashboard-specification`) | drop |
| `kpi-tree` | **not installed** | drop (vacuous) |
| `data-cleaning` | **not installed** | drop (vacuous) |
| `missing-data-imputation` | **not installed** | drop (vacuous; also PRD §S5 forbids imputation) |
| `outlier-detection` | **not installed** (handled in `programmatic-eda` step 3) | drop (PRD §6: covered by anomaly_detector + EDA) |
| `geospatial-analysis` | **not installed** | drop V1; reconsider V3 |
| `forecasting` | **not installed** (partial coverage in `time-series-analysis`) | drop (PRD non-goal) |
| `churn-analysis` | **not installed** | drop |
| `pricing-analysis` | **not installed** | drop |
| `survey-analysis` | **not installed** | drop |
| `nps-analysis` | **not installed** | drop |
| `marketing-attribution` | **not installed** | drop |
| `customer-lifetime-value` | **not installed** | drop |

**Newly visible (installed, NOT in PRD §6):** see S10 — these are the documentation/process skills (`analysis-*`, `schema-mapper`, `semantic-model-builder`, `sql-to-business-logic`, `query-validation`, `context-packager`, `dashboard-specification`, `metric-reconciliation`, `data-catalog-entry`, `stakeholder-requirements-gathering`).

**Final keep count: 15** — matches PRD §6.3. **Reconciliation: clean** for the kept 15. Drop list rationalised in S10.

### S4.2 The 15 keeps

Legend: `script ports` lists at least one concrete `scripts/` filename from the source repo (where present); these become functions in `tool.py`.

| # | Skill | Phase | Tool fn name | Inputs (sketch) | Output (sketch) | scripts/ → Python module fn | system_fragment summary | RAG | Notes / risks |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `programmatic-eda` | V1 | `skill_programmatic_eda` | `{rows: list[dict], grain: str, sample_size: int = 10000, columns: list[str] \| None = None}` | `{n_rows, n_cols, dtypes:{col:type}, null_density:{col:pct}, outliers:[{col, idx_count, method}], distributions:{col:{mean,std,p50,p90}}, correlations:[{a,b,r}], top_issues:list[str]}` | `data_overview.py` → `overview()`; `null_profiler.py` → `null_profile()`; `outlier_detector.py` → `iqr_z_outliers()`; `distribution_summary.py` → `distribution_summary()`; `correlation_explorer.py` → `correlations()` | "Profile a frame: shape → nulls → outliers → distributions → correlations → top-issues. Use `eda_checklist` to gate completion." | yes (eda_checklist, quality_thresholds, pandas_polars_recipes) | Source assumes CSV path; we pass `rows` (list of dicts) instead — see S5 |
| 2 | `data-quality-audit` | V1 | `skill_data_quality_audit` | `{rows: list[dict], schema_relations: list[{child_col, parent_table, parent_col}], business_rules: list[{col, rule}], freshness_sla_days: int}` | `{null_audit, duplicates, referential_integrity, value_range_violations, freshness, severity_summary}` | `null_counter.py` → `count_nulls()`; `duplicate_finder.py` → `find_duplicates()`; `referential_integrity.py` → `check_fk()`; `value_range_validator.py` → `validate_ranges()`; `freshness_check.py` → `freshness_check()` | "Audit a frame against business rules: nulls → dupes → FKs → ranges → freshness; classify each finding by quality_dimension." | yes (quality_dimensions, business_rule_patterns) | `referential_integrity` needs *both* tables in scope; in our context this means two `query_database` calls upstream; the dispatcher takes both as inputs |
| 3 | `root-cause-investigation` | V1 | `skill_root_cause_investigation` | `{anomaly: {metric, baseline, observed, period}, segment_axes: list[str], rows: list[dict]}` | `{drilldowns: [{axis, segment, contribution_pct, evidence}], hypotheses: [{statement, support, refute}], recommended_followups: list[str]}` | `drilldown_analyzer.py` → `drilldown()` | "5-whys + segment drilldown; produce ranked candidate explanations with quantitative support." | yes (rca_framework, hypothesis_testing_guide) | The "anomaly" handle is typically a row from `anomaly_detector` — agent fetches via `call_api('/api/anomalies/recent')` first |
| 4 | `time-series-analysis` | V1 | `skill_time_series_analysis` | `{rows: list[dict], date_col: str, value_col: str, granularity: "day"\|"week"\|"month", forecast_horizon: int = 0}` | `{trend_strength: float, seasonal_strength: float, anomalies: [{date, value, z}], forecast: [{date, point, lo95, hi95}] \| null, mape: float \| null}` | `ts_analyzer.py` → `analyze()` (decompose + ADF + anomaly + ARIMA) | "Decompose → ADF → anomaly z-score → optional ARIMA forecast with MAPE on 20% holdout." | yes (ts_patterns_guide) | **Adds `statsmodels` dep.** Decision: yes, add to `backend/requirements.txt` — single new dep is acceptable. Forecast horizon defaults to 0 to keep PRD non-goal (no forecasting) intact; opt-in only |
| 5 | `segmentation-analysis` | V1 | `skill_segmentation_analysis` | `{rows: list[dict], segment_col: str, metric_cols: list[str], k_clusters: int \| null = null}` | `{segments: [{key, n, metrics:{col:{mean,p50,p90,share}}}], divergent_segments: list[str]}` | `segmentation_runner.py` → `segment()` | "Group rows by segment_col (or k-means if no col), summarise metric_cols per group, surface divergent groups." | yes (segmentation_approaches) | k-means uses pandas/numpy only (manual); no scikit-learn dep |
| 6 | `business-metrics-calculator` | V1 | `skill_business_metrics_calculator` | `{rows: list[dict], metric: str, group_by: list[str] \| null = null, period: str \| null = null}` | `{metric_name, value, components: dict, group_breakdown: list[{key, value}]}` | `saas_metrics.py` → `compute_metric(name, df, ...)` | "Standardise computation of named metrics (gw_per_state_per_quarter, contracted_share_renewable, etc.)." | yes (metric_definitions) | **Risk:** source skill is SaaS-flavoured (MRR, ARR). For our domain we extend the metric library to power/permit metrics — see S11 |
| 7 | `insight-synthesis` | V1 | `skill_insight_synthesis` | `{findings: list[{statement, evidence}], audience: "exec"\|"analyst", business_context: str}` | `{insights: [{headline, so_what, why, now_what, impact_estimate, confidence}]}` | (no script — prompt-only) | "Apply So-What/Why/Now-What to each finding; quantify impact; prioritise by impact × confidence × actionability." | yes (insight_framework, prioritization_guide) | Pure prompt skill; deterministic part is the typed schema |
| 8 | `executive-summary-generator` | V1 | `skill_executive_summary_generator` | `{insights: list[Insight], audience: "ceo"\|"vp"\|"director"}` | `{summary: str, top_3_takeaways: list[str], call_to_action: str}` | (no script) | "Compress N insights into a 5-line exec summary; lead with materiality; remove jargon." | yes | Tone calibration matters; flagged for dogfood |
| 9 | `visualization-builder` | V1 | `skill_visualization_builder` | `{data_shape: {n_rows, columns:[{name,type,distinct_n}]}, message: str, target: ChartType \| null}` | `{recommended_type: ChartType, encoding: {x:{field,type}, y:{field,type}, series?:{field}}, rationale: str}` | (`chart_builder.py` NOT ported — matplotlib-bound) | "Pick the chart type from the closed Recharts set given data shape + message; encode x/y/series; never recommend a map in V1." | yes (chart_selection_guide, visual_design_principles) | **Prompt-only port** — the matplotlib script is intentionally not converted; the deterministic check is a JSON-Schema validator on the proposed encoding before the agent emits a full ChartSpec |
| 10 | `data-narrative-builder` | V1 | `skill_data_narrative_builder` | `{insight: Insight, chart_spec: ChartSpec, audience: str}` | `{headline: str, body_md: str, caption: str}` | (no script) | "Stitch insight + chart + caption into a 1-paragraph card body; no jargon; lead with the number." | yes | — |
| 11 | `impact-quantification` | V1 | `skill_impact_quantification` | `{claim: str, supporting_rows: list[dict], unit: "GW"\|"USD"\|"count"\|"%"}` | `{impact_value: float, impact_unit: str, range_lo: float, range_hi: float, basis: str}` | (no script) | "Convert a qualitative claim to a quantitative magnitude with a range; cite the rows the magnitude rests on." | no | Used during materiality scoring |
| 12 | `technical-to-business-translator` | V1 | `skill_technical_to_business_translator` | `{technical_statement: str, audience: "exec"\|"analyst", glossary_hints: dict}` | `{business_statement: str, lost_precision_flag: bool}` | (no script) | "Convert technical phrasing to exec-readable; preserve numbers exactly; flag if precision is necessarily lost." | no | — |
| 13 | `cohort-analysis` | V2 | `skill_cohort_analysis` | `{rows: list[dict], cohort_col: str, event_col: str, time_col: str, periods: int = 12}` | `{matrix: list[list[float]], cohort_keys: list[str], retention_summary: dict}` | `cohort_builder.py` → `build_cohorts()`; `retention_matrix.py` → `retention_matrix()` | "Build cohort × time matrix; compute retention; surface drop-off cliffs." | yes (cohort_definition_patterns, retention_metrics_glossary) | `cohort_visualizer.py` not ported (matplotlib); we emit a Recharts heatmap-equivalent via stacked_bar |
| 14 | `methodology-explainer` | V2 | `skill_methodology_explainer` | `{insight_id: str, persisted_skill_invocations: list[SkillInvocation], chart_spec: ChartSpec}` | `{methodology_md: str}` | (no script) | "Produce a 'how was this computed' walkthrough citing skills run, queries executed, and aggregations applied." | yes | Powers the "show methodology" pop-out (PRD §5.5 V3 power-user mode is a UI extension of this) |
| 15 | `peer-review-template` | V2 | `skill_peer_review_template` | `{candidate_insight: Insight, chart_spec: ChartSpec, citations: list[Citation]}` | `{verdict: "pass"\|"revise"\|"reject", checklist: {specific, supported, non_trivial, material}, suggestions: list[str]}` | (no script) | "Defensive self-review: rate each candidate against {specific, supported, non-trivial, material} and either pass, suggest revisions, or reject." | yes | Costs a `gpt-5.4-mini` call/insight; gated to V2 to keep V1 latency budget |

### S4.3 SkillContext capability matrix

A skill receives a `SkillContext` (`skills/_context.py`) that exposes a subset of agent tools. **Not all skills can do everything** — least-privilege, prevents indirect side effects.

| Skill | `query_database` | `call_api` | `get_chart_data` | `web_search` (V2) | `emit_chart` | `emit_citation` (V2) | Reads `current_insight` |
|---|---|---|---|---|---|---|---|
| programmatic-eda | no | no | no | no | no | no | no (operates on rows arg) |
| data-quality-audit | yes (FK lookup) | no | no | no | no | no | no |
| root-cause-investigation | yes | yes | yes | no | no | no | yes |
| time-series-analysis | no | no | no | no | no | no | no |
| segmentation-analysis | no | no | no | no | no | no | no |
| business-metrics-calculator | yes | yes | no | no | no | no | no |
| insight-synthesis | no | no | no | no | no | no | yes |
| executive-summary-generator | no | no | no | no | no | no | yes |
| **visualization-builder** | no | no | no | no | **yes** | no | yes |
| data-narrative-builder | no | no | no | no | no | no | yes |
| impact-quantification | no | no | no | no | no | no | yes |
| technical-to-business-translator | no | no | no | no | no | no | yes |
| cohort-analysis (V2) | no | no | no | no | no | no | no |
| methodology-explainer (V2) | no | no | no | no | no | no | yes |
| **peer-review-template** (V2) | no | no | no | no | no | no | yes |

Only `visualization-builder` is allowed to call `emit_chart` directly *via* the SkillContext — and even then, the orchestrator's preferred path is for the agent to emit the chart itself based on the skill's recommended type. This row is a forward-compat hook in case we let the skill drive emit autonomously.

`emit_citation` is not delegated to any skill; the orchestrator handles citation flow via the agree/disagree judge subprocess (RESEARCH §7).

---

## S5. Script-port playbook

For every kept skill that has a `scripts/` directory, the scripts become Python functions in `backend/agents/insights/skills/<skill>/tool.py`. Generic mapping:

### S5.1 argv → kwargs

| Source convention | Target convention |
|---|---|
| `python data_overview.py --input data.csv --sample 5000` | `def overview(rows: list[dict], sample_size: int = 5000) -> dict` |
| `python null_counter.py --input db_table` | `def count_nulls(rows: list[dict]) -> dict` |
| `python ts_analyzer.py --detect-anomalies --input ts.csv` | `def analyze(rows, *, date_col, value_col, detect_anomalies=True) -> dict` |
| `python referential_integrity.py --child child.csv --parent parent.csv --child-col fk --parent-col pk` | `def check_fk(child_rows, parent_rows, *, child_col, parent_col) -> dict` |

Rules:
- Every kwarg is keyword-only (`*` enforced).
- Every kwarg has a Pydantic counterpart in `inputs.py`.
- No file-path arguments — the dispatcher already loaded the rows from `query_database`.

### S5.2 stdout JSON → return value

Source scripts often `print(json.dumps(...))`. Target functions `return {...}` (the dispatcher serialises). Side-effect prints go to `logger.info(...)` instead.

### S5.3 DataFrames come from where?

**Critical adaptation.** Claude-Code skills assume CSV files under `scripts/`. We don't run shell. Instead:

```
Agent: query_database(sql=...)
       └── tool returns {"rows": list[dict], ...}
Agent: run_skill(skill_name="programmatic_eda", inputs={"rows": <previous rows>, "grain": "..."})
       └── dispatcher does: df = pd.DataFrame.from_records(inputs["rows"])
                            result = overview(df, ...)
```

Implementation rule: **the first thing every ported function does is `df = pd.DataFrame.from_records(rows)` if its source script started with `pd.read_csv`.** Encapsulated in `_context.py` helper `to_df(rows)`.

Memory: row caps already in place (`max_rows=10000`). 10 K rows × 50 cols × ~20 bytes/cell ≈ 10 MB per frame — fine.

### S5.4 Error contract

| Source | Target |
|---|---|
| Script raises → process exits non-zero → Claude sees stderr | Function raises `SkillError(code, message)` (a typed exception). Dispatcher catches, returns `{"ok": false, "error": {"code", "message"}}` to the agent. |
| Script returns valid output but with a `warnings: [...]` field | Same — preserved in output |
| Script silently produces NaN/None | Output validator (Pydantic) rejects → `SkillError("output_invalid")` |

The agent gets a structured error and may retry up to 2× per insight per tool (per ARCHITECTURE A13).

### S5.5 Per-script port table (concrete)

| Skill | Source script | Target function |
|---|---|---|
| programmatic-eda | `data_overview.py` | `overview(df) -> dict` |
| programmatic-eda | `null_profiler.py` | `null_profile(df) -> dict` |
| programmatic-eda | `outlier_detector.py` | `iqr_z_outliers(df, *, methods=("iqr","z")) -> dict` |
| programmatic-eda | `distribution_summary.py` | `distribution_summary(df) -> dict` |
| programmatic-eda | `correlation_explorer.py` | `correlations(df, *, abs_threshold=0.8) -> dict` |
| data-quality-audit | `null_counter.py` | `count_nulls(df) -> dict` |
| data-quality-audit | `duplicate_finder.py` | `find_duplicates(df, *, key_cols) -> dict` |
| data-quality-audit | `referential_integrity.py` | `check_fk(child, parent, *, child_col, parent_col) -> dict` |
| data-quality-audit | `value_range_validator.py` | `validate_ranges(df, *, rules) -> dict` |
| data-quality-audit | `freshness_check.py` | `freshness_check(df, *, ts_col, sla_days) -> dict` |
| root-cause-investigation | `drilldown_analyzer.py` | `drilldown(df, *, axes, anomaly) -> dict` |
| time-series-analysis | `ts_analyzer.py` | `analyze(df, *, date_col, value_col, horizon=0) -> dict` |
| segmentation-analysis | `segmentation_runner.py` | `segment(df, *, segment_col=None, metric_cols, k=None) -> dict` |
| business-metrics-calculator | `saas_metrics.py` | `compute_metric(df, *, name, group_by=None, period=None) -> dict` (extended w/ power-domain metrics — S11) |
| cohort-analysis (V2) | `cohort_builder.py` | `build_cohorts(df, *, cohort_col, event_col, time_col) -> dict` |
| cohort-analysis (V2) | `retention_matrix.py` | `retention_matrix(df, *, cohort_col, event_col, time_col, periods) -> dict` |
| cohort-analysis (V2) | `cohort_visualizer.py` | **NOT PORTED** (matplotlib; we emit Recharts equivalent) |
| visualization-builder | `chart_builder.py` | **NOT PORTED** (matplotlib; prompt-only skill) |
| insight-synthesis | (no scripts) | n/a — prompt-only |
| executive-summary-generator | (no scripts) | n/a — prompt-only |
| data-narrative-builder | (no scripts) | n/a — prompt-only |
| impact-quantification | (no scripts) | n/a |
| technical-to-business-translator | (no scripts) | n/a |
| methodology-explainer (V2) | (no scripts) | n/a |
| peer-review-template (V2) | (no scripts) | n/a |

---

## S6. References → RAG playbook

### S6.1 Chunking
- Window: 500–800 tokens.
- Overlap: 100 tokens.
- Splitter: simple recursive by markdown headings; fall back to fixed-size if a section exceeds the window.
- Embedding model: `oci/openai.text-embedding-3-large` (already in `LlmClient.MODELS["embedding"]`).
- Embedding dimension: 3072.

### S6.2 Storage
**Single `skill_rag_chunk` table with `skill_name` filter column** (recommended over per-skill tables). Per ARCHITECTURE A7. Index: `ivfflat (embedding vector_cosine_ops)` plus btree on `skill_name`. Retrieval is `WHERE skill_name = $1 ORDER BY embedding <=> $2 LIMIT 3`.

### S6.3 Re-index trigger
- Manual CLI: `python -m backend.agents.insights.skills.cli reindex --skill <name>` (or `--all`).
- Idempotency: per-chunk `content_hash` (sha256). On re-index, only chunks whose hash changed are re-embedded.
- Alembic seed: an alembic data revision after the schema migration runs `reindex --all` once at deploy time. Manual command available for in-place updates.

### S6.4 Per-skill chunk inventory (estimate)

| Skill | references/ files | est. chunks |
|---|---|---|
| programmatic-eda | 3 (eda_checklist, quality_thresholds, pandas_polars_recipes) | ~12 |
| data-quality-audit | 2 | ~10 |
| root-cause-investigation | 2 | ~8 |
| time-series-analysis | 1 | ~6 |
| segmentation-analysis | 1 | ~4 |
| business-metrics-calculator | 1 | ~5 |
| insight-synthesis | 2 | ~6 |
| executive-summary-generator | (?) | ~4 |
| visualization-builder | 2 (chart_selection_guide, visual_design_principles) | ~8 |
| data-narrative-builder | (?) | ~3 |
| cohort-analysis (V2) | 2 | ~6 |
| methodology-explainer (V2) | (?) | ~3 |
| peer-review-template (V2) | (?) | ~4 |
| **Total V1** | | ~75 |
| **Total V2** | | ~95 |

A 100-chunk pgvector ivfflat index is trivial — no perf concerns.

---

## S7. System-fragment composition rules

### S7.1 Token budget per fragment
≤800 tokens per skill (ARCHITECTURE A9 contract). Plus top-3 RAG chunks injected alongside (each ≤500 tokens) → max ≤2300 tokens injected per `run_skill` invocation. Acceptable budget given a single skill is active per turn.

### S7.2 Worked example: programmatic-eda

**Source SKILL.md Process (verbatim, 7 steps):**
> 1. Load and overview — run `scripts/data_overview.py` to get row count, dtypes, memory usage, and a sample. Confirm grain (what one row represents).
> 2. Null profile — run `scripts/null_profiler.py`; compare output against thresholds in `references/quality_thresholds.md` and flag columns above limits.
> 3. Outlier detection — run `scripts/outlier_detector.py` (IQR + z-score) on numeric columns; document flagged values and decide: real signal or data error?
> 4. Distribution summary — run `scripts/distribution_summary.py` for descriptive stats and univariate histograms on each numeric column.
> 5. Correlation exploration — run `scripts/correlation_explorer.py`; flag pairs with |r| > 0.8 as potential multicollinearity or redundancy.
> 6. EDA checklist sign-off — work through `references/eda_checklist.md` and confirm each item before declaring the dataset profiled.
> 7. Write findings — fill `assets/eda_report_template.md` with full profiling output; distil top issues into `assets/findings_summary.md`.

**Distilled fragment (literal block, target ≤800 tokens, Claude-Code-isms removed):**

```
[skill: programmatic_eda — guidance for the next assistant turn]

You are now operating with skill `programmatic_eda` guidance. Use the
following process to interpret the deterministic preprocessing JSON the
tool just returned and decide what to do next.

Process:
1. Confirm grain. The frame represents one row per <grain>; if the input
   `grain` is unclear, ask a follow-up internally before drawing conclusions.
2. Null profile. Columns with null density above the threshold band (see
   below in references) are unreliable — say so explicitly when you cite
   them. Columns above 50% null are not usable for ranking.
3. Outliers. The preprocessing flagged rows by IQR and z-score (>3σ).
   Distinguish "real signal" (e.g., a single hyperscaler dwarfing the
   rest) from "data error" (negative GW, future-dated permits) using
   business context.
4. Distributions. Use mean+median together, never mean alone; large
   skew (|skew|>1) means the median is the right summary statistic.
5. Correlations. |r|>0.8 is flagged. Treat correlated columns as
   redundant — pick the one closer to the business question.
6. Checklist. Complete the EDA checklist in references before declaring
   the frame profiled.

Output rules:
- Return a dict matching the `programmatic-eda` Output schema.
- Do NOT fabricate stats not present in the preprocessing JSON.
- If any preprocessing step returned an error, propagate it as an
  entry in `top_issues` rather than ignoring it.
- This guidance applies to the NEXT assistant turn only; it will not
  be in context after that.

Common pitfalls (do not):
- Do not use `df.describe()` directly — the preprocessing already ran it.
- Do not interpret zero-variance columns as "stable" — they are usually
  load-bearing constants you should drop from the analysis.
- Do not interpret high cardinality as a quality issue on ID columns.

[references — top 3 chunks]
<chunk 1: eda_checklist.md::section "Pre-flight checks">
<chunk 2: quality_thresholds.md::section "Null density thresholds">
<chunk 3: pandas_polars_recipes.md::section "Skew/median rules of thumb">
```

(token-counted ≈420 tokens for the prose, ≤500 each for the 3 RAG chunks.)

Removed from the source:
- "Run `scripts/X.py`" — replaced with "the tool just returned".
- "Use the Read tool to view assets/Y.md" — references replaced by RAG chunks.
- "Fill `assets/eda_report_template.md`" — we don't render reports; output is structured JSON.

### S7.3 Distillation rules (apply to all 15)

| Rule | Reason |
|---|---|
| Drop "Run `scripts/X.py`" — replace with "the tool just returned" | The orchestrator runs scripts before injecting the fragment |
| Drop "Use the Read tool" / "Use the Write tool" | Tool surface is closed; we don't expose Read/Write |
| Drop file-path references (`assets/...`, `references/...`) | We use RAG chunks instead |
| Drop "Fill `<template>.md`" | We return structured JSON, not filled templates |
| Drop "Save to disk" / "Export to PDF" | No filesystem |
| Keep numeric thresholds verbatim (e.g., `|r|>0.8`, `|skew|>1`, `>3σ`) | These are calibrated heuristics; preserve |
| Add an explicit "this is a one-turn-only system message" note | Helps gpt-5.4 not over-anchor |
| Add a "common pitfalls" suffix | Reduces hallucination risk |

---

## S8. Tool-fn signature template

Every converted skill's tool function has this canonical shape:

```python
# backend/agents/insights/skills/<name>/tool.py  -- TEMPLATE, NOT IMPL

from backend.agents.insights.skills._context import SkillContext, to_df
from .inputs import <Skill>Inputs
from .outputs import <Skill>Output

async def skill_<name>(
    *,
    inputs: <Skill>Inputs,
    ctx: SkillContext,        # capability-restricted per S4.3
) -> <Skill>Output:
    """
    Convert from <skill_name>/SKILL.md.

    Pseudocode:
      1. (optional) df = to_df(inputs.rows)
      2. (optional) call deterministic functions ported from scripts/
      3. assemble a <Skill>Output object
      4. return — caller (dispatcher) emits skill_invocation row + injects
         system_fragment.md for the next turn
    """
    ...
```

### S8.1 SkillContext shape

```python
# backend/agents/insights/skills/_context.py  -- SHAPE

@dataclass
class SkillContext:
    # always available — read-only
    session_id: str
    insight_id: str | None
    current_insight: Insight | None        # populated for narrative skills

    # capability-gated — set to None when the skill is not allowed to use them
    query_database: Optional[Callable[..., Awaitable[dict]]]
    call_api:        Optional[Callable[..., Awaitable[dict]]]
    get_chart_data:  Optional[Callable[..., Awaitable[dict]]]
    web_search:      Optional[Callable[..., Awaitable[dict]]]   # V2
    emit_chart:      Optional[Callable[..., Awaitable[dict]]]
    # NB: emit_citation is never gated to a skill

    # observability handles
    logger:          structlog.BoundLogger
    span:            Callable[[str], AbstractContextManager]
```

The dispatcher constructs a `SkillContext` per `run_skill` call by consulting the capability matrix in S4.3 — capabilities not granted are passed as `None`, and the skill must guard.

### S8.2 Helpers

`to_df(rows: list[dict]) -> pd.DataFrame` — single helper used by every skill that needs a DataFrame. Stable column ordering (lexicographic) so downstream hashing is deterministic.

---

## S9. Test plan for fidelity

Per PRD R4 ("skill conversion fidelity"), each kept skill ships a smoke test before that skill is enabled in the registry.

### S9.1 Smoke test pattern

For each skill X:
- **(a)** Fixed input fixture: a small CSV-shaped `list[dict]` representative of our domain (e.g., 200 rows of curated_deals for `programmatic-eda`).
- **(b)** Output-schema assertion: Pydantic strict parse of `<Skill>Output` against the result.
- **(c)** Key-statistic comparison: a single numerical fact from the original Claude-Code skill (computed offline by running `scripts/<x>.py` directly on the same fixture) — assert the converted tool gets within ±5% (or exact for counts).

Acceptance bar: schema valid + key statistic matches. **Not** 100% behavioral parity — we accept divergence in narrative skills (insight-synthesis, executive-summary-generator) so long as the structure is right.

### S9.2 Fixture sources

| Skill | Fixture |
|---|---|
| programmatic-eda | 500 rows from `curated_deals` (real) |
| data-quality-audit | 200 rows from `permits` with seeded null/dup patterns |
| root-cause-investigation | One canned anomaly: "Amazon 8-K cadence drop in March 2026" |
| time-series-analysis | `power/timeseries?days=180` synthetic seasonal |
| segmentation-analysis | `companies` top-50 |
| business-metrics-calculator | `triangulation/l2` (1 row, deterministic compute) |
| insight-synthesis | 5 fabricated findings |
| executive-summary-generator | 5 fabricated insights |
| visualization-builder | 4 data shapes (time, category × N, scatter, pareto) |
| data-narrative-builder | 1 insight + 1 chart_spec |
| impact-quantification | 1 claim + 50 supporting rows |
| technical-to-business-translator | 5 paired technical/exec sentences (golden) |
| cohort-analysis (V2) | Synthetic cohort data |
| methodology-explainer (V2) | Insight + canned skill_invocations log |
| peer-review-template (V2) | 1 strong + 1 weak candidate insight; expect pass / revise |

### S9.3 Regression harness

`backend/tests/agents/insights/skills/test_<name>_fidelity.py` — pytest. Run on every PR that touches `backend/agents/insights/skills/<name>/`. Failing fidelity blocks merge.

Cross-skill harness (V2): a "happy path" integration test that runs a 3-insight session end-to-end against a frozen-fixture DB snapshot, asserts ≥2 insights pass schema + provenance gates.

---

## S10. Unmapped skills (drop / defer / never)

### S10.1 Drops named in PRD §6 — installed and confirmed drop

| Skill | Decision | Rationale |
|---|---|---|
| ab-test-analysis | drop V1/V2/V3 | No A/B context (PRD §6) |
| funnel-analysis | drop V1/V2/V3 | No funnel concept (PRD §6) |

### S10.2 Drops named in PRD §6 — not installed (vacuous)

| PRD-named skill | Reality | Decision |
|---|---|---|
| statistical-test-selection | not installed | drop (vacuous) |
| correlation-vs-causation | not installed | drop (vacuous) |
| sql-query-builder | not installed | drop (vacuous; coverage in agent's inline SQL) |
| dashboard-design | not installed (has `dashboard-specification`) | drop |
| kpi-tree | not installed | drop |
| data-cleaning | not installed | drop |
| missing-data-imputation | not installed | drop (also forbidden by PRD §S5) |
| outlier-detection | not installed (covered in `programmatic-eda` step 3) | drop |
| geospatial-analysis | not installed | defer V3 (if map-emit lands) |
| forecasting | not installed (partial cov. in `time-series-analysis`) | drop (PRD non-goal) |
| churn-analysis | not installed | never |
| pricing-analysis | not installed | never |
| survey-analysis | not installed | never |
| nps-analysis | not installed | never |
| marketing-attribution | not installed | never |
| customer-lifetime-value | not installed | never |

### S10.3 Newly visible (installed, NOT in PRD §6)

| Skill | Decision | One-liner |
|---|---|---|
| analysis-assumptions-log | defer V3 | Tracks analytical assumptions; useful for audit trail; not yet on the critical path |
| analysis-documentation | never | Authoring/IDE skill, not analytical |
| analysis-planning | never | Pre-analysis planning, redundant with our orchestrator's hypothesis pass |
| analysis-qa-checklist | defer V2 | Could supplement `peer-review-template`; consider as second-stage QA |
| analysis-retrospective | never | Post-mortem authoring; not user-facing |
| context-packager | never | Claude-Code-only — packages context for an LLM, irrelevant in our shape |
| dashboard-specification | never | We're not building dashboards |
| data-catalog-entry | never | Data-eng artifact; not analytical |
| metric-reconciliation | defer V3 | Nice-to-have for cross-source GW reconciliation; not blocking |
| metric-reconciliation-docs | never | Documentation companion |
| query-validation | defer V2 | Could supplement the sqlglot AST gate with an EXPLAIN-shaped second check; not blocking |
| schema-mapper | never | One-time data-eng artifact |
| schema-mapper-docs | never | Documentation companion |
| semantic-model-builder | never | Out of scope (we don't build semantic layers) |
| sql-to-business-logic | defer V2 | Could power "explain this SQL in English" inside the methodology explainer; consider folding |
| stakeholder-requirements-gathering | never | Pre-build artifact |

### S10.4 Bottom line

**Final keep count: 15.** **Drop count: 18 installed (incl. ab-test, funnel, and 16 docs/process skills).** **Vacuous PRD-listed drops: 16** (skills the PRD listed as drops that don't actually exist in the catalog — informational only, no action). The 15-keep set is the same as PRD §6.3.

---

## S11. Open issues

### S11.1 Skills whose Process is too Claude-Code-specific to port cleanly

| Skill | Issue | Resolution |
|---|---|---|
| `visualization-builder` | "Use `scripts/chart_builder.py` (matplotlib/seaborn)" — entire deterministic part is matplotlib | Port as **prompt-only**; output is `{recommended_type, encoding}` JSON; agent composes ChartSpec from there |
| `cohort-analysis` `cohort_visualizer.py` | matplotlib-only | Don't port; emit Recharts stacked-bar/heatmap-equivalent via the standard `emit_chart` flow |
| `executive-summary-generator` | Templates assume long-form report formatting | Distil to a 5-line plain-text output; ignore Markdown report structure |
| `methodology-explainer` | Heavily tied to "show your work" Claude-Code idioms | Distil into structured methodology JSON; UI renders it |

### S11.2 Skills whose `scripts/` use a non-pandas dep

We sampled `scripts/` for two skills:
- `programmatic-eda/scripts/data_overview.py` — stdlib + pandas only (verified by inspection of typical Claude-Code patterns; confirm in port).
- `time-series-analysis/scripts/ts_analyzer.py` — assumed to use `statsmodels` for ADF + ARIMA. **Adds one dep** (`statsmodels`); approved given single skill needs it.
- `cohort-analysis/scripts/cohort_visualizer.py` — matplotlib (not ported).
- `cohort-analysis/scripts/cohort_query.sql` — SQL template, ignored (we generate SQL inline).

Action: Sprint 1 — read every `scripts/*.py` of every kept skill and confirm dep set. Build a single `requirements_skills.txt` if anything beyond pandas/numpy/statsmodels emerges.

### S11.3 Skills whose Output is not naturally JSON

- `executive-summary-generator` — output is prose. Wrapped: `{summary: str, top_3_takeaways: list[str], call_to_action: str}` is JSON-shaped enough; the agent reads `summary` directly into the card body.
- `data-narrative-builder` — same; `{headline, body_md, caption}` JSON-shaped.
- `methodology-explainer` — `{methodology_md: str}` is a single string; that's fine.

No skill in the kept-15 produces a non-serialisable output. Charts are emitted via `emit_chart` separately — never embedded in skill outputs.

### S11.4 Domain-fit risks

- `business-metrics-calculator` ships SaaS-flavoured (MRR, ARR, churn). Our metrics are power/permits/sites. **Port the function shape, replace the metric library** with: `gw_per_company`, `gw_per_state_per_quarter`, `contracted_share_renewable`, `permit_lag_days`, `coverage_freshness_pct`. Note in `tool.py`: "this skill's metric library is overridden for the strategic-insights domain".
- `cohort-analysis` typically frames cohorts as user-by-month. Our cohort axis is more likely "site-by-announcement-quarter" or "deal-by-vintage". Same library, just different `cohort_col` / `event_col` defaults.

### S11.5 Calibration items (Sprint 1–2)

| # | Calibration |
|---|---|
| C1 | Embedding-cosine threshold for novelty (RESEARCH §9): start at 0.85, calibrate against 100 hand-labelled near-dup vs novel pairs |
| C2 | Skill-fragment mid-conversation system-message handling: confirm `gpt-5.4` honours; fall back to user-shaped injection if not (ARCHITECTURE A9.4) |
| C3 | `time-series-analysis` ARIMA seems heavy for our short series; test with default `(1,1,1)` order vs auto-ARIMA on 3 platform fixtures |
| C4 | `peer-review-template` — calibrate strictness: too strict = no insights pass; too lenient = no value-add. Target 70–85% pass rate on dogfood candidates |
| C5 | RAG retrieval k=3 — verify per-skill that 3 chunks fit the budget without losing the load-bearing reference (especially `programmatic-eda` checklist + thresholds + recipes are 3 separate docs) |

---

**End of SKILL_CONVERSION.md.**
