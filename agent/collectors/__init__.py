"""DockIQ agent collectors (Phase 1).

Each collector publishes JSON payloads to NATS per
``docs/phase1-agent-protocol.md``: discovery, events, stats, logs and health.

This package is the Python port of the original Go agent. It keeps the same
subjects, payload shapes and behaviour, so the control-plane backend needs no
changes.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import docker

from agent.nats_publisher import NatsPublisher

log = logging.getLogger("dockiq.agent.collectors")


@dataclass
class Config:
    """Shared wiring every collector needs: the Docker SDK client, the NATS
    publisher, and the tenant/host identity handed back by enrollment."""

    docker: docker.DockerClient
    nats: NatsPublisher
    tenant_id: str
    host_id: str

    def subject(self, kind: str) -> str:
        """Build a ``dockiq.<tenant_id>.<host_id>.<kind>`` subject."""
        return f"dockiq.{self.tenant_id}.{self.host_id}.{kind}"

    def publish(self, kind: str, payload: Any) -> None:
        """Marshal ``payload`` to JSON and publish it, logging (never raising)
        on failure so a single bad publish can't take down the agent."""
        try:
            data = json.dumps(payload).encode("utf-8")
        except (TypeError, ValueError) as exc:
            log.error("marshal %s payload: %s", kind, exc)
            return
        try:
            self.nats.publish(self.subject(kind), data)
        except Exception as exc:  # noqa: BLE001 - resilience over strictness
            log.error("publish %s: %s", kind, exc)


def now_rfc3339() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Env var names that must be redacted per the protocol: *PASSWORD*, *SECRET*,
# *TOKEN*, *KEY*, *_DSN.
_REDACT_KEY = re.compile(r"(PASSWORD|SECRET|TOKEN|KEY|_DSN)", re.IGNORECASE)
# URLs carrying inline credentials, e.g. postgres://user:pass@host/db.
_CREDS_URL = re.compile(r"^[a-z][a-z0-9+.-]*://[^/@\s:]+:[^/@\s]+@", re.IGNORECASE)
_REDACTED = "***REDACTED***"


def redact_env(env: list[str] | None) -> dict[str, str]:
    """Turn a Docker ``KEY=VALUE`` env list into a map, redacting
    secret-looking values per the Phase 1 protocol."""
    out: dict[str, str] = {}
    for kv in env or []:
        key, sep, val = kv.partition("=")
        if not sep:
            out[kv] = ""
            continue
        if _REDACT_KEY.search(key) or _CREDS_URL.match(val):
            out[key] = _REDACTED
        else:
            out[key] = val
    return out


def run(cfg: Config, stop: threading.Event) -> None:
    """Start all Phase 1 collectors and block until ``stop`` is set.

    Resilient by design: an individual collector failing (docker socket
    hiccup, container disappearing mid-stream, etc.) is logged and does not
    bring down the others or the agent process.
    """
    # Imported here to avoid a circular import at module load.
    from agent.collectors import discovery, events, stats, logs

    stats_mgr = stats.StatsManager(cfg)
    logs_mgr = logs.LogsManager(cfg)

    # Seed churn-driven collectors with whatever is running right now; the
    # event stream only reports *future* transitions.
    events.seed_running(cfg, stats_mgr, logs_mgr)

    threads = [
        threading.Thread(
            target=discovery.run_discovery, args=(cfg, stop), name="discovery", daemon=True
        ),
        threading.Thread(
            target=events.run_events,
            args=(cfg, stats_mgr, logs_mgr, stop),
            name="events",
            daemon=True,
        ),
    ]
    for t in threads:
        t.start()

    stop.wait()
    stats_mgr.stop_all()
    logs_mgr.stop_all()
