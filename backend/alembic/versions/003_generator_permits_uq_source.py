"""003_generator_permits_unique_source_permit_id

Revision ID: b4c8d2e6f3a1
Revises: a3b7c9d1e5f2
Create Date: 2026-04-28 23:30:00.000000

Phase 1A: Add unique constraint on (source, source_permit_id) to
generator_permits so that ingestion adapters can upsert via
ON CONFLICT DO UPDATE.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4c8d2e6f3a1"
down_revision: Union[str, Sequence[str], None] = "a3b7c9d1e5f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add unique constraint on (source, source_permit_id) for upsert support."""
    op.create_unique_constraint(
        "uq_generator_permit_source_permitid",
        "generator_permits",
        ["source", "source_permit_id"],
    )


def downgrade() -> None:
    """Remove unique constraint."""
    op.drop_constraint(
        "uq_generator_permit_source_permitid",
        "generator_permits",
        type_="unique",
    )
