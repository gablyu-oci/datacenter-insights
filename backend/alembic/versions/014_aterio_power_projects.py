"""014_aterio_power_projects — Aterio US Power-Generation ingestion schema.

Revision ID: 014_aterio_power_projects
Revises: 013_ai_insight_embedding_vector
Create Date: 2026-05-07 00:00:00.000000

Creates four objects driving the Aterio US power-generation pipeline:

  1. `power_projects` — 61 mirrored Aterio columns + bookkeeping
        (PK = aterio_phase_uid).
  2. `aterio_row_hashes` — per-row SHA1 of the input payload, used to
        compute new/changed/unchanged/removed counts on each run.
  3. `power_deal_links` — N:N link table tying EDGAR extractions to
        power_projects rows with a tier label and confidence score.
  4. `power_projects_ai_relevant` — VIEW that filters power_projects to
        the AI/datacenter-relevant subset (hyperscaler customers, neo-cloud
        operators, datacenter/AI naming, behind-the-meter projects).

Down-revision points at the previous migration's actual revision string.
`downgrade()` drops the view first, then the three tables in dependency
order.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "014_aterio_power_projects"
down_revision: Union[str, Sequence[str], None] = "013_ai_insight_embedding_vector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# AI/datacenter relevance VIEW
# ---------------------------------------------------------------------------
# Matches a row when ANY of the following is true:
#   - customer_companies references a hyperscaler / AI lab
#   - customer_companies references a neo-cloud / colo operator
#   - project_name OR plant_name mentions "data center"/"datacenter"/"AI"
#   - flg_btm_project = 'Y' (behind-the-meter -> almost always AI/DC today)
# Uses POSIX `~*` (case-insensitive regex) on Postgres.
# ---------------------------------------------------------------------------

_VIEW_SQL = """
CREATE OR REPLACE VIEW power_projects_ai_relevant AS
SELECT *
FROM power_projects
WHERE
    customer_companies ~* '(Microsoft|Amazon|AWS|Google|Alphabet|Meta|Facebook|Oracle|xAI|Apple|Anthropic|OpenAI)'
 OR customer_companies ~* '(Crusoe|Vantage|Digital Realty|QTS|CyrusOne|STACK|Equinix|CoreWeave|Lambda|Applied Digital|EdgeConneX|DataBank|Aligned|NTT|Compass|TeraWulf)'
 OR project_name ILIKE '%data center%'
 OR project_name ILIKE '%datacenter%'
 OR project_name ILIKE '%AI%'
 OR plant_name   ILIKE '%data center%'
 OR plant_name   ILIKE '%datacenter%'
 OR plant_name   ILIKE '%AI%'
 OR flg_btm_project = 'Y';
