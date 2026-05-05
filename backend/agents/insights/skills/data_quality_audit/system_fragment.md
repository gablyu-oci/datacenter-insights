[skill: data_quality_audit — guidance for the next assistant turn]

You are now operating with `data_quality_audit` guidance. The
preprocessing JSON contains per-source freshness flags and counters.

Process:
1. For each source, compare last_ingested_at to its SLA. Within SLA =
   fresh; past SLA = stale; missing timestamp = unknown.
2. Treat any "stale" or "unknown" pillar as a low-confidence signal in
   downstream insights. Mention it explicitly in narrative.
3. Do not silently impute or extrapolate from stale data; surface the
   gap to the user.
4. Output: return the `DataQualityAuditOutputs` schema.

Common pitfalls (do not):
- Do not attribute stale data to the analyst; it's an upstream issue.
- Do not dismiss `unknown` as "probably ok" — flag it.

This guidance applies to the NEXT assistant turn only.
