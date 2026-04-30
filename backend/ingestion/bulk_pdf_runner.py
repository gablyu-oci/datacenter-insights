"""
Bulk PDF parser runner — Phase 2 (AC6).

Iterates over generator_permits rows whose raw_payload contains a PDF URL
(EPA ECHO Title V air permits, etc.) AND whose rated_mw_total is NULL.
Downloads the PDF, runs the 3-stage cascade in ingestion.pdf_parser, and
updates the permit row with mw_total / fuel_type / num_units / permit_status
when the parser produced confident values.

Per AC6 we cap LLM-vision calls at 200 per run to control spend; once the
cap is hit, subsequent docs are still parsed by stages 1+2 (deterministic,
no LLM cost) but skip the vision fallback.

PDF results are cached to backend/data/cache/permit_pdf_<sha1>.json so a
re-run is free for already-processed PDFs.

Public entry point:
    async def run_bulk_pdf_parse(session, *, limit=500, llm_call_cap=200) -> dict
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_dir() -> Path:
    base = Path(__file__).resolve().parent.parent / "data" / "cache"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cache_key(pdf_url: str) -> str:
    return hashlib.sha1(pdf_url.encode("utf-8")).hexdigest()


def _cache_get(pdf_url: str) -> dict | None:
    p = _cache_dir() / f"permit_pdf_{_cache_key(pdf_url)}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _cache_put(pdf_url: str, payload: dict) -> None:
    p = _cache_dir() / f"permit_pdf_{_cache_key(pdf_url)}.json"
    try:
        p.write_text(json.dumps(payload, default=str))
    except Exception as exc:
        logger.warning("bulk_pdf.cache_write_failed: %s", exc)


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------

# Common keys on epa_echo / generic permits raw_payload that hold a PDF URL.
_PDF_KEYS = ("permit_pdf_url", "pdf_url", "document_url", "pdf",
             "fp_pdf", "fpdf", "permit_doc_url")


def _extract_pdf_url(raw_payload: dict | None) -> str | None:
    if not raw_payload or not isinstance(raw_payload, dict):
        return None
    for k in _PDF_KEYS:
        v = raw_payload.get(k)
        if v and isinstance(v, str) and v.lower().endswith(".pdf"):
            return v
        if v and isinstance(v, str) and v.startswith("http") and ".pdf" in v.lower():
            return v
    # Some echo entries store nested doc lists
    docs = raw_payload.get("documents") or raw_payload.get("attachments")
    if isinstance(docs, list):
        for d in docs:
            if isinstance(d, dict):
                for k in _PDF_KEYS + ("url", "href"):
                    v = d.get(k)
                    if v and isinstance(v, str) and ".pdf" in v.lower():
                        return v
    return None


async def _select_candidates(session: AsyncSession, limit: int) -> list[dict]:
    """Find permit rows that have a PDF URL and no rated_mw_total."""
    rows = await session.execute(text("""
        SELECT id, source, source_permit_id, raw_payload, rated_mw_total,
               fuel_type, permit_status, num_units
        FROM generator_permits
        WHERE source IN ('epa_echo', 'tceq', 'va_open_data',
                         'iowa_open_data', 'ohio_open_data')
          AND rated_mw_total IS NULL
          AND raw_payload IS NOT NULL
        ORDER BY id ASC
        LIMIT :lim
    """), {"lim": limit * 3})  # over-select; many won't have a PDF link

    selected: list[dict] = []
    for r in rows:
        url = _extract_pdf_url(r[3])
        if not url:
            continue
        selected.append({
            "id": r[0],
            "source": r[1],
            "source_permit_id": r[2],
            "pdf_url": url,
        })
        if len(selected) >= limit:
            break
    return selected


# ---------------------------------------------------------------------------
# Per-PDF processing
# ---------------------------------------------------------------------------

async def _download(url: str, dest: Path, timeout: float = 60.0) -> bool:
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(connect=15.0, read=timeout, write=10.0, pool=15.0),
            headers={"User-Agent": "strategic-insights-tool/1.0 (research)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
        return True
    except Exception as exc:
        logger.warning("bulk_pdf.download_failed url=%s err=%s", url, exc)
        return False


async def _process_one(
    session: AsyncSession,
    candidate: dict,
    *,
    skip_llm: bool,
) -> dict:
    """Returns {"updated": bool, "used_llm": bool, "from_cache": bool}."""
    url = candidate["pdf_url"]
    permit_id = candidate["id"]

    cached = _cache_get(url)
    if cached:
        parsed = cached
        used_llm = False
        from_cache = True
    else:
        from_cache = False
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "permit.pdf"
            ok = await _download(url, pdf_path)
            if not ok:
                return {"updated": False, "used_llm": False, "from_cache": False}

            # Toggle LLM stage via env var the parser reads (best-effort).
            prior_disable = os.environ.get("DISABLE_LLM_VISION")
            if skip_llm:
                os.environ["DISABLE_LLM_VISION"] = "1"
            try:
                from ingestion.pdf_parser import parse_permit_pdf
                result = await parse_permit_pdf(
                    str(pdf_path), source_url=url, session=session,
                )
            except Exception as exc:
                logger.warning("bulk_pdf.parse_failed id=%s err=%s", permit_id, exc)
                return {"updated": False, "used_llm": False, "from_cache": False}
            finally:
                if skip_llm:
                    if prior_disable is None:
                        os.environ.pop("DISABLE_LLM_VISION", None)
                    else:
                        os.environ["DISABLE_LLM_VISION"] = prior_disable

            stages = list(getattr(result, "stages_used", []) or [])
            used_llm = "llm_vision" in stages
            parsed = {
                "mw_total": getattr(result, "mw_total", None),
                "num_units": getattr(result, "num_units", None),
                "fuel_type": getattr(result, "fuel_type", None),
                "permit_status": getattr(result, "permit_status", None),
                "confidence": getattr(result, "confidence", None),
                "stages_used": stages,
                "error": getattr(result, "error", None),
                "parsed_at": datetime.utcnow().isoformat(),
            }
            _cache_put(url, parsed)

    updates = {}
    if parsed.get("mw_total") is not None:
        updates["rated_mw_total"] = float(parsed["mw_total"])
    if parsed.get("num_units") is not None:
        updates["num_units"] = int(parsed["num_units"])
    if parsed.get("fuel_type"):
        updates["fuel_type"] = str(parsed["fuel_type"])[:100]
    if parsed.get("permit_status"):
        updates["permit_status"] = str(parsed["permit_status"])[:100]

    if not updates:
        return {"updated": False, "used_llm": used_llm, "from_cache": from_cache}

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    updates["pid"] = permit_id
    await session.execute(
        text(f"UPDATE generator_permits SET {set_clause}, updated_at = NOW() "
             f"WHERE id = :pid"),
        updates,
    )
    return {"updated": True, "used_llm": used_llm, "from_cache": from_cache}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_bulk_pdf_parse(
    session: AsyncSession,
    *,
    limit: int = 500,
    llm_call_cap: int = 200,
) -> dict:
    """Process up to `limit` permit PDFs. Cap LLM-vision usage at `llm_call_cap`."""
    started = datetime.utcnow()
    candidates = await _select_candidates(session, limit)
    logger.info("bulk_pdf.selected count=%d (limit=%d)", len(candidates), limit)

    processed = 0
    updated = 0
    llm_used = 0
    cache_hits = 0
    download_failed = 0
    for cand in candidates:
        skip_llm = (llm_used >= llm_call_cap)
        try:
            r = await _process_one(session, cand, skip_llm=skip_llm)
        except Exception as exc:
            logger.warning("bulk_pdf.process_exception id=%s err=%s", cand.get("id"), exc)
            continue

        processed += 1
        if r["updated"]:
            updated += 1
        if r["used_llm"]:
            llm_used += 1
        if r["from_cache"]:
            cache_hits += 1
        if not r["updated"] and not r["from_cache"]:
            download_failed += 1

        # Commit every 25 rows so partial progress survives interruption.
        if processed % 25 == 0:
            await session.commit()

    await session.commit()
    duration = (datetime.utcnow() - started).total_seconds()
    summary = {
        "candidates": len(candidates),
        "processed": processed,
        "updated": updated,
        "llm_calls_used": llm_used,
        "llm_call_cap": llm_call_cap,
        "cache_hits": cache_hits,
        "no_progress": download_failed,
        "duration_seconds": round(duration, 1),
    }
    logger.info("bulk_pdf.done summary=%s", summary)
    return summary
