from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict


class EnrollRequest(BaseModel):
    host_name: str
    tenant_id: str | None = None
    join_token: str | None = None


class EnrollResponse(BaseModel):
    host_id: str
    tenant_id: str
    nats_url: str
    heartbeat_subject: str
    token: str


class HostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    agent_status: str
    last_heartbeat: dt.datetime | None = None
    agent_version: str | None = None
    os: str | None = None
    arch: str | None = None
    docker_version: str | None = None
