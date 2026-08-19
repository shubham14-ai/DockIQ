"""Self-Healing API (Phase 5 Self-Healing Engine).

Router is included by ``main.py`` (wiring left to the caller per task
constraints — see report). Pydantic request/response models are defined
locally rather than in ``app/api/schemas.py`` since that file is outside this
engine's allowed write path.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.agents.commander import send_command
from app.bus.nats_bus import bus
from app.core.config import settings
from app.store.db import SessionLocal
from app.store.models import Container, HealingAction, HealingPolicy

router = APIRouter(tags=["healing"])


# ----------------------------------------------------------------------
# schemas
# ----------------------------------------------------------------------


class HealingPolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: str
    name: str
    target_selector: dict | None = None
    allowed_actions: list[str] | None = None
    mode: str
    max_per_hour: int
    enabled: bool
    created_at: dt.datetime


class HealingPolicyCreate(BaseModel):
    name: str
    target_selector: dict | None = None
    allowed_actions: list[str] | None = None
    mode: str = "off"
    max_per_hour: int = 3
    enabled: bool = True
    tenant_id: str | None = None


class HealingPolicyUpdate(BaseModel):
    name: str | None = None
    target_selector: dict | None = None
    allowed_actions: list[str] | None = None
    mode: str | None = None
    max_per_hour: int | None = None
    enabled: bool | None = None


class HealingActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: str
    policy_id: int | None = None
    trigger: str | None = None
    target: str | None = None
    host_id: str | None = None
    container_id: str | None = None
    action: str
    outcome: str
    detail: str | None = None
    started_at: dt.datetime
    verified_at: dt.datetime | None = None


class HealResponse(BaseModel):
    ok: bool
    error: str | None = None
    detail: str | None = None
    action_id: int


# ----------------------------------------------------------------------
# healing policies
# ----------------------------------------------------------------------


@router.get("/healing-policies", response_model=list[HealingPolicyOut])
async def list_healing_policies(tenant_id: str | None = None) -> list[HealingPolicy]:
    async with SessionLocal() as session:
        stmt = select(HealingPolicy).order_by(HealingPolicy.id)
        if tenant_id is not None:
            stmt = stmt.where(HealingPolicy.tenant_id == tenant_id)
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows)


@router.post("/healing-policies", response_model=HealingPolicyOut, status_code=201)
async def create_healing_policy(body: HealingPolicyCreate) -> HealingPolicy:
    async with SessionLocal() as session:
        policy = HealingPolicy(
            tenant_id=body.tenant_id or settings.default_tenant,
            name=body.name,
            target_selector=body.target_selector,
            allowed_actions=body.allowed_actions,
            mode=body.mode,
            max_per_hour=body.max_per_hour,
            enabled=body.enabled,
        )
        session.add(policy)
        await session.commit()
        await session.refresh(policy)
        return policy


@router.put("/healing-policies/{policy_id}", response_model=HealingPolicyOut)
async def update_healing_policy(policy_id: int, body: HealingPolicyUpdate) -> HealingPolicy:
    async with SessionLocal() as session:
        policy = await session.get(HealingPolicy, policy_id)
        if policy is None:
            raise HTTPException(status_code=404, detail="Healing policy not found")
        updates = body.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(policy, field, value)
        await session.commit()
        await session.refresh(policy)
        return policy


@router.delete("/healing-policies/{policy_id}", status_code=204)
async def delete_healing_policy(policy_id: int):
    async with SessionLocal() as session:
        policy = await session.get(HealingPolicy, policy_id)
        if policy is None:
            raise HTTPException(status_code=404, detail="Healing policy not found")
        await session.delete(policy)
        await session.commit()


# ----------------------------------------------------------------------
# healing actions (audit trail)
# ----------------------------------------------------------------------


@router.get("/healing-actions", response_model=list[HealingActionOut])
async def list_healing_actions(
    container_id: str | None = None,
    tenant_id: str | None = None,
    limit: int = 100,
) -> list[HealingAction]:
    async with SessionLocal() as session:
        stmt = select(HealingAction).order_by(HealingAction.started_at.desc()).limit(limit)
        if container_id is not None:
            stmt = stmt.where(HealingAction.container_id == container_id)
        if tenant_id is not None:
            stmt = stmt.where(HealingAction.tenant_id == tenant_id)
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows)


# ----------------------------------------------------------------------
# manual heal (always allowed, bypasses policy mode)
# ----------------------------------------------------------------------


@router.post("/containers/{container_id}/heal", response_model=HealResponse)
async def heal_container(container_id: str) -> HealResponse:
    async with SessionLocal() as session:
        container = await session.get(Container, container_id)
        if container is None:
            raise HTTPException(status_code=404, detail="Container not found")

        result = await send_command(
            bus, container.tenant_id, container.host_id, "restart", container_id=container_id
        )
        outcome = "fixed" if result.get("ok") else "failed"
        action = HealingAction(
            tenant_id=container.tenant_id,
            policy_id=None,
            trigger="manual",
            target=container_id,
            host_id=container.host_id,
            container_id=container_id,
            action="restart",
            outcome=outcome,
            detail=result.get("error") or result.get("detail"),
        )
        session.add(action)
        await session.commit()
        await session.refresh(action)

        return HealResponse(
            ok=bool(result.get("ok")),
            error=result.get("error"),
            detail=result.get("detail"),
            action_id=action.id,
        )
