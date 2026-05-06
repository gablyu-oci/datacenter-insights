"""Static / import-level guards for the agent-unification cleanup.

Coverage map (PRD/ARCH 15 §3-§4):
  t1  routers.insights no longer exposes `_legacy_chat_handler` or
      `_chat_system_prompt`.
  t2  config.settings no longer carries `openclaw_enabled`.
  t3  no live `openclaw_enabled` / `OPENCLAW_ENABLED` reference outside
      the documented historical doc-comments.
  t4  no file under backend/ imports the deleted `tool_loop` module.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = Path(os.path.abspath(os.path.join(HERE, "..")))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# ---------------------------------------------------------------------------
# t1 — routers.insights is shorn of the legacy chat handler symbols
# ---------------------------------------------------------------------------


def test_t1_no_legacy_chat_handler_symbol() -> None:
    import routers.insights as m

    assert not hasattr(m, "_legacy_chat_handler"), (
        "routers.insights still defines `_legacy_chat_handler`; "
        "the legacy chat dispatcher should have been removed in ARCH 15."
    )
    assert not hasattr(m, "_chat_system_prompt"), (
        "routers.insights still defines `_chat_system_prompt`; "
        "the legacy system-prompt builder should have been removed."
    )


# ---------------------------------------------------------------------------
# t2 — Settings drops the openclaw_enabled flag
# ---------------------------------------------------------------------------


def test_t2_no_openclaw_enabled_in_config() -> None:
    from config import settings

    assert not hasattr(settings, "openclaw_enabled"), (
        "config.settings still exposes `openclaw_enabled`; the rollback "
        "flag should have been removed in ARCH 15."
    )


# ---------------------------------------------------------------------------
# t3 — no live `openclaw_enabled` / `OPENCLAW_ENABLED` references
# ---------------------------------------------------------------------------


# Allow-listed historical doc-comment lines. The cleanup intentionally
# preserved a small number of comments that explain the removal so
# future readers know why the flag is absent.
_DOC_COMMENT_ALLOWLIST = (
    # backend/config.py
    "legacy in-process ToolLoopDriver lane and its `openclaw_enabled`",
    # backend/.env.example
    "there is no `OPENCLAW_ENABLED` flag.",
)


def _is_doc_comment_line(line: str) -> bool:
    """True if the line is a comment / docstring whitelisted by name."""
    stripped = line.lstrip()
    is_comment = stripped.startswith("#") or stripped.startswith('"')
    if not is_comment:
        # Inside a docstring body lines may be plain prose; allow if the
        # whitelist phrase appears.
        pass
    return any(allowed in line for allowed in _DOC_COMMENT_ALLOWLIST)


def test_t3_no_openclaw_enabled_grep() -> None:
    files_to_scan = [
        BACKEND_ROOT / "routers" / "insights.py",
        BACKEND_ROOT / "openclaw" / "forwarder.py",
        BACKEND_ROOT / "config.py",
        BACKEND_ROOT / ".env.example",
    ]
    pattern = re.compile(r"openclaw_enabled|OPENCLAW_ENABLED")

    offenders: list[tuple[str, int, str]] = []
    for path in files_to_scan:
        assert path.exists(), f"expected file missing: {path}"
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if not pattern.search(line):
                continue
            # Allow if it matches one of our whitelisted doc-comment lines.
            if _is_doc_comment_line(line):
                continue
            offenders.append((str(path), lineno, line))

    assert not offenders, (
        "Found live (non-doc-comment) references to openclaw_enabled / "
        f"OPENCLAW_ENABLED:\n"
        + "\n".join(f"  {p}:{n}: {l}" for p, n, l in offenders)
    )


# ---------------------------------------------------------------------------
# t4 — no `tool_loop` import lingers anywhere under backend/
# ---------------------------------------------------------------------------


def test_t4_no_tool_loop_imports() -> None:
    forbidden_patterns = [
        re.compile(r"from\s+openclaw\.tool_loop"),
        re.compile(r"from\s+\.tool_loop"),
        re.compile(r"import\s+tool_loop\b"),
        re.compile(r"from\s+tool_loop\b"),
    ]

    offenders: list[tuple[str, int, str]] = []
    # Walk all .py files under backend/, but skip __pycache__ and tests
    # for self-tests (the test file itself contains the literal patterns).
    for py_path in BACKEND_ROOT.rglob("*.py"):
        rel = py_path.relative_to(BACKEND_ROOT)
        # Skip the test file that contains these patterns as data.
        if rel.parts and rel.parts[0] == "tests" and py_path.name == "test_routers_insights_no_legacy_imports.py":
            continue
        # Skip caches.
        if "__pycache__" in rel.parts:
            continue
        try:
            text = py_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pat in forbidden_patterns:
                if pat.search(line):
                    offenders.append((str(py_path), lineno, line))

    assert not offenders, (
        "Found surviving `tool_loop` imports under backend/:\n"
        + "\n".join(f"  {p}:{n}: {l}" for p, n, l in offenders)
    )
