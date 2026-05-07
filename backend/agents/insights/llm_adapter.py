"""LlamaStack adapter — wraps `LlmClient.reason()` with tool-loop ergonomics
and mid-conversation system-fragment injection.

Injection mode (set via env `AI_INSIGHTS_SYSTEM_INJECTION_MODE`):
    "system"        — append a {role:"system"} message in mid-conversation
                      (default; preferred when the model honours it)
    "user-shaped"   — wrap as a {role:"user"} message with [SYSTEM]/[/SYSTEM]
                      markers (fallback when the model does not honour
                      mid-turn system messages)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Literal

logger = logging.getLogger(__name__)


InjectionMode = Literal["system", "user-shaped"]
ENV_INJECTION_MODE = "AI_INSIGHTS_SYSTEM_INJECTION_MODE"


def get_injection_mode() -> InjectionMode:
    mode = os.environ.get(ENV_INJECTION_MODE, "system").lower()
    if mode not in ("system", "user-shaped"):
        logger.warning(
            "ai_insights.llm_adapter.unknown_injection_mode",
            extra={"value": mode},
        )
        return "system"
    return mode  # type: ignore[return-value]


def inject_system_mid_conversation(
    messages: list[dict[str, Any]],
    system_fragment: str,
    *,
    mode: InjectionMode | None = None,
) -> list[dict[str, Any]]:
    """Return a new message list with `system_fragment` injected.

    Per ARCH A9.3 the injection is *ephemeral*: this helper is intended to
    be called once per `run_skill` turn and the resulting list is *not*
    persisted into long-term context. The caller is responsible for not
    re-pinning the fragment across turns.
    """
    chosen = mode or get_injection_mode()
    out = list(messages)
    if chosen == "system":
        out.append(
            {
                "role": "system",
                "content": system_fragment,
            }
        )
    else:
        # user-shaped fallback
        out.append(
            {
                "role": "user",
                "content": (
                    "[SYSTEM]: "
                    + system_fragment.strip()
                    + " [/SYSTEM]"
                ),
            }
        )
    return out


async def reason_with_tools(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str | None = None,
    prompt_version: str = "ai-insights/v1",
) -> dict[str, Any]:
    """Single-turn LlmClient.reason() wrapper that always passes tools=…

    Returns the dict expected by `ToolLoopDriver.llm_call`::

        {
            "content": str | None,
            "tool_calls": list[{id, function:{name,arguments}}],
            "model": str,
            "tokens": dict,
        }
    """
    from backend.llm.client import MODELS, llm_client  # type: ignore

    chosen_model = model or MODELS["reasoning"]
    turn = await llm_client.reason(
        model=chosen_model,
        prompt_version=prompt_version,
        messages=messages,
        tools=tools,
    )
    return {
        "content": turn.content or None,
        "tool_calls": list(turn.tool_calls or []),
        "model": turn.model,
        "tokens": turn.tokens or {},
    }
