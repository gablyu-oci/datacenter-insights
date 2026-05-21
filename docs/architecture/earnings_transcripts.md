# Architecture: Earnings Call Transcripts

**Status:** Approved for build
**Architect:** System Architect (strategic-insights-tool)
**Owner:** Backend + Frontend agents (paste structures from here verbatim where indicated)
**Last updated:** 2026-05-12
**Sources of truth:**
- PRD: `docs/prd/earnings_transcripts.md`
- Plan: `/home/ubuntu/.claude/plans/i-want-to-include-dynamic-summit.md`
- Research: `docs/research/alpha_vantage_earnings.md`

> This document is the engineering contract. Where it says "exact",
> "canonical", or "paste verbatim", downstream agents should not deviate
> without an ADR. Open items live in the Risks section.

---

## 1. System Overview

We extend the existing ingestion + agent + UI stack with a parallel
earnings-transcripts lane that mirrors the EDGAR lane file-for-file. The
new lane consumes Alpha Vantage's `EARNINGS_CALL_TRANSCRIPT` and
`EARNINGS_CALENDAR` endpoints for the ~30 US-public companies in
`TRACKED_FILERS`, lands two new tables (`earnings_transcripts`,
`earnings_passages`), and surfaces results through three additive
endpoints under `/api/earnings` plus a new "Earnings Calls" tab. The
synthesis agent gains an `earnings` branch on the existing
`search_documents` tool so it can cite transcript quotes alongside
filings.

Design constraints:
- **Strictly additive.** No existing edgar / permits / insights logic
  changes. Failure of the earnings lane must not affect any other lane.
- **Adapter parity.** New adapter conforms to the `DataSourceAdapter`
  Protocol; new passage table mirrors `edgar_passages` shape so the
  search tool can polymorphically merge results.
- **Free-tier safe.** Alpha Vantage free tier is 25 calls/day; the
  adapter enforces an internal daily-call counter and short-circuits at
  24 to leave one call of headroom.
- **Idempotent.** `(cik, quarter)` is the natural key. Re-running the
  adapter is a no-op for already-extracted transcripts.

---

## 2. Architecture Diagram (ASCII)

```
                      ┌─────────────────────────────────┐
                      │      Alpha Vantage API          │
                      │   EARNINGS_CALENDAR (CSV)       │
                      │   EARNINGS_CALL_TRANSCRIPT(JSON)│
                      └─────────┬───────────────────────┘
                                │ httpx.AsyncClient
                                │ stamina retries
                                │ semaphore=1, 12.5s delay
                                ▼
       ┌─────────────────────────────────────────────────────────┐
       │  EarningsTranscriptsAdapter                              │
       │  backend/ingestion/earnings_transcripts.py               │
       │                                                          │
       │  ┌────────────┐  ┌────────────┐  ┌──────────────────┐    │
       │  │  fetch()   │→ │ normalize()│→ │ upsert()         │    │
       │  │ calendar + │  │  AV JSON → │  │  ON CONFLICT     │    │
       │  │ transcripts│  │  canonical │  │  (cik, quarter)  │    │
       │  └────────────┘  └────────────┘  └────────┬─────────┘    │
       │  raw cache: data/cache/earnings_TICKER_YYYYQM.json (12h) │
       │  daily-call counter: ingestion_runs.config_snapshot      │
       └─────────┬─────────────────────────────────────────┬──────┘
                 │                                         │
                 ▼                                         ▼
   ┌──────────────────────────┐         ┌─────────────────────────┐
   │  earnings_chunker.py     │         │  earnings_extractor.py  │
   │  speaker-aware turns     │         │  Claude Sonnet 4.6      │
   │  prepared vs Q&A by      │         │  single-pass JSON       │
   │  Operator-turn heuristic │         │  substring quote-       │
   │  cl100k_base, ~500 tok   │         │  validation invariant   │
   │  hard cap 800            │         │  → guidance, capex,     │
   └──────────┬───────────────┘         │    ai_power, competitive│
              │                          │    mw_capacity, 4-axis │
              │                          │    sentiment          │
              │                          └────────────┬───────────┘
              ▼                                       ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  Postgres                                                   │
   │  ┌───────────────────────────┐  ┌────────────────────────┐  │
   │  │ earnings_transcripts      │  │ earnings_passages      │  │
   │  │  - parent, JSONB columns  │  │  - BM25 chunks         │  │
   │  │  - sentiment + structured │  │  - tsvector + GIN      │  │
   │  │  - UNIQUE(cik, quarter)   │  │  - FK ON DELETE CASCADE│  │
   │  └───────────────────────────┘  └────────────────────────┘  │
   │  ingestion_runs / data_coverage / data_lineage (reused)     │
   └──────────┬──────────────────────────────────────────┬───────┘
              │                                          │
              ▼                                          ▼
   ┌─────────────────────────┐         ┌───────────────────────────┐
   │ search_documents()      │         │ /api/earnings  (router)   │
   │  source="earnings"      │         │ /api/earnings/{id}        │
   │  source="all" → merge   │         │ /api/companies/{id}/      │
   │  + re-rank by score     │         │   earnings                │
   │  → cited by synthesis   │         │ LineageEnvelope / Coverage│
   └─────────────────────────┘         └──────────┬────────────────┘
                                                  │
                                                  ▼
                                ┌──────────────────────────────────┐
                                │  Frontend                        │
                                │  EarningsTab.tsx (feed + modal)  │
                                │  CompanyDetailPanel section      │
                                │  useApi<T>, CitationFooter       │
                                └──────────────────────────────────┘

   ── Scheduler (backend/pipeline/runner.py) ─────────────────────────
   06:00 UTC  edgar_daily          (existing)
   06:15 UTC  quarterly_filings    (existing)
   06:45 UTC  earnings_transcripts ← NEW
   07:00 UTC  permits_state        (existing)
   ...
   09:00 UTC  insights_daily       (existing — sees today's transcripts)
```

---

## 3. Components & Responsibilities

| Component | File | Responsibility |
|---|---|---|
| Adapter | `backend/ingestion/earnings_transcripts.py` (new) | Resolve tickers; gate on calendar; rate-limit; cache raw JSON; upsert parent row; dispatch chunker + extractor; write lineage/coverage |
| Chunker | `backend/ingestion/earnings_chunker.py` (new) | Speaker-aware ~500-tok passages with hard cap 800; section tag (`prepared_remarks` \| `q_and_a`); replace-then-insert by `document_id` |
| Extractor | `backend/agents/earnings_extractor.py` (new) | One Sonnet 4.6 call per transcript; strict JSON schema; substring quote-validation; populate parent's JSONB + sentiment columns |
| Migration | `backend/alembic/versions/019_earnings_transcripts.py` (new) | Create `earnings_transcripts` + `earnings_passages`; tsvector trigger + GIN; mirror 017 pattern |
| Search tool | `backend/agents/insights/tools/search_documents.py` (edit) | Add `_EARNINGS_SQL`, `_shape_earnings_row`, extend `ALLOWED_SOURCES`, merge in `source="all"` |
| API router | `backend/routers/earnings.py` (new) | Three endpoints; LineageEnvelope/CoverageEnvelope; pagination + filter parsing |
| Scheduler | `backend/pipeline/runner.py` (edit) | Add `earnings_transcripts_daily` to `JOB_CONFIG` + `_JOB_FUNCTIONS`; new invoke helper |
| Frontend tab | `frontend/src/components/tabs/EarningsTab.tsx` (new) | Feed + filters + modal |
| Frontend section | `frontend/src/components/tabs/CompaniesTab.tsx` (edit) | New "Earnings Calls" section in `CompanyDetailPanel` |
| Nav | `frontend/src/App.tsx`, `frontend/src/components/layout/TabNav.tsx` (edit) | Add `earnings` tab id |
| Workspace docs | `.openclaw/workspace/SCHEMA.md`, `FRESHNESS.md`, `AI_INSIGHTS_PLAYBOOK.md` (edit) | Inform synthesis agent about the new source |

