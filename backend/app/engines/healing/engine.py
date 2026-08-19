"""Self-Healing Engine (Phase 5).

Consumes ``health``, ``events``, and ``alerts`` telemetry to detect trigger
conditions (unhealthy status, OOM kill, crash loop, or a down/unhealthy
alert) and, if a matching ``HealingPolicy`` allows it, sends a ``restart``
command to the affected container's agent via ``app.agents.commander``.

Safety model (see docs/engines/08-self-healing-engine.md):
    - Only the ``restart`` rung is in scope this phase.
    - A policy only acts if ``mode == "auto"`` AND ``"restart"`` is in
      ``allowed_actions`` AND the container is under ``max_per_hour``
      (counted from ``HealingAction`` rows in the last hour).
    - No matching policy, or policy ``mode == "off"``, means NOTHING is
      recorded and NOTHING is done — default-safe.
    - The single seeded default policy ships with ``mode="off"``, so nothing
      auto-heals until an operator explicitly turns it on.
    - Manual heals (``POST /containers/{id}/heal`` in app/api/healing.py)
      bypass policy entirely — they are an explicit operator action.

Kept exception-safe throughout: any handler exception is caught so the
shared NATS consumer loop (see ``app.engines.registry``) stays alive.
"""
from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict, deque
from typing import Any

from sqlalchemy import func, select

from app.agents.commander import send_command
from app.bus.subjects import EVENTS, HEALTH, wildcard
from app.core.config import settings
from app.engines.base import BaseEngine, EngineContext
from app.store.db import SessionLocal
from app.store.models import Container, HealingAction, HealingPolicy, Tenant

log = logging.getLogger("dockiq.engine.healing")

CRASH_LOOP_MIN_STARTS = 3
CRASH_LOOP_WINDOW_SECONDS = 300


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_time(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, str):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return _now()


