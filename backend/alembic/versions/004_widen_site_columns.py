"""004_widen_site_columns

Revision ID: d6e2a8f1b3c4
Revises: c5d9e3f7a4b2
Create Date: 2026-04-29 14:00:00.000000

Phase 1.5 step 1: Capture Phase 1A inline-ALTER drift on the `sites` table
that was applied to live DBs but never recorded as a migration. Also widen
permit/ingestion-run columns observed to overflow at adapter runtime.

This migration is idempotent against an already-widened live DB: alembic
emits ALTER COLUMN TYPE statements, and Postgres treats `varchar(N)->varchar(N)`
as a no-op when N is unchanged. The same column widths can therefore be
re-applied safely.

Drift captured:
  sites.provider_ticker             varchar(20)  -> varchar(50)
  sites.provider_public_private     varchar(20)  -> varchar(100)
  sites.utility_public_private      varchar(20)  -> varchar(100)
  sites.utility_ticker              varchar(20)  -> varchar(50)
  sites.bal_auth_abbr               varchar(20)  -> varchar(50)
  sites.bal_auth_subregion_code     varchar(20)  -> varchar(50)
  sites.project_execution_likelihood Float       -> varchar(50)
      (TYPE change: uses USING clause to cast double precision -> text and
       back on downgrade.)

Permit / ingestion column widenings (defensive, based on observed overflow
risk -- e.g. fuel_type values like "natural_gas_and_diesel_dual_fuel"):
  generator_permits.fuel_type        varchar(50)  -> varchar(100)
  generator_permits.permit_status    varchar(50)  -> varchar(100)
  generator_permits.frs_id           varchar(50)  -> varchar(100)
  generator_permits.naics_code       varchar(10)  -> varchar(50)
  ingestion_runs.adapter_version     varchar(20)  -> varchar(50)
  ingestion_runs.status              varchar(20)  -> varchar(50)
  ingestion_runs.trigger             varchar(20)  -> varchar(50)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d6e2a8f1b3c4"
down_revision: Union[str, Sequence[str], None] = "c5d9e3f7a4b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Widen sites + permit + ingestion columns to current SQLModel widths."""

    # ----- sites: Phase 1A drift -----
    op.alter_column(
        "sites", "provider_ticker",
        existing_type=sa.String(length=20),
        type_=sa.String(length=50),
        existing_nullable=True,
    )
    op.alter_column(
        "sites", "provider_public_private",
        existing_type=sa.String(length=20),
        type_=sa.String(length=100),
        existing_nullable=True,
    )
    op.alter_column(
        "sites", "utility_public_private",
        existing_type=sa.String(length=20),
        type_=sa.String(length=100),
        existing_nullable=True,
    )
    op.alter_column(
        "sites", "utility_ticker",
        existing_type=sa.String(length=20),
        type_=sa.String(length=50),
        existing_nullable=True,
    )
    op.alter_column(
        "sites", "bal_auth_abbr",
        existing_type=sa.String(length=20),
        type_=sa.String(length=50),
        existing_nullable=True,
    )
    op.alter_column(
        "sites", "bal_auth_subregion_code",
        existing_type=sa.String(length=20),
        type_=sa.String(length=50),
        existing_nullable=True,
    )

    # TYPE change: Float -> varchar(50). Use USING clause so Postgres can
    # cast existing numeric values to text without data loss.
    op.alter_column(
        "sites", "project_execution_likelihood",
        existing_type=sa.Float(),
        type_=sa.String(length=50),
        existing_nullable=True,
        postgresql_using="project_execution_likelihood::text",
    )

    # ----- generator_permits: defensive widenings -----
    op.alter_column(
        "generator_permits", "fuel_type",
        existing_type=sa.String(length=50),
        type_=sa.String(length=100),
        existing_nullable=True,
    )
    op.alter_column(
        "generator_permits", "permit_status",
        existing_type=sa.String(length=50),
        type_=sa.String(length=100),
        existing_nullable=True,
    )
    op.alter_column(
        "generator_permits", "frs_id",
        existing_type=sa.String(length=50),
        type_=sa.String(length=100),
        existing_nullable=True,
    )
    op.alter_column(
        "generator_permits", "naics_code",
        existing_type=sa.String(length=10),
        type_=sa.String(length=50),
        existing_nullable=True,
    )

    # ----- ingestion_runs: defensive widenings -----
    op.alter_column(
        "ingestion_runs", "adapter_version",
        existing_type=sa.String(length=20),
        type_=sa.String(length=50),
        existing_nullable=True,
    )
    op.alter_column(
        "ingestion_runs", "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=50),
        existing_nullable=False,
    )
    op.alter_column(
        "ingestion_runs", "trigger",
        existing_type=sa.String(length=20),
        type_=sa.String(length=50),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Revert columns to their pre-widening widths.

    NOTE: The downgrade may raise `value too long` errors if rows now contain
    data that exceeds the original widths. That's by design -- you cannot lose
    data silently on a width shrink.
    """

    # ----- ingestion_runs -----
    op.alter_column(
        "ingestion_runs", "trigger",
        existing_type=sa.String(length=50),
        type_=sa.String(length=20),
        existing_nullable=True,
    )
    op.alter_column(
        "ingestion_runs", "status",
        existing_type=sa.String(length=50),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
    op.alter_column(
        "ingestion_runs", "adapter_version",
        existing_type=sa.String(length=50),
        type_=sa.String(length=20),
        existing_nullable=True,
    )

    # ----- generator_permits -----
    op.alter_column(
        "generator_permits", "naics_code",
        existing_type=sa.String(length=50),
        type_=sa.String(length=10),
        existing_nullable=True,
    )
    op.alter_column(
        "generator_permits", "frs_id",
        existing_type=sa.String(length=100),
        type_=sa.String(length=50),
        existing_nullable=True,
    )
    op.alter_column(
        "generator_permits", "permit_status",
        existing_type=sa.String(length=100),
        type_=sa.String(length=50),
        existing_nullable=True,
    )
    op.alter_column(
        "generator_permits", "fuel_type",
        existing_type=sa.String(length=100),
        type_=sa.String(length=50),
        existing_nullable=True,
    )

    # ----- sites: revert -----
    op.alter_column(
        "sites", "project_execution_likelihood",
        existing_type=sa.String(length=50),
        type_=sa.Float(),
        existing_nullable=True,
        postgresql_using="project_execution_likelihood::double precision",
    )
    op.alter_column(
        "sites", "bal_auth_subregion_code",
        existing_type=sa.String(length=50),
        type_=sa.String(length=20),
        existing_nullable=True,
    )
    op.alter_column(
        "sites", "bal_auth_abbr",
        existing_type=sa.String(length=50),
        type_=sa.String(length=20),
        existing_nullable=True,
    )
    op.alter_column(
        "sites", "utility_ticker",
        existing_type=sa.String(length=50),
        type_=sa.String(length=20),
        existing_nullable=True,
    )
    op.alter_column(
        "sites", "utility_public_private",
        existing_type=sa.String(length=100),
        type_=sa.String(length=20),
        existing_nullable=True,
    )
    op.alter_column(
        "sites", "provider_public_private",
        existing_type=sa.String(length=100),
        type_=sa.String(length=20),
        existing_nullable=True,
    )
    op.alter_column(
        "sites", "provider_ticker",
        existing_type=sa.String(length=50),
        type_=sa.String(length=20),
        existing_nullable=True,
    )
