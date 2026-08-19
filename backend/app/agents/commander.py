"""Send commands to agents and await their result (Phases 5-6).

The agent subscribes to ``dockiq.<tenant>.<host_id>.commands`` and replies with
``{command_id, ok, error?, detail?}``. Every command is audited by the caller.
"""
from __future__ import annotations

import logging
import uuid

from app.bus.nats_bus import NatsBus

log = logging.getLogger("dockiq.commander")

VALID_ACTIONS = {"restart", "stop", "start", "pull", "recreate", "prune"}


async def send_command(
    bus: NatsBus,
    tenant_id: str,
    host_id: str,
    action: str,
    *,
    container_id: str | None = None,
    image: str | None = None,
    timeout_secs: int = 10,
    request_timeout: float = 30.0,
    extra: dict | None = None,
) -> dict:
    """Send one command to the agent on ``host_id`` and return its result.

    Returns ``{command_id, ok, error?, detail?}``. On transport failure (agent
    offline / no reply) returns ``{ok: False, error: ...}`` rather than raising.
    """
    if action not in VALID_ACTIONS:
        return {"ok": False, "error": f"invalid action: {action}"}

    command_id = uuid.uuid4().hex
    subject = f"dockiq.{tenant_id}.{host_id}.commands"
    payload = {
        "command_id": command_id,
        "action": action,
        "container_id": container_id,
        "image": image,
        "timeout_secs": timeout_secs,
    }
    # Action-specific fields (e.g. prune: targets, dry_run, dangling_only).
    if extra:
        payload.update(extra)
    try:
        result = await bus.request(subject, payload, timeout=request_timeout)
        log.info("command %s %s on %s -> ok=%s", action, (container_id or "")[:12], host_id, result.get("ok"))
        return result
    except Exception as exc:  # noqa: BLE001 — agent offline / timeout
        log.warning("command %s to host %s failed: %s", action, host_id, exc)
        return {"command_id": command_id, "ok": False, "error": f"transport: {exc}"}
