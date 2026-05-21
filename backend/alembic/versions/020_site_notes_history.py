"""020_site_notes_history — append-only audit of sites.notes changes.

Revision ID: 020_site_notes_history
Revises: 019_earnings_transcripts
Create Date: 2026-05-14

The Aterio inventory CSV's NOTES column is the one truly free-form field
the adapter ingests; analyst commentary there can be rewritten run-to-run.
The site-level upsert overwrites the value (correctly — `sites.notes` is
the current view), so without this table we silently lose prior wording.

Schema:

    site_notes_history(
      id               BIGSERIAL PRIMARY KEY,
      aterio_dc_uid    TEXT NOT NULL  -- references sites.aterio_dc_uid
                                      -- (logical FK; no CASCADE so deleted
                                      -- sites still leave their notes
                                      -- history behind for audit).
      notes_text       TEXT NOT NULL,
      observed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      ingestion_run_id BIGINT NULL    -- references ingestion_runs.id
                                      -- (SET NULL on delete so retention
                                      -- cleanup of ingestion_runs doesn't
                                      -- cascade and wipe history).
    );

Indexes:
  - (aterio_dc_uid, observed_at DESC) for "show me notes history for site X"
  - (ingestion_run_id) for "what notes deltas did the 2026-05-14 run land?"
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "020_site_notes_history"
down_revision: Union[str, Sequence[str], None] = "019_earnings_transcripts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "site_notes_history",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("aterio_dc_uid", sa.Text(), nullable=False),
        sa.Column("notes_text", sa.Text(), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "ingestion_run_id",
            sa.BigInteger(),
            sa.ForeignKey("ingestion_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_site_notes_history_uid_obs",
        "site_notes_history",
        ["aterio_dc_uid", sa.text("observed_at DESC")],
    )
    op.create_index(
        "ix_site_notes_history_run",
        "site_notes_history",
        ["ingestion_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_site_notes_history_run", table_name="site_notes_history")
    op.drop_index("ix_site_notes_history_uid_obs", table_name="site_notes_history")
    op.drop_table("site_notes_history")
