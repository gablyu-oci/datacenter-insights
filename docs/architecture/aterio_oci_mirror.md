# Architecture: Aterio OCI Mirror

Status: Draft
Date: 2026-05-21
PRD: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/prd/aterio_oci_mirror.md`
Reference implementation: `/home/ubuntu/oci-ai-incubations/strategic-insights-tool/docs/research/oci_object_storage_upload.md`

## System Overview

Add a thin, side-effect-only mirror that copies every Aterio CSV the runner
writes to local disk into the OCI `aterio-archive` bucket. The mirror is a
best-effort durability layer; the local archive remains the source of truth
for downstream parsing.

## Architecture Diagram

```
                            +-------------------+
  Aterio S3 access point -->| _download_aterio  |
  (boto3 s3.download_file)  |   _object(obj,    |
                            |    subdir)        |
                            +---------+---------+
                                      |
                                      | writes
                                      v
                            +-------------------+
                            | local archive     |
                            | data/aterio_      |
                            |  archive/<date>/  |
                            |  <subdir>/<file>  |
                            +---------+---------+
                                      |
                                      | (side effect, fire-and-forget)
                                      v
                            +-------------------+      +------------------+
                            | mirror_to_oci(    |----->| oci://aterio-    |
                            |   dest, key)      |      | archive/<date>/  |
                            | (warn-on-failure) |      | <subdir>/<file>  |
                            +---------+---------+      +------------------+
                                      |
                                      | returns dest (Path) unchanged
                                      v
                            downstream parser/adapter
```

The mirror call is intentionally a **non-gating side effect**. Its return
value is consumed for logging only; the function's return path
(`return dest`) is unaffected by upload outcome.

## Components & Responsibilities

### `backend/pipeline/aterio_oci_mirror.py` (new module)

Single public function:

```
mirror_to_oci(local_path: pathlib.Path, object_name: str) -> bool
```

Responsibilities:
- Resolve config (env overrides, kill switch).
- Build an `ObjectStorageClient` from `~/.oci/config` (per-call, see research §4).
- Stream the file via `put_object` with explicit `content_length`.
- Catch all exceptions; log at WARNING (kill switch / not-a-file) or ERROR
  (`ServiceError`, unexpected). Never raise.
- Return `True` on success, `False` otherwise.

Justification for a separate module:
- **Testability.** A single mock target (`backend.pipeline.aterio_oci_mirror.ObjectStorageClient`) covers all upload behavior; no monkey-patching of `runner.py` internals.
- **Single responsibility.** `runner.py` orchestrates ingestion; this module owns one verb (PUT one local file to one OCI key).
- **Lazy OCI import.** Keeping `import oci.*` in a sibling module means importing `runner.py` (which the API process does at startup) does not pull the OCI SDK into memory until the daily Aterio job runs. The reference implementation in research §8 already does `from oci.* import ...` at module top level — that import cost is paid only when this sibling module is first imported, which happens inside `_download_aterio_object`.
- **Reuse.** Other adapters (SEC, earnings) keeping local archives can call the same helper later, without touching `runner.py`.

### `backend/pipeline/runner.py` (modified)

Only `_download_aterio_object` (around line 825) changes. See Integration Point below.

## Data Models

No DB changes. No new tables, columns, or sidecars.

Object key contract:

```
<YYYY-MM-DD>/<subdir>/<basename>
  e.g. 2026-05-21/inventory/aterio-inventory-2026-05-21.csv
       2026-05-21/events/aterio-events-2026-05-21.csv
```

This is the literal local relative path under `data/aterio_archive/`. Slashes
are literal in the OCI object key (OCI has no real directories — the slash
just produces a logical prefix for listing).

## API Contracts

### Public

```
def mirror_to_oci(local_path: pathlib.Path, object_name: str) -> bool
```

- Idempotent: same `object_name` overwrites the existing object's bytes.
- Never raises. Returns `False` on any failure (auth, network, 5xx, missing file, kill switch).
- Does not validate `object_name` shape — caller owns key construction.

### Internal (runner integration)

`_download_aterio_object(obj, subdir) -> pathlib.Path` keeps its signature
and return type. Behavior delta:

```
key = obj["Key"]
basename = key.rsplit("/", 1)[-1]
today = datetime.utcnow().strftime("%Y-%m-%d")
dest_dir = _ATERIO_ARCHIVE_ROOT / today / subdir
dest = dest_dir / basename

if not dest.exists():
    s3.download_file(_ATERIO_S3_ACCESS_POINT, key, str(dest))

# NEW: mirror runs whether or not we just downloaded — covers
# idempotent re-runs where the local file already exists but the
# OCI object may not (e.g. first run after enabling the mirror).
oci_key = f"{today}/{subdir}/{basename}"
mirror_to_oci(dest, oci_key)

