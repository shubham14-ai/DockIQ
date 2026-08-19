from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

import nats
from nats.aio.client import Client as NATS
from nats.aio.msg import Msg

from app.core.config import settings

log = logging.getLogger("dockiq.bus")

MessageHandler = Callable[[Msg], Awaitable[None]]


class NatsBus:
    """Thin wrapper over the NATS client.

    Phase 0 uses core NATS pub/sub (heartbeats are transient — losing one is
    harmless). Durable JetStream streams arrive with the Phase 1 event engines.
    """

    def __init__(self) -> None:
        self._nc: NATS | None = None

    @property
    def is_connected(self) -> bool:
        return self._nc is not None and self._nc.is_connected

    async def connect(self) -> None:
        self._nc = await nats.connect(
            settings.nats_url,
            name="dockiq-backend",
            max_reconnect_attempts=-1,
            reconnect_time_wait=2,
        )
        log.info("connected to NATS at %s", settings.nats_url)

    async def subscribe(self, subject: str, handler: MessageHandler) -> None:
        if self._nc is None:
            raise RuntimeError("NATS not connected")
        await self._nc.subscribe(subject, cb=handler)
        log.info("subscribed to %s", subject)

    async def publish(self, subject: str, data: dict) -> None:
        if self._nc is None:
            raise RuntimeError("NATS not connected")
        await self._nc.publish(subject, json.dumps(data).encode())

    async def request(self, subject: str, data: dict, timeout: float = 20.0) -> dict:
        """Request/reply — used to send commands to agents and await the result."""
        if self._nc is None:
            raise RuntimeError("NATS not connected")
        msg = await self._nc.request(
            subject, json.dumps(data).encode(), timeout=timeout
        )
        return json.loads(msg.data.decode())

    async def close(self) -> None:
        if self._nc is not None:
            await self._nc.drain()
            self._nc = None


# Module-level singleton used across the app.
bus = NatsBus()
