"""Discovery Engine.

Consumes ``discovery`` inventory snapshots and ``events`` lifecycle messages,
maintaining the authoritative ``containers`` inventory + ``events`` timeline.

See docs/phase1-agent-protocol.md for the exact payload contracts and
docs/engines/01-discovery-engine.md for the design.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.bus.subjects import DISCOVERY, EVENTS, wildcard
from app.engines.base import BaseEngine, EngineContext
from app.store.db import SessionLocal
from app.store.models import Container, Event

log = logging.getLogger("dockiq.engine.discovery")

# Event types that map to a container state transition. Anything not in this
# map leaves the container's stored state untouched.
_EVENT_STATE = {
    "create": "created",
    "start": "running",
    "stop": "exited",
    "die": "exited",
    "kill": "exited",
    "oom": "exited",
}


class DiscoveryEngine(BaseEngine):
    name = "discovery"

    def subjects(self) -> list[str]:
        return [wildcard(DISCOVERY), wildcard(EVENTS)]

    async def start(self, ctx: EngineContext) -> None:
        await super().start(ctx)
        self.log.info("discovery engine started")

    async def handle(self, subject: str, data: dict) -> None:
        kind = subject.split(".")[-1]
        if kind == DISCOVERY:
            await self._handle_snapshot(data)
        elif kind == EVENTS:
            await self._handle_event(data)
        else:
            self.log.debug("ignoring subject %s", subject)

    async def stop(self) -> None:
        self.log.info("discovery engine stopped")

    # -- snapshot (inventory) -------------------------------------------------

    async def _handle_snapshot(self, data: dict) -> None:
        tenant_id = data.get("tenant_id")
        host_id = data.get("host_id")
        containers = data.get("containers") or []
        if not tenant_id or not host_id:
            self.log.warning("discovery snapshot missing tenant_id/host_id, dropping")
            return

        async with SessionLocal() as session:
            for c in containers:
                container_id = c.get("id")
                if not container_id:
                    continue
                await self._upsert_container(session, tenant_id, host_id, c)
            await session.commit()

        self.log.debug(
            "processed discovery snapshot host=%s containers=%d", host_id, len(containers)
        )

    async def _upsert_container(
        self, session, tenant_id: str, host_id: str, c: dict
    ) -> None:
        ports = c.get("ports")
        values = dict(
            id=c["id"],
            tenant_id=tenant_id,
            host_id=host_id,
            name=c.get("name") or c["id"][:12],
            image_ref=c.get("image"),
            image_digest=c.get("image_digest"),
            state=c.get("state"),
            status=c.get("status"),
            command=c.get("command"),
            compose_project=c.get("compose_project"),
            compose_service=c.get("compose_service"),
            labels=c.get("labels") or {},
            env=c.get("env") or {},
            ports=ports or {},
            mounts=c.get("mounts") or [],
            networks=c.get("networks") or [],
            native_health=c.get("health"),
        )
        stmt = pg_insert(Container).values(**values)
        update_cols = {k: stmt.excluded[k] for k in values if k != "id"}
        update_cols["last_seen"] = func.now()
        stmt = stmt.on_conflict_do_update(index_elements=[Container.id], set_=update_cols)
        await session.execute(stmt)

    # -- lifecycle events -------------------------------------------------------

    async def _handle_event(self, data: dict) -> None:
        tenant_id = data.get("tenant_id")
        host_id = data.get("host_id")
        container_id = data.get("container_id")
        event_type = data.get("type")
        if not tenant_id or not event_type:
            self.log.warning("discovery event missing tenant_id/type, dropping")
            return

        detail = {
            "name": data.get("name"),
            "exit_code": data.get("exit_code"),
            "time": data.get("time"),
            "attributes": data.get("attributes") or {},
        }

        async with SessionLocal() as session:
            # Idempotency: skip if we've already recorded this exact event
            # (same host/container/type/time) — the agent may redeliver.
            if container_id and data.get("time"):
                existing = await session.execute(
                    select(Event.id).where(
                        Event.tenant_id == tenant_id,
                        Event.container_id == container_id,
                        Event.type == event_type,
                        Event.detail["time"].astext == data.get("time"),
                    )
                )
                if existing.scalar_one_or_none() is not None:
                    return

            session.add(
                Event(
                    tenant_id=tenant_id,
                    host_id=host_id,
                    container_id=container_id,
                    type=event_type,
                    detail=detail,
                )
            )

            new_state = _EVENT_STATE.get(event_type)
            if container_id and new_state:
                container = await session.get(Container, container_id)
                if container is not None:
                    container.state = new_state
                    if data.get("name"):
                        container.name = data["name"]

            await session.commit()
