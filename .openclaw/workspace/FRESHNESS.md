# Freshness — placeholder

The auto-refresh script for this file is currently failing silently. Treat as a known coverage gap; do NOT block on this file being empty.

## In the meantime

Drill via query_database and search_documents directly. SCHEMA.md alone is enough to find the data you need.

## Known refresh cadences (manually maintained)

| Table | Source cadence | Pipeline refresh | Freshness signal |
|---|---|---|---|
| `earnings_transcripts` | quarterly (one call per US-public TRACKED_FILER per quarter) | daily 06:45 UTC, calendar-gated to ±14 days of a call | `MAX(call_date)` per `ticker`; expect 1–2 day lag post-call before transcript becomes available |
| `earnings_passages` | follows parent | re-chunked on every parent re-ingest | `MAX(created_at)` |
