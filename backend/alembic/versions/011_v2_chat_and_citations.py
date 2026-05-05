"""011_v2_chat_and_citations -- AI Insights V2 chat threads + V2 column flags.

Revision ID: 011_v2_chat_and_citations
Revises: 010_edgar_power_pipeline
Create Date: 2026-05-04 00:00:00.000000

Adds the V2 surface area:
- `insight_thread`             — one chat thread per insight (V2 §5.4).
- `insight_subscription`       — V3-stub; the V2 "Subscribe" button writes here.
- `ai_insight` columns         — citation_count, low_external_support default,
                                  web_search_calls counter (V2 telemetry).
- `agent_message.thread_id`    — optional FK to `insight_thread`. Existing V1
                                  rows have NULL here. Distinguishes batch
                                  agent transcript from chat thread messages.

Note on existing tables (deviation from kickoff naming):
- The PRD/kickoff specifies new tables `insight_threads` (plural),
  `agent_messages` (plural), and `citations` (plural). Migration 009
  already created `agent_message` (singular, with `session_id` NOT NULL,
  `delete_after`, JSONB tool_calls, etc.) and `agent_citation`. To avoid
  a pointless rename + double-write path we extend the existing singular
  tables. The V2 chat transcript reuses `agent_message` rows scoped via
  the new `thread_id` FK; V2 citations continue to live in
  `agent_citation`. The new table created here is `insight_thread`
  (singular) for naming consistency.

Indexes:
- btree on insight_thread.insight_id
- btree on agent_message.thread_id (newly added column)
- (citations: ix_agent_citation_insight_id already exists from 009)
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision: str = "011_v2_chat_and_citations"
down_revision: Union[str, Sequence[str], None] = "010_edgar_power_pipeline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) insight_thread
    # ------------------------------------------------------------------
    # `delete_after` defaults NULL at the DB; the application sets
    # `now() + interval '90 days'` on insert (PRD V2 retention; the
    # kickoff specifies the +90 days policy lives in app code).
    op.create_table(
        "insight_thread",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "insight_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai_insight.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "last_active",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "delete_after",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="App sets to now() + interval '90 days' at insert time.",
        ),
    )
    op.create_index(
        "ix_insight_thread_insight_id", "insight_thread", ["insight_id"]
    )

    # ------------------------------------------------------------------
    # 2) Add thread_id to agent_message (idx for chat fetch).
    # ------------------------------------------------------------------
    op.add_column(
        "agent_message",
        sa.Column("thread_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_message_thread_id",
        "agent_message",
        "insight_thread",
        ["thread_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_agent_message_thread_id", "agent_message", ["thread_id"]
    )

    # ------------------------------------------------------------------
    # 3) insight_subscription (V3 scaffold; V2 button writes here)
    # ------------------------------------------------------------------
    op.create_table(
        "insight_subscription",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "insight_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai_insight.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("criteria_json", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.create_index(
        "ix_insight_subscription_insight_id",
        "insight_subscription",
        ["insight_id"],
    )

    # ------------------------------------------------------------------
    # 4) Alter ai_insight: V2 telemetry columns.
    # ------------------------------------------------------------------
    # `low_external_support` already exists from 009 (boolean nullable).
    # We do NOT add a default there to preserve V1's intent that NULL =
    # not yet evaluated. V2 paths set it explicitly.
    op.add_column(
        "ai_insight",
        sa.Column(
            "citation_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "ai_insight",
        sa.Column(
            "web_search_calls",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # ------------------------------------------------------------------
    # 5) Indexes on the existing agent_citation table -- ix on insight_id
    #    already exists from 009 (`ix_agent_citation_insight_id`). No
    #    additional citation indexes needed.
    # ------------------------------------------------------------------


def downgrade() -> None:
    op.drop_column("ai_insight", "web_search_calls")
    op.drop_column("ai_insight", "citation_count")

    op.drop_index(
        "ix_insight_subscription_insight_id",
        table_name="insight_subscription",
    )
    op.drop_table("insight_subscription")

    op.drop_index("ix_agent_message_thread_id", table_name="agent_message")
    op.drop_constraint(
        "fk_agent_message_thread_id", "agent_message", type_="foreignkey"
    )
    op.drop_column("agent_message", "thread_id")

    op.drop_index("ix_insight_thread_insight_id", table_name="insight_thread")
    op.drop_table("insight_thread")
