"""Dashboard Generator Engine (Phase 3).

Consumes ``discovery`` inventory snapshots (debounced) to notice when the set
of distinct technologies present in the fleet changes, and (re)provisions a
Grafana dashboard per technology plus one fleet-overview dashboard.

Since ``dockiq_*`` metric series only carry ``tenant, host_id, container_id,
container`` labels (no role/tech labels), each tech's dashboard is scoped by
a ``container=~"name1|name2|..."`` regex built from the container names
currently classified under that tech (see ``app/store/models.Classification``).

Provisioning is exception-safe: if Grafana is unreachable the engine logs and
skips that cycle rather than dying, per docs/engines/09-dashboard-generator.md
("Grafana down -> queue provisioning; retry; native panels still work").
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus.subjects import DISCOVERY, wildcard
from app.core.config import settings
from app.engines.base import BaseEngine, EngineContext
from app.engines.dashboards.templates import PanelSpec, TemplateSpec, build_template
from app.store.db import SessionLocal
from app.store.models import Classification, Container, Dashboard

log = logging.getLogger("dockiq.engine.dashboards")

# Minimum time between regenerations triggered by discovery snapshots.
DEBOUNCE_SECONDS = 60.0

_DATASOURCE_NAME = "VictoriaMetrics"


def _regex_escape(name: str) -> str:
    return re.escape(name)


class DashboardEngine(BaseEngine):
    name = "dashboards"

    def __init__(self) -> None:
        super().__init__()
        self._lock = asyncio.Lock()
        self._last_run: float = 0.0
        self._last_techs: frozenset[str] = frozenset()
        self._datasource_uid: str | None = None

    def subjects(self) -> list[str]:
        return [wildcard(DISCOVERY)]

    async def start(self, ctx: EngineContext) -> None:
        await super().start(ctx)
        self.log.info("dashboard engine started")

    async def stop(self) -> None:
        self.log.info("dashboard engine stopped")

    async def handle(self, subject: str, data: dict) -> None:
        try:
            await self._maybe_regenerate()
        except Exception:  # noqa: BLE001 — never let a bad snapshot kill the consumer
            self.log.exception("dashboard regeneration failed for subject %s", subject)

    # -- debounce ------------------------------------------------------------

    async def _maybe_regenerate(self) -> None:
        loop = asyncio.get_event_loop()
        now = loop.time()

        async with SessionLocal() as session:
            techs = await self._distinct_techs(session)

        techs_changed = techs != self._last_techs
        due = (now - self._last_run) >= DEBOUNCE_SECONDS

        if not techs_changed and not due:
            return

        await self.regenerate()

    async def regenerate(self) -> int:
        """Regenerate all dashboards now. Returns the number provisioned."""
        async with self._lock:
            loop = asyncio.get_event_loop()
            self._last_run = loop.time()

            async with SessionLocal() as session:
                techs = await self._distinct_techs(session)
                self._last_techs = techs

                count = 0
                async with httpx.AsyncClient(
                    base_url=settings.grafana_url,
                    auth=(settings.grafana_user, settings.grafana_password),
                    timeout=10.0,
                ) as client:
                    await self._ensure_datasource_uid(client)

                    for tech in sorted(techs):
                        names = await self._container_names_for_tech(session, tech)
                        if not names:
                            continue
                        ok = await self._provision_tech_dashboard(client, session, tech, names)
                        if ok:
                            count += 1

                    if await self._provision_fleet_dashboard(client, session):
                        count += 1

                await session.commit()

            self.log.info("dashboard regeneration complete: %d dashboard(s) provisioned", count)
            return count

    # -- fleet queries ---------------------------------------------------------

    async def _distinct_techs(self, session: AsyncSession) -> frozenset[str]:
        rows = (
            await session.execute(
                select(Classification.tech).where(Classification.tech.isnot(None)).distinct()
            )
        ).scalars().all()
        return frozenset(t for t in rows if t)

    async def _container_names_for_tech(self, session: AsyncSession, tech: str) -> list[str]:
        rows = (
            await session.execute(
                select(Container.name)
                .join(Classification, Classification.container_id == Container.id)
                .where(Classification.tech == tech)
            )
        ).scalars().all()
        return sorted({n for n in rows if n})

    # -- Grafana provisioning ---------------------------------------------------

    async def _ensure_datasource_uid(self, client: httpx.AsyncClient) -> None:
        if self._datasource_uid is not None:
            return
        try:
            resp = await client.get(f"/api/datasources/name/{_DATASOURCE_NAME}")
            if resp.status_code == 200:
                self._datasource_uid = resp.json().get("uid")
        except Exception:  # noqa: BLE001
            self.log.warning("could not resolve %s datasource uid; falling back to name ref", _DATASOURCE_NAME)

    def _datasource_ref(self) -> dict | str:
        if self._datasource_uid:
            return {"type": "prometheus", "uid": self._datasource_uid}
        return _DATASOURCE_NAME

    def _panel_json(self, idx: int, panel: PanelSpec) -> dict:
        x = (idx % 2) * 12
        y = (idx // 2) * 8
        return {
            "id": idx + 1,
            "title": panel.title,
            "type": panel.panel_type,
            "gridPos": {"h": 8, "w": 12, "x": x, "y": y},
            "datasource": self._datasource_ref(),
            "fieldConfig": {"defaults": {"unit": panel.unit}, "overrides": []},
            "targets": [
                {
                    "expr": panel.promql,
                    "refId": "A",
                    "datasource": self._datasource_ref(),
                }
            ],
        }

    def _dashboard_json(self, title: str, panels: list[PanelSpec], tags: list[str]) -> dict:
        return {
            "title": title,
            "uid": None,
            "tags": ["dockiq", "generated", *tags],
            "timezone": "browser",
            "schemaVersion": 39,
            "version": 0,
            "refresh": "30s",
            "time": {"from": "now-6h", "to": "now"},
            "panels": [self._panel_json(i, p) for i, p in enumerate(panels)],
        }

    async def _provision(
        self, client: httpx.AsyncClient, dashboard_json: dict, existing_uid: str | None
    ) -> dict[str, Any] | None:
        if existing_uid:
            dashboard_json["uid"] = existing_uid
        body = {"dashboard": dashboard_json, "overwrite": True, "folderId": 0}
        try:
            resp = await client.post("/api/dashboards/db", json=body)
            resp.raise_for_status()
            return resp.json()
        except Exception:  # noqa: BLE001 — Grafana down/unreachable: skip, don't crash the engine
            self.log.warning("failed to provision dashboard %r to Grafana", dashboard_json.get("title"))
            return None

    async def _upsert_dashboard_row(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        title: str,
        tier: str,
        tech: str | None,
        target_selector: dict | None,
        grafana_result: dict[str, Any],
        spec: dict,
    ) -> None:
        uid = grafana_result.get("uid")
        row = (
            await session.execute(
                select(Dashboard).where(Dashboard.tenant_id == tenant_id, Dashboard.title == title)
            )
        ).scalar_one_or_none()

        grafana_url = f"{settings.grafana_url}/d/{uid}" if uid else None

        if row is None:
            session.add(
                Dashboard(
                    tenant_id=tenant_id,
                    title=title,
                    tier=tier,
                    tech=tech,
                    target_selector=target_selector,
                    grafana_uid=uid,
                    grafana_url=grafana_url,
                    generated=True,
                    spec=spec,
                )
            )
        else:
            row.tier = tier
            row.tech = tech
            row.target_selector = target_selector
            row.grafana_uid = uid or row.grafana_uid
            row.grafana_url = grafana_url or row.grafana_url
            row.generated = True
            row.spec = spec

    async def _provision_tech_dashboard(
        self,
        client: httpx.AsyncClient,
        session: AsyncSession,
        tech: str,
        container_names: list[str],
    ) -> bool:
        tenant_id = settings.default_tenant
        regex = "|".join(_regex_escape(n) for n in container_names)
        selector = f'container=~"{regex}"'
        template: TemplateSpec = build_template(tech, selector)
        title = f"DockIQ - {template.display_name}"

        existing = (
            await session.execute(
                select(Dashboard).where(Dashboard.tenant_id == tenant_id, Dashboard.title == title)
            )
        ).scalar_one_or_none()

        dash_json = self._dashboard_json(title, template.panels, tags=["technology", tech])
        result = await self._provision(client, dash_json, existing.grafana_uid if existing else None)
        if result is None:
            return False

        await self._upsert_dashboard_row(
            session,
            tenant_id=tenant_id,
            title=title,
            tier="technology",
            tech=tech,
            target_selector={"tech": tech, "containers": container_names},
            grafana_result=result,
            spec=dash_json,
        )
        return True

    async def _provision_fleet_dashboard(self, client: httpx.AsyncClient, session: AsyncSession) -> bool:
        tenant_id = settings.default_tenant
        title = "DockIQ Fleet Overview"

        panels = [
            PanelSpec("Top Containers by CPU", "topk(10, dockiq_cpu_usage_ratio)", unit="percentunit"),
            PanelSpec("Top Containers by Memory", "topk(10, dockiq_mem_usage_ratio)", unit="percentunit"),
            PanelSpec("Containers Up", "sum(dockiq_container_up)", unit="short"),
            PanelSpec("Total Restarts", "sum(dockiq_container_restarts_total)", unit="short"),
            PanelSpec("Fleet Network RX", "sum(rate(dockiq_net_rx_bytes_total[5m]))", unit="Bps"),
            PanelSpec("Fleet Network TX", "sum(rate(dockiq_net_tx_bytes_total[5m]))", unit="Bps"),
        ]

        existing = (
            await session.execute(
                select(Dashboard).where(Dashboard.tenant_id == tenant_id, Dashboard.title == title)
            )
        ).scalar_one_or_none()

        dash_json = self._dashboard_json(title, panels, tags=["fleet"])
        result = await self._provision(client, dash_json, existing.grafana_uid if existing else None)
        if result is None:
            return False

        await self._upsert_dashboard_row(
            session,
            tenant_id=tenant_id,
            title=title,
            tier="fleet",
            tech=None,
            target_selector=None,
            grafana_result=result,
            spec=dash_json,
        )
        return True
