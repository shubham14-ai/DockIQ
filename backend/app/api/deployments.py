"""Deployment & Release API (Phase 6 Deployment & Release layer).

Router is included by ``main.py`` (wiring left to the caller — see report).
Pydantic request/response models are defined locally rather than in
``app/api/schemas.py`` since that file is outside this layer's allowed write
path.
"""
from __future__ import annotations

import datetime as dt
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.core.config import settings
from app.engines.deployment.service import DeploymentError, deploy, rollback
from app.store.db import SessionLocal
from app.store.models import Container, Deployment, Release

log = logging.getLogger("dockiq.api.deployments")

router = APIRouter(tags=["deployments"])


# ----------------------------------------------------------------------
# schemas
# ----------------------------------------------------------------------


class DeploymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: str
    service: str
    host_id: str | None = None
    container_id: str | None = None
    from_version: str | None = None
    to_version: str | None = None
    image_ref: str | None = None
    strategy: str
    trigger: str
    status: str
    risk_score: str | None = None
    risk_reasons: dict | None = None
    detail: dict | None = None
    initiated_by: str | None = None
    started_at: dt.datetime
    finished_at: dt.datetime | None = None


class ReleaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: str
    service: str
    version: str | None = None
    image_ref: str | None = None
    deployment_id: int | None = None
    known_good: bool
    deployed_at: dt.datetime


class DeployRequest(BaseModel):
    target: str
    image: str
    strategy: str = "rolling"
    tenant_id: str | None = None


class WebhookResponse(BaseModel):
    ok: bool
    note: str | None = None
    deployment: dict | None = None


# ----------------------------------------------------------------------
# deployments
# ----------------------------------------------------------------------


@router.post("/deployments", response_model=DeploymentOut)
async def create_deployment(body: DeployRequest) -> Deployment:
    tenant_id = body.tenant_id or settings.default_tenant
    try:
        result = await deploy(
            tenant_id,
            body.target,
            body.image,
            strategy=body.strategy,
            initiated_by="api",
        )
    except DeploymentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async with SessionLocal() as session:
        dep = await session.get(Deployment, result["id"])
        if dep is None:
            raise HTTPException(status_code=500, detail="deployment vanished")
        return dep


@router.get("/deployments", response_model=list[DeploymentOut])
async def list_deployments(
    service: str | None = None,
    tenant_id: str | None = None,
    limit: int = 50,
) -> list[Deployment]:
    async with SessionLocal() as session:
        stmt = select(Deployment).order_by(Deployment.started_at.desc()).limit(limit)
        if service is not None:
            stmt = stmt.where(Deployment.service == service)
        if tenant_id is not None:
            stmt = stmt.where(Deployment.tenant_id == tenant_id)
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows)


@router.get("/deployments/{deployment_id}", response_model=DeploymentOut)
async def get_deployment(deployment_id: int) -> Deployment:
    async with SessionLocal() as session:
        dep = await session.get(Deployment, deployment_id)
        if dep is None:
            raise HTTPException(status_code=404, detail="Deployment not found")
        return dep


@router.post("/deployments/{deployment_id}/rollback", response_model=DeploymentOut)
async def rollback_deployment(deployment_id: int) -> Deployment:
    async with SessionLocal() as session:
        original = await session.get(Deployment, deployment_id)
        if original is None:
            raise HTTPException(status_code=404, detail="Deployment not found")
        tenant_id = original.tenant_id

    try:
        result = await rollback(tenant_id, deployment_id)
    except DeploymentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async with SessionLocal() as session:
        dep = await session.get(Deployment, result["id"])
        if dep is None:
            raise HTTPException(status_code=500, detail="rollback deployment vanished")
        return dep


# ----------------------------------------------------------------------
# releases (version history)
# ----------------------------------------------------------------------


@router.get("/releases", response_model=list[ReleaseOut])
async def list_releases(
    service: str | None = None,
    tenant_id: str | None = None,
    limit: int = 50,
) -> list[Release]:
    async with SessionLocal() as session:
        stmt = select(Release).order_by(Release.deployed_at.desc()).limit(limit)
        if service is not None:
            stmt = stmt.where(Release.service == service)
        if tenant_id is not None:
            stmt = stmt.where(Release.tenant_id == tenant_id)
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows)