Failure-isolation rule: each component must catch exceptions at its
boundary and write `ingestion_runs.status='partial_failure'` rather than
re-raise, except for fatal errors (DB connection lost), which the
`_run_adapter_job` wrapper already handles.

---

## 4. Data Models

### 4.1 SQLAlchemy model — `earnings_transcripts`

Add to `backend/db/models.py` alongside `EdgarExtraction`. Column types
mirror `EdgarExtraction` where applicable.

```python
from sqlalchemy import (
    BigInteger, Column, Date, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

class EarningsTranscript(Base):
    __tablename__ = "earnings_transcripts"

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    cik             = Column(String(20), nullable=False, index=True)
    ticker          = Column(String(16), nullable=False, index=True)
    company_name    = Column(String(255), nullable=False)
    quarter         = Column(String(8),  nullable=False)   # e.g. '2026Q1'
    fiscal_year     = Column(Integer,    nullable=True)
    fiscal_quarter  = Column(Integer,    nullable=True)
    call_date       = Column(Date,       nullable=True, index=True)
    transcript_url  = Column(String(1024), nullable=True)
    raw_text        = Column(Text,       nullable=False)
    speaker_count   = Column(Integer,    nullable=True)
    word_count      = Column(Integer,    nullable=True)

    # Structured highlights — see §4.4 for JSONB sub-shapes
    guidance              = Column(JSONB, nullable=True)
    capex_mentions        = Column(JSONB, nullable=True)
    ai_power_mentions     = Column(JSONB, nullable=True)
    competitive_mentions  = Column(JSONB, nullable=True)
    mw_capacity_mentions  = Column(JSONB, nullable=True)

    # Sentiment (LLM-tagged enums)
    sentiment_ai_demand          = Column(String(16), nullable=True)
    sentiment_power_constraints  = Column(String(16), nullable=True)
    sentiment_datacenter_capex   = Column(String(16), nullable=True)
    sentiment_overall            = Column(String(16), nullable=True)

    extracted_at      = Column(DateTime(timezone=True), nullable=True)
    extractor_version = Column(String(16), nullable=True)
    retrieved_at      = Column(DateTime(timezone=True), nullable=False)
    created_at        = Column(DateTime(timezone=True), nullable=False,
                               server_default=text("now()"))

    passages = relationship(
        "EarningsPassage", back_populates="transcript",
        cascade="all, delete-orphan", passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("cik", "quarter", name="uq_earnings_transcripts_cik_quarter"),
        Index("ix_earnings_transcripts_call_date_desc", "call_date"),
    )
```

### 4.2 SQLAlchemy model — `earnings_passages`

```python
class EarningsPassage(Base):
    __tablename__ = "earnings_passages"

    passage_id   = Column(UUID(as_uuid=True), primary_key=True,
                          server_default=text("gen_random_uuid()"))
    document_id  = Column(BigInteger,
                          ForeignKey("earnings_transcripts.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    ord          = Column(Integer, nullable=False)
    text         = Column(Text,    nullable=False)
    char_start   = Column(Integer, nullable=False)
    char_end     = Column(Integer, nullable=False)
    token_count  = Column(Integer, nullable=False)
    tokenizer    = Column(String(64), nullable=False,
                          server_default=text("'cl100k_base'"))
    speaker      = Column(String(255), nullable=True)
    section      = Column(String(32),  nullable=True)   # 'prepared_remarks' | 'q_and_a'
    # tsv populated by Postgres trigger (see migration)
    created_at   = Column(DateTime(timezone=True), nullable=False,
                          server_default=text("now()"))

    transcript = relationship("EarningsTranscript", back_populates="passages")

    __table_args__ = (
        UniqueConstraint("document_id", "ord", name="uq_earnings_passages_doc_ord"),
    )
```

### 4.3 Sentiment enum values

All four sentiment columns share this domain (case-sensitive):

```
bullish | cautious | bearish | not_mentioned
```

