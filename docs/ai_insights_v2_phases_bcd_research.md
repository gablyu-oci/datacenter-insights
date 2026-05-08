# AI Insights v2 — Phases B/C/D Research Memo

**Date:** 2026-05-07 · **Owner:** research-agent
**Scope:** SQL safety hardening, query timeouts/row caps, token-aware chunking, Postgres BM25, RRF, Pydantic v2 chart-spec validation, golden retrieval test set.
**Companion docs:** `docs/ai_insights_v2_spec.md`, `docs/ai_insights_v2_phase_a_research.md`, `docs/ai_insights_v2_phase_a_architecture.md`.

---

## 1. SQL Safety via AST Parsing — sqlglot vs pglast

### Research Question
Replace any residual regex-based filtering in `backend/agents/insights/tools/sql_gate.py` with a defensible AST-based approach. The current module already uses `sqlglot` for parse + walk; the question is whether to (a) stay on `sqlglot` and harden the visitor, or (b) migrate to `pglast` (libpg_query — the actual Postgres parser as a C library).

### Options Considered

| Dimension | sqlglot | pglast (libpg_query) |
|---|---|---|
| Parser fidelity | Hand-written recursive-descent supporting 30+ dialects; not a Postgres validator (will accept some non-Postgres SQL the server would reject) | Bundles the actual Postgres backend parser via libpg_query; what parses ≈ what Postgres parses |
| Install footprint | Pure Python (mypyc-compiled core in 25.x+ for speed); zero C deps; works in slim wheels | Cython + C extension; needs libpg_query toolchain; wheels exist but slimmer than sqlglot |
| AST stability | Public exp.* node classes; minor renames between majors (e.g. AlterTable→Alter at 30.x — already absorbed in our gate) | Mirrors Postgres parse-tree node names; very stable across Postgres versions |
| Walk ergonomics | tree.walk() yields nodes; isinstance checks against exp.Select / exp.Table / exp.With | Tree of dicts plus Node wrappers; visitor pattern via Visitor base class |
| Multi-statement handling | sqlglot.parse() returns a list per ; — easy "exactly one" check | parse_sql returns a list of RawStmt — same easy check |
| Already in our stack | Yes (`sqlglot>=30,<31` in `backend/requirements.txt`, used in `sql_gate.py`) | No |
| Operational risk | Subtle parsing differences vs Postgres are theoretically exploitable, but the gate is *allow-list by structure*, not *deny-list by string*, which neutralizes most bypasses | None — same parser as the server, so server-accepted attacks must also be in our AST |

### Recommendation — **Stay on sqlglot, but harden the visitor**

Switching to pglast for marginal parser-fidelity gain is not worth the C-toolchain risk in our containers, and the existing gate is already AST-based (not regex). Two structural risks remain that we should close in Phase B:

1. **Banned-schema/identifier checks must recurse into CTEs and subqueries.** sqlglot's `tree.walk()` already does, but the lookup uses `tbl.name` and walks `args.get("db") / args.get("catalog")`. Postgres allows three-part `catalog.schema.table` and quoted/case-mixed identifiers; we must lower-case both, and refuse anything where any *part* of the qualified name matches a banned schema or `pg_*` prefix.
2. **`ONLY`, table functions, and `LATERAL` subqueries** (`exp.Subquery`, `exp.Lateral`, `exp.TableFromRows`) are walked but the `Table` node may carry the unqualified function name — already covered by `_walk_funcs` for `pg_read_file`, `dblink`, etc., but worth a regression test.

#### Hardened sketch (for the memo, not for project files)

