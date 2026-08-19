from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

log = logging.getLogger("dockiq.store")


class Base(AsyncAttrs, DeclarativeBase):
    pass


engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Create tables (Phase 0: create_all; migrations arrive with Alembic later)
    and ensure the default tenant exists."""
    # Import models so they register on Base.metadata before create_all.
    from app.store import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        tenant = await session.get(models.Tenant, settings.default_tenant)
        if tenant is None:
            session.add(models.Tenant(id=settings.default_tenant, name="Default"))
            await session.commit()
            log.info("created default tenant %r", settings.default_tenant)

    # Bootstrap admin user (Phase 7) — created once if no users exist.
    from sqlalchemy import select

    from app.auth import security

    async with SessionLocal() as session:
        any_user = (await session.execute(select(models.User).limit(1))).scalars().first()
        if any_user is None:
            session.add(
                models.User(
                    tenant_id=settings.default_tenant,
                    username=settings.admin_username,
                    password_hash=security.hash_password(settings.admin_password),
                    role="owner",
                )
            )
            await session.commit()
            log.warning(
                "created bootstrap admin user %r — CHANGE THE PASSWORD (set ADMIN_PASSWORD)",
                settings.admin_username,
            )
