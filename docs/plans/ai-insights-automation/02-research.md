# Research: AI Insights Automation & Real-Data Synthesis

## 0. Scope and grounding

This document investigates four design questions for wiring the existing `InsightOrchestrator` into a scheduled, real-data daily insights run. It builds on (and does not redo) the prior investigation summarized in the user's brief.

Files inspected in-tree to ground the recommendations:

- `backend/agents/insights/orchestrator.py` — five-phase orchestrator; bootstrap (line 279) is wired to 8 survey endpoints but only counts rows; hypothesize (line 339) emits a single `reasoning_step` and produces nothing; verify+synthesize (line 355) loops `max_insights` times with the literal `f"Candidate insight #{idx + 1}"` hypothesis (line 398).
- `backend/pipeline/runner.py` — `AsyncIOScheduler` with `SQLAlchemyJobStore` against the same Postgres; `JOB_CONFIG` already holds 10 jobs; common wrapper `_run_adapter_job` (line 177) brackets each run with an `IngestionRun` audit row; weekly_brief uses `grace=86400, coalesce=True`, daily jobs use `grace=3600, coalesce=True`.
- `backend/agents/weekly_brief.py` — already implements the exact "deterministic SQL fact pack → single LLM call → persist" pattern; a strong precedent for Option A1.
- `backend/alembic/versions/009_ai_insights.py` — confirms `CREATE EXTENSION IF NOT EXISTS vector;` runs on migrate (line 54). `ai_insight.headline_embedding` exists as `Text` today, with the migration comment explicitly noting "dedup writes vector via raw SQL". `skill_reference.embedding` is `vector(3072)` and proves pgvector is available end-to-end.
- `backend/agents/insights/dedup.py` — already implements Jaccard pre-filter + cosine over text-embedding-3-large vectors against an in-memory `prior_headlines_with_embeddings` list. It does not yet read priors from the DB.

These confirm that the platform pieces are present; the work is integration and a few new policies, not new technology.

---

## A. Synthesis pipeline architecture

### A.0 The three options (recap)

- **A1 — Deterministic fact pack → constrained synthesis.** A new `hypothesizer.py` runs ~6–10 fixed SQL queries (top movers, new permits in last 24h, anomalies flagged today, EDGAR filings mentioning capacity/MW, etc.), assembles a JSON pack of "candidate facts", and the LLM only synthesises prose/insight from that pack. No tool loop.
- **A2 — Full ToolLoopDriver / agentic.** LLM is given DB-query tools (and possibly the existing `call_api` survey tool) and decides which to call, iterating up to `V1_TOOL_CALL_CAP=40`.
- **A3 — Hybrid.** Deterministic candidate generation as in A1 produces N hypotheses with attached fact rows; the LLM is granted exactly one optional follow-up tool call per hypothesis (drill-down) before synthesis.

### A.1 Comparison matrix

| Dimension | A1 Deterministic | A2 Full agentic | A3 Hybrid |
|---|---|---|---|
| Cost / run (oci/openai.gpt-5.4) | ~1 LLM call for hypotheses + 7 syntheses ≈ 8 turns; or 1 mega-call. **~15–30 K tokens/day.** | 5–30× chat baseline per agentic patterns; **realistically 100–400 K tokens/day** for a 40-tool-call cap with 7 insights. | 1 deterministic + up to 7 follow-up tool calls + 7 syntheses; **~30–60 K tokens/day.** |
| Wall-clock | 30–90 s | 4–8 min (cap is 480 s) | 1–3 min |
| Determinism / repeatability | High — same SQL, same output (tied to data) | Low — model picks tools | High for hypothesis seeds, model-side noise only on prose |
| Debuggability | Excellent — fact pack is JSON, can be diffed | Poor — long transcript, branchy | Good — fact pack + at most one extra tool call per insight |
| Failure modes | SQL throws → caught row-by-row; LLM 5xx → one retry | Tool-loop divergence; spend cap thrashing; stuck loops | Same as A1 plus a single bounded follow-up |
| Code complexity | One new module (`hypothesizer.py`) plus a small synthesis prompt change | Need to wire `ToolLoopDriver`, register DB tools, write tool schemas, add system prompt for the loop | A1 + a thin "drill_down" tool with a hard cap of 1 |
| Test surface | Pure functions: SQL → JSON, JSON → string. Unit testable. | Requires fakes for the LLM and tool registry; integration tests are fragile | A1 tests + 1 small loop test |
| Surprise value (user-facing) | Lower — sees only what we queried for | Higher — model can chase angles | Medium — drill-down is the surprise lever |
| Observability | `IngestionRun` + `skill_invocation` rows | `agent_tool_call` rows already exist; richer | Same as A1 + 0–7 `agent_tool_call` rows |
| Dedup-friendliness across days | Easy — fact pack rows hash deterministically | Hard — the model may rephrase the same thing differently | Easy — same as A1 |