Enforced at the LLM extractor; not enforced via Postgres CHECK
constraint (we keep the column as `String(16)` so a future fifth axis
or value doesn't require a migration).

### 4.4 JSONB sub-shapes (canonical)

`guidance` — single object (call may have at most one consolidated
guidance set):
```json
{
  "revenue_growth": "string | null",
  "capex_outlook":  "string | null",
  "raw_quote":      "string"
}
```

`capex_mentions` — array:
```json
[
  {
    "quote": "string (verbatim from raw_text)",
    "dollar_amount": "string | null",
    "context": "string | null"
  }
]
```

`ai_power_mentions` — array:
```json
[
  {
    "quote": "string",
    "theme": "AI | datacenter | power | grid",
    "context": "string | null"
  }
]
```

`competitive_mentions` — array:
```json
[
  {
    "quote": "string",
    "mentioned_company": "string",
    "sentiment": "positive | neutral | negative"
  }
]
```

`mw_capacity_mentions` — array:
```json
[
  {
    "quote": "string",
    "mw_value": "number | null",
    "location": "string | null"
  }
]
```

Empty arrays are valid; the API hides empty sections in the UI. `null`
values are dropped from cards but preserved in the DB row.

---

## 5. Migration `019_earnings_transcripts.py` — exact SQL

Paste verbatim into `backend/alembic/versions/019_earnings_transcripts.py`.
Revision = `019_earnings_transcripts`, down_revision = `018_ai_insights_v2_columns`.

```python
"""019_earnings_transcripts — Alpha Vantage earnings call transcripts.

Revision ID: 019_earnings_transcripts
Revises: 018_ai_insights_v2_columns
Create Date: 2026-05-12

Mirrors 017_passage_tables for the EDGAR side: parent table holds
structured + sentiment columns; passage table holds BM25 chunks with a
Postgres tsvector trigger + GIN index. UNIQUE(cik, quarter) makes
re-ingest idempotent. FK to parent uses ON DELETE CASCADE so re-chunking
a transcript is a clean delete-then-insert via passage_id.
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
    # earnings_transcripts (parent)
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
        sa.Column("guidance",             JSONB() if on_pg else sa.JSON(), nullable=True),
        sa.Column("capex_mentions",       JSONB() if on_pg else sa.JSON(), nullable=True),
        sa.Column("ai_power_mentions",    JSONB() if on_pg else sa.JSON(), nullable=True),
        sa.Column("competitive_mentions", JSONB() if on_pg else sa.JSON(), nullable=True),
        sa.Column("mw_capacity_mentions", JSONB() if on_pg else sa.JSON(), nullable=True),
        sa.Column("sentiment_ai_demand",         sa.String(length=16), nullable=True),
        sa.Column("sentiment_power_constraints", sa.String(length=16), nullable=True),
        sa.Column("sentiment_datacenter_capex",  sa.String(length=16), nullable=True),
        sa.Column("sentiment_overall",           sa.String(length=16), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extractor_version", sa.String(length=16), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("cik", "quarter", name="uq_earnings_transcripts_cik_quarter"),
    )
    op.create_index(
        "ix_earnings_transcripts_cik", "earnings_transcripts", ["cik"],
    )
    op.create_index(
        "ix_earnings_transcripts_ticker", "earnings_transcripts", ["ticker"],
    )
    op.create_index(
        "ix_earnings_transcripts_call_date_desc",
        "earnings_transcripts", ["call_date"],
    )

    # ------------------------------------------------------------------
    # earnings_passages (BM25 chunks)
    # ------------------------------------------------------------------
    columns = [
        sa.Column(
            "passage_id",
            UUID(as_uuid=True) if on_pg else sa.String(length=36),
            primary_key=True, nullable=False,
            server_default=sa.text("gen_random_uuid()") if on_pg else None,
        ),
        sa.Column(
            "document_id", sa.BigInteger(),
            sa.ForeignKey("earnings_transcripts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column(
            "tokenizer", sa.String(length=64), nullable=False,
            server_default=sa.text("'cl100k_base'"),
        ),
        sa.Column("speaker", sa.String(length=255), nullable=True),
        sa.Column("section", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("document_id", "ord",
                            name="uq_earnings_passages_doc_ord"),
        sa.CheckConstraint(
            "section IS NULL OR section IN ('prepared_remarks','q_and_a')",
            name="ck_earnings_passages_section",
        ),
    ]
    if on_pg:
        columns.append(sa.Column("tsv", sa.Text(), nullable=True))

    op.create_table("earnings_passages", *columns)
    op.create_index(
        "ix_earnings_passages_document_id",
        "earnings_passages", ["document_id"],
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
        op.execute("DROP TRIGGER IF EXISTS earnings_passages_tsv_trg ON earnings_passages;")
        op.execute("DROP FUNCTION IF EXISTS earnings_passages_tsv_update();")
    op.drop_index("ix_earnings_passages_document_id", table_name="earnings_passages")
    op.drop_table("earnings_passages")

    op.drop_index("ix_earnings_transcripts_call_date_desc", table_name="earnings_transcripts")
    op.drop_index("ix_earnings_transcripts_ticker", table_name="earnings_transcripts")
    op.drop_index("ix_earnings_transcripts_cik", table_name="earnings_transcripts")
    op.drop_table("earnings_transcripts")
```

---

## 6. Adapter Class Skeleton

File: `backend/ingestion/earnings_transcripts.py`

Exact method signatures (matches `DataSourceAdapter` Protocol; matches
`EdgarAdapter` patterns from `backend/ingestion/edgar.py`):

```python
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from datetime import date, datetime, timedelta

import httpx
import stamina
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from agents.edgar_agent import TRACKED_FILERS, _load_cache, _save_cache
from db.models import DataCoverage, IngestionRun, EarningsTranscript

logger = logging.getLogger(__name__)

# ---------- Constants (from research §7) -----------------------------------
ALPHA_VANTAGE_BASE_URL       = "https://www.alphavantage.co/query"
TRANSCRIPT_CACHE_TTL_HOURS   = 12
CALENDAR_CACHE_TTL_HOURS     = 12
MAX_DAILY_CALLS              = 24
RETRY_WINDOW_DAYS            = 7
MAX_RETRIES_PER_QUARTER      = 7
SEMAPHORE_LIMIT              = 1
INTER_CALL_DELAY_SECONDS     = 12.5
HTTP_TIMEOUT_SECONDS         = 30.0


class EarningsTranscriptsAdapter:
    """Alpha Vantage earnings-call-transcript ingestion adapter.

    Conforms to backend/ingestion/base.py:DataSourceAdapter Protocol.
    """

    adapter_name      = "Alpha Vantage Earnings Transcripts"
    adapter_id        = "earnings_transcripts"
    adapter_version   = "1.0.0"
    pillar            = "earnings_intelligence"
    source_id         = "alpha_vantage"
    declared_status   = "live"
    coverage_scope    = "US"

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
        self._client: httpx.AsyncClient | None = None
        self._daily_calls_used: int = 0

    # ---------------- DataSourceAdapter contract --------------------------

    async def fetch(self) -> list[dict]:
        """Pull (a) calendar CSV, (b) candidate transcripts.

        Returns a flat list of {ticker, cik, company_name, quarter,
        call_date, raw_payload} dicts. One element per (cik, quarter)
        that needs processing. Returns [] if budget exhausted before any
        transcript fetch.
        """
        ...

    async def normalize(self, raw: list[dict]) -> list[dict]:
        """AV payload → canonical row dict.

        - Concatenate `transcript[].content` into `raw_text`.
        - Compute `speaker_count`, `word_count`.
        - Derive `call_date` from calendar `reportDate` (or null).
        - Compute fiscal_year / fiscal_quarter from quarter string.
        """
        ...

    async def upsert(self, session: AsyncSession, records: list[dict]) -> int:
        """ON CONFLICT (cik, quarter) DO UPDATE.

        After upsert, dispatch chunker + extractor for each new/changed
        row. Returns number of parent rows written.
        """
        ...

    async def write_lineage(self, session, run_id: int, record_count: int) -> None: ...
    async def write_coverage(self, session) -> None: ...

    # ---------------- Orchestration entry point ---------------------------

    async def run(
        self,
        session: AsyncSession,
        *,
        ticker_filter: list[str] | None = None,
        days_back: int = 90,
    ) -> dict:
        """fetch → normalize → upsert → chunker → extractor → coverage.

        ticker_filter narrows the run to a subset (used by tests / dry-run).
        Returns the standard summary dict
        {fetched, stored, skipped, classifier_rejected, errors}.
        """
        ...

    # ---------------- Helpers (private, but exposed for tests) ------------

    async def _fetch_calendar(self) -> list[dict]: ...
    async def _fetch_transcript(self, symbol: str, quarter: str) -> dict: ...
    def    _check_throttled(self, payload: dict) -> None: ...   # raises if AV throttle
    async def _gate_daily_budget(self) -> bool: ...             # returns False if exhausted
    async def _is_already_extracted(self, session, cik: str, quarter: str) -> bool: ...
    def    _quarter_from_date(self, d: date) -> str: ...        # date → '2026Q1'
```

### 6.1 TRACKED_FILERS subset — canonical US-public tickers (paste verbatim)

The adapter targets US-public companies only. Foreign filers and
private/pre-IPO companies are excluded at the resolution step. **This
list is the source of truth** — derived by reading
`backend/agents/edgar_agent.py` and applying the explicit skip list
(TSMC/TSM, ASE Technology, NuScale, Oklo, X-Energy) plus the implicit
FPI/no-ticker rules.

```python
# US-public tickers eligible for Alpha Vantage earnings transcripts.
# Maps TRACKED_FILERS display_name → ticker symbol.
EARNINGS_ELIGIBLE_TICKERS: dict[str, str] = {
    # ---- Hyperscalers (5) ----
    "Microsoft":            "MSFT",
    "Amazon":               "AMZN",
    "Alphabet":             "GOOGL",
    "Meta":                 "META",
    "Oracle":               "ORCL",
    # ---- Energy / IPP / Utility — US-public (6) ----
    "Constellation Energy": "CEG",
    "Talen Energy":         "TLN",
    "Vistra Energy":        "VST",
    "NextEra Energy":       "NEE",
    "AES Corporation":      "AES",
    "Dominion Energy":      "D",
    # ---- Silicon (US-public, non-FPI) — 8 ----
    "NVIDIA":               "NVDA",
    "AMD":                  "AMD",
    "Intel-DCAI":           "INTC",   # one ticker for the Intel filer
    "Broadcom":             "AVGO",
    "Marvell":              "MRVL",
    "Coherent":             "COHR",
    "Lumentum":             "LITE",
    "Credo":                "CRDO",
    "Astera Labs":          "ALAB",
    "Fabrinet":             "FN",
    "Amkor":                "AMKR",
    "Applied Materials":    "AMAT",
    # ---- Additional power-pillar (POWER_FILERS) US-public — 13 ----
    "Apple":                "AAPL",
    "IBM":                  "IBM",
    "Duke Energy":          "DUK",
    "Southern Co":          "SO",
    "AEP":                  "AEP",
    "Exelon":               "EXC",
    "Entergy":              "ETR",
    "PG&E":                 "PCG",
    "Snowflake":            "SNOW",
    "Palantir":             "PLTR",
    "ServiceNow":           "NOW",
    "Salesforce":           "CRM",
    "MongoDB":              "MDB",
    "Datadog":              "DDOG",
    "Equinix":              "EQIX",
    "Digital Realty":       "DLR",
    "Iron Mountain":        "IRM",
}

# Explicit skip list (logged at startup so coverage is auditable).
EARNINGS_SKIPPED: dict[str, str] = {
    "TSMC":             "FPI 20-F filer; Alpha Vantage returns []",
    "ASE Technology":   "FPI 20-F filer; Alpha Vantage returns []",
    "GlobalFoundries":  "FPI 20-F filer",
    "ASML":             "FPI 20-F filer",
    "NuScale Power":    "Excluded per skip list (pre-IPO/SPAC volatility)",
    "Oklo":             "Excluded per skip list (pre-IPO/SPAC volatility)",
    "X-Energy":         "Private, no SEC filings",
    # Intel-Foundry collapses into Intel-DCAI (one filer, one ticker).
}
```

Total in-scope: **~30 tickers** × 4 quarters/year = **120 transcripts/year**.
Plus 1 calendar call/day = 365/year. Plus retries (~150/year).
**Blended ~1.8 calls/day** — well inside the 25/day free-tier cap (research §3).

### 6.2 Throttle detection (research §4 gotcha)

Alpha Vantage returns HTTP 200 with `{"Information": "..."}` or
`{"Note": "..."}` when rate-limited. The adapter must check for these
keys after each call:

```python
def _check_throttled(self, payload: dict) -> None:
    if "Information" in payload or "Note" in payload:
        msg = payload.get("Information") or payload.get("Note")
        raise RuntimeError(f"alpha_vantage_throttled: {msg}")
```

### 6.3 Daily-budget gate

Before any HTTP call:

```python
async def _gate_daily_budget(self) -> bool:
    if self._daily_calls_used >= MAX_DAILY_CALLS:
        logger.warning("earnings.daily_budget_exhausted",
                       extra={"used": self._daily_calls_used})
        return False
    return True
```

On exhaustion the adapter writes a `data_lineage` row with
`status='skipped_quota'` and exits cleanly (does not raise).

### 6.4 Idempotency check

Before any transcript fetch:

```sql
SELECT id, extracted_at, retrieved_at
FROM earnings_transcripts
WHERE cik = :cik AND quarter = :quarter;
```

If the row exists with `extracted_at IS NOT NULL` AND
`retrieved_at > now() - interval '30 days'`, skip the AV call entirely.

### 6.5 Retry window for unavailable transcripts

If `transcript[]` is empty in the AV response, this is a "not yet
published" signal. The adapter inserts a placeholder row with
`raw_text=''`, `extracted_at=NULL`, and a marker in `extractor_version`
(`pending-{N}` where N is the attempt count). After
`MAX_RETRIES_PER_QUARTER` (7) consecutive failed attempts, the row's
`extractor_version` is set to `transcript_unavailable` and the adapter
stops retrying.

---

## 7. Chunker Design

File: `backend/ingestion/earnings_chunker.py`

### 7.1 Entry point

```python
async def chunk_transcript(
    session: AsyncSession,
    transcript_id: int,
    raw_payload: dict,
    *,
    target_tokens: int = 500,
    max_tokens: int = 800,
) -> int:
    """Replace-then-insert all passages for one transcript.

    Returns count of passages written.
    """
```

### 7.2 Algorithm

1. **Read the parsed payload.** `raw_payload["transcript"]` is the
   array of `{speaker, title, content, sentiment}` dicts.
2. **Detect prepared-remarks / Q&A boundary** (research §1 heuristic):
   a. Scan in order for the first turn whose `speaker` or `title`
      matches `/operator/i` AND whose `content` contains any of
      `questions`, `Q&A`, `Q and A`, `analyst`, `first question`.
   b. **Backup**: if no Operator boundary found, after the first 60% of
      turns the first turn whose `title` contains `Analyst` or whose
      `speaker` contains an affiliation marker (`–`, `—`, `at`).
   c. **Last resort**: treat the entire transcript as `prepared_remarks`
      (log a warning so we can audit).
3. **Tag each turn** with `section = "prepared_remarks"` until the
   boundary, then `"q_and_a"`.
4. **Token-aware packing within speaker turns.**
   - Use `tiktoken.get_encoding("cl100k_base")` (already used by the
     EDGAR chunker).
   - For each turn:
     - If `token_count(turn.content) <= target_tokens`, emit one passage
       carrying `(speaker, section)`.
     - If `target_tokens < token_count <= max_tokens`, still emit as a
       single passage (do not split — preserves single-thought integrity).
     - If `token_count > max_tokens`, split on sentence boundaries
       (`r"(?<=[.!?])\s+"`); pack sentences greedily until adding the
       next would exceed `max_tokens`, then start a new passage. Carry
       the same `(speaker, section)` on all child passages.
   - **Q&A merging exception**: within `q_and_a`, if two consecutive
     turns are an analyst-question + management-answer pair AND their
     combined token count is `<= max_tokens`, emit a single passage
     carrying `speaker = "{analyst} / {answerer}"`. This preserves
     question-answer context for BM25 ranking.
5. **Compute char_start / char_end** against the concatenated `raw_text`
   stored on the parent. The concatenation order is the same as the
   transcript array; use a running cursor.
6. **Write the passages**:
   ```sql
   DELETE FROM earnings_passages WHERE document_id = :id;
   -- then batched INSERT
   ```
   Wrapped in the caller's transaction.

### 7.3 Tokenizer

```python
import tiktoken
_ENC = tiktoken.get_encoding("cl100k_base")
def _count_tokens(s: str) -> int:
    return len(_ENC.encode(s))
```

Persist `tokenizer = "cl100k_base"` on every passage so the column stays
auditable when we change tokenizers.

---

## 8. LLM Extractor Design

File: `backend/agents/earnings_extractor.py`
Prompt template: `backend/agents/prompts/earnings_extraction_v1.md`

### 8.1 Model

```python
from llm.client import MODELS, llm_client
# Use the existing extraction-tier model; matches edgar_extractor.
# Plan calls for "Claude Sonnet 4.6"; the existing wrapper maps
# MODELS["extraction"] to that family.
MODEL = MODELS["extraction"]
```

One Sonnet 4.6 call per transcript (single-pass; ~8K input tokens
typical, ~20K worst case — well within 200K context).

Estimated cost (research §6): **~$8/year** at 140 transcripts/year.

### 8.2 Prompt template structure

`earnings_extraction_v1.md`:

```
You are an equity-research analyst extracting structured signals from a
quarterly earnings call transcript. Read the FULL TRANSCRIPT BELOW and
return a JSON object exactly matching the schema given. Every extracted
`quote` field must be a verbatim substring of the input transcript —
do not paraphrase, summarize, or invent text. If a category has no
signal, return an empty array. Sentiment values must be exactly one of:
bullish, cautious, bearish, not_mentioned.

SCHEMA (additionalProperties=false):
<inlined JSON schema, see §8.3>

FIELD DEFINITIONS:
- guidance: one consolidated object across ALL guidance language. Pick
  the most quantitative statement on revenue + capex outlook.
- capex_mentions: ALL specific capex disclosures or capex-trajectory
  comments. `dollar_amount` is a verbatim string like "$15 billion".
- ai_power_mentions: ANY mention of AI demand, datacenter buildout,
  power supply / grid constraint, or generation procurement.
  `theme` must be one of: AI, datacenter, power, grid.
- competitive_mentions: management naming a competitor and characterizing
  the dynamic. `sentiment` ∈ {positive, neutral, negative} from the
  filer's perspective.
- mw_capacity_mentions: explicit MW or GW figures tied to a site or
  deal. `mw_value` is a NUMBER in MW (convert GW → MW × 1000); null if
  the quote names a site but no figure.

SENTIMENT AXES:
- sentiment_ai_demand:         is the filer's AI demand outlook ___?
- sentiment_power_constraints: how worried about power / grid supply?
                               bullish = "no concern"; bearish = "major risk"
- sentiment_datacenter_capex:  posture toward continuing/expanding capex
- sentiment_overall:           aggregate management tone

INVARIANTS:
- If you cannot find a verbatim quote, drop the entry. Never fabricate.
- Empty arrays are valid. `not_mentioned` is valid for sentiment.

TRANSCRIPT:
<<<
{raw_text}
>>>
```

### 8.3 Output JSON schema (strict)

```python
EARNINGS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "guidance",
        "capex_mentions", "ai_power_mentions",
        "competitive_mentions", "mw_capacity_mentions",
        "sentiment_ai_demand", "sentiment_power_constraints",
        "sentiment_datacenter_capex", "sentiment_overall",
    ],
    "properties": {
        "guidance": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                "revenue_growth": {"type": ["string", "null"]},
                "capex_outlook":  {"type": ["string", "null"]},
                "raw_quote":      {"type": "string"},
            },
            "required": ["raw_quote"],
        },
        "capex_mentions": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["quote"],
                "properties": {
                    "quote":         {"type": "string"},
                    "dollar_amount": {"type": ["string", "null"]},
                    "context":       {"type": ["string", "null"]},
                },
            },
        },
        "ai_power_mentions": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["quote", "theme"],
                "properties": {
                    "quote":   {"type": "string"},
                    "theme":   {"type": "string",
                                "enum": ["AI", "datacenter", "power", "grid"]},
                    "context": {"type": ["string", "null"]},
                },
            },
        },
        "competitive_mentions": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["quote", "mentioned_company", "sentiment"],
                "properties": {
                    "quote":             {"type": "string"},
                    "mentioned_company": {"type": "string"},
                    "sentiment": {"type": "string",
                                  "enum": ["positive", "neutral", "negative"]},
                },
            },
        },
        "mw_capacity_mentions": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["quote"],
                "properties": {
                    "quote":    {"type": "string"},
                    "mw_value": {"type": ["number", "null"]},
                    "location": {"type": ["string", "null"]},
                },
            },
        },
        "sentiment_ai_demand": {
            "type": "string",
            "enum": ["bullish", "cautious", "bearish", "not_mentioned"],
        },
        "sentiment_power_constraints": {
            "type": "string",
            "enum": ["bullish", "cautious", "bearish", "not_mentioned"],
        },
        "sentiment_datacenter_capex": {
            "type": "string",
            "enum": ["bullish", "cautious", "bearish", "not_mentioned"],
        },
        "sentiment_overall": {
            "type": "string",
            "enum": ["bullish", "cautious", "bearish", "not_mentioned"],
        },
    },
}
```

### 8.4 Quote-validation invariant (the critical defense)

Mirrors `validate_buyer()` in `backend/agents/edgar_extractor.py`. After
the LLM returns:

```python
def _validate_quotes(extracted: dict, raw_text: str) -> dict:
    """Drop any extracted entry whose `quote` is not a verbatim substring.

    Quote matching is normalized whitespace (collapse runs of whitespace
    to single space, strip leading/trailing) on both sides — Alpha
    Vantage transcripts sometimes have extra spaces around punctuation.

    Returns the cleaned dict and a counts dict (kept | dropped).
    Logs each drop with the offending quote at WARN.
    """
```

Apply to: `guidance.raw_quote`, `capex_mentions[].quote`,
`ai_power_mentions[].quote`, `competitive_mentions[].quote`,
`mw_capacity_mentions[].quote`. If `guidance.raw_quote` fails, the
entire `guidance` is set to `null` (not an empty object).

PRD success metric: <5% of extracted entries fail validation.

### 8.5 Persistence

```python
async def extract_and_persist(session, transcript_id: int) -> dict:
    """Single-pass extract; validate quotes; UPDATE the parent row in place.

    Sets extractor_version='earnings-llm-v1' and extracted_at=now().
    Returns counters: {validated, dropped, errors}.
    """
```

The extractor does NOT touch `earnings_passages` — that's the chunker's
job. The two run sequentially, both inside the adapter's `upsert()`
flow.

---

## 9. Search Tool Integration — exact code shape

File: `backend/agents/insights/tools/search_documents.py`

### 9.1 ALLOWED_SOURCES extension

```python
ALLOWED_SOURCES = ("edgar", "permits", "earnings", "all")
```

### 9.2 `_EARNINGS_SQL` (paste verbatim)

```python
_EARNINGS_SQL = text(
    """
    SELECT
      ep.passage_id::text AS passage_id,
      ep.text             AS passage_text,
      ep.speaker          AS speaker,
      ep.section          AS section,
      ts_rank_cd(ep.tsv, websearch_to_tsquery('english', :q), 32) AS score,
      et.cik              AS cik,
      et.ticker           AS ticker,
      et.company_name     AS company,
      et.quarter          AS quarter,
      et.call_date        AS call_date,
      et.transcript_url   AS url,
      et.retrieved_at     AS retrieved_at
    FROM earnings_passages ep
    JOIN earnings_transcripts et ON et.id = ep.document_id
    WHERE ep.tsv @@ websearch_to_tsquery('english', :q)
    ORDER BY score DESC
    LIMIT :k
    """
)
```

### 9.3 `_shape_earnings_row` (paste verbatim)

```python
def _shape_earnings_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": row.get("passage_text") or "",
        "score": float(row.get("score") or 0.0),
        "citation": {
            "source": "earnings",
            "company": row.get("company"),
            "filing_type": f"earnings_call_{row.get('quarter')}"
                            if row.get("quarter") else "earnings_call",
            "url": row.get("url"),
            "retrieved_at": _iso(row.get("retrieved_at")),
            "passage_id": row.get("passage_id"),
            "speaker": row.get("speaker"),
            "section": row.get("section"),
        },
    }
```

### 9.4 `source="all"` merge logic — additive edits to existing function

In `search_documents()`, add a third branch under the existing two:

```python
earnings_rows: list[dict[str, Any]] = []
try:
    async with engine.connect() as conn:
        if source in ("edgar", "all"):
            ...
        if source in ("permits", "all"):
            ...
        if source in ("earnings", "all"):
            result = await conn.execute(
                _EARNINGS_SQL, {"q": query, "k": effective_k}
            )
            earnings_rows = [dict(r) for r in result.mappings().all()]
except Exception as exc:
    ...
```

And in the shape stage:

```python
passages: list[dict[str, Any]] = []
for row in edgar_rows:    passages.append(_shape_edgar_row(row))
for row in permit_rows:   passages.append(_shape_permit_row(row))
for row in earnings_rows: passages.append(_shape_earnings_row(row))

passages.sort(key=lambda p: p["score"], reverse=True)
passages = passages[:effective_k]
```

The merge re-ranks cross-source by raw `ts_rank_cd` score. Known
limitation: cross-source BM25 scores aren't strictly comparable
(different corpora, different IDF distributions). Acceptable for v1
per PRD open-question #5; revisit if analysts report crowding.

### 9.5 Citation envelope (canonical for the frontend)

The earnings citation shape extends the existing two-key citation
contract (`source`, `company`, `filing_type`, `url`, `retrieved_at`,
`passage_id`) with two earnings-specific optional keys (`speaker`,
`section`). The frontend insight-card renderer should treat
`speaker` and `section` as optional adornments — never assume present.

---

## 10. API Contract

File: `backend/routers/earnings.py` (new). Mounted in `backend/main.py`
via `app.include_router(earnings.router)`.

### 10.1 Pydantic models

```python
from datetime import date, datetime
from typing import Any, Optional
from pydantic import BaseModel, Field

class EarningsSentimentBlock(BaseModel):
    ai_demand:          str  # bullish | cautious | bearish | not_mentioned
    power_constraints:  str
    datacenter_capex:   str
    overall:            str

class EarningsListItem(BaseModel):
    """Card payload for the EarningsTab feed (no raw_text, no passages)."""
    id:             int
    cik:            str
    ticker:         str
    company_name:   str
    quarter:        str        # '2026Q1'
    call_date:      Optional[date] = None
    sentiment:      EarningsSentimentBlock
    top_quote:      Optional[str] = None         # ≤140 chars; ellipsis if longer
    top_quote_kind: Optional[str] = None         # 'capex' | 'ai_power' | None
    transcript_url: Optional[str] = None
    retrieved_at:   datetime

class EarningsListResponse(BaseModel):
    items:      list[EarningsListItem]
    total:      int
    page:       int
    page_size:  int

class EarningsHighlight(BaseModel):
    quote:    str
    speaker:  Optional[str] = None
    section:  Optional[str] = None
    # Free-form extras carried through from the JSONB:
    extra:    dict[str, Any] = Field(default_factory=dict)

class EarningsDetail(BaseModel):
    id:                int
    cik:               str
    ticker:            str
    company_name:      str
    quarter:           str
    fiscal_year:       Optional[int] = None
    fiscal_quarter:    Optional[int] = None
    call_date:         Optional[date] = None
    transcript_url:    Optional[str] = None
    word_count:        Optional[int] = None
    speaker_count:     Optional[int] = None
    sentiment:                 EarningsSentimentBlock
    guidance:                  Optional[EarningsHighlight] = None
    capex_mentions:            list[EarningsHighlight]
    ai_power_mentions:         list[EarningsHighlight]
    competitive_mentions:      list[EarningsHighlight]
    mw_capacity_mentions:      list[EarningsHighlight]
    top_passages:              list[dict]   # top-5 BM25 hits vs themes
    extracted_at:              Optional[datetime] = None
    extractor_version:         Optional[str] = None
    retrieved_at:              datetime

class CompanyEarningsRow(BaseModel):
    """Compact timeline row for CompanyDetailPanel."""
    id:               int
    quarter:          str
    call_date:        Optional[date] = None
    sentiment_overall: str
    headline:         Optional[str] = None    # 1-line guidance summary

class CompanyEarningsResponse(BaseModel):
    company_id:  int
    ticker:      Optional[str] = None
    transcripts: list[CompanyEarningsRow]
```

### 10.2 Endpoints

All endpoints wrap responses in `LineageEnvelope` (or `CoverageEnvelope`
when freshness matters for the UI). Patterns mirror
`backend/routers/insights.py` and `backend/routers/coverage.py`.

| Method | Path | Query / Path params | Response (data field) | Envelope |
|---|---|---|---|---|
| GET | `/api/earnings` | `page=1`, `page_size=20` (≤100), `ticker?`, `quarter?`, `sentiment_axis?` ∈ {ai_demand,power_constraints,datacenter_capex,overall}, `sentiment_value?` ∈ {bullish,cautious,bearish} | `EarningsListResponse` | `CoverageEnvelope` |
| GET | `/api/earnings/{transcript_id}` | path int | `EarningsDetail` | `LineageEnvelope` |
| GET | `/api/companies/{company_id}/earnings` | path int | `CompanyEarningsResponse` | `LineageEnvelope` |

### 10.3 Filter composition

Filters compose with AND. Querystring example:

```
GET /api/earnings?ticker=NVDA&quarter=2026Q1&sentiment_axis=ai_demand&sentiment_value=bullish&page_size=20
```

### 10.4 `top_passages` for the detail endpoint

The detail endpoint runs a BM25 query against `earnings_passages` for
the given `document_id` with the canned theme bundle:

```sql
SELECT ep.passage_id::text, ep.text, ep.speaker, ep.section,
       ts_rank_cd(ep.tsv, q, 32) AS score
FROM   earnings_passages ep,
       websearch_to_tsquery('english', 'AI demand power datacenter capex') AS q
WHERE  ep.document_id = :id
  AND  ep.tsv @@ q
ORDER  BY score DESC
LIMIT  5;
```

Each row is shaped as the same citation envelope `_shape_earnings_row`
produces — frontend can reuse one rendering component for inline
citations and detail-page passages.

### 10.5 Lineage / Coverage shape (exact)

`LineageMeta` per response:

```python
LineageMeta(
    source_url="https://www.alphavantage.co/",
    retrieved_at=<max retrieved_at across rows>,
    parser_version="earnings-adapter-1.0.0",
    confidence=0.85,
)
```

`CoverageMeta` on the list endpoint:

```python
CoverageMeta(
    pillar="earnings_intelligence",
    states_included=["US"],
    states_excluded_with_reason={
        "TW": "Foreign filers (TSMC, ASE) not covered by Alpha Vantage",
    },
    freshness_status="ok" | "stale",   # stale if newest retrieved_at > 48h old
)
```

---

## 11. Frontend Data Flow

### 11.1 Types

`frontend/src/types/earnings.ts` (new):

```typescript
export interface EarningsSentimentBlock {
  ai_demand:         "bullish" | "cautious" | "bearish" | "not_mentioned";
  power_constraints: "bullish" | "cautious" | "bearish" | "not_mentioned";
  datacenter_capex:  "bullish" | "cautious" | "bearish" | "not_mentioned";
  overall:           "bullish" | "cautious" | "bearish" | "not_mentioned";
}

export interface EarningsListItem {
  id: number;
  cik: string;
  ticker: string;
  company_name: string;
  quarter: string;
  call_date: string | null;
  sentiment: EarningsSentimentBlock;
  top_quote: string | null;
  top_quote_kind: "capex" | "ai_power" | null;
  transcript_url: string | null;
  retrieved_at: string;
}

export interface EarningsHighlight {
  quote: string;
  speaker?: string | null;
  section?: "prepared_remarks" | "q_and_a" | null;
  extra?: Record<string, unknown>;
}

export interface EarningsDetail { /* mirrors backend EarningsDetail */ }
export interface CompanyEarningsRow { /* mirrors backend CompanyEarningsRow */ }
```

### 11.2 Hooks

Reuse `useApi<T>(path)` from `frontend/src/hooks/useApi.ts`. No new
hooks needed. Filter state lives in component-local state; each filter
change rebuilds the path and `useApi` refetches.

### 11.3 Components

```
EarningsTab.tsx                       (new)
  ├── EarningsFilters                 (multi-select company, quarter, sentiment)
  ├── EarningsFeed
  │     └── EarningsCard (×N)         (badges + top quote + CitationFooter)
  └── EarningsDetailModal             (opens on card click)
        ├── SentimentRow              (4 axis badges)
        ├── HighlightSection (×5)     (Guidance / Capex / AI&Power / Competitive / MW)
        └── TopPassages               (top-5 BM25 hits)

CompaniesTab.tsx                      (edit)
  CompanyDetailPanel
    └── CompanyEarningsSection        (new — compact timeline; clicks reuse EarningsDetailModal)
```

Shared imports: `ErrorPanel`, `CitationFooter`, `TabWrapper` (set
`pillar="Earnings Transcripts"`) from
`frontend/src/components/shared/`.

### 11.4 Color tokens

Match dark theme. Sentiment badge colors:

```
bullish:        #16a34a (green-600)
cautious:       #d97706 (amber-600)
bearish:        #dc2626 (red-600)
not_mentioned:  #475569 (slate-600)
```

### 11.5 Nav registration

```typescript
// frontend/src/App.tsx
earnings: { component: EarningsTab, pillar: "Earnings Transcripts" }

// frontend/src/components/layout/TabNav.tsx — AFTER_SUPPLIER append:
{ id: "earnings", label: "Earnings Calls", icon: Mic, real: true }
```

---

## 12. Cron Schedule + Dependencies

Add to `backend/pipeline/runner.py:JOB_CONFIG`:

```python
"earnings_transcripts_daily": {
    "adapter": "earnings_transcripts",
    "trigger": CronTrigger(hour=6, minute=45),   # 45 6 * * *  UTC
    "phase": 2,
    "enabled": True,
},
```

Register in `_JOB_FUNCTIONS`:

```python
"earnings_transcripts_daily": run_earnings_transcripts_job,
```

Add the job runner + invoke helper following the existing pattern:

```python
async def run_earnings_transcripts_job() -> None:
    await _run_adapter_job("earnings_transcripts", _invoke_earnings_transcripts)

async def _invoke_earnings_transcripts(session) -> dict:
    from ingestion.earnings_transcripts import EarningsTranscriptsAdapter
    adapter = EarningsTranscriptsAdapter()
    result = await adapter.run(session, days_back=90)
    await session.commit()
    return result
```

**Order of operations (06:00 → 09:00 UTC)**:

```
06:00 UTC   edgar_daily              (8-K)
06:15 UTC   quarterly_filings_daily  (10-K / 10-Q / 20-F / 6-K)
06:30 UTC   county_permits_daily
06:45 UTC   earnings_transcripts_daily   ← new; depends on TRACKED_FILERS only
07:00 UTC   permits_state_daily
08:00 UTC   permits_air_daily        (EPA ECHO)
09:00 UTC   insights_daily           ← consumes all of the above
```

Earnings runs **before** `insights_daily` so transcripts are in the
search corpus by the time synthesis fires. It does NOT depend on EDGAR
(other than reusing the submissions cache for ticker lookups), so a
failure of `edgar_daily` does not block earnings.

Misfire grace: 3600s + `coalesce=True` (same default as other daily
jobs in `create_scheduler()`).

---

## 13. Failure Modes & Retry Strategy

### 13.1 Failure-mode matrix

| Failure | Detection | Response | Lineage status |
|---|---|---|---|
| Alpha Vantage HTTP 5xx | `stamina.retry` raises | 3 attempts, exponential backoff (2s init); on final fail log + skip ticker | `partial_failure` |
| Alpha Vantage HTTP-200 throttle (`Information`/`Note` key) | `_check_throttled()` | Abort run, schedule retry tomorrow | `skipped_throttled` |
| Daily budget exhausted (≥24 calls) | `_gate_daily_budget()` returns False | Stop fetching new transcripts; commit what's done | `skipped_quota` |
| `transcript[] == []` (not yet published) | Adapter checks length | Insert placeholder row; mark `extractor_version='pending-{N}'`; retry up to 7 days | (per-row) `pending` |
| Foreign-filer rejection (TSMC, ASE) | Filtered at `EARNINGS_ELIGIBLE_TICKERS` resolution | Never fetched; logged at startup | (no row) |
| LLM call timeout | `asyncio.TimeoutError` at extractor | Log + leave parent row with `extracted_at=NULL`; next run retries | `partial_failure` |
| LLM returns invalid JSON / fails schema | Existing `llm_client.extract` catches | Same as above | `partial_failure` |
| Quote-validation drops all entries | `_validate_quotes` returns empty | Still persist parent row with sentiment_*=`not_mentioned`; mark `extractor_version='earnings-llm-v1-empty'` | `success` (degraded) |
| DB constraint violation (unique key race) | `IntegrityError` | Rollback; re-read; treat as already-extracted | `success` |
| Postgres connection lost | `OperationalError` | `_run_adapter_job` wrapper sets `failure` and re-raises | `failure` |

### 13.2 Daily-budget exhaustion — explicit behavior

The adapter's `run()` loop processes (cik, quarter) pairs in this order:

1. Tickers with a call in the past 48 hours (highest priority — fresh
   data).
2. Tickers with a call in the past 14 days but `extracted_at IS NULL`
   (catch-up).
3. Tickers with a planned call in the next 14 days (probe — likely
   empty, cheap).

If `_gate_daily_budget()` returns False mid-loop, the adapter logs a
warning, writes a single `data_lineage` row with `status='skipped_quota'`
and an explanatory `details` field, commits, and returns the partial
summary. Tomorrow's run picks up where we left off (the
already-fetched rows are already-extracted, so they're skipped via
idempotency check).