```python
import sqlglot
from sqlglot import exp

BANNED_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast"}
BANNED_PREFIXES = ("pg_",)

class SqlGateError(ValueError): ...

def _all_idents(table: exp.Table) -> list[str]:
    """Return [catalog, schema, name], lower-cased, '' for missing parts."""
    parts = []
    for key in ("catalog", "db"):              # db == schema in sqlglot
        node = table.args.get(key)
        parts.append(node.name.lower() if isinstance(node, exp.Identifier) else "")
    parts.append((table.name or "").lower())
    return parts

def validate_sql(sql: str, *, max_rows: int = 10_000) -> str:
    statements = sqlglot.parse(sql, dialect="postgres")
    if not statements:
        raise SqlGateError("parse_error: no statements")
    if len(statements) > 1:
        raise SqlGateError("multi_statement")
    tree = statements[0]
    if tree is None:
        raise SqlGateError("parse_error: None")

    # 1) Top-level SELECT (or WITH/UNION wrapping a SELECT).
    root = tree.this if isinstance(tree, exp.With) else tree
    if isinstance(root, exp.Union):
        if not all(isinstance(s, (exp.Select, exp.Union)) for s in (root.left, root.right)):
            raise SqlGateError("non_select_root")
    elif not isinstance(root, exp.Select):
        raise SqlGateError("non_select_root")

    # 2) No DDL/DML *anywhere* — covers CTEs and subqueries automatically.
    for node in tree.walk():
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Merge,
                             exp.Create, exp.Drop, exp.Alter, exp.AlterColumn,
                             exp.TruncateTable, exp.Grant, exp.Set, exp.Copy,
                             exp.Command, exp.Transaction, exp.Commit, exp.Rollback)):
            raise SqlGateError(f"disallowed_statement:{type(node).__name__}")

    # 3) Banned schema / pg_* in any FROM / JOIN / CTE / subquery.
    for tbl in tree.find_all(exp.Table):
        cat, schema, name = _all_idents(tbl)
        if schema in BANNED_SCHEMAS or cat in BANNED_SCHEMAS:
            raise SqlGateError(f"banned_schema:{schema or cat}")
        if any(part.startswith(p) for p in BANNED_PREFIXES for part in (name, schema)):
            raise SqlGateError(f"banned_table:{name}")

    # 4) Banned functions (already handled in current gate via _walk_funcs).
    # 5) LIMIT clamp/attach (already handled in current gate via _attach_limit).
    return tree.sql(dialect="postgres")
```

The crucial change vs today's gate is **explicit recursion into CTEs/subqueries via `tree.find_all(exp.Table)`** (which walks the whole tree, including the inner SELECT bodies of `exp.With`'s `expressions` list — sqlglot stores CTEs as `exp.CTE` nodes whose `.this` is a Select, all reachable from `walk`/`find_all`).

### Warnings
- sqlglot bumps majors fairly often; node renames have happened (`AlterTable`→`Alter`). Pin tightly (`>=30,<31`) and add a smoke test that loads the gate at import time so a wheel mismatch fails loudly.
- sqlglot does **not** validate SQL semantically. A query that references a non-existent table will still pass the gate. That's fine — Postgres will reject it. Our gate is about *shape*, not *correctness*.
- Do **not** rely on `to_sql()` round-tripping equivalence for security checks; always validate the parsed AST directly.

---

## 2. Postgres `statement_timeout` and Row Caps

### Research Question
Apply a hard 10-second statement timeout per AI-Insights query and a hard 10,000-row cap, idiomatically, in SQLAlchemy 2.x with the existing async + sync engines.

### Postgres facts
- `statement_timeout` aborts any statement exceeding the limit; integer is milliseconds; `0` = disabled.
- `SET LOCAL` is scoped to the **current transaction**; outside a transaction, `SET LOCAL` is silently a no-op and the session value applies. So `SET LOCAL statement_timeout = '10s'` is only meaningful when issued inside an explicit `BEGIN` (or SQLAlchemy `begin()` block).
- Setting in `postgresql.conf` is discouraged because it affects every session.

### Recommended pattern — explicit `with engine.begin()` + `SET LOCAL`

```python
from sqlalchemy import text

QUERY_TIMEOUT_MS = 10_000
HARD_ROW_CAP    = 10_000

def run_agent_query(engine, validated_sql: str, applied_limit: int):
    # validated_sql already includes a clamped LIMIT (see §1)
    with engine.begin() as conn:                       # one transaction
        conn.execute(text(f"SET LOCAL statement_timeout = {QUERY_TIMEOUT_MS}"))
        rs = conn.execute(text(validated_sql))
        # Cursor-side cap: defence-in-depth in case the LIMIT was stripped/transformed.
        rows = rs.fetchmany(HARD_ROW_CAP)
        if rs.fetchone() is not None:
            raise RuntimeError("row_cap_exceeded")
    return rows
```

