"""002_edgar_extractions

Revision ID: a3b7c9d1e5f2
Revises: 94f7ae8d80fc
Create Date: 2026-04-28 23:00:00.000000

Phase 1A: Create the edgar_extractions staging table for raw EDGAR
filing extraction results (8-K, 10-K, 10-Q).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

# revision identifiers, used by Alembic.
revision: str = "a3b7c9d1e5f2"
down_revision: Union[str, Sequence[str], None] = "94f7ae8d80fc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create edgar_extractions table."""
    op.create_table(
        "edgar_extractions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("cik", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("accession_number", sqlmodel.sql.sqltypes.AutoString(length=30), nullable=False),
        sa.Column("form_type", sqlmodel.sql.sqltypes.AutoString(length=10), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("item_codes", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
        sa.Column("edgar_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("capacity_mw", sa.Float(), nullable=True),
        sa.Column("energy_source", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.Column("buyer_raw", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("seller_raw", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("parser_version", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False, server_default="regex-v1"),
        sa.Column("confidence", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(), nullable=False),
        sa.Column("buyer_company_id", sa.BigInteger(), nullable=True),
        sa.Column("seller_company_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("accession_number", name="uq_edgar_extraction_accession"),
    )
    op.create_index("ix_edgar_extractions_cik", "edgar_extractions", ["cik"])
    op.create_index("ix_edgar_extractions_filing_date", "edgar_extractions", ["filing_date"])


def downgrade() -> None:
    """Drop edgar_extractions table."""
    op.drop_index("ix_edgar_extractions_filing_date", table_name="edgar_extractions")
    op.drop_index("ix_edgar_extractions_cik", table_name="edgar_extractions")
    op.drop_table("edgar_extractions")
