"""SQL allow-list gate based on sqlglot AST inspection.

ARCHITECTURE.md A10.1 is the contract. Per RESEARCH_ADDENDUM_2026-05-04.md
the function returns a ValidatedSQL Pydantic struct so the caller can log
the normalised SQL + applied LIMIT alongside the executed-at timestamp.

Allow:
    - exactly one statement
    - SELECT root (with optional WITH/CTE wrapping)
    - aggregates, window functions, JOINs, GROUP BY, ORDER BY
    - allowlisted scalar / date functions
    - tables outside `pg_*` and `information_schema.*`

Reject:
    - DDL/DML (INSERT/UPDATE/DELETE/MERGE/CREATE/DROP/ALTER/TRUNCATE/
      GRANT/REVOKE)
    - SET / COPY / DBLINK / pg_sleep / pg_read_file / pg_ls_dir /
      pg_advisory_lock
    - multi-statement payloads
    - any reference to pg_* or information_schema.* tables
    - missing LIMIT (we attach LIMIT 10000) — flagged via notes

Errors raise `SqlGateError` with a structured `code` so the agent gets a
deterministic tool_error code back.
"""
from __future__ import annotations

from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict

try:
    import sqlglot
    from sqlglot import exp
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "sqlglot is required for the AI Insights SQL gate. "
        "Add `sqlglot>=30,<31` to backend/pyproject.toml."
    ) from exc


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hard row cap (ARCH A6.1).
DEFAULT_ROW_LIMIT = 10_000

# Banned scalar functions (called via Anonymous func name walk).
BANNED_FUNCS = frozenset(
    {
        "pg_sleep",
        "pg_read_file",
        "pg_read_server_files",
        "pg_ls_dir",
        "pg_terminate_backend",
        "pg_advisory_lock",
        "pg_advisory_unlock",
        "pg_advisory_xact_lock",
        "dblink",
        "dblink_exec",
        "dblink_connect",
        "lo_import",
        "lo_export",
        "copy",
        "current_setting",  # can leak GUC; we don't need it
        "set_config",
    }
)

# Banned schema/table prefixes (case-insensitive on the bare identifier).
BANNED_TABLE_PREFIXES = ("pg_",)
BANNED_SCHEMAS = frozenset({"pg_catalog", "information_schema", "pg_toast"})

# Statement classes that are unconditionally blocked.
_BLOCKED_STATEMENTS: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,  # sqlglot 30+ renamed AlterTable → Alter (covers ALTER TABLE/INDEX/etc.)
    exp.AlterColumn,
    exp.TruncateTable,
    exp.Grant,
    exp.Set,
    exp.Copy,
    exp.Command,  # generic catch-all for DO/CALL/COPY-shaped commands
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)


# ---------------------------------------------------------------------------
# Public model + error
# ---------------------------------------------------------------------------


class ValidatedSQL(BaseModel):
    """The result of a successful sql-gate pass."""

    model_config = ConfigDict(extra="forbid")

    normalized_sql: str
    applied_limit: int
    banned_funcs_seen: list[str] = []
    notes: list[str] = []


