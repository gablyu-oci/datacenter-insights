"""015_widen_aterio_string_cols — widen power_projects varchar columns.

Revision ID: 015_widen_aterio_string_cols
Revises: 014_aterio_power_projects
Create Date: 2026-05-07 00:00:00.000000

Two power_projects columns were declared too narrow in 014 vs the actual
Aterio US Power-generation snapshot (20260505):

  - utility_public_private  declared 32, actual max 36
  - aterio_bal_auth_uid     declared 64, actual max 73

This migration widens them. Reversible (downgrade narrows back, but only
safe if the table is empty or values fit — best-effort).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "015_widen_aterio_string_cols"
down_revision: Union[str, Sequence[str], None] = "014_aterio_power_projects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Recreate the AI-relevance view exactly as defined in 014.
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
    # Postgres won't let us ALTER a column type while a view references it,
    # so drop the view, alter, then recreate.
    op.execute("DROP VIEW IF EXISTS power_projects_ai_relevant;")
    op.alter_column(
        "power_projects",
        "utility_public_private",
        type_=sa.String(length=64),
        existing_type=sa.String(length=32),
        existing_nullable=True,
    )
    op.alter_column(
        "power_projects",
        "aterio_bal_auth_uid",
        type_=sa.String(length=128),
        existing_type=sa.String(length=64),
        existing_nullable=True,
    )
    op.execute(_VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS power_projects_ai_relevant;")
    op.alter_column(
        "power_projects",
        "aterio_bal_auth_uid",
        type_=sa.String(length=64),
        existing_type=sa.String(length=128),
        existing_nullable=True,
    )
    op.alter_column(
        "power_projects",
        "utility_public_private",
        type_=sa.String(length=32),
        existing_type=sa.String(length=64),
        existing_nullable=True,
    )
    op.execute(_VIEW_SQL)
