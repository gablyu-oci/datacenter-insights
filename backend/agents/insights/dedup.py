"""Embedding-based duplicate detection for insight headlines.

Uses cosine similarity against text-embedding-3-large vectors. Threshold
0.85 per ratified C-1 (TASKS.md T2). The function is async to keep the
embed call non-blocking.

Optional Jaccard token-overlap pre-filter avoids embedding work on obvious
near-duplicates.

Phase 2 addition (D8 — cross-day dedup):
    fetch_recent_embeddings(db, days=14) primes the orchestrator's
    `_emitted_headlines` list at session start with the last 14 days of
    AIInsight rows that already have a pgvector embedding. The
    orchestrator feeds the result into `is_duplicate()` so today's
    candidate headlines are deduped against the prior fortnight, not
    just headlines emitted within the current session.
"""
from __future__ import annotations

import logging
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .specs.skill_context import SkillContext

logger = logging.getLogger(__name__)

DEFAULT_COSINE_THRESHOLD = 0.85
JACCARD_PREFILTER = 0.7
# D8 — pgvector cosine vs. last 14 days at threshold 0.85.
CROSS_DAY_LOOKBACK_DAYS = 14

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text)}


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def _cosine(u: Sequence[float], v: Sequence[float]) -> float:
    if not u or not v or len(u) != len(v):
        return 0.0
    dot = sum(a * b for a, b in zip(u, v))
    nu = math.sqrt(sum(a * a for a in u))
    nv = math.sqrt(sum(b * b for b in v))
    if nu == 0.0 or nv == 0.0:
        return 0.0
    return dot / (nu * nv)


async def _embed_one(text: str) -> list[float]:
    """Embed a single string via the existing LlmClient singleton."""
    from llm.client import llm_client  # type: ignore

    out = await llm_client.embed(texts=[text])
    return out[0] if out else []


async def is_duplicate(
    headline: str,
    prior_headlines_with_embeddings: Iterable[tuple[str, list[float]]],
    ctx: SkillContext | None = None,
    *,
    cosine_threshold: float = DEFAULT_COSINE_THRESHOLD,
    jaccard_threshold: float = JACCARD_PREFILTER,
) -> bool:
    """Return True if `headline` is a duplicate of any prior entry.

    Strategy:
      1. Cheap Jaccard pre-filter: if any prior headline scores >= 0.7 we
         declare duplicate without bothering the embedding endpoint.
      2. Otherwise embed `headline` and compare cosine to each prior vector.
      3. Threshold defaults to 0.85.
    """
    priors = list(prior_headlines_with_embeddings)
    if not priors:
        return False

    # 1) Jaccard pre-filter
    for prior_text, _ in priors:
        if _jaccard(headline, prior_text) >= jaccard_threshold:
            return True

    # 2) Cosine
    target_vec = await _embed_one(headline)
    if not target_vec:
        # If embedding fails we fall back to "not duplicate" so we don't
        # silently drop content. The caller logs this case.
        return False
    for _, vec in priors:
        # PRD §5.1 says "reject if cosine ≥ 0.85" — `>=` is the intentional inclusive
        # boundary. test_insights_dedup.py asserts a 0.85 example is rejected.
        if _cosine(target_vec, vec) >= cosine_threshold:
            return True
    return False


# ---------------------------------------------------------------------------
# Phase 2 (D8): cross-day priming
# ---------------------------------------------------------------------------


async def fetch_recent_embeddings(
    db: AsyncSession,
    days: int = CROSS_DAY_LOOKBACK_DAYS,
) -> list[tuple[uuid.UUID, str, list[float]]]:
    """Return prior-N-days insight rows with a non-null headline_embedding.

    Each tuple is (ai_insight.id, headline, embedding_vector). The vector
    is returned as a plain Python list[float] regardless of whether
    pgvector returned a numpy array, a Vector object, or a string —
    callers can pass it straight into `is_duplicate(...)`.

    Implementation notes:
      * Uses raw SQL because the SQLModel column type is `Any` (the
        pgvector binding is optional at import time, see models.py).
      * Joins `ai_session` so we only return rows from successful
        sessions (status='complete'). Failed/cancelled sessions are
        intentionally ignored — they may carry junk headlines.
      * The 14-day window is the D8-ratified default; callers can pass
        a different `days` value for tests.
      * On ANY exception (e.g. pgvector not installed in a test DB) we
        log a warning and return []. The caller is therefore safe to
        call this at session start without try/except — the worst case
        is an empty cross-day prior, identical to a brand-new
        deployment.
    """
    if db is None or days <= 0:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # NOTE: we cast `headline_embedding::text` and parse the bracketed
    # textual representation ('[0.1,0.2,...]') so the function works on
    # both pgvector-bound rows and the SQLite test fixture (where the
    # column is plain TEXT). pgvector serializes vector(N) to a square-
    # bracketed comma-separated string in text mode, so a single parser
    # handles both backends.
    sql = text(
        """
        SELECT i.id           AS id,
               i.headline     AS headline,
               i.headline_embedding::text AS embedding_text
          FROM ai_insight i
          JOIN ai_session s ON s.id = i.session_id
         WHERE i.headline_embedding IS NOT NULL
           AND i.created_at >= :cutoff
           AND s.status = 'complete'
         ORDER BY i.created_at DESC
        """
    )

    out: list[tuple[uuid.UUID, str, list[float]]] = []
    try:
        result = await db.execute(sql, {"cutoff": cutoff})
        for row in result.mappings().all():
            raw = row.get("embedding_text")
            if raw is None:
                continue
            vec = _parse_embedding_text(raw)
            if not vec:
                continue
            row_id = row.get("id")
            if isinstance(row_id, str):
                try:
                    row_id = uuid.UUID(row_id)
                except ValueError:
                    continue
            headline = row.get("headline") or ""
            out.append((row_id, headline, vec))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "ai_insights.dedup.fetch_recent_embeddings_failed",
            extra={"error": str(exc), "days": days},
        )
        return []
    return out


def _parse_embedding_text(raw: Any) -> list[float]:
    """Parse pgvector text serialization "[0.1,0.2,...]" into a list[float].

    Tolerates JSON-style brackets and stray whitespace. Returns [] on
    any parse failure rather than raising — callers iterate priors and
    silently skip malformed rows.
    """
    if isinstance(raw, list):
        try:
            return [float(x) for x in raw]
        except (TypeError, ValueError):
            return []
    if not isinstance(raw, str):
        return []
    s = raw.strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    try:
        return [float(part) for part in s.split(",") if part.strip()]
    except ValueError:
        return []
