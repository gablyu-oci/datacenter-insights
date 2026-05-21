# PRD: Mirror Aterio Daily CSVs to OCI Object Storage

Status: Draft
Owner: PM (strategic-insights-tool)
Date: 2026-05-21
Target branch: `feat/save-and-history` (or successor)

## Background

The Aterio ingestion pipeline downloads daily CSVs from an upstream S3 access
point and writes them to local disk under
`backend/data/aterio_archive/<YYYY-MM-DD>/<inventory|events>/<basename>.csv`.
This local archive is the only durable copy. Because the application runs on
an OCI VM with an ephemeral block volume layout, a VM rebuild or disk loss
would wipe historical Aterio snapshots — including days we can no longer
re-pull from upstream (the access point only exposes a rolling window).

We already provision an OCI Object Storage bucket `aterio-archive` in tenancy
namespace `iduyx1qnmway` for exactly this purpose, but the runner does not
write to it yet. This PRD covers wiring the downloader to mirror each CSV to
that bucket as a side effect of the existing download step.

## Goals

- Every CSV written by `_download_aterio_object` in
  `backend/pipeline/runner.py` is also uploaded to `oci://aterio-archive/<YYYY-MM-DD>/<subdir>/<basename>`.
- Object key in OCI mirrors the local relative path exactly, so a human can
  trivially map between local archive and bucket.
- Upload uses the default `~/.oci/config` profile already present on the host.
- Mirroring is idempotent: re-running the pipeline for the same day overwrites
  the same key without error or duplication.
- OCI upload failures degrade gracefully — they are logged but do not raise,
  do not change the function's return value, and do not block downstream
  parser/adapter steps.

## Non-goals

- No change to downloader, parser, or adapter behavior beyond the new
  side-effect upload.
- No backfill of historical local files already on disk (handled separately,
  out of scope here).
- No deletion, retention policy, lifecycle rules, or compaction on the bucket.
- No new config surface for bucket / namespace beyond module-level constants
  (or env override) — the values are fixed and already known.
- No switch of the local archive to "OCI-first" (local write remains the
  source of truth for this iteration).
- No metrics/alerting wiring beyond standard logger output.

## User stories

1. As a **data engineer on the team**, I want each Aterio CSV the pipeline
   downloads to also land in the `aterio-archive` OCI bucket, so that a VM
   rebuild or disk failure does not lose historical snapshots that upstream
   no longer serves.

2. As an **on-call engineer**, I want a transient OCI Object Storage outage
   to log a warning but NOT fail the ingestion pipeline, so that today's
   parser/adapter run still completes and we do not get paged for a
   non-critical mirror step.

3. As a **future analyst**, I want the object key in OCI to mirror the local
   path layout (`<date>/<subdir>/<basename>`) exactly, so that I can browse
   the bucket and reason about contents without consulting a separate
   mapping.

## Acceptance criteria

Behavioral:
- [ ] After `_download_aterio_object` returns for a given (date, subdir,
      basename), an object exists in bucket `aterio-archive` (namespace
      `iduyx1qnmway`) at key `<YYYY-MM-DD>/<subdir>/<basename>` whose bytes
      equal the local file's bytes.
- [ ] Function still returns the local `pathlib.Path` unchanged; callers
      observe no signature or return-type change.
- [ ] Re-running ingestion for the same date overwrites the same object key
      without raising and without producing duplicate keys.
- [ ] If the OCI upload raises any exception (auth, network, 5xx, etc.), the
      function logs a warning that includes bucket, key, and exception type,
      and then returns the local path normally. The pipeline run continues.
- [ ] OCI client is constructed from the default `~/.oci/config` profile; no
      new credential plumbing is introduced.

Code/structure:
- [ ] The upload helper is isolated (e.g. a small private function in
      `runner.py` or a sibling module) so it can be mocked in unit tests
      without monkey-patching the OCI SDK globally.
- [ ] Bucket name and namespace are defined as module-level constants (with
      optional env override) — not hardcoded inline at the call site.

Tests:
- [ ] Unit test: with the OCI client mocked, calling `_download_aterio_object`
      for a known (date, subdir, basename) results in exactly one upload call
      whose arguments include `namespace_name='iduyx1qnmway'`,
      `bucket_name='aterio-archive'`, and
      `object_name='<YYYY-MM-DD>/<subdir>/<basename>'`.
- [ ] Unit test: when the mocked OCI upload raises, the function still
      returns the expected local `pathlib.Path` and a warning is logged.
- [ ] Integration-style test (S3 + OCI both mocked at the boundary): the
      returned value is a `pathlib.Path` pointing at the expected local
      archive location, and the file exists on disk.

Operational:
- [ ] One full pipeline run on the dev VM produces both the local files under
      `backend/data/aterio_archive/<today>/...` and the corresponding objects
      in `oci://aterio-archive/<today>/...`, verified by listing the bucket.

## Risks and mitigations

- **Risk:** OCI SDK import or client construction adds startup cost or import
  cycles in `runner.py`.
  **Mitigation:** Import `oci` lazily inside the upload helper; construct
  the ObjectStorageClient once and cache at module scope.

- **Risk:** Silent upload failures cause the bucket to drift from the local
  archive without anyone noticing.
  **Mitigation:** Log warnings at WARN level with structured fields (bucket,
  key, exception class). Follow-up ticket (out of scope) to add a daily
  reconcile check that compares local archive tree to bucket listing.

- **Risk:** Large CSVs exceed single-PUT limits or time out.
  **Mitigation:** Current Aterio CSVs are well under the 50 GiB single-PUT
  ceiling; use a simple `put_object` for now. If file sizes grow, switch to
  `UploadManager` with multipart in a follow-up.

- **Risk:** Tests accidentally hit the real OCI tenancy.
  **Mitigation:** Mock the OCI client at the helper boundary; never
  instantiate a real `ObjectStorageClient` in tests. Guard the helper so it
  no-ops if a `DISABLE_OCI_MIRROR=1` env is set, to keep CI safe.

- **Risk:** Key collisions across reruns silently overwrite a newer good file
  with a re-downloaded older snapshot.
  **Mitigation:** Upstream basenames are date-stamped and content for a given
  date is stable; overwrite is the intended behavior. Document this in the
  helper's docstring.

## Open questions

- Should we also write a small `_manifest.json` per date (list of keys + sha256)
  alongside the CSVs? Deferred — not required to unblock disaster recovery.
- Should the helper be reused by other adapters (SEC, earnings) that also keep
  local archives? Likely yes, but generalization is out of scope for this PRD.