### 13.3 Transcript-not-yet-available — explicit behavior

This is the common case for "we ran on Wednesday but the call was
Tuesday post-market and Alpha Vantage hasn't published yet."

On `transcript[] == []`:

1. UPSERT a placeholder row with:
   - `raw_text = ''`
   - `extracted_at = NULL`
   - `extractor_version = 'pending-{retry_count}'`
   - All sentiment columns = `'not_mentioned'`
2. Increment `retry_count` (parsed from the existing `extractor_version`
   if present) on each subsequent miss.
3. After `MAX_RETRIES_PER_QUARTER` (7), set `extractor_version =
   'transcript_unavailable'` and stop fetching for that (cik, quarter).
4. The list endpoint hides rows where `raw_text = ''` from the feed by
   default; the detail endpoint returns a 410 Gone for unavailable rows.

### 13.4 Foreign-filer rejection

Filtered upstream: tickers not in `EARNINGS_ELIGIBLE_TICKERS` are never
sent to Alpha Vantage. The `EARNINGS_SKIPPED` map logs the reason once
at adapter startup so coverage gaps are visible to operators. There is
NO retry / probe for these — the design treats them as out of scope for
v1 (PRD non-goal).

If Alpha Vantage's coverage probe in week 1 (PRD open question #1)
finds an unexpectedly missing US-public ticker, the fix is to add a
row to `EARNINGS_SKIPPED` with a documented reason rather than to
silently absorb the empty response as "not yet published".