"""


def upgrade() -> None:
    # ----- 1. power_projects -------------------------------------------
    op.create_table(
        "power_projects",
        sa.Column("aterio_phase_uid", sa.String(length=64), primary_key=True),
        sa.Column("aterio_energy_project_uid", sa.String(length=64), nullable=True, index=True),
        sa.Column("aterio_energy_plant_uid", sa.String(length=64), nullable=True, index=True),
        sa.Column("project_name", sa.Text(), nullable=True),
        sa.Column("flg_btm_project", sa.String(length=1), nullable=True, index=True),
        sa.Column("developer_companies", sa.Text(), nullable=True),
        sa.Column("developer_companies_ticker", sa.Text(), nullable=True),
        sa.Column("eia_entity_ids", sa.Text(), nullable=True),
        sa.Column("eia_entity_names", sa.Text(), nullable=True),
        sa.Column("construction_equipment_provider_companies", sa.Text(), nullable=True),
        sa.Column("project_financing_companies", sa.Text(), nullable=True),
        sa.Column("customer_companies", sa.Text(), nullable=True),
        sa.Column("tot_project_cost", sa.Numeric(18, 2), nullable=True),
        sa.Column("project_footprint_acreage", sa.Numeric(14, 2), nullable=True),
        sa.Column("site_boundary_acreage", sa.Numeric(14, 2), nullable=True),
        sa.Column("tot_contracted_power_capacity_mw", sa.Numeric(12, 2), nullable=True),
        sa.Column("agreement_url", sa.Text(), nullable=True),
        sa.Column("agreement_type", sa.String(length=200), nullable=True),
        sa.Column("project_source_url", sa.Text(), nullable=True),
        sa.Column("project_level_notes", sa.Text(), nullable=True),
        sa.Column("plant_name", sa.Text(), nullable=True),
        sa.Column("eia_plant_codes", sa.Text(), nullable=True),
        sa.Column("eia_plant_names", sa.Text(), nullable=True),
        sa.Column("county_name", sa.String(length=200), nullable=True),
        sa.Column("city_name", sa.String(length=200), nullable=True),
        sa.Column("state_code", sa.String(length=8), nullable=True, index=True),
        sa.Column("location_latitude", sa.Numeric(10, 6), nullable=True),
        sa.Column("location_longitude", sa.Numeric(10, 6), nullable=True),
        sa.Column("aterio_plant_technology_type", sa.String(length=100), nullable=True),
        sa.Column("aterio_plant_energy_source", sa.String(length=100), nullable=True, index=True),
        sa.Column("aterio_electrical_utility_uid", sa.String(length=64), nullable=True),
        sa.Column("utility_name", sa.String(length=300), nullable=True),
        sa.Column("utility_code", sa.String(length=64), nullable=True),
        sa.Column("utility_public_private", sa.String(length=32), nullable=True),
        sa.Column("utility_ticker_name", sa.String(length=32), nullable=True),
        sa.Column("utility_bloomberg_ticker_name", sa.String(length=64), nullable=True),
        sa.Column("utility_exchange_provider_ticker_name", sa.String(length=64), nullable=True),
        sa.Column("aterio_bal_auth_uid", sa.String(length=64), nullable=True),
        sa.Column("bal_auth_abbr", sa.String(length=32), nullable=True, index=True),
        sa.Column("bal_auth_name", sa.String(length=200), nullable=True),
        sa.Column("aterio_energy_market_region", sa.String(length=64), nullable=True),
        sa.Column("plant_source_url", sa.Text(), nullable=True),
        sa.Column("plant_level_notes", sa.Text(), nullable=True),
        sa.Column("eia_generator_ids", sa.Text(), nullable=True),
        sa.Column("plant_phase_name", sa.String(length=200), nullable=True),
        sa.Column("plant_phase_stage", sa.String(length=64), nullable=True, index=True),
        sa.Column("tot_phase_nameplate_power_mw", sa.Numeric(12, 2), nullable=True),
        sa.Column("tot_phase_storage_duration_hours", sa.Numeric(10, 2), nullable=True),
        sa.Column("tot_phase_storage_capacity_mwh", sa.Numeric(14, 2), nullable=True),
        sa.Column("plant_phase_filing_date", sa.Date(), nullable=True),
        sa.Column("plant_phase_announced_date", sa.Date(), nullable=True),
        sa.Column("plant_phase_aterio_estimated_construction_start_date", sa.Date(), nullable=True),
        sa.Column("plant_phase_aterio_estimated_completion_date", sa.Date(), nullable=True),
        sa.Column("plant_phase_public_estimated_activation_date", sa.Date(), nullable=True),
        sa.Column("plant_phase_actual_activation_date", sa.Date(), nullable=True),
        sa.Column("plant_phase_cancelled_date", sa.Date(), nullable=True),
        sa.Column("plant_phase_project_notapproved_withdrawn_date", sa.Date(), nullable=True),
        sa.Column("latest_satellite_picture_date", sa.Date(), nullable=True),
        sa.Column("pct_construction_status", sa.Numeric(5, 2), nullable=True),
        sa.Column("record_updated_date", sa.Date(), nullable=True),
        sa.Column("updated_at_source", sa.TIMESTAMP(timezone=False), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=False), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=False), nullable=False, server_default=sa.func.now()),
    )

    # ----- 2. aterio_row_hashes ----------------------------------------
    op.create_table(
        "aterio_row_hashes",
        sa.Column("aterio_phase_uid", sa.String(length=64), primary_key=True),
        sa.Column("row_hash", sa.String(length=40), nullable=False),
        sa.Column(
            "last_seen_at", sa.TIMESTAMP(timezone=False),
            nullable=False, server_default=sa.func.now(),
        ),
    )

    # ----- 3. power_deal_links -----------------------------------------
    op.create_table(
        "power_deal_links",
        sa.Column(
            "id", sa.BigInteger(),
            primary_key=True, autoincrement=True,
        ),
        sa.Column(
            "edgar_extraction_id", sa.BigInteger(),
            sa.ForeignKey("edgar_extractions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "aterio_phase_uid", sa.String(length=64),
            sa.ForeignKey("power_projects.aterio_phase_uid", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("match_tier", sa.String(length=2), nullable=False),
        sa.Column("match_score", sa.Numeric(3, 2), nullable=False),
        sa.Column(
            "matched_at", sa.TIMESTAMP(timezone=False),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "edgar_extraction_id", "aterio_phase_uid",
            name="uq_power_deal_links_edgar_phase",
        ),
    )
    op.create_index(
        "ix_power_deal_links_edgar",
        "power_deal_links", ["edgar_extraction_id"],
    )
    op.create_index(
        "ix_power_deal_links_phase",
        "power_deal_links", ["aterio_phase_uid"],
    )

    # ----- 4. AI-relevant VIEW -----------------------------------------
    # Skip on SQLite (test runner): the regex `~*` operator is
    # Postgres-only. The adapter's `rows_filtered_in` metric simply
    # reports 0 there, which is fine for the round-trip test.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(_VIEW_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP VIEW IF EXISTS power_projects_ai_relevant;")

    op.drop_index("ix_power_deal_links_phase", table_name="power_deal_links")
    op.drop_index("ix_power_deal_links_edgar", table_name="power_deal_links")
    op.drop_table("power_deal_links")
    op.drop_table("aterio_row_hashes")
    op.drop_table("power_projects")
