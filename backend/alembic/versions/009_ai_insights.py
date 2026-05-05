"""009_ai_insights — AI Insights V1 schema.

Revision ID: 009_ai_insights
Revises: c9d3e4f5a6b7
Create Date: 2026-05-04 00:00:00.000000

Creates the eight tables backing the AI Insights tab plus the pgvector
extension required for the skill_reference embeddings.

Tables (per ARCHITECTURE.md A7 / A8):
    ai_session          — top-level agent run
    ai_insight          — final insight cards persisted to disk
    agent_message       — full LLM transcript (with `delete_after` per P-3)
    agent_tool_call     — every tool dispatch + latency + ok/err
    agent_chart         — emitted ChartSpec blobs + row_hash
    agent_citation      — V2 web citations (table created in V1; not written)
    skill_invocation    — per run_skill() record
    skill_reference     — RAG chunks, embedding vector(3072)

Notes:
- pgvector extension is created defensively (`IF NOT EXISTS`).
- `delete_after timestamptz NULL` lives on agent_message per ratified P-3
  so V2 retention sweeps don't need a follow-up migration.
- agent_chart.row_hash is the canonical sha256 over chart.data captured at
  emit time; mismatches with the originating tool call's hash are rejected
  upstream.
- skill_reference.embedding uses pgvector dim=3072 (text-embedding-3-large).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision: str = "009_ai_insights"
down_revision: Union[str, Sequence[str], None] = "c9d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ts(default_now: bool = False) -> sa.Column:
    kwargs: dict = {"nullable": False}
    if default_now:
        kwargs["server_default"] = sa.text("NOW()")
    return sa.Column("created_at", sa.DateTime(timezone=True), **kwargs)


def upgrade() -> None:
    # 0) pgvector extension (idempotent).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 1) ai_session
    op.create_table(
        "ai_session",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False),  # running|complete|failed|cancelled
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model", sa.String(length=80), nullable=True),
        sa.Column("focus", sa.Text(), nullable=True),
        sa.Column("max_insights", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("version", sa.String(length=8), nullable=False, server_default="v1"),
        sa.Column("insights_emitted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("budget_status", sa.String(length=16), nullable=True),
        sa.Column("created_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_ai_session_status", "ai_session", ["status"])
    op.create_index("ix_ai_session_started_at", "ai_session", ["started_at"])

    # 2) ai_insight
    op.create_table(
        "ai_insight",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id", UUID(as_uuid=True),
            sa.ForeignKey("ai_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=False),  # low|medium|high
        sa.Column("materiality", sa.String(length=16), nullable=False),  # low|medium|high (S/M/L)
        sa.Column("skills_run", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("low_external_support", sa.Boolean(), nullable=True),
        # Embedding for novelty (cosine, ARCH A10.3). 3072-dim text-embedding-3-large.
        sa.Column("headline_embedding", sa.Text(), nullable=True),  # store as text in V1; dedup writes vector via raw SQL
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_ai_insight_session_id", "ai_insight", ["session_id"])
    op.create_index("ix_ai_insight_created_at", "ai_insight", ["created_at"])

    # 3) agent_message
    op.create_table(
        "agent_message",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id", UUID(as_uuid=True),
            sa.ForeignKey("ai_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "insight_id", UUID(as_uuid=True),
            sa.ForeignKey("ai_insight.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),  # system|user|assistant|tool
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("tool_calls", JSONB(), nullable=True),
        sa.Column("tool_call_id", sa.String(length=80), nullable=True),
        # P-3: V2 retention sweep target. NULL = never expire (V1 default).
        sa.Column("delete_after", sa.DateTime(timezone=True), nullable=True),
        # SSE replay buffer fields.
        sa.Column("event_id", sa.String(length=64), nullable=True),
        sa.Column("event_name", sa.String(length=32), nullable=True),
        sa.Column("event_payload", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_agent_message_session_id", "agent_message", ["session_id"])
    op.create_index("ix_agent_message_insight_id", "agent_message", ["insight_id"])
    op.create_index("ix_agent_message_session_seq", "agent_message", ["session_id", "seq"])
    op.create_index("ix_agent_message_delete_after", "agent_message", ["delete_after"])

    # 4) agent_tool_call
    op.create_table(
        "agent_tool_call",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id", UUID(as_uuid=True),
            sa.ForeignKey("ai_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "insight_id", UUID(as_uuid=True),
            sa.ForeignKey("ai_insight.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tool_call_id", sa.String(length=80), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("args", JSONB(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("token_estimate", sa.Integer(), nullable=True),
        # row_hash captured at fetch time so emit_chart can verify.
        sa.Column("row_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_agent_tool_call_session_id", "agent_tool_call", ["session_id"])
    op.create_index("ix_agent_tool_call_insight_id", "agent_tool_call", ["insight_id"])
    op.create_index("ix_agent_tool_call_tool_name", "agent_tool_call", ["tool_name"])
    op.create_index("ix_agent_tool_call_tool_call_id", "agent_tool_call", ["tool_call_id"])

    # 5) agent_chart
    op.create_table(
        "agent_chart",
        sa.Column("id", sa.String(length=32), primary_key=True),  # ChartSpec.chart_id (e.g. c_a1b2c3d4)
        sa.Column(
            "session_id", UUID(as_uuid=True),
            sa.ForeignKey("ai_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "insight_id", UUID(as_uuid=True),
            sa.ForeignKey("ai_insight.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("spec", JSONB(), nullable=False),
        sa.Column("data_source", JSONB(), nullable=False),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_agent_chart_session_id", "agent_chart", ["session_id"])
    op.create_index("ix_agent_chart_insight_id", "agent_chart", ["insight_id"])

    # 6) agent_citation (V2 — created in V1 for forward-compat, not written)
    op.create_table(
        "agent_citation",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "insight_id", UUID(as_uuid=True),
            sa.ForeignKey("ai_insight.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("agree_or_disagree", sa.String(length=16), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("search_query", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(length=24), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_agent_citation_insight_id", "agent_citation", ["insight_id"])

    # 7) skill_invocation
    op.create_table(
        "skill_invocation",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id", UUID(as_uuid=True),
            sa.ForeignKey("ai_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "insight_id", UUID(as_uuid=True),
            sa.ForeignKey("ai_insight.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("skill_name", sa.String(length=64), nullable=False),
        sa.Column("inputs_hash", sa.String(length=64), nullable=True),
        sa.Column("outputs", JSONB(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("fragment_mode", sa.String(length=16), nullable=True),  # "system" | "user-shaped"
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_skill_invocation_session_id", "skill_invocation", ["session_id"])
    op.create_index("ix_skill_invocation_skill_name", "skill_invocation", ["skill_name"])

    # 8) skill_reference (pgvector)
    op.execute(
        """
        CREATE TABLE skill_reference (
            id            uuid PRIMARY KEY,
            skill_name    varchar(64)    NOT NULL,
            source_path   text           NOT NULL,
            chunk_index   integer        NOT NULL,
            chunk_id      varchar(128)   NOT NULL UNIQUE,
            text          text           NOT NULL,
            embedding     vector(3072),
            token_count   integer,
            content_hash  varchar(64)    NOT NULL,
            created_at    timestamptz    NOT NULL DEFAULT NOW()
        )
        """
    )
    op.create_index("ix_skill_reference_skill_name", "skill_reference", ["skill_name"])
    # Note: ivfflat over vector(3072) requires explicit lists tuning at scale.
    # For V1 (~75 chunks) we skip the ivfflat index — sequential scan is fine.


def downgrade() -> None:
    # Drop in reverse order. Do NOT drop the vector extension; other features
    # may rely on it once V2/V3 lights up.
    op.drop_index("ix_skill_reference_skill_name", table_name="skill_reference")
    op.drop_table("skill_reference")

    op.drop_index("ix_skill_invocation_skill_name", table_name="skill_invocation")
    op.drop_index("ix_skill_invocation_session_id", table_name="skill_invocation")
    op.drop_table("skill_invocation")

    op.drop_index("ix_agent_citation_insight_id", table_name="agent_citation")
    op.drop_table("agent_citation")

    op.drop_index("ix_agent_chart_insight_id", table_name="agent_chart")
    op.drop_index("ix_agent_chart_session_id", table_name="agent_chart")
    op.drop_table("agent_chart")

    op.drop_index("ix_agent_tool_call_tool_call_id", table_name="agent_tool_call")
    op.drop_index("ix_agent_tool_call_tool_name", table_name="agent_tool_call")
    op.drop_index("ix_agent_tool_call_insight_id", table_name="agent_tool_call")
    op.drop_index("ix_agent_tool_call_session_id", table_name="agent_tool_call")
    op.drop_table("agent_tool_call")

    op.drop_index("ix_agent_message_delete_after", table_name="agent_message")
    op.drop_index("ix_agent_message_session_seq", table_name="agent_message")
    op.drop_index("ix_agent_message_insight_id", table_name="agent_message")
    op.drop_index("ix_agent_message_session_id", table_name="agent_message")
    op.drop_table("agent_message")

    op.drop_index("ix_ai_insight_created_at", table_name="ai_insight")
    op.drop_index("ix_ai_insight_session_id", table_name="ai_insight")
    op.drop_table("ai_insight")

    op.drop_index("ix_ai_session_started_at", table_name="ai_session")
    op.drop_index("ix_ai_session_status", table_name="ai_session")
    op.drop_table("ai_session")
