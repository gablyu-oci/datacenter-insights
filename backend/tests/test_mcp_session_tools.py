"""In-process tests of the 3 Phase 2 session-scoped MCP write tools.

PRD/ARCH: docs/plans/ai-insights-automation/14-unified-agent-architecture.md §3.

Strategy
--------
The MCP transport itself is unit-tested in `test_mcp_server.py` (HTTP +
JSON-RPC envelope). Here we drive the handlers directly through the
shared `_invoke_session(name, session_id, args)` helper exported from
`mcp_server`, mirroring the envelope shape OpenClaw consumes:

    {"ok": True, "result": {...}, "code": 0}             on success
    {"ok": False, "error": "...", "code": "BAD_INPUT"}   on validation
    {"ok": False, "error": "...", "code": "TOOL_FAILED"} on unhandled

We keep persistence on aiosqlite + JSONB->TEXT compat (mirroring
`test_openclaw_forwarder.py`).
"""
from __future__ import annotations

import os
import sys
import types
import uuid
from datetime import datetime
from typing import Any

import pytest
import pytest_asyncio

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))
for p in (BACKEND_ROOT, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------------------------------------------------------------------------
# Pre-import shims (mirrors test_openclaw_forwarder + test_mcp_server)
# ---------------------------------------------------------------------------
import agents  # noqa: E402,F401
import agents.insights  # noqa: E402,F401

# Only install the sql_gate stub if the real module cannot be imported.
# Unconditionally installing it poisons tests/test_insights_sql_gate.py
# when our test runs first alphabetically.
try:  # pragma: no cover
    import agents.insights.tools.sql_gate as _real_sql_gate  # noqa: F401
except Exception:  # noqa: BLE001
    if "agents.insights.tools" not in sys.modules:
        _tools_pkg = types.ModuleType("agents.insights.tools")
        _tools_pkg.__path__ = [os.path.join(BACKEND_ROOT, "agents", "insights", "tools")]
        sys.modules["agents.insights.tools"] = _tools_pkg

    if "agents.insights.tools.sql_gate" not in sys.modules:
        from pydantic import BaseModel as _BM

        _sg = types.ModuleType("agents.insights.tools.sql_gate")

        class SqlGateError(Exception):
            def __init__(self, code: str = "sql_gate_blocked", *args, **kwargs) -> None:
                super().__init__(*args)
                self.code = code

        class ValidatedSQL(_BM):
            sql: str
            notes: list[str] = []

        def validate_sql(sql: str, **_kw):
            return ValidatedSQL(sql=sql)

        _sg.SqlGateError = SqlGateError
        _sg.ValidatedSQL = ValidatedSQL
        _sg.validate_sql = validate_sql
        _sg.DEFAULT_ROW_LIMIT = 10_000
        sys.modules["agents.insights.tools.sql_gate"] = _sg

# JSONB / UUID -> SQLite-friendly compat patches.
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler  # noqa: E402


def _visit_JSONB(self, type_, **kw):  # noqa: N802
    return "TEXT"


def _visit_UUID(self, type_, **kw):  # noqa: N802
    return "CHAR(36)"


SQLiteTypeCompiler.visit_JSONB = _visit_JSONB  # type: ignore[attr-defined]
SQLiteTypeCompiler.visit_UUID = _visit_UUID  # type: ignore[attr-defined]


from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

import agents.insights.db.models as ai_models  # noqa: E402,F401  (registers tables)
from agents.insights.db.models import (  # noqa: E402
    AIInsight,
    AISession,
    InsightThread,
    AgentMessage,
    AgentChart,
)
from agents.insights.session_tools import HANDLERS  # noqa: E402,F401

import db.session as db_session_mod  # noqa: E402
import mcp_server as mcp_server_mod  # noqa: E402


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def sqlite_engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    needed_tables = [
        AISession.__table__,
        AIInsight.__table__,
        InsightThread.__table__,
        AgentMessage.__table__,
        AgentChart.__table__,
    ]
    async with eng.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: SQLModel.metadata.create_all(
                sync_conn, tables=needed_tables
            )
        )
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(sqlite_engine):
    return sessionmaker(sqlite_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def patched_factory(monkeypatch: pytest.MonkeyPatch, session_factory):
    """Wire `_invoke_session`'s lazy `from db.session import async_session_factory`
    onto our SQLite session factory. mcp_server does
    `from db.session import async_session_factory` inside the function body,
    so we patch the module attribute that `from` would resolve.
    """
    monkeypatch.setattr(db_session_mod, "async_session_factory", session_factory)
    yield session_factory


@pytest_asyncio.fixture
async def running_session(session_factory):
    """Seed an `ai_session` row in `status='running'` ready for write-tools."""
    sess = AISession(
        id=uuid.uuid4(),
        status="running",
        model="oci/openai.gpt-5.4",
        focus="OC",
        max_insights=7,
        version="v2",
        insights_emitted=0,
    )
    async with session_factory() as s:
        s.add(sess)
        await s.commit()
    return sess


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# v2 persist_insight shape: flat kwargs (no `insight` wrapper, no
# `supporting_row_ids`, no `confidence_signal` — confidence is the
# direct field). Citations stays optional in this dict; tests pass it
# explicitly.
_VALID_INSIGHT_BODY: dict[str, Any] = {
    "headline": "Test insight",
    "body": "Body for the test insight.",
    "confidence": "high",
    "materiality": "high",
    "citations": [],
}


# ---------------------------------------------------------------------------
# 1. persist_insight happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_insight_happy_path(
    patched_factory, running_session, session_factory
) -> None:
    sess_id = running_session.id

    envelope = await mcp_server_mod._invoke_session(
        "persist_insight",
        str(sess_id),
        dict(_VALID_INSIGHT_BODY),
    )
    assert envelope["ok"] is True, envelope
    assert envelope["code"] == 0, envelope
    result = envelope["result"]
    new_id = uuid.UUID(result["insight_id"])  # round-trips as a UUID

    async with session_factory() as s:
        rows = (
            (
                await s.execute(
                    select(AIInsight).where(AIInsight.session_id == sess_id)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    row = rows[0]
    assert row.id == new_id
    assert row.headline == _VALID_INSIGHT_BODY["headline"]
    assert row.body == _VALID_INSIGHT_BODY["body"]
    assert row.confidence == "high"
    assert row.materiality == "high"


# ---------------------------------------------------------------------------
# 2. persist_insight invalid session_id -> envelope error 400/BAD_INPUT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_insight_invalid_session_id_envelope(
    patched_factory,
) -> None:
    envelope = await mcp_server_mod._invoke_session(
        "persist_insight",
        "not-a-uuid",
        dict(_VALID_INSIGHT_BODY),
    )
    assert envelope["ok"] is False
    assert envelope["code"] == "BAD_INPUT"
    assert "bad_session_id" in envelope["error"]


# ---------------------------------------------------------------------------
# 3. persist_insight rejects empty/missing headline with headline_required.
#    (The v1 shape — `{"insight": {...}}` plus `supporting_row_ids` against
#     a registered FactPack — was deleted with v1.)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_insight_missing_headline_returns_validation_error(
    patched_factory, running_session
) -> None:
    sess_id = running_session.id
    bad_args = {
        "body": "Body without a headline",
        "confidence": "high",
        "materiality": "high",
        "citations": [],
    }
    envelope = await mcp_server_mod._invoke_session(
        "persist_insight",
        str(sess_id),
        bad_args,
    )
    # _invoke_session wraps a validation error from the tool handler
    # as ok=True at the envelope layer with the inner result.ok=False.
    inner = envelope.get("result") if envelope.get("ok") else envelope
    assert inner.get("ok") is False, envelope
    assert inner.get("error") == "headline_required"


# ---------------------------------------------------------------------------
# 5. finalize_session happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_session_happy_path(
    patched_factory, running_session, session_factory
) -> None:
    sess_id = running_session.id
    envelope = await mcp_server_mod._invoke_session(
        "finalize_session",
        str(sess_id),
        {"status": "complete", "token_estimate": 12345},
    )
    assert envelope["ok"] is True, envelope
    assert envelope["result"]["status"] == "complete"

    async with session_factory() as s:
        row = (
            (
                await s.execute(select(AISession).where(AISession.id == sess_id))
            )
            .scalar_one_or_none()
        )
    assert row is not None
    assert row.status == "complete"
    assert row.finished_at is not None
    assert row.token_estimate == 12345


