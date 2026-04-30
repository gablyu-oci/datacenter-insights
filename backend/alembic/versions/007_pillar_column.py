"""007_pillar_column

Revision ID: b8c2d3e4f5a6
Revises: a7b1c2d3e4f5
Create Date: 2026-04-30 12:00:00.000000

Phase 2 — Supplier Insights foundation (AC2):
  * Add `pillar` VARCHAR(32) column to `edgar_extractions` and `press_releases`.
    Valid values today are 'power_contract' (existing power-contract extractor)
    and 'vendor_supply' (forthcoming Phase 2 vendor-supply extractor). Kept as
    plain VARCHAR rather than a Postgres ENUM to keep this migration simple
    and reversible without ALTER TYPE gymnastics.
  * Backfill all existing rows with pillar='power_contract' (every row in
    these tables today was produced by the power-contract pipeline).
  * Add an index on `pillar` to both tables — the supplier-insights routers
    filter heavily on this column to partition vendor_supply rows from
    power_contract rows.

Side note (not a schema change but a registry correction documented here for
posterity): the Coherent CIK has been corrected from 0001140536 (which
actually maps to WILLIS TOWERS WATSON PLC) to 0000820318 (COHERENT CORP.,
ticker COHR). Verified against https://data.sec.gov/submissions/ on
2026-04-30. The fix lives in backend/agents/edgar_agent.py::VENDOR_FILERS.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a7b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- edgar_extractions.pillar -----------------------------------------
    op.add_column(
        "edgar_extractions",
        sa.Column("pillar", sa.String(length=32), nullable=True),
    )
    op.execute(
        "UPDATE edgar_extractions "
        "SET pillar = 'power_contract' "
        "WHERE pillar IS NULL"
    )
    op.create_index(
        "ix_edgar_extractions_pillar",
        "edgar_extractions",
        ["pillar"],
    )

    # --- press_releases.pillar --------------------------------------------
    op.add_column(
        "press_releases",
        sa.Column("pillar", sa.String(length=32), nullable=True),
    )
    op.execute(
        "UPDATE press_releases "
        "SET pillar = 'power_contract' "
        "WHERE pillar IS NULL"
    )
    op.create_index(
        "ix_press_releases_pillar",
        "press_releases",
        ["pillar"],
    )


def downgrade() -> None:
    op.drop_index("ix_press_releases_pillar", table_name="press_releases")
    op.drop_column("press_releases", "pillar")

    op.drop_index("ix_edgar_extractions_pillar", table_name="edgar_extractions")
    op.drop_column("edgar_extractions", "pillar")