Sources: agentic loops typically consume **5–30× more tokens than chat baselines**, with multi-agent systems hitting 200K–1M tokens per task ([Token Cost Trap](https://medium.com/@klaushofenbitzer/token-cost-trap-why-your-ai-agents-roi-breaks-at-scale-and-how-to-fix-it-4e4a9f6f5b9a)). Both OpenAI and Anthropic guidance is "start with the simplest architecture that solves the problem and introduce the agent loop only when iterative reasoning and adaptive tool use are required" ([4 Levels of AI Agents](https://www.barnacle.ai/blog/2025-09-25-agents-intro)).

### A.2 Recommendation: **A1 Deterministic for V1, with A3 Hybrid as the V1.1 migration target**

Reasons:

1. **There is already an in-tree precedent.** `agents/weekly_brief.py` is already an A1-style pipeline: `_safe_query` over each pillar table → JSON context → one `llm_client` call → persist. Cloning that shape gives engineers a known-good reference and slashes the surface area of new code.
2. **Cost predictability is non-negotiable for a daily cron.** A daily cron has exactly 365 firings per year. A1 puts daily token spend in a tight band (see §C); A2 has variance of 10–20× depending on the model's path choices. The product is not yet at scale where the additional surface from agentic mode pays for itself.
3. **Repeatability is what makes dedup work.** The dedup design (§D) hinges on the *same* underlying fact triggering the *same or near-same* candidate today and tomorrow. Deterministic SQL guarantees this; an LLM tool loop does not.
4. **Failure modes are understood.** When the EDGAR adapter fails, the corresponding fact-pack section is empty; synthesis gracefully degrades. With A2 a partial outage triggers tool-call retries, which can chew through the 40-call budget without producing anything.
5. **Test debt today is low.** The repo has `test_insights_*` tests around dedup, SSE, SQL gates, and tool loops. A1 keeps the surface small enough that we can keep the new module at >80% line coverage.

**Migration path to A3:** Once V1 is shipped and we have ~30 days of insight history, add a `drill_down` tool restricted to:
- A whitelist of read-only SQL templates parameterised by `(entity, metric, days)`.
- One call per insight, gated by a `needs_drilldown: bool` field returned by the hypothesizer.

This keeps the bound tight (max 7 extra tool calls = 14 LLM turns), still fits inside the 480 s wall clock, and lets the model surface the angle the deterministic queries missed without blowing the budget.

### A.3 Concrete A1 shape

```
hypothesizer.py
  build_fact_pack(db) -> FactPack
    sections:
      - top_capacity_movers_24h    (power deals + GW deltas)
      - new_permits_24h             (county + state)
      - anomalies_today             (rows where flagged_at::date = today)
      - edgar_capacity_mentions_7d  (filings whose extracted body mentions MW/GW)
      - epa_echo_new_records_24h
      - coverage_gaps               (data_coverage rows now status='partial')
      - top_companies_by_delta      (week-over-week capacity)
    each section is independently try/except'd (mirror weekly_brief._safe_query)

orchestrator._phase_hypothesize_iter
  fact_pack = await build_fact_pack(self.db)
  hypotheses = await llm.complete(
    prompt=HYPOTHESIZE_PROMPT.format(fact_pack=fact_pack.to_compact_json()),
    response_format={"type": "json_schema", "schema": HypothesesSchema},
  )
  # hypotheses: list[ {id, headline_draft, supporting_row_ids[], confidence_signal} ]

orchestrator._phase_verify_and_synthesize_iter
  for h in hypotheses[:max_insights]:
    rows = fact_pack.lookup(h.supporting_row_ids)
    synth = run_insight_synthesis(InsightSynthesisInputs(
      hypothesis=h.headline_draft,
      supporting_rows=rows,           # was [] in V1
      context={...}
    ))
```

The fact pack lookup gives us the row-backed `ChartSpec.data_source.row_hash` we need for the existing chart-emission verifier (`agent_chart.row_hash`).

### A.4 Token-budget arithmetic for A1 vs 7 separate vs 1 mega call

See §C — the mega-call is cheaper and more coherent; recommend it.

---

## B. Scheduling: APScheduler vs alternatives

### B.1 The alternatives (and why we reject them)

- **Celery + Redis/Beat.** A second runtime, a second persistence layer, and overlapping job-store concepts. Worth it once we need horizontal worker scale-out. Today the runner is single-instance; the cost-benefit is negative.
- **Kubernetes CronJob.** External to the FastAPI process; good when jobs need different resources from the API. Cost: every job needs its own image / entrypoint script, HTTP credentials to talk back to the API, and a separate observability path. Loses the existing `IngestionRun` row pattern.
- **Existing CronCreate / RemoteTrigger primitive.** Per the brief: that is the Claude harness scheduling primitive. It does not run when the harness is offline and is not a server-side production scheduler. **Not applicable.**
- **A separate worker process (e.g., a dedicated `python -m insights.daily` invoked by systemd).** Cleaner separation of concerns but adds deployment complexity and a second place where DB sessions are configured.

### B.2 Recommendation: **Stay on APScheduler. Add one job to `JOB_CONFIG`.**

The runner already gives us:

- A Postgres-backed `SQLAlchemyJobStore` (line 384 of runner.py) — surviving process restarts.
- The `_run_adapter_job(adapter_name, invoke_fn)` wrapper that creates an `IngestionRun` row at start and updates it on completion or exception (line 177).
- `coalesce=True` on every job — a missed firing replays once, not N times.
- Differentiated `misfire_grace_time` (3600 daily, 86400 weekly).

### B.3 Settings for the new `insights_daily` job

| Setting | Value | Rationale |
|---|---|---|
| `id` | `insights_daily` | Mirrors `edgar_daily` / `permits_state_daily` naming |
| `trigger` | `CronTrigger(hour=9, minute=0)` UTC | Runs after edgar (06:00), county permits (06:30), edgar quarterly (06:15), permits state (07:00), epa echo (08:00) — so today's fact pack always sees today's ingest |
| `misfire_grace_time` | `3600` (1 h) | Same as other dailies; if FastAPI was restarting at 09:00, we still fire by 10:00 |
| `coalesce` | `True` | If we missed multiple firings, only run once on recovery |
| `max_instances` | `1` (default) | A previous run still running at 09:00 the next day must NOT spawn a second |
| `replace_existing` | `True` | Same as siblings |

These match APScheduler's documented guidance: by default only one instance per job is allowed; if a previous run hasn't finished the next firing is treated as a misfire ([APScheduler user guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html)).

### B.4 Idempotency: protect against two firings on the same day

`misfire_grace_time=3600` + `coalesce=True` makes the *scheduler* fire only once per logical scheduled time. But across DST, manual triggers, and operator reruns we still need the *job body* to be idempotent. Recommended guard at the top of the job body (semantic, not literal code):

```
async def run_insights_daily() -> None:
    today = date.today()
    async with async_session_factory() as s:
        existing = await s.execute(
            select(AISession.id).where(
                AISession.created_by == "scheduler",
                func.date(AISession.started_at) == today,
                AISession.status.in_(("running", "complete")),
            )
        )
        if existing.first() is not None:
            logger.info("insights_daily: already ran today, skipping")
            return
    # ... proceed with orchestrator run
```

A unique partial index `CREATE UNIQUE INDEX ... ON ai_session ((started_at::date)) WHERE created_by = 'scheduler' AND status <> 'failed'` is a stronger DB-level guarantee but is an ALTER and can wait for v1.1. The application-level guard above is enough for V1 and uses fields that already exist on `ai_session` (`created_by`, `started_at`, `status` per migration 009).

### B.5 Concurrency/connection-pool safety

Per SQLAlchemy 2.0 async docs, **use a separate AsyncSession per task**, never share one across `asyncio.gather` ([SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)). The runner's `_run_adapter_job` already opens a fresh session per firing via `async with async_session_factory()`, and the orchestrator stores it on `self.db`. Keep that pattern; do not reuse FastAPI request-scoped sessions.

---

## C. LLM cost & token budgeting

### C.1 oci/openai.gpt-5.4 pricing — what we know

OCI Generative AI's documented on-demand pricing model is **per-character** (1 character = 1 transaction), with the pricing page quoting "per 10,000 transactions or per 1,000,000 tokens" depending on the model class ([OCI GenAI pricing](https://www.oracle.com/artificial-intelligence/generative-ai/generative-ai-service/pricing/), [Paying for On-Demand Inferencing](https://docs.oracle.com/en-us/iaas/Content/generative-ai/pay-on-demand.htm)). For Cohere Command R-class on OCI, the public number is roughly $0.0219 per 10,000 transactions.

For the OpenAI-named GPT-5.4 model behind the `oci/openai.gpt-5.4` model string, third-party trackers report pricing in the same order of magnitude as direct OpenAI: **~$2.50 / 1M input tokens, ~$15.00 / 1M output tokens** ([AI Pricing Guru — OpenAI 2026](https://www.aipricing.guru/openai-pricing/), [OpenAI API pricing](https://openai.com/api/pricing/)). OCI may apply a multiplier or character-conversion; consider these pessimistic-side-of-realistic numbers.

**For budgeting, use:** input $2.50/1M tokens, output $15/1M tokens. These are the most defensible public figures; we will validate against the actual OCI line-items after the first week.

### C.2 Token math: per-day estimate for V1 (A1 architecture)

Assumptions:
- Fact pack: ~6 sections × ~10 rows × ~30 tokens/row JSON ≈ **1,800 tokens**.
- System prompt + role/preamble: ~500 tokens.
- Hypothesizer call: ~2,300 input + ~700 output (10 hypotheses × ~70 tokens) = **3,000 tokens**.
- Per-insight synthesis: hypothesis (~70 t) + supporting rows (~300 t) + system (~400 t) input ≈ 800 t; output ~500 t. Total per insight ≈ **1,300 tokens**.
- 7 insights × 1,300 = **9,100 tokens**.
- Embedding dedup: 7 headlines × text-embedding-3-large (3072-d, ~50 input tokens, no output) — embedding pricing on the order of $0.13/1M tokens — negligible.

**Per-day total ≈ 12 K tokens.** Mostly input (≈ 9 K) and output (≈ 3 K).

**Per-day cost ≈ 9K × $2.50/1M + 3K × $15/1M = $0.0225 + $0.045 ≈ $0.07/day.**

**Per-year cost ≈ $25.** Even with a 5–10× model error, well under $300/year.

### C.3 One mega synthesis call vs 7 separate calls

| Shape | Input tokens | Output tokens | Pros | Cons |
|---|---|---|---|---|
| One mega call (fact pack + "produce 7 insights") | ~2,800 | ~3,500 | Cheaper (single system prompt amortised); model can self-coordinate ordering and avoid intra-day duplication; one rate-limit slot | Harder to retry-on-partial-failure; structured-output schema must be a list; one bad insight invalidates the batch unless schema is robust |
| 7 separate calls | ~5,600 | ~3,500 | Each call is independent; one bad insight is recoverable; SSE streaming has natural per-insight chunks | ~2× input tokens (system prompt repeated 7×); 7 rate-limit slots; intra-day dedup must be done in Python because each call is blind to the others |

**Recommendation: one mega synthesis call** with a JSON-schema response wrapper of shape `{insights: [InsightOutput, ...]}`, **plus the existing in-memory dedup pass** to reject any same-call near-duplicates. We get the cost and intra-batch-coordination wins, and we keep the 7-event SSE UX by *streaming events as we parse the response* rather than as we call the model. This is consistent with how `weekly_brief` already does a single call.

If reliability requires retries: keep the mega call but add a one-shot reissue of *only the failed indices* on JSON-parse failure.

### C.4 Hard daily token budget and enforcement

Recommend a **hard ceiling of 30,000 tokens per `insights_daily` run** (≈ 2.5× the median estimate). Enforcement layers:

1. **Static caps in code:**
   - `FACT_PACK_MAX_ROWS_PER_SECTION = 12` (hypothesizer truncates).
   - `MAX_HYPOTHESES = 10` (already `V1_MAX_HYPOTHESES`).
   - `MAX_INSIGHTS = 7` (orchestrator default).
   - `MAX_SUPPORTING_ROWS_PER_INSIGHT = 8` (synthesis prompt truncates).
2. **Pre-flight token estimate:** `tiktoken` or `len(prompt)//4` heuristic before the OpenAI call; if `> 25K input tokens`, drop low-priority fact-pack sections (coverage_gaps first, then EDGAR mentions) until under cap.
3. **Post-flight accounting:** record `prompt_tokens`, `completion_tokens` from the API response onto a new column or onto `skill_invocation.outputs->>'usage'`; sum per session into `ai_session.token_estimate` (currently nullable on `agent_tool_call`; add a column to `ai_session` in a follow-up migration).
4. **Daily aggregate guard:** before scheduling tomorrow's run, check `SELECT SUM(token_estimate) FROM ai_session WHERE started_at > now() - interval '24h'`. If anomalous (>3× rolling 14-day mean), page operators and downgrade to a "no-op heartbeat" that just records freshness without LLM calls.

This is consistent with industry guidance that "production agent loops use multiple stopping conditions layered together — maximum iteration limits, token and cost budgets, no-progress detection, and goal-achievement checks" ([Zylos Token Economics](https://zylos.ai/research/2026-02-19-ai-agent-cost-optimization-token-economics)).

---

## D. Deduplication strategy across days

### D.1 What the codebase already gives us

- **pgvector is installed** — migration 009 runs `CREATE EXTENSION IF NOT EXISTS vector;` and the `skill_reference` table uses `vector(3072)` with text-embedding-3-large. So pgvector ANN/cosine queries against persisted vectors are available out of the box.
- **`ai_insight.headline_embedding`** already exists, but is currently typed as `Text` with the migration comment: *"store as text in V1; dedup writes vector via raw SQL"* (line 93 of 009_ai_insights.py).
- **In-session dedup is wired** — `dedup.is_duplicate` already does Jaccard pre-filter + cosine 0.85 against an in-memory `_emitted_headlines` list that is currently populated only within the same session (orchestrator line 167, line 468). It does NOT yet read yesterday's headlines.

### D.2 Comparison

| Option | Cost / run | Latency / run | Implementation effort | Quality | Failure mode |
|---|---|---|---|---|---|
| D1 — pgvector cosine vs prior 7 days | 7 embed calls (already paid in §C) + one SQL `SELECT ... ORDER BY embedding <=> :v LIMIT 5` per insight | <50 ms per insight (3072-d sequential scan over ~50 rows is fine; HNSW later) | Low — change column type to `vector(3072)`, swap one Python comparison for a SQL one | High; established pattern | Embedding API outage → fall back to Jaccard |
| D2 — LLM-judge "is this the same story as yesterday?" | +1 LLM call/run (~1K tokens) or +N tokens to the existing mega-call | ~1 s | Medium — prompt design, output validation | Medium; model can rationalise too aggressively (false negatives) or be too literal (false positives) | Model failure forces accept-as-novel; no clear regression on cost |
| D3 — Heuristic on (entity, metric, direction) tuple | ~0 | ~0 | Medium-high — must extract structured `(entity, metric, direction)` from the headline reliably | Brittle; fails on cross-entity narratives ("hyperscalers slow nuclear PPAs") | Schema drift |

### D.3 Recommendation: **D1 pgvector, with the existing Jaccard pre-filter kept as a cheap first pass**

Reasoning:
- pgvector is already installed; the column already exists; the dedup module already computes cosine — this is the *least new code* path.
- The 0.85 cosine threshold is already ratified in PRD §5.1 (per orchestrator line 84) and tested.
- Embedding cost is already in the budget; reusing the embedding for cross-day dedup costs nothing extra.
- It composes naturally with D2 as a tiebreaker if we ever want one: pgvector returns top-k near-duplicates, then a model judges *only* the borderline 0.80–0.85 band.

**Migration steps (planning, not code):**

1. Alter `ai_insight.headline_embedding` from `Text` to `vector(3072)`. Backfill is empty (table is new). Add an `ivfflat` or `hnsw` index keyed on `vector_cosine_ops` once we exceed ~500 rows; until then, sequential scan is fine.
2. In `dedup.py`, add `async def fetch_recent_embeddings(db, since: datetime, limit: int) -> list[tuple[str, list[float]]]` that pulls rows from `ai_insight` joined to `ai_session` where `ai_session.status = 'complete' AND ai_session.started_at >= now() - interval '14 days'`.
3. In the orchestrator, before iterating insights, prime `self._emitted_headlines` with the result of step 2. The existing `is_duplicate()` works unchanged.
4. When a duplicate is rejected today, persist a row anyway with a new flag `ongoing_of_id UUID NULL REFERENCES ai_insight(id)` so the UI can show "X — ongoing since DATE" instead of dropping the data point. (This is an additive migration.)

**Why not D2 alone:** a model judging "still the dominant story" introduces stochasticity into a behaviour users will notice (today's run shows the same insight as yesterday — or doesn't — based on model temperature). D1 is deterministic given the input; engineers and users can reason about the threshold.

**Why not D3 alone:** the headlines we generate cross multiple entities and metrics ("Microsoft and Meta both upsized 2026 capex while Google trimmed permits"). Tuple-based heuristics will under-fire on these.

---

## E. Headless invocation pattern

### E.1 The constraint

`InsightOrchestrator.run_session` is an `AsyncIterator[_SSEBase]` — designed to back an SSE endpoint. The scheduled job has no SSE consumer; the events must be drained server-side and only their persistence side-effects matter.

### E.2 The pattern, ground-truthed against the existing runner

`pipeline/runner.py:_invoke_anomaly_detection` (line 235) and `_invoke_weekly_brief` (line 344) both follow the same shape:

```
async with async_session_factory() as session:    # provided by _run_adapter_job
    result = await some_agent_function(session)   # awaits to completion
    await session.commit()
```

The insights job mirrors that, with the additional step of consuming the async iterator:

```
async def _invoke_insights_daily(session) -> dict:
    from agents.insights.orchestrator import InsightOrchestrator
    import uuid
    sid = uuid.uuid4()
    orch = InsightOrchestrator(session_id=sid, db=session, llm=llm_client)
    insights_emitted = 0
    async for ev in orch.run_session(filters={"focus": "daily-cron"}):
        # Persistence happens inside the orchestrator already (_persist_insight,
        # _persist_session_finish). We just need to drain the iterator.
        if isinstance(ev, InsightCompleteEvent):
            insights_emitted += 1
    return {"fetched": 0, "stored": insights_emitted}
```

Then in `runner.py`:

```
JOB_CONFIG["insights_daily"] = {
    "adapter": "insights_daily",
    "trigger": CronTrigger(hour=9, minute=0),
    "phase": 2,
}
async def run_insights_daily_job() -> None:
    await _run_adapter_job("insights_daily", _invoke_insights_daily)
_JOB_FUNCTIONS["insights_daily"] = run_insights_daily_job
```

This gives us the existing `IngestionRun` audit row for free, on top of the `AISession` row the orchestrator persists.

### E.3 Watch-outs

- **The orchestrator already commits/flushes on its own** via `await self.db.flush()`. The wrapper does the final `await session.commit()`. Don't double-commit mid-stream from inside the orchestrator's helpers.
- **Cancellation is unused server-side.** `cancel()` is for the user-driven SSE path. No need to wire it for the cron.
- **No StreamingResponse, no `to_sse_text`.** Drop the SSE serializer; the iterator yields native events and we throw them away after counting.
- **The "ingestion_runs" row will say `records_stored = N insights`.** That's a slight semantic stretch — consider also writing a `summary_log` or extending the IngestionRun schema later. For V1 it's fine.

---

## F. Failure handling

### F.1 APScheduler-side errors

Wire two listeners on the scheduler in `create_scheduler()` (call out, not code):

- `EVENT_JOB_ERROR` — log `event.exception` + `event.traceback` with structured fields `{job_id, scheduled_run_time}`. Optionally fan out to Sentry / OCI Logging.
- `EVENT_JOB_MISSED` — log a WARN with `job_id`. This fires when `misfire_grace_time` lapsed — it's how we'll learn the scheduler is starved.
- Optionally `EVENT_JOB_MAX_INSTANCES` — if it ever fires, the previous run is still going; investigate before it becomes a silent dropper.

### F.2 Orchestrator-side errors

The orchestrator already has the right shape:

- Top-level try/except in `run_session` (line 269) emits an `error` + `session_complete` and calls `_persist_session_finish(status="failed", ...)`.
- Per-insight `insight_synthesis_failed` (line 405) emits an `error` and `continue`s to the next insight without poisoning the session.
- `_persist_*` helpers are wrapped to "never hard-fail the stream on DB issues" (line 563).

For the cron path, we want **two additions**:

1. **A wall-clock guard outside the orchestrator** — the cron should also wrap with `asyncio.wait_for(orch.run_session(...), timeout=600)` (slightly larger than the internal 480 s `V1_WALL_CLOCK_S`) so a hung LLM call cannot block the next day's job. On `TimeoutError`, mark the AISession failed and let the next firing pick up clean.
2. **Explicit `ai_session.status='failed'` write on uncaught exceptions** — already covered by `_terminate("error", ...)` for code paths inside `run_session`, but the wrapper should also UPDATE the row if the iterator itself raises before any `_persist_session_finish` runs.

### F.3 SQLAlchemy session lifecycle on long jobs

- One session for the lifetime of one orchestrator run is fine (the orchestrator does many small flushes, not one giant transaction).
- Never share that session with another concurrent task spawned via `asyncio.gather`.
- On exception, **rollback then close** — `_run_adapter_job` already relies on `async with` cleanup.
- The orchestrator's `_persist_*` use `flush()` rather than `commit()`, deferring the durable write — good. Make sure no new persistence helper calls `commit()` from inside a phase.
- Add an idle-in-transaction monitor — set `pool_pre_ping=True` on the engine if not already, and consider `statement_timeout` at the Postgres role level (e.g., `ALTER ROLE app SET statement_timeout = '30s'`). A 30 s SQL statement is anomalous for our queries and will leak through the LLM 480 s budget.

---

## G. Recommendations summary (drop-in for the design doc)

| # | Question | Recommendation | One-line rationale |
|---|---|---|---|
| 1 | Synthesis pipeline (V1) | **A1 — Deterministic fact pack → single mega-call synthesis** | Mirrors in-tree `weekly_brief.py`; cheapest, most testable, dedup-friendly |
| 2 | Synthesis pipeline (V1.1) | **A3 — Hybrid with a single bounded `drill_down` per insight** | Adds surprise value once we have a baseline to measure against |
| 3 | Scheduler | **APScheduler — add `insights_daily` to `JOB_CONFIG`** | Already running 10 jobs with `IngestionRun` audit + Postgres-backed jobstore |
| 4 | Schedule slot | **`CronTrigger(hour=9, minute=0)` UTC** | After all daily ingest jobs finish (last is EPA at 08:00) |
| 5 | misfire_grace_time | **3600 s** | Same as other dailies; LLM can't run early-morning ingest gaps |
| 6 | coalesce / max_instances | **`coalesce=True`, `max_instances=1`** | Prevents pile-up across DST or restart storms |
| 7 | Idempotency guard | **Top-of-job check: skip if `AISession` exists today with `created_by='scheduler'` and `status in ('running','complete')`** | Defense in depth above scheduler-level coalesce |
| 8 | LLM call shape | **One mega synthesis call (JSON-schema list output)** + per-insight SSE event fan-out from parsed result | Cheaper, intra-batch coherence, still 7 SSE events |
| 9 | Daily token budget | **Hard ceiling 30 K tokens/run; soft target ~12 K** | ~$0.07/day at gpt-5.4 list pricing; ~$25/year |
| 10 | Token-budget enforcement | **Static row caps + pre-flight `tiktoken` estimate + post-flight `usage` accounting on `ai_session`** | Layered stopping conditions, industry standard |
| 11 | Cross-day dedup | **D1 — pgvector cosine vs last 14 days, threshold 0.85** | pgvector already installed; `headline_embedding` column already exists; reuses ratified threshold |
| 12 | Dedup migration | **`ALTER COLUMN headline_embedding TYPE vector(3072)` + add `ongoing_of_id` FK** | Two small additive migrations; existing dedup code change is one-line |
| 13 | Headless invocation | **Drain `orch.run_session()` inside `_invoke_insights_daily(session)`, count `InsightCompleteEvent`s** | Mirrors `_invoke_anomaly_detection` / `_invoke_weekly_brief` exactly |
| 14 | Wall-clock guard | **Wrap with `asyncio.wait_for(..., timeout=600)`** | Slightly above orchestrator's internal 480 s cap |
| 15 | Failure persistence | **APScheduler `EVENT_JOB_ERROR` + `EVENT_JOB_MISSED` listeners; explicit `ai_session.status='failed'` on outer exception** | Covers iterator-raise-before-finish gap |
| 16 | DB session shape | **One AsyncSession per cron firing; `flush()` mid-stream, single `commit()` on exit** | SQLAlchemy 2.0 async best practice |
| 17 | Operational guardrail | **Statement-timeout at Postgres role level (e.g., 30 s)** | Caps a hung SQL from inside the fact pack |
| 18 | Future-proofing | **Add `token_estimate` column to `ai_session`** (follow-up migration) | Enables daily aggregate budget guard |

---

## H. Warnings / gotchas

- **`oci/openai.gpt-5.4` pricing is character-based, not token-based**, on OCI's infrastructure. The §C estimate uses OpenAI list prices as a defensible upper bound; verify against your first OCI billing statement and adjust the daily budget accordingly.
- **The mega synthesis call's structured output must round-trip through JSON-schema validation** — gpt-5 family models are reliable here, but plan for one retry on `json.JSONDecodeError`. Don't let a transient parse failure burn the whole run.
- **`headline_embedding` is currently `Text`** despite the column name promising a vector. Code that writes to it today will store a string; cross-day dedup will not work until the type is migrated. Catch this in CI with a smoke test that asserts `pg_type` for the column.
- **`is_duplicate` reads `_emitted_headlines` only from the in-memory list.** Until you prime that list from the DB at session start, cross-day dedup is silently a no-op even after the column type migration. The two changes must ship together.
- **APScheduler with `SQLAlchemyJobStore` requires a sync driver** — `runner._sync_database_url()` already converts `asyncpg` → `psycopg2`. Make sure `psycopg2-binary` stays in `pyproject.toml` deps; a removal would silently fall back to the in-memory job store and lose persistence across restarts.
- **`max_instances=1` is the default**, but if the daily run starts taking longer than 24 hours (unlikely but possible if the LLM endpoint thrashes), tomorrow's firing will be skipped with `EVENT_JOB_MAX_INSTANCES`. The wall-clock guard in §F.2 is what stops this; don't remove it.
- **`coalesce=True` collapses missed firings into one** — if the box was off for 3 days, recovery runs the job once, not three times. That is the correct behaviour for an insights cron. Document this explicitly so an operator who expects "catch-up" runs is not surprised.
- **`statement_timeout` set at the role level affects ALL queries that role runs**, including the FastAPI request handlers. If you set it, make sure it's high enough for any legitimate UI query.
- **The current `_phase_hypothesize_iter` only emits a `reasoning_step` event** (orchestrator line 350); when you wire in real hypothesizing, retain that single event so existing frontend SSE consumers don't see new event types they can't render.
- **Don't move `_persist_*` from `flush()` to `commit()`** mid-stream. The current design lets `_run_adapter_job` own the final commit and roll back the whole session on exception.
- **pgvector ANN indexes (ivfflat / hnsw) are not free** — building one on `ai_insight` while the table is hot will lock writes briefly. Defer the index until table size justifies it (~2,500 rows/year). Sequential scan is fine until then.

---

## I. Key references & links

- **Code (in-tree):**
  - `backend/agents/insights/orchestrator.py`
  - `backend/agents/insights/dedup.py`
  - `backend/agents/weekly_brief.py`
  - `backend/pipeline/runner.py`
  - `backend/alembic/versions/009_ai_insights.py`
- **APScheduler:**
  - [User guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html)
  - [Scheduler base API (events)](https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/base.html)
  - [SQLAlchemyJobStore](https://apscheduler.readthedocs.io/en/3.x/modules/jobstores/sqlalchemy.html)
  - [issue #499 — async pooling caveats](https://github.com/agronholm/apscheduler/issues/499)
- **SQLAlchemy async:**
  - [asyncio extension docs](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- **pgvector:**
  - [pgvector README](https://github.com/pgvector/pgvector)
  - [Cosine in pgvector](https://www.sarahglasmacher.com/how-to-use-cosine-similarity-in-pgvector/)
  - [Supabase pgvector guide](https://supabase.com/docs/guides/database/extensions/pgvector)
- **Embeddings:**
  - [OpenAI embeddings guide](https://developers.openai.com/api/docs/guides/embeddings)
- **LLM cost / agentic patterns:**
  - [OCI GenAI pricing](https://www.oracle.com/artificial-intelligence/generative-ai/generative-ai-service/pricing/)
  - [OCI on-demand inferencing pricing](https://docs.oracle.com/en-us/iaas/Content/generative-ai/pay-on-demand.htm)
  - [OpenAI API pricing](https://openai.com/api/pricing/)
  - [AI Pricing Guru — OpenAI 2026](https://www.aipricing.guru/openai-pricing/)
  - [Token Cost Trap — Klaus Hofenbitzer](https://medium.com/@klaushofenbitzer/token-cost-trap-why-your-ai-agents-roi-breaks-at-scale-and-how-to-fix-it-4e4a9f6f5b9a)
  - [Zylos — Agent Cost Optimization & FinOps](https://zylos.ai/research/2026-02-19-ai-agent-cost-optimization-token-economics)
  - [Barnacle — 4 Levels of AI Agents](https://www.barnacle.ai/blog/2025-09-25-agents-intro)
- **FastAPI / async testing:**
  - [FastAPI Async Tests](https://fastapi.tiangolo.com/advanced/async-tests/)
