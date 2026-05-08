# AI Insights v2 — Phase A Research Brief

**Date:** 2026-05-07 · **Owner:** research-agent · **Scope:** spec §3, §4.1, §4.2, §4.4, §5.1, §8 Phase A

## 1. SQLAlchemy / SQLModel metadata introspection

**Recommendation: walk `Base.metadata.tables` (in-process), not `Inspector` (DB round-trip).**
We already have authoritative `SQLModel.metadata` at process start; the Inspector reflects the live DB and adds latency + DB-permission requirements we don't need for SCHEMA.md generation.

One-liner:
```python
for table in Base.metadata.sorted_tables:        # FK-ordered
    for col in table.columns:
        col.name, str(col.type), col.nullable, col.primary_key
    for fk in table.foreign_keys:
        fk.column.table.name, fk.column.name      # target side
```

**Pitfalls:**
- **PostGIS / GeoAlchemy2 `Geometry`** — `str(col.type)` emits e.g. `geometry(POINT,4326)`. Fine for documentation, but Inspector-based reflection of an existing DB will fail to map `geometry` unless GeoAlchemy2 is imported (which registers the type) or you hook `column_reflect`. Walking `metadata.tables` sidesteps this entirely.
- **`Enum`** — render as `enum(values=...)` not just `VARCHAR`. Use `col.type.enums` if `isinstance(col.type, sqlalchemy.Enum)`. PG `CREATE TYPE` enums are independently reflectable.
- **`JSONB`** — `str(JSONB())` yields `JSONB`; that's all we need for the doc.
- **`ARRAY(...)`** — render the inner item type explicitly.
- Mixed `SQLModel` and `SQLAlchemy` `Base` — make sure both metadata objects are registered. In this repo, models import via `db/models.py` so `from db.models import *` (already done in env.py) suffices to populate `SQLModel.metadata`.

For row counts use a separate `SELECT count(*)` per table — Inspector doesn't give counts, and `pg_class.reltuples` is approximate.

## 2. Alembic post-upgrade hook pattern

**Recommendation: approach (a) — call `refresh_schema_doc.main()` from `env.py` after `context.run_migrations()` in `run_migrations_online`.** Simple, deterministic, fires exactly once per `alembic upgrade head` invocation, runs in our app's interpreter so `Base.metadata` is already imported.

```python
# backend/alembic/env.py — run_migrations_online
def run_migrations_online():
    ...
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        # POST-UPGRADE HOOK — runs after txn commits
        if os.environ.get("ALEMBIC_SKIP_POST_HOOKS") != "1":
            from scripts.refresh_schema_doc import main as refresh
            try:
                refresh()
            except Exception as exc:
                logging.getLogger("alembic.post").warning("refresh_schema_doc failed: %s", exc)
```

Add the env-var escape hatch so CI test fixtures and `alembic stamp` don't trigger it.

**Footgun: `post_write_hooks` (the trap).** The `[post_write_hooks]` section in `alembic.ini` runs ONLY on `alembic revision` (file generation, e.g. `ruff format` on the new migration file). It does NOT fire on `upgrade`. Document this in the env.py comment so future contributors don't move it.

**Alternative considered:** `EnvironmentContext.configure(on_version_apply=...)` fires per-migration-step, not at end-of-upgrade. To run only "after the last step" you'd compare the step against the head — strictly worse than a single call after `context.run_migrations()`.

## 3. APScheduler CronTrigger — daily 02:00 UTC

We already use APScheduler with a Postgres job store (`backend/pipeline/runner.py`, `JOB_CONFIG`). New job slots cleanly:

```python
# backend/pipeline/runner.py — append to JOB_CONFIG
"freshness_doc_daily": {
    "adapter": "_freshness_doc_refresh",
    "trigger": CronTrigger(hour=2, minute=0, timezone="UTC"),  # 0 2 * * *
    "phase": 1,
    "enabled": True,
},
```

```python
# add to _JOB_FUNCTIONS map
_JOB_FUNCTIONS["freshness_doc_daily"] = run_freshness_doc_job

async def run_freshness_doc_job() -> None:
    await _run_adapter_job("_freshness_doc_refresh", _invoke_freshness_doc_refresh)

async def _invoke_freshness_doc_refresh(session) -> dict:
    from scripts.refresh_freshness_doc import refresh
    return await refresh(session)
```

**Why `timezone="UTC"` explicitly:** the scheduler's default tz is process-local. UTC dodges DST entirely. Misfire grace 1h + `coalesce=True` already handled by `create_scheduler()`.

## 4. Path-traversal-safe file reads (`read_workspace`)

For an MCP tool with a *fixed* allowlist of two filenames, prefer the explicit literal check over generic resolve()/is_relative_to(). It is shorter, has no symlink-confusion edge case, and is trivially auditable.

```python
ALLOWED = {"SCHEMA.md", "FRESHNESS.md"}
WORKSPACE = Path(".openclaw/workspace").resolve()
MAX_BYTES = 16 * 1024

async def read_workspace(file: str, ctx) -> dict:
    if file not in ALLOWED:                              # explicit literal
        return {"ok": False, "error": "file_not_allowed"}
    target = (WORKSPACE / file).resolve()
    if not target.is_relative_to(WORKSPACE):             # belt + suspenders
        return {"ok": False, "error": "path_traversal"}
    if not target.is_file():
        return {"ok": False, "error": "not_found"}
    raw = target.read_bytes()
    truncated = len(raw) > MAX_BYTES
    body = raw[:MAX_BYTES].decode("utf-8", errors="replace")
    return {"ok": True, "content": body, "truncated": truncated}
```

