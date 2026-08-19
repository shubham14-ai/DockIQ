"""``GET /containers`` and ``GET /containers/{id}`` — inventory + classification.

Read-only API over the Discovery/Classification engines' tables. Not wired
into ``main.py`` yet (see report) — add
``app.include_router(containers.router)`` there to expose it.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.store.db import SessionLocal
from app.store.models import Classification, Container

router = APIRouter(prefix="/containers", tags=["containers"])


class ClassificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role: str
    tech: str | None = None
    confidence: float
    evidence: dict | None = None
    source: str
    overridden: bool
    classified_at: dt.datetime


class ContainerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    host_id: str
    name: str
    image_ref: str | None = None
    image_digest: str | None = None
    state: str | None = None
    status: str | None = None
    command: str | None = None
    compose_project: str | None = None
    compose_service: str | None = None
    # These are stored as JSONB; shapes vary (labels/env/ports are objects,
    # mounts/networks are lists per the agent protocol), so accept any JSON.
    labels: Any | None = None
    env: Any | None = None
    ports: Any | None = None
    mounts: Any | None = None
    networks: Any | None = None
    native_health: str | None = None
    first_seen: dt.datetime
    last_seen: dt.datetime
    classification: ClassificationOut | None = None


def _to_out(container: Container, classification: Classification | None) -> ContainerOut:
    data = ContainerOut.model_validate(container)
    if classification is not None:
        data.classification = ClassificationOut.model_validate(classification)
    return data


@router.get("", response_model=list[ContainerOut])
async def list_containers(
    host_id: str | None = Query(default=None),
    role: str | None = Query(default=None),
    tech: str | None = Query(default=None),
    state: str | None = Query(default=None),
) -> list[ContainerOut]:
    async with SessionLocal() as session:
        stmt = select(Container, Classification).outerjoin(
            Classification, Classification.container_id == Container.id
        )
        if host_id is not None:
            stmt = stmt.where(Container.host_id == host_id)
        if state is not None:
            stmt = stmt.where(Container.state == state)
        if role is not None:
            stmt = stmt.where(Classification.role == role)
        if tech is not None:
            stmt = stmt.where(Classification.tech == tech)
        stmt = stmt.order_by(Container.name)

        rows = (await session.execute(stmt)).all()
        return [_to_out(container, classification) for container, classification in rows]


@router.get("/{container_id}", response_model=ContainerOut)
async def get_container(container_id: str) -> ContainerOut:
    async with SessionLocal() as session:
        stmt = (
            select(Container, Classification)
            .outerjoin(Classification, Classification.container_id == Container.id)
            .where(Container.id == container_id)
        )
        row = (await session.execute(stmt)).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Container not found")
        container, classification = row
        return _to_out(container, classification)
