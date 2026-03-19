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

    # --- Vault (Phase 2) ---
    vault_url: str | None = None
    vault_token: str | None = None
    vault_mount_point: str = "secret"

    # --- Cold Tier Docker (Phase 2) ---
    docker_network: str = "agent-pulsar-net"
    cold_tier_mem_limit: str = "512m"
    cold_tier_cpu_quota: int = 50000

    # --- Token Broker (Phase 2) ---
    token_broker_secret: str = "dev-secret-change-me"
    token_broker_host: str = "0.0.0.0"
    token_broker_port: int = 8101
    token_broker_url: str = "http://localhost:8101"
    default_token_ttl_seconds: int = 300

    # --- Config Portal (Phase 2) ---
    config_portal_host: str = "0.0.0.0"
    config_portal_port: int = 8102
    config_portal_base_url: str = "http://localhost:8102"
    onboarding_link_ttl_seconds: int = 600


def get_settings() -> Settings:
    """Create and return a Settings instance (cached via lru_cache if needed)."""
    return Settings()
