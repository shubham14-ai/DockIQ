from __future__ import annotations

import hmac
import logging
import secrets
import uuid

from fastapi import APIRouter, HTTPException

from app.api.schemas import EnrollRequest, EnrollResponse
from app.core.config import settings
from app.store.db import SessionLocal
from app.store.models import Host, Tenant

log = logging.getLogger("dockiq.agents")

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/enroll", response_model=EnrollResponse)
async def enroll(req: EnrollRequest) -> EnrollResponse:
    """Enroll a new agent.

    Gated by the shared ``AGENT_JOIN_TOKEN`` when configured (Phase 7). Issues a
    host_id and returns the NATS address + heartbeat subject the agent publishes
    on. (mTLS client certs are a later enhancement.)
    """
    if settings.agent_join_token:
        if not req.join_token or not hmac.compare_digest(req.join_token, settings.agent_join_token):
            raise HTTPException(status_code=401, detail="invalid or missing agent join token")

    tenant_id = req.tenant_id or settings.default_tenant
    host_id = uuid.uuid4().hex
    token = secrets.token_urlsafe(24)

    async with SessionLocal() as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            session.add(Tenant(id=tenant_id, name=tenant_id))

        session.add(
            Host(
                id=host_id,
                tenant_id=tenant_id,
                name=req.host_name,
                agent_status="enrolling",
            )
        )
        await session.commit()

    subject = f"dockiq.{tenant_id}.{host_id}.heartbeat"
    log.info("enrolled host %s (%s) for tenant %s", req.host_name, host_id, tenant_id)

    return EnrollResponse(
        host_id=host_id,
        tenant_id=tenant_id,
        nats_url=settings.nats_advertise_url,
        heartbeat_subject=subject,
        token=token,
    )
