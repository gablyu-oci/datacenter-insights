"""Registry tests for ``search_documents`` (AI Insights v2 Phase B.1).

Mirrors the structure of ``test_registry_read_workspace.py`` to confirm
the new tool is exposed on TOOL_DEFS, present in _DISPATCH, and routes
correctly through the dispatch() shim.
"""
from __future__ import annotations

import os
import sys
from unittest import mock

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from agents.insights.tools.registry import (  # noqa: E402
    TOOL_DEFS,
    _DISPATCH,
    dispatch,
)


def _search_documents_def() -> dict:
    for d in TOOL_DEFS:
        if d.get("function", {}).get("name") == "search_documents":
            return d
    raise AssertionError("search_documents not present in TOOL_DEFS")


def test_tool_defs_contains_search_documents():
    spec = _search_documents_def()
    func = spec["function"]
    params = func["parameters"]

    # Required params per spec §5.3.
    assert "query" in params["required"]
    # Source enum mirrors ALLOWED_SOURCES.
    src = params["properties"]["source"]
    assert sorted(src["enum"]) == ["all", "earnings", "edgar", "permits"]
    # k is bounded.
    k = params["properties"]["k"]
    assert k["minimum"] == 1
    assert k["maximum"] == 50
    assert params["additionalProperties"] is False


def test_dispatch_map_contains_search_documents():
    assert "search_documents" in _DISPATCH
    fn = _DISPATCH["search_documents"]
    assert callable(fn)


@pytest.mark.asyncio
async def test_dispatch_routes_search_documents():
    """``dispatch('search_documents', ...)`` should route to the tool fn.

    We mock the underlying engine call so the dispatch path is exercised
    without touching the DB.
    """
    with mock.patch(
        "agents.insights.tools.search_documents.get_readonly_engine"
    ) as mock_engine:
        # Build a mock async engine whose connect() returns a context
        # manager yielding a mock connection that returns empty results.
        from contextlib import asynccontextmanager

        class _StubResult:
            def mappings(self):
                return self

            def all(self):
                return []

        class _StubConn:
            async def execute(self, *args, **kwargs):
                return _StubResult()

        @asynccontextmanager
        async def _connect():
            yield _StubConn()

        engine = mock.MagicMock()
        engine.connect = _connect
        mock_engine.return_value = engine

        out = await dispatch(
            "search_documents",
            {"query": "Crusoe Wyoming offtaker", "source": "edgar", "k": 5},
            ctx=None,
        )

    assert isinstance(out, dict)
    assert out["ok"] is True
    assert out["passages"] == []
    assert out["row_count"] == 0
