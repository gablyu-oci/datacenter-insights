"""Round-trip test for migration 021_insight_subscription_user_email.

Acceptance criteria 8.3 from
`docs/planning/save-and-history-per-user/01-PRD.md`:

  * Seed N pre-021 `insight_subscription` rows (`user_email = NULL`),
    run `upgrade()`, assert every row is backfilled to
    `gabrielle.lyu@oracle.com`.
  * `downgrade()` drops the `user_email` column and the
    `ix_insight_subscription_user_email` index without errors.

We bypass the full alembic chain (earlier migrations use
Postgres-only types like UUID/JSONB/NOW()) and instead build a minimal
pre-021 schema on an in-memory SQLite engine, then invoke the 021
module's `upgrade()` / `downgrade()` directly inside a hand-rolled
`MigrationContext`.

The migration's NOT-NULL flip (step 4) is guarded by `_is_postgres()`
and is therefore a no-op on SQLite, so the post-upgrade column is
nullable at the DB layer here. That mirrors the live SQLite test
behavior described in the migration's docstring.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)


from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402
from sqlalchemy import (  # noqa: E402
    Boolean,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
    text,
)


# Import the 021 module directly. Its filename starts with a digit, so we
# go through importlib rather than `from alembic.versions...` which would
# require dotted-name acrobatics.
import importlib.util  # noqa: E402

_MIG_PATH = os.path.join(
    BACKEND_ROOT,
    "alembic",
    "versions",
    "021_insight_subscription_user_email.py",
)
_spec = importlib.util.spec_from_file_location("mig_021", _MIG_PATH)
mig_021 = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(mig_021)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_pre_021_table(engine) -> None:
    """Create the `insight_subscription` table at the pre-021 shape (no
    user_email column). Uses portable SQLAlchemy types so this works on
    SQLite."""
    metadata = MetaData()
    Table(
        "insight_subscription",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("insight_id", String(36), nullable=False),
        Column("criteria_json", String, nullable=True),
        Column("created_at", DateTime, nullable=True),
        Column("enabled", Boolean, nullable=False, default=False),
    )
    metadata.create_all(engine)


def _seed_rows(engine, n: int) -> list[str]:
    """Insert N pre-021 rows (user_email implicitly NULL because the column
    does not exist yet). Returns the row ids."""
    row_ids: list[str] = []
    with engine.begin() as conn:
        for _ in range(n):
            rid = str(uuid.uuid4())
            iid = str(uuid.uuid4())
            row_ids.append(rid)
            conn.execute(
                text(
                    "INSERT INTO insight_subscription "
                    "(id, insight_id, enabled) "
                    "VALUES (:id, :iid, :enabled)"
                ),
                {"id": rid, "iid": iid, "enabled": True},
            )
    return row_ids


def _run_upgrade(engine) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig_021.upgrade()
        conn.commit()


def _run_downgrade(engine) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig_021.downgrade()
        conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_migration_021_backfills_gabrielle():
    """Every NULL user_email row is rewritten to gabrielle.lyu@oracle.com."""
    engine = create_engine("sqlite:///:memory:")
    try:
        _build_pre_021_table(engine)
        ids = _seed_rows(engine, n=3)
        assert len(ids) == 3

        # Sanity check: pre-upgrade, the column does not exist.
        cols_before = {c["name"] for c in inspect(engine).get_columns(
            "insight_subscription"
        )}
        assert "user_email" not in cols_before

        _run_upgrade(engine)

        # Post-upgrade: column exists and every row was backfilled.
        cols_after = {c["name"] for c in inspect(engine).get_columns(
            "insight_subscription"
        )}
        assert "user_email" in cols_after

        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, user_email FROM insight_subscription")
            ).all()
        assert len(rows) == 3
        for (_rid, user_email) in rows:
            assert user_email == "gabrielle.lyu@oracle.com"
    finally:
        engine.dispose()


def test_migration_021_downgrade_drops_column():
    """Downgrade removes the user_email column AND the
    ix_insight_subscription_user_email index."""
    engine = create_engine("sqlite:///:memory:")
    try:
        _build_pre_021_table(engine)
        _seed_rows(engine, n=2)

        _run_upgrade(engine)

        # Confirm the index exists after upgrade.
        index_names_after_upgrade = {
            ix["name"]
            for ix in inspect(engine).get_indexes("insight_subscription")
        }
        assert (
            "ix_insight_subscription_user_email"
            in index_names_after_upgrade
        )

        _run_downgrade(engine)

        # Column is gone.
        cols_after_downgrade = {
            c["name"]
            for c in inspect(engine).get_columns("insight_subscription")
        }
        assert "user_email" not in cols_after_downgrade

        # Index is gone.
        index_names_after_downgrade = {
            ix["name"]
            for ix in inspect(engine).get_indexes("insight_subscription")
        }
        assert (
            "ix_insight_subscription_user_email"
            not in index_names_after_downgrade
        )
    finally:
        engine.dispose()
