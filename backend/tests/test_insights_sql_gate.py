"""SQL allow-list gate tests (AI Insights V1).

Asserts the validate_sql() entry-point in agents/insights/tools/sql_gate.py
correctly accepts whitelisted SELECT shapes and rejects DDL/DML, system
catalog access, and multi-statement payloads.
"""
from __future__ import annotations

import pytest

sqlglot = pytest.importorskip(
    "sqlglot", reason="sqlglot dep not installed; run `uv sync` in backend/"
)

from agents.insights.tools.sql_gate import SqlGateError, validate_sql


# ---------------------------------------------------------------------------
# Accept cases
# ---------------------------------------------------------------------------


def test_accepts_simple_select():
    out = validate_sql("SELECT col FROM my_table WHERE x = 1")
    assert out.applied_limit > 0
    assert "my_table" in out.normalized_sql.lower()


def test_accepts_select_with_join_groupby_orderby():
    sql = (
        "SELECT t.col, SUM(t.val) AS total "
        "FROM my_table t "
        "JOIN other o ON o.id = t.other_id "
        "WHERE t.x = 1 "
        "GROUP BY t.col "
        "ORDER BY total DESC "
        "LIMIT 100"
    )
    out = validate_sql(sql)
    assert out.applied_limit == 100  # explicit LIMIT preserved when <= max


# ---------------------------------------------------------------------------
# Reject DDL/DML
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO my_table (x) VALUES (1)",
        "UPDATE my_table SET x = 1 WHERE y = 2",
        "DELETE FROM my_table WHERE x = 1",
        "DROP TABLE my_table",
    ],
)
def test_rejects_ddl_dml(sql):
    with pytest.raises(SqlGateError) as ei:
        validate_sql(sql)
    # Either explicit disallowed_statement, or non_select_root for parse-recovered shapes.
    assert ei.value.code in {
        "disallowed_statement",
        "non_select_root",
        "parse_error",
    }


# ---------------------------------------------------------------------------
# Reject system catalogs
# ---------------------------------------------------------------------------


def test_rejects_pg_table_reference():
    with pytest.raises(SqlGateError) as ei:
        validate_sql("SELECT * FROM pg_user")
    assert ei.value.code in {"banned_table", "banned_schema"}


def test_rejects_cte_referencing_pg_table():
    sql = "WITH x AS (SELECT * FROM pg_class) SELECT * FROM x"
    with pytest.raises(SqlGateError) as ei:
        validate_sql(sql)
    assert ei.value.code in {"banned_table", "banned_schema"}


# ---------------------------------------------------------------------------
# Multi-statement payloads
# ---------------------------------------------------------------------------


def test_rejects_multi_statement():
    with pytest.raises(SqlGateError) as ei:
        validate_sql("SELECT 1; SELECT 2")
    assert ei.value.code == "multi_statement"
