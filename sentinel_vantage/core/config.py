"""Central configuration: all settings load from ``SV_``-prefixed env vars (or ``.env``)."""

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

    postgres_dsn: str = "postgresql://sentinel:sentinel@localhost:5432/sentinel"
    redis_url: str = "redis://localhost:6379/0"

    provider_name: str = "polygon"
    polygon_api_key: str = ""
    feed_mode: Literal["delayed", "realtime"] = "delayed"
    # 5 = free tier (5 req/min); 0 or large disables pacing on paid tiers.
    polygon_requests_per_minute: int = 5

    # SEC requires a descriptive UA: set SV_SEC_USER_AGENT to "Your Name your@email".
    sec_user_agent: str = "sentinel-vantage-mcp/0.1 (set SV_SEC_USER_AGENT)"

    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8080
    # Empty = auth disabled (local dev only); set before exposing on a network.
    mcp_auth_token: str = ""

    # get_status flags market data as stale when the newest bar is older than this many
    # calendar days (4 tolerates a weekend plus a holiday before the next backfill).
    data_stale_after_days: int = 4

    scoring_interval_seconds: int = 60
    backfill_days: int = 220  # calendar days (~150 trading days)
    trend_horizon: str = "1d"
    # Research fundamentals change slowly, so score them far less often than trend.
    research_scoring_interval_seconds: int = 3600
    research_strategies: list[str] = ["GARP"]

    alert_interval_seconds: int = 300

    # Scheduled daily backfill (scheduler process). Off by default; hour/minute are UTC.
    daily_backfill_enabled: bool = False
    daily_backfill_hour: int = 23
    daily_backfill_minute: int = 0
    daily_backfill_days: int = 7

    # Alert delivery. "none" (default) sends nothing; "email" uses SMTP; "webhook" POSTs
    # a Slack/Mattermost/Discord/ntfy-compatible message to SV_WEBHOOK_URL.
    notify_channel: Literal["none", "email", "webhook"] = "none"
    webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    smtp_starttls: bool = True

    # Agent LLM. "anthropic" uses the Messages API; "openai_compat" targets any OpenAI-style
    # /chat/completions server (default base URL is a local Ollama).
    llm_backend: Literal["anthropic", "openai_compat"] = "anthropic"
    llm_model: str = "claude-haiku-4-5-20251001"
    anthropic_api_key: str = ""
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = ""
    agent_max_steps: int = 8
    agent_max_total_tokens: int = 100_000

    # Agent-written alert notes (scheduler process). Off by default; needs an LLM backend.
    # Only alerts at or above the severity floor are investigated, capped per hour/cycle;
    # on timeout or failure the plain alert is sent unchanged.
    agent_alert_investigation_enabled: bool = False
    agent_alert_min_severity: Literal["info", "warning", "critical"] = "warning"
    agent_alert_max_per_hour: int = 6
    agent_alert_max_per_cycle: int = 3
    agent_alert_timeout_seconds: int = 90

    # Agent-written daily brief (scheduler process, Mon-Fri, UTC). Off by default; needs an
    # LLM backend and delivers via SV_NOTIFY_CHANNEL.
    daily_brief_enabled: bool = False
    daily_brief_hour: int = 13
    daily_brief_minute: int = 0

    @property
    def feed_label(self) -> str:
        return f"{self.provider_name}/{self.feed_mode}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
