"""Light unit tests asserting ``read_workspace`` is wired into the tool
registry (TOOL_DEFS + _DISPATCH + dispatch() routing).

Phase A AI Insights v2 (arch §1.6).
"""
from __future__ import annotations

import os
import sys

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


def _read_workspace_def() -> dict:
    for d in TOOL_DEFS:
        if d.get("function", {}).get("name") == "read_workspace":
            return d
    raise AssertionError("read_workspace not present in TOOL_DEFS")


def test_tool_defs_contains_read_workspace_with_correct_enum():
    spec = _read_workspace_def()
    func = spec["function"]
    params = func["parameters"]

    assert params["required"] == ["file"]
    file_param = params["properties"]["file"]
    assert file_param["type"] == "string"
    assert sorted(file_param["enum"]) == ["FRESHNESS.md", "SCHEMA.md"]
    # additionalProperties must be False so the model can't slip extras through.
    assert params["additionalProperties"] is False


def test_dispatch_map_contains_read_workspace():
    assert "read_workspace" in _DISPATCH
    # Sanity: it is callable and async.
    fn = _DISPATCH["read_workspace"]
    assert callable(fn)


@pytest.mark.asyncio
async def test_dispatch_routes_read_workspace_to_tool(tmp_path, monkeypatch):
    """``dispatch('read_workspace', ...)`` should reach the tool function and
    return its shape (``ok`` key present)."""
    monkeypatch.setenv("OPENCLAW_WORKSPACE_DIR", str(tmp_path))
    (tmp_path / "SCHEMA.md").write_text("hello\n", encoding="utf-8")

    out = await dispatch("read_workspace", {"file": "SCHEMA.md"}, ctx=None)

    assert isinstance(out, dict)
    assert "ok" in out
    assert out["ok"] is True
    assert out["content"] == "hello\n"
    assert out["truncated"] is False


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_does_not_collide_with_read_workspace():
    """Sanity: misspelled name still routes to the unknown_tool fallback,
    not into ``read_workspace`` (defence against future copy/paste edits).
    """
    out = await dispatch("read__workspace", {"file": "SCHEMA.md"}, ctx=None)
    assert out == {
        "ok": False,
        "error": "unknown_tool",
        "detail": {"requested": "read__workspace"},
    }
