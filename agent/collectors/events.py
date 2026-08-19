"""Events collector: subscribes to the Docker container event stream, translates
events into the protocol's ``events`` (and, for health transitions, ``health``)
payloads, and drives per-container start/stop of the stats and logs collectors
as containers churn.

On disconnect it retries with a short backoff rather than exiting, so a transient
Docker daemon restart doesn't permanently blind the agent.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from agent.collectors import Config
from agent.collectors.health import publish_health

log = logging.getLogger("dockiq.agent.events")

# Raw Docker event actions the protocol wants surfaced as-is (health_status is
# handled separately below, since Docker reports it as "health_status: <status>").
_INTERESTING = {"create", "start", "stop", "die", "kill", "oom"}


def run_events(cfg: Config, stats_mgr, logs_mgr, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            _watch_events(cfg, stats_mgr, logs_mgr, stop)
        except Exception as exc:  # noqa: BLE001
            log.error("stream error: %s (retrying in 5s)", exc)
        stop.wait(5)


def _watch_events(cfg: Config, stats_mgr, logs_mgr, stop: threading.Event) -> None:
    # decode=True yields dicts; the generator blocks, so we periodically break
    # via the daemon thread + stop flag checked on each message.
    stream = cfg.docker.events(filters={"type": "container"}, decode=True)
    try:
        for msg in stream:
            if stop.is_set():
                return
            _handle_event(cfg, stats_mgr, logs_mgr, msg)
    finally:
        try:
            stream.close()
        except Exception:  # noqa: BLE001
            pass


def _handle_event(cfg: Config, stats_mgr, logs_mgr, msg: dict) -> None:
    actor = msg.get("Actor") or {}
    attrs = actor.get("Attributes") or {}
    container_id = actor.get("ID", "")
    name = (attrs.get("name") or "").lstrip("/")

    time_nano = msg.get("timeNano", 0)
    occurred_at = datetime.fromtimestamp(
        time_nano / 1e9, tz=timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    action = msg.get("Action", "")
    kind, sep, status = action.partition(":")
    if sep and kind.strip() == "health_status":
        status = status.strip()
        publish_health(cfg, container_id, name, status, occurred_at)
        _publish_event(cfg, container_id, name, "health_status", None, occurred_at, attrs)
        return

    if action not in _INTERESTING:
        return

    exit_code = None
    if action == "die":
        raw = attrs.get("exitCode")
        if raw is not None:
            try:
                exit_code = int(raw)
            except ValueError:
                exit_code = None

    _publish_event(cfg, container_id, name, action, exit_code, occurred_at, attrs)

    if action == "start":
        stats_mgr.start(container_id, name)
        logs_mgr.start(container_id, name)
    elif action in ("stop", "die", "kill"):
        stats_mgr.stop(container_id)
        logs_mgr.stop(container_id)


def _publish_event(cfg, container_id, name, typ, exit_code, occurred_at, attrs) -> None:
    payload = {
        "tenant_id": cfg.tenant_id,
        "host_id": cfg.host_id,
        "container_id": container_id,
        "name": name,
        "type": typ,  # create|start|stop|die|kill|oom|health_status
        "time": occurred_at,
        "attributes": attrs,
    }
    if exit_code is not None:
        payload["exit_code"] = exit_code
    cfg.publish("events", payload)


def seed_running(cfg: Config, stats_mgr, logs_mgr) -> None:
    """Start stats/logs collection for every container already running when the
    agent boots (the event stream only reports future transitions)."""
    try:
        summaries = cfg.docker.api.containers()  # running only
    except Exception as exc:  # noqa: BLE001
        log.error("seed running containers: %s", exc)
        return
    for s in summaries:
        names = s.get("Names") or []
        name = (names[0] if names else "").lstrip("/")
        stats_mgr.start(s["Id"], name)
        logs_mgr.start(s["Id"], name)