# ----------------------------------------------------------------------
# webhooks
# ----------------------------------------------------------------------

_VALID_PROVIDERS = {"github", "gitlab", "dockerhub", "registry"}


def _repo_from_image(image: str) -> str:
    """Strip a tag/digest off ``image`` to get its repo, for matching against
    running containers' image_ref."""
    ref = image.split("@", 1)[0]
    # Only strip a trailing :tag, not a port in a registry host (e.g.
    # myregistry:5000/app:tag) — only consider the last path segment.
    last_slash = ref.rfind("/")
    tail = ref[last_slash + 1 :]
    if ":" in tail:
        ref = ref[: last_slash + 1] + tail.rsplit(":", 1)[0]
    return ref


def _parse_webhook_image(provider: str, body: dict) -> str | None:
    """Best-effort, defensive extraction of an image reference from a
    provider webhook payload. Returns None if nothing usable is found."""
    try:
        if provider == "dockerhub":
            push_data = body.get("push_data") or {}
            repo = body.get("repository") or {}
            repo_name = repo.get("repo_name") or repo.get("name")
            tag = push_data.get("tag")
            if repo_name and tag:
                return f"{repo_name}:{tag}"
            if repo_name:
                return repo_name

        elif provider == "registry":
            # Generic registry notification / custom payload.
            events = body.get("events")
            if isinstance(events, list) and events:
                target = (events[0] or {}).get("target") or {}
                repo = target.get("repository")
                tag = target.get("tag")
                if repo and tag:
                    return f"{repo}:{tag}"
                if repo:
                    return repo

        elif provider == "github":
            # GitHub package/registry-style payload (best-effort).
            pkg = body.get("package") or {}
            version = pkg.get("package_version") or {}
            image_uri = version.get("package_url") or version.get("name")
            if image_uri:
                return image_uri

        elif provider == "gitlab":
            # GitLab container registry event (best-effort).
            reg = body.get("registry") or body.get("container_registry") or {}
            image_uri = reg.get("path") or reg.get("image")
            if image_uri:
                return image_uri

        # Generic fallback usable by any provider.
        if body.get("image"):
            return body["image"]
        if body.get("image_ref"):
            return body["image_ref"]
    except Exception:  # noqa: BLE001 — parsing is best-effort, never raise
        log.exception("webhook: failed to parse payload for provider %s", provider)
        return None
    return None


async def _find_service_for_image(image: str) -> tuple[str, str] | None:
    """Match ``image``'s repo against a running container's image repo.

    Returns (target, tenant_id) or None if no match found.
    """
    repo = _repo_from_image(image)
    if not repo:
        return None
    async with SessionLocal() as session:
        stmt = select(Container).where(Container.state == "running")
        rows = (await session.execute(stmt)).scalars().all()
        for row in rows:
            if not row.image_ref:
                continue
            if _repo_from_image(row.image_ref) == repo:
                return (row.compose_service or row.name, row.tenant_id)
    return None


@router.post("/webhooks/{provider}", response_model=WebhookResponse, status_code=202)
async def handle_webhook(provider: str, request: Request) -> WebhookResponse:
    if provider not in _VALID_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown provider {provider!r}")

    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:  # noqa: BLE001 — tolerate malformed/empty bodies
        body = {}

    image = _parse_webhook_image(provider, body)
    if not image:
        return WebhookResponse(ok=False, note="could not parse image reference from payload")

    match = await _find_service_for_image(image)
    if match is None:
        return WebhookResponse(
            ok=False, note=f"no running container matches image {image!r}"
        )
    target, tenant_id = match

    try:
        result = await deploy(
            tenant_id,
            target,
            image,
            strategy="rolling",
            initiated_by=f"webhook:{provider}",
            trigger="webhook",
        )
    except DeploymentError as exc:
        return WebhookResponse(ok=False, note=str(exc))

    return WebhookResponse(ok=True, deployment=result)