#### Async variant

```python
async with engine.begin() as conn:
    await conn.execute(text(f"SET LOCAL statement_timeout = {QUERY_TIMEOUT_MS}"))
    rs = await conn.execute(text(validated_sql))
    rows = rs.fetchmany(HARD_ROW_CAP)
```

For asyncpg specifically, you can *also* use connection-level `command_timeout` at engine creation as a belt-and-braces guard, but `SET LOCAL` is the portable answer that works on psycopg2/3 and asyncpg.

### LIMIT injection vs cursor cap — recommended approach

Use **both**, layered:

1. **Inject a `LIMIT 10000` at parse time** (the gate already does `_attach_limit`). This means Postgres itself stops producing rows; the planner can use the limit to prune work. *This is the primary control.*
2. **Cursor-side `fetchmany(HARD_ROW_CAP)` followed by a "is there more?" probe**, raising on overflow. This is defence-in-depth: a query that wraps `LIMIT` inside an unintended subquery, or a `UNION ALL` that produces more than the outer limit (it shouldn't, but assume nothing) is still caught.

A pure cursor cap without LIMIT injection is wrong — Postgres still **executes** the full plan and only stops streaming when the client stops reading. For aggregations over big tables that's wasted CPU and a DoS vector.

### Warnings
- A bare `SET statement_timeout` (without `LOCAL`) leaks into the connection and persists across checkouts from the pool. Always use `SET LOCAL` or wrap your own teardown with `RESET statement_timeout`.
- `SET LOCAL` *outside* a transaction is silently ignored. Verify in tests with an obviously-too-low value (e.g. `1ms`) and a query that would otherwise succeed; assert it raises.
- Postgres 17 introduces `transaction_timeout` as a stricter sibling — useful future hardening, but not required here.

---

## 3. Token-Aware Chunking (~300 tokens, ~50 overlap)

### Recommendation — **tiktoken with `cl100k_base`, fall back to word-count if not installed**

The 5–10% drift between `cl100k_base` and OCI Cohere's tokenizer is irrelevant at this granularity (we're targeting 300 ± a few). What matters is that chunk lengths are **stable across reindexing runs** so passage IDs remain comparable, which both options give us; tiktoken just gives tighter bounds on the BM25 index size.

#### Sketch

```python
from typing import Iterable

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    def _count(text: str) -> int: return len(_ENC.encode(text))
    def _decode(tokens: list[int]) -> str: return _ENC.decode(tokens)
    def _encode(text: str) -> list[int]: return _ENC.encode(text)
    _MODE = "tiktoken"
except ImportError:
    _MODE = "word"
    def _count(text: str) -> int: return max(1, int(len(text.split()) / 0.75))

def chunk_text(text: str, *, target_tokens: int = 300, overlap: int = 50) -> Iterable[str]:
    """Yield ~target_tokens chunks with ~overlap-token overlap.

    tiktoken path: token-exact slicing.
    Fallback path: word-window approximation (0.75 words ≈ 1 token).
    """
    if not text or not text.strip():
        return
    if _MODE == "tiktoken":
        toks = _encode(text)
        step = target_tokens - overlap
        if step <= 0:
            raise ValueError("overlap must be < target_tokens")
        for start in range(0, len(toks), step):
            window = toks[start : start + target_tokens]
            if not window:
                break
            yield _decode(window)
            if start + target_tokens >= len(toks):
                break
    else:
        words = text.split()
        target_words = int(target_tokens * 0.75)
        overlap_words = int(overlap * 0.75)
        step = max(1, target_words - overlap_words)
        for start in range(0, len(words), step):
            window = words[start : start + target_words]
            if not window:
                break
            yield " ".join(window)
            if start + target_words >= len(words):
                break
```

