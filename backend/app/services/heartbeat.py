from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from nats.aio.msg import Msg
from sqlalchemy import update

from app.bus.nats_bus import bus
from app.core.config import settings
from app.store.db import SessionLocal
from app.store.models import Host

log = logging.getLogger("dockiq.heartbeat")

# Wildcard: dockiq.<tenant>.<host_id>.heartbeat
HEARTBEAT_SUBJECT = "dockiq.*.*.heartbeat"


async def _on_heartbeat(msg: Msg) -> None:
    try:
        data = json.loads(msg.data.decode())
    except (ValueError, UnicodeDecodeError):
        log.warning("dropping malformed heartbeat on %s", msg.subject)
        return

    host_id = data.get("host_id")
    if not host_id:
        return

    async with SessionLocal() as session:
        host = await session.get(Host, host_id)
        if host is None:
            # Heartbeat for an unknown host (e.g. DB reset). Ignore in Phase 0.
            log.warning("heartbeat from unknown host %s", host_id)
            return
        host.agent_status = "online"
        host.last_heartbeat = datetime.now(timezone.utc)
        host.agent_version = data.get("agent_version") or host.agent_version
        host.os = data.get("os") or host.os
        host.arch = data.get("arch") or host.arch
        host.docker_version = data.get("docker_version") or host.docker_version
        await session.commit()

    log.info("heartbeat from host %s", host_id)


async def start_heartbeat_consumer() -> None:
    await bus.subscribe(HEARTBEAT_SUBJECT, _on_heartbeat)


async def offline_sweeper() -> None:
    """Mark hosts offline when their heartbeat goes stale."""
    interval = 10
    while True:
        try:
            await asyncio.sleep(interval)
            cutoff = datetime.now(timezone.utc) - timedelta(
                seconds=settings.heartbeat_offline_seconds
            )
            async with SessionLocal() as session:
                result = await session.execute(
                    update(Host)
                    .where(Host.agent_status == "online", Host.last_heartbeat < cutoff)
                    .values(agent_status="offline")
                )
                if result.rowcount:
                    log.info("marked %d host(s) offline", result.rowcount)
                await session.commit()
        except asyncio.CancelledError:
            break
        except Exception:  # keep the sweeper alive
            log.exception("offline sweeper iteration failed")
