"""Alert Engine (Phase 1).

Consumes ``health`` and ``events`` telemetry to fire/resolve alerts inline, and
runs a periodic evaluator that queries VictoriaMetrics for threshold-rule
breaches. All alert lifecycle transitions are persisted to Postgres
(``AlertRule`` / ``Alert``) and published as JSON to ``dockiq.<tenant>.alerts``.

Kept intentionally defensive: any handler exception is caught so the shared
NATS consumer loop (see ``app.engines.registry``) stays alive, and a missing/
broken ``app.store.vm`` module only degrades metric-threshold rules for that
tick rather than crashing the engine.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
from collections import defaultdict, deque
from typing import Any

from sqlalchemy import select

from app.bus.subjects import EVENTS, HEALTH, wildcard
from app.core.config import settings
from app.engines.alert.defaults import DEFAULT_RULES
from app.engines.base import BaseEngine, EngineContext
from app.store.db import SessionLocal
from app.store.models import Alert, AlertRule, Tenant

log = logging.getLogger("dockiq.engine.alert")

EVALUATOR_INTERVAL_SECONDS = 30
CRASH_LOOP_MIN_STARTS = 3
CRASH_LOOP_WINDOW_SECONDS = 300
OPEN_STATES = ("pending", "firing", "acked")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_time(value: Any) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, str):
        try:
            v = value.replace("Z", "+00:00")
            return dt.datetime.fromisoformat(v)
        except ValueError:
            pass
    return _now()


class AlertEngine(BaseEngine):
    name = "alert"

    def __init__(self) -> None:
        super().__init__()
        # In-memory dedup: (tenant, rule_key, target) -> open Alert.id
        self._open_alerts: dict[tuple[str, str, str], int] = {}
        # crash-loop heuristic: (tenant, container_id) -> deque[datetime] of `start` events
        self._start_events: dict[tuple[str, str], deque[dt.datetime]] = defaultdict(
            lambda: deque(maxlen=20)
        )
        # threshold breach tracking: (rule_id, target) -> first-breach timestamp
        self._first_breach: dict[tuple[int, str], dt.datetime] = {}
        self._evaluator_task: asyncio.Task | None = None

    def subjects(self) -> list[str]:
        return [wildcard(HEALTH), wildcard(EVENTS)]

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def start(self, ctx: EngineContext) -> None:
        await super().start(ctx)
        try:
            await self._seed_default_rules()
        except Exception:  # noqa: BLE001
            self.log.exception("failed to seed default alert rules")
        self._evaluator_task = asyncio.create_task(self._evaluator_loop())

    async def stop(self) -> None:
        if self._evaluator_task is not None:
            self._evaluator_task.cancel()
            try:
                await self._evaluator_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._evaluator_task = None

    async def _seed_default_rules(self) -> None:
        async with SessionLocal() as session:
            tenant_ids = (await session.execute(select(Tenant.id))).scalars().all()
            if not tenant_ids:
                tenant_ids = [settings.default_tenant]
            for tenant_id in tenant_ids:
                existing = (
                    await session.execute(
                        select(AlertRule.id).where(AlertRule.tenant_id == tenant_id)
                    )
                ).scalars().first()
                if existing is not None:
                    continue
                for rule_def in DEFAULT_RULES:
                    session.add(AlertRule(tenant_id=tenant_id, **rule_def))
                self.log.info("seeded %d default alert rules for tenant %s", len(DEFAULT_RULES), tenant_id)
            await session.commit()

    # ------------------------------------------------------------------
    # inline handlers: health + events
    # ------------------------------------------------------------------

    async def handle(self, subject: str, data: dict) -> None:
        parts = subject.split(".")
        kind = parts[3] if len(parts) >= 4 else None
        try:
            if kind == HEALTH:
                await self._handle_health(data)
            elif kind == EVENTS:
                await self._handle_event(data)
        except Exception:  # noqa: BLE001 — keep consumer alive
            self.log.exception("error handling %s message", kind)

    async def _handle_health(self, data: dict) -> None:
        tenant = data.get("tenant_id", settings.default_tenant)
        container_id = data.get("container_id") or data.get("name") or "unknown"
        name = data.get("name") or container_id
        status = data.get("status")

        if status == "unhealthy":
            await self._fire(
                tenant=tenant,
                rule_key="container-unhealthy",
                target=container_id,
                severity="warning",
                summary=f"Container {name} is unhealthy",
                labels={"container": name, "container_id": container_id, "host_id": data.get("host_id")},
            )
        elif status == "healthy":
            await self._resolve(tenant=tenant, rule_key="container-unhealthy", target=container_id)

    async def _handle_event(self, data: dict) -> None:
        tenant = data.get("tenant_id", settings.default_tenant)
        container_id = data.get("container_id") or data.get("name") or "unknown"
        name = data.get("name") or container_id
        etype = data.get("type")
        labels = {"container": name, "container_id": container_id, "host_id": data.get("host_id")}

        if etype == "oom":
            await self._fire(
                tenant=tenant,
                rule_key="oom-kill",
                target=container_id,
                severity="critical",
                summary=f"Container {name} was OOM-killed",
                labels=labels,
            )
        elif etype == "die":
            exit_code = data.get("exit_code")
            if exit_code not in (None, 0):
                await self._fire(
                    tenant=tenant,
                    rule_key="oom-kill" if data.get("attributes", {}).get("oom") else "container-crash",
                    target=container_id,
                    severity="warning",
                    summary=f"Container {name} exited with code {exit_code}",
                    labels=labels,
                    value=float(exit_code) if isinstance(exit_code, (int, float)) else None,
                )
        elif etype == "start":
            key = (tenant, container_id)
            when = _parse_time(data.get("time"))
            dq = self._start_events[key]
            dq.append(when)
            cutoff = _now() - dt.timedelta(seconds=CRASH_LOOP_WINDOW_SECONDS)
            recent = [t for t in dq if t >= cutoff]
            if len(recent) >= CRASH_LOOP_MIN_STARTS:
                await self._fire(
                    tenant=tenant,
                    rule_key="container-crash-loop",
                    target=container_id,
                    severity="warning",
                    summary=f"Container {name} is crash-looping ({len(recent)} restarts in {CRASH_LOOP_WINDOW_SECONDS}s)",
                    labels=labels,
                    value=float(len(recent)),
                )

    # ------------------------------------------------------------------
    # periodic threshold evaluator
    # ------------------------------------------------------------------

    async def _evaluator_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(EVALUATOR_INTERVAL_SECONDS)
                await self._evaluate_threshold_rules()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                self.log.exception("threshold evaluator tick failed")

    async def _evaluate_threshold_rules(self) -> None:
        try:
            from app.store.vm import vm
        except Exception:  # noqa: BLE001
            self.log.debug("app.store.vm not available yet; skipping metric rules this tick")
            return

        async with SessionLocal() as session:
            rules = (
                await session.execute(
                    select(AlertRule).where(AlertRule.enabled.is_(True))
                )
            ).scalars().all()

        for rule in rules:
            condition = rule.condition or {}
            if condition.get("type") != "threshold":
                continue
            metric = condition.get("metric")
            op = condition.get("op", ">")
            value = condition.get("value")
            if not metric or value is None:
                continue
            promql = f"{metric} {op} {value}"
            try:
                result = await vm.query(promql)
            except Exception:  # noqa: BLE001
                self.log.warning("vm.query failed for rule %s (%s)", rule.name, promql, exc_info=True)
                continue

            breaching_targets = self._extract_targets(result)
            now = _now()

            for target, sample_value in breaching_targets:
                breach_key = (rule.id, target)
                first_seen = self._first_breach.setdefault(breach_key, now)
                if (now - first_seen).total_seconds() < (rule.for_seconds or 0):
                    continue  # not breaching long enough yet
                await self._fire(
                    tenant=rule.tenant_id,
                    rule_key=rule.name,
                    target=target,
                    severity=rule.severity,
                    summary=f"{rule.name}: {metric} {op} {value} (target={target})",
                    labels={"rule": rule.name, **({"container_id": target})},
                    value=sample_value,
                    rule_id=rule.id,
                )

            # clear breach-tracking + auto-resolve targets no longer breaching
            still_breaching = {t for t, _ in breaching_targets}
            stale_keys = [k for k in self._first_breach if k[0] == rule.id and k[1] not in still_breaching]
            for k in stale_keys:
                del self._first_breach[k]
                await self._resolve(tenant=rule.tenant_id, rule_key=rule.name, target=k[1])

    @staticmethod
    def _extract_targets(result: Any) -> list[tuple[str, float | None]]:
        """Normalize a VictoriaMetrics/Prometheus query response into
        (target, value) pairs. Tolerates a few plausible shapes from the
        ``vm.query`` helper (raw HTTP JSON, or an already-unwrapped list)."""
        items: list[dict] = []
        if isinstance(result, dict):
            items = result.get("data", {}).get("result", []) or []
        elif isinstance(result, list):
            items = result

        out: list[tuple[str, float | None]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            metric_labels = item.get("metric", {})
            target = (
                metric_labels.get("container_id")
                or metric_labels.get("container")
                or metric_labels.get("instance")
                or "unknown"
            )
            raw_value = item.get("value")
            val: float | None = None
            if isinstance(raw_value, (list, tuple)) and len(raw_value) == 2:
                try:
                    val = float(raw_value[1])
                except (TypeError, ValueError):
                    val = None
            out.append((target, val))
        return out

    # ------------------------------------------------------------------
    # fire / resolve + publish
    # ------------------------------------------------------------------

    async def _fire(
        self,
        *,
        tenant: str,
        rule_key: str,
        target: str,
        severity: str,
        summary: str,
        labels: dict | None = None,
        value: float | None = None,
        rule_id: int | None = None,
    ) -> None:
        dedup_key = (tenant, rule_key, target)
        async with SessionLocal() as session:
            resolved_rule_id = rule_id
            if resolved_rule_id is None:
                resolved_rule_id = (
                    await session.execute(
                        select(AlertRule.id).where(
                            AlertRule.tenant_id == tenant, AlertRule.name == rule_key
                        )
                    )
                ).scalars().first()

            alert_id = self._open_alerts.get(dedup_key)
            alert: Alert | None = None
            if alert_id is not None:
                alert = await session.get(Alert, alert_id)
                if alert is not None and alert.state not in OPEN_STATES:
                    alert = None  # was resolved/acked-closed elsewhere; treat as new

            if alert is None:
                # Fall back to DB lookup (covers process restarts / multi-worker
                # deployments where the in-memory dedup cache is cold). We filter
                # on rule_key in Python since it lives inside the JSONB labels blob.
                existing = (
                    await session.execute(
                        select(Alert).where(
                            Alert.tenant_id == tenant,
                            Alert.target == target,
                            Alert.state.in_(OPEN_STATES),
                        )
                    )
                ).scalars().all()
                alert = next(
                    (a for a in existing if (a.labels or {}).get("rule_key") == rule_key), None
                )

            event_labels = dict(labels or {})
            event_labels["rule_key"] = rule_key

            if alert is not None:
                alert.count += 1
                alert.value = value
                alert.summary = summary
                lifecycle = "updated"
            else:
                alert = Alert(
                    tenant_id=tenant,
                    rule_id=resolved_rule_id,
                    target=target,
                    state="firing",
                    severity=severity,
                    summary=summary,
                    labels=event_labels,
                    value=value,
                    count=1,
                )
                session.add(alert)
                lifecycle = "fired"

            await session.commit()
            await session.refresh(alert)
            self._open_alerts[dedup_key] = alert.id

            await self._publish(tenant, lifecycle, alert)

    async def _resolve(self, *, tenant: str, rule_key: str, target: str) -> None:
        dedup_key = (tenant, rule_key, target)
        async with SessionLocal() as session:
            alert: Alert | None = None
            alert_id = self._open_alerts.get(dedup_key)
            if alert_id is not None:
                alert = await session.get(Alert, alert_id)

            if alert is None:
                existing = (
                    await session.execute(
                        select(Alert).where(
                            Alert.tenant_id == tenant,
                            Alert.target == target,
                            Alert.state.in_(OPEN_STATES),
                        )
                    )
                ).scalars().all()
                alert = next(
                    (a for a in existing if (a.labels or {}).get("rule_key") == rule_key), None
                )

            if alert is None or alert.state == "resolved":
                self._open_alerts.pop(dedup_key, None)
                return

            alert.state = "resolved"
            alert.resolved_at = _now()
            await session.commit()
            await session.refresh(alert)
            self._open_alerts.pop(dedup_key, None)

            await self._publish(tenant, "resolved", alert)

    async def _publish(self, tenant: str, lifecycle: str, alert: Alert) -> None:
        if self.ctx is None:
            return
        payload = {
            "lifecycle": lifecycle,
            "id": alert.id,
            "tenant_id": alert.tenant_id,
            "rule_id": alert.rule_id,
            "target": alert.target,
            "state": alert.state,
            "severity": alert.severity,
            "summary": alert.summary,
            "labels": alert.labels,
            "value": alert.value,
            "count": alert.count,
            "started_at": alert.started_at.isoformat() if alert.started_at else None,
            "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
        }
        try:
            await self.ctx.bus.publish(f"dockiq.{tenant}.alerts", payload)
        except Exception:  # noqa: BLE001
            self.log.warning("failed to publish alert lifecycle event", exc_info=True)
