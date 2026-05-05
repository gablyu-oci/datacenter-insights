"""013_ai_insight_embedding_vector — Phase 2 schema for AI Insights automation.

Revision ID: 013_ai_insight_embedding_vector
Revises: 012_track_c_power_relevance
Create Date: 2026-05-05 00:00:00.000000

Implements the architecture §5.1 schema migration for the AI Insights
automation Phase 2 + 3 rollout:

  * `ai_insight.headline_embedding`  Text  ->  vector(3072)
        (re-typed via DROP/ADD COLUMN; column is empty in dev/prod
         today — see arch §5.1 + §9 R6 for the safety analysis)
  * `ai_insight.ongoing_of_id  UUID NULL  REFERENCES ai_insight(id)`
        (cross-day "ongoing" linkage — D8 in the plan)
  * `ai_insight.supporting_row_ids  JSONB NULL`
        (replaces the inline "_Sources: row_ids=[...]_" footer Phase 1
         stuffed into ai_insight.body)
  * `ai_session.cron_run_date  DATE NULL`
        (idempotency guard for the daily scheduler job — D5)
  * `ai_session.token_estimate  INT NULL`
        (post-flight token accounting — D7)
  * btree index on (ai_session.created_by, ai_session.cron_run_date)
        (fast idempotency lookup at top of _invoke_insights_daily)

The pgvector extension is already created in migration 009; this
migration intentionally does NOT recreate it. ANN indices (ivfflat /
hnsw) are deferred per arch §5.1 (defer until row count > ~500).

Downgrade is reversible — restores `headline_embedding TEXT NULL`,
drops the new columns and indices in reverse order.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision: str = "013_ai_insight_embedding_vector"
down_revision: Union[str, Sequence[str], None] = "012_track_c_power_relevance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Helper: detect Postgres so the migration can no-op the `vector` typing
# under SQLite (test runners). SQLite does not have pgvector; we fall back
# to a TEXT column there so the round-trip test still passes.
def _is_postgres(bind) -> bool:
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    bind = op.get_bind()
    on_pg = _is_postgres(bind)

    # ------------------------------------------------------------------
    # 1) ai_insight.headline_embedding  TEXT  ->  vector(3072)
    # ------------------------------------------------------------------
    # On Postgres pgvector does not provide a Text -> vector cast. The
    # column is empty today (see arch §5.1 + §9 R6). On SQLite there is
    # no vector type, so we just leave the column as TEXT — the dedup
    # round-trip path uses raw SQL guarded by `_is_postgres` upstream.
    if on_pg:
        op.execute("ALTER TABLE ai_insight DROP COLUMN headline_embedding;")
        op.execute(
            "ALTER TABLE ai_insight "
            "ADD COLUMN headline_embedding vector(3072) NULL;"
        )
    # else: SQLite already has it as TEXT (which sqlmodel can hold). No-op.

    # ------------------------------------------------------------------
    # 2) ai_insight.ongoing_of_id (cross-day linkage)
    # ------------------------------------------------------------------
    op.add_column(
        "ai_insight",
        sa.Column(
            "ongoing_of_id",
            UUID(as_uuid=True) if on_pg else sa.String(length=36),
            sa.ForeignKey("ai_insight.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_ai_insight_ongoing_of_id",
        "ai_insight",
        ["ongoing_of_id"],
    )

    # ------------------------------------------------------------------
    # 3) ai_insight.supporting_row_ids (JSONB list of "section:n" strings)
    # ------------------------------------------------------------------
    # Use JSONB on Postgres; fall back to JSON on SQLite for round-trip tests.
    op.add_column(
        "ai_insight",
        sa.Column(
            "supporting_row_ids",
            JSONB() if on_pg else sa.JSON(),
            nullable=True,
        ),
    )

    # ------------------------------------------------------------------
    # 4) ai_session.cron_run_date  (idempotency)
    # ------------------------------------------------------------------
    op.add_column(
        "ai_session",
        sa.Column("cron_run_date", sa.Date(), nullable=True),
    )

    # ------------------------------------------------------------------
    # 5) ai_session.token_estimate  (post-flight accounting)
    # ------------------------------------------------------------------
    op.add_column(
        "ai_session",
        sa.Column("token_estimate", sa.Integer(), nullable=True),
    )

    # ------------------------------------------------------------------
    # 6) Composite btree index for the idempotency-guard query:
    #    SELECT ... WHERE created_by = 'scheduler' AND cron_run_date = today
    # ------------------------------------------------------------------
    op.create_index(
        "ix_ai_session_created_by_cron_run_date",
        "ai_session",
        ["created_by", "cron_run_date"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    on_pg = _is_postgres(bind)

    # Drop indices first.
    op.drop_index(
        "ix_ai_session_created_by_cron_run_date",
        table_name="ai_session",
    )
    op.drop_column("ai_session", "token_estimate")
    op.drop_column("ai_session", "cron_run_date")

    op.drop_column("ai_insight", "supporting_row_ids")

    op.drop_index(
        "ix_ai_insight_ongoing_of_id",
        table_name="ai_insight",
    )
    op.drop_column("ai_insight", "ongoing_of_id")

    # Restore headline_embedding as TEXT NULL (the pre-013 shape).
    if on_pg:
        op.execute("ALTER TABLE ai_insight DROP COLUMN headline_embedding;")
        op.execute("ALTER TABLE ai_insight ADD COLUMN headline_embedding TEXT NULL;")
    # else: SQLite never changed type; nothing to undo.
