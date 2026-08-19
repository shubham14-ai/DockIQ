"""AI Anomaly Engine (Phase 2, MVP-lite).

Periodic poller (no NATS subscriptions) that queries VictoriaMetrics for the
current value of a handful of key metrics per container, maintains a rolling
robust baseline (median/MAD, windowed, plus an EWMA mean/std) per
(metric, container_id) series, and publishes an anomaly signal to
``dockiq.<tenant>.anomaly`` when the robust z-score crosses the sensitivity
threshold after warmup.

See docs/engines/07-ai-anomaly-engine.md (Phase MVP-lite: rolling robust
z-score). Kept dependency-free (pure ``statistics`` module, no numpy/pandas)
and defensive: a VM outage or a bad sample degrades that tick only, it never
kills the poll loop.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import statistics
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.engines.base import BaseEngine, EngineContext
from app.store.db import SessionLocal
from app.store.models import Baseline

log = logging.getLogger("dockiq.engine.anomaly")

POLL_INTERVAL_SECONDS = 30
WATCHED_METRICS = ("dockiq_cpu_usage_ratio", "dockiq_mem_usage_ratio")

# Rolling window size (number of recent samples kept in ``Baseline.state``).
WINDOW_SIZE = 120
# Robust z-score threshold (MAD-scaled) that triggers an anomaly signal.
Z_THRESHOLD = 3.5
# Minimum number of updates before we trust the baseline enough to score.
WARMUP_SAMPLES = 20
# 0.6745 = Phi^-1(0.75); converts MAD to a normal-consistent scale estimate.
MAD_SCALE = 0.6745
# EWMA smoothing factor for the (secondary) mean/std trend estimate.
EWMA_ALPHA = 0.2


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _series_key(metric: str, container_id: str) -> str:
    return f"{metric}|{container_id}"


class AnomalyEngine(BaseEngine):
    name = "anomaly"

    def __init__(self) -> None:
        super().__init__()
        self._poll_task: asyncio.Task | None = None

    def subjects(self) -> list[str]:
        # Periodic poller only — no NATS subscriptions.
        return []

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def start(self, ctx: EngineContext) -> None:
        await super().start(ctx)
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._poll_task = None

    async def _poll_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — keep the poll loop alive
                self.log.exception("anomaly poll tick failed")

    # ------------------------------------------------------------------
    # per-tick work
    # ------------------------------------------------------------------

    async def _tick(self) -> None:
        try:
            from app.store.vm import vm
        except Exception:  # noqa: BLE001
            self.log.debug("app.store.vm not available yet; skipping this tick")
            return

        for metric in WATCHED_METRICS:
            try:
                result = await vm.query(metric)
            except Exception:  # noqa: BLE001
                self.log.warning("vm.query failed for %s", metric, exc_info=True)
                continue

            samples = self._extract_samples(result)
            if not samples:
                continue

            for tenant, container_id, value in samples:
                try:
                    await self._update_and_score(tenant, metric, container_id, value)
                except Exception:  # noqa: BLE001 — one bad series shouldn't stop the tick
                    self.log.exception(
                        "failed to update baseline for %s/%s", metric, container_id
                    )

    @staticmethod
    def _extract_samples(result: Any) -> list[tuple[str, str, float]]:
        """Normalize a VM instant-query response into (tenant, container_id, value)."""
        items: list[dict] = []
        if isinstance(result, dict):
            items = result.get("data", {}).get("result", []) or []
        elif isinstance(result, list):
            items = result

        out: list[tuple[str, str, float]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            labels = item.get("metric", {}) or {}
            container_id = labels.get("container_id")
            if not container_id:
                continue  # need a stable series identity
            tenant = labels.get("tenant") or settings.default_tenant

            raw_value = item.get("value")
            if not (isinstance(raw_value, (list, tuple)) and len(raw_value) == 2):
                continue
            try:
                value = float(raw_value[1])
            except (TypeError, ValueError):
                continue
            out.append((tenant, container_id, value))
        return out

    # ------------------------------------------------------------------
    # baseline update + robust z-score
    # ------------------------------------------------------------------

    async def _update_and_score(
        self, tenant: str, metric: str, container_id: str, value: float
    ) -> None:
        series_key = _series_key(metric, container_id)

        async with SessionLocal() as session:
            row = (
                await session.execute(
                    select(Baseline).where(
                        Baseline.tenant_id == tenant,
                        Baseline.series_key == series_key,
                    )
                )
            ).scalars().first()

            if row is None:
                row = Baseline(
                    tenant_id=tenant,
                    series_key=series_key,
                    metric=metric,
                    container_id=container_id,
                    samples=0,
                    state={"values": []},
                )
                session.add(row)

            state = dict(row.state or {})
            values: list[float] = list(state.get("values") or [])
            values.append(value)
            if len(values) > WINDOW_SIZE:
                values = values[-WINDOW_SIZE:]
            state["values"] = values

            median = statistics.median(values)
            mad = statistics.median([abs(v - median) for v in values]) if values else 0.0

            prev_mean = row.mean if row.mean is not None else value
            prev_std = row.std if row.std is not None else 0.0
            ewma_mean = prev_mean + EWMA_ALPHA * (value - prev_mean)
            deviation = abs(value - ewma_mean)
            ewma_std = prev_std + EWMA_ALPHA * (deviation - prev_std)

            total_samples = (row.samples or 0) + 1

            z: float
            if mad and mad > 0:
                z = (MAD_SCALE * (value - median)) / mad
            else:
                z = 0.0

            row.median = median
            row.mad = mad
            row.mean = ewma_mean
            row.std = ewma_std
            row.samples = total_samples
            state["last_z"] = z
            state["last_value"] = value
            state["last_at"] = _now().isoformat()
            row.state = state

            await session.commit()

            is_anomaly = abs(z) >= Z_THRESHOLD and total_samples >= WARMUP_SAMPLES

        if is_anomaly:
            await self._publish_anomaly(
                tenant=tenant,
                metric=metric,
                container_id=container_id,
                value=value,
                median=median,
                mad=mad,
                z=z,
            )

    async def _publish_anomaly(
        self,
        *,
        tenant: str,
        metric: str,
        container_id: str,
        value: float,
        median: float,
        mad: float,
        z: float,
    ) -> None:
        if self.ctx is None:
            return
        payload = {
            "tenant_id": tenant,
            "metric": metric,
            "container_id": container_id,
            "value": value,
            "median": median,
            "mad": mad,
            "z": z,
            "at": _now().isoformat(),
        }
        try:
            await self.ctx.bus.publish(f"dockiq.{tenant}.anomaly", payload)
        except Exception:  # noqa: BLE001
            self.log.warning("failed to publish anomaly signal", exc_info=True)
