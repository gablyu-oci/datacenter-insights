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

    # Mock data gate
    mock_data: int = 0

    # Llama Stack
    llama_stack_url: str = "https://llama-stack.ai-apps-ord.oci-incubations.com"

    # App
    app_version: str = "0.1.0"
    log_level: str = "INFO"


settings = Settings()
