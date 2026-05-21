"""019_earnings_transcripts — Alpha Vantage earnings call transcripts.

Revision ID: 019_earnings_transcripts
Revises: 018_ai_insights_v2_columns
Create Date: 2026-05-12

Mirrors 017_passage_tables for the EDGAR side: parent table holds
structured + sentiment columns; passage table holds BM25 chunks with a
Postgres tsvector trigger + GIN index. UNIQUE(cik, quarter) makes
re-ingest idempotent. FK to parent uses ON DELETE CASCADE so re-chunking
a transcript is a clean delete-then-insert via passage_id.

SQLite (used by some unit tests) does not support tsvector / GIN, so the
migration no-ops the trigger + GIN under non-Postgres backends and falls
back to a TEXT column for ``tsv``.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision: str = "019_earnings_transcripts"
down_revision: Union[str, Sequence[str], None] = "018_ai_insights_v2_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres(bind) -> bool:
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    bind = op.get_bind()
    on_pg = _is_postgres(bind)

    # ------------------------------------------------------------------
    # earnings_transcripts (parent — one row per call)
    # ------------------------------------------------------------------
    op.create_table(
        "earnings_transcripts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("cik", sa.String(length=20), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("quarter", sa.String(length=8), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("fiscal_quarter", sa.Integer(), nullable=True),
        sa.Column("call_date", sa.Date(), nullable=True),
        sa.Column("transcript_url", sa.String(length=1024), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("speaker_count", sa.Integer(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("guidance", JSONB() if on_pg else sa.JSON(), nullable=True),
        sa.Column("capex_mentions", JSONB() if on_pg else sa.JSON(), nullable=True),
        sa.Column("ai_power_mentions", JSONB() if on_pg else sa.JSON(), nullable=True),
        sa.Column("competitive_mentions", JSONB() if on_pg else sa.JSON(), nullable=True),
        sa.Column("mw_capacity_mentions", JSONB() if on_pg else sa.JSON(), nullable=True),
        sa.Column("sentiment_ai_demand", sa.String(length=16), nullable=True),
        sa.Column("sentiment_power_constraints", sa.String(length=16), nullable=True),
        sa.Column("sentiment_datacenter_capex", sa.String(length=16), nullable=True),
        sa.Column("sentiment_overall", sa.String(length=16), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extractor_version", sa.String(length=16), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "cik", "quarter", name="uq_earnings_transcripts_cik_quarter"
        ),
    )
    op.create_index(
        "ix_earnings_transcripts_cik", "earnings_transcripts", ["cik"]
    )
    op.create_index(
        "ix_earnings_transcripts_ticker", "earnings_transcripts", ["ticker"]
    )
    op.create_index(
        "ix_earnings_transcripts_call_date_desc",
        "earnings_transcripts",
        ["call_date"],
    )

    # ------------------------------------------------------------------
    # earnings_passages (BM25 chunks — mirrors edgar_passages)
    # ------------------------------------------------------------------
    passage_columns = [
        sa.Column(
            "passage_id",
            UUID(as_uuid=True) if on_pg else sa.String(length=36),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()") if on_pg else None,
        ),
        sa.Column(
            "document_id",
            sa.BigInteger(),
            sa.ForeignKey("earnings_transcripts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column(
            "tokenizer",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'cl100k_base'"),
        ),
        sa.Column("speaker", sa.String(length=255), nullable=True),
        sa.Column("section", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "document_id", "ord", name="uq_earnings_passages_doc_ord"
        ),
        sa.CheckConstraint(
            "section IS NULL OR section IN ('prepared_remarks','q_and_a')",
            name="ck_earnings_passages_section",
        ),
    ]
    if on_pg:
        passage_columns.append(sa.Column("tsv", sa.Text(), nullable=True))

    op.create_table("earnings_passages", *passage_columns)
    op.create_index(
        "ix_earnings_passages_document_id",
        "earnings_passages",
        ["document_id"],
    )

    if on_pg:
        op.execute(
            "ALTER TABLE earnings_passages "
            "ALTER COLUMN tsv TYPE tsvector USING tsv::tsvector"
        )
        op.execute(
            """
            CREATE OR REPLACE FUNCTION earnings_passages_tsv_update()
            RETURNS trigger AS $$
            BEGIN
              NEW.tsv := to_tsvector('english', coalesce(NEW.text, ''));
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER earnings_passages_tsv_trg
              BEFORE INSERT OR UPDATE OF text ON earnings_passages
              FOR EACH ROW EXECUTE FUNCTION earnings_passages_tsv_update();
            """
        )
        op.execute(
            "CREATE INDEX gin_earnings_passages_tsv "
            "ON earnings_passages USING gin (tsv);"
        )


def downgrade() -> None:
    bind = op.get_bind()
    on_pg = _is_postgres(bind)

    if on_pg:
        op.execute("DROP INDEX IF EXISTS gin_earnings_passages_tsv;")
        op.execute(
            "DROP TRIGGER IF EXISTS earnings_passages_tsv_trg ON earnings_passages;"
        )
        op.execute("DROP FUNCTION IF EXISTS earnings_passages_tsv_update();")
    op.drop_index(
        "ix_earnings_passages_document_id", table_name="earnings_passages"
    )
    op.drop_table("earnings_passages")

    op.drop_index(
        "ix_earnings_transcripts_call_date_desc",
        table_name="earnings_transcripts",
    )
    op.drop_index(
        "ix_earnings_transcripts_ticker", table_name="earnings_transcripts"
    )
    op.drop_index(
        "ix_earnings_transcripts_cik", table_name="earnings_transcripts"
    )
    op.drop_table("earnings_transcripts")
