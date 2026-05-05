"""010_edgar_power_pipeline — Track A power-pipeline columns.

Revision ID: 010_edgar_power_pipeline
Revises: 009_ai_insights
Create Date: 2026-05-04 00:00:00.000000

Adds the columns the rebuilt EDGAR power-pillar pipeline needs:
  rejected_buyer_raw     — original LLM string when validate_buyer rejected
  rejected_seller_raw    — same for seller
  buyer_canonical        — entity_resolution-canonicalized name (or
                           validated raw value when no high-confidence match)
  seller_canonical       — same for seller
  methodology            — MWh→MW derivation audit trail (≤200 chars)
  canonical_deal_id      — 16-char hash for deal-level dedup grouping
  flagged_capacity       — TRUE when capacity_mw > 100,000 MW (sanity guard)
  appearance_count       — count of rows sharing canonical_deal_id

Indexes added:
  ix_edgar_extractions_buyer_canonical
  ix_edgar_extractions_canonical_deal_id
  ix_edgar_extractions_canonical_deal_id_filing_date — composite for
    "latest per canonical_deal_id" CTE in /api/power/announcements.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "010_edgar_power_pipeline"
down_revision: Union[str, Sequence[str], None] = "009_ai_insights"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "edgar_extractions",
        sa.Column("rejected_buyer_raw", sa.String(), nullable=True),
    )
    op.add_column(
        "edgar_extractions",
        sa.Column("rejected_seller_raw", sa.String(), nullable=True),
    )
    op.add_column(
        "edgar_extractions",
        sa.Column("buyer_canonical", sa.String(), nullable=True),
    )
    op.add_column(
        "edgar_extractions",
        sa.Column("seller_canonical", sa.String(), nullable=True),
    )
    op.add_column(
        "edgar_extractions",
        sa.Column("methodology", sa.Text(), nullable=True),
    )
    op.add_column(
        "edgar_extractions",
        sa.Column("canonical_deal_id", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "edgar_extractions",
        sa.Column(
            "flagged_capacity",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "edgar_extractions",
        sa.Column(
            "appearance_count",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )

    op.create_index(
        "ix_edgar_extractions_buyer_canonical",
        "edgar_extractions",
        ["buyer_canonical"],
    )
    op.create_index(
        "ix_edgar_extractions_canonical_deal_id",
        "edgar_extractions",
        ["canonical_deal_id"],
    )
    # Composite index supports "latest per canonical_deal_id" lookups in
    # _gw_summary_from_db (DISTINCT ON canonical_deal_id ORDER BY filing_date DESC).
    op.create_index(
        "ix_edgar_extractions_canonical_deal_id_filing_date",
        "edgar_extractions",
        ["canonical_deal_id", sa.text("filing_date DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_edgar_extractions_canonical_deal_id_filing_date",
        table_name="edgar_extractions",
    )
    op.drop_index(
        "ix_edgar_extractions_canonical_deal_id",
        table_name="edgar_extractions",
    )
    op.drop_index(
        "ix_edgar_extractions_buyer_canonical",
        table_name="edgar_extractions",
    )

    op.drop_column("edgar_extractions", "appearance_count")
    op.drop_column("edgar_extractions", "flagged_capacity")
    op.drop_column("edgar_extractions", "canonical_deal_id")
    op.drop_column("edgar_extractions", "methodology")
    op.drop_column("edgar_extractions", "seller_canonical")
    op.drop_column("edgar_extractions", "buyer_canonical")
    op.drop_column("edgar_extractions", "rejected_seller_raw")
    op.drop_column("edgar_extractions", "rejected_buyer_raw")
