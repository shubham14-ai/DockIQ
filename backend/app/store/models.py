from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.store.db import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Host(Base):
    """A Docker host running a DockIQ agent."""

    __tablename__ = "hosts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))

    agent_status: Mapped[str] = mapped_column(String(20), default="enrolling")
    last_heartbeat: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    agent_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    os: Mapped[str | None] = mapped_column(String(50), nullable=True)
    arch: Mapped[str | None] = mapped_column(String(50), nullable=True)
    docker_version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Container(Base):
    """A container discovered on a host (Discovery Engine)."""

    __tablename__ = "containers"

    # Docker container id.
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    host_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("hosts.id"), index=True
    )

    name: Mapped[str] = mapped_column(String(255))
    image_ref: Mapped[str | None] = mapped_column(String(400), nullable=True)
    image_digest: Mapped[str | None] = mapped_column(String(200), nullable=True)
    state: Mapped[str | None] = mapped_column(String(40), nullable=True)  # running…
    status: Mapped[str | None] = mapped_column(String(120), nullable=True)
    command: Mapped[str | None] = mapped_column(Text, nullable=True)

    compose_project: Mapped[str | None] = mapped_column(String(200), nullable=True)
    compose_service: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Flexible facts (labels, env-redacted, ports, mounts, networks).
    labels: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    env: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ports: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    mounts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    networks: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    native_health: Mapped[str | None] = mapped_column(String(40), nullable=True)

    first_seen: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Classification(Base):
    """Role + technology assigned to a container (Classification Engine)."""

    __tablename__ = "classifications"

    container_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("containers.id"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)

    role: Mapped[str] = mapped_column(String(30), default="unknown")
    tech: Mapped[str | None] = mapped_column(String(60), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="passive")  # passive|probe|override
    overridden: Mapped[bool] = mapped_column(default=False)

    classified_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Event(Base):
    """Container/host lifecycle timeline entry."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    host_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    container_id: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)

    type: Mapped[str] = mapped_column(String(40))  # create|start|stop|die|oom|health|image_update
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class TopologyEdge(Base):
    """A dependency/communication edge between two services (Topology Engine)."""

    __tablename__ = "topology_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    host_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    src_service: Mapped[str] = mapped_column(String(200), index=True)
    dst_service: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="declared")  # declared|observed|inferred
    proto: Mapped[str | None] = mapped_column(String(20), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    first_seen: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Baseline(Base):
    """Learned baseline for a metric series (AI Anomaly Engine, lite)."""

    __tablename__ = "baselines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    series_key: Mapped[str] = mapped_column(String(300), index=True)  # metric+labels hash
    metric: Mapped[str] = mapped_column(String(120))
    container_id: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)

    # Compact model state (median/MAD/EWMA etc.), not raw history.
    median: Mapped[float | None] = mapped_column(Float, nullable=True)
    mad: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    std: Mapped[float | None] = mapped_column(Float, nullable=True)
    samples: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AlertRule(Base):
    """An alerting rule (Alert Engine). Rules may be default or user-defined."""

    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200))

    # {"role": "...", "tech": "...", "service": "...", "host": "..."}
    target_selector: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # {"type": "threshold|health|event", "metric": "...", "op": ">", "value": 0.9}
    condition: Mapped[dict] = mapped_column(JSONB)
    for_seconds: Mapped[int] = mapped_column(Integer, default=0)
    severity: Mapped[str] = mapped_column(String(20), default="warning")
    actions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    source: Mapped[str] = mapped_column(String(20), default="default")  # default|user

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class User(Base):
    """A platform user (Phase 7 auth)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # viewer|operator|deployer|admin|owner
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_login: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ApiKey(Base):
    """A hashed API key for automation / programmatic access (Phase 7)."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(12), index=True)  # first chars, for lookup
    key_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    enabled: Mapped[bool] = mapped_column(default=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuditLog(Base):
    """Append-only record of mutating actions (Phase 7)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(120))  # username|apikey:name|system
    action: Mapped[str] = mapped_column(String(80))
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Dashboard(Base):
    """A generated (or custom) dashboard record (Dashboard Generator, Phase 3)."""

    __tablename__ = "dashboards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    tier: Mapped[str] = mapped_column(String(20), default="technology")  # technology|service|fleet
    tech: Mapped[str | None] = mapped_column(String(60), nullable=True)
    role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    target_selector: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    grafana_uid: Mapped[str | None] = mapped_column(String(80), nullable=True)
    grafana_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    generated: Mapped[bool] = mapped_column(default=True)
    spec: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class HealingPolicy(Base):
    """Per-target self-healing policy (Self-Healing Engine, Phase 5)."""

    __tablename__ = "healing_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200))
    target_selector: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    allowed_actions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # ["restart",...]
    mode: Mapped[str] = mapped_column(String(20), default="off")  # off|auto|semi
    max_per_hour: Mapped[int] = mapped_column(Integer, default=3)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class HealingAction(Base):
    """A self-healing action instance (audit trail)."""

    __tablename__ = "healing_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    policy_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trigger: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    host_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    container_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    action: Mapped[str] = mapped_column(String(30))
    outcome: Mapped[str] = mapped_column(String(20), default="attempted")  # attempted|fixed|escalated|failed
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    verified_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Deployment(Base):
    """A deployment attempt (Deployment & Release layer, Phase 6)."""

    __tablename__ = "deployments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    service: Mapped[str] = mapped_column(String(200), index=True)
    host_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    container_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    from_version: Mapped[str | None] = mapped_column(String(200), nullable=True)
    to_version: Mapped[str | None] = mapped_column(String(200), nullable=True)
    image_ref: Mapped[str | None] = mapped_column(String(400), nullable=True)
    strategy: Mapped[str] = mapped_column(String(20), default="rolling")  # rolling|bluegreen|canary
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # manual|webhook|registry
    status: Mapped[str] = mapped_column(String(20), default="pending")
    risk_score: Mapped[str | None] = mapped_column(String(10), nullable=True)  # low|med|high
    risk_reasons: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    initiated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Release(Base):
    """Per-service version history + known-good marker for rollback."""

    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    service: Mapped[str] = mapped_column(String(200), index=True)
    version: Mapped[str | None] = mapped_column(String(200), nullable=True)
    image_ref: Mapped[str | None] = mapped_column(String(400), nullable=True)
    deployment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    known_good: Mapped[bool] = mapped_column(default=False)
    deployed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Alert(Base):
    """A fired alert instance."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    rule_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("alert_rules.id"), nullable=True
    )

    target: Mapped[str | None] = mapped_column(String(255), nullable=True)  # container/service
    state: Mapped[str] = mapped_column(String(20), default="firing")  # pending|firing|acked|resolved
    severity: Mapped[str] = mapped_column(String(20), default="warning")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    labels: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    count: Mapped[int] = mapped_column(Integer, default=1)

    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    acked_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
