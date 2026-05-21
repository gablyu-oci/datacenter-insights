"""
Application configuration via pydantic-settings.
Reads from backend/.env, environment variables, and defaults.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

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

    # Alpha Vantage (earnings call transcripts pipeline — migration 019)
    # Free tier is 25 calls/day. NEVER commit the key. Set env var
    # ALPHA_VANTAGE_API_KEY locally. EarningsTranscriptsAdapter raises a
    # clear error at init time when this is None.
    alpha_vantage_api_key: str | None = None

    # Mock data gate
    mock_data: int = 0

    # Llama Stack
    llama_stack_url: str = "https://llama-stack.ai-apps-ord.oci-incubations.com"

    # App
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    # Deployment environment marker. Read from the ENVIRONMENT env var
    # (set on production hosts). The `current_user_email` dependency in
    # routers/insights.py uses this to gate the dev-only "dev@local"
    # fallback when oauth2-proxy's X-Forwarded-Email header is absent —
    # so production deploys 401 instead of silently authenticating as a
    # synthetic identity. See docs/planning/save-and-history-per-user/.
    environment: str = "development"

    # ------------------------------------------------------------------
    # OpenClaw gateway settings (PRD 11a, ARCH 11b, ADDENDUM 11c, ARCH 15).
    # All chat / QA / synthesis traffic flows through the gateway. The
    # legacy in-process ToolLoopDriver lane and its `openclaw_enabled`
    # flag were removed in Phase 5-followup (ARCH 15).
    # ------------------------------------------------------------------
    openclaw_gateway_url: str = "http://localhost:7474"
    openclaw_gateway_token: str = ""  # OPENCLAW_GATEWAY_TOKEN env
    agent_tools_bearer: str = ""  # AGENT_TOOLS_BEARER env (Bearer the
    # OpenClaw plugins present on calls back into FastAPI)
    llama_stack_api_key: str = ""  # LLAMA_STACK_API_KEY env (used by
    # the OpenClaw provider config; FastAPI itself does not need it)
    openclaw_session_prefix: str = "agent:main:insight:"



settings = Settings()
