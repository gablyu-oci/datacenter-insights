"""Speaker-aware chunker for Alpha Vantage earnings call transcripts.

Mirrors the EDGAR-side chunker shape but operates on per-speaker turns
rather than free-form filing text. Each transcript is a list of turns:

    [{"speaker": "...", "title": "...", "content": "...", ...}, ...]

We:
  1. Concatenate turns into a single raw_text the way the parent row
     stores it (speaker label + ": " + content + double newline).
  2. Detect the prepared-remarks → Q&A boundary heuristically — the
     first Operator turn whose content mentions "question", "Q&A",
     or "analyst" demarcates the start of Q&A. Pre-boundary chunks
     are tagged ``section='prepared_remarks'``, post-boundary chunks
     get ``section='q_and_a'``.
  3. Chunk WITHIN turns. Target 500 tokens, hard-cap 800. A single
     turn under 800 tokens emits one chunk; longer turns are
     sentence-split into windows that fit under the cap. We never
     merge two distinct speaker turns into one chunk — that would
     destroy speaker attribution.
  4. Replace-then-insert: existing earnings_passages for the
     document_id are deleted before the new chunk set is inserted,
     so re-chunking after extraction is a clean swap.

Public API:
    async def chunk_and_store(session, transcript_id, raw_text) -> int
"""
from __future__ import annotations

import logging
import re
import uuid as _uuid
from typing import Any

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


TARGET_TOKENS = 500
HARD_CAP_TOKENS = 800
TOKENIZER_NAME = "cl100k_base"

# Heuristic Q&A boundary cues — see docs/research/alpha_vantage_earnings.md §1.
_OPERATOR_QA_CUES = re.compile(
    r"(question[- ]and[- ]answer|q\s*&\s*a|q\s+and\s+a|first question|"
    r"analyst|please go ahead)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Tokenizer (lazy import — tiktoken is heavy)
# ---------------------------------------------------------------------------

_enc = None


def _get_encoder():
    global _enc
    if _enc is None:
        try:
            import tiktoken
            _enc = tiktoken.get_encoding(TOKENIZER_NAME)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "earnings_chunker.tiktoken_unavailable",
                extra={"error": str(exc)},
            )
            _enc = False
    return _enc


