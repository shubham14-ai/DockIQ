"""FastAPI auth dependencies: resolve the caller and enforce roles."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select

from app.auth import security
from app.auth.roles import has_at_least
from app.core.config import settings
from app.store.db import SessionLocal
from app.store.models import ApiKey


@dataclass
class Principal:
    kind: str  # "user" | "apikey"
    name: str
    tenant_id: str
    role: str


async def get_principal(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> Principal:
    """Resolve the caller from a Bearer JWT or an X-API-Key header.

    When ``auth_enabled`` is False, returns a synthetic admin principal so the
    platform runs open (dev only)."""
    if not settings.auth_enabled:
        return Principal(kind="user", name="anonymous", tenant_id=settings.default_tenant, role="owner")

    # API key path
    if x_api_key:
        key_hash = security.hash_api_key(x_api_key)
        async with SessionLocal() as session:
            row = (
                await session.execute(
                    select(ApiKey).where(
                        ApiKey.prefix == x_api_key[:12],
                        ApiKey.key_hash == key_hash,
                        ApiKey.enabled.is_(True),
                    )
                )
            ).scalars().first()
            if row is None:
                raise _unauth("invalid API key")
            row.last_used = datetime.now(timezone.utc)
            await session.commit()
            return Principal(kind="apikey", name=f"apikey:{row.name}", tenant_id=row.tenant_id, role=row.role)

    # JWT path
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
        try:
            payload = security.decode_access_token(token)
        except jwt.ExpiredSignatureError:
            raise _unauth("token expired")
        except jwt.InvalidTokenError:
            raise _unauth("invalid token")
        return Principal(
            kind="user",
            name=payload.get("sub", "?"),
            tenant_id=payload.get("tenant_id", settings.default_tenant),
            role=payload.get("role", "viewer"),
        )

    raise _unauth("authentication required")


def require_role(minimum: str):
    """Dependency factory: require the principal's role >= ``minimum``."""

    async def _checker(principal: Principal = Depends(get_principal)) -> Principal:
        if not has_at_least(principal.role, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires role '{minimum}' or higher (you are '{principal.role}')",
            )
        return principal

    return _checker


def _unauth(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
