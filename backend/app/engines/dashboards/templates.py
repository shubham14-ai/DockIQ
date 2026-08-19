"""Declarative dashboard templates (Dashboard Generator, Phase 3).

Each technology template describes the panels to render, scoped to a
``container=~"<regex>"`` selector built from the tech's matching container
names (metric series only carry ``tenant, host_id, container_id, container``
labels — no role/tech labels — so scoping happens by container-name regex,
resolved from the ``classifications`` table at generation time).

Panels degrade gracefully: every template only references metrics that the
Metrics Engine always emits (CPU/mem/net/restarts), so any detected tech gets
a useful dashboard immediately, per docs/engines/09-dashboard-generator.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Techs with a purpose-built (but still resource-metric-based) template. Any
# tech not listed here falls back to GENERIC_TEMPLATE.
KNOWN_TECHS: tuple[str, ...] = (
    "postgres",
    "mysql",
    "redis",
    "mongodb",
    "kafka",
    "rabbitmq",
    "nginx",
    "fastapi",
    "node",
    "qdrant",
    "elasticsearch",
)


@dataclass(frozen=True)
class PanelSpec:
    title: str
    promql: str
    unit: str = "short"
    panel_type: str = "timeseries"


@dataclass(frozen=True)
class TemplateSpec:
    tech: str
    display_name: str
    panels: list[PanelSpec] = field(default_factory=list)


def _resource_panels(selector: str) -> list[PanelSpec]:
    """Panels every technology gets: CPU, memory, net rx/tx, restarts/up."""
    return [
        PanelSpec("CPU Usage", f"dockiq_cpu_usage_ratio{{{selector}}}", unit="percentunit"),
        PanelSpec("Memory Usage", f"dockiq_mem_usage_ratio{{{selector}}}", unit="percentunit"),
        PanelSpec("Network RX", f"rate(dockiq_net_rx_bytes_total{{{selector}}}[5m])", unit="Bps"),
        PanelSpec("Network TX", f"rate(dockiq_net_tx_bytes_total{{{selector}}}[5m])", unit="Bps"),
        PanelSpec("Container Restarts", f"dockiq_container_restarts_total{{{selector}}}", unit="short"),
        PanelSpec("Container Up", f"dockiq_container_up{{{selector}}}", unit="short"),
    ]


def build_template(tech: str, selector: str) -> TemplateSpec:
    """Build the panel set for ``tech`` scoped to ``selector`` (a PromQL
    label-matcher body, e.g. ``container=~"orders-db|orders-db-2"``).

    All current templates are resource-metric based (the generic/degraded
    form from the design doc); technology-specific deep panels (e.g. pg
    connections) can be layered on per tech as those metrics land without
    changing this contract.
    """
    display = tech.replace("_", " ").title() if tech else "Unknown"
    return TemplateSpec(tech=tech, display_name=display, panels=_resource_panels(selector))