# ---------------------------------------------------------------------------
# 6. finalize_session rejects status not in {complete, degraded, failed}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_session_rejects_unknown_status(
    patched_factory, running_session
) -> None:
    sess_id = running_session.id
    envelope = await mcp_server_mod._invoke_session(
        "finalize_session",
        str(sess_id),
        {"status": "succeeded", "token_estimate": 0},
    )
    assert envelope["ok"] is False
    assert envelope["code"] == "BAD_INPUT"


# ---------------------------------------------------------------------------
# 7. persist_brief returns brief_run_not_found envelope (no BriefRun row)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_brief_returns_brief_run_not_found(
    patched_factory, running_session
) -> None:
    sess_id = running_session.id
    envelope = await mcp_server_mod._invoke_session(
        "persist_brief",
        str(sess_id),
        {
            "sections": {"movers": "..."},
            "citations": [{"url": "https://example.com"}],
        },
    )
    assert envelope["ok"] is False, envelope
    # Either the structured BRIEF_RUN_NOT_FOUND code (when BriefRun model
    # imports cleanly + no row matches), or BAD_INPUT (when the model
    # import path itself raises ToolValidationError because the test DB
    # has no brief_runs table). Both signal "no brief found".
    assert envelope["code"] in ("BRIEF_RUN_NOT_FOUND", "BAD_INPUT"), envelope
    assert "brief_run_not_found" in envelope["error"].lower()


# ---------------------------------------------------------------------------
# Bonus: HANDLERS registry exposes exactly the 3 Phase 2 names.
# ---------------------------------------------------------------------------


def test_handlers_registry_has_three_phase2_tools() -> None:
    assert set(HANDLERS.keys()) == {
        "persist_insight",
        "finalize_session",
        "persist_brief",
    }
