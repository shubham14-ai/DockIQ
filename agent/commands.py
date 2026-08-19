"""Command execution — the agent's action side (Phases 5-6).

Subscribes to ``dockiq.<tenant>.<host_id>.commands`` and executes control-plane
commands against the local Docker daemon, replying with the outcome. Used by the
Self-Healing and Deployment engines via NATS request/reply.

Supported actions: restart, stop, start, pull, recreate, prune. All are gated by
control-plane policy (the backend decides *whether* to send a command); the agent
just executes and reports. Nothing here runs arbitrary code.

``prune`` reclaims unwanted Docker cache (dangling images, stopped containers,
unused build cache / networks). It is deliberately two-phase: with
``dry_run=True`` it only *reports* what could be reclaimed (via ``docker df``) and
removes nothing; the destructive pass runs only when the control plane sends
``dry_run=False`` — which the backend does exclusively after explicit human
approval. Volumes are never touched unless ``"volumes"`` is explicitly requested,
since that can delete data.
"""
from __future__ import annotations

import logging

import docker

log = logging.getLogger("dockiq.agent.commands")

# What a bare prune touches. Volumes are intentionally excluded — removing them
# can destroy data, so a caller must opt in by naming "volumes" explicitly.
DEFAULT_PRUNE_TARGETS = ("build-cache", "images", "containers", "networks")


def _pull(client: docker.DockerClient, image: str) -> None:
    repo, sep, tag = image.partition(":")
    client.api.pull(repo, tag=(tag if sep else "latest"))


def _recreate(client: docker.DockerClient, container, new_image: str | None) -> str:
    """Best-effort recreate preserving the container's config/host-config and its
    primary network. (Full multi-network / volume fidelity is a follow-up.)"""
    attrs = container.attrs
    name = attrs["Name"].lstrip("/")
    config = attrs.get("Config", {})
    host_config = attrs.get("HostConfig", {})
    networks = (attrs.get("NetworkSettings", {}) or {}).get("Networks", {}) or {}
    image_ref = new_image or config.get("Image")

    if new_image:
        _pull(client, new_image)

    container.stop(timeout=10)
    container.remove(force=True)

    net_names = list(networks.keys())
    networking_config = None
    if net_names:
        first = net_names[0]
        ep = networks[first] or {}
        aliases = ep.get("Aliases") or None
        networking_config = client.api.create_networking_config(
            {first: client.api.create_endpoint_config(aliases=aliases)}
        )

    created = client.api.create_container(
        image=image_ref,
        name=name,
        command=config.get("Cmd"),
        entrypoint=config.get("Entrypoint"),
        environment=config.get("Env"),
        labels=config.get("Labels") or {},
        host_config=host_config,  # raw Docker-format dict; accepted by the low-level API
        networking_config=networking_config,
    )
    new_id = created["Id"]
    client.api.start(new_id)
    for extra in net_names[1:]:
        try:
            client.api.connect_container_to_network(new_id, extra)
        except Exception as exc:  # noqa: BLE001
            log.warning("reconnect network %s: %s", extra, exc)
    return new_id


def _scan_reclaimable(client: docker.DockerClient, targets) -> dict:
    """Report reclaimable space per target without removing anything.

    Uses ``docker df`` (``/system/df``) and sums the entries Docker itself marks
    as reclaimable: dangling/untagged images with no container, stopped
    containers, and idle build cache. This is what a real prune *would* free.
    """
    df = client.df()
    per_target: dict[str, dict] = {}

    if "images" in targets:
        images = df.get("Images") or []
        # Dangling == untagged (RepoTags is <none>) and unreferenced by a container.
        dangling = [
            img for img in images
            if not (img.get("RepoTags") or []) and int(img.get("Containers", 0)) <= 0
        ]
        per_target["images"] = {
            "count": len(dangling),
            "reclaimable_bytes": sum(int(i.get("Size", 0)) for i in dangling),
        }

    if "containers" in targets:
        containers = df.get("Containers") or []
        stopped = [c for c in containers if (c.get("State") or "").lower() != "running"]
        per_target["containers"] = {
            "count": len(stopped),
            "reclaimable_bytes": sum(int(c.get("SizeRw", 0)) for c in stopped),
        }

    if "build-cache" in targets:
        cache = df.get("BuildCache") or []
        idle = [e for e in cache if not e.get("InUse")]
        per_target["build-cache"] = {
            "count": len(idle),
            "reclaimable_bytes": sum(int(e.get("Size", 0)) for e in idle),
        }

    if "volumes" in targets:
        volumes = df.get("Volumes") or []
        unused = [
            v for v in volumes
            if int(((v.get("UsageData") or {}).get("RefCount", 0))) <= 0
        ]
        per_target["volumes"] = {
            "count": len(unused),
            "reclaimable_bytes": sum(
                max(int(((v.get("UsageData") or {}).get("Size", 0))), 0) for v in unused
            ),
        }

    if "networks" in targets:
        # df has no network sizes; report presence only (prune frees no bytes).
        per_target["networks"] = {"count": 0, "reclaimable_bytes": 0}

    total = sum(t["reclaimable_bytes"] for t in per_target.values())
    return {"dry_run": True, "targets": per_target, "reclaimable_bytes": total}


