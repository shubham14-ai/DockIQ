"""``GET /projects`` and ``GET /projects/{project}`` — compose-stack grouping.

A **project** is the value of a container's ``com.docker.compose.project`` label
(persisted as ``Container.compose_project``). This router aggregates the existing
Discovery/Classification tables into the same host → project → service → container
hierarchy Docker Desktop shows — no extra collection required. Containers with no
compose project fall into a synthetic ``STANDALONE`` bucket.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.containers import ContainerOut, _to_out
from app.store.db import SessionLocal
from app.store.models import Classification, Container

router = APIRouter(prefix="/projects", tags=["projects"])

# Synthetic project id for containers with no compose project label.
STANDALONE = "(standalone)"


class ProjectSummary(BaseModel):
    project: str
    standalone: bool = False
    hosts: list[str]
    service_count: int
    container_count: int
    state_counts: dict[str, int]
    health: dict[str, int]
    image_count: int
    techs: list[str]
    last_seen: dt.datetime | None = None


class ProjectServiceOut(BaseModel):
    service: str
    container_count: int
    state_counts: dict[str, int]
    containers: list[ContainerOut]


class ProjectImageOut(BaseModel):
    image_ref: str | None = None
    image_digest: str | None = None
    services: list[str]
    container_count: int


class ProjectConfig(BaseModel):
    config_files: str | None = None
    working_dir: str | None = None
    networks: list[str] = []


class ProjectDetail(ProjectSummary):
    services: list[ProjectServiceOut]
    images: list[ProjectImageOut]
    config: ProjectConfig


def _project_key(container: Container) -> str:
    return container.compose_project or STANDALONE


def _health_of(container: Container) -> str:
    """Roll a container's native health / state up to one of four buckets."""
    native = (container.native_health or "").lower()
    if native == "healthy":
        return "healthy"
    if native in ("unhealthy",):
        return "down"
    if native == "starting":
        return "degraded"
    state = (container.state or "").lower()
    if state == "running":
        return "healthy"
    if state in ("exited", "dead"):
        return "down"
    if state in ("restarting", "paused", "created"):
        return "degraded"
    return "unknown"


def _service_of(container: Container) -> str:
    return container.compose_service or container.name


async def _load_rows(
    host_id: str | None = None,
) -> list[tuple[Container, Classification | None]]:
    async with SessionLocal() as session:
        stmt = select(Container, Classification).outerjoin(
            Classification, Classification.container_id == Container.id
        )
        if host_id is not None:
            stmt = stmt.where(Container.host_id == host_id)
        stmt = stmt.order_by(Container.compose_project, Container.name)
        return list((await session.execute(stmt)).all())


def _summarize(project: str, rows: list[tuple[Container, Classification | None]]) -> ProjectSummary:
    containers = [c for c, _ in rows]
    hosts = sorted({c.host_id for c in containers if c.host_id})
    services = {_service_of(c) for c in containers}
    images = {(c.image_ref, c.image_digest) for c in containers}

    state_counts: dict[str, int] = {}
    health: dict[str, int] = {}
    techs: set[str] = set()
    last_seen: dt.datetime | None = None
    for c, cls in rows:
        state = c.state or "unknown"
        state_counts[state] = state_counts.get(state, 0) + 1
        h = _health_of(c)
        health[h] = health.get(h, 0) + 1
        if cls is not None and cls.tech:
            techs.add(cls.tech)
        if c.last_seen and (last_seen is None or c.last_seen > last_seen):
            last_seen = c.last_seen

    return ProjectSummary(
        project=project,
        standalone=(project == STANDALONE),
        hosts=hosts,
        service_count=len(services),
        container_count=len(containers),
        state_counts=state_counts,
        health=health,
        image_count=len(images),
        techs=sorted(techs),
        last_seen=last_seen,
    )


@router.get("", response_model=list[ProjectSummary])
async def list_projects(
    host_id: str | None = Query(default=None),
) -> list[ProjectSummary]:
    rows = await _load_rows(host_id)
    grouped: dict[str, list[tuple[Container, Classification | None]]] = {}
    for container, cls in rows:
        grouped.setdefault(_project_key(container), []).append((container, cls))

    summaries = [_summarize(project, grp) for project, grp in grouped.items()]
    # Real stacks first (alpha), standalone bucket last.
    summaries.sort(key=lambda s: (s.standalone, s.project.lower()))
    return summaries


@router.get("/{project}", response_model=ProjectDetail)
async def get_project(
    project: str,
    host_id: str | None = Query(default=None),
) -> ProjectDetail:
    rows = await _load_rows(host_id)
    mine = [(c, cls) for c, cls in rows if _project_key(c) == project]
    if not mine:
        raise HTTPException(status_code=404, detail="Project not found")

    summary = _summarize(project, mine)

    # Group by service.
    by_service: dict[str, list[tuple[Container, Classification | None]]] = {}
    for container, cls in mine:
        by_service.setdefault(_service_of(container), []).append((container, cls))

    services: list[ProjectServiceOut] = []
    for service in sorted(by_service):
        svc_rows = by_service[service]
        state_counts: dict[str, int] = {}
        for c, _ in svc_rows:
            state = c.state or "unknown"
            state_counts[state] = state_counts.get(state, 0) + 1
        services.append(
            ProjectServiceOut(
                service=service,
                container_count=len(svc_rows),
                state_counts=state_counts,
                containers=[_to_out(c, cls) for c, cls in svc_rows],
            )
        )

    # Distinct images used across the project (derived from containers).
    img_index: dict[tuple[str | None, str | None], dict] = {}
    for container, _ in mine:
        key = (container.image_ref, container.image_digest)
        entry = img_index.setdefault(
            key,
            {"services": set(), "container_count": 0},
        )
        entry["services"].add(_service_of(container))
        entry["container_count"] += 1
    images = [
        ProjectImageOut(
            image_ref=ref,
            image_digest=digest,
            services=sorted(entry["services"]),
            container_count=entry["container_count"],
        )
        for (ref, digest), entry in sorted(
            img_index.items(), key=lambda kv: (kv[0][0] or "")
        )
    ]

    # Project-level config, read from any member container's compose labels.
    config = ProjectConfig()
    networks: set[str] = set()
    for container, _ in mine:
        labels = container.labels or {}
        if config.config_files is None:
            config.config_files = labels.get("com.docker.compose.project.config_files")
        if config.working_dir is None:
            config.working_dir = labels.get("com.docker.compose.project.working_dir")
        if isinstance(container.networks, list):
            networks.update(n for n in container.networks if isinstance(n, str))
    config.networks = sorted(networks)

    return ProjectDetail(**summary.model_dump(), services=services, images=images, config=config)
