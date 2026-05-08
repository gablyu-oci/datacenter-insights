"""018_ai_insights_v2_columns — Phase C v2 schema additions.

Revision ID: 018_ai_insights_v2_columns
Revises: 017_passage_tables
Create Date: 2026-05-07 14:00:00.000000

Phase C of the AI Insights v2 redesign (see
``docs/ai_insights_v2_phases_bcd_architecture.md`` §3). Two surgical
schema deltas, both backwards-compatible (NULLABLE / DEFAULT-bearing)
so v1 inserts continue to work unchanged:

  * ``agent_chart.insight_id`` becomes NULLABLE. v2 ``build_chart`` writes
    a chart row before ``persist_insight`` runs — there is no insight to
    bind to yet — so the FK is set later by ``persist_insight_v2``.
    v1 keeps inserting with insight_id NOT NULL because the v1 path
    sequences chart-after-insight.

  * ``ai_insight`` gains four v2 columns:
      - ``chart_id`` (TEXT NULL, FK → agent_chart.id ON DELETE SET NULL)
      - ``citations`` (JSONB NULL) — typed citation list
      - ``open_question_id`` (TEXT NULL) — pointer into OpenClaw's
        open_questions journal
      - ``version`` (TEXT NOT NULL DEFAULT 'v1')

The v1 ``chart_type`` / ``chart_y_label`` / ``supporting_row_ids``
columns are preserved (some live elsewhere on the model) so
``persist_insight`` v1 stays byte-identical.

SQLite (used by some unit tests) lacks ALTER COLUMN for nullability;
under non-Postgres backends we no-op the agent_chart change and rely on
the model layer for shape. The ai_insight column adds use ADD COLUMN
which sqlite supports.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "018_ai_insights_v2_columns"
down_revision: Union[str, Sequence[str], None] = "017_passage_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres(bind) -> bool:
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    bind = op.get_bind()
    on_pg = _is_postgres(bind)

    # ------------------------------------------------------------------
    # 1) agent_chart.insight_id → NULLABLE (Postgres only; sqlite ignored).
    # ------------------------------------------------------------------
    if on_pg:
        op.alter_column(
            "agent_chart",
            "insight_id",
            existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        )

    # ------------------------------------------------------------------
    # 2) ai_insight v2 columns.
    # ------------------------------------------------------------------
    json_type = JSONB() if on_pg else sa.Text()

    op.add_column(
        "ai_insight",
        sa.Column("chart_id", sa.String(length=32), nullable=True),
    )
    if on_pg:
        op.create_foreign_key(
            "fk_ai_insight_chart_id",
            "ai_insight",
            "agent_chart",
            ["chart_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.add_column(
        "ai_insight",
        sa.Column("citations", json_type, nullable=True),
    )
    op.add_column(
        "ai_insight",
        sa.Column("open_question_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ai_insight",
        sa.Column(
            "version",
            sa.String(length=8),
            nullable=False,
            server_default=sa.text("'v1'"),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    on_pg = _is_postgres(bind)

    if on_pg:
        op.drop_constraint("fk_ai_insight_chart_id", "ai_insight", type_="foreignkey")
    op.drop_column("ai_insight", "version")
    op.drop_column("ai_insight", "open_question_id")
    op.drop_column("ai_insight", "citations")
    op.drop_column("ai_insight", "chart_id")

    if on_pg:
        op.alter_column(
            "agent_chart",
            "insight_id",
            existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        )
