"""Deployment service — MANUAL single-container rolling deploy.

Scope for Phase 6 (see docs/deployment/01-deployment-layer.md,
02-strategies.md, 03-rollback-and-healing.md): a "rolling" deploy here means
recreating the target container with a new image via the command bus
(``app.agents.commander.send_command``), then validating the recreate
succeeded, and — on failure — automatically rolling back to the last known
good image. Version history is tracked via the ``Release`` table.

Blue-green, canary, drift detection and risk scoring are out of scope and
land in a later phase.

These are plain async functions (not a ``BaseEngine``) invoked directly by
``app/api/deployments.py``.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from sqlalchemy import select

from app.agents.commander import send_command
from app.bus.nats_bus import bus
from app.core.config import settings
from app.store.db import SessionLocal
from app.store.models import Container, Deployment, Release

log = logging.getLogger("dockiq.deployment")

# How long to wait after issuing a recreate before we consider the container
# "settled" enough to record the outcome. The commander's recreate command
# itself waits for the container to come back up (per timeout_secs) before
# replying, so this is a small extra grace period, not the primary check.
POST_RECREATE_SETTLE_SECS = 5
RECREATE_TIMEOUT_SECS = 60


class DeploymentError(Exception):
    """Raised for user-facing errors (bad target, no rollback target, ...)."""


async def _resolve_target(session, tenant_id: str, target: str) -> Container:
    """Resolve ``target`` to a Container: by id, then name, then compose_service."""
    container = await session.get(Container, target)
    if container is not None and container.tenant_id == tenant_id:
        return container

    stmt = select(Container).where(
        Container.tenant_id == tenant_id, Container.name == target
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is not None:
        return row

    # Match by compose_service — prefer a running instance.
    stmt = select(Container).where(
        Container.tenant_id == tenant_id, Container.compose_service == target
    )
    rows = (await session.execute(stmt)).scalars().all()
    if rows:
        for row in rows:
            if row.state == "running":
                return row
        return rows[0]

    raise DeploymentError(f"no container found matching target {target!r}")


def _service_name(container: Container) -> str:
    return container.compose_service or container.name


async def _ensure_known_good(
    session, tenant_id: str, service: str, image_ref: str | None
) -> None:
    """Record the CURRENT image as a known-good release if not already present."""
    if not image_ref:
        return
    stmt = select(Release).where(
        Release.tenant_id == tenant_id,
        Release.service == service,
        Release.image_ref == image_ref,
    )
    existing = (await session.execute(stmt)).scalars().first()
    if existing is not None:
        if not existing.known_good:
            existing.known_good = True
        return
    session.add(
        Release(
            tenant_id=tenant_id,
            service=service,
            version=image_ref,
            image_ref=image_ref,
            deployment_id=None,
            known_good=True,
        )
    )


async def _latest_known_good(
    session, tenant_id: str, service: str, exclude_image_ref: str | None = None
) -> Release | None:
    stmt = (
        select(Release)
        .where(
            Release.tenant_id == tenant_id,
            Release.service == service,
            Release.known_good.is_(True),
        )
        .order_by(Release.deployed_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    for row in rows:
        if exclude_image_ref is None or row.image_ref != exclude_image_ref:
            return row
    return None


def _deployment_dict(dep: Deployment) -> dict:
    return {
        "id": dep.id,
        "tenant_id": dep.tenant_id,
        "service": dep.service,
        "host_id": dep.host_id,
        "container_id": dep.container_id,
        "from_version": dep.from_version,
        "to_version": dep.to_version,
        "image_ref": dep.image_ref,
        "strategy": dep.strategy,
        "trigger": dep.trigger,
        "status": dep.status,
        "detail": dep.detail,
        "initiated_by": dep.initiated_by,
        "started_at": dep.started_at.isoformat() if dep.started_at else None,
        "finished_at": dep.finished_at.isoformat() if dep.finished_at else None,
    }


async def deploy(
    tenant_id: str,
    target: str,
    image: str,
    strategy: str = "rolling",
    initiated_by: str = "api",
    trigger: str = "manual",
) -> dict:
    """Deploy ``image`` onto the container/service resolved from ``target``.

    Recreates the container via the command bus, waits briefly, and checks
    the outcome. On failure, automatically rolls back to the last known-good
    image for the service.
    """
    tenant_id = tenant_id or settings.default_tenant

    async with SessionLocal() as session:
        container = await _resolve_target(session, tenant_id, target)
        service = _service_name(container)
        current_image = container.image_ref
        host_id = container.host_id
        container_id = container.id
        # Target recreate by NAME (stable across recreate — the id changes).
        container_name = container.name

        deployment = Deployment(
            tenant_id=tenant_id,
            service=service,
            host_id=host_id,
            container_id=container_id,
            from_version=current_image,
            to_version=image,
            image_ref=image,
            strategy=strategy,
            trigger=trigger,
            status="deploying",
            initiated_by=initiated_by,
        )
        session.add(deployment)
        await _ensure_known_good(session, tenant_id, service, current_image)
        await session.commit()
        await session.refresh(deployment)

    log.info(
        "deploy: tenant=%s service=%s target=%s %s -> %s",
        tenant_id, service, target, current_image, image,
    )

    result = await send_command(
        bus,
        tenant_id,
        host_id,
        "recreate",
        container_id=container_name,
        image=image,
        timeout_secs=RECREATE_TIMEOUT_SECS,
    )

    await asyncio.sleep(POST_RECREATE_SETTLE_SECS)

    async with SessionLocal() as session:
        deployment = await session.get(Deployment, deployment.id)

        if result.get("ok"):
            deployment.status = "promoted"
            deployment.detail = {"container_name": container_name, "recreate": result}
            deployment.finished_at = dt.datetime.now(dt.timezone.utc)
            session.add(
                Release(
                    tenant_id=tenant_id,
                    service=service,
                    version=image,
                    image_ref=image,
                    deployment_id=deployment.id,
                    known_good=True,
                )
            )
            await session.commit()
            await session.refresh(deployment)
            log.info("deploy %s promoted (%s -> %s)", deployment.id, service, image)
            return _deployment_dict(deployment)

        # Recreate failed — attempt automatic rollback to the last known good
        # image for this service (excluding the image we just tried).
        log.warning(
            "deploy %s recreate failed for %s: %s — attempting rollback",
            deployment.id, service, result.get("error"),
        )
        prior = await _latest_known_good(session, tenant_id, service, exclude_image_ref=image)

        detail: dict = {"container_name": container_name, "recreate": result}

        if prior is None:
            deployment.status = "failed"
            detail["rollback"] = {"ok": False, "error": "no known-good release to roll back to"}
            deployment.detail = detail
            deployment.finished_at = dt.datetime.now(dt.timezone.utc)
            await session.commit()
            await session.refresh(deployment)
            return _deployment_dict(deployment)

        rollback_result = await send_command(
            bus,
            tenant_id,
            host_id,
            "recreate",
            container_id=container_name,
            image=prior.image_ref,
            timeout_secs=RECREATE_TIMEOUT_SECS,
        )
        detail["rollback"] = {"to": prior.image_ref, "result": rollback_result}
        deployment.detail = detail
        deployment.status = "rolledback" if rollback_result.get("ok") else "failed"
        deployment.finished_at = dt.datetime.now(dt.timezone.utc)
        await session.commit()
        await session.refresh(deployment)
        log.info(
            "deploy %s status=%s (rollback to %s ok=%s)",
            deployment.id, deployment.status, prior.image_ref, rollback_result.get("ok"),
        )
        return _deployment_dict(deployment)


async def rollback(tenant_id: str, deployment_id: int) -> dict:
    """Roll a service back to the last known-good release prior to ``deployment_id``."""
    tenant_id = tenant_id or settings.default_tenant

    async with SessionLocal() as session:
        original = await session.get(Deployment, deployment_id)
        if original is None or original.tenant_id != tenant_id:
            raise DeploymentError(f"deployment {deployment_id} not found")

        service = original.service
        host_id = original.host_id
        container_id = original.container_id
        # Prefer the stable container name captured at deploy time; the id may
        # be stale after a prior recreate.
        container_name = (original.detail or {}).get("container_name") or container_id

        stmt = (
            select(Release)
            .where(
                Release.tenant_id == tenant_id,
                Release.service == service,
                Release.known_good.is_(True),
                Release.deployed_at < original.started_at,
            )
            .order_by(Release.deployed_at.desc())
        )
        prior = (await session.execute(stmt)).scalars().first()
        if prior is None:
            # Fall back to any known-good release that isn't the deployment's
            # own target image.
            prior = await _latest_known_good(
                session, tenant_id, service, exclude_image_ref=original.to_version
            )
        if prior is None:
            raise DeploymentError(f"no known-good release found for service {service!r}")

        if host_id is None or container_id is None:
            raise DeploymentError("original deployment has no host/container to target")

        new_deployment = Deployment(
            tenant_id=tenant_id,
            service=service,
            host_id=host_id,
            container_id=container_id,
            from_version=original.to_version,
            to_version=prior.image_ref,
            image_ref=prior.image_ref,
            strategy=original.strategy,
            trigger="manual",
            status="deploying",
            initiated_by="rollback",
            detail={"rollback_of": deployment_id, "container_name": container_name},
        )
        session.add(new_deployment)
        await session.commit()
        await session.refresh(new_deployment)

    result = await send_command(
        bus,
        tenant_id,
        host_id,
        "recreate",
        container_id=container_name,
        image=prior.image_ref,
        timeout_secs=RECREATE_TIMEOUT_SECS,
    )

    async with SessionLocal() as session:
        new_deployment = await session.get(Deployment, new_deployment.id)
        new_deployment.status = "rolledback" if result.get("ok") else "failed"
        new_deployment.detail = {**(new_deployment.detail or {}), "recreate": result}
        new_deployment.finished_at = dt.datetime.now(dt.timezone.utc)
        if result.get("ok"):
            session.add(
                Release(
                    tenant_id=tenant_id,
                    service=service,
                    version=prior.image_ref,
                    image_ref=prior.image_ref,
                    deployment_id=new_deployment.id,
                    known_good=True,
                )
            )
        await session.commit()
        await session.refresh(new_deployment)
        log.info(
            "rollback of deployment %s -> new deployment %s status=%s",
            deployment_id, new_deployment.id, new_deployment.status,
        )
        return _deployment_dict(new_deployment)
