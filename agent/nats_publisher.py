"""A thread-safe NATS publisher.

The Go agent used goroutines; this Python port uses plain threads for the
collectors (docker-py is a blocking SDK, so a thread per stream reads
naturally). The NATS client (``nats-py``) is async-only, so we run one asyncio
event loop on a dedicated background thread and expose a synchronous, thread-safe
``publish`` that schedules the coroutine on that loop.
"""
from __future__ import annotations

import asyncio
import logging
import threading

import nats

log = logging.getLogger("dockiq.agent.nats")


class NatsPublisher:
    def __init__(self, url: str) -> None:
        self._url = url
        self._loop = asyncio.new_event_loop()
        self._nc: nats.NATS | None = None
        self._thread = threading.Thread(
            target=self._run_loop, name="nats-loop", daemon=True
        )

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def connect(self) -> None:
        """Start the loop thread and connect. Blocks until connected."""
        self._thread.start()
        fut = asyncio.run_coroutine_threadsafe(self._connect(), self._loop)
        fut.result()  # propagate connection errors to the caller

    async def _connect(self) -> None:
        self._nc = await nats.connect(
            self._url,
            name="dockiq-agent",
            max_reconnect_attempts=-1,
            reconnect_time_wait=2,
        )

    def publish(self, subject: str, data: bytes) -> None:
        """Publish ``data`` on ``subject``. Thread-safe; fire-and-forget."""
        if self._nc is None:
            raise RuntimeError("NATS not connected")
        asyncio.run_coroutine_threadsafe(
            self._nc.publish(subject, data), self._loop
        )

    def serve_requests(self, subject, handler) -> None:
        """Subscribe to ``subject`` and reply to each request.

        ``handler(req: dict) -> dict`` runs in a thread pool (so blocking Docker
        calls don't stall the event loop); its return value is JSON-encoded and
        published to the message's reply subject. Thread-safe.
        """
        import json

        async def _subscribe() -> None:
            async def _cb(msg) -> None:
                try:
                    req = json.loads(msg.data.decode()) if msg.data else {}
                except (ValueError, UnicodeDecodeError):
                    req = {}
                result = await self._loop.run_in_executor(None, handler, req)
                if msg.reply:
                    await self._nc.publish(msg.reply, json.dumps(result).encode())

            await self._nc.subscribe(subject, cb=_cb)

        asyncio.run_coroutine_threadsafe(_subscribe(), self._loop).result()

    def close(self) -> None:
        if self._nc is not None:
            fut = asyncio.run_coroutine_threadsafe(self._nc.drain(), self._loop)
            try:
                fut.result(timeout=5)
            except Exception as exc:  # noqa: BLE001
                log.warning("nats drain: %s", exc)
        self._loop.call_soon_threadsafe(self._loop.stop)
