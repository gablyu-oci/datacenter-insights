"""LLC -> Parent resolver agent (Phase 1.5).

Resolves a `permittee_raw_name` (e.g. "Vadata, Inc.") to its ultimate
hyperscaler parent (e.g. Amazon) by aggregating multiple weak signals.

Signal pipeline (ordered, short-circuit on Exhibit 21 exact match):
    1. SEC Exhibit 21 alias lookup       (weight 1.0 exact, 0.9 fuzzy)
    2. OpenCorporates free API           (weight 0.8)
    3. Parcel deeds                       (TODO Phase 2 -- skipped)
    4. ISO/RTO queue cross-reference      (weight 0.5)
    5. Web search via LlmClient.reason    (weight 0.6, capped contribution)

Confidence aggregation:
    - SEC Exhibit 21 EXACT match -> 1.0 (short-circuit, no other signals needed)
    - 2+ independent signals corroborating the SAME parent -> >= 0.85 (auto-apply)
    - 1 signal only that is not Exhibit 21 exact -> < 0.85 (review queue)
    - LLM-only with no other signal -> capped at 0.84 (review queue)

DB effects per resolution:
    - confidence >= 0.85 AND parent_company_id known:
        UPSERT site_company_associations (role='permit_parent', source='parent_resolver')
        UPDATE generator_permits.resolved_company_id
    - 0 < confidence < 0.85:
        INSERT permit_parent_review_queue (status='pending') with top-3 candidates
    - Always:
        INSERT llm_extraction_runs (agent_name='parent_resolver') for caching/audit

Smoke test:
    cd backend && python -m agents.parent_resolver
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

import httpx
from rapidfuzz import fuzz
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Company,
    CompanyAlias,
    GeneratorPermit,
    LlmExtractionRun,
    PermitParentReviewQueue,
    SiteCompanyAssociation,
)

logger = logging.getLogger("agents.parent_resolver")

PROMPT_VERSION = "parent-resolver-v1.0.0"
AGENT_NAME = "parent_resolver"

# Weights per signal — mirrors §7.5.4 of the pipeline doc
SIGNAL_WEIGHTS = {
    "sec_exhibit_21_exact": 1.0,
    "sec_exhibit_21_fuzzy": 0.9,
    "opencorporates": 0.8,
    "parcel_deeds": 0.7,  # weight if we ever implement
    "iso_queue": 0.5,
    "filing_attorney": 0.3,
    "web_search": 0.6,
}

OPENCORPORATES_BASE = "https://api.opencorporates.com/v0.4"
OPENCORPORATES_THROTTLE_SEC = 2.5  # free tier ~50/day

# Hyperscaler-corporate-counsel/officer fingerprint phrases. Substring match
# (case-insensitive) on OpenCorporates officer names / addresses.
HYPERSCALER_FINGERPRINTS = {
    "Amazon": [
        "amazon", "vadata", "amazon data services", "amazon web services",
        "ads-c01", "p.o. box 81226 seattle",
    ],
    "Microsoft": [
        "microsoft", "msft", "microsoft corporation",
        "1 microsoft way redmond",
    ],
    "Google": [
        "google", "alphabet", "raiden", "google llc",
        "1600 amphitheatre parkway",
    ],
    "Meta": [
        "meta platforms", "facebook", "mfnw", "starbelt",
        "1 hacker way menlo park",
    ],
    "Oracle": [
        "oracle", "oracle america", "oracle cerner",
        "2300 oracle way austin",
    ],
}


# ---------------------------------------------------------------------------
# Result + Signal dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Signal:
    name: str
    weight: float
    parent_canonical: Optional[str]
    finding: str
    source_url: Optional[str] = None
    raw: Optional[dict] = None


@dataclass
class ResolutionResult:
    permittee_raw_name: str
    parent_company_id: Optional[int]
    parent_canonical_name: Optional[str]
    confidence: float
    evidence: list[dict]
    auto_applied: bool
    review_queue_id: Optional[int] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers: name normalization + hashing
# ---------------------------------------------------------------------------


_NAME_NOISE = re.compile(
    r"\b(inc\.?|llc|l\.l\.c\.|corp\.?|co\.|ltd\.?|company|the|holdings|"
    r"data\s*services?|technologies?|technology)\b",
    re.IGNORECASE,
)


def _normalize(name: str) -> str:
    """Lowercase, strip corp suffixes, collapse whitespace."""
    n = name.lower()
    n = _NAME_NOISE.sub(" ", n)
    n = re.sub(r"[,.&]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _input_hash(permittee: str, state: Optional[str]) -> str:
    raw = f"{_normalize(permittee)}|{(state or '').upper()}"
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


# ---------------------------------------------------------------------------
# Signal 1: SEC Exhibit 21 (via company_aliases)
# ---------------------------------------------------------------------------


async def _signal_sec_exhibit21(
    db: AsyncSession, permittee: str
) -> list[Signal]:
    """Query company_aliases for Exhibit 21-sourced matches."""
    norm_permittee = _normalize(permittee)
    if not norm_permittee:
        return []

    # Fetch all sec_exhibit_21 aliases and the parent companies they point at.
    # In a fresh DB this is small (<10k rows); a more scalable design would
    # use trigram indexes, but for MVP the in-memory rapidfuzz scan is fine.
    stmt = (
        select(CompanyAlias.id, CompanyAlias.raw_name, CompanyAlias.company_id, Company.canonical_name)
        .join(Company, Company.id == CompanyAlias.company_id)
        .where(CompanyAlias.source.in_(["sec_exhibit_21", "sec_exhibit21"]))
    )
    rows = (await db.execute(stmt)).all()

    if not rows:
        return []

    signals: list[Signal] = []

    # Pass 1: exact normalized match
    for _alias_id, raw_name, _company_id, canonical_name in rows:
        if _normalize(raw_name) == norm_permittee:
            return [
                Signal(
                    name="sec_exhibit_21_exact",
                    weight=SIGNAL_WEIGHTS["sec_exhibit_21_exact"],
                    parent_canonical=canonical_name,
                    finding=f"Exact Exhibit 21 alias match: {raw_name!r}",
                    source_url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
                    raw={"alias_company_id": _company_id, "raw_name": raw_name},
                )
            ]

    # Pass 2: token_set_ratio fuzzy match (>=92 considered strong)
    best_score = 0.0
    best_row = None
    for _alias_id, raw_name, _company_id, canonical_name in rows:
        score = fuzz.token_set_ratio(norm_permittee, _normalize(raw_name))
        if score > best_score:
            best_score = score
            best_row = (raw_name, _company_id, canonical_name)
    if best_row and best_score >= 92:
        raw_name, company_id, canonical_name = best_row
        signals.append(
            Signal(
                name="sec_exhibit_21_fuzzy",
                weight=SIGNAL_WEIGHTS["sec_exhibit_21_fuzzy"]
                * (best_score / 100.0),
                parent_canonical=canonical_name,
                finding=f"Fuzzy Exhibit 21 match score={best_score:.0f}: {raw_name!r}",
                source_url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
                raw={"alias_company_id": company_id, "score": best_score, "raw_name": raw_name},
            )
        )

    return signals


# ---------------------------------------------------------------------------
# Signal 2: OpenCorporates free API
# ---------------------------------------------------------------------------


async def _signal_opencorporates(
    permittee: str, state: Optional[str]
) -> list[Signal]:
    """Hit the OpenCorporates free-tier search API and look for fingerprints."""
    if not permittee.strip():
        return []
    params = {"q": permittee, "per_page": 5}
    if state:
        params["jurisdiction_code"] = f"us_{state.lower()}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            await asyncio.sleep(OPENCORPORATES_THROTTLE_SEC)
            resp = await http.get(
                f"{OPENCORPORATES_BASE}/companies/search", params=params
            )
            if resp.status_code in (429, 403):
                logger.warning(
                    "opencorporates.rate_limited",
                    extra={"status": resp.status_code, "permittee": permittee},
                )
                return []
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # pragma: no cover -- network path
        logger.info(
            "opencorporates.unavailable",
            extra={"err": str(exc), "permittee": permittee},
        )
        return []

    companies = (data.get("results") or {}).get("companies") or []
    if not companies:
        return []

    signals: list[Signal] = []
    for entry in companies[:3]:
        co = entry.get("company") or {}
        text_blob = " ".join(
            filter(
                None,
                [
                    co.get("name", ""),
                    co.get("registered_address_in_full", ""),
                    co.get("agent_name", ""),
                    co.get("agent_address", ""),
                    " ".join(o.get("name", "") for o in co.get("officers") or []),
                ],
            )
        ).lower()
        for parent, phrases in HYPERSCALER_FINGERPRINTS.items():
            if any(p in text_blob for p in phrases):
                signals.append(
                    Signal(
                        name="opencorporates",
                        weight=SIGNAL_WEIGHTS["opencorporates"],
                        parent_canonical=parent,
                        finding=(
                            f"OpenCorporates record for "
                            f"{co.get('name','?')!r} "
                            f"contains fingerprint for {parent}"
                        ),
                        source_url=co.get("opencorporates_url"),
                        raw={"co": co.get("name"), "jurisdiction": co.get("jurisdiction_code")},
                    )
                )
                break  # one fingerprint per record is enough
    return signals


# ---------------------------------------------------------------------------
# Signal 4: ISO/RTO queue cross-reference
# ---------------------------------------------------------------------------


async def _signal_iso_queue(
    db: AsyncSession,
    permittee: str,
    lat: Optional[float],
    lon: Optional[float],
    state: Optional[str],
) -> list[Signal]:
    """Look for an ISO interconnection queue project sharing
    name-fragments or geography with the permit."""
    norm_permittee = _normalize(permittee)

    # 1) Name fuzzy match across pjm-sourced rows in generator_permits
    stmt = select(GeneratorPermit).where(GeneratorPermit.source.like("pjm%"))
    if state:
        stmt = stmt.where(GeneratorPermit.state_code == state.upper())
    iso_rows = (await db.execute(stmt)).scalars().all()

    signals: list[Signal] = []
    best = (0.0, None)
    for row in iso_rows:
        candidate = row.permittee_raw_name or row.facility_name or ""
        score = fuzz.token_set_ratio(norm_permittee, _normalize(candidate))
        if score > best[0]:
            best = (score, row)

    if best[1] is not None and best[0] >= 80:
        row = best[1]
        candidate = row.permittee_raw_name or row.facility_name or ""
        # Try to identify a parent in the ISO project name
        for parent, phrases in HYPERSCALER_FINGERPRINTS.items():
            blob = candidate.lower()
            if any(p in blob for p in phrases):
                signals.append(
                    Signal(
                        name="iso_queue",
                        weight=SIGNAL_WEIGHTS["iso_queue"]
                        * (best[0] / 100.0),
                        parent_canonical=parent,
                        finding=(
                            f"PJM queue project {candidate!r} "
                            f"(score={best[0]:.0f}) fingerprints {parent}"
                        ),
                        source_url="https://pjm.com/planning/services-requests/",
                        raw={"queue_facility": candidate, "score": best[0]},
                    )
                )
                break
    return signals


# ---------------------------------------------------------------------------
# Signal 5: LLM web-search reasoning
# ---------------------------------------------------------------------------


async def _signal_web_search_llm(
    permittee: str, state: Optional[str]
) -> list[Signal]:
    """Use LlmClient.reason with web_search to ask 'what hyperscaler owns X?'.
    Best-effort -- if the LLM endpoint or web_search tool is unavailable, return [].
    """
    try:
        from llm.client import llm_client  # local import to avoid hard dep at module-load
    except Exception:
        return []

    state_part = f" in {state}" if state else ""
    user_msg = (
        f"What hyperscaler company ultimately owns the LLC '{permittee}'{state_part}? "
        "It is the applicant on a US air permit. Search the public record "
        "(SEC filings, press releases, news). "
        'Reply with strict JSON: {"parent": "Microsoft|Amazon|Google|Meta|Oracle|Other|Unknown",'
        ' "confidence": 0..1, "reason": "...", "citations": [{"url": "...", "snippet": "..."}]}'
    )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the public web for a query.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        }
    ]

    try:
        turn = await llm_client.reason(
            prompt_version=PROMPT_VERSION,
            messages=[
                {"role": "system", "content": "You are a corporate-records analyst."},
                {"role": "user", "content": user_msg},
            ],
            tools=tools,
        )
    except Exception as exc:
        logger.info("parent_resolver.llm_unavailable", extra={"err": str(exc)})
        return []

    content = (turn.content or "").strip()
    # Extract JSON from possibly-wrapped reply
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return []
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []

    parent = parsed.get("parent")
    conf = float(parsed.get("confidence") or 0)
    if not parent or parent in ("Unknown", "Other") or conf < 0.5:
        return []

    return [
        Signal(
            name="web_search",
            weight=SIGNAL_WEIGHTS["web_search"] * conf,
            parent_canonical=parent,
            finding=parsed.get("reason", "LLM web-search inference"),
            source_url=(parsed.get("citations") or [{}])[0].get("url"),
            raw={"llm_parsed": parsed, "model": turn.model},
        )
    ]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _aggregate(signals: list[Signal]) -> tuple[Optional[str], float, list[Signal]]:
    """Pick winning parent + final confidence.

    Rules:
        - If sec_exhibit_21_exact fired -> short-circuit confidence=1.0.
        - Otherwise group signals by parent_canonical, sum weights per parent,
          pick highest-summing parent.
        - Final confidence = min(1.0, max_per_parent_sum).
        - If only signal is web_search (no corroboration) -> cap at 0.84.
    """
    if not signals:
        return (None, 0.0, [])

    # Short-circuit on exact Exhibit 21
    for s in signals:
        if s.name == "sec_exhibit_21_exact":
            return (s.parent_canonical, 1.0, [s])

    by_parent: dict[str, float] = {}
    by_parent_sigs: dict[str, list[Signal]] = {}
    for s in signals:
        if not s.parent_canonical:
            continue
        by_parent.setdefault(s.parent_canonical, 0.0)
        by_parent[s.parent_canonical] += s.weight
        by_parent_sigs.setdefault(s.parent_canonical, []).append(s)

    if not by_parent:
        return (None, 0.0, [])

    winner = max(by_parent.items(), key=lambda kv: kv[1])
    parent, score = winner
    sigs_for_winner = by_parent_sigs[parent]

    # Cap LLM-only resolutions
    if len(sigs_for_winner) == 1 and sigs_for_winner[0].name == "web_search":
        score = min(score, 0.84)

    return (parent, min(1.0, score), sigs_for_winner)


# ---------------------------------------------------------------------------
# DB-effect helpers
# ---------------------------------------------------------------------------


async def _get_company_id_by_name(db: AsyncSession, canonical_name: str) -> Optional[int]:
    stmt = select(Company.id).where(Company.canonical_name == canonical_name)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _record_llm_run(
    db: AsyncSession,
    *,
    permittee: str,
    state: Optional[str],
    output: dict,
    confidence: float,
    status: str,
    used_llm: bool,
) -> int:
    h = _input_hash(permittee, state)
    # Use a SAVEPOINT so a duplicate-key race doesn't poison the outer transaction.
    sp = await db.begin_nested()
    try:
        run = LlmExtractionRun(
            agent_name=AGENT_NAME,
            model=("oci/openai.gpt-5.4" if used_llm else "deterministic"),
            prompt_version=PROMPT_VERSION,
            input_hash=h,
            input_excerpt=permittee[:240],
            output=output,
            confidence=confidence,
            tool_calls={"signals": output.get("evidence", [])},
            status=status,
        )
        db.add(run)
        await db.flush()
        run_id = run.id
        await sp.commit()
        return run_id
    except Exception:
        await sp.rollback()
        # Fall back to fetching the existing row by (agent_name, input_hash)
        existing = (
            await db.execute(
                select(LlmExtractionRun.id).where(
                    LlmExtractionRun.agent_name == AGENT_NAME,
                    LlmExtractionRun.input_hash == h,
                )
            )
        ).scalar_one_or_none()
        return existing or 0


async def _apply_high_confidence(
    db: AsyncSession,
    *,
    generator_permit_id: Optional[int],
    site_id: Optional[int],
    parent_company_id: int,
    confidence: float,
) -> None:
    """UPSERT the permit_parent association and update generator_permits."""
    if site_id and parent_company_id:
        stmt = pg_insert(SiteCompanyAssociation).values(
            site_id=site_id,
            company_id=parent_company_id,
            role="permit_parent",
            source="parent_resolver",
            source_record_id=str(generator_permit_id) if generator_permit_id else None,
            confidence=confidence,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        ).on_conflict_do_update(
            index_elements=["site_id", "company_id", "role", "source"],
            set_={"confidence": confidence, "updated_at": datetime.utcnow()},
        )
        await db.execute(stmt)

    if generator_permit_id:
        await db.execute(
            update(GeneratorPermit)
            .where(GeneratorPermit.id == generator_permit_id)
            .values(resolved_company_id=parent_company_id, confidence=confidence)
        )


async def _enqueue_review(
    db: AsyncSession,
    *,
    generator_permit_id: Optional[int],
    permittee_raw_name: str,
    candidates: list[Signal],
    agent_run_id: int,
) -> int:
    """Insert a row into permit_parent_review_queue with top candidates."""
    cand_payload = [
        {
            "parent": s.parent_canonical,
            "weight": s.weight,
            "signal": s.name,
            "finding": s.finding,
            "source_url": s.source_url,
        }
        for s in candidates[:3]
    ]
    row = PermitParentReviewQueue(
        generator_permit_id=generator_permit_id,
        permittee_raw_name=permittee_raw_name,
        candidate_parents={"candidates": cand_payload},
        agent_run_id=agent_run_id or None,
        status="pending",
    )
    db.add(row)
    await db.flush()
    return row.id


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def resolve_permittee(
    permittee_raw_name: str,
    *,
    site_id: Optional[int] = None,
    permit_lat: Optional[float] = None,
    permit_lon: Optional[float] = None,
    permit_state: Optional[str] = None,
    generator_permit_id: Optional[int] = None,
    db: AsyncSession,
) -> ResolutionResult:
    """Run the full signal pipeline against one permittee."""
    permittee_raw_name = (permittee_raw_name or "").strip()
    if not permittee_raw_name:
        return ResolutionResult(
            permittee_raw_name=permittee_raw_name,
            parent_company_id=None,
            parent_canonical_name=None,
            confidence=0.0,
            evidence=[],
            auto_applied=False,
            error="empty permittee_raw_name",
        )

    signals: list[Signal] = []
    used_llm = False

    # Signal 1
    try:
        sigs = await _signal_sec_exhibit21(db, permittee_raw_name)
        signals.extend(sigs)
        # Short-circuit if Exhibit 21 exact fired
        if any(s.name == "sec_exhibit_21_exact" for s in sigs):
            pass  # we still flow through aggregation, which short-circuits
    except Exception as exc:
        logger.warning("signal.sec_exhibit_21_failed", extra={"err": str(exc)})

    only_exact = any(s.name == "sec_exhibit_21_exact" for s in signals)

    # Signal 2: OpenCorporates (skip if exact already)
    if not only_exact:
        try:
            sigs = await _signal_opencorporates(permittee_raw_name, permit_state)
            signals.extend(sigs)
        except Exception as exc:
            logger.warning("signal.opencorporates_failed", extra={"err": str(exc)})

    # Signal 3: parcel deeds -- TODO Phase 2
    if not only_exact:
        signals.append(
            Signal(
                name="parcel_deeds",
                weight=0.0,
                parent_canonical=None,
                finding="TODO Phase 2 -- county GIS adapters not built",
            )
        )

    # Signal 4: ISO/RTO queue
    if not only_exact:
        try:
            sigs = await _signal_iso_queue(
                db, permittee_raw_name, permit_lat, permit_lon, permit_state
            )
            signals.extend(sigs)
        except Exception as exc:
            logger.warning("signal.iso_queue_failed", extra={"err": str(exc)})

    # Signal 5: LLM web search (only if signals 1-4 are weak)
    pre_score = sum(
        s.weight for s in signals if s.name not in ("parcel_deeds",)
    )
    if not only_exact and pre_score < 0.85:
        try:
            sigs = await _signal_web_search_llm(permittee_raw_name, permit_state)
            if sigs:
                used_llm = True
                signals.extend(sigs)
        except Exception as exc:
            logger.warning("signal.web_search_failed", extra={"err": str(exc)})

    parent, confidence, winning_sigs = _aggregate(signals)
    parent_company_id = (
        await _get_company_id_by_name(db, parent) if parent else None
    )

    evidence_payload = [
        {
            "signal": s.name,
            "weight": s.weight,
            "parent_canonical": s.parent_canonical,
            "finding": s.finding,
            "source_url": s.source_url,
        }
        for s in signals
    ]

    output = {
        "parent_canonical": parent,
        "parent_company_id": parent_company_id,
        "confidence": confidence,
        "evidence": evidence_payload,
    }
    run_id = await _record_llm_run(
        db,
        permittee=permittee_raw_name,
        state=permit_state,
        output=output,
        confidence=confidence,
        status="success" if parent else "fallback",
        used_llm=used_llm,
    )

    auto_applied = False
    review_queue_id: Optional[int] = None

    if confidence >= 0.85 and parent_company_id is not None:
        await _apply_high_confidence(
            db,
            generator_permit_id=generator_permit_id,
            site_id=site_id,
            parent_company_id=parent_company_id,
            confidence=confidence,
        )
        auto_applied = True
    else:
        # Per §7.5.4: anything not auto-applied is queued for human review.
        # That includes zero-confidence cases (no signal fired) -- reviewer
        # then knows the resolver tried and found nothing, vs. silently
        # dropping the permittee.
        review_queue_id = await _enqueue_review(
            db,
            generator_permit_id=generator_permit_id,
            permittee_raw_name=permittee_raw_name,
            candidates=winning_sigs or signals,
            agent_run_id=run_id,
        )

    return ResolutionResult(
        permittee_raw_name=permittee_raw_name,
        parent_company_id=parent_company_id,
        parent_canonical_name=parent,
        confidence=confidence,
        evidence=evidence_payload,
        auto_applied=auto_applied,
        review_queue_id=review_queue_id,
    )


async def resolve_all_pending(
    *, db: AsyncSession, batch_size: int = 100
) -> dict:
    """Iterate over generator_permits rows missing a resolved parent."""
    stmt = (
        select(GeneratorPermit)
        .where(GeneratorPermit.resolved_company_id.is_(None))
        .limit(batch_size)
    )
    rows = (await db.execute(stmt)).scalars().all()

    counts = {"processed": 0, "auto_applied": 0, "queued": 0, "errors": 0}
    for row in rows:
        try:
            res = await resolve_permittee(
                row.permittee_raw_name or "",
                site_id=row.site_id,
                permit_lat=row.latitude,
                permit_lon=row.longitude,
                permit_state=row.state_code,
                generator_permit_id=row.id,
                db=db,
            )
            counts["processed"] += 1
            if res.auto_applied:
                counts["auto_applied"] += 1
            elif res.review_queue_id:
                counts["queued"] += 1
        except Exception as exc:
            logger.exception(
                "resolver.row_failed",
                extra={"permit_id": row.id, "err": str(exc)},
            )
            counts["errors"] += 1
        # Commit after each row so partial progress survives a later crash
        await db.commit()
    return counts


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------


async def _smoke_seed_test_data(db: AsyncSession) -> list[int]:
    """Ensure 5 known + 3 ambiguous permits exist for smoke testing."""
    # Make sure canonical hyperscaler companies exist
    seeds = [
        ("Amazon",     "AMZN", "0001018724"),
        ("Microsoft",  "MSFT", "0000789019"),
        ("Google",     "GOOGL","0001652044"),
        ("Meta",       "META", "0001326801"),
        ("Oracle",     "ORCL", "0001341439"),
    ]
    company_ids: dict[str, int] = {}
    for canonical, ticker, cik in seeds:
        existing = (
            await db.execute(select(Company).where(Company.canonical_name == canonical))
        ).scalar_one_or_none()
        if existing is None:
            c = Company(
                canonical_name=canonical,
                ticker=ticker,
                cik=cik,
                public_private="public",
            )
            db.add(c)
            await db.flush()
            company_ids[canonical] = c.id
        else:
            company_ids[canonical] = existing.id

    # Seed Exhibit 21 aliases used by Signal 1
    exhibit21 = [
        ("Vadata, Inc.",                   "Amazon"),
        ("Amazon Data Services, Inc.",     "Amazon"),
        ("Microsoft Azure FXS LLC",        "Microsoft"),
        ("Raiden LLC",                     "Google"),  # known Google data-center LLC
        ("MFNW LLC",                       "Meta"),
        ("Oracle America, Inc.",           "Oracle"),
        ("Bowman Development LLC",         "Google"),
    ]
    for raw_name, parent in exhibit21:
        cid = company_ids[parent]
        existing = (
            await db.execute(
                select(CompanyAlias).where(
                    CompanyAlias.source == "sec_exhibit_21",
                    CompanyAlias.raw_name == raw_name,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                CompanyAlias(
                    company_id=cid,
                    source="sec_exhibit_21",
                    raw_name=raw_name,
                    match_method="manual_seed",
                    confidence=1.0,
                )
            )
    await db.flush()

    # Seed test generator_permits rows
    test_permits = [
        # 5 known hyperscaler subsidiaries (auto-apply expected)
        {"source": "smoke_test", "source_permit_id": "TEST-001",
         "permittee_raw_name": "Vadata, Inc.",                  "state_code": "VA"},
        {"source": "smoke_test", "source_permit_id": "TEST-002",
         "permittee_raw_name": "Microsoft Azure FXS LLC",       "state_code": "WA"},
        {"source": "smoke_test", "source_permit_id": "TEST-003",
         "permittee_raw_name": "Raiden LLC",                    "state_code": "OR"},
        {"source": "smoke_test", "source_permit_id": "TEST-004",
         "permittee_raw_name": "MFNW LLC",                      "state_code": "OR"},
        {"source": "smoke_test", "source_permit_id": "TEST-005",
         "permittee_raw_name": "Oracle America, Inc.",          "state_code": "TX"},
        # 3 ambiguous (review-queue expected)
        {"source": "smoke_test", "source_permit_id": "TEST-006",
         "permittee_raw_name": "Quantum Holdings LLC",          "state_code": "VA"},
        {"source": "smoke_test", "source_permit_id": "TEST-007",
         "permittee_raw_name": "ABC Power Services",            "state_code": "TX"},
        {"source": "smoke_test", "source_permit_id": "TEST-008",
         "permittee_raw_name": "TechPark Operator LLC",         "state_code": "CO"},
    ]
    permit_ids: list[int] = []
    for p in test_permits:
        existing = (
            await db.execute(
                select(GeneratorPermit).where(
                    GeneratorPermit.source == p["source"],
                    GeneratorPermit.source_permit_id == p["source_permit_id"],
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            row = GeneratorPermit(
                source=p["source"],
                source_permit_id=p["source_permit_id"],
                permittee_raw_name=p["permittee_raw_name"],
                state_code=p["state_code"],
                fuel_type="diesel",
                permit_status="issued",
            )
            db.add(row)
            await db.flush()
            permit_ids.append(row.id)
        else:
            permit_ids.append(existing.id)
    await db.commit()
    return permit_ids


async def _smoke() -> None:
    from db.session import async_session_factory  # type: ignore

    async with async_session_factory() as db:
        permit_ids = await _smoke_seed_test_data(db)
        print(f"[smoke] seeded/found {len(permit_ids)} test permits: {permit_ids}")

        counts = await resolve_all_pending(db=db, batch_size=20)
        print(f"[smoke] resolve_all_pending counts: {counts}")

        # Show resulting site_company_associations + review queue
        sca_q = await db.execute(
            text(
                "SELECT s.id, s.company_id, c.canonical_name, s.confidence, s.source_record_id "
                "FROM site_company_associations s "
                "LEFT JOIN companies c ON c.id = s.company_id "
                "WHERE s.role='permit_parent' "
                "ORDER BY s.id DESC LIMIT 10"
            )
        )
        print("[smoke] permit_parent associations (last 10):")
        for r in sca_q.all():
            print(f"   {dict(r._mapping)}")

        rq_q = await db.execute(
            text(
                "SELECT id, permittee_raw_name, status, "
                "candidate_parents->'candidates'->0->>'parent' AS top_candidate "
                "FROM permit_parent_review_queue "
                "ORDER BY id DESC LIMIT 10"
            )
        )
        print("[smoke] review queue (last 10):")
        for r in rq_q.all():
            print(f"   {dict(r._mapping)}")

        # Acceptance asserts
        assoc_count = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM site_company_associations "
                    "WHERE role='permit_parent' AND source='parent_resolver'"
                )
            )
        ).scalar_one()
        rq_count = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM permit_parent_review_queue "
                    "WHERE status='pending'"
                )
            )
        ).scalar_one()
        # Note: associations only land if site_id is set. Our smoke permits
        # have site_id=NULL so we count via resolved_company_id on permits.
        resolved_count = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM generator_permits "
                    "WHERE source='smoke_test' AND resolved_company_id IS NOT NULL"
                )
            )
        ).scalar_one()
        print(f"[smoke] permit_parent assocs={assoc_count}, "
              f"resolved_permits={resolved_count}, review_queue={rq_count}")
        assert resolved_count >= 5, (
            f"expected >=5 high-confidence resolutions, got {resolved_count}"
        )
        assert rq_count >= 3, (
            f"expected >=3 review queue rows, got {rq_count}"
        )
        print("[smoke] PASS")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_smoke())
