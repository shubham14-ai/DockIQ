"""Stats collector: one sampling thread per running container, started and
stopped in lockstep with the Docker event stream (start/stop/die/kill)."""
from __future__ import annotations

import logging
import threading

from agent.collectors import Config, now_rfc3339

log = logging.getLogger("dockiq.agent.stats")

STATS_INTERVAL = 5  # seconds


class StatsManager:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._lock = threading.Lock()
        self._stops: dict[str, threading.Event] = {}

    def start(self, container_id: str, name: str) -> None:
        with self._lock:
            if container_id in self._stops:
                return  # already sampling
            stop = threading.Event()
            self._stops[container_id] = stop
        threading.Thread(
            target=self._sample_loop,
            args=(container_id, name, stop),
            name=f"stats-{container_id[:12]}",
            daemon=True,
        ).start()

    def stop(self, container_id: str) -> None:
        with self._lock:
            stop = self._stops.pop(container_id, None)
        if stop is not None:
            stop.set()

    def stop_all(self) -> None:
        with self._lock:
            stops = list(self._stops.values())
            self._stops.clear()
        for stop in stops:
            stop.set()

    def _sample_loop(self, container_id: str, name: str, stop: threading.Event) -> None:
        self._sample(container_id, name)  # first sample immediately
        while not stop.wait(STATS_INTERVAL):
            self._sample(container_id, name)

    def _sample(self, container_id: str, name: str) -> None:
        try:
            v = self._cfg.docker.api.stats(container_id, stream=False)
        except Exception:  # noqa: BLE001
            # Container likely exited between event and sample; the stop event
            # (or next discovery reconcile) cleans this thread up. Skip this tick.
            return

        sample = _to_sample(container_id, name, v)
        self._cfg.publish(
            "metrics",
            {
                "tenant_id": self._cfg.tenant_id,
                "host_id": self._cfg.host_id,
                "ts": now_rfc3339(),
                "samples": [sample],
            },
        )


def _to_sample(container_id: str, name: str, v: dict) -> dict:
    mem = v.get("memory_stats") or {}
    sample = {
        "container_id": container_id,
        "name": name,
        "cpu_ratio": _cpu_ratio(v),
        "mem_bytes": mem.get("usage", 0) or 0,
        "mem_limit_bytes": mem.get("limit", 0) or 0,
        "net_rx_bytes": 0,
        "net_tx_bytes": 0,
        "blk_read_bytes": 0,
        "blk_write_bytes": 0,
    }

    for net in (v.get("networks") or {}).values():
        sample["net_rx_bytes"] += net.get("rx_bytes", 0) or 0
        sample["net_tx_bytes"] += net.get("tx_bytes", 0) or 0

    blkio = v.get("blkio_stats") or {}
    for entry in blkio.get("io_service_bytes_recursive") or []:
        op = (entry.get("op") or "").lower()
        val = entry.get("value", 0) or 0
        if op == "read":
            sample["blk_read_bytes"] += val
        elif op == "write":
            sample["blk_write_bytes"] += val

    return sample


def _cpu_ratio(v: dict) -> float:
    """CPU usage as a fraction of one core (0..N cores), following the standard
    ``docker stats`` formula."""
    cpu = v.get("cpu_stats") or {}
    precpu = v.get("precpu_stats") or {}
    cpu_usage = (cpu.get("cpu_usage") or {}).get("total_usage", 0) or 0
    pre_usage = (precpu.get("cpu_usage") or {}).get("total_usage", 0) or 0
    cpu_delta = cpu_usage - pre_usage
    system_delta = (cpu.get("system_cpu_usage", 0) or 0) - (precpu.get("system_cpu_usage", 0) or 0)
    if cpu_delta <= 0 or system_delta <= 0:
        return 0.0

    online = cpu.get("online_cpus") or 0
    if not online:
        online = len((cpu.get("cpu_usage") or {}).get("percpu_usage") or [])
    if not online:
        online = 1
    return (cpu_delta / system_delta) * online
