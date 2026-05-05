"""SkillContext — capability matrix passed to every converted skill tool.

Authoritative source: SKILL_CONVERSION.md S1.2 + S4.3.

A `SkillContext` is constructed by the `run_skill` dispatcher per invocation,
encoding *which* tool capabilities the active skill is allowed to exercise.
Capabilities not granted by the matrix MUST appear as False here so that
downstream code paths can short-circuit cleanly. Recursive `run_skill` is
forbidden (PRD §5.1) — the corresponding flag exists for documentation but
is gated upstream by the orchestrator, never overridden here.

NO business logic — pure schema + a single `with_capabilities` helper.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Capabilities(BaseModel):
    """Boolean flags governing which agent tools the skill may invoke.

    Defaults match V1 conservative posture: read-only data access OFF,
    emit OFF, web search OFF (V1 doesn't ship it), citation emit OFF (V2),
    and `run_skill` recursion OFF (PRD §5.1 — flat tool-use only).

    Per-skill grants come from the SKILL_CONVERSION.md S4.3 matrix:
    only `visualization-builder` is granted `can_emit_chart`; only
    `data-quality-audit`, `root-cause-investigation`, and
    `business-metrics-calculator` are granted `can_query_db`; etc.
    """

    model_config = ConfigDict(extra="forbid")

    can_query_db: bool = False
    can_call_api: bool = False
    can_get_chart_data: bool = False
    can_emit_chart: bool = False
    # Recursion is enforced upstream; the flag exists for audit and is
    # always False in V1.
    can_run_skill: bool = False
    # V2 capabilities — always False in V1.
    can_emit_citation: bool = False
    can_web_search: bool = False


class RAGRef(BaseModel):
    """One reference chunk surfaced to the skill (top-k cosine match).

    Persisted shape lives in the `skill_rag_chunk` table (ARCH A7); this
    model is the in-memory projection injected with the ephemeral system
    fragment per ARCH A9.3.
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    skill_name: str
    source_path: str
    chunk_index: int = Field(..., ge=0)
    text: str
    score: float = Field(..., ge=0.0, le=1.0)


class RAGContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    k: int = Field(default=3, ge=0, le=10)
    references: list[RAGRef] = Field(default_factory=list)


class SkillContext(BaseModel):
    """Per-invocation context handed to every converted skill tool.

    The dispatcher (`tools/skill.py`) constructs this object at the moment
    `run_skill(skill_name, inputs)` is called. The object is immutable from
    the skill's point of view; use `with_capabilities` to derive a new
    context with overrides instead of mutating in place.
    """

    # Identity / correlation
    session_id: str
    turn_id: str
    correlation_id: str

    # Model + budget
    model: str
    budget_seconds_remaining: float = Field(..., ge=0.0)

    # Capability matrix (per SKILL_CONVERSION.md S4.3)
    capabilities: Capabilities = Field(default_factory=Capabilities)

    # RAG injection (k=3 by default, ARCH A9.2)
    rag: RAGContext | None = None

    # Database role used for `query_database` calls; `ai_agent` is the
    # least-privilege read-only role per ARCH A1.3 / A10.1.
    db_role: str = "ai_agent"

    # ------------------------------------------------------------------
    # V2 additions (additive; V1 callers ignore these).
    # ------------------------------------------------------------------
    # Per-session web_search counter. Capped at 8 by `tools/web_search.py`
    # (PRD §5.3 V2 rate guardrail). Default 0 keeps V1 contract unchanged.
    web_search_count: int = Field(default=0, ge=0)

    # Optional thread handle for chat sessions; None for batch insight runs.
    thread_id: str | None = None

    # Optional active-insight handle for citation emission and chat scoping.
    insight_id: str | None = None

    # Optional bearer for the SSE event sink. The chat agent assigns a
    # `Callable[[BaseModel], Awaitable[None]]` here so tools (esp.
    # web_search and emit_citation) can publish progress events without
    # threading the queue through every signature. Pydantic stores it via
    # arbitrary-type allowance below; it stays None for V1.
    emit_event: Any | None = None

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    def with_capabilities(self, **overrides: Any) -> SkillContext:
        """Return a new `SkillContext` with the given capability overrides.

        Example::

            ctx2 = ctx.with_capabilities(can_query_db=True, can_emit_chart=True)
        """
        new_caps = self.capabilities.model_copy(update=overrides)
        return self.model_copy(update={"capabilities": new_caps})