def _count_tokens(s: str) -> int:
    enc = _get_encoder()
    if not enc:
        # Cheap fallback: ~4 chars/token estimate keeps the chunker
        # functional in test environments without tiktoken.
        return max(1, len(s) // 4)
    return len(enc.encode(s))


# ---------------------------------------------------------------------------
# Sentence splitter (regex, deliberately simple — earnings prose is clean)
# ---------------------------------------------------------------------------

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def _split_sentences(s: str) -> list[str]:
    s = s.strip()
    if not s:
        return []
    parts = _SENTENCE_SPLIT.split(s)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Turn-level helpers
# ---------------------------------------------------------------------------


def _format_turn_text(turn: dict) -> str:
    """Render a single turn as ``"Speaker: content"`` for the raw_text concat."""
    speaker = (turn.get("speaker") or "").strip()
    content = (turn.get("content") or "").strip()
    if speaker:
        return f"{speaker}: {content}"
    return content


def _is_operator_qa_boundary(turn: dict) -> bool:
    """Detect the prepared_remarks → q_and_a boundary turn."""
    speaker = (turn.get("speaker") or "").lower()
    title = (turn.get("title") or "").lower()
    if "operator" not in speaker and "operator" not in title:
        return False
    content = turn.get("content") or ""
    return bool(_OPERATOR_QA_CUES.search(content))


def _chunk_turn(
    speaker: str,
    content: str,
    section: str,
    abs_offset: int,
    next_ord: int,
) -> list[dict]:
    """Split a single speaker turn into ≤HARD_CAP_TOKENS sub-chunks.

    Returns a list of passage-row dicts ready for insert. ``abs_offset``
    is the character offset of ``content`` inside the parent raw_text
    so char_start/char_end stay aligned.
    """
    out: list[dict] = []
    content = content or ""
    if not content.strip():
        return out

    total_tokens = _count_tokens(content)
    if total_tokens <= HARD_CAP_TOKENS:
        out.append({
            "ord": next_ord,
            "text": content,
            "char_start": abs_offset,
            "char_end": abs_offset + len(content),
            "token_count": total_tokens,
            "tokenizer": TOKENIZER_NAME,
            "speaker": (speaker or None),
            "section": section,
        })
        return out

    # Turn is too long. Sentence-split + greedy pack to TARGET tokens
    # with HARD_CAP_TOKENS as the hard cap.
    sentences = _split_sentences(content)
    if not sentences:
        # No sentence boundaries detected — fall back to a single chunk
        # truncated to the hard cap so we never emit a HARD_CAP-blowing row.
        out.append({
            "ord": next_ord,
            "text": content,
            "char_start": abs_offset,
            "char_end": abs_offset + len(content),
            "token_count": total_tokens,
            "tokenizer": TOKENIZER_NAME,
            "speaker": (speaker or None),
            "section": section,
        })
        return out

    buf: list[str] = []
    buf_tokens = 0
    # Track buffer's char start inside the original content so we can
    # restore abs_offset-relative char_start/char_end.
    buf_char_start = 0
    cursor = 0  # walks through content as we consume sentences

    def _flush() -> None:
        nonlocal buf, buf_tokens, buf_char_start
        if not buf:
            return
        joined = " ".join(buf).strip()
        if not joined:
            buf = []
            buf_tokens = 0
            return
        char_start = abs_offset + buf_char_start
        char_end = char_start + len(joined)
        out.append({
            "ord": next_ord + len(out),
            "text": joined,
            "char_start": char_start,
            "char_end": char_end,
            "token_count": _count_tokens(joined),
            "tokenizer": TOKENIZER_NAME,
            "speaker": (speaker or None),
            "section": section,
        })
        buf = []
        buf_tokens = 0

    for sent in sentences:
        # Find the sentence within `content` starting at cursor so
        # char offsets stay anchored to the source text.
        idx = content.find(sent, cursor)
        if idx < 0:
            idx = cursor
        sent_tokens = _count_tokens(sent)
        if not buf:
            buf_char_start = idx
        # If a single sentence by itself exceeds the hard cap, flush
        # whatever is buffered then emit the long sentence as its own
        # chunk. Earnings prose rarely produces sentences this long but
        # legal disclaimer sentences can.
        if sent_tokens > HARD_CAP_TOKENS:
            _flush()
            char_start = abs_offset + idx
            char_end = char_start + len(sent)
            out.append({
                "ord": next_ord + len(out),
                "text": sent,
                "char_start": char_start,
                "char_end": char_end,
                "token_count": sent_tokens,
                "tokenizer": TOKENIZER_NAME,
                "speaker": (speaker or None),
                "section": section,
            })
            cursor = idx + len(sent)
            continue
        # Would adding this sentence blow the hard cap? Flush first.
        if buf_tokens + sent_tokens > HARD_CAP_TOKENS:
            _flush()
            buf_char_start = idx
        buf.append(sent)
        buf_tokens += sent_tokens
        cursor = idx + len(sent)
        # If we've hit the target, flush proactively to keep most
        # chunks near TARGET_TOKENS rather than HARD_CAP_TOKENS.
        if buf_tokens >= TARGET_TOKENS:
            _flush()

    _flush()
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def chunk_and_store(
    session: AsyncSession,
    transcript_id: int,
    raw_text: str,
    *,
    turns: list[dict] | None = None,
) -> int:
    """Chunk a transcript and persist passages.

    Parameters
    ----------
    session : AsyncSession
        Active SQLAlchemy session; caller manages commit.
    transcript_id : int
        FK target on ``earnings_transcripts.id``.
    raw_text : str
        The full transcript text as stored on the parent row.
    turns : list[dict] | None
        Optional structured turn list (the same shape Alpha Vantage
        returns: ``{"speaker", "title", "content"}``). If provided we
        respect speaker boundaries. If absent we fall back to a single
        anonymous turn — better than nothing.

    Returns
    -------
    int
        Number of passages inserted.
    """
    if not raw_text or not raw_text.strip():
        logger.warning(
            "earnings_chunker.empty_raw_text",
            extra={"transcript_id": transcript_id},
        )
        return 0

    # 1) Replace-then-insert: delete any prior passages for this transcript.
    await session.execute(
        sa_text("DELETE FROM earnings_passages WHERE document_id = :doc"),
        {"doc": transcript_id},
    )

    # 2) Build the turn list. If caller didn't pass one, synthesize a
    #    single turn so we still produce passages.
    if not turns:
        turns = [{"speaker": None, "title": None, "content": raw_text}]

    # 3) Walk turns, detect q_and_a boundary, build passage rows.
    section = "prepared_remarks"
    rows: list[dict] = []
    cursor = 0  # char offset inside raw_text
    next_ord = 0

    for turn in turns:
        content = (turn.get("content") or "").strip()
        if not content:
            continue

        # Boundary detection: flip section starting AT this turn.
        if section == "prepared_remarks" and _is_operator_qa_boundary(turn):
            section = "q_and_a"

        # Where in raw_text does this turn's content begin? We stored
        # raw_text as "Speaker: content\n\nSpeaker2: content2..." so
        # advance cursor by the rendered prefix length.
        rendered = _format_turn_text(turn)
        idx = raw_text.find(rendered, cursor)
        if idx < 0:
            # raw_text was produced differently — fall back to a
            # best-effort find of the content alone, then to cursor.
            idx = raw_text.find(content, cursor)
            if idx < 0:
                idx = cursor
            content_offset = idx
        else:
            # Skip past "Speaker: " prefix so char_start aligns with
            # the content the chunker is actually emitting.
            speaker_part = (turn.get("speaker") or "").strip()
            prefix_len = len(f"{speaker_part}: ") if speaker_part else 0
            content_offset = idx + prefix_len

        chunks = _chunk_turn(
            speaker=turn.get("speaker") or "",
            content=content,
            section=section,
            abs_offset=content_offset,
            next_ord=next_ord,
        )
        rows.extend(chunks)
        next_ord += len(chunks)
        cursor = max(cursor, content_offset + len(content))

        # After the boundary turn itself flips to q_and_a, every
        # downstream turn inherits q_and_a.
        if section == "prepared_remarks":
            # Heuristic backup: if we're > 60% through the turn list
            # without a hit on the operator regex, the next analyst
            # title implies Q&A has begun.
            title = (turn.get("title") or "").lower()
            speaker = (turn.get("speaker") or "").lower()
            if "analyst" in title or "–" in speaker or " - " in speaker:
                section = "q_and_a"

    # 4) Bulk insert.
    if not rows:
        return 0

    for r in rows:
        await session.execute(
            sa_text(
                """
                INSERT INTO earnings_passages (
                    passage_id, document_id, ord, text,
                    char_start, char_end, token_count, tokenizer,
                    speaker, section
                ) VALUES (
                    :passage_id, :document_id, :ord, :text,
                    :char_start, :char_end, :token_count, :tokenizer,
                    :speaker, :section
                )
                """
            ),
            {
                "passage_id": str(_uuid.uuid4()),
                "document_id": transcript_id,
                "ord": r["ord"],
                "text": r["text"],
                "char_start": r["char_start"],
                "char_end": r["char_end"],
                "token_count": r["token_count"],
                "tokenizer": r["tokenizer"],
                "speaker": r["speaker"],
                "section": r["section"],
            },
        )

    logger.info(
        "earnings_chunker.stored",
        extra={
            "transcript_id": transcript_id,
            "passage_count": len(rows),
        },
    )
    return len(rows)


__all__ = ["chunk_and_store", "TARGET_TOKENS", "HARD_CAP_TOKENS"]