class HealingEngine(BaseEngine):
    name = "healing"

    def __init__(self) -> None:
        super().__init__()
        # crash-loop heuristic: (tenant, container_id) -> deque[datetime] of `start` events
        self._start_events: dict[tuple[str, str], deque[dt.datetime]] = defaultdict(
            lambda: deque(maxlen=20)
        )

    def subjects(self) -> list[str]:
        return [wildcard(HEALTH), wildcard(EVENTS), "dockiq.*.alerts"]

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def start(self, ctx: EngineContext) -> None:
        await super().start(ctx)
        try:
            await self._seed_default_policy()
        except Exception:  # noqa: BLE001
            self.log.exception("failed to seed default healing policy")

    async def stop(self) -> None:
        self._start_events.clear()

    async def _seed_default_policy(self) -> None:
        async with SessionLocal() as session:
            tenant_ids = (await session.execute(select(Tenant.id))).scalars().all()
            if not tenant_ids:
                tenant_ids = [settings.default_tenant]
            for tenant_id in tenant_ids:
                existing = (
                    await session.execute(
                        select(HealingPolicy.id).where(
                            HealingPolicy.tenant_id == tenant_id
                        )
                    )
                ).scalars().first()
                if existing is not None:
                    continue
                session.add(
                    HealingPolicy(
                        tenant_id=tenant_id,
                        name="default",
                        target_selector={},
                        allowed_actions=["restart"],
                        mode="off",
                        max_per_hour=3,
                    )
                )
                self.log.info("seeded default (off) healing policy for tenant %s", tenant_id)
            await session.commit()

    # ------------------------------------------------------------------
    # inline handlers
    # ------------------------------------------------------------------

    async def handle(self, subject: str, data: dict) -> None:
        try:
            parts = subject.split(".")
            # dockiq.<tenant>.<host>.<kind>  or  dockiq.<tenant>.alerts
            if len(parts) >= 4 and parts[3] in (HEALTH, EVENTS):
                kind = parts[3]
                if kind == HEALTH:
                    await self._handle_health(data)
                else:
                    await self._handle_event(data)
            elif len(parts) == 3 and parts[2] == "alerts":
                await self._handle_alert(data)
        except Exception:  # noqa: BLE001 — keep consumer alive
            self.log.exception("error handling healing message on %s", subject)

    async def _handle_health(self, data: dict) -> None:
        if data.get("status") != "unhealthy":
            return
        tenant = data.get("tenant_id", settings.default_tenant)
        container_id = data.get("container_id")
        host_id = data.get("host_id")
        if not container_id or not host_id:
            return
        await self._on_trigger(
            tenant=tenant,
            trigger="unhealthy",
            container_id=container_id,
            host_id=host_id,
        )

    async def _handle_event(self, data: dict) -> None:
        tenant = data.get("tenant_id", settings.default_tenant)
        container_id = data.get("container_id")
        host_id = data.get("host_id")
        etype = data.get("type")

        if etype == "oom":
            if not container_id or not host_id:
                return
            await self._on_trigger(
                tenant=tenant,
                trigger="oom",
                container_id=container_id,
                host_id=host_id,
            )
        elif etype == "start":
            if not container_id or not host_id:
                return
            key = (tenant, container_id)
            when = _parse_time(data.get("time"))
            dq = self._start_events[key]
            dq.append(when)
            cutoff = _now() - dt.timedelta(seconds=CRASH_LOOP_WINDOW_SECONDS)
            recent = [t for t in dq if t >= cutoff]
            if len(recent) >= CRASH_LOOP_MIN_STARTS:
                await self._on_trigger(
                    tenant=tenant,
                    trigger="crash_loop",
                    container_id=container_id,
                    host_id=host_id,
                )

    async def _handle_alert(self, data: dict) -> None:
        # Alerts published by AlertEngine (dockiq.<tenant>.alerts). Only act on
        # newly firing/updated down/unhealthy-style alerts that carry the
        # container/host identity we need.
        if data.get("lifecycle") not in ("fired", "updated"):
            return
        labels = data.get("labels") or {}
        summary = (data.get("summary") or "").lower()
        rule_key = (labels.get("rule_key") or "").lower()
        if not any(k in rule_key or k in summary for k in ("unhealthy", "down", "crash")):
            return
        container_id = labels.get("container_id") or data.get("target")
        host_id = labels.get("host_id")
        tenant = data.get("tenant_id", settings.default_tenant)
        if not container_id or not host_id:
            return
        await self._on_trigger(
            tenant=tenant,
            trigger="alert",
            container_id=container_id,
            host_id=host_id,
        )

    # ------------------------------------------------------------------
    # policy evaluation + action
    # ------------------------------------------------------------------

    async def _on_trigger(
        self, *, tenant: str, trigger: str, container_id: str, host_id: str
    ) -> None:
        async with SessionLocal() as session:
            policy = await self._match_policy(session, tenant)
            if policy is None or policy.mode != "auto":
                # No policy, or policy explicitly off/semi: default-safe, do nothing.
                return

            allowed_actions = policy.allowed_actions or []
            if "restart" not in allowed_actions:
                return

            hour_ago = _now() - dt.timedelta(hours=1)
            count = (
                await session.execute(
                    select(func.count(HealingAction.id)).where(
                        HealingAction.tenant_id == tenant,
                        HealingAction.container_id == container_id,
                        HealingAction.started_at >= hour_ago,
                    )
                )
            ).scalar_one()
            if count >= (policy.max_per_hour or 0):
                self.log.info(
                    "healing rate-limited: container=%s count=%d max=%d",
                    container_id, count, policy.max_per_hour,
                )
                return

            self.log.info(
                "healing trigger=%s container=%s host=%s -> restart",
                trigger, container_id, host_id,
            )

            if self.ctx is None:
                return
            result = await send_command(
                self.ctx.bus, tenant, host_id, "restart", container_id=container_id
            )
            outcome = "fixed" if result.get("ok") else "failed"
            session.add(
                HealingAction(
                    tenant_id=tenant,
                    policy_id=policy.id,
                    trigger=trigger,
                    target=container_id,
                    host_id=host_id,
                    container_id=container_id,
                    action="restart",
                    outcome=outcome,
                    detail=result.get("error") or result.get("detail"),
                )
            )
            await session.commit()

    async def _match_policy(self, session, tenant: str) -> HealingPolicy | None:
        """Return the first enabled policy for the tenant.

        ``target_selector`` matching is intentionally simple for this phase
        (empty selector == matches everything); richer selector matching can
        be layered on later without changing the safety gates above.
        """
        rows = (
            await session.execute(
                select(HealingPolicy)
                .where(HealingPolicy.tenant_id == tenant, HealingPolicy.enabled.is_(True))
                .order_by(HealingPolicy.id)
            )
        ).scalars().all()
        return rows[0] if rows else None
