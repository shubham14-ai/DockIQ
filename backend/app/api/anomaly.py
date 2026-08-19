"""Anomaly baselines API (Phase 2 AI Anomaly Engine, lite).

Router is included by ``main.py`` (wiring left to the caller per task
constraints — see report). Pydantic response models are defined locally
rather than in ``app/api/schemas.py`` since that file is outside this
engine's allowed write path.
"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.store.db import SessionLocal
from app.store.models import Baseline

router = APIRouter(prefix="/anomaly", tags=["anomaly"])


# ----------------------------------------------------------------------
# schemas
# ----------------------------------------------------------------------


class BaselineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: str
    metric: str
    container_id: str | None = None
    median: float | None = None
    mad: float | None = None
    mean: float | None = None
    std: float | None = None
    samples: int
    last_z: float | None = None
    updated_at: dt.datetime


class Band(BaseModel):
    lower: float
    upper: float


class SeriesOut(BaseModel):
    metric: str
    container_id: str | None = None
    baseline: BaselineOut | None = None
    band: Band | None = None


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _to_out(row: Baseline) -> BaselineOut:
    state = row.state or {}
    return BaselineOut(
        tenant_id=row.tenant_id,
        metric=row.metric,
        container_id=row.container_id,
        median=row.median,
        mad=row.mad,
        mean=row.mean,
        std=row.std,
        samples=row.samples,
        last_z=state.get("last_z"),
        updated_at=row.updated_at,
    )


def _band(row: Baseline) -> Band | None:
    if row.median is None or row.mad is None:
        return None
    # Inverse of the robust z-score transform: z = 0.6745*(x-median)/mad.
    spread = (3.5 * row.mad) / 0.6745 if row.mad else 0.0
    return Band(lower=row.median - spread, upper=row.median + spread)


# ----------------------------------------------------------------------
# routes
# ----------------------------------------------------------------------


@router.get("/baselines", response_model=list[BaselineOut])
async def list_baselines(
    metric: str | None = None, container_id: str | None = None
) -> list[BaselineOut]:
    async with SessionLocal() as session:
        stmt = select(Baseline).order_by(Baseline.updated_at.desc())
        if metric is not None:
            stmt = stmt.where(Baseline.metric == metric)
        if container_id is not None:
            stmt = stmt.where(Baseline.container_id == container_id)
        rows = (await session.execute(stmt)).scalars().all()
        return [_to_out(row) for row in rows]


@router.get("/series", response_model=SeriesOut)
async def get_series(metric: str, container_id: str) -> SeriesOut:
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(Baseline).where(
                    Baseline.metric == metric, Baseline.container_id == container_id
                )
            )
        ).scalars().first()

        if row is None:
            return SeriesOut(metric=metric, container_id=container_id, baseline=None, band=None)

        return SeriesOut(
            metric=metric,
            container_id=container_id,
            baseline=_to_out(row),
            band=_band(row),
        )
