from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from fastapi import Depends

from app.api import (
    agents,
    alerts,
    anomaly,
    auth,
    containers,
    dashboards,
    deployments,
    diagnostics,
    health,
    healing,
    hosts,
    llm,
    logs,
    maintenance,
    metrics,
    projects,
    topology,
)
from app.auth.deps import get_principal, require_role
from app.bus.nats_bus import bus
from app.core.config import settings
from app.core.logging import setup_logging
from app.engines import registry
from app.services.heartbeat import offline_sweeper, start_heartbeat_consumer
from app.store.db import init_db

setup_logging()
log = logging.getLogger("dockiq")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("starting %s %s", settings.app_name, settings.version)
    await init_db()
    await bus.connect()
    await start_heartbeat_consumer()
    await registry.start_all(bus)
    sweeper = asyncio.create_task(offline_sweeper())
    log.info("DockIQ backend ready")
    try:
        yield
    finally:
        sweeper.cancel()
        await registry.stop_all()
        await bus.close()
        log.info("DockIQ backend stopped")


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

# Root-level health probes.
app.include_router(health.router)

# --- Auth (Phase 7) ---
# Auth router is open where it needs to be (login) and self-guards elsewhere.
app.include_router(auth.router, prefix=settings.api_prefix)

# Agent enrollment is NOT user-authenticated — it is gated by a join token
# validated inside the endpoint (see agents.enroll).
app.include_router(agents.router, prefix=settings.api_prefix)

# Every other API route requires an authenticated principal (any role).
_authed = [Depends(get_principal)]
# Ops-sensitive routers require operator+ (deploy/heal recreate/restart things).
_ops = [Depends(require_role("operator"))]

app.include_router(hosts.router, prefix=settings.api_prefix, dependencies=_authed)
app.include_router(containers.router, prefix=settings.api_prefix, dependencies=_authed)
app.include_router(projects.router, prefix=settings.api_prefix, dependencies=_authed)
app.include_router(metrics.router, prefix=settings.api_prefix, dependencies=_authed)
app.include_router(logs.router, prefix=settings.api_prefix, dependencies=_authed)
app.include_router(alerts.router, prefix=settings.api_prefix, dependencies=_authed)
app.include_router(topology.router, prefix=settings.api_prefix, dependencies=_authed)
app.include_router(anomaly.router, prefix=settings.api_prefix, dependencies=_authed)
app.include_router(diagnostics.router, prefix=settings.api_prefix, dependencies=_authed)
app.include_router(dashboards.router, prefix=settings.api_prefix, dependencies=_authed)
app.include_router(llm.router, prefix=settings.api_prefix, dependencies=_authed)
app.include_router(healing.router, prefix=settings.api_prefix, dependencies=_ops)
# Cache maintenance (prune) is destructive → operator role + per-call approval.
app.include_router(maintenance.router, prefix=settings.api_prefix, dependencies=_ops)
app.include_router(deployments.router, prefix=settings.api_prefix, dependencies=_ops)


@app.get("/")
async def root() -> dict:
    return {
        "name": settings.app_name,
        "version": settings.version,
        "phase": "1",
        "docs": "/docs",
    }