---

## 14. Non-Functional Requirements

| NFR | Target | Mechanism |
|---|---|---|
| API p95 latency `/api/earnings` (20 cards) | < 400 ms | BM25 GIN index; parent-only row fetch (no raw_text); pagination |
| API p95 latency `/api/earnings/{id}` | < 600 ms | Single parent SELECT + 1 BM25 top-5 query; structured columns are JSONB (read in same row) |
| Adapter wall time per run | < 10 min | Semaphore=1 + 12.5s delay × ≤24 calls = ~5 min worst case |
| Transcript freshness | New transcripts visible within 48h of call | Daily 06:45 UTC cron + 7-day retry window |
| Pipeline reliability | ≥95% scheduled runs succeed (14-day rolling) | `ingestion_runs` audit + `stale_check` job |
| LLM cost | ≤$10/year | Sonnet 4.6 single-pass; ~$0.06/transcript × 140/year |
| Extraction quality | <5% quote-validation drops | Substring invariant; logged per drop |
| Security — API key | Never logged; only in env | `config.py` reads `ALPHA_VANTAGE_API_KEY`; `.env.example` blank |
| Security — DB role | Search tool uses read-only role | Existing `get_readonly_engine()` (no change) |

---

## 15. ADRs (Key Decisions)

### ADR-001: Mirror EDGAR table topology instead of unifying into one `documents` table

