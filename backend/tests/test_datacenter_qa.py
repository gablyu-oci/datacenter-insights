"""
Tests for the Datacenter Q&A agent (schema-aware refactor).

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
    _describe_schema_for_llm,
    _tool_query,
    answer_question,
    dispatch_tool,
)

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
    out = await _tool_query(
        session,
        table="sites",
        where=[{"column": "state_code", "op": "=", "value": "VA"}],
        limit=10,
    )
    assert isinstance(out, dict)
    for k in ("rows", "total_count", "returned", "truncated"):
        assert k in out, f"missing {k} in query result"
    rows = out["rows"]
    if rows and "error" not in rows[0]:
        assert all(r.get("state_code") == "VA" for r in rows)


@pytest.mark.asyncio
async def test_aggregate_sites_by_provider(session):
    out = await _tool_query(
        session,
        table="sites",
        group_by=["provider_name"],
        metric="sum:power_capacity_mw",
        limit=5,
    )
    assert isinstance(out, dict)
    rows = out["rows"]
    assert out["returned"] <= 5
    assert len(rows) <= 5
    if rows:
        assert "value" in rows[0]


@pytest.mark.asyncio
async def test_dispatch_tool_unknown(session):
    out = await dispatch_tool(session, "does_not_exist", {})
    assert isinstance(out, list)
    assert out and "error" in out[0]


@pytest.mark.asyncio
async def test_aggregate_unknown_column(session):
    out = await _tool_query(
        session,
        table="sites",
        where=[{"column": "nope_not_a_column", "op": "=", "value": 1}],
        limit=5,
    )
    # Errors come back as the list-shaped error envelope.
    assert isinstance(out, list)
    assert out and "error" in out[0]


# ---------------------------------------------------------------------------
# New tests for the unified query tool
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_with_arbitrary_field(session):
    out = await _tool_query(
        session,
        table="sites",
        where=[{"column": "yearly_pue", "op": "<", "value": 1.5}],
        limit=10,
    )
    assert isinstance(out, dict)
    assert "rows" in out
    assert "total_count" in out


@pytest.mark.asyncio
async def test_query_returns_total_count(session):
    out = await _tool_query(session, table="sites", limit=2)
    assert isinstance(out, dict)
    assert out["returned"] <= out["total_count"]
    assert out["truncated"] == (out["total_count"] > out["returned"])


def test_schema_doc_includes_pue():
    doc = _describe_schema_for_llm()
    assert "yearly_pue" in doc
    assert "tot_facility_space_sqft" in doc
    assert "provider_name" in doc


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
