"""021_sub_user_email — per-user owner column on insight_subscription.

Revision ID: 021_sub_user_email
Revises: 020_site_notes_history
Create Date: 2026-05-21 12:00:00.000000

Save & History (Phase B): scope `insight_subscription` rows to the
calling user. Until this migration runs, every logged-in Oracle user
sees every other user's saved insights — see
``docs/planning/save-and-history-per-user/03-architecture.md`` (ADR-3).

Upgrade sequence (Postgres path):
  1. ADD COLUMN `user_email VARCHAR(254) NULL` — online-safe DDL.
  2. Backfill every existing row to ``gabrielle.lyu@oracle.com`` (the
     sole pre-launch saver). The literal is intentionally hard-coded:
     this is a one-shot data fix, not a configurable parameter.
  3. CREATE INDEX `ix_insight_subscription_user_email` on the new
     column. Cardinality is single-digit today; a B-tree is selective
     enough for every `WHERE user_email = ?` we'll issue.
  4. ALTER COLUMN `user_email NOT NULL` — locks the table briefly but
     finishes in milliseconds at current row counts (<100).

SQLite caveat (mirrors 018_ai_insights_v2_columns.py:28-32): SQLite's
ALTER COLUMN cannot change NULLability without table rebuild. Step 4
is therefore Postgres-only; SQLite test harnesses keep the column
NULL-able at the DB layer, and the non-Optional SQLModel field in
``backend/agents/insights/db/models.py`` provides app-level
enforcement.

Downgrade drops the index then the column. The NOT NULL flip does not
need an explicit reversal because the column is dropped wholesale.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "021_sub_user_email"
down_revision: Union[str, Sequence[str], None] = "020_site_notes_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres(bind) -> bool:
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    bind = op.get_bind()
    on_pg = _is_postgres(bind)

    # 1) ADD COLUMN nullable so the backfill in step 2 can run without
    #    constraint violations on existing rows.
    op.add_column(
        "insight_subscription",
        sa.Column("user_email", sa.String(length=254), nullable=True),
    )

    # 2) Backfill all pre-existing rows to the sole pre-launch saver.
    op.execute(
        sa.text(
            "UPDATE insight_subscription "
            "SET user_email = 'gabrielle.lyu@oracle.com' "
            "WHERE user_email IS NULL"
        )
    )

    # 3) Index for the WHERE user_email = ? predicate added to every
    #    per-user query (see routers/insights.py).
    op.create_index(
        "ix_insight_subscription_user_email",
        "insight_subscription",
        ["user_email"],
    )

    # 4) Flip to NOT NULL on Postgres. SQLite cannot ALTER COLUMN
    #    NULLability without a table rebuild, so we rely on the
    #    SQLModel-level non-Optional annotation there.
    if on_pg:
        op.alter_column(
            "insight_subscription",
            "user_email",
            existing_type=sa.String(length=254),
            nullable=False,
        )


def downgrade() -> None:
    op.drop_index(
        "ix_insight_subscription_user_email",
        table_name="insight_subscription",
    )
    op.drop_column("insight_subscription", "user_email")
