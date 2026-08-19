"""``GET /topology`` and blast-radius endpoints — the service dependency graph.

Read-only API over the Topology Engine's ``topology_edges`` table plus the
Discovery/Classification tables (for node metadata). Not wired into
``main.py`` yet (see report) — add ``app.include_router(topology.router,
prefix=settings.api_prefix)`` there to expose it.
"""
from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Query
from sqlalchemy import select

from app.store.db import SessionLocal
from app.store.models import Classification, Container, TopologyEdge

router = APIRouter(tags=["topology"])


class NodeOut(BaseModel):
    id: str
    service: str
    role: str
    tech: str | None = None
    host_id: str | None = None
    state: str | None = None
    replicas: int = 1


class EdgeOut(BaseModel):
    source: str
    target: str
    kind: str
    confidence: float
    port: int | None = None


class TopologyOut(BaseModel):
    nodes: list[NodeOut]
    edges: list[EdgeOut]


class DependencyOut(BaseModel):
    service: str
    kind: str
    confidence: float
    port: int | None = None


def _service_name(container: Container) -> str:
    # Namespaced by compose project to match TopologyEngine node ids, so a
    # `redis` in project A is distinct from a `redis` in project B.
    bare = container.compose_service or container.name
    proj = container.compose_project or ""
    return f"{proj}/{bare}" if proj else bare


@router.get("/topology", response_model=TopologyOut)
async def get_topology(host_id: str | None = Query(default=None)) -> TopologyOut:
    async with SessionLocal() as session:
        stmt = select(Container, Classification).outerjoin(
            Classification, Classification.container_id == Container.id
        )
        if host_id is not None:
            stmt = stmt.where(Container.host_id == host_id)
        rows = (await session.execute(stmt)).all()

        # Aggregate containers -> one node per service (replicas merged).
        services: dict[str, dict] = {}
        for container, classification in rows:
            svc = _service_name(container)
            entry = services.setdefault(
                svc,
                {
                    "id": svc,
                    "service": svc,
                    "role": None,
                    "tech": None,
                    "host_id": container.host_id,
                    "states": [],
                    "best_confidence": -1.0,
                    "replicas": 0,
                },
            )
            entry["replicas"] += 1
            entry["states"].append(container.state)
            if classification is not None:
                conf = classification.confidence or 0.0
                if conf >= entry["best_confidence"]:
                    entry["role"] = classification.role
                    entry["tech"] = classification.tech
                    entry["best_confidence"] = conf

        nodes: list[NodeOut] = []
        for entry in services.values():
            states = entry.pop("states")
            entry.pop("best_confidence", None)
            entry["state"] = "running" if "running" in states else (states[0] if states else None)
            entry["role"] = entry["role"] or "unknown"
            nodes.append(NodeOut(**entry))

        service_names = {n.service for n in nodes}

        edge_rows = (await session.execute(select(TopologyEdge))).scalars().all()
        edges: list[EdgeOut] = []
        for e in edge_rows:
            if host_id is not None and (
                e.src_service not in service_names and e.dst_service not in service_names
            ):
                continue
            edges.append(
                EdgeOut(
                    source=e.src_service,
                    target=e.dst_service,
                    kind=e.kind,
                    confidence=e.confidence,
                    port=e.port,
                )
            )

        return TopologyOut(nodes=nodes, edges=edges)


@router.get("/services/dependencies", response_model=list[DependencyOut])
async def get_dependencies(service: str = Query(...)) -> list[DependencyOut]:
    """Services that ``service`` depends on (edges where it is the source).

    ``service`` is a query param (not a path segment) because namespaced
    service ids contain ``/`` (e.g. ``carevora/api``).
    """
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(TopologyEdge).where(TopologyEdge.src_service == service)
            )
        ).scalars().all()
        return [
            DependencyOut(service=e.dst_service, kind=e.kind, confidence=e.confidence, port=e.port)
            for e in rows
        ]


@router.get("/services/dependents", response_model=list[DependencyOut])
async def get_dependents(service: str = Query(...)) -> list[DependencyOut]:
    """Services that depend on ``service`` — its blast radius if it goes down."""
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(TopologyEdge).where(TopologyEdge.dst_service == service)
            )
        ).scalars().all()
        return [
            DependencyOut(service=e.src_service, kind=e.kind, confidence=e.confidence, port=e.port)
            for e in rows
        ]
