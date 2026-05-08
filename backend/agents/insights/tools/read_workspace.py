"""``read_workspace`` MCP tool.

Phase A deliverable per `docs/ai_insights_v2_phase_a_architecture.md` §1.5
and `docs/ai_insights_v2_spec.md` §5.1.

The synthesis agent calls this at session start to orient against the
workspace artefacts (``SCHEMA.md``, ``FRESHNESS.md``). Both files are
written by Phase A refresh jobs.

Hardening:
  * Literal allowlist enforced BEFORE any ``Path`` join — path traversal
    is structurally impossible.
  * 16 KB byte cap with a ``truncated`` flag.
  * Tool never raises; all failure modes return ``{ok: False, error: ...}``.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ..specs.skill_context import SkillContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WORKSPACE_DIR_ENV = "OPENCLAW_WORKSPACE_DIR"

ALLOWED_FILES: frozenset[str] = frozenset({"SCHEMA.md", "FRESHNESS.md"})
MAX_BYTES: int = 16 * 1024


def _project_root() -> Path:
    """The repo root, three parents up from this file (``backend/agents/
    insights/tools/read_workspace.py`` -> repo root).
    """
    return Path(__file__).resolve().parents[4]


def _workspace_dir() -> Path:
    env_val = os.environ.get(WORKSPACE_DIR_ENV)
    if env_val:
        return Path(env_val).resolve()
    return (_project_root() / ".openclaw" / "workspace").resolve()


# ---------------------------------------------------------------------------
# Tool entrypoint
# ---------------------------------------------------------------------------


async def read_workspace(
    file: str,
    ctx: SkillContext | None = None,
) -> dict[str, Any]:
    """Read a workspace artefact, returning ``{ok, content, truncated}``.

    On any failure path returns ``{ok: False, error: <code>, detail?: dict}``.
    Never raises.
    """
    if file not in ALLOWED_FILES:
        logger.info(
            "ai_insights.read_workspace.rejected",
            extra={"file": file, "reason": "not_in_allowlist"},
        )
        return {
            "ok": False,
            "error": "file_not_allowed",
            "detail": {"file": file, "allowed": sorted(ALLOWED_FILES)},
        }

    workspace = _workspace_dir()
    target = workspace / file

    if not target.is_file():
        logger.info(
            "ai_insights.read_workspace.not_found",
            extra={"file": file, "path": str(target)},
        )
        return {
            "ok": False,
            "error": "file_not_found",
            "detail": {"file": file, "path": str(target)},
        }

    # Defence in depth: even though ``file`` came from a literal allowlist,
    # confirm the resolved path stays inside the workspace dir. Symlinks
    # outside the workspace would fail this check.
    try:
        resolved = target.resolve()
        if not resolved.is_relative_to(workspace):
            return {
                "ok": False,
                "error": "file_not_allowed",
                "detail": {"file": file, "reason": "resolved_outside_workspace"},
            }
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "ok": False,
            "error": "read_failed",
            "detail": {"reason": f"resolve_failed: {exc}"},
        }

    try:
        # Read MAX_BYTES + 1 so we can detect truncation without slurping
        # an arbitrarily large file.
        with open(resolved, "rb") as fh:
            raw = fh.read(MAX_BYTES + 1)
    except Exception as exc:
        logger.warning(
            "ai_insights.read_workspace.read_failed",
            extra={"file": file, "error": str(exc)},
        )
        return {
            "ok": False,
            "error": "read_failed",
            "detail": {"reason": str(exc)},
        }

    truncated = len(raw) > MAX_BYTES
    body_bytes = raw[:MAX_BYTES] if truncated else raw
    content = body_bytes.decode("utf-8", errors="replace")

    logger.info(
        "ai_insights.read_workspace.ok",
        extra={
            "file": file,
            "bytes": len(body_bytes),
            "truncated": truncated,
        },
    )

    return {
        "ok": True,
        "content": content,
        "truncated": truncated,
    }


__all__ = ["read_workspace", "ALLOWED_FILES", "MAX_BYTES"]
