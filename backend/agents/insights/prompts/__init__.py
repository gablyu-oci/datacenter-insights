"""Prompt loader for the agentic insights pipeline (Phase 2).

Each per-mode rules file lives as a sibling ``<name>.md`` inside this
package. ``load_prompt(name)`` returns the file's UTF-8 body, lru-cached
for the process lifetime so re-reads on every request are free. To pick
up changes during development, restart the process.

Cross-cutting work (post Phase 2) replaces ``synthesis_rules.md``'s
starter content with the slimmed mode-only rules described in
``docs/plans/ai-insights-automation/14-unified-agent-architecture.md`` §10.1.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_HERE = Path(__file__).resolve().parent


@lru_cache(maxsize=8)
def load_prompt(name: str) -> str:
    """Return the markdown body of ``prompts/<name>.md``.

    Args:
      name: bare basename of the prompt file (no extension). Examples:
        ``"synthesis_rules"``, ``"chat_rules"``, ``"brief_rules"``.

    Raises:
      FileNotFoundError: when the file does not exist on disk.
    """
    path = _HERE / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt not found: {name} ({path})")
    return path.read_text(encoding="utf-8")


__all__ = ["load_prompt"]
