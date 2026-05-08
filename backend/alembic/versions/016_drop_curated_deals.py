"""016_drop_curated_deals — remove the curated_deals table.

Revision ID: 016_drop_curated_deals
Revises: 015_widen_aterio_string_cols
Create Date: 2026-05-07 00:00:00.000000

The curated_deals table held 23 hand-verified historical deals seeded as a
pre-EDGAR baseline. With the EDGAR extraction pipeline live and the Aterio
project inventory landing as the new spine, the curated layer is no longer
needed. All references in routers/power.py, routers/triangulation.py,
agents/triangulation.py, and the frontend have been removed in the same
change set.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = "016_drop_curated_deals"
down_revision: Union[str, Sequence[str], None] = "015_widen_aterio_string_cols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f("ix_curated_deals_legacy_id"), table_name="curated_deals")
    op.drop_table("curated_deals")


def downgrade() -> None:
    op.create_table(
        "curated_deals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("legacy_id", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("buyer", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("seller", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("deal_type", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column("energy_source", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column("capacity_mw", sa.Integer(), nullable=True),
        sa.Column("location", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("state", sqlmodel.sql.sqltypes.AutoString(length=10), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("announced_date", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=True),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column("duration_years", sa.Integer(), nullable=True),
        sa.Column("headline", sa.Text(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("source_type", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column("source_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("edgar_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("data_source", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("energy_contract_mwh_million", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_curated_deals_legacy_id"),
        "curated_deals",
        ["legacy_id"],
        unique=True,
    )
