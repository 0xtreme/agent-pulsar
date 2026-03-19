"""Centralized configuration for Agent Pulsar.

All configuration is loaded from environment variables with the AP_ prefix.
Copy .env.example to .env and fill in required values.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="AP_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # --- Required ---
    anthropic_api_key: str

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- PostgreSQL ---
    database_url: str = (
        "postgresql+asyncpg://agent_pulsar:agent_pulsar@localhost:5432/agent_pulsar"
    )

    # --- Supervisor ---
    supervisor_host: str = "0.0.0.0"
    supervisor_port: int = 8100

    # --- LLM Models ---
    decomposition_model: str = "claude-opus-4-0-20250514"
    classification_model: str = "claude-haiku-4-5-20250414"

    # --- OpenClaw Callback ---
    openclaw_webhook_url: str = "http://localhost:18789/hooks/agent"

    # --- Event Bus ---
    consumer_group: str = "agent-pulsar-supervisor"
    event_bus_poll_ms: int = 1000
    max_retries: int = 3


def get_settings() -> Settings:
    """Create and return a Settings instance (cached via lru_cache if needed)."""
    return Settings()
