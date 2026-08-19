"""Loki HTTP client: push log streams + LogQL query_range."""
from __future__ import annotations

import logging

import httpx

from app.core.config import settings

log = logging.getLogger("dockiq.store.loki")


class LokiClient:
    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (base_url or settings.loki_url).rstrip("/")

    async def push(self, streams: list[dict]) -> None:
        """POST ``streams`` (each ``{"stream": {...labels}, "values": [[ns_ts, line], ...]}``)."""
        if not streams:
            return
        url = f"{self._base_url}/loki/api/v1/push"
        body = {"streams": streams}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=body)
                resp.raise_for_status()
        except Exception:  # noqa: BLE001 — store may be unavailable, don't crash the consumer
            log.exception("failed to push %d log stream(s) to Loki", len(streams))

    async def query_range(
        self, logql: str, start: str | None = None, end: str | None = None, limit: int = 100
    ) -> dict:
        url = f"{self._base_url}/loki/api/v1/query_range"
        params: dict = {"query": logql, "limit": limit}
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
        except Exception:  # noqa: BLE001
            log.exception("Loki query_range failed: %s", logql)
            return {"status": "error", "error": "query_range failed"}


# Module-level singleton used across the app.
loki = LokiClient()
