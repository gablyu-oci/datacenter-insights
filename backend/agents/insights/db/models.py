"""SQLAlchemy/SQLModel models matching the alembic 009_ai_insights migration.

Schema authority is the migration; these models exist for typed app-side
reads/writes via the existing async session factory.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import Column, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlmodel import Field, SQLModel

# pgvector is the runtime type for AIInsight.headline_embedding (3072-dim,
# matches text-embedding-3-large). The dependency is optional in the test
# environment; we fall back to a plain SQLAlchemy Text column so import
# succeeds and the round-trip alembic test runs against SQLite without
# pgvector installed. Production reads/writes use the real Vector type.
try:  # pragma: no cover - optional dependency branch
    from pgvector.sqlalchemy import Vector as _PGVector  # type: ignore[import-not-found]

    def _headline_embedding_column() -> Column:
        return Column(_PGVector(3072), nullable=True)

except ImportError:  # pragma: no cover - hit only when pgvector unavailable
    from sqlalchemy import Text as _SAText

    def _headline_embedding_column() -> Column:
        return Column(_SAText(), nullable=True)


# ---------------------------------------------------------------------------
# ai_session
# ---------------------------------------------------------------------------


class AISession(SQLModel, table=True):
    __tablename__ = "ai_session"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    status: str = Field(index=True, max_length=32)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    model: Optional[str] = Field(default=None, max_length=80)
    focus: Optional[str] = None
    max_insights: int = 7
    version: str = Field(default="v2", max_length=8)
    insights_emitted: int = 0
    duration_ms: Optional[int] = None
    budget_status: Optional[str] = Field(default=None, max_length=16)
    created_by: Optional[str] = Field(default=None, max_length=120)
    # Phase 2 (migration 013): idempotency guard for the daily scheduler
    # job. Populated only on scheduler-originated runs; manual sessions
    # leave it NULL so they never collide with the cron uniqueness check.
    cron_run_date: Optional[date] = Field(default=None)
    # Phase 2 (migration 013): post-flight token accounting (D7).
    token_estimate: Optional[int] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# ai_insight
# ---------------------------------------------------------------------------


class AIInsight(SQLModel, table=True):
    __tablename__ = "ai_insight"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    session_id: uuid.UUID = Field(
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("ai_session.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    idx: int
    headline: str
    body: Optional[str] = None
    confidence: str = Field(max_length=16)
    materiality: str = Field(max_length=16)
    skills_run: list[str] = Field(default_factory=list, sa_column=Column(JSONB))
    low_external_support: Optional[bool] = None
    # Phase 2 (migration 013): pgvector(3072). The Python type is `Any`
    # because pgvector binds list[float] at write time and returns a
    # numpy-array-like object at read time. The column is NULL until the
    # mega-synthesis path embeds a fresh headline.
    headline_embedding: Optional[Any] = Field(
        default=None,
        sa_column=_headline_embedding_column(),
    )
    # Phase 2 (migration 013): cross-day "ongoing" linkage. When a freshly
    # synthesized headline scores >= 0.85 cosine vs. a prior-14-day
    # AIInsight, we persist the new row with `ongoing_of_id` pointing at
    # that prior row. Frontend renders the ongoing pill / cyan accent
    # (UX §3 D14) by following this FK.
    ongoing_of_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("ai_insight.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    # Legacy FactPack-era column (migration 013) — provenance now lives
    # in agent_chart (executed_sql + row_hash) + agent_citation rows, so
    # this is NULL on every current insight.
    supporting_row_ids: Optional[list[str]] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    # Migration 018 additions. chart_id is the FK back-edge that
    # `persist_insight` writes after `build_chart` has materialized the
    # chart row; citations is the typed grounding list; open_question_id
    # links into OpenClaw memory.
    chart_id: Optional[str] = Field(default=None, max_length=32)
    citations: Optional[list[dict[str, Any]]] = Field(
        default=None, sa_column=Column(JSONB, nullable=True),
    )
    open_question_id: Optional[str] = Field(default=None, max_length=64)
    version: str = Field(default="v2", max_length=8)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# agent_message
# ---------------------------------------------------------------------------


class AgentMessage(SQLModel, table=True):
    __tablename__ = "agent_message"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    session_id: uuid.UUID = Field(
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("ai_session.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    insight_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("ai_insight.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    # Chat-thread scoping (migration 011). Nullable so legacy rows
    # without a thread stay valid.
    thread_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("insight_thread.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    seq: int = 0
    role: str = Field(max_length=16)
    content: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = Field(
        default=None, sa_column=Column(JSONB),
    )
    tool_call_id: Optional[str] = Field(default=None, max_length=80)
    delete_after: Optional[datetime] = Field(default=None, index=True)
    event_id: Optional[str] = Field(default=None, max_length=64)
    event_name: Optional[str] = Field(default=None, max_length=32)
    event_payload: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# agent_tool_call
# ---------------------------------------------------------------------------


class AgentToolCall(SQLModel, table=True):
    __tablename__ = "agent_tool_call"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    session_id: uuid.UUID = Field(
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("ai_session.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    insight_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("ai_insight.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    tool_call_id: str = Field(max_length=80, index=True)
    tool_name: str = Field(max_length=64, index=True)
    args: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSONB))
    ok: bool = False
    error_code: Optional[str] = Field(default=None, max_length=64)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    latency_ms: Optional[int] = None
    token_estimate: Optional[int] = None
    row_hash: Optional[str] = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# agent_chart
# ---------------------------------------------------------------------------


class AgentChart(SQLModel, table=True):
    __tablename__ = "agent_chart"

    id: str = Field(primary_key=True, max_length=32)
    session_id: uuid.UUID = Field(
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("ai_session.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    insight_id: uuid.UUID = Field(
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("ai_insight.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    spec: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    data_source: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    row_hash: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# agent_citation
# ---------------------------------------------------------------------------


class AgentCitation(SQLModel, table=True):
    __tablename__ = "agent_citation"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    insight_id: uuid.UUID = Field(
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("ai_insight.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    url: str
    title: Optional[str] = None
    snippet: Optional[str] = None
    agree_or_disagree: Optional[str] = Field(default=None, max_length=16)
    rationale: Optional[str] = None
    search_query: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    provider: Optional[str] = Field(default=None, max_length=24)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# skill_invocation
# ---------------------------------------------------------------------------


class SkillInvocation(SQLModel, table=True):
    __tablename__ = "skill_invocation"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    session_id: uuid.UUID = Field(
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("ai_session.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    insight_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("ai_insight.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    skill_name: str = Field(max_length=64, index=True)
    inputs_hash: Optional[str] = Field(default=None, max_length=64)
    outputs: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSONB))
    latency_ms: Optional[int] = None
    fragment_mode: Optional[str] = Field(default=None, max_length=16)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# skill_reference (pgvector). Embedding stored as text in the model layer; we
# write it via raw SQL on the orchestrator side for the dim=3072 vector type.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# insight_thread
# ---------------------------------------------------------------------------


class InsightThread(SQLModel, table=True):
    __tablename__ = "insight_thread"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    insight_id: uuid.UUID = Field(
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("ai_insight.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    session_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_active: datetime = Field(default_factory=datetime.utcnow)
    delete_after: Optional[datetime] = None


# ---------------------------------------------------------------------------
# insight_subscription (subscribe button writes here; cron consumes)
# ---------------------------------------------------------------------------


class InsightSubscription(SQLModel, table=True):
    __tablename__ = "insight_subscription"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    insight_id: uuid.UUID = Field(
        sa_column=Column(
            UUID(as_uuid=True),
            ForeignKey("ai_insight.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    criteria_json: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    enabled: bool = False


# ---------------------------------------------------------------------------
# skill_reference (pgvector)
# ---------------------------------------------------------------------------


class SkillReference(SQLModel, table=True):
    __tablename__ = "skill_reference"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    skill_name: str = Field(max_length=64, index=True)
    source_path: str
    chunk_index: int
    chunk_id: str = Field(max_length=128, unique=True)
    text: str
    # `embedding` column is `vector(3072)` in Postgres; SQLAlchemy maps via
    # the pgvector library at runtime. We omit it from the SQLModel to avoid
    # a hard dependency at import time; raw SQL writes/queries handle it.
    token_count: Optional[int] = None
    content_hash: str = Field(max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow)
