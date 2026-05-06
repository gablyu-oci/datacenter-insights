"""
Application configuration via pydantic-settings.
Reads from backend/.env, environment variables, and defaults.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Pydantic-settings only exposes declared fields. Loading .env into os.environ
# too lets ad-hoc os.environ.get() lookups (e.g. tools/web_search.py reading
# BRAVE_SEARCH_API_KEY) see secrets without us declaring every key here.
load_dotenv(Path(__file__).parent / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://sit_app:changeme@localhost:5432/strategic_insights"
    db_echo: bool = False

    # CORS
    allowed_origins: str = '["http://localhost:5173"]'

    @property
    def cors_origins(self) -> List[str]:
        try:
            return json.loads(self.allowed_origins)
        except (json.JSONDecodeError, TypeError):
            return [self.allowed_origins]

    # EDGAR
    edgar_user_agent: str = "Datacenter Intelligence Platform research@oracle.com"

    # Mock data gate
    mock_data: int = 0

    # Llama Stack
    llama_stack_url: str = "https://llama-stack.ai-apps-ord.oci-incubations.com"

    # App
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    # ------------------------------------------------------------------
    # OpenClaw migration (PRD 11a, ARCH 11b, ADDENDUM 11c).
    # The chat path can be served either by the legacy ToolLoopDriver
    # (rollback target) or by the OpenClaw gateway forwarder. The flag
    # below picks which lane runs at request time. Defaults: 1 in dev,
    # 0 in prod; flip in environment / .env.
    # ------------------------------------------------------------------
    openclaw_enabled: int = 1
    openclaw_gateway_url: str = "http://localhost:7474"
    openclaw_gateway_token: str = ""  # OPENCLAW_GATEWAY_TOKEN env
    agent_tools_bearer: str = ""  # AGENT_TOOLS_BEARER env (Bearer the
    # OpenClaw plugins present on calls back into FastAPI)
    llama_stack_api_key: str = ""  # LLAMA_STACK_API_KEY env (used by
    # the OpenClaw provider config; FastAPI itself does not need it)
    openclaw_session_prefix: str = "agent:main:insight:"

    # ------------------------------------------------------------------
    # Phase 2 (PRD/ARCH 14) — agentic synthesis dispatcher flag.
    # `agentic` (default) routes the orchestrator's synthesis phase
    # through `run_agentic_synthesis` (OpenClaw + MCP write-tools).
    # `legacy` keeps the V1 `_phase_hypothesize_iter` +
    # `_phase_verify_and_synthesize_iter` path (rollback target during
    # Phases 2-4; flag is removed in Phase 5).
    #     env: SYNTHESIS_MODE
    # ------------------------------------------------------------------
    synthesis_mode: Literal["legacy", "agentic"] = "agentic"

    # Phase 2 / FR-X.5 — relaxed token ceiling for the agentic loop. The
    # legacy module-level constant in hypothesizer.py stays at 30K (only
    # used by `synthesize_insights` which Phase 5 deletes); new code reads
    # this setting instead.
    hypothesizer_token_ceiling: int = 80_000


settings = Settings()
