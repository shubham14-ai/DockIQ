"""Logs collector: one log-tailing thread per running container, started and
stopped in lockstep with the Docker event stream.

Each container gets a *reader* thread (follows the container's combined
stdout/stderr from "now", splits lines, pushes them onto a queue) and a *batch*
thread (drains the queue, flushing ``logs`` payloads every ``FLUSH_INTERVAL`` or
``FLUSH_MAX_LINES``, whichever comes first) — mirroring the Go agent's
lineCh + batchAndPublish design.
"""
from __future__ import annotations

import logging
import queue
import re
import threading
import time

from agent.collectors import Config, now_rfc3339

log = logging.getLogger("dockiq.agent.logs")

FLUSH_INTERVAL = 1.0  # seconds
FLUSH_MAX_LINES = 100

_SENTINEL = object()
# RFC3339 / RFC3339Nano leading timestamp, e.g. 2024-01-02T15:04:05.123456789Z.
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


class LogsManager:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._lock = threading.Lock()
        self._stops: dict[str, threading.Event] = {}

    def start(self, container_id: str, name: str) -> None:
        with self._lock:
            if container_id in self._stops:
                return  # already tailing
            stop = threading.Event()
            self._stops[container_id] = stop
        threading.Thread(
            target=self._tail,
            args=(container_id, name, stop),
            name=f"logs-{container_id[:12]}",
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

    def _tail(self, container_id: str, name: str, stop: threading.Event) -> None:
        try:
            container = self._cfg.docker.containers.get(container_id)
            # docker-py's logs() does not support demux; it yields combined
            # stdout+stderr byte chunks. We label the merged stream "stdout".
            stream = container.logs(
                stdout=True,
                stderr=True,
                follow=True,
                timestamps=True,
                since=int(time.time()),
                stream=True,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("open stream for %s: %s", container_id, exc)
            return

        line_q: queue.Queue = queue.Queue(maxsize=1024)

        reader = threading.Thread(
            target=self._read_stream,
            args=(stream, line_q, stop),
            name=f"logsrd-{container_id[:12]}",
            daemon=True,
        )
        reader.start()

        self._batch_and_publish(container_id, name, line_q, stop)

    def _read_stream(self, stream, line_q: queue.Queue, stop: threading.Event) -> None:
        buffer = b""
        try:
            for chunk in stream:
                if stop.is_set():
                    break
                if not chunk:
                    continue
                buffer += chunk
                *lines, buffer = buffer.split(b"\n")
                for raw in lines:
                    line_q.put(_parse_line(raw.decode("utf-8", "replace"), "stdout"))
        except Exception as exc:  # noqa: BLE001
            log.debug("log stream ended: %s", exc)
        finally:
            line_q.put(_SENTINEL)

    def _batch_and_publish(self, container_id, name, line_q, stop) -> None:
        buf: list[dict] = []

        def flush() -> None:
            if not buf:
                return
            self._cfg.publish(
                "logs",
                {
                    "tenant_id": self._cfg.tenant_id,
                    "host_id": self._cfg.host_id,
                    "container_id": container_id,
                    "name": name,
                    "lines": list(buf),
                },
            )
            buf.clear()

        while True:
            try:
                item = line_q.get(timeout=FLUSH_INTERVAL)
            except queue.Empty:
                flush()
                if stop.is_set():
                    return
                continue
            if item is _SENTINEL:
                flush()
                return
            buf.append(item)
            if len(buf) >= FLUSH_MAX_LINES:
                flush()


def _parse_line(raw: str, stream: str) -> dict:
    """Split a Docker timestamped log line ("<RFC3339Nano ts> <msg>") into its
    parts, falling back to the current time if the line is malformed."""
    ts, sep, msg = raw.partition(" ")
    if not sep or not _TS_RE.match(ts):
        return {"ts": now_rfc3339(), "stream": stream, "message": raw}
    return {"ts": ts, "stream": stream, "message": msg}
