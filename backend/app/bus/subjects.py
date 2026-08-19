"""NATS subject taxonomy. See docs/layers/04-event-streaming.md.

    dockiq.<tenant>.<host_id>.<kind>
"""
from __future__ import annotations

PREFIX = "dockiq"

# kinds
HEARTBEAT = "heartbeat"
EVENTS = "events"
METRICS = "metrics"
LOGS = "logs"
HEALTH = "health"
TOPOLOGY = "topology"
DISCOVERY = "discovery"  # full/partial inventory snapshots


def subject(tenant: str, host_id: str, kind: str) -> str:
    return f"{PREFIX}.{tenant}.{host_id}.{kind}"


def wildcard(kind: str) -> str:
    """Subscribe to a kind across all tenants/hosts: dockiq.*.*.<kind>."""
    return f"{PREFIX}.*.*.{kind}"
