"""Cache maintenance API — reclaim unwanted Docker cache, with an approval gate.

Clearing cache (dangling images, stopped containers, idle build cache) is
destructive, so it is deliberately split into two calls:

1. ``POST /hosts/{host_id}/cache/scan`` — asks the agent (``dry_run``) how much
   space each target could reclaim. Removes nothing. Safe to call anytime.
2. ``POST /hosts/{host_id}/cache/prune`` — actually reclaims, and **only runs
   when the body carries ``approve: true``**. Without explicit approval it is
   rejected with 422. The approval is the human-in-the-loop step the UI drives
   after showing the scan result.

Both are operator-gated at the router level (see ``main.py``) and every prune is
written to the ``healing_actions`` audit trail with ``action="prune"``.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents.commander import send_command
from app.bus.nats_bus import bus
from app.store.db import SessionLocal
from app.store.models import HealingAction, Host

router = APIRouter(tags=["maintenance"])

# Targets a caller may request. Volumes are allowed but never a default — the
# UI must let the operator opt in explicitly, since pruning volumes loses data.
ALLOWED_TARGETS = {"build-cache", "images", "containers", "networks", "volumes"}
DEFAULT_TARGETS = ["build-cache", "images", "containers", "networks"]


class CacheScanRequest(BaseModel):
    targets: list[str] | None = None


class CachePruneRequest(BaseModel):
    targets: list[str] | None = None
    dangling_only: bool = True
    # Human-in-the-loop gate. Must be explicitly true or the prune is refused.
    approve: bool = Field(
        default=False,
        description="Must be true to execute. This is the required approval step.",
    )


class CacheResult(BaseModel):
    ok: bool
    host_id: str
    dry_run: bool
    reclaimable_bytes: int | None = None
    reclaimed_bytes: int | None = None
    targets: dict | None = None
    error: str | None = None
    action_id: int | None = None


def _validate_targets(targets: list[str] | None) -> list[str]:
    if not targets:
        return list(DEFAULT_TARGETS)
    unknown = [t for t in targets if t not in ALLOWED_TARGETS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown targets: {unknown}")
    return targets


async def _get_host(host_id: str) -> Host:
    async with SessionLocal() as session:
        host = await session.get(Host, host_id)
        if host is None:
            raise HTTPException(status_code=404, detail="Host not found")
        return host


@router.post("/hosts/{host_id}/cache/scan", response_model=CacheResult)
async def scan_cache(host_id: str, body: CacheScanRequest) -> CacheResult:
    """Report reclaimable cache per target without removing anything."""
    host = await _get_host(host_id)
    targets = _validate_targets(body.targets)

    result = await send_command(
        bus, host.tenant_id, host_id, "prune",
        extra={"dry_run": True, "targets": targets},
    )
    if not result.get("ok"):
        return CacheResult(
            ok=False, host_id=host_id, dry_run=True, error=result.get("error")
        )
    return CacheResult(
        ok=True,
        host_id=host_id,
        dry_run=True,
        reclaimable_bytes=result.get("reclaimable_bytes"),
        targets=result.get("targets"),
    )


@router.post("/hosts/{host_id}/cache/prune", response_model=CacheResult)
async def prune_cache(host_id: str, body: CachePruneRequest) -> CacheResult:
    """Reclaim cache. Refused unless ``approve`` is explicitly true."""
    if not body.approve:
        raise HTTPException(
            status_code=422,
            detail="Prune requires explicit approval: send {\"approve\": true}.",
        )

    host = await _get_host(host_id)
    targets = _validate_targets(body.targets)

    result = await send_command(
        bus, host.tenant_id, host_id, "prune",
        extra={
            "dry_run": False,
            "targets": targets,
            "dangling_only": body.dangling_only,
        },
        # Removal can take a while on a full host.
        request_timeout=120.0,
    )

    reclaimed = result.get("reclaimed_bytes")
    async with SessionLocal() as session:
        action = HealingAction(
            tenant_id=host.tenant_id,
            policy_id=None,
            trigger="manual",
            target=host_id,
            host_id=host_id,
            container_id=None,
            action="prune",
            outcome="fixed" if result.get("ok") else "failed",
            detail=(
                result.get("error")
                if not result.get("ok")
                else f"reclaimed {reclaimed} bytes across {', '.join(targets)}"
            ),
        )
        session.add(action)
        await session.commit()
        await session.refresh(action)
        action_id = action.id

    return CacheResult(
        ok=bool(result.get("ok")),
        host_id=host_id,
        dry_run=False,
        reclaimed_bytes=reclaimed,
        targets=result.get("targets"),
        error=result.get("error"),
        action_id=action_id,
    )