### Warnings
- Always **encode → slice → decode** when using tiktoken. Slicing the original string by character offsets and then re-counting will produce off-by-N drift across chunks.
- Persist the tokenizer name + chunk params alongside each chunk's row in `passages`. If you switch encoders, you must reindex — silent encoder swaps break recall@k comparisons.
- Empty-string input must be a no-op, not raise. Add a regression test.
- For markdown/HTML, strip front-matter and `<script>`/`<style>` before chunking; otherwise BPE eats far more tokens than the human-readable length suggests.

---

## 4. Postgres BM25-ish Full-Text Search via tsvector

### Recommendation Snapshot
- **Index**: GIN on a generated `tsvector` column (preferred) or on `to_tsvector('english', body)` directly.
- **Query parser**: `websearch_to_tsquery` (handles `"quoted phrases"`, `OR`, leading `-` for NOT, and **never raises on bad input** — safe for raw user/agent text).
- **Rank**: `ts_rank_cd(tsv, query, 32)` — cover-density (proximity-aware) rank, normalized to `rank/(rank+1) ∈ [0,1)`.

#### DDL

```sql
ALTER TABLE passages
  ADD COLUMN tsv tsvector
  GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(body,  '')), 'B')
  ) STORED;

CREATE INDEX passages_tsv_gin ON passages USING gin (tsv);
```

#### Query

```sql
WITH q AS (
  SELECT websearch_to_tsquery('english', :user_query) AS query
)
SELECT
  p.id,
  ts_rank_cd(p.tsv, q.query, 32) AS rank
FROM passages p, q
WHERE p.tsv @@ q.query
ORDER BY rank DESC
LIMIT :k;
```

### `websearch_to_tsquery` vs `plainto_tsquery`

**Recommend `websearch_to_tsquery` unconditionally.** Agents and humans alike will write quoted phrases (`"colocation agreement"`) and we want phrase-precision. There is no downside vs `plainto_tsquery`.

### `ts_rank_cd` vs `ts_rank`

- `ts_rank` is term-frequency only.
- `ts_rank_cd` is **cover density** — it boosts documents where matching terms appear close to each other. For our use case ("Crusoe Wyoming uncontracted MW"), proximity is exactly what we want.
- `normalization=32` adds the rescale `rank / (rank + 1)` so ranks fit `[0,1)`. This **does not change ordering**; it only makes the score easier to display, log, and combine with vector cosine scores in RRF/hybrid.

### Performance on ~50K passages

- A GIN index on `tsv` typically gives **<10ms** index lookup at this scale; the bottleneck moves to `ts_rank_cd` evaluation.
- The well-known cliff: when `LIMIT k` is small but the matched set is large, Postgres has to compute rank for *all* matches before sort. Mitigation: always pass a tight `LIMIT`.
- BM25 proper is *not* native to Postgres. Don't take that dependency in Phase B; revisit in Phase D if recall@10 < 0.7.

---

## 5. Reciprocal Rank Fusion (RRF) — Phase B.2 only if needed

### Brief Explanation
RRF (Cormack, Clarke & Buettcher, SIGIR 2009) — uses ranks only:

```
RRFscore(d) = Σᵢ 1 / (k + rankᵢ(d))
```

**`k = 60` is the original paper's default** and remains the de-facto choice (Elastic, OpenSearch, Vespa, LangChain, LlamaIndex all default to 60).

#### Sketch

```python
def rrf(rankings: list[list[str]], *, k: int = 60, top_n: int = 25) -> list[tuple[str, float]]:
    """rankings = list of ordered passage_id lists, best-first."""
    scores: dict[str, float] = {}
    for ranks in rankings:
        for rank, pid in enumerate(ranks, start=1):
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
```

### Recommendation
Do **not** ship RRF in Phase B.1 — single-retriever BM25 is enough to establish the recall floor. Add RRF in Phase B.2 only if BM25 alone is below threshold.

---

## 6. Pydantic v2 Chart-Spec Validation — confirmation only

**Yes — Pydantic v2 with a discriminated union on `chart_type` plus a `model_validator(mode="after")` for cross-field invariants is the right tool.**

#### Sketch

