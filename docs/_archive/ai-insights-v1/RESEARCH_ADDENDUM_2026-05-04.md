# RESEARCH ADDENDUM — AI Insights Tab
**Date:** 2026-05-04 · **Status:** No changes required — confirmation only
**Scope:** Verifies two technical assumptions baked into RESEARCH.md / ARCHITECTURE.md / TASKS.md before V1 build kickoff.

## Executive summary
Both load-bearing technical assumptions in the ratified planning docs are correct as written.
1. The OCI Llama Stack endpoint is OpenAI-Chat-Completions-compatible for tool use — same wire shape as `openai.chat.completions.create(...)` — and the existing `LlmClient.reason()` already exercises it in production.
2. `sqlglot` (current PyPI 30.7.0, well above the 23.x floor we required) exposes every AST primitive the SQL gate needs: `parse_one(..., dialect="postgres")`, `exp.Select`, `exp.With`, `exp.CTE`, `exp.Anonymous` (with `.name` for raw function-call matching), `exp.Func`, `Expression.walk()`, and `Expression.find_all(<cls>)`.

No architecture or task adjustments follow.

## Llama Stack tool-call shape — confirmed
Endpoint: `POST /v1/chat/completions` (already used by `backend/llm/client.py`).

Request body for tool use:
```json
{
  "model": "oci/openai.gpt-5.4",
  "messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}],
  "tools": [
    {"type": "function",
     "function": {"name": "run_sql", "description": "...",
                  "parameters": { "type": "object", "properties": {}, "required": [] }}}
  ],
  "tool_choice": "auto",
  "max_completion_tokens": 4096
}
```

Response shape when the model invokes a tool:
```json
{"choices":[{"finish_reason":"tool_calls",
  "message":{"role":"assistant","content":null,
    "tool_calls":[{"id":"call_abc","type":"function",
                   "function":{"name":"run_sql","arguments":"{\"sql\":\"...\"}"}}]}}]}
```

Tool-result follow-up: append `{"role":"tool","tool_call_id":"call_abc","content":"<json result>"}` to `messages` and re-POST. Loop until `finish_reason != "tool_calls"`. Matches the loop driver contract in ARCHITECTURE.md and RESEARCH.md §0 bullet 3.

Mid-conversation system messages: ordinary `{"role":"system","content":"..."}` entries can be inserted at any index in `messages`; there is no Llama-Stack-specific field. The SKILL_CONVERSION.md plan to load each skill's system_fragment when a skill tool is invoked is wire-compatible. The W3.4 calibration test on day-1 must still confirm gpt-5.4 honors mid-conversation system messages; if it does not, fall back to user-shaped injection per ARCH §A9.4.

Parallel tool calls: supported (model may emit multiple entries in `tool_calls`). The 4-per-turn cap from RESEARCH.md §0 is enforced client-side by truncating the array.

Token-name quirk: GPT-5.x rejects `max_tokens` and requires `max_completion_tokens` — already handled in `LlmClient`. New code must keep using `max_completion_tokens`.

## sqlglot capability — confirmed
Version: PyPI 30.7.0 (2026-05-04). Pin `sqlglot>=30,<31`.

AST gate primitives (all present, no workaround needed):
- Multi-statement detection: `sqlglot.parse(sql, dialect="postgres")` returns a list — reject if `len(...) > 1`.
- Statement-type allowlist: `isinstance(root, exp.Select)`; reject anything else (covers DML/DDL/`SET`/`COPY` — those parse to `exp.Insert/Update/Delete/Create/Drop/Set/Copy`, all not `exp.Select`).
- CTE walking: `for cte in root.find_all(exp.CTE):` then inspect `cte.this` (the inner `exp.Select`).
- `pg_*` / `information_schema` whitelist: `for t in root.find_all(exp.Table): if (t.db or "").lower() == "information_schema" or (t.name or "").lower().startswith("pg_"): ...`
- Banned function-call detection: `for fn in root.find_all(exp.Anonymous): if fn.name.lower() in {"pg_sleep","pg_read_file","pg_ls_dir","dblink","copy"}: reject`. Also walk `exp.Func` for resolved built-ins.
- LIMIT enforcement: `lim = root.args.get("limit")`; if `lim is None`, attach `root.set("limit", exp.Limit(expression=exp.Literal.number(10000)))`; if present, clamp `int(lim.expression.this)` to `min(value, 10000)`.

Defense-in-depth (already in ARCHITECTURE.md): AST gate is the primary control; `SET LOCAL statement_timeout = 5000` and a `NOSUPERUSER NOCREATEDB NOCREATEROLE` Postgres role are belt-and-braces.

## Implications for ARCHITECTURE.md / TASKS.md
None. Both documents proceed as ratified. The tool-loop driver task in TASKS.md should reference `LlmClient.reason()` as the underlying transport and add only a thin loop wrapper that:
1. POSTs the current message list.
2. If `finish_reason == "tool_calls"`, dispatches each tool call (capped at 4 in parallel), appends `{role:"tool", tool_call_id, content}` per result, and reposts.
3. Stops at depth 12 or when `finish_reason in {"stop","length","content_filter"}` — or at the 120s wall budget.

## References
- Existing OpenAI-compatible Llama Stack client (proof for Task 1): `backend/llm/client.py` — `LlmClient.reason()` lines 201–251.
- Cached OpenAPI spec: `docs/llama_stack/openapi.json` (single-line minified).
- sqlglot AST primer: https://github.com/tobymao/sqlglot
- sqlglot expressions API: https://sqlglot.com/sqlglot/expressions.html
- sqlglot PyPI (30.7.0, 2026-05-04): https://pypi.org/project/sqlglot/
- OpenAI Chat Completions tool-call shape (reference for the wire format Llama Stack mirrors): https://platform.openai.com/docs/guides/function-calling
