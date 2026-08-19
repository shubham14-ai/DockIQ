"""VictoriaMetrics HTTP client: prometheus-exposition import + PromQL query."""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

log = logging.getLogger("dockiq.store.vm")


class VictoriaMetricsClient:
    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (base_url or settings.vm_url).rstrip("/")

    async def import_prometheus(self, lines: list[str]) -> None:
        """POST prometheus exposition ``lines`` to VM's import endpoint."""
        if not lines:
            return
        body = "\n".join(lines) + "\n"
        url = f"{self._base_url}/api/v1/import/prometheus"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, content=body.encode("utf-8"))
                resp.raise_for_status()
        except Exception:  # noqa: BLE001 — store may be unavailable, don't crash the consumer
            log.exception("failed to import %d prometheus line(s) to VM", len(lines))

    async def query(self, promql: str) -> dict:
        url = f"{self._base_url}/api/v1/query"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params={"query": promql})
                resp.raise_for_status()
                return resp.json()
        except Exception:  # noqa: BLE001
            log.exception("VM query failed: %s", promql)
            return {"status": "error", "error": "query failed"}

    async def query_range(self, promql: str, start: str, end: str, step: str) -> dict:
        url = f"{self._base_url}/api/v1/query_range"
        params = {"query": promql, "start": start, "end": end, "step": step}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
        except Exception:  # noqa: BLE001
            log.exception("VM query_range failed: %s", promql)
            return {"status": "error", "error": "query_range failed"}


# Module-level singleton used across the app.
vm = VictoriaMetricsClient()