class SqlGateError(ValueError):
    """Raised when SQL fails the allow-list gate."""

    def __init__(self, code: str, message: str, *, detail: dict[str, Any] | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail or {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_statements(sql: str) -> list[str]:
    """Lightweight split on top-level semicolons.

    sqlglot.parse() already handles multi-statement input, but we use it to
    detect "more than one statement" which is itself a rejection condition.
    """
    parsed = sqlglot.parse(sql, dialect="postgres")
    return [stmt.sql() for stmt in parsed if stmt is not None]


def _is_select_root(tree: exp.Expression) -> bool:
    if isinstance(tree, exp.Select):
        return True
    if isinstance(tree, exp.With):
        # With wraps an inner expression accessible via .this
        inner = tree.this
        return isinstance(inner, exp.Select)
    if isinstance(tree, exp.Union):
        return all(_is_select_root(e) for e in (tree.left, tree.right))
    return False


def _walk_funcs(tree: exp.Expression) -> Iterable[str]:
    for node in tree.walk():
        if isinstance(node, exp.Anonymous):
            name = (node.this or "").lower() if isinstance(node.this, str) else ""
            if name:
                yield name
        elif isinstance(node, exp.Func):
            # sqlglot's known funcs expose .sql_name() (string) — fallback to class name.
            try:
                name = node.sql_name().lower()  # type: ignore[attr-defined]
            except Exception:
                name = type(node).__name__.lower()
            yield name


def _walk_tables(tree: exp.Expression) -> Iterable[exp.Table]:
    for node in tree.walk():
        if isinstance(node, exp.Table):
            yield node


def _has_explicit_limit(tree: exp.Expression) -> bool:
    """True if the outermost SELECT carries a LIMIT."""
    target: exp.Expression = tree
    if isinstance(tree, exp.With):
        target = tree.this
    if isinstance(target, exp.Union):
        # Apply on the union as a whole.
        return target.args.get("limit") is not None
    if isinstance(target, exp.Select):
        return target.args.get("limit") is not None
    return False


def _attach_limit(tree: exp.Expression, n: int) -> exp.Expression:
    target: exp.Expression = tree
    if isinstance(tree, exp.With):
        # Attach limit to the inner SELECT/UNION
        inner = tree.this
        new_inner = _attach_limit(inner, n)
        tree.set("this", new_inner)
        return tree
    if isinstance(target, exp.Union):
        target.set("limit", exp.Limit(expression=exp.Literal.number(n)))
        return target
    if isinstance(target, exp.Select):
        target.set("limit", exp.Limit(expression=exp.Literal.number(n)))
        return target
    return tree


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def validate_sql(sql: str, *, max_rows: int = DEFAULT_ROW_LIMIT) -> ValidatedSQL:
    """Validate `sql`. On success return a ValidatedSQL; on failure raise SqlGateError.

    The gate is conservative: any structural surprise rejects.
    """
    if not sql or not sql.strip():
        raise SqlGateError("empty_sql", "SQL string is empty")

    # 1) Single-statement check.
    try:
        statements = _split_statements(sql)
    except Exception as exc:
        raise SqlGateError("parse_error", f"sqlglot could not parse SQL: {exc}") from exc

    if len(statements) == 0:
        raise SqlGateError("parse_error", "no statements parsed")
    if len(statements) > 1:
        raise SqlGateError(
            "multi_statement",
            f"only single-statement SELECT is allowed; got {len(statements)} statements",
        )

    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except Exception as exc:
        raise SqlGateError("parse_error", f"sqlglot parse_one failed: {exc}") from exc

    if tree is None:
        raise SqlGateError("parse_error", "sqlglot returned None for SELECT root")

    # 2) Disallowed top-level statements.
    for cls in _BLOCKED_STATEMENTS:
        if isinstance(tree, cls):
            raise SqlGateError(
                "disallowed_statement",
                f"statement type {cls.__name__} is not allowed",
            )

    # 3) Must be a SELECT (possibly wrapped in WITH/UNION).
    if not _is_select_root(tree):
        raise SqlGateError(
            "non_select_root",
            f"only SELECT/CTE/UNION trees are allowed; got {type(tree).__name__}",
        )

    # 4) Function allow/deny — banned funcs reject.
    banned_seen: list[str] = []
    for fname in _walk_funcs(tree):
        if fname in BANNED_FUNCS:
            banned_seen.append(fname)
    if banned_seen:
        raise SqlGateError(
            "banned_function",
            f"banned function(s) referenced: {sorted(set(banned_seen))}",
            detail={"banned": sorted(set(banned_seen))},
        )

    # 5) Table reference checks — no pg_*, no information_schema.
    for tbl in _walk_tables(tree):
        name = (tbl.name or "").lower()
        schema = ((tbl.args.get("db") or tbl.args.get("catalog")) or "")
        schema_lower = (schema.name if isinstance(schema, exp.Identifier) else str(schema or "")).lower()
        if any(name.startswith(p) for p in BANNED_TABLE_PREFIXES):
            raise SqlGateError(
                "banned_table",
                f"table {name!r} is in a banned namespace (pg_*)",
            )
        if schema_lower in BANNED_SCHEMAS:
            raise SqlGateError(
                "banned_schema",
                f"schema {schema_lower!r} is not allowed (use the snapshot endpoint)",
            )

    # 6) LIMIT enforcement: clamp or attach.
    notes: list[str] = []
    applied_limit = max_rows
    if _has_explicit_limit(tree):
        # Clamp if a numeric literal limit > max_rows is present.
        target = tree.this if isinstance(tree, exp.With) else tree
        lim = target.args.get("limit") if isinstance(target, (exp.Select, exp.Union)) else None
        if lim is not None:
            lit = lim.expression if hasattr(lim, "expression") else None
            try:
                value = int(lit.this) if isinstance(lit, exp.Literal) else max_rows
            except Exception:
                value = max_rows
            if value > max_rows:
                notes.append(f"clamped LIMIT {value} -> {max_rows}")
                _attach_limit(tree, max_rows)
                applied_limit = max_rows
            else:
                applied_limit = value
    else:
        notes.append(f"attached LIMIT {max_rows}")
        _attach_limit(tree, max_rows)

    normalized = tree.sql(dialect="postgres")
    return ValidatedSQL(
        normalized_sql=normalized,
        applied_limit=applied_limit,
        banned_funcs_seen=[],  # we reject above; success path is empty
        notes=notes,
    )
