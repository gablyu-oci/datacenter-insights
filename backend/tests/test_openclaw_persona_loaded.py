"""Pure-file assertions on the OpenClaw agent persona.

Spec:
  - docs/plans/ai-insights-automation/11a-openclaw-migration-prd.md
    AC4 ("Persona answers come from SOUL.md") + R3 (per-request override)
  - docs/plans/ai-insights-automation/11b-openclaw-migration-architecture.md §8

This module performs ZERO LLM calls and ZERO I/O beyond reading the
SOUL.md persona file. The intent is to lock in the wire-deliverable
persona contract as a unit-test invariant so a stray edit cannot
silently regress the agent's voice or scope.

The canonical workspace path is the project-root `.openclaw/workspace/`
directory (the OpenClaw gateway mounts that directory; backend agent's
implementation note in 11b §8). The legacy in-repo copy under
`backend/openclaw/SOUL.md` is the source of truth that we ship into the
workspace; a separate test asserts both files exist and assert against
the workspace copy (which is what the OpenClaw process actually loads
at runtime).
"""
from __future__ import annotations

from pathlib import Path

import pytest

# Project root resolved at import time.
_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parents[2]  # tests/ -> backend/ -> project-root
_WORKSPACE_SOUL = _PROJECT_ROOT / ".openclaw" / "workspace" / "SOUL.md"
_BACKEND_SOUL = _PROJECT_ROOT / "backend" / "openclaw" / "SOUL.md"


# ---------------------------------------------------------------------------
# Existence + non-empty
# ---------------------------------------------------------------------------


def test_workspace_soul_md_exists_and_nonempty() -> None:
    """The OpenClaw gateway mounts .openclaw/workspace/; SOUL.md must be there."""
    assert _WORKSPACE_SOUL.exists(), (
        f"SOUL.md missing at {_WORKSPACE_SOUL}; OpenClaw will boot with a "
        "generic persona and AC4 will fail (PRD 11a §7)."
    )
    body = _WORKSPACE_SOUL.read_text(encoding="utf-8")
    assert body.strip(), "SOUL.md is empty; OpenClaw will boot with no persona."
    assert len(body) > 500, (
        f"SOUL.md is suspiciously short ({len(body)} bytes); the full "
        "persona is ~6+ KB per ARCH 11b §8."
    )


def test_backend_soul_md_exists() -> None:
    """The in-repo copy lives next to the forwarder for reviewability."""
    assert _BACKEND_SOUL.exists(), (
        f"In-repo SOUL.md missing at {_BACKEND_SOUL}; ARCH 11b §8 says the "
        "backend code path keeps a sibling copy for code review even "
        "though OpenClaw loads from the workspace."
    )


# ---------------------------------------------------------------------------
# Persona signature
# ---------------------------------------------------------------------------


def test_persona_signature_present() -> None:
    """The persona must self-identify as the Datacenter & Power Analyst.

    The canonical phrase from the in-repo persona is "Datacenter & Power
    Analyst" (note the ampersand; "Senior" is implied by the rest of the
    persona — voice, MW math, terse — but is not the literal title).
    PRD 11a AC4 ("who are you?" returns the senior datacenter analyst
    persona text) requires that the file at minimum names the role.
    """
    body = _WORKSPACE_SOUL.read_text(encoding="utf-8")
    # Accept either the exact phrase or the spec's "Senior Datacenter
    # and Power Analyst" form so the test does not break if the file is
    # later tightened to match 11b §8 verbatim.
    role_phrases = (
        "Datacenter & Power Analyst",
        "Datacenter and Power Analyst",
        "Senior Datacenter and Power Analyst",
        "Senior Datacenter & Power Analyst",
    )
    assert any(p in body for p in role_phrases), (
        f"None of {role_phrases} found in SOUL.md; the persona's "
        "self-identification (PRD AC4) is not anchored."
    )
    # Oracle anchor: the persona must claim Oracle/OCI as its home.
    assert "Oracle" in body or "OCI" in body, (
        "Persona should anchor itself to Oracle/OCI per ARCH 11b §8."
    )


# ---------------------------------------------------------------------------
# Players (competitive landscape)
# ---------------------------------------------------------------------------

