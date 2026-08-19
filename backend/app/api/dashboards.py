"""Dashboard Generator API (Phase 3).

Router is not wired into ``main.py`` yet (outside this task's allowed write
path) — add ``app.include_router(dashboards.router, prefix=settings.api_prefix)``
there, plus importing ``dashboards`` in the ``from app.api import (...)`` block,
to expose it.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.engines.dashboards.templates import KNOWN_TECHS
from app.store.db import SessionLocal
from app.store.models import Dashboard

router = APIRouter(tags=["dashboards"])


class DashboardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: str
    title: str
    tier: str
    tech: str | None = None
    role: str | None = None
    grafana_uid: str | None = None
    grafana_url: str | None = None
    generated: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class RegenerateOut(BaseModel):
    provisioned: int


class TemplateOut(BaseModel):
    tech: str


@router.get("/dashboards", response_model=list[DashboardOut])
async def list_dashboards(tech: str | None = None) -> list[DashboardOut]:
    async with SessionLocal() as session:
        stmt = select(Dashboard).order_by(Dashboard.title)
        if tech is not None:
            stmt = stmt.where(Dashboard.tech == tech)
        rows = (await session.execute(stmt)).scalars().all()
        return [DashboardOut.model_validate(row) for row in rows]


@router.post("/dashboards/regenerate", response_model=RegenerateOut)
async def regenerate_dashboards() -> RegenerateOut:
    # Imported lazily to avoid a hard import-time dependency of the API layer
    # on the engine registry's runtime instance.
    from app.engines import registry

    engine = next((e for e in registry._engines if e.name == "dashboards"), None)
    if engine is None:
        # Registry hasn't started this engine (e.g. import failed) — run a
        # one-off instance so the endpoint still works standalone.
        from app.engines.base import EngineContext
        from app.engines.dashboards.engine import DashboardEngine

        engine = DashboardEngine()
        await engine.start(EngineContext(bus=None))  # type: ignore[arg-type]

    count = await engine.regenerate()
    return RegenerateOut(provisioned=count)


@router.get("/dashboard-templates", response_model=list[TemplateOut])
async def list_dashboard_templates() -> list[TemplateOut]:
    return [TemplateOut(tech=t) for t in KNOWN_TECHS]
