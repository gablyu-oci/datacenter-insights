"""008_building_permits

Revision ID: c9d3e4f5a6b7
Revises: b8c2d3e4f5a6
Create Date: 2026-04-30 18:00:00.000000

Karan-fixes batch (AC3) -- county-level US BUILDING permit ingestion.

Adds the `building_permits` table to hold raw county-issued building
permit rows (Loudoun VA, Mesa AZ, Grant County WA, etc.). This is
distinct from `generator_permits`, which stays the canonical home for
state air/generator permits (4150 rows today). The new table is the
landing zone for county open-data adapters and is surfaced via a
separate `/api/permits/building` endpoint.

Schema mirrors the contract in the AC3 brief:
    * uniqueness on (source, source_permit_id) for idempotent upserts
    * indexes on (state, county), (issued_date), (permit_status)
    * raw_payload JSONB so we never lose the upstream blob
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "c9d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = "b8c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "building_permits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("source_permit_id", sa.String(length=80), nullable=False),
        sa.Column("county", sa.String(length=80), nullable=False),
        sa.Column("state", sa.String(length=2), nullable=False),
        sa.Column("jurisdiction", sa.String(length=80), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("permit_type", sa.String(length=80), nullable=True),
        sa.Column("permit_status", sa.String(length=40), nullable=True),
        sa.Column("applied_date", sa.Date(), nullable=True),
        sa.Column("issued_date", sa.Date(), nullable=True),
        sa.Column("completed_date", sa.Date(), nullable=True),
        sa.Column("valuation_usd", sa.Float(), nullable=True),
        sa.Column("square_footage", sa.Integer(), nullable=True),
        sa.Column("applicant_name", sa.String(length=200), nullable=True),
        sa.Column("raw_payload", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "retrieved_at", sa.DateTime(), nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source", "source_permit_id",
            name="uq_building_permit_source_permitid",
        ),
    )
    op.create_index(
        "ix_building_permits_state_county", "building_permits",
        ["state", "county"],
    )
    op.create_index(
        "ix_building_permits_issued_date", "building_permits",
        ["issued_date"],
    )
    op.create_index(
        "ix_building_permits_permit_status", "building_permits",
        ["permit_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_building_permits_permit_status", table_name="building_permits",
    )
    op.drop_index(
        "ix_building_permits_issued_date", table_name="building_permits",
    )
    op.drop_index(
        "ix_building_permits_state_county", table_name="building_permits",
    )
    op.drop_table("building_permits")
