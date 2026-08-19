"""Health payload helper: published whenever a container's Docker healthcheck
status transitions (derived from the ``health_status`` Docker event; see
events.py)."""
from __future__ import annotations

from agent.collectors import Config


def publish_health(cfg: Config, container_id: str, name: str, status: str, at: str) -> None:
    cfg.publish(
        "health",
        {
            "tenant_id": cfg.tenant_id,
            "host_id": cfg.host_id,
            "container_id": container_id,
            "name": name,
            "status": status,  # healthy|unhealthy|none
            "at": at,
        },
    )
