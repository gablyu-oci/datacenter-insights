"""Earnings call transcript LLM extractor.

Mirrors backend/agents/edgar_extractor.py:
  * Strict JSON schema with quote-validation defense (analogue of
    validate_buyer for EDGAR — every emitted ``quote`` MUST be a
    verbatim substring of raw_text or it is dropped).
  * Writes one ``llm_extraction_runs`` audit row per call (same
    pattern edgar_extractor uses).
  * Updates the parent ``earnings_transcripts`` row with structured
    JSONB columns + 4-axis sentiment + extracted_at / extractor_version.

Public entry point:
    async def extract_and_update(session, transcript_id) -> dict
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from llm.client import MODELS, llm_client

logger = logging.getLogger(__name__)


EXTRACTOR_VERSION = "1.0.0"
PROMPT_VERSION = "earnings_extraction_v1"
AGENT_NAME = "earnings_extractor"

# Sonnet 4.5 / equivalent reasoning-class model; the LLM client wrapper
# (backend/llm/client.py) ultimately routes through Llama Stack so we
# use the "extraction" alias the EDGAR side uses and let ops point it at
# whatever Sonnet-class model is current.
DEFAULT_MODEL = MODELS.get("extraction", "oci/openai.gpt-5.4-mini")

_VALID_SENTIMENT = {"bullish", "cautious", "bearish", "not_mentioned"}
_VALID_THEMES = {"AI", "datacenter", "power", "grid"}
_VALID_COMP_SENT = {"positive", "neutral", "negative"}

# JSON schema mirrored from the prompt template — the LLM client wrapper
# passes this to the upstream gateway when response_format is supported.
EARNINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "guidance": {
            "type": ["object", "null"],
            "properties": {
                "revenue_growth": {"type": ["string", "null"]},
                "capex_outlook": {"type": ["string", "null"]},
                "raw_quote": {"type": ["string", "null"]},
            },
            "required": ["revenue_growth", "capex_outlook", "raw_quote"],
            "additionalProperties": False,
        },
        "capex_mentions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "dollar_amount": {"type": ["string", "null"]},
                    "context": {"type": ["string", "null"]},
                },
                "required": ["quote", "dollar_amount", "context"],
                "additionalProperties": False,
            },
        },
        "ai_power_mentions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "theme": {"type": "string"},
                    "context": {"type": ["string", "null"]},
                },
                "required": ["quote", "theme", "context"],
                "additionalProperties": False,
            },
        },
        "competitive_mentions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "mentioned_company": {"type": "string"},
                    "sentiment": {"type": "string"},
                },
                "required": ["quote", "mentioned_company", "sentiment"],
                "additionalProperties": False,
            },
        },
        "mw_capacity_mentions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "mw_value": {"type": ["number", "null"]},
                    "location": {"type": ["string", "null"]},
                },
                "required": ["quote", "mw_value", "location"],
                "additionalProperties": False,
            },
        },
        "sentiment": {
            "type": "object",
            "properties": {
                "ai_demand": {"type": "string"},
                "power_constraints": {"type": "string"},
                "datacenter_capex": {"type": "string"},
                "overall": {"type": "string"},
            },
            "required": [
                "ai_demand",
                "power_constraints",
                "datacenter_capex",
                "overall",
            ],
            "additionalProperties": False,
        },
    },
    "required": [
        "guidance",
        "capex_mentions",
        "ai_power_mentions",
        "competitive_mentions",
        "mw_capacity_mentions",
        "sentiment",
    ],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------

_PROMPT_CACHE: str | None = None


def _load_prompt() -> str:
    """Read backend/agents/prompts/earnings_extraction_v1.md once."""
    global _PROMPT_CACHE
    if _PROMPT_CACHE is not None:
        return _PROMPT_CACHE
    path = Path(__file__).parent / "prompts" / "earnings_extraction_v1.md"
    _PROMPT_CACHE = path.read_text(encoding="utf-8")
    return _PROMPT_CACHE


# ---------------------------------------------------------------------------
# Quote validation — defense against hallucinated quotes
# ---------------------------------------------------------------------------


def _normalize_for_match(s: str) -> str:
    """Lowercase + collapse whitespace so minor whitespace edits in the
    quote don't trigger a false rejection."""
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _validate_quote(raw_text_norm: str, quote: str | None) -> bool:
    """Return True iff `quote` is a verbatim substring of raw_text.

    Lowercased + whitespace-collapsed comparison so the LLM can
    legitimately strip trailing punctuation or normalize curly quotes
    without us nuking the row.
    """
    if not quote or not isinstance(quote, str):
        return False
    q = _normalize_for_match(quote)
    if len(q) < 8:  # protect against trivial substring hits
        return False
    return q in raw_text_norm