```python
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator

class _BaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    x: "EncodingChannel"
    y: "EncodingChannel"

class BarSpec(_BaseSpec):
    chart_type: Literal["bar"]

class StackedBarSpec(_BaseSpec):
    chart_type: Literal["stacked_bar"]
    series: list[str]
    @model_validator(mode="after")
    def _series_nonempty(self):
        if not self.series:
            raise ValueError("stacked_bar requires non-empty series")
        return self

class LineSpec(_BaseSpec):
    chart_type: Literal["line"]
    @model_validator(mode="after")
    def _x_is_temporal(self):
        if self.x.kind != "temporal":
            raise ValueError("line requires temporal x")
        return self

ChartSpec = Annotated[
    Union[BarSpec, StackedBarSpec, LineSpec],  # extend with all 16
    Field(discriminator="chart_type"),
]
```

### Warnings
- Discriminated-union validation is **ignored inside `Sequence[...]`** in some Pydantic versions. If a parent model contains `charts: list[ChartSpec]`, validate by wrapping in `TypeAdapter(list[ChartSpec])`.
- `model_validator(mode="after")` returns `self`. Returning `None` is a silent footgun.
- Keep `extra="forbid"` everywhere; the agent will hallucinate fields and we want loud failure, not silent drift.

---

## 7. 30-Pair Golden Retrieval Test Set

### Format — JSONL, one pair per line

```jsonl
{"id": "g001", "claim": "Crusoe's Wyoming campus has uncontracted capacity for new tenants in 2025.", "expected_passage_id": "psg_2025_q3_crusoe_10q_p042", "tags": ["uncontracted", "crusoe", "wyoming"]}
```

Stored at `backend/tests/golden/document_retrieval_recall.jsonl`.

### Scoring — Recall@k (binary, mean-aggregated)

```
recall@k(pair) = 1 if expected_passage_id ∈ retriever.top_k(claim) else 0
mean_recall@k = mean over all 30 pairs
```

Spec threshold to ship Phase B without B.2: **mean recall@8 ≥ 0.85**.

### Scenario coverage — required slices (~5 pairs each)

1. **High-value uncontracted-capacity claims** (Crusoe Wyoming, Stack Stockholm).
2. **Hyperscaler offtake announcements** (MSFT/Meta/GOOG/AMZN × specific provider).
3. **EPA ECHO permits without a named buyer.**
4. **Abandoned permits / withdrawn applications.**
5. **Multi-quarter contract amendments.**
6. **Reserve slot for adversarial / out-of-distribution claims** (abstention test).

### Warnings
- 30 pairs is a **floor**, not a ceiling. CIs are wide (±0.15 at 95%). Treat as smoke screen and grow to 100+ pairs as a Phase D goal.
- Pin passage IDs to a content hash, not a row id, so reindexing doesn't silently break expected IDs.
- Never let the agent that generated the SQL/answer also pick the gold passage.

---

## Aggregate Warnings / Gotchas

1. The SQL gate is structural, not semantic. Defence-in-depth across gate + row cap + statement timeout is the design.
2. `SET LOCAL` outside a transaction is silently a no-op. Always wrap in `engine.begin()`.
3. GIN indexes invalidate on column type changes.
4. Tokenizer changes invalidate passage IDs. Pin tokenizer name + chunk params per row.
5. 30-pair golden tests have wide CIs. Don't treat single-point swings as regressions.
6. Pydantic v2 discriminated unions don't auto-discriminate inside `list[...]` in some 2.x versions — use `TypeAdapter`.
7. sqlglot major bumps rename AST nodes. Pin tightly and add an import-time smoke test.

---

## Key References

- [tobymao/sqlglot](https://github.com/tobymao/sqlglot)
- [pglast docs](https://pglast.readthedocs.io/en/stable/)
- [Postgres §19.11 statement_timeout](https://www.postgresql.org/docs/current/runtime-config-client.html)
- [Postgres §12.3 Text Search Controls](https://www.postgresql.org/docs/current/textsearch-controls.html)
- [openai/tiktoken](https://github.com/openai/tiktoken)
- [Cormack 2009 — RRF](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf)
- [Pydantic — Unions](https://docs.pydantic.dev/latest/concepts/unions/)
- [VectorChord — Postgres FTS performance](https://blog.vectorchord.ai/postgresql-full-text-search-fast-when-done-right-debunking-the-slow-myth)

---

**End of memo.**