**Decision.** Create `earnings_transcripts` + `earnings_passages` as
parallel siblings to `edgar_extractions` + `edgar_passages` rather than
introducing a single polymorphic `documents` table.

**Context.** A polymorphic table would simplify the search tool (one
SQL branch instead of three) but would force every column to be a
nullable union of EDGAR + earnings + permits shapes. The agent already
handles polymorphism in `search_documents` via Python-level merging.

**Consequences.**
- + Migration is small and reviewable; downgrade is clean.
- + EDGAR columns stay strongly typed; new earnings columns stay
  strongly typed.
- - Schema drift risk between the two passage tables. Mitigation: a
  note in `SCHEMA.md` and a single-line cross-reference comment in
  both migrations.

### ADR-002: Foreign key on `earnings_passages.document_id` (vs polymorphic discriminator)

**Decision.** Use a hard FK with `ON DELETE CASCADE` to
`earnings_transcripts.id`. Don't replicate the
`source_kind`/`source_doc_id` discriminator from `permit_passages`.

**Context.** Permits use a polymorphic discriminator because they span
five upstream tables. Earnings has exactly one parent.

**Consequences.**
- + Re-chunking is a clean delete-then-insert on `document_id`.
- + Search SQL is a simple JOIN.
- - If we ever add a second earnings source (e.g., Motley Fool feed),
  we'll either (a) widen the FK target or (b) add a new sibling table.
  Either is acceptable.

