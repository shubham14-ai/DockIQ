"""Logging Engine: `logs` payloads → Loki push streams.

See docs/phase1-agent-protocol.md (`logs` payload) and
docs/engines/05-logging-engine.md for the label convention.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.bus.subjects import wildcard
from app.engines.base import BaseEngine
from app.store.loki import loki


def _parse_ts_ns(ts: str | None) -> int:
    """Parse an ISO-8601 timestamp into epoch nanoseconds (Loki's line format).

    Falls back to "now" if ``ts`` is missing or unparseable so a line is
    never silently dropped.
    """
    if ts:
        try:
            normalized = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1_000_000_000)
        except (ValueError, TypeError):
            pass
    return int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)


class LoggingEngine(BaseEngine):
    name = "logging"

    def subjects(self) -> list[str]:
        return [wildcard("logs")]

    async def handle(self, subject: str, data: dict) -> None:
        tenant = data.get("tenant_id", "")
        host_id = data.get("host_id", "")
        container_id = data.get("container_id", "")
        container = data.get("name", "")
        raw_lines = data.get("lines") or []

        # Group lines into one stream per (container_id, stream) as required.
        grouped: dict[str, list[list[str]]] = {}
        for line in raw_lines:
            stream = line.get("stream", "stdout")
            message = line.get("message", "")
            ts_ns = _parse_ts_ns(line.get("ts"))
            grouped.setdefault(stream, []).append([str(ts_ns), message])

        streams: list[dict] = []
        for stream, values in grouped.items():
            # Loki requires values sorted by timestamp within a stream.
            values.sort(key=lambda v: int(v[0]))
            streams.append(
                {
                    "stream": {
                        "tenant": tenant,
                        "host_id": host_id,
                        "container_id": container_id,
                        "container": container,
                        "stream": stream,
                    },
                    "values": values,
                }
            )

        if streams:
            await loki.push(streams)
