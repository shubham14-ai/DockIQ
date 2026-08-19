"""DockIQ agent — Phase 1 (Python).

Responsibilities: enroll with the control plane over REST, publish a periodic
heartbeat over NATS, and run the Docker collectors (discovery, events, stats,
logs, health) documented in docs/phase1-agent-protocol.md and
docs/layers/01-agent.md. Command execution arrives in a later phase.
"""
from __future__ import annotations

import logging
import os
import platform
import signal
import socket
import threading
import time
from datetime import datetime, timezone

import docker
import requests

from agent import collectors
from agent.collectors import Config
from agent.nats_publisher import NatsPublisher

AGENT_VERSION = "0.0.1-phase1"
HEARTBEAT_INTERVAL = 5  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("dockiq.agent")


def env(key: str, default: str) -> str:
    return os.getenv(key) or default


def enroll(control_plane_url: str, host_name: str) -> dict:
    payload = {"host_name": host_name}
    join_token = os.getenv("DOCKIQ_JOIN_TOKEN")
    if join_token:
        payload["join_token"] = join_token
    resp = requests.post(
        f"{control_plane_url}/api/v1/agents/enroll",
        json=payload,
        timeout=10,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"enroll failed: {resp.status_code} {resp.reason}")
    return resp.json()


def main() -> None:
    control_plane_url = env("CONTROL_PLANE_URL", "http://localhost:8080")
    host_name = env("HOST_NAME", "") or socket.gethostname()
    nats_override = env("NATS_URL", "")

    log.info(
        "dockiq-agent %s starting (control plane=%s host=%s)",
        AGENT_VERSION,
        control_plane_url,
        host_name,
    )

    # Enroll, retrying until the control plane is reachable.
    while True:
        try:
            reg = enroll(control_plane_url, host_name)
            break
        except Exception as exc:  # noqa: BLE001
            log.warning("enroll error: %s (retrying in 5s)", exc)
            time.sleep(5)
    log.info("enrolled: host_id=%s tenant=%s", reg["host_id"], reg["tenant_id"])

    nats_url = nats_override or reg["nats_url"]
    heartbeat_subject = reg["heartbeat_subject"]

    publisher = NatsPublisher(nats_url)
    try:
        publisher.connect()
    except Exception as exc:  # noqa: BLE001
        log.error("nats connect (%s): %s", nats_url, exc)
        raise SystemExit(1)
    log.info("connected to NATS %s; heartbeat subject=%s", nats_url, heartbeat_subject)

    stop = threading.Event()

    def _handle_signal(signum, _frame):
        log.info("shutting down (signal %s)", signum)
        stop.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Docker collectors talk to the daemon over the socket mounted into the
    # container. A failure here (socket not mounted, daemon unreachable) is
    # logged but not fatal — heartbeat and enrollment keep working so the host
    # still shows up as online.
    try:
        docker_client = docker.from_env()
        docker_client.ping()
    except Exception as exc:  # noqa: BLE001
        log.warning("docker client init failed, collectors disabled: %s", exc)
    else:
        log.info("docker client ready; starting collectors")
        cfg = Config(
            docker=docker_client,
            nats=publisher,
            tenant_id=reg["tenant_id"],
            host_id=reg["host_id"],
        )
        threading.Thread(
            target=collectors.run, args=(cfg, stop), name="collectors", daemon=True
        ).start()

        # Command executor (Phases 5-6): serve restart/stop/start/pull/recreate
        # requests from the control plane on the commands subject.
        from agent.commands import make_handler

        commands_subject = f"dockiq.{reg['tenant_id']}.{reg['host_id']}.commands"
        try:
            publisher.serve_requests(commands_subject, make_handler(docker_client))
            log.info("command executor listening on %s", commands_subject)
        except Exception as exc:  # noqa: BLE001
            log.warning("command executor failed to start: %s", exc)

    def send_heartbeat() -> None:
        hb = {
            "host_id": reg["host_id"],
            "agent_version": AGENT_VERSION,
            "os": platform.system().lower(),
            "arch": platform.machine(),
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        try:
            publisher.publish(heartbeat_subject, _json(hb))
        except Exception as exc:  # noqa: BLE001
            log.error("heartbeat publish error: %s", exc)

    send_heartbeat()  # beat immediately so the host shows online without delay
    while not stop.wait(HEARTBEAT_INTERVAL):
        send_heartbeat()

    publisher.close()


def _json(obj) -> bytes:
    import json

    return json.dumps(obj).encode("utf-8")


if __name__ == "__main__":
    main()