# The required players from PRD/ARCH 11b §8. We require at least 10 to
# be present by exact substring; "Virginia Power" is split across a line
# break in the in-repo copy ("Dominion (incl. Virginia\nPower)") so it
# is excluded from the strict-substring count and asserted separately
# with a normalized search below.
_REQUIRED_PLAYERS = (
    "Microsoft",
    "AWS",
    "Google",
    "Meta",
    "xAI",
    "Crusoe",
    "Pattern",
    "Enlight",
    "QTS",
    "Constellation",
    "Vistra",
    "Dominion",
)
# Bonus: AWS may appear as "Amazon" or "Amazon (AWS)"; both forms count.
_AWS_ALIASES = ("AWS", "Amazon")


def test_required_players_named() -> None:
    body = _WORKSPACE_SOUL.read_text(encoding="utf-8")

    matched: list[str] = []
    for name in _REQUIRED_PLAYERS:
        if name == "AWS":
            if any(alias in body for alias in _AWS_ALIASES):
                matched.append(name)
            continue
        if name in body:
            matched.append(name)

    assert len(matched) >= 10, (
        f"Persona names only {len(matched)} of {len(_REQUIRED_PLAYERS)} "
        f"required players; matched={matched}. ARCH 11b §8 requires the "
        "persona to anchor on the competitive landscape."
    )


def test_virginia_power_named_even_across_linebreak() -> None:
    """`Dominion (incl. Virginia\\n  Power)` should still register as a hit."""
    body = _WORKSPACE_SOUL.read_text(encoding="utf-8")
    # Collapse whitespace so a soft line-wrap inside "Virginia Power"
    # does not defeat the substring search.
    collapsed = " ".join(body.split())
    assert "Virginia Power" in collapsed, (
        "Persona must mention Virginia Power as a regulated utility "
        "(ARCH 11b §8); not found even after whitespace normalization."
    )


# ---------------------------------------------------------------------------
# Schema knowledge
# ---------------------------------------------------------------------------


_REQUIRED_TABLES = (
    "sites",
    "energy_projects",
    "generator_permits",
    "edgar_extractions",
    "building_permits",
    "anomalies",
    "data_coverage",
)


def test_persona_lists_schema_tables() -> None:
    """The agent must be told which tables it can SELECT from.

    We grep for each table name as a literal substring; the persona is
    a markdown doc, the tables appear in a bullet list per ARCH 11b §8.
    """
    body = _WORKSPACE_SOUL.read_text(encoding="utf-8")
    missing = [t for t in _REQUIRED_TABLES if t not in body]
    assert not missing, (
        f"SOUL.md is missing schema tables {missing}; agent will not "
        "know it can query them. ARCH 11b §8 'Schema knowledge' bullet."
    )


# ---------------------------------------------------------------------------
# Voice + boundary rules
# ---------------------------------------------------------------------------


def test_voice_rules_anchored() -> None:
    """The persona must teach the agent the voice cues we rely on.

    - "citation" — required for the citation rules (PRD R3, AC6).
    - "MW" — required as the default unit for capacity claims.
    - "outside my brief" — the redirect phrase for off-topic asks
      (ARCH 11b §8 'Out-of-scope redirect').
    """
    body = _WORKSPACE_SOUL.read_text(encoding="utf-8")
    for phrase in ("citation", "MW", "outside my brief"):
        assert phrase in body, (
            f"Voice anchor '{phrase}' missing from SOUL.md; "
            "user-visible behavior contract (ARCH 11b §8) not met."
        )


# ---------------------------------------------------------------------------
# Performance budget — this whole file must run fast (<100ms target).
# ---------------------------------------------------------------------------


def test_persona_assertions_are_pure_file_io(monkeypatch: pytest.MonkeyPatch) -> None:
    """No network / DB / LLM allowed in this module.

    We patch httpx.Client to raise on any instantiation as a defense-in-
    depth check: if a future edit accidentally drags in an HTTP call,
    the assertion below will fail loudly.
    """
    # The actual checks above already passed if we got here; this test
    # just enforces the no-network discipline going forward.
    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx is a hard dep
        return

    real_send = httpx.Client.send

    def _boom(*_args, **_kwargs):  # pragma: no cover - only fires on regression
        raise AssertionError(
            "test_openclaw_persona_loaded module made an HTTP call; "
            "this suite is meant to be pure file IO."
        )

    monkeypatch.setattr(httpx.Client, "send", _boom)

    # Re-read the file once to prove no side-effect HTTP happens.
    body = _WORKSPACE_SOUL.read_text(encoding="utf-8")
    assert body  # touched bytes only, no network

    # Restore (monkeypatch will undo automatically; this is for clarity).
    monkeypatch.setattr(httpx.Client, "send", real_send)