return dest
```

The mirror call sits **after** the conditional download block and runs
unconditionally on every call. This means a same-day re-run still pushes to
OCI even when the local file was already present — required for the first
run after enabling the feature, and a no-cost overwrite thereafter.

## Tech Stack Decisions

| Concern | Choice | Rationale |
|---|---|---|
| OCI SDK | `oci>=2.126,<3.0` | Stable `put_object` kwargs across 2.x; major version pin guards future break (research §7) |
| Upload primitive | `ObjectStorageClient.put_object` | Files are tens of MB; `UploadManager` is overkill and harder to mock (research §2) |
| Client lifetime | Per call | Archiver runs at most a few times per day; per-call simplifies mocking and avoids long-lived state (research §4) |
| Auth | `oci.config.from_file` default profile | Already provisioned on the VM; no new credential plumbing (PRD goal) |
| Content type | `text/csv` | Aids future humans browsing the bucket via Console |

## Config Surface

All resolved at call time inside `mirror_to_oci`:

| Env var | Default | Purpose |
|---|---|---|
| `OCI_ARCHIVE_NAMESPACE` | `iduyx1qnmway` | Tenancy namespace |
| `OCI_ARCHIVE_BUCKET` | `aterio-archive` | Target bucket |
| `OCI_ARCHIVE_ENABLED` | `1` | Kill switch; `0` makes the function log + return `False` without touching OCI |
| `OCI_CONFIG_FILE` | `~/.oci/config` | Config file path for `from_file` |
| `OCI_CONFIG_PROFILE` | `DEFAULT` | Profile within the config file |

Kill-switch behavior: when `OCI_ARCHIVE_ENABLED=0`, the function returns
early (no client construction, no SDK call) and logs at INFO. CI and local
dev set this to keep tests off the real tenancy.

## ADRs (key decisions)

**ADR-1: Side effect, not a gate.** The mirror MUST NOT raise into the
runner. Pipeline durability (the parser/adapter chain produces today's data
even if OCI is degraded) outweighs strict mirror consistency. A drifted
bucket is recoverable by a follow-up reconcile job; a missed daily parse is
not (upstream rolls off).

**ADR-2: Per-call client.** Trades a few hundred ms of construction for
simpler mocking and no module-level state. Acceptable because the helper is
invoked at most twice per day per CSV.

**ADR-3: Separate module, not a private helper in `runner.py`.** Keeps the
OCI SDK import out of the API process's hot import path and gives unit tests
one stable patch target.

**ADR-4: Overwrite is the intended idempotency mode.** Upstream basenames
are date-stamped; content for a given date is stable. No HEAD preflight, no
`if-none-match`. Documented as such per PRD risk note.

## Idempotency

Same `(date, subdir, basename)` always yields the same OCI key. Re-running
the pipeline on the same date PUTs the same bytes to the same key — OCI
overwrites atomically and assigns a new ETag. Acceptable per PRD acceptance
criteria.

## Test Seams

Explicit patch targets for unit tests in
`backend/tests/test_aterio_oci_mirror.py` (new):

- `backend.pipeline.aterio_oci_mirror.ObjectStorageClient` — patch the **class** at the import site so `_build_client()` returns a `MagicMock`.
- `backend.pipeline.aterio_oci_mirror.from_file` — patch the config loader so tests don't read `~/.oci/config`.

Required test cases (from PRD acceptance criteria):

1. Happy path: `put_object` called once with kwargs `namespace_name='iduyx1qnmway'`, `bucket_name='aterio-archive'`, `object_name='<date>/<subdir>/<basename>'`, `content_length=<file size>`.
2. Failure path: `put_object.side_effect = ServiceError(status=503, code='ServiceUnavailable', headers={}, message='boom')`. Assert `mirror_to_oci` returns `False`, logs at ERROR, does not raise.
3. Kill switch: with `OCI_ARCHIVE_ENABLED=0`, the function returns `False` and the patched `ObjectStorageClient` is **not** instantiated.
4. Runner integration: patch `mirror_to_oci` itself inside `backend.pipeline.runner` (where it is imported) and assert `_download_aterio_object` calls it with the expected key while still returning the local `Path`.

Do NOT patch `oci.object_storage.ObjectStorageClient` directly — see research §5 gotcha.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Silent drift between local archive and bucket | WARN/ERROR logs with bucket+key+exception class; follow-up reconcile job (out of scope) |
| OCI SDK import slows runner startup | Imports live in the sibling module, loaded only when `_download_aterio_object` runs |
| Tests hit real tenancy | Kill switch env var on CI + mandatory mock at `ObjectStorageClient` symbol |
| Large CSV growth exceeds single-PUT timeout | Current files << 50 GiB ceiling; switch to `UploadManager` later if needed (research §2) |
| Cross-region redirects add latency | Profile region pinned to bucket region in `~/.oci/config` on the VM |

## Out of Scope

- No change to `_latest_aterio_object` (S3 listing logic untouched).
- No change to `AterioAdapter` or any parser.
- No new ETag sidecar or manifest file (`.last_*_etag` stays local-only).
- No backfill of historical files already on disk before this feature ships.
- No bucket lifecycle policy, retention rules, or compaction.
- No metrics/alerting beyond standard logger output.
- No generalization to SEC/earnings adapters (possible follow-up).
