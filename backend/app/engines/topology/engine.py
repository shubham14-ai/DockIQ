"""Topology Engine (Phase 2, MVP-lite: static graph).

Consumes ``discovery`` inventory snapshots and builds a service-level
dependency graph from cheap, static evidence:

1. **Shared docker networks** — services co-located on the same user-defined
   network *can* talk. Low-confidence, ``kind="inferred"`` edges, added in
   both directions.
2. **Compose ``depends_on``** — from the
   ``com.docker.compose.depends_on`` label (format:
   ``"svcA:condition:bool,svcB:condition:bool"``). High-confidence,
   ``kind="declared"`` directed edges.
3. **Env var references** — values of ``*_URL`` / ``*_HOST`` (and similar)
   env keys are parsed for a hostname; if that hostname matches another
   container/service known on the same host, a directed edge is recorded.
   High-confidence, ``kind="declared"``.

Edges are upserted into ``topology_edges`` deduped by
``(tenant_id, src_service, dst_service)``, keeping the highest-confidence
kind/evidence seen and bumping ``last_seen``. Self-edges are dropped.

See docs/phase1-agent-protocol.md for the discovery payload contract and
docs/engines/03-topology-engine.md for the design.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus.subjects import DISCOVERY, wildcard
from app.engines.base import BaseEngine, EngineContext
from app.store.db import SessionLocal
from app.store.models import TopologyEdge

log = logging.getLogger("dockiq.engine.topology")

# Env var keys that plausibly carry a hostname reference, e.g. REDIS_URL,
# DATABASE_URL, POSTGRES_HOST, MONGO_URI-ish (URL/HOST/URI suffix).
_HOSTLIKE_KEY_RE = re.compile(r"(URL|HOST|URI)$", re.IGNORECASE)

# Ordering used to decide which evidence "wins" when the same (src, dst)
# pair is observed from multiple sources: declared > observed > inferred.
_KIND_RANK = {"inferred": 0, "observed": 1, "declared": 2}

_IGNORED_NETWORKS = {"host", "none", "bridge"}


def _project(container: dict) -> str:
    """Compose project the container belongs to ("" if standalone)."""
    return container.get("compose_project") or ""


def _bare_service(container: dict) -> str:
    """The unqualified service/container name (used for hostname resolution)."""
    return (
        container.get("compose_service")
        or container.get("name")
        or (container.get("id") or "")[:12]
    )


def _service_name(container: dict) -> str:
    """Canonical node id, namespaced by compose project so that a `redis` in
    project A is a distinct node from a `redis` in project B."""
    bare = _bare_service(container)
    proj = _project(container)
    return f"{proj}/{bare}" if proj else bare


def _extract_host_port(value: str) -> tuple[str | None, int | None]:
    """Pull a hostname (and optional port) out of an env var value.

    Handles ``scheme://[user:pass@]host[:port][/path]`` and bare
    ``host[:port]`` forms.
    """
    value = (value or "").strip()
    if not value:
        return None, None

    if "://" in value:
        try:
            parsed = urlparse(value)
        except ValueError:
            return None, None
        return parsed.hostname, parsed.port

    part = value.split("/", 1)[0]
    if "@" in part:
        part = part.rsplit("@", 1)[-1]
    if not part:
        return None, None

    if ":" in part:
        host, _, port_s = part.partition(":")
        try:
            port = int(port_s)
        except ValueError:
            port = None
        return (host or None), port

    return part, None


class TopologyEngine(BaseEngine):
    name = "topology"

    def subjects(self) -> list[str]:
        return [wildcard(DISCOVERY)]

    async def start(self, ctx: EngineContext) -> None:
        await super().start(ctx)
        self.log.info("topology engine started")

    async def stop(self) -> None:
        self.log.info("topology engine stopped")

    async def handle(self, subject: str, data: dict) -> None:
        # Exception-safe: never let a bad/partial snapshot kill the consumer.
        try:
            await self._handle_snapshot(data)
        except Exception:  # noqa: BLE001
            self.log.exception("failed to process discovery snapshot for topology")

    # -- snapshot processing -------------------------------------------------

    async def _handle_snapshot(self, data: dict) -> None:
        tenant_id = data.get("tenant_id")
        host_id = data.get("host_id")
        containers = data.get("containers") or []
        if not tenant_id or not containers:
            return

        edges = self._build_edges(containers)
        if not edges:
            return

        async with SessionLocal() as session:
            await self._upsert_edges(session, tenant_id, host_id, edges)
            await session.commit()

        self.log.debug(
            "topology: derived %d edge(s) from host=%s (%d containers)",
            len(edges),
            host_id,
            len(containers),
        )

    def _build_edges(self, containers: list[dict]) -> dict[tuple[str, str], dict]:
        # Per-project name -> canonical (namespaced) service id. Hostnames in
        # env refs / depends_on resolve within the *same* compose project,
        # since Compose networks are project-scoped.
        proj_maps: dict[str, dict[str, str]] = {}
        for c in containers:
            proj = _project(c)
            svc = _service_name(c)
            m = proj_maps.setdefault(proj, {})
            m[_bare_service(c)] = svc
            if c.get("name"):
                m[c["name"]] = svc

        edges: dict[tuple[str, str], dict] = {}

        def add_edge(
            src: str | None,
            dst: str | None,
            kind: str,
            confidence: float,
            port: int | None = None,
            proto: str | None = None,
            evidence: dict | None = None,
        ) -> None:
            if not src or not dst or src == dst:
                return
            key = (src, dst)
            existing = edges.get(key)
            if existing is None:
                edges[key] = {
                    "kind": kind,
                    "confidence": confidence,
                    "port": port,
                    "proto": proto,
                    "evidence": evidence or {},
                }
                return
            # Keep whichever evidence source ranks higher (declared beats
            # inferred); on a tie, keep the higher confidence.
            if _KIND_RANK.get(kind, 0) > _KIND_RANK.get(existing["kind"], 0) or (
                kind == existing["kind"] and confidence > existing["confidence"]
            ):
                existing.update(
                    kind=kind,
                    confidence=confidence,
                    port=port if port is not None else existing.get("port"),
                    proto=proto if proto is not None else existing.get("proto"),
                    evidence=evidence or existing.get("evidence"),
                )
            else:
                existing["confidence"] = max(existing["confidence"], confidence)

        # 1. Shared docker networks -> low-confidence, bidirectional, inferred.
        network_to_services: dict[str, set[str]] = {}
        for c in containers:
            svc = _service_name(c)
            for net in c.get("networks") or []:
                if not net or net in _IGNORED_NETWORKS:
                    continue
                network_to_services.setdefault(net, set()).add(svc)

        for net, svcs in network_to_services.items():
            svc_list = sorted(svcs)
            for i, a in enumerate(svc_list):
                for b in svc_list[i + 1 :]:
                    add_edge(a, b, "inferred", 0.3, evidence={"source": "network", "network": net})
                    add_edge(b, a, "inferred", 0.3, evidence={"source": "network", "network": net})

        # 2. Compose depends_on label -> high-confidence, directed, declared.
        for c in containers:
            svc = _service_name(c)
            labels = c.get("labels") or {}
            depends_raw = labels.get("com.docker.compose.depends_on")
            if not depends_raw:
                continue
            for part in str(depends_raw).split(","):
                part = part.strip()
                if not part:
                    continue
                dep_svc = part.split(":", 1)[0].strip()
                if not dep_svc:
                    continue
                # depends_on references a sibling service in the same project.
                proj_map = proj_maps.get(_project(c), {})
                fallback = f"{_project(c)}/{dep_svc}" if _project(c) else dep_svc
                dst = proj_map.get(dep_svc, fallback)
                add_edge(
                    svc,
                    dst,
                    "declared",
                    0.95,
                    evidence={"source": "compose_depends_on", "raw": part},
                )

        # 3. Env var host/url references -> high-confidence, directed, declared.
        for c in containers:
            svc = _service_name(c)
            env = c.get("env") or {}
            for key, value in env.items():
                if value is None or value == "***REDACTED***":
                    continue
                if not _HOSTLIKE_KEY_RE.search(str(key)):
                    continue
                host, port = _extract_host_port(str(value))
                if not host:
                    continue
                # Resolve the hostname within the source container's project.
                dst = proj_maps.get(_project(c), {}).get(host)
                if not dst:
                    continue
                add_edge(
                    svc,
                    dst,
                    "declared",
                    0.8,
                    port=port,
                    evidence={"source": "env_ref", "env_key": key, "host": host},
                )

        return edges

    # -- persistence -----------------------------------------------------------

    async def _upsert_edges(
        self,
        session: AsyncSession,
        tenant_id: str,
        host_id: str | None,
        edges: dict[tuple[str, str], dict],
    ) -> None:
        for (src, dst), info in edges.items():
            existing = await session.execute(
                select(TopologyEdge).where(
                    TopologyEdge.tenant_id == tenant_id,
                    TopologyEdge.src_service == src,
                    TopologyEdge.dst_service == dst,
                )
            )
            row = existing.scalar_one_or_none()

            if row is None:
                session.add(
                    TopologyEdge(
                        tenant_id=tenant_id,
                        host_id=host_id,
                        src_service=src,
                        dst_service=dst,
                        kind=info["kind"],
                        proto=info.get("proto"),
                        port=info.get("port"),
                        confidence=info["confidence"],
                        evidence=info.get("evidence"),
                    )
                )
                continue

            # Keep the highest-ranked kind/confidence seen so far; always
            # refresh last_seen/host_id to reflect that the edge is current.
            if _KIND_RANK.get(info["kind"], 0) > _KIND_RANK.get(row.kind, 0) or (
                info["kind"] == row.kind and info["confidence"] > (row.confidence or 0.0)
            ):
                row.kind = info["kind"]
                row.confidence = info["confidence"]
                if info.get("port") is not None:
                    row.port = info["port"]
                if info.get("proto") is not None:
                    row.proto = info["proto"]
                if info.get("evidence"):
                    row.evidence = info["evidence"]
            else:
                row.confidence = max(row.confidence or 0.0, info["confidence"])

            row.host_id = host_id
