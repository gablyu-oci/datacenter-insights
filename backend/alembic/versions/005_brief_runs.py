"""005_brief_runs

Revision ID: c5d9e3f7a4b2
Revises: b4c8d2e6f3a1
Create Date: 2026-04-29 12:00:00.000000

Phase 1C: Create the brief_runs table that persists weekly LLM-generated
intelligence briefings (markdown content, model + token metadata).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c5d9e3f7a4b2"
down_revision: Union[str, Sequence[str], None] = "b4c8d2e6f3a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create brief_runs table."""
    op.create_table(
        "brief_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column("bullet_count", sa.Integer(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_brief_runs_generated_at_desc",
        "brief_runs",
        [sa.text("generated_at DESC")],
    )


def downgrade() -> None:
    """Drop brief_runs table."""
    op.drop_index("ix_brief_runs_generated_at_desc", table_name="brief_runs")
    op.drop_table("brief_runs")
