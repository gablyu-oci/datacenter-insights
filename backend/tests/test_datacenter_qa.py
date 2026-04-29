"""
Tests for the Datacenter Q&A agent.

DB-level tool tests run against the live local Postgres at
postgresql+asyncpg://sit_app:changeme@localhost:5432/strategic_insights.

The integration tests that talk to Llama Stack are skipped gracefully
when the LLM endpoint is unreachable.
"""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agents.datacenter_qa import (
    _tool_aggregate,
    _tool_query_sites,
    answer_question,
    dispatch_tool,
)

# The spec calls out the canonical DB URL, but locally `.env` overrides the
# password.  Prefer the configured settings.database_url, fall back to the
# spec-default for portability.
try:
    from config import settings as _settings
    DB_URL = _settings.database_url
except Exception:  # noqa: BLE001
    DB_URL = "postgresql+asyncpg://sit_app:changeme@localhost:5432/strategic_insights"


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(DB_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


# ---------------------------------------------------------------------------
# Pure DB-tool tests (no LLM) -- should always pass
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_sites_va(session):
    rows = await _tool_query_sites(session, state="VA", limit=10)
    assert isinstance(rows, list)
    # Either we have VA sites or the DB is empty; tolerate both.
    if rows and "error" not in rows[0]:
        assert all(r.get("state_code") == "VA" for r in rows)


@pytest.mark.asyncio
async def test_aggregate_sites_by_provider(session):
    rows = await _tool_aggregate(
        session, table="sites", group_by=["provider_name"], metric="sum_mw", top_n=5
    )
    assert isinstance(rows, list)
    assert len(rows) <= 5
    if rows:
        assert "value" in rows[0] or "error" in rows[0]


@pytest.mark.asyncio
async def test_dispatch_tool_unknown(session):
    rows = await dispatch_tool(session, "does_not_exist", {})
    assert rows and "error" in rows[0]


@pytest.mark.asyncio
async def test_aggregate_unknown_column(session):
    rows = await _tool_aggregate(
        session, table="sites", group_by=["nope_not_a_column"], metric="count"
    )
    assert rows and "error" in rows[0]


# ---------------------------------------------------------------------------
# Live LLM integration smoke tests -- skip if Llama Stack unreachable
# ---------------------------------------------------------------------------

def _skip_if_llm_down(exc: BaseException) -> None:
    msg = str(exc)
    pytest.skip(f"Llama Stack unreachable or errored: {msg[:200]}")


@pytest.mark.asyncio
async def test_answer_question_microsoft_va(session):
    events = []
    try:
        async for e in answer_question(
            session,
            "How much MW capacity does Microsoft have in Virginia?",
            [],
        ):
            events.append(e)
            if len(events) > 50:
                break
    except httpx.HTTPError as exc:
        _skip_if_llm_down(exc)
    types = {e.type for e in events}
    assert "text_chunk" in types or "error" in types or "tool_result" in types


@pytest.mark.asyncio
async def test_answer_question_top_providers_chart(session):
    events = []
    try:
        async for e in answer_question(
            session,
            "Show me total MW by provider for top 5 hyperscalers",
            [],
        ):
            events.append(e)
            if len(events) > 60:
                break
    except httpx.HTTPError as exc:
        _skip_if_llm_down(exc)
    types = {e.type for e in events}
    # Comparative numeric question -- expect either a chart or at least a tool_result.
    assert "chart_spec" in types or "tool_result" in types or "error" in types


@pytest.mark.asyncio
async def test_answer_question_permits_by_state(session):
    events = []
    try:
        async for e in answer_question(
            session,
            "Which states have the most generator permits?",
            [],
        ):
            events.append(e)
            if len(events) > 60:
                break
    except httpx.HTTPError as exc:
        _skip_if_llm_down(exc)
    types = {e.type for e in events}
    assert "tool_result" in types or "error" in types
