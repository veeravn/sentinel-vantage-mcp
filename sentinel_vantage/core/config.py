"""Central configuration.

All settings load from environment variables prefixed ``SV_`` (or a local ``.env``).
Secrets (provider API keys) live here and are never returned through MCP tools.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SV_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"

    # Storage
    postgres_dsn: str = "postgresql://sentinel:sentinel@localhost:5432/sentinel"
    redis_url: str = "redis://localhost:6379/0"

    # Market-data provider
    provider_name: str = "polygon"
    polygon_api_key: str = ""
    # Recorded as feed provenance on every bar and score.
    feed_mode: Literal["delayed", "realtime"] = "delayed"

    # MCP server (streamable-http transport)
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8080

    @property
    def feed_label(self) -> str:
        """Human-readable feed provenance stamped onto outputs."""
        return f"{self.provider_name}/{self.feed_mode}"


@lru_cache
def get_settings() -> Settings:
    """Process-wide singleton. Cached so env is read once per process."""
    return Settings()
