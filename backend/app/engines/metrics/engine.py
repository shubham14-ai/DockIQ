"""Metrics Engine: `metrics` payloads → Prometheus exposition lines → VictoriaMetrics.

See docs/phase1-agent-protocol.md (`metrics` payload) and
docs/engines/04-metrics-engine.md for the series/labels this emits.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.bus.subjects import wildcard
from app.engines.base import BaseEngine
from app.store.vm import vm


def _escape_label_value(value: str) -> str:
    """Escape a label value for Prometheus exposition format."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


def _parse_ts_ms(ts: str | None) -> int:
    """Parse an ISO-8601 timestamp (as sent by the agent) into epoch millis.

    Falls back to "now" if ``ts`` is missing or unparseable so a sample is
    never silently dropped.
    """
    if ts:
        try:
            normalized = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except (ValueError, TypeError):
            pass
    return int(datetime.now(timezone.utc).timestamp() * 1000)


class MetricsEngine(BaseEngine):
    name = "metrics"

    def subjects(self) -> list[str]:
        return [wildcard("metrics")]

    async def handle(self, subject: str, data: dict) -> None:
        tenant = data.get("tenant_id", "")
        host_id = data.get("host_id", "")
        ts_ms = _parse_ts_ms(data.get("ts"))
        samples = data.get("samples") or []

        lines: list[str] = []
        for sample in samples:
            lines.extend(self._sample_lines(tenant, host_id, ts_ms, sample))

        if lines:
            await vm.import_prometheus(lines)

    def _sample_lines(
        self, tenant: str, host_id: str, ts_ms: int, sample: dict
    ) -> list[str]:
        container_id = sample.get("container_id", "")
        container = sample.get("name", "")

        label_pairs = {
            "tenant": tenant,
            "host_id": host_id,
            "container_id": container_id,
            "container": container,
        }
        # Optional labels when available (Classification enrichment, not present
        # in the MVP agent payload — included only if the sample carries them).
        for optional in ("role", "tech"):
            if sample.get(optional):
                label_pairs[optional] = sample[optional]

        label_str = ",".join(
            f'{key}="{_escape_label_value(value)}"' for key, value in label_pairs.items()
        )

        cpu_ratio = sample.get("cpu_ratio")
        mem_bytes = sample.get("mem_bytes")
        mem_limit_bytes = sample.get("mem_limit_bytes")
        net_rx_bytes = sample.get("net_rx_bytes")
        net_tx_bytes = sample.get("net_tx_bytes")
        blk_read_bytes = sample.get("blk_read_bytes")
        blk_write_bytes = sample.get("blk_write_bytes")

        lines: list[str] = []

        def emit(metric: str, value) -> None:
            if value is None:
                return
            lines.append(f"{metric}{{{label_str}}} {value} {ts_ms}")

        emit("dockiq_cpu_usage_ratio", cpu_ratio)
        emit("dockiq_mem_usage_bytes", mem_bytes)
        emit("dockiq_mem_limit_bytes", mem_limit_bytes)

        if mem_bytes is not None and mem_limit_bytes:
            try:
                if float(mem_limit_bytes) > 0:
                    mem_ratio = float(mem_bytes) / float(mem_limit_bytes)
                    emit("dockiq_mem_usage_ratio", mem_ratio)
            except (TypeError, ValueError, ZeroDivisionError):
                pass

        emit("dockiq_net_rx_bytes", net_rx_bytes)
        emit("dockiq_net_tx_bytes", net_tx_bytes)
        emit("dockiq_blk_read_bytes", blk_read_bytes)
        emit("dockiq_blk_write_bytes", blk_write_bytes)
        emit("dockiq_container_up", 1)

        return lines
