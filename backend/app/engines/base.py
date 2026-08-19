"""Engine contract. Every intelligence engine implements this interface.

Engines communicate only via the event bus + stores (never direct calls), so
they can later be extracted into separate services (see docs/layers/02-backend.md).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.bus.nats_bus import NatsBus


@dataclass
class EngineContext:
    bus: NatsBus


class BaseEngine:
    #: unique short name, e.g. "discovery"
    name: str = "engine"

    def __init__(self) -> None:
        self.log = logging.getLogger(f"dockiq.engine.{self.name}")
        self.ctx: EngineContext | None = None

    def subjects(self) -> list[str]:
        """NATS subjects this engine consumes (wildcards allowed).

        The registry subscribes each subject and calls ``handle`` with the
        decoded JSON payload. Return [] if the engine only runs periodic work.
        """
        return []

    async def start(self, ctx: EngineContext) -> None:
        """Called once at startup. Store ctx; launch any periodic tasks here."""
        self.ctx = ctx

    async def handle(self, subject: str, data: dict) -> None:
        """Handle one decoded message from a subscribed subject."""

    async def stop(self) -> None:
        """Called at shutdown. Cancel periodic tasks, flush state."""
