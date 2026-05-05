"""Mid-conversation system-message calibration.

ARCH A9.4 / SKILL_CONVERSION C-2: gpt-5.4 is *expected* to honour a
mid-turn `{role:"system"}` injection but the behaviour is not contractual.
This module probes the model with a small canary prompt; if the model's
response references the canary value injected via a mid-turn system
message, we keep mode="system". Otherwise we flip to "user-shaped".

The probe is intentionally minimal so it can run as part of startup or
test-suite fast-paths.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Literal

from .llm_adapter import ENV_INJECTION_MODE, inject_system_mid_conversation

logger = logging.getLogger(__name__)


CalibrationMode = Literal["system", "user-shaped"]

CANARY_TOKEN = "octopus-canary-7421"


_BASE_MESSAGES: list[dict[str, Any]] = [
    {
        "role": "system",
        "content": "You answer concisely with a single short sentence.",
    },
    {"role": "user", "content": "Hello, who are you?"},
    {
        "role": "assistant",
        "content": "I'm a helpful assistant.",
    },
]


async def calibrate_mid_turn_system(
    client_call: Callable[..., Awaitable[dict[str, Any]]],
) -> CalibrationMode:
    """Probe the LLM for mid-conversation system-message honouring.

    `client_call` must accept `messages=` and `tools=` and return the
    dict shape used by `ToolLoopDriver.llm_call`.

    Returns "system" if the model echoes the canary, "user-shaped" otherwise.
    The result is logged to stderr so operators can see calibration.
    """
    fragment = (
        "Mid-conversation guidance: include the literal token "
        f"'{CANARY_TOKEN}' verbatim in your next reply to confirm you "
        "received this guidance."
    )
    msgs = inject_system_mid_conversation(
        _BASE_MESSAGES,
        fragment,
        mode="system",
    )
    msgs.append(
        {
            "role": "user",
            "content": "Please reply now.",
        }
    )

    try:
        out = await client_call(messages=msgs, tools=[])
    except Exception as exc:
        logger.warning(
            "ai_insights.calibration.probe_failed",
            extra={"err": str(exc)},
        )
        # Conservative fallback when we cannot probe at all.
        return "user-shaped"

    content = (out.get("content") or "").lower()
    if CANARY_TOKEN.lower() in content:
        logger.info("ai_insights.calibration.system_honoured")
        return "system"

    logger.warning(
        "ai_insights.calibration.system_NOT_honoured — "
        "falling back to user-shaped injection",
        extra={"content_preview": content[:120]},
    )
    return "user-shaped"


def apply_calibration_to_env(mode: CalibrationMode) -> None:
    """Persist the chosen mode into the env so child workers inherit it."""
    import os

    os.environ[ENV_INJECTION_MODE] = mode