### ADR-003: Single-pass LLM extraction (no chunked extraction)

**Decision.** Run one Sonnet call per transcript over the full
`raw_text` rather than per-chunk + merge (like
`run_llm_extraction_quarterly` does for 10-Ks).

**Context.** Research §1 shows transcripts are 6–10K tokens typical, 20K
worst case — comfortably within a single Sonnet call. 10-Ks routinely
exceed 100K tokens, hence the chunked path there.

**Consequences.**
- + Simpler extractor; no merger needed; one quote-validation pass.
- + Sentiment is naturally consistent (one LLM forms one view).
- - If a future transcript provider returns 100K+ token transcripts,
  we'll need to add a chunked path. Acceptable risk for v1.

### ADR-004: Speaker-aware chunking, not pure char-window

**Decision.** Chunk on speaker-turn boundaries with a token target;
pack within turns; split a turn only when it exceeds the hard cap.

**Context.** Earnings transcripts are dialogues. A char-window splitter
would chop mid-quote, breaking BM25 attribution (we'd not know whether
"we expect AI capex to accelerate" came from the CEO or an analyst).

**Consequences.**
- + Citations carry meaningful speaker attribution.
- + Q&A pairs are preserved when small enough.
- - Slightly larger passages on average (a long monologue turn may emit
  one ~700-tok passage where char-window would emit two ~500-tok
  passages). Acceptable for BM25.

