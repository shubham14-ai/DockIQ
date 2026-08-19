# Layer: Frontend (Web UI)

The UI is where the intelligence becomes visible: live infrastructure, topology,
dashboards, logs, alerts, deployments, and LLM observability — all in one place.

> Framework is **proposed** (React + TypeScript), not locked. See
> [Tech Stack §10](../02-tech-stack.md) (`[DECISION PENDING D-2]`).

---

## 1. Goals

- **Zero-config value visible immediately** — connect a host and *see* classified
  containers, auto dashboards, and the topology graph without configuring
  anything.
- **Live** — WebSocket-driven updates (events, alerts, deploy progress); no manual
  refresh.
- **Correlated** — one click from a metric spike to the container's logs to its
  place in the topology.
- **Operable** — trigger and watch deployments, acknowledge alerts, inspect
  self-healing actions.

---

## 2. Primary views

| View | Purpose | Backed by |
|---|---|---|
| **Overview / Fleet** | All hosts + health at a glance | Postgres + heartbeat WS |
| **Hosts** | Per-host detail, container list, facts | Postgres, VM |
| **Containers** | Per-container: metrics, logs, health, classification, events | VM + Loki + Postgres |
| **Topology** | Live service dependency + communication graph | Topology engine (Postgres graph) |
| **Dashboards** | Auto-generated per-technology dashboards | Grafana (embedded) + native |
| **Logs** | Multi-container live log viewer (Dozzle-style) | Loki |
| **Alerts** | Active/history, ack, suppression, maintenance windows | Alert engine (Postgres) |
| **Deployments** | Release console: current/previous versions, rollback | Deployment layer |
| **LLM Observability** | Tokens, cost, prompt/RAG latency, vector DB perf | LLM engine (VM) |
| **Settings** | Users, roles, tenants, API keys, integrations | Auth/RBAC |

---

## 3. Topology view (a signature feature)

- Interactive graph (Cytoscape.js or react-flow, `[DECISION PENDING D-3]`).
- Nodes = containers/services, colored/iconed by **role** and **tech** (from
  Classification). Edges = dependencies / observed connections.
- Overlays: health (red/green), live traffic (edge thickness), alert state.
- Click a node → side panel with metrics, logs, classification, and actions.
- Time-scrub `[FUTURE]` — replay how topology/health changed around an incident.

Example the UI renders:
```
[Frontend] → [FastAPI] → [Redis]
                   │
                   └────→ [PostgreSQL]
```

---

## 4. Dashboards

- **Embedded Grafana** panels for the auto-generated per-technology dashboards
  (the [Dashboard Generator](../engines/09-dashboard-generator.md) provisions
  Grafana JSON).
- **Native panels** for DockIQ-specific views Grafana can't express (topology,
  classification breakdowns, deployment timelines, LLM cost).
- Hybrid keeps rich TSDB dashboards cheap while owning the unique UX.

---

## 5. Live updates (WebSocket)

- One authenticated WS connection per session.
- The backend [WS gateway](02-backend.md#9-websocket-gateway) subscribes the
  session to the NATS subjects allowed by tenant + RBAC and fans out:
  event timeline entries, alert state changes, deploy progress, health flips.
- The client updates views reactively (no polling).

---

## 6. API integration

- The frontend consumes the backend's OpenAPI via a **generated typed client**,
  keeping UI and API in lockstep. See [API Design](../api-design.md).
- All reads/writes go through `/api/v1`; live data via WS.

---

## 7. Access control in the UI

- The UI reflects RBAC: users only see tenants/hosts/actions they're permitted.
- Destructive controls (rollback, scale-down, restart, delete) are gated by
  permission and show confirmation with the action's blast radius.
- Multi-tenant users get a tenant switcher; single-tenant deployments hide it.

---

## 8. Design principles

- **Density with clarity** — SRE tools show a lot; group and progressively
  disclose.
- **Consistent labels** — the same `role`/`tech`/`service` vocabulary as metrics
  and logs, so the UI, charts, and queries all speak one language.
- **Dark/light aware**, responsive, keyboard-friendly for power users.
- **Fast first paint** — overview loads from Postgres immediately; heavy panels
  (VM/Loki queries) stream in.

---

## 9. Phase

- **`[MVP]`** Overview, Hosts, Containers (metrics + logs + classification +
  events), basic Alerts, auth/login. WebSocket live event timeline.
- **`[FUTURE]`** Topology graph, auto-dashboards (Grafana embed), Deployment
  console, LLM Observability, maintenance windows/suppression UI, time-scrub.
