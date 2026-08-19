"""LLM Observability Engine (Phase 4, Engine 10).

Registry loads this as ``app.engines.llm.engine:LLMEngine``. MVP scope:

- No NATS subjects consumed (periodic-only, like AnomalyEngine).
- Optionally scrapes a configurable list of vector-DB ``/metrics`` endpoints
  (Prometheus exposition text) and re-emits a lightweight
  ``dockiq_vectordb_up{service}`` gauge into VictoriaMetrics so the LLM
  dashboards have *something* to show even before deep vector-DB metric
  parsing lands. Defaults to an empty list, so this is a no-op unless
  configured via the ``DOCKIQ_LLM_VECTORDB_TARGETS`` env var (comma-separated
  ``service=url`` pairs, e.g. ``qdrant=http://qdrant:6333/metrics``).

Cross-network scrapes of a user's actual vector DB will often fail (network
policy, auth, wrong path) — that's expected and handled by logging + skipping
that target for the tick; it never kills the poll loop.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

log = logging.getLogger("dockiq.engine.llm")

POLL_INTERVAL_SECONDS = 60
_TARGETS_ENV_VAR = "DOCKIQ_LLM_VECTORDB_TARGETS"

from app.engines.base import BaseEngine, EngineContext  # noqa: E402


def _parse_targets(raw: str) -> dict[str, str]:
    """Parse ``service=url,service2=url2`` into a dict. Empty/invalid -> {}."""
    targets: dict[str, str] = {}
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        service, _, url = chunk.partition("=")
        service = service.strip()
        url = url.strip()
        if service and url:
            targets[service] = url
    return targets


class LLMEngine(BaseEngine):
    name = "llm"

    def __init__(self) -> None:
        super().__init__()
        self._poll_task: asyncio.Task | None = None
        # Default: empty -> engine is a no-op until configured.
        self._targets: dict[str, str] = _parse_targets(os.environ.get(_TARGETS_ENV_VAR, ""))

    def subjects(self) -> list[str]:
        # Periodic poller only — ingestion happens via the HTTP API, not the bus.
        return []

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def start(self, ctx: EngineContext) -> None:
        await super().start(ctx)
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._poll_task = None

    async def _poll_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — keep the poll loop alive
                self.log.exception("llm engine poll tick failed")

    # ------------------------------------------------------------------
    # per-tick work
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        if not self._targets:
            return  # nothing configured -> no-op, by design

        try:
            from app.store.vm import vm
        except Exception:  # noqa: BLE001
            self.log.debug("app.store.vm not available yet; skipping this tick")
            return

        lines: list[str] = []
        ts_ms = int(time.time() * 1000)

        for service, url in self._targets.items():
            up = await self._scrape_one(service, url)
            lines.append(f'dockiq_vectordb_up{{service="{service}"}} {1 if up else 0} {ts_ms}')

        if lines:
            try:
                await vm.import_prometheus(lines)
            except Exception:  # noqa: BLE001
                self.log.warning("failed to import vectordb_up gauges to VM", exc_info=True)

    async def _scrape_one(self, service: str, url: str) -> bool:
        """Attempt to fetch Prometheus text from a vector-DB metrics endpoint.

        Returns True if the endpoint responded successfully; False (and logs)
        on any failure. Cross-network scrapes commonly fail — that's fine.
        """
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                # We don't parse vendor-specific metric names yet (MVP); just
                # confirm we got Prometheus-looking text back.
                return bool(resp.text)
        except Exception:  # noqa: BLE001
            self.log.debug("vector-db scrape failed for %s (%s)", service, url, exc_info=True)
            return False
