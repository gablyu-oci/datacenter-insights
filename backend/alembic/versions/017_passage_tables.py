"""017_passage_tables — BM25 passage tables for AI Insights v2 Phase B.1.

Revision ID: 017_passage_tables
Revises: 016_drop_curated_deals
Create Date: 2026-05-07 12:00:00.000000

Phase B.1 of the AI Insights v2 redesign (see
``docs/ai_insights_v2_phases_bcd_architecture.md`` §1.1). Lands two
passage tables that back the new ``search_documents`` MCP tool:

  * ``edgar_passages`` — chunked text from ``edgar_extractions`` (BigInt
    PK on the parent; FK with ON DELETE CASCADE).
  * ``permit_passages`` — chunked text from one of several permit
    document sources. INTENTIONALLY NO HARD FK — ``source_kind`` plus
    ``source_doc_id`` is a polymorphic discriminator (per ADR-002 in the
    architecture doc) because parent tables diverge:
    ``generator_permits`` / ``building_permits`` / EPA-ECHO PDFs / county
    permit PDFs / state permit PDFs. The chunker is the sole writer, so
    referential integrity is enforced at the application layer.

Both tables carry a ``tsv`` tsvector populated by a Postgres trigger
(``BEFORE INSERT OR UPDATE OF text``). We use a trigger rather than
``GENERATED ALWAYS AS (to_tsvector('english', text)) STORED`` because
``to_tsvector`` is *stable* but not *immutable* in some Postgres
configurations, which can break the GENERATED expression. The trigger
shape works on every supported PG version.

Both tables get a GIN index on ``tsv`` (mandatory for ``@@`` queries) and
a unique constraint on ``(document_id, ord)`` / ``(source_kind,
source_doc_id, ord)`` so re-chunking a document is an idempotent
delete-then-insert.

SQLite (used by some unit tests) does not support tsvector / GIN, so the
migration no-ops the trigger + GIN under non-Postgres backends and falls
back to a TEXT column. The ``search_documents`` tool only runs against
Postgres in production.

Downgrade reverses everything in dependency order: drop GIN indexes,
drop triggers, drop trigger functions, drop tables.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "017_passage_tables"
down_revision: Union[str, Sequence[str], None] = "016_drop_curated_deals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_postgres(bind) -> bool:
    return bind.dialect.name == "postgresql"


# Discriminator values for permit_passages.source_kind.
_PERMIT_SOURCE_KINDS = (
    "generator_permit",
    "building_permit",
    "epa_echo_pdf",
    "county_pdf",
    "state_pdf",
)


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    bind = op.get_bind()
    on_pg = _is_postgres(bind)

    # ------------------------------------------------------------------
    # edgar_passages
    # ------------------------------------------------------------------
    edgar_columns = [
        sa.Column(
            "passage_id",
            UUID(as_uuid=True) if on_pg else sa.String(length=36),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()") if on_pg else None,
        ),
        # edgar_extractions.id is BigInteger autoincrement — see migration 002.
        sa.Column(
            "document_id",
            sa.BigInteger(),
            sa.ForeignKey("edgar_extractions.id", ondelete="CASCADE"),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("document_id", "ord", name="uq_edgar_passages_doc_ord"),
    ]
    if on_pg:
        # Postgres-only: tsvector column populated by trigger.
        edgar_columns.append(sa.Column("tsv", sa.Text(), nullable=True))

    op.create_table("edgar_passages", *edgar_columns)
    op.create_index(
        "ix_edgar_passages_document_id",
        "edgar_passages",
        ["document_id"],
    )

    if on_pg:
        # Switch tsv to tsvector; SQLAlchemy doesn't have a first-class
        # tsvector type without pgvector/dialect extras, so we ALTER it.
        op.execute("ALTER TABLE edgar_passages ALTER COLUMN tsv TYPE tsvector USING tsv::tsvector")

        # Trigger function — fenced via CREATE OR REPLACE so re-run is safe.
        op.execute(
            """
            CREATE OR REPLACE FUNCTION edgar_passages_tsv_update()
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
            CREATE TRIGGER edgar_passages_tsv_trg
              BEFORE INSERT OR UPDATE OF text ON edgar_passages
              FOR EACH ROW EXECUTE FUNCTION edgar_passages_tsv_update();
            """
        )
        op.execute(
            "CREATE INDEX gin_edgar_passages_tsv "
            "ON edgar_passages USING gin (tsv);"
        )

    # ------------------------------------------------------------------
    # permit_passages — polymorphic, no hard FK (ADR-002).
    # ------------------------------------------------------------------
    check_clause = " OR ".join(
        f"source_kind = '{k}'" for k in _PERMIT_SOURCE_KINDS
    )

    permit_columns = [
        sa.Column(
            "passage_id",
            UUID(as_uuid=True) if on_pg else sa.String(length=36),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()") if on_pg else None,
        ),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_doc_id", sa.String(length=128), nullable=False),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(check_clause, name="ck_permit_passages_source_kind"),
        sa.UniqueConstraint(
            "source_kind",
            "source_doc_id",
            "ord",
            name="uq_permit_passages_src_doc_ord",
        ),
    ]
    if on_pg:
        permit_columns.append(sa.Column("tsv", sa.Text(), nullable=True))

    op.create_table("permit_passages", *permit_columns)
    op.create_index(
        "ix_permit_passages_source",
        "permit_passages",
        ["source_kind", "source_doc_id"],
    )

    if on_pg:
        op.execute(
            "ALTER TABLE permit_passages ALTER COLUMN tsv TYPE tsvector USING tsv::tsvector"
        )
        op.execute(
            """
            CREATE OR REPLACE FUNCTION permit_passages_tsv_update()
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
            CREATE TRIGGER permit_passages_tsv_trg
              BEFORE INSERT OR UPDATE OF text ON permit_passages
              FOR EACH ROW EXECUTE FUNCTION permit_passages_tsv_update();
            """
        )
        op.execute(
            "CREATE INDEX gin_permit_passages_tsv "
            "ON permit_passages USING gin (tsv);"
        )


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    bind = op.get_bind()
    on_pg = _is_postgres(bind)

    if on_pg:
        op.execute("DROP INDEX IF EXISTS gin_permit_passages_tsv;")
        op.execute("DROP TRIGGER IF EXISTS permit_passages_tsv_trg ON permit_passages;")
        op.execute("DROP FUNCTION IF EXISTS permit_passages_tsv_update();")
    op.drop_index("ix_permit_passages_source", table_name="permit_passages")
    op.drop_table("permit_passages")

    if on_pg:
        op.execute("DROP INDEX IF EXISTS gin_edgar_passages_tsv;")
        op.execute("DROP TRIGGER IF EXISTS edgar_passages_tsv_trg ON edgar_passages;")
        op.execute("DROP FUNCTION IF EXISTS edgar_passages_tsv_update();")
    op.drop_index("ix_edgar_passages_document_id", table_name="edgar_passages")
    op.drop_table("edgar_passages")
