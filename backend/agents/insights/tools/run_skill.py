"""run_skill — dispatcher for the converted analytical skills.

Each skill module lives at `backend.agents.insights.skills.<name>` and
exports an `async def run(inputs, ctx) -> outputs` entrypoint.

We enforce:
- closed-set skill_name (else `unknown_skill`)
- no recursive `run_skill` (the call stack on ctx is checked; the SkillContext
  spec also flags `can_run_skill=False` per S4.3)
- inputs are passed through to the skill's typed Pydantic model
"""
from __future__ import annotations

import importlib
import logging
import time
from typing import Any

from ..specs.skill_context import SkillContext

logger = logging.getLogger(__name__)


# Authoritative dispatch list. Must match SKILL_CONVERSION.md S4.2 / W4
# plus the PRD §6.3 additions.
ALL_SKILLS = (
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
    "cohort_analysis",
    "methodology_explainer",
    "peer_review_template",
)


class _CallStack:
    """Per-context call-stack tracker preventing run_skill recursion."""

    def __init__(self) -> None:
        self.active: list[str] = []


def _get_call_stack(ctx: SkillContext | None) -> _CallStack:
    if ctx is None:
        return _CallStack()
    # SkillContext is a Pydantic model with extra='forbid', so we attach the
    # call-stack to the dispatcher-side dict via __dict__ on a model_copy.
    stack = getattr(ctx, "_run_skill_stack", None)
    if stack is None:
        stack = _CallStack()
        # Bypass pydantic immutability by writing into __dict__ directly.
        object.__setattr__(ctx, "_run_skill_stack", stack)
    return stack


async def run_skill(
    skill_name: str,
    inputs: dict[str, Any] | None = None,
    ctx: SkillContext | None = None,
) -> dict[str, Any]:
    """Dispatch to the named skill and return its typed output as a dict.

    On any failure returns ``{"ok": False, "error": "<code>", ...}``.
    """
    inputs = inputs or {}

    if skill_name not in ALL_SKILLS:
        return {
            "ok": False,
            "error": "unknown_skill",
            "detail": {"requested": skill_name, "allowed": list(ALL_SKILLS)},
        }

    stack = _get_call_stack(ctx)
    if skill_name in stack.active:
        return {
            "ok": False,
            "error": "recursive_run_skill",
            "detail": {"skill": skill_name, "stack": list(stack.active)},
        }
    stack.active.append(skill_name)

    started = time.monotonic()
    try:
        module = importlib.import_module(
            f"backend.agents.insights.skills.{skill_name}"
        )
    except ImportError as exc:
        stack.active.pop()
        return {
            "ok": False,
            "error": "skill_import_failed",
            "detail": {"skill": skill_name, "exc": str(exc)},
        }

    try:
        run_fn = getattr(module, "run")
    except AttributeError:
        stack.active.pop()
        return {
            "ok": False,
            "error": "skill_missing_run",
            "detail": {"skill": skill_name},
        }

    try:
        # Build the inputs object via the skill's Inputs model (if present).
        try:
            inputs_module = importlib.import_module(
                f"backend.agents.insights.skills.{skill_name}.inputs"
            )
            # convention: <Camel>Inputs
            inputs_cls = getattr(
                inputs_module,
                next(n for n in dir(inputs_module) if n.endswith("Inputs")),
            )
            parsed_inputs = inputs_cls.model_validate(inputs)
        except (ImportError, StopIteration, AttributeError):
            parsed_inputs = inputs  # type: ignore[assignment]

        result = await run_fn(parsed_inputs, ctx)

        # Convert pydantic outputs to dicts for the dispatcher.
        out_dict: Any
        if hasattr(result, "model_dump"):
            out_dict = result.model_dump()
        else:
            out_dict = result

        latency_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": True,
            "skill": skill_name,
            "outputs": out_dict,
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        logger.exception("ai_insights.run_skill.error", extra={"skill": skill_name})
        return {
            "ok": False,
            "error": "skill_runtime_error",
            "detail": {"skill": skill_name, "exc": str(exc)},
        }
    finally:
        stack.active.pop()