**Why byte-truncation, not char-truncation:** UTF-8 is multi-byte. Slicing on character index can still produce strings whose serialized form exceeds the cap; slicing on byte index then decoding with `errors="replace"` guarantees a hard ≤16KB ceiling and only mangles the *single* boundary character (becomes U+FFFD), which is fine for markdown.

## 5. MEMORY.md section parsing

OpenClaw writes section headers as `## <Title>` and entries as `- <text>  _<YYYY-MM-DD>_` (see `.openclaw/workspace/MEMORY.md`). The dreaming-promotion block adds an HTML comment marker and a `[score=... source=...]` suffix.

**Recommendation: regex-locate the section, then iterate non-empty bulleted lines.**

```python
import re

DATE_SUFFIX_RE = re.compile(r"\s+_<?(\d{4}-\d{2}-\d{2})>?_\s*$")
SCORE_SUFFIX_RE = re.compile(r"\s*\[score=[^\]]+\]\s*$")

def parse_open_questions(md: str) -> list[dict]:
    pattern = re.compile(
        r"^##\s+open[\s_-]*questions\b.*?$(?P<body>.*?)(?=^##\s|\Z)",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(md)
    if not m:
        return []
    by_id = {}
    for line in m.group("body").splitlines():
        line = line.strip()
        if not line.startswith(("-", "*")):
            continue
        line = line.lstrip("-* ").rstrip()
        date_match = DATE_SUFFIX_RE.search(line)
        last_seen = date_match.group(1) if date_match else None
        line = DATE_SUFFIX_RE.sub("", line)
        line = SCORE_SUFFIX_RE.sub("", line).strip()
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            continue
        qid, status, materiality, note = parts[0], parts[1], parts[2], "|".join(parts[3:]).strip()
        prev = by_id.get(qid)
        if prev is None or (last_seen and last_seen >= (prev.get("last_seen_iso") or "")):
            by_id[qid] = {
                "id": qid, "status": status, "materiality": materiality,
                "latest_note": note, "last_seen_iso": last_seen,
            }
    return list(by_id.values())
```

**Key robustness points:**
- The `_<YYYY-MM-DD>_` suffix style varies (`_<2026-05-07>_` and `_2026-05-07_` both seen) — the regex tolerates the optional `< >`.
- HTML-comment promotion markers (`<!-- openclaw-memory-promotion:... -->`) are not bullet lines → skipped.
- Lines without 4 pipe-fields silently skipped (legacy free-form bullets in §"Threads to revisit").
- Group-by-`id` keeping the most recent `last_seen_iso` matches §4.4 contract.

## 6. Golden-file pytest pattern

**Recommendation: hand-rolled fixture comparison. Skip syrupy and pytest-snapshot.**

Reason: SCHEMA.md / FRESHNESS.md / open-questions parsing are small (≤30KB) deterministic outputs whose diff we want to *read* in PR review. Syrupy stores a single ambiguous `.ambr` blob per test class and encourages "press U to update" muscle memory — exactly the wrong incentive when the artifact is human-facing markdown.

Pattern:
```python
from pathlib import Path
import pytest, difflib

FIXTURE = Path(__file__).parent / "fixtures" / "schema_doc_expected.md"

def test_schema_doc_golden(in_memory_metadata, frozen_now):
    from scripts.refresh_schema_doc import generate
    actual = generate(metadata=in_memory_metadata, now=frozen_now)
    expected = FIXTURE.read_text(encoding="utf-8")
    if actual != expected:
        diff = "\n".join(difflib.unified_diff(
            expected.splitlines(), actual.splitlines(),
            fromfile="expected", tofile="actual", lineterm=""))
        pytest.fail(f"SCHEMA.md drift:\n{diff}")
```

**Determinism requirements:**
- `frozen_now` fixture pins `datetime.utcnow` so the header timestamp is stable.
- `in_memory_metadata` fixture is a small SQLite-backed `MetaData` with 3-4 fixture tables.
- Skip-marker for the freshness-doc test when no DB is available.

For the MEMORY.md parser test, no DB is needed — pure unit test.

## Summary table

| Topic | Recommendation | Watch out for |
|---|---|---|
| Schema introspection | `Base.metadata.sorted_tables` walk | PostGIS/Enum/JSONB `str(type)` rendering |
| Post-upgrade hook | Call generator from `env.py` after `run_migrations()` | Don't put it in `[post_write_hooks]` (revision-time only) |
| APScheduler cron | `CronTrigger(hour=2, minute=0, timezone="UTC")` | Always set `timezone=` explicitly |
| Path-safe read | Literal allowlist + `is_relative_to` + byte-truncate | UTF-8 boundary char → `errors="replace"` |
| MEMORY.md parse | Regex section header, strip date+score suffixes, pipe-split | Tolerate `_<date>_` and `_date_` variants |
| Golden tests | Plain `assert generated == fixture.read_text()` | Determinism: pin time, pin in-memory DB |

## Warnings / gotchas

1. **Alembic `[post_write_hooks]` is the wrong tool** — fires on `revision`, not `upgrade`.
2. **PostGIS `Geometry` reflection** silently fails without GeoAlchemy2 imported. Walking `Base.metadata` (in-process) avoids this.
3. **APScheduler default timezone** is process-local. Always pass `timezone="UTC"`.
4. **`is_relative_to()` requires Python 3.9+** — fine for this repo.
5. **Byte-vs-char truncation** matters for the 16KB cap.
6. **`build_factpack` removal** is Phase D — Phase A research above stays compatible with v1 still running.
