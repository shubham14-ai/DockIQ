from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend configuration, populated from environment variables.

    Field names map case-insensitively to env vars (e.g. ``database_url`` <-
    ``DATABASE_URL``).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "DockIQ"
    version: str = "0.0.1-phase0"
    api_prefix: str = "/api/v1"

    # Storage / bus
    database_url: str = "postgresql+asyncpg://dockiq:dockiq@postgres:5432/dockiq"
    vm_url: str = "http://victoriametrics:8428"
    loki_url: str = "http://loki:3100"
    nats_url: str = "nats://nats:4222"

    # Grafana (Dashboard Generator, Phase 3)
    grafana_url: str = "http://grafana:3000"
    grafana_user: str = "admin"
    grafana_password: str = "admin"
    # Address handed to agents at enrollment (must be reachable *by the agent*).
    nats_advertise_url: str = "nats://nats:4222"

    # Tenancy / liveness
    default_tenant: str = "default"
    heartbeat_offline_seconds: int = 30

    # Auth / RBAC (Phase 7)
    auth_enabled: bool = True
    jwt_secret: str = "dev-insecure-change-me"
    jwt_expire_minutes: int = 720
    # Bootstrap admin (created on first start if no users exist).
    admin_username: str = "admin"
    admin_password: str = "admin"
    # Agents must present this token to enroll (empty = enrollment open, dev only).
    agent_join_token: str = ""

    # Diagnostic Query Agent (Engine 11) — Claude-powered.
    anthropic_api_key: str = ""
    diagnostic_model: str = "claude-opus-5"
    diagnostic_max_iterations: int = 8

    @property
    def diagnostic_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


settings = Settings()
