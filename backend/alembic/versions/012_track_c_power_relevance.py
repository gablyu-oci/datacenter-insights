"""012_track_c_power_relevance — Track C schema additions.

Adds the data-layer changes Track C needs:
  - `is_power_related: bool` — extractor sets this true for any filing whose
    body discusses power deals, datacenter power, or generation M&A. Lets the
    UI show rows even when buyer/capacity couldn't be extracted (per user req).
  - `signing_date: date` — actual deal-signing date pulled from the body
    (e.g. "On January 10, 2025…"). Distinct from filing_date.
  - `deal_index: int` — for multi-deal filings (e.g. a single 10-Q describing
    Calpine + Clinton-Meta + South Texas Project), disambiguates the rows that
    share an accession_number.

Drops the UNIQUE(accession_number) constraint so a single filing can yield N
EdgarExtraction rows. Replaced by a non-unique index for query performance.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "012_track_c_power_relevance"
down_revision = "011_v2_chat_and_citations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) New columns on edgar_extractions
    op.add_column(
        "edgar_extractions",
        sa.Column(
            "is_power_related",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "edgar_extractions",
        sa.Column("signing_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "edgar_extractions",
        sa.Column(
            "deal_index",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # 2) Drop the unique-on-accession_number constraint so we can store N
    # deal rows per filing (multi-deal extraction).
    op.drop_constraint(
        "uq_edgar_extraction_accession",
        "edgar_extractions",
        type_="unique",
    )

    # 3) Replace with a non-unique index so accession-based lookups stay fast.
    op.create_index(
        "ix_edgar_extractions_accession_number",
        "edgar_extractions",
        ["accession_number"],
        unique=False,
    )

    # 3b) Composite unique on (accession_number, deal_index) so the existing
    # `ON CONFLICT (accession_number) DO UPDATE` upsert pattern still works
    # AND multi-deal extractions (deal_index 0, 1, 2, ...) can coexist for one
    # filing. The extractor's _persist_extraction will be updated to target
    # this composite key.
    op.create_unique_constraint(
        "uq_edgar_extractions_accession_deal",
        "edgar_extractions",
        ["accession_number", "deal_index"],
    )

    # 4) Index on is_power_related for the UI-facing query.
    op.create_index(
        "ix_edgar_extractions_is_power_related",
        "edgar_extractions",
        ["is_power_related"],
        unique=False,
    )

    # 5) Backfill is_power_related from existing data: rows with a non-null
    # capacity_mw OR a non-rejected buyer_canonical are presumed power-related.
    # This is conservative; the proper backfill happens via edgar-reprocess.
    op.execute(
        """
        UPDATE edgar_extractions
           SET is_power_related = TRUE
         WHERE capacity_mw IS NOT NULL
            OR buyer_canonical IS NOT NULL
            OR pillar = 'power'
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_edgar_extractions_is_power_related",
        table_name="edgar_extractions",
    )
    op.drop_index(
        "ix_edgar_extractions_accession_number",
        table_name="edgar_extractions",
    )
    op.create_unique_constraint(
        "uq_edgar_extraction_accession",
        "edgar_extractions",
        ["accession_number"],
    )
    op.drop_column("edgar_extractions", "deal_index")
    op.drop_column("edgar_extractions", "signing_date")
    op.drop_column("edgar_extractions", "is_power_related")
