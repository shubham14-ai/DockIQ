from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.schemas import HostOut
from app.store.db import SessionLocal
from app.store.models import Host

router = APIRouter(prefix="/hosts", tags=["hosts"])


@router.get("", response_model=list[HostOut])
async def list_hosts() -> list[Host]:
    async with SessionLocal() as session:
        rows = (await session.execute(select(Host).order_by(Host.name))).scalars().all()
        return list(rows)


@router.get("/{host_id}", response_model=HostOut)
async def get_host(host_id: str) -> Host:
    async with SessionLocal() as session:
        host = await session.get(Host, host_id)
        if host is None:
            raise HTTPException(status_code=404, detail="Host not found")
        return host
