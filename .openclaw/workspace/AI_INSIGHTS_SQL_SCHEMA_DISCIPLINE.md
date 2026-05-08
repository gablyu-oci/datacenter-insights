# AI Insights SQL Schema Discipline

This file is a hard guardrail for SQL generation in AI insights, QA, and synthesis.

## Rule

Do not use a table or column name unless it is confirmed by:
- `SCHEMA.md`
- `QUERIES.md`
- a tool result
- or an already-validated active query

Do not substitute a plausible-looking generic column name for a real warehouse column.

## Required process

1. Check `SCHEMA.md` before querying unfamiliar tables.
2. Check `QUERIES.md` for a canonical query pattern before inventing SQL.
3. If the docs show caveats, include those caveats in the query logic.
4. If the schema is still unclear, stop and narrow the claim instead of fabricating SQL.

## Generator permits guardrails

- Never use `generator_permits.parent_company`; it is not a real column.
- For parent/company rollups, use `resolved_company_id -> companies.canonical_name`.
- Do not assume a generic `capacity_mw` column exists in `generator_permits`.
- Use the documented `generator_permits` patterns in `QUERIES.md` before writing custom SQL.
- Be careful with MW logic because some source slices may require documented fallback handling.

## Why this exists

The failure mode is not just hallucinated facts in prose. It is also hallucinated schema in SQL. A plausible-looking wrong column can break the agentic flow before insight persistence even begins.
