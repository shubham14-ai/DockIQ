"""Read-only tools the Diagnostic Agent can call.

Every tool is strictly read-only (metric/log queries + DB reads). Claude decides
which to call to gather evidence; the backend executes them and returns bounded
JSON. Nothing here mutates state or touches the Docker socket.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select

from app.store.db import SessionLocal
from app.store.models import Alert, Baseline, Classification, Container, Event, TopologyEdge

# Tool schemas advertised to Claude (Anthropic tool-use format).
TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "query_metrics",
        "description": (
            "Run an instant PromQL query against VictoriaMetrics and return the "
            "current value(s). Available series (labels: tenant, host_id, "
            "container_id, container): dockiq_cpu_usage_ratio, dockiq_mem_usage_ratio, "
            "dockiq_mem_usage_bytes, dockiq_mem_limit_bytes, dockiq_net_rx_bytes, "
            "dockiq_net_tx_bytes, dockiq_blk_read_bytes, dockiq_blk_write_bytes, "
            "dockiq_container_up. Example: 'dockiq_mem_usage_ratio{container=\"carevora-api-1\"}' "
            "or 'topk(5, dockiq_cpu_usage_ratio)'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"promql": {"type": "string", "description": "PromQL expression"}},
            "required": ["promql"],
        },
    },
    {
        "name": "query_metrics_range",
        "description": (
            "Run a PromQL range query over the last N minutes to see a trend "
            "(e.g. to check if memory is climbing). Returns downsampled points."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "promql": {"type": "string"},
                "minutes": {"type": "integer", "description": "Look-back window, default 30"},
            },
            "required": ["promql"],
        },
    },
    {
        "name": "query_logs",
        "description": (
            "Query container logs from Loki via LogQL over the last N minutes. "
            "Labels: container, container_id, host_id, stream. Example: "
            "'{container=\"carevora-api-1\"} |= \"error\"'. Returns recent matching lines."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "logql": {"type": "string"},
                "minutes": {"type": "integer", "description": "Look-back window, default 30"},
                "limit": {"type": "integer", "description": "Max lines, default 50"},
            },
            "required": ["logql"],
        },
    },
    {
        "name": "list_containers",
        "description": (
            "List discovered containers with their classification (role, tech). "
            "Optionally filter by role, tech, or state."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "role": {"type": "string"},
                "tech": {"type": "string"},
                "state": {"type": "string"},
            },
        },
    },
    {
        "name": "get_topology",
        "description": (
            "Get the service dependency graph edges (src_service -> dst_service). "
            "Use this to reason about blast radius and which service a problem "
            "propagates from. Optionally filter to edges touching a given service."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"service": {"type": "string", "description": "Namespaced service id, e.g. 'carevora/api'"}},
        },
    },
    {
        "name": "list_alerts",
        "description": "List alerts, optionally filtered by state (firing|acked|resolved).",
        "input_schema": {
            "type": "object",
            "properties": {"state": {"type": "string"}},
        },
    },
    {
        "name": "get_anomaly_baselines",
        "description": (
            "Get learned metric baselines (median/MAD) and whether current values "
            "deviate. Optionally filter by container_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"container_id": {"type": "string"}},
        },
    },
    {
        "name": "list_events",
        "description": (
            "List recent container lifecycle events (start/stop/die/oom/health) — "
            "useful to correlate a problem with a restart or crash. Optionally "
            "filter by container_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "container_id": {"type": "string"},
                "minutes": {"type": "integer", "description": "Look-back window, default 60"},
            },
        },
    },
]

_MAX_RESULT_CHARS = 6000


def _clip(obj: Any) -> str:
    text = json.dumps(obj, default=str)
    if len(text) > _MAX_RESULT_CHARS:
        return text[:_MAX_RESULT_CHARS] + f"... [truncated, {len(text)} chars]"
    return text


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def execute_tool(name: str, args: dict, tenant_id: str) -> str:
    """Dispatch a tool call and return a JSON string result (bounded)."""
    try:
        if name == "query_metrics":
            from app.store.vm import vm

            data = await vm.query(args["promql"])
            return _clip(data.get("data", data))

        if name == "query_metrics_range":
            from app.store.vm import vm

            minutes = int(args.get("minutes", 30))
            end = _now()
            start = end - timedelta(minutes=minutes)
            step = max(15, (minutes * 60) // 60)  # ~60 points
            data = await vm.query_range(
                args["promql"],
                str(int(start.timestamp())),
                str(int(end.timestamp())),
                f"{step}s",
            )
            return _clip(data.get("data", data))

        if name == "query_logs":
            from app.store.loki import loki

            minutes = int(args.get("minutes", 30))
            limit = int(args.get("limit", 50))
            end = _now()
            start = end - timedelta(minutes=minutes)
            data = await loki.query_range(
                args["logql"],
                str(int(start.timestamp() * 1_000_000_000)),
                str(int(end.timestamp() * 1_000_000_000)),
                limit,
            )
            # Flatten Loki streams to simple lines to save tokens.
            lines: list[str] = []
            for stream in data.get("data", {}).get("result", []):
                for _ts, line in stream.get("values", []):
                    lines.append(line)
            return _clip({"lines": lines[-limit:], "count": len(lines)})

        async with SessionLocal() as session:
            if name == "list_containers":
                stmt = (
                    select(Container, Classification)
                    .outerjoin(Classification, Classification.container_id == Container.id)
                    .where(Container.tenant_id == tenant_id)
                )
                rows = (await session.execute(stmt)).all()
                out = []
                for c, cl in rows:
                    if args.get("state") and c.state != args["state"]:
                        continue
                    if args.get("role") and (not cl or cl.role != args["role"]):
                        continue
                    if args.get("tech") and (not cl or cl.tech != args["tech"]):
                        continue
                    out.append(
                        {
                            "id": c.id[:12],
                            "name": c.name,
                            "state": c.state,
                            "image": c.image_ref,
                            "role": cl.role if cl else None,
                            "tech": cl.tech if cl else None,
                            "compose_project": c.compose_project,
                        }
                    )
                return _clip({"containers": out, "count": len(out)})

            if name == "get_topology":
                stmt = select(TopologyEdge).where(TopologyEdge.tenant_id == tenant_id)
                svc = args.get("service")
                if svc:
                    stmt = stmt.where(
                        (TopologyEdge.src_service == svc) | (TopologyEdge.dst_service == svc)
                    )
                rows = (await session.execute(stmt)).scalars().all()
                edges = [
                    {"source": e.src_service, "target": e.dst_service, "kind": e.kind, "confidence": e.confidence, "port": e.port}
                    for e in rows
                ]
                return _clip({"edges": edges, "count": len(edges)})

            if name == "list_alerts":
                stmt = select(Alert).where(Alert.tenant_id == tenant_id).order_by(desc(Alert.started_at))
                if args.get("state"):
                    stmt = stmt.where(Alert.state == args["state"])
                rows = (await session.execute(stmt.limit(50))).scalars().all()
                out = [
                    {"id": a.id, "severity": a.severity, "state": a.state, "summary": a.summary, "target": a.target, "started_at": a.started_at}
                    for a in rows
                ]
                return _clip({"alerts": out, "count": len(out)})

            if name == "get_anomaly_baselines":
                stmt = select(Baseline).where(Baseline.tenant_id == tenant_id)
                if args.get("container_id"):
                    stmt = stmt.where(Baseline.container_id.like(f"{args['container_id']}%"))
                rows = (await session.execute(stmt.limit(60))).scalars().all()
                out = [
                    {
                        "metric": b.metric,
                        "container_id": (b.container_id or "")[:12],
                        "median": b.median,
                        "mad": b.mad,
                        "samples": b.samples,
                        "last_z": (b.state or {}).get("last_z") if b.state else None,
                    }
                    for b in rows
                ]
                return _clip({"baselines": out, "count": len(out)})

            if name == "list_events":
                minutes = int(args.get("minutes", 60))
                cutoff = _now() - timedelta(minutes=minutes)
                stmt = (
                    select(Event)
                    .where(Event.tenant_id == tenant_id, Event.at >= cutoff)
                    .order_by(desc(Event.at))
                )
                if args.get("container_id"):
                    stmt = stmt.where(Event.container_id.like(f"{args['container_id']}%"))
                rows = (await session.execute(stmt.limit(60))).scalars().all()
                out = [
                    {"type": e.type, "container_id": (e.container_id or "")[:12], "at": e.at, "detail": e.detail}
                    for e in rows
                ]
                return _clip({"events": out, "count": len(out)})

        return _clip({"error": f"unknown tool {name}"})
    except Exception as exc:  # noqa: BLE001 — report tool errors back to Claude
        return _clip({"error": f"{type(exc).__name__}: {exc}"})
