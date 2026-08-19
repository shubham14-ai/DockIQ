"""Auth API (Phase 7): login, current user, user + API-key management."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.auth import security
from app.auth.deps import Principal, get_principal, require_role
from app.auth.roles import ROLES
from app.core.config import settings
from app.store.db import SessionLocal
from app.store.models import ApiKey, AuditLog, User

router = APIRouter(prefix="/auth", tags=["auth"])


# --- schemas -----------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    tenant_id: str
    username: str


class MeResponse(BaseModel):
    username: str
    role: str
    tenant_id: str
    kind: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"
    tenant_id: str | None = None


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    tenant_id: str
    enabled: bool


class CreateApiKeyRequest(BaseModel):
    name: str
    role: str = "viewer"
    tenant_id: str | None = None


class ApiKeyCreated(BaseModel):
    id: int
    name: str
    role: str
    api_key: str  # shown once


# --- audit helper ------------------------------------------------------------

async def _audit(session, tenant_id, actor, action, target=None, result="ok", detail=None):
    session.add(
        AuditLog(tenant_id=tenant_id, actor=actor, action=action, target=target, result=result, detail=detail)
    )


# --- endpoints ---------------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest) -> TokenResponse:
    async with SessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.username == req.username))
        ).scalars().first()
        if user is None or not user.enabled or not security.verify_password(req.password, user.password_hash):
            raise HTTPException(status_code=401, detail="invalid username or password")
        user.last_login = dt.datetime.now(dt.timezone.utc)
        await _audit(session, user.tenant_id, user.username, "auth.login")
        await session.commit()
        token = security.create_access_token(sub=user.username, tenant_id=user.tenant_id, role=user.role)
        return TokenResponse(access_token=token, role=user.role, tenant_id=user.tenant_id, username=user.username)


@router.get("/me", response_model=MeResponse)
async def me(principal: Principal = Depends(get_principal)) -> MeResponse:
    return MeResponse(username=principal.name, role=principal.role, tenant_id=principal.tenant_id, kind=principal.kind)


@router.get("/roles")
async def roles() -> dict:
    return {"roles": ROLES}


@router.get("/users", response_model=list[UserOut])
async def list_users(principal: Principal = Depends(require_role("admin"))) -> list[User]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(User).where(User.tenant_id == principal.tenant_id).order_by(User.username))
        ).scalars().all()
        return list(rows)


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(req: CreateUserRequest, principal: Principal = Depends(require_role("admin"))) -> User:
    if req.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"invalid role; must be one of {ROLES}")
    tenant_id = req.tenant_id or principal.tenant_id
    async with SessionLocal() as session:
        exists = (
            await session.execute(select(User).where(User.username == req.username))
        ).scalars().first()
        if exists is not None:
            raise HTTPException(status_code=409, detail="username already exists")
        user = User(
            tenant_id=tenant_id,
            username=req.username,
            password_hash=security.hash_password(req.password),
            role=req.role,
        )
        session.add(user)
        await _audit(session, tenant_id, principal.name, "user.create", target=req.username)
        await session.commit()
        await session.refresh(user)
        return user


@router.get("/api-keys")
async def list_api_keys(principal: Principal = Depends(require_role("admin"))) -> list[dict]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(ApiKey).where(ApiKey.tenant_id == principal.tenant_id))
        ).scalars().all()
        return [
            {"id": k.id, "name": k.name, "role": k.role, "prefix": k.prefix, "enabled": k.enabled, "last_used": k.last_used}
            for k in rows
        ]


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(req: CreateApiKeyRequest, principal: Principal = Depends(require_role("admin"))) -> ApiKeyCreated:
    if req.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"invalid role; must be one of {ROLES}")
    tenant_id = req.tenant_id or principal.tenant_id
    full, prefix, key_hash = security.generate_api_key()
    async with SessionLocal() as session:
        key = ApiKey(
            tenant_id=tenant_id, name=req.name, prefix=prefix, key_hash=key_hash,
            role=req.role, created_by=principal.name,
        )
        session.add(key)
        await _audit(session, tenant_id, principal.name, "apikey.create", target=req.name)
        await session.commit()
        await session.refresh(key)
        return ApiKeyCreated(id=key.id, name=key.name, role=key.role, api_key=full)


@router.get("/audit")
async def audit_log(principal: Principal = Depends(require_role("admin")), limit: int = 100) -> list[dict]:
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(AuditLog).where(AuditLog.tenant_id == principal.tenant_id).order_by(AuditLog.at.desc()).limit(limit)
            )
        ).scalars().all()
        return [
            {"actor": a.actor, "action": a.action, "target": a.target, "result": a.result, "at": a.at}
            for a in rows
        ]