def _filter_quote_items(
    items: list[dict] | None,
    raw_text_norm: str,
    *,
    label: str,
    transcript_id: int,
) -> list[dict]:
    """Drop any list entry whose ``quote`` isn't a verbatim transcript substring."""
    if not items:
        return []
    out: list[dict] = []
    dropped = 0
    for item in items:
        if not isinstance(item, dict):
            dropped += 1
            continue
        if _validate_quote(raw_text_norm, item.get("quote")):
            out.append(item)
        else:
            dropped += 1
            logger.warning(
                "earnings_extractor.quote_rejected",
                extra={
                    "transcript_id": transcript_id,
                    "field": label,
                    "quote_preview": (item.get("quote") or "")[:120],
                },
            )
    return out


def _validate_guidance(
    guidance: Any,
    raw_text_norm: str,
    *,
    transcript_id: int,
) -> dict | None:
    """If guidance.raw_quote isn't verbatim, drop the whole guidance block."""
    if not isinstance(guidance, dict):
        return None
    raw_quote = guidance.get("raw_quote")
    if raw_quote and not _validate_quote(raw_text_norm, raw_quote):
        logger.warning(
            "earnings_extractor.guidance_rejected",
            extra={
                "transcript_id": transcript_id,
                "raw_quote_preview": (raw_quote or "")[:120],
            },
        )
        return {"revenue_growth": None, "capex_outlook": None, "raw_quote": None}
    return {
        "revenue_growth": guidance.get("revenue_growth"),
        "capex_outlook": guidance.get("capex_outlook"),
        "raw_quote": raw_quote,
    }


def _coerce_sentiment(value: Any) -> str:
    s = (value or "").strip().lower() if isinstance(value, str) else ""
    if s in _VALID_SENTIMENT:
        return s
    return "not_mentioned"


