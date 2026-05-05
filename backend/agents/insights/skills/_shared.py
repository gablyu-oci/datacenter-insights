"""Shared helpers used across skill ports."""
from __future__ import annotations

import logging
import statistics
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_fragment(skill_dir: Path) -> str:
    """Read system_fragment.md next to the skill module."""
    p = skill_dir / "system_fragment.md"
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def numeric_columns(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    cols = []
    sample = rows[0]
    for k, v in sample.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            cols.append(k)
    return cols


def basic_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0}
    n = len(values)
    mean = sum(values) / n
    sorted_v = sorted(values)
    median = sorted_v[n // 2] if n % 2 == 1 else 0.5 * (sorted_v[n // 2 - 1] + sorted_v[n // 2])
    stdev = statistics.pstdev(values) if n > 1 else 0.0
    p90_idx = max(0, int(round(0.9 * (n - 1))))
    return {
        "n": n,
        "mean": mean,
        "median": median,
        "stdev": stdev,
        "min": sorted_v[0],
        "max": sorted_v[-1],
        "p90": sorted_v[p90_idx],
    }


async def llm_reason_short(prompt: str, *, system: str | None = None) -> str:
    """Call LlmClient.reason() with optional system message and return text content."""
    from backend.llm.client import MODELS, llm_client  # type: ignore

    msgs: list[dict[str, Any]] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    turn = await llm_client.reason(
        model=MODELS["reasoning"],
        prompt_version="ai-insights/skill",
        messages=msgs,
    )
    return turn.content or ""