def _prune(client: docker.DockerClient, targets, dangling_only: bool = True) -> dict:
    """Execute the prune. Destructive — only reached with dry_run=False."""
    per_target: dict[str, dict] = {}
    total = 0

    # Order matters: containers first frees images they pinned.
    if "containers" in targets:
        res = client.containers.prune()
        freed = int(res.get("SpaceReclaimed", 0))
        per_target["containers"] = {
            "removed": len(res.get("ContainersDeleted") or []),
            "reclaimed_bytes": freed,
        }
        total += freed

    if "images" in targets:
        # dangling_only=True → only untagged layers (the "unwanted" default).
        res = client.images.prune(filters={"dangling": bool(dangling_only)})
        freed = int(res.get("SpaceReclaimed", 0))
        per_target["images"] = {
            "removed": len(res.get("ImagesDeleted") or []),
            "reclaimed_bytes": freed,
        }
        total += freed

    if "build-cache" in targets:
        res = client.api.prune_builds()
        freed = int(res.get("SpaceReclaimed", 0))
        per_target["build-cache"] = {
            "removed": len(res.get("CachesDeleted") or []),
            "reclaimed_bytes": freed,
        }
        total += freed

    if "networks" in targets:
        res = client.networks.prune()
        per_target["networks"] = {
            "removed": len(res.get("NetworksDeleted") or []),
            "reclaimed_bytes": 0,
        }

    if "volumes" in targets:
        res = client.volumes.prune()
        freed = int(res.get("SpaceReclaimed", 0))
        per_target["volumes"] = {
            "removed": len(res.get("VolumesDeleted") or []),
            "reclaimed_bytes": freed,
        }
        total += freed

    return {"dry_run": False, "targets": per_target, "reclaimed_bytes": total}


def make_handler(client: docker.DockerClient):
    """Return a ``handler(req: dict) -> dict`` for NatsPublisher.serve_requests."""

    def handle(req: dict) -> dict:
        command_id = req.get("command_id")
        action = req.get("action")
        container_id = req.get("container_id")
        timeout = int(req.get("timeout_secs", 10))
        result = {"command_id": command_id, "ok": False}
        try:
            if action == "pull":
                _pull(client, req["image"])
                result["ok"] = True
                return result

            if action == "prune":
                targets = req.get("targets") or list(DEFAULT_PRUNE_TARGETS)
                if req.get("dry_run", True):
                    result.update(_scan_reclaimable(client, targets))
                else:
                    result.update(_prune(client, targets, req.get("dangling_only", True)))
                result["ok"] = True
                log.info(
                    "prune %s targets=%s (cmd %s)",
                    "scan" if result.get("dry_run") else "executed", targets, command_id,
                )
                return result

            container = client.containers.get(container_id) if container_id else None

            if action == "restart":
                container.restart(timeout=timeout)
            elif action == "stop":
                container.stop(timeout=timeout)
            elif action == "start":
                container.start()
            elif action == "recreate":
                new_id = _recreate(client, container, req.get("image"))
                result["detail"] = f"recreated as {new_id[:12]}"
            else:
                result["error"] = f"unknown action: {action}"
                return result

            result["ok"] = True
            log.info("executed %s on %s (cmd %s)", action, (container_id or "")[:12], command_id)
            return result
        except Exception as exc:  # noqa: BLE001 — report failures back to the control plane
            log.warning("command %s (%s) failed: %s", action, command_id, exc)
            result["error"] = f"{type(exc).__name__}: {exc}"
            return result

    return handle