def _coerce_theme(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip()
    # Case-insensitive match against the canonical set.
    for canon in _VALID_THEMES:
        if v.lower() == canon.lower():
            return canon
    return None


def _coerce_comp_sentiment(value: Any) -> str:
    s = (value or "").strip().lower() if isinstance(value, str) else ""
    if s in _VALID_COMP_SENT:
        return s
    return "neutral"


# ---------------------------------------------------------------------------
# LLM-runs audit row
# ---------------------------------------------------------------------------


async def _write_llm_run(
    session: AsyncSession,
    *,
    input_text: str,
    output: dict | None,
    confidence: float,
    latency_ms: int,
    tokens_prompt: int,
    tokens_completion: int,
    status: str,
    error_detail: str | None = None,
) -> None:
    """Mirror edgar_extractor's audit pattern: one row per LLM call."""
    input_hash = f"sha256:{hashlib.sha256(input_text.encode()).hexdigest()}"
    try:
        await session.execute(
            sa_text(
                """
                INSERT INTO llm_extraction_runs (
                    agent_name, model, prompt_version, input_hash,
                    input_excerpt, output, confidence,
                    tokens_prompt, tokens_completion, latency_ms,
                    status, error_detail, created_at
                ) VALUES (
                    :agent_name, :model, :prompt_version, :input_hash,
                    :input_excerpt, CAST(:output AS jsonb), :confidence,
                    :tokens_prompt, :tokens_completion, :latency_ms,
                    :status, :error_detail, :created_at
                )
                ON CONFLICT (agent_name, input_hash) DO UPDATE SET
                    output = EXCLUDED.output,
                    confidence = EXCLUDED.confidence,
                    tokens_prompt = EXCLUDED.tokens_prompt,
                    tokens_completion = EXCLUDED.tokens_completion,
                    latency_ms = EXCLUDED.latency_ms,
                    status = EXCLUDED.status,
                    error_detail = EXCLUDED.error_detail
                """
            ),
            {
                "agent_name": AGENT_NAME,
                "model": DEFAULT_MODEL,
                "prompt_version": PROMPT_VERSION,
                "input_hash": input_hash,
                "input_excerpt": input_text[:2000],
                "output": json.dumps(output) if output is not None else None,
                "confidence": confidence,
                "tokens_prompt": tokens_prompt,
                "tokens_completion": tokens_completion,
                "latency_ms": latency_ms,
                "status": status,
                "error_detail": error_detail,
                "created_at": datetime.utcnow(),
            },
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "earnings_extractor.llm_run_audit_failed",
            extra={"error": str(exc)},
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def extract_and_update(
    session: AsyncSession,
    transcript_id: int,
) -> dict:
    """Run LLM extraction on one earnings_transcripts row and update it.

    Returns a status dict shaped like::

        {
          "ok": bool,
          "transcript_id": int,
          "guidance": dict | None,
          "capex_count": int,
          "ai_power_count": int,
          "competitive_count": int,
          "mw_capacity_count": int,
          "sentiment": dict,
          "errors": list[str],
        }
    """
    # 1. Load raw_text from the parent row.
    row = (
        await session.execute(
            sa_text(
                "SELECT id, raw_text FROM earnings_transcripts WHERE id = :id"
            ),
            {"id": transcript_id},
        )
    ).mappings().first()

    if row is None:
        logger.warning(
            "earnings_extractor.transcript_missing",
            extra={"transcript_id": transcript_id},
        )
        return {"ok": False, "transcript_id": transcript_id, "errors": ["not_found"]}

    raw_text: str = row.get("raw_text") or ""
    if not raw_text.strip():
        logger.warning(
            "earnings_extractor.empty_raw_text",
            extra={"transcript_id": transcript_id},
        )
        return {
            "ok": False,
            "transcript_id": transcript_id,
            "errors": ["empty_raw_text"],
        }

    # 2. Render prompt + run LLM.
    prompt = _load_prompt()
    input_text = (
        prompt
        + "\n\n---\nTRANSCRIPT (verbatim quotes must come from below):\n---\n"
        + raw_text
    )

    try:
        extraction = await llm_client.extract(
            model=DEFAULT_MODEL,
            prompt_version=PROMPT_VERSION,
            input_text=input_text,
            schema=EARNINGS_SCHEMA,
        )
    except Exception as exc:
        logger.error(
            "earnings_extractor.llm_call_failed",
            extra={"transcript_id": transcript_id, "error": str(exc)},
        )
        await _write_llm_run(
            session,
            input_text=input_text,
            output=None,
            confidence=0.0,
            latency_ms=0,
            tokens_prompt=0,
            tokens_completion=0,
            status="error",
            error_detail=str(exc)[:500],
        )
        return {
            "ok": False,
            "transcript_id": transcript_id,
            "errors": [f"llm_call_failed: {exc}"],
        }

    result = extraction.result or {}
    errors: list[str] = list(extraction.errors or [])
    if errors:
        logger.warning(
            "earnings_extractor.llm_parse_errors",
            extra={"transcript_id": transcript_id, "errors": errors},
        )

    # 3. Validate quotes — drop any hallucinated items.
    raw_text_norm = _normalize_for_match(raw_text)

    guidance = _validate_guidance(
        result.get("guidance"), raw_text_norm, transcript_id=transcript_id
    )
    capex_items = _filter_quote_items(
        result.get("capex_mentions") or [],
        raw_text_norm,
        label="capex_mentions",
        transcript_id=transcript_id,
    )

    # ai_power_mentions need theme coercion too.
    raw_ai_power = result.get("ai_power_mentions") or []
    ai_power_validated = _filter_quote_items(
        raw_ai_power, raw_text_norm,
        label="ai_power_mentions",
        transcript_id=transcript_id,
    )
    ai_power_items: list[dict] = []
    for it in ai_power_validated:
        theme = _coerce_theme(it.get("theme"))
        if theme is None:
            logger.warning(
                "earnings_extractor.ai_power_theme_rejected",
                extra={
                    "transcript_id": transcript_id,
                    "raw_theme": it.get("theme"),
                },
            )
            continue
        ai_power_items.append({
            "quote": it.get("quote"),
            "theme": theme,
            "context": it.get("context"),
        })

    raw_comp = result.get("competitive_mentions") or []
    comp_validated = _filter_quote_items(
        raw_comp, raw_text_norm,
        label="competitive_mentions",
        transcript_id=transcript_id,
    )
    comp_items = [
        {
            "quote": it.get("quote"),
            "mentioned_company": it.get("mentioned_company"),
            "sentiment": _coerce_comp_sentiment(it.get("sentiment")),
        }
        for it in comp_validated
        if it.get("mentioned_company")
    ]

    mw_items = _filter_quote_items(
        result.get("mw_capacity_mentions") or [],
        raw_text_norm,
        label="mw_capacity_mentions",
        transcript_id=transcript_id,
    )

    sentiment = result.get("sentiment") or {}
    sentiment_ai = _coerce_sentiment(sentiment.get("ai_demand"))
    sentiment_power = _coerce_sentiment(sentiment.get("power_constraints"))
    sentiment_capex = _coerce_sentiment(sentiment.get("datacenter_capex"))
    sentiment_overall = _coerce_sentiment(sentiment.get("overall"))

    # 4. Update parent row.
    now = datetime.utcnow()
    try:
        await session.execute(
            sa_text(
                """
                UPDATE earnings_transcripts
                SET guidance                    = CAST(:guidance AS jsonb),
                    capex_mentions              = CAST(:capex AS jsonb),
                    ai_power_mentions           = CAST(:ai_power AS jsonb),
                    competitive_mentions        = CAST(:competitive AS jsonb),
                    mw_capacity_mentions        = CAST(:mw_capacity AS jsonb),
                    sentiment_ai_demand         = :s_ai,
                    sentiment_power_constraints = :s_power,
                    sentiment_datacenter_capex  = :s_capex,
                    sentiment_overall           = :s_overall,
                    extracted_at                = :now,
                    extractor_version           = :ver
                WHERE id = :id
                """
            ),
            {
                "guidance": json.dumps(guidance) if guidance is not None else None,
                "capex": json.dumps(capex_items),
                "ai_power": json.dumps(ai_power_items),
                "competitive": json.dumps(comp_items),
                "mw_capacity": json.dumps(mw_items),
                "s_ai": sentiment_ai,
                "s_power": sentiment_power,
                "s_capex": sentiment_capex,
                "s_overall": sentiment_overall,
                "now": now,
                "ver": EXTRACTOR_VERSION,
                "id": transcript_id,
            },
        )
    except Exception as exc:
        logger.error(
            "earnings_extractor.update_failed",
            extra={"transcript_id": transcript_id, "error": str(exc)},
        )
        await _write_llm_run(
            session,
            input_text=input_text,
            output=result,
            confidence=extraction.confidence,
            latency_ms=extraction.latency_ms,
            tokens_prompt=int(extraction.tokens.get("prompt", 0) or 0),
            tokens_completion=int(extraction.tokens.get("completion", 0) or 0),
            status="error",
            error_detail=str(exc)[:500],
        )
        return {
            "ok": False,
            "transcript_id": transcript_id,
            "errors": [f"update_failed: {exc}"],
        }

    # 5. Audit row.
    await _write_llm_run(
        session,
        input_text=input_text,
        output={
            "guidance": guidance,
            "capex_mentions": capex_items,
            "ai_power_mentions": ai_power_items,
            "competitive_mentions": comp_items,
            "mw_capacity_mentions": mw_items,
            "sentiment": {
                "ai_demand": sentiment_ai,
                "power_constraints": sentiment_power,
                "datacenter_capex": sentiment_capex,
                "overall": sentiment_overall,
            },
        },
        confidence=extraction.confidence,
        latency_ms=extraction.latency_ms,
        tokens_prompt=int(extraction.tokens.get("prompt", 0) or 0),
        tokens_completion=int(extraction.tokens.get("completion", 0) or 0),
        status="success" if not errors else "fallback",
    )

    return {
        "ok": True,
        "transcript_id": transcript_id,
        "guidance": guidance,
        "capex_count": len(capex_items),
        "ai_power_count": len(ai_power_items),
        "competitive_count": len(comp_items),
        "mw_capacity_count": len(mw_items),
        "sentiment": {
            "ai_demand": sentiment_ai,
            "power_constraints": sentiment_power,
            "datacenter_capex": sentiment_capex,
            "overall": sentiment_overall,
        },
        "errors": errors,
    }


__all__ = [
    "extract_and_update",
    "EXTRACTOR_VERSION",
    "PROMPT_VERSION",
    "EARNINGS_SCHEMA",
]
