from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.bus.nats_bus import bus
from app.store.db import engine

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict:
    """Liveness: the process is up."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> dict:
    """Readiness: dependencies (Postgres, NATS) are reachable."""
    checks: dict[str, str] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["postgres"] = f"error: {exc}"

    checks["nats"] = "ok" if bus.is_connected else "down"

    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
