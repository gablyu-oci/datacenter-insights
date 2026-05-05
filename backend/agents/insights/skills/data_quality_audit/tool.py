"""data_quality_audit — per-source freshness flag (fresh / stale / unknown)."""
from __future__ import annotations

from datetime import datetime, timezone

from ...specs.skill_context import SkillContext
from .inputs import DataQualityAuditInputs
from .outputs import DataQualityAuditOutputs, SourceFreshness


async def run(
    inputs: DataQualityAuditInputs, ctx: SkillContext | None = None
) -> DataQualityAuditOutputs:
    now = inputs.now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    out: list[SourceFreshness] = []
    n_fresh = n_stale = n_unknown = 0
    for s in inputs.sources:
        if s.last_ingested_at is None:
            out.append(SourceFreshness(name=s.name, flag="unknown", sla_days=s.sla_days))
            n_unknown += 1
            continue
        last = s.last_ingested_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age_days = (now - last).total_seconds() / 86400.0
        if age_days <= s.sla_days:
            out.append(
                SourceFreshness(name=s.name, flag="fresh", age_days=age_days, sla_days=s.sla_days)
            )
            n_fresh += 1
        else:
            out.append(
                SourceFreshness(name=s.name, flag="stale", age_days=age_days, sla_days=s.sla_days)
            )
            n_stale += 1

    return DataQualityAuditOutputs(
        sources=out,
        n_fresh=n_fresh,
        n_stale=n_stale,
        n_unknown=n_unknown,
    )