### ADR-005: tsvector trigger (not GENERATED column)

**Decision.** Use a BEFORE INSERT/UPDATE trigger to maintain `tsv`,
matching the EDGAR pattern in migration 017.

**Context.** `to_tsvector` is `STABLE` not `IMMUTABLE` under some PG
configurations, breaking GENERATED ALWAYS AS expressions.

**Consequences.**
- + Works on every supported PG version.
- + Identical to EDGAR shape; one mental model.
- - Trigger overhead on every insert. Negligible at our write volume
  (~140 transcripts/year × ~50 passages = 7K passage inserts/year).

### ADR-006: Daily-budget gate inside the adapter, not at the scheduler

**Decision.** The cron fires daily unconditionally. The adapter
internally tracks calls used today against `MAX_DAILY_CALLS=24` and
short-circuits.

**Context.** A scheduler-level gate would require a separate counter
table and would race with manual `adapter.run(...)` invocations.

**Consequences.**
- + Manual runs (CLI / API trigger) respect the same budget.
- + The cron stays a simple time trigger; no conditional cron logic.
- - Counter is in-process. A restart mid-day resets it. Mitigation:
  query `ingestion_runs` for today's call count on adapter start; not
  exact but bounded.

---

## 16. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Alpha Vantage tightens free-tier limits | Medium | High (entire feature stalls) | Premium tier upgrade ($49.99/mo) is documented as the escape hatch; pillar coverage badge flips to `stale` automatically via `stale_check` |
| Smaller utilities missing from AV coverage | Medium | Low (gap, not failure) | Week-1 coverage probe + add to `EARNINGS_SKIPPED` with explicit reason rather than burning retries |
| LLM hallucinated quotes get past substring validation (whitespace edge cases) | Low | Medium (downstream citations look fabricated) | Normalize whitespace on both sides before substring check; unit test on a known-good IBM transcript |
| Sentiment label drift between LLM versions | Medium | Low | `extractor_version` column lets us bucket / re-extract; sentiment values are open `String(16)` not enum |
| `source="all"` ranking dominated by one source's IDF | Medium | Low | Acceptable for v1 per PRD open question #5; revisit with reciprocal rank fusion if observed |
| Schema drift between `edgar_passages` and `earnings_passages` | Low | Medium | Cross-reference comment in both migrations; `SCHEMA.md` note |
| Synthesis-prompt regression (new source crowds out filings) | Medium | Medium | Synthesis-rules wording keeps earnings as "acceptable source alongside EDGAR", not preferred; existing portfolio-quality preflight guards mix |
| ALPHA_VANTAGE_API_KEY accidentally committed | Low | High | `.env.example` blank; pre-commit hook on secrets is out of scope but recommended |
| Calendar CSV format change | Low | Medium | `csv.DictReader` reads named columns; defensive empty-string cast on `estimate`; unrecognized columns ignored |
| Transcript HTML escape weirdness in BM25 query | Low | Low | `to_tsvector('english', ...)` handles HTML-stripped text fine; if AV returns markup, strip in the chunker |

---

## 17. Out of Scope (v1 explicit)

Reaffirms PRD Non-Goals and Plan Part 7:

- Real-time / streaming transcript ingestion
- Foreign filers (TSMC, ASE) — different provider required
- Audio analysis (tone of voice)
- Backfilling more than the last 90 days on first run
- Modifying any existing edgar / permits / insights pipelines
- Cross-source ranking calibration (RRF for `source="all"`)
- Per-passage embeddings (Phase B.2 territory; gated on recall@8 < 0.85)

---

## 18. Verification Outline

Defer to Plan Part 6 for the executable steps. Add one architecture-
specific check after migration applies:

```bash
psql $DATABASE_URL -c "
SELECT conname, pg_get_constraintdef(oid)
FROM   pg_constraint
WHERE  conrelid = 'earnings_transcripts'::regclass
ORDER  BY conname;
"
# Confirm: uq_earnings_transcripts_cik_quarter UNIQUE (cik, quarter)
```

And one for the trigger:

```bash
psql $DATABASE_URL -c "
SELECT tgname FROM pg_trigger
WHERE  tgrelid = 'earnings_passages'::regclass
  AND  NOT tgisinternal;
"
# Confirm: earnings_passages_tsv_trg
```
