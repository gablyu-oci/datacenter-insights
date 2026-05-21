"""Unit tests for ``agents.insights.tools.read_workspace``.

Phase A AI Insights v2 (arch §1.5). Pure-IO tool — no DB, no LLM.

Cases:
  * Allowed file present, < 16KB -> ok=True, truncated=False, full content.
  * Allowed file > 16KB -> ok=True, truncated=True, content length matches
    the byte cap (after UTF-8 decode of ``MAX_BYTES`` bytes).
  * Disallowed names ('../etc/passwd', 'random.txt') -> file_not_allowed.
  * Allowed file missing -> file_not_found.
"""
from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from agents.insights.tools.read_workspace import (  # noqa: E402
    MAX_BYTES,
    read_workspace,
)


@pytest.mark.asyncio
async def test_read_workspace_returns_content_for_allowed_small_file(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENCLAW_WORKSPACE_DIR", str(tmp_path))
    payload = "# Schema Digest\n\nhello world\n"
    (tmp_path / "SCHEMA.md").write_text(payload, encoding="utf-8")

    result = await read_workspace("SCHEMA.md")

    assert result["ok"] is True
    assert result["truncated"] is False
    assert result["content"] == payload


@pytest.mark.asyncio
async def test_read_workspace_truncates_files_over_16kb(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCLAW_WORKSPACE_DIR", str(tmp_path))
    # ASCII so byte length == char length; comfortably above MAX_BYTES.
    payload = "x" * (MAX_BYTES + 4096)
    (tmp_path / "FRESHNESS.md").write_text(payload, encoding="utf-8")

    result = await read_workspace("FRESHNESS.md")

    assert result["ok"] is True
    assert result["truncated"] is True
    # ASCII => decoded char count matches the byte cap exactly.
    assert len(result["content"]) == MAX_BYTES
    assert result["content"] == "x" * MAX_BYTES


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    ["../etc/passwd", "random.txt", "schema.md", "FRESHNESS", "MEMORY.md", ""],
)
async def test_read_workspace_rejects_disallowed_files(tmp_path, monkeypatch, name):
    monkeypatch.setenv("OPENCLAW_WORKSPACE_DIR", str(tmp_path))

    result = await read_workspace(name)

    assert result == {
        "ok": False,
        "error": "file_not_allowed",
        "detail": {
            "file": name,
            "allowed": [
                "AI_INSIGHTS_PLAYBOOK.md",
                "AI_INSIGHTS_PREFLIGHT_CHECKLIST.md",
                "AI_INSIGHTS_SQL_SCHEMA_DISCIPLINE.md",
                "FRESHNESS.md",
                "SCHEMA.md",
            ],
        },
    }


@pytest.mark.asyncio
async def test_read_workspace_returns_not_found_for_missing_file(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OPENCLAW_WORKSPACE_DIR", str(tmp_path))
    # Workspace dir exists but the file does not.
    result = await read_workspace("SCHEMA.md")

    assert result["ok"] is False
    assert result["error"] == "file_not_found"
    assert result["detail"]["file"] == "SCHEMA.md"
    assert "path" in result["detail"]
