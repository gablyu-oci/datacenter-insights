# AI Insights v2 — Phase A Ops Runbook

Operational reference for the workspace-artefact refresh jobs introduced in
Phase A: `SCHEMA.md` (regenerated on every Alembic upgrade) and `FRESHNESS.md`
(regenerated daily at 02:00 UTC by APScheduler).

## Manual triggers

Run from `backend/` with the project venv active (`.venv/bin/activate`).

| Artefact | Command |
| --- | --- |
| `.openclaw/workspace/SCHEMA.md` | `python -m scripts.refresh_schema_doc` |
| `.openclaw/workspace/FRESHNESS.md` | `python -m scripts.refresh_freshness_doc` |

Both scripts open their own readonly engine, write atomically
(`*.tmp` + `os.replace`), and never raise out — failure is logged and a
best-effort partial file is emitted.

## Verifying the cron job is scheduled

`GET /api/health` already returns the count of active scheduled jobs via
`agents_active` (it reads `len(JOB_CONFIG)` in `routers/health.py`). To inspect
the live APScheduler job list including next-fire times, use a Python REPL
attached to the running backend process, e.g.:

```python
from main import app  # gives access to app.state.scheduler
for job in app.state.scheduler.get_jobs():
    print(job.id, job.next_run_time, job.trigger)
```

Expect to see `freshness_doc_daily` with a `CronTrigger(hour=2, minute=0)` and
`next_run_time` set to the next 02:00 UTC.

## Skipping the alembic post-upgrade hook in CI / tests

Set `SKIP_SCHEMA_DOC_REFRESH=1` in the environment that invokes
`alembic upgrade`. The hook in `backend/alembic/env.py`
(`_run_post_upgrade_schema_refresh`) checks this var first and short-circuits.
It is also auto-skipped in offline mode (`alembic upgrade --sql`).

There is no `.github/workflows/` config in this repo today and no `Makefile`
or `pytest.ini` that drives `alembic upgrade`, so the only invocation path is
`start.sh` (developer machines). **Recommendation, not modification**: when CI
is added, set `SKIP_SCHEMA_DOC_REFRESH=1` in the migration step's env block to
keep test runs deterministic and fast. `start.sh` itself should leave the var
unset so devs get a fresh `SCHEMA.md` on every migration.

## Generated artefact locations

Both files live under `.openclaw/workspace/` at the repo root, which is the
mount target inside the OpenClaw gateway container (see
`docker-compose.openclaw.yml` volumes section, line 73:
`./.openclaw/workspace:/home/node/.openclaw/workspace`).

- `.openclaw/workspace/SCHEMA.md`
- `.openclaw/workspace/FRESHNESS.md`

The mount is read-write from the host (the backend / cron writes here) and
read-only from the agent's perspective (it consumes via `read_workspace`). No
new env vars or volume mounts are required for `freshness_doc_daily` — the
cron runs in the FastAPI process (not inside the gateway container) and the
existing host filesystem path is already writable.

If APScheduler is ever moved into the gateway container, the workspace volume
mount above must be writable from inside the container (it currently is, via
the bind mount).

## Failure modes

| Failure | Effect | Recovery |
| --- | --- | --- |
| `refresh_schema_doc.refresh()` raises during alembic upgrade | Logged at WARN by `alembic.post_upgrade`. Migration is **not** rolled back (hook lives outside `with context.begin_transaction()`). | Re-run manually: `python -m scripts.refresh_schema_doc`. |
| `refresh_freshness_doc.refresh()` raises during the 02:00 cron | `_run_adapter_job` catches the exception, writes `IngestionRun(status='failure', error_log=[...])`. Cron continues to fire next day. | Inspect `ingestion_runs` for `adapter_name='_freshness_doc_refresh'`. Re-run manually. |
| `SKIP_SCHEMA_DOC_REFRESH=1` left set in production | `SCHEMA.md` goes stale relative to migrations. Agent still functions but may reason against an older schema. | Unset the var; run the manual trigger. |
| Workspace dir not writable | Atomic `os.replace` fails inside the script; logged, no exception out. | Fix filesystem perms on `.openclaw/workspace/`. |

## Rollback

Deleting either artefact is harmless. The agent's `read_workspace` tool returns
`file_not_found`, which is a documented degraded-but-functional state — the
synthesis loop falls back to direct DB tool calls.

To force a rebuild after deletion:

```bash
cd backend
python -m scripts.refresh_schema_doc
python -m scripts.refresh_freshness_doc
```

Or simply wait for the next scheduled fire (alembic upgrade for SCHEMA, 02:00
UTC for FRESHNESS).
