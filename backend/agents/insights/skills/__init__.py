"""Converted skills (V1 + V2).

Each skill is a subpackage with:
    - inputs.py            Pydantic Inputs model
    - outputs.py           Pydantic Outputs model
    - tool.py              async def run(inputs, ctx) -> outputs
    - system_fragment.md   ephemeral system fragment (≤800 tokens)

The dispatcher (`tools/run_skill.py`) imports each subpackage by name and
calls its top-level `run(...)` re-export.

`SKILL_REGISTRY` below is the package-level enumeration of all converted
skills (V1 + V2). The authoritative dispatch list is
`tools/run_skill.py::ALL_SKILLS` (with `V1_SKILLS` retained as a
backward-compatible alias for the original 12 names); this module mirrors
it so other modules (orchestrator, tests) can import the registry from here
without depending on the tools layer.
"""
from __future__ import annotations

from typing import Callable

# Lazy module references — importing each `run` callable here would force-
# load every skill package at startup (and pull pandas/etc.). The dispatcher
# already imports lazily by name, so we just expose the canonical name list.

V1_SKILL_NAMES: tuple[str, ...] = (
    "programmatic_eda",
    "data_quality_audit",
    "root_cause_investigation",
    "time_series_analysis",
    "segmentation_analysis",
    "business_metrics_calculator",
    "insight_synthesis",
    "executive_summary_generator",
    "visualization_builder",
    "data_narrative_builder",
    "impact_quantification",
    "technical_to_business_translator",
)

V2_SKILL_NAMES: tuple[str, ...] = (
    "cohort_analysis",
    "methodology_explainer",
    "peer_review_template",
)

ALL_SKILL_NAMES: tuple[str, ...] = V1_SKILL_NAMES + V2_SKILL_NAMES


def _load_run(skill_name: str) -> Callable[..., object]:
    """Lazily import `<skill>.run` to avoid eager package-wide imports."""
    import importlib

    module = importlib.import_module(f"backend.agents.insights.skills.{skill_name}")
    return getattr(module, "run")


# `SKILL_REGISTRY` is keyed by skill name; values are zero-arg loaders that
# return the skill's `run` callable on first access. The kickoff allows
# either `SKILL_REGISTRY` or `SKILLS` as the registry variable name.
SKILL_REGISTRY: dict[str, Callable[[], Callable[..., object]]] = {
    name: (lambda n=name: _load_run(n)) for name in ALL_SKILL_NAMES
}

__all__ = [
    "SKILL_REGISTRY",
    "V1_SKILL_NAMES",
    "V2_SKILL_NAMES",
    "ALL_SKILL_NAMES",
]
