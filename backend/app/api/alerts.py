"""Alerts + alert-rules API (Phase 1 Alert Engine).

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

from app.core.config import settings
from app.store.db import SessionLocal
from app.store.models import Alert, AlertRule

router = APIRouter(tags=["alerts"])


# ----------------------------------------------------------------------
# schemas
# ----------------------------------------------------------------------


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: str
    rule_id: int | None = None
    target: str | None = None
    state: str
    severity: str
    summary: str | None = None
    labels: dict | None = None
    value: float | None = None
    count: int
    started_at: dt.datetime
    acked_at: dt.datetime | None = None
    resolved_at: dt.datetime | None = None


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: str
    name: str
    target_selector: dict | None = None
    condition: dict
    for_seconds: int
    severity: str
    actions: dict | None = None
    enabled: bool
    source: str
    created_at: dt.datetime


class AlertRuleCreate(BaseModel):
    name: str
    target_selector: dict | None = None
    condition: dict
    for_seconds: int = 0
    severity: str = "warning"
    actions: dict | None = None
    enabled: bool = True
    tenant_id: str | None = None


class AckResponse(BaseModel):
    id: int
    state: str
    acked_at: dt.datetime | None = None


# ----------------------------------------------------------------------
# alerts
# ----------------------------------------------------------------------


@router.get("/alerts", response_model=list[AlertOut])
async def list_alerts(
    state: str | None = None,
    severity: str | None = None,
    tenant_id: str | None = None,
) -> list[Alert]:
    async with SessionLocal() as session:
        stmt = select(Alert).order_by(Alert.started_at.desc())
        if state is not None:
            stmt = stmt.where(Alert.state == state)
        if severity is not None:
            stmt = stmt.where(Alert.severity == severity)
        if tenant_id is not None:
            stmt = stmt.where(Alert.tenant_id == tenant_id)
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows)


@router.post("/alerts/{alert_id}/ack", response_model=AckResponse)
async def ack_alert(alert_id: int) -> Alert:
    async with SessionLocal() as session:
        alert = await session.get(Alert, alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail="Alert not found")
        if alert.state not in ("pending", "firing"):
            raise HTTPException(
                status_code=409, detail=f"Cannot ack alert in state {alert.state!r}"
            )
        alert.state = "acked"
        alert.acked_at = dt.datetime.now(dt.timezone.utc)
        await session.commit()
        await session.refresh(alert)
        return alert


# ----------------------------------------------------------------------
# alert rules
# ----------------------------------------------------------------------


@router.get("/alert-rules", response_model=list[AlertRuleOut])
async def list_alert_rules(tenant_id: str | None = None) -> list[AlertRule]:
    async with SessionLocal() as session:
        stmt = select(AlertRule).order_by(AlertRule.id)
        if tenant_id is not None:
            stmt = stmt.where(AlertRule.tenant_id == tenant_id)
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows)


@router.post("/alert-rules", response_model=AlertRuleOut, status_code=201)
async def create_alert_rule(body: AlertRuleCreate) -> AlertRule:
    async with SessionLocal() as session:
        rule = AlertRule(
            tenant_id=body.tenant_id or settings.default_tenant,
            name=body.name,
            target_selector=body.target_selector,
            condition=body.condition,
            for_seconds=body.for_seconds,
            severity=body.severity,
            actions=body.actions,
            enabled=body.enabled,
            source="user",
        )
        session.add(rule)
        await session.commit()
        await session.refresh(rule)
        return rule


@router.delete("/alert-rules/{rule_id}", status_code=204)
async def delete_alert_rule(rule_id: int):
    async with SessionLocal() as session:
        rule = await session.get(AlertRule, rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="Alert rule not found")
        await session.delete(rule)
        await session.commit()
