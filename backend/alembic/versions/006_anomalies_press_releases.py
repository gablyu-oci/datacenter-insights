"""006_anomalies_press_releases

Revision ID: a7b1c2d3e4f5
Revises: c5d9e3f7a4b2
Create Date: 2026-04-29 14:00:00.000000

Phase 2 (AC3 + AC5):
  * `anomalies`       -- WoW ±2σ deviation findings from agents.anomaly_detector
  * `press_releases`  -- IR press releases scraped by ingestion.press_releases
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7b1c2d3e4f5"
# Merge prior split heads (004_widen_site_columns + 005_brief_runs) so that
# subsequent migrations have a single linear history again.
down_revision: Union[str, Sequence[str], None] = ("d6e2a8f1b3c4", "c5d9e3f7a4b2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "anomalies",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("metric_kind", sa.String(length=50), nullable=False),
        sa.Column("dimension", sa.String(length=20), nullable=False,
                  server_default="ALL"),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("baseline_mean", sa.Float(), nullable=True),
        sa.Column("baseline_stddev", sa.Float(), nullable=True),
        sa.Column("z_score", sa.Float(), nullable=True),
        sa.Column("direction", sa.String(length=10), nullable=False,
                  server_default="spike"),
        sa.Column("sample_size", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "metric_kind", "dimension", "period_end",
            name="uq_anomaly_metric_dim_period",
        ),
    )
    op.create_index("ix_anomaly_period_end", "anomalies", ["period_end"])
    op.create_index("ix_anomalies_metric_kind", "anomalies", ["metric_kind"])

    op.create_table(
        "press_releases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("company_canon", sa.String(length=100), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=False),
        sa.Column("published_date", sa.Date(), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("matched_terms", sa.String(length=300), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("parser_version", sa.String(length=50), nullable=False,
                  server_default="press-v1"),
        sa.Column("retrieved_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_url", name="uq_press_release_url"),
    )
    op.create_index(
        "ix_press_release_company_date", "press_releases",
        ["company_canon", "published_date"],
    )
    op.create_index(
        "ix_press_releases_company_canon", "press_releases", ["company_canon"],
    )
    op.create_index(
        "ix_press_releases_published_date", "press_releases", ["published_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_press_releases_published_date", table_name="press_releases")
    op.drop_index("ix_press_releases_company_canon", table_name="press_releases")
    op.drop_index("ix_press_release_company_date", table_name="press_releases")
    op.drop_table("press_releases")

    op.drop_index("ix_anomalies_metric_kind", table_name="anomalies")
    op.drop_index("ix_anomaly_period_end", table_name="anomalies")
    op.drop_table("anomalies")
