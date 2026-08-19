"""Discovery collector: publishes a full container inventory snapshot on start
and every ``DISCOVERY_INTERVAL`` seconds thereafter (reconcile)."""
from __future__ import annotations

import logging
import threading

from agent.collectors import Config, redact_env

log = logging.getLogger("dockiq.agent.discovery")

DISCOVERY_INTERVAL = 30  # seconds


def run_discovery(cfg: Config, stop: threading.Event) -> None:
    discover_once(cfg)
    while not stop.wait(DISCOVERY_INTERVAL):
        discover_once(cfg)


def discover_once(cfg: Config) -> None:
    try:
        summaries = cfg.docker.api.containers(all=True)
    except Exception as exc:  # noqa: BLE001
        log.error("list containers: %s", exc)
        return

    containers = []
    for summary in summaries:
        try:
            containers.append(_inspect_container(cfg, summary))
        except Exception as exc:  # noqa: BLE001
            log.error("inspect %s: %s (skipping)", summary.get("Id", "?"), exc)
            continue

    cfg.publish(
        "discovery",
        {
            "tenant_id": cfg.tenant_id,
            "host_id": cfg.host_id,
            "containers": containers,
        },
    )


def _inspect_container(cfg: Config, summary: dict) -> dict:
    j = cfg.docker.api.inspect_container(summary["Id"])

    config = j.get("Config") or {}
    labels = config.get("Labels") or {}
    state = j.get("State") or {}

    info: dict = {
        "id": j.get("Id", ""),
        "name": (j.get("Name") or "").lstrip("/"),
        "image": config.get("Image", ""),
        "state": state.get("Status", "unknown"),
        "status": summary.get("Status", ""),
        "command": " ".join(config.get("Cmd") or []),
        "labels": labels,
        "env": redact_env(config.get("Env")),
        "ports": {},
        "mounts": [],
        "networks": [],
        "compose_project": labels.get("com.docker.compose.project", ""),
        "compose_service": labels.get("com.docker.compose.service", ""),
    }

    health = state.get("Health")
    if health and health.get("Status"):
        info["health"] = health["Status"]

    image_id = j.get("Image")
    if image_id:
        digest = _image_digest(cfg, image_id)
        if digest:
            info["image_digest"] = digest

    net = j.get("NetworkSettings") or {}
    for port, bindings in (net.get("Ports") or {}).items():
        if not bindings:
            continue
        try:
            info["ports"][port] = int(bindings[0]["HostPort"])
        except (KeyError, ValueError, TypeError):
            continue
    for name in (net.get("Networks") or {}):
        info["networks"].append(name)

    for m in j.get("Mounts") or []:
        info["mounts"].append(
            {"source": m.get("Source", ""), "destination": m.get("Destination", "")}
        )

    return info


def _image_digest(cfg: Config, image_id: str) -> str:
    """Resolve the repo digest (sha256:...) for an image id, best effort —
    empty string if it can't be resolved (e.g. locally built images)."""
    try:
        img = cfg.docker.api.inspect_image(image_id)
    except Exception:  # noqa: BLE001
        return ""
    digests = img.get("RepoDigests") or []
    return digests[0] if digests else ""
