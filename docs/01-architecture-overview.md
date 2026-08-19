# Architecture Overview

This document describes the physical and logical shape of DockIQ: the major
components, how they are separated, and how they are deployed. Deep dives live in
the [`layers/`](layers/) and [`engines/`](engines/) docs.

---

## 1. Two planes

DockIQ separates concerns into a **control plane** and a set of **data-plane
agents**.

- **Control Plane** — the central brain. Runs the backend, all engines, the
  event bus, the databases, and the web UI. Usually one deployment (HA later).
- **Data Plane (Agents)** — one lightweight Python agent per Docker host. Agents
  never make decisions; they *observe and act on command*.

```
                          ┌──────────────────────────────────────────────┐
                          │                CONTROL PLANE                  │
                          │                                               │
   ┌──────────┐  HTTPS/WS │   ┌───────────┐      ┌────────────────────┐   │
   │  Web UI   │◀────────▶│   │  FastAPI   │◀────▶│   Engines (10)      │   │
   └──────────┘           │   │  Backend   │      │  Discovery, Class., │   │
                          │   │  (API+WS)  │      │  Topology, Metrics, │   │
                          │   └─────┬──────┘      │  Logging, Alert,    │   │
                          │         │             │  Anomaly, Healing,  │   │
                          │         │             │  Dashboards, LLM    │   │
                          │   ┌─────▼──────┐      └─────────┬──────────┘   │
                          │   │   NATS      │◀──────────────┘              │
                          │   │ (JetStream) │                             │
                          │   └─────┬──────┘                             │
                          │         │                                     │
                          │   ┌─────▼───────────────────────────────┐    │
                          │   │  Storage: VictoriaMetrics │ Loki │   │    │
                          │   │           PostgreSQL                │    │
                          │   └─────────────────────────────────────┘    │
                          └───────────────┬──────────────────────────────┘
                                          │ gRPC/WSS + NATS (mTLS)
              ┌───────────────────────────┼───────────────────────────┐
              │                           │                           │
      ┌───────▼────────┐         ┌────────▼───────┐          ┌────────▼───────┐
      │  Docker Host A │         │  Docker Host B │          │  Docker Host C │
      │  ┌───────────┐ │         │  ┌───────────┐ │          │  ┌───────────┐ │
      │  │  Agent    │ │         │  │  Agent    │ │          │  │  Agent    │ │
      │  └─────┬─────┘ │         │  └─────┬─────┘ │          │  └─────┬─────┘ │
      │  Docker Engine │         │  Docker Engine │          │  Docker Engine │
      └────────────────┘         └────────────────┘          └────────────────┘
```

---

## 2. Components

### 2.1 Agent (Python) — [details](layers/01-agent.md)
Runs on every Docker host. Responsibilities:
- Subscribe to **Docker events** (create/start/stop/die/OOM/health)
- Sample **Docker stats** (CPU, memory, net, disk I/O)
- **Discover** containers, images, networks, volumes
- **Health monitoring** (Docker healthchecks + probes)
- **Log collection** (stream container logs)
- **Topology discovery** (network membership, observed connections)
- **Heartbeat** (liveness + host facts)
- **Execute actions** on command (restart, stop, recreate, scale, run script)

The agent is a single static binary. It is **stateless** beyond a small local
buffer for reliability.

### 2.2 Backend (FastAPI / Python) — [details](layers/02-backend.md)
The control-plane brain:
- REST + WebSocket API (auto-generated OpenAPI)
- Hosts all 10 engines as internal modules/plugins
- Orchestrates agents (issues commands, receives streams)
- AuthN/Z, RBAC, multi-tenancy
- Business logic for deployment/rollback

### 2.3 Storage — [details](layers/03-storage.md)
| Store | Holds | Why |
|---|---|---|
| **VictoriaMetrics** | Time-series metrics | Compression, retention, scale; Prometheus-compatible |
| **Loki** | Logs (indexed by label) | Cheap storage, Grafana-native, label model |
| **PostgreSQL** | Hosts, containers, classifications, topology, rules, alerts, deployments, tenants, audit | Relational source of truth |

### 2.4 Event Bus — NATS/JetStream — [details](layers/04-event-streaming.md)
The nervous system connecting agents, engines, and processors:
```
Agent → Event Bus → Processors → Alert Engine
```
JetStream gives durable, replayable streams so no event is lost if a consumer is
briefly down.

### 2.5 Frontend (Web UI) — [details](layers/05-frontend.md)
Single-page app: hosts/containers views, live topology graph, metrics dashboards,
log viewer, alerts, deployment console, LLM observability.

---

## 3. Logical layering

```
┌─────────────────────────────────────────────────────────────┐
│  Presentation      Web UI · REST/WS API · Grafana (embedded) │
├─────────────────────────────────────────────────────────────┤
│  Intelligence      10 Engines (Discovery … LLM Observability)│
│                    + Deployment/Release Management Layer      │
├─────────────────────────────────────────────────────────────┤
│  Platform          FastAPI Backend · NATS Event Bus          │
│                    AuthN/Z · RBAC · Multi-tenancy · Audit    │
├─────────────────────────────────────────────────────────────┤
│  Storage           VictoriaMetrics · Loki · PostgreSQL       │
├─────────────────────────────────────────────────────────────┤
│  Collection    Python Agents (per host) · Docker Engine SDK  │
└─────────────────────────────────────────────────────────────┘
```

Data flows **up** (agents → storage → engines → UI) and commands flow **down**
(UI/engines → backend → agents).

---

## 4. Communication & protocols

| Path | Protocol | Notes |
|---|---|---|
| Agent → Backend (register, heartbeat, commands) | gRPC or WSS `[DECISION PENDING]` | mTLS; long-lived |
| Agent → Event Bus (events, metrics samples, health) | NATS over TLS | durable subjects per host/tenant |
| Backend ↔ Engines | in-process + NATS | engines subscribe to subjects |
| Backend → VictoriaMetrics | HTTP (Prometheus remote-write / query) | |
| Backend → Loki | HTTP (push/query) | |
| Backend ↔ PostgreSQL | SQL (async driver) | |
| UI ↔ Backend | HTTPS REST + WSS | JWT/OIDC session |

> **`[DECISION PENDING]`** Agent↔Backend control channel: gRPC (typed, efficient,
> bidi streaming) vs WSS (simpler through proxies/firewalls). Leaning gRPC for
> control + NATS for data. Resolve in [Agent layer](layers/01-agent.md).

---

## 5. Multi-tenancy model

Every persisted entity carries a `tenant_id`. `[FUTURE]` for full SaaS, but the
column and scoping exist from day one so single-tenant deployments upgrade
cleanly.

- **Isolation:** row-level scoping in PostgreSQL; per-tenant NATS subject
  prefixes; per-tenant label sets in VictoriaMetrics/Loki.
- **v1 default:** a single implicit tenant (`default`).

See [Security](security.md#multi-tenancy) for details.

---

## 6. Deployment topology (how DockIQ itself is deployed)

DockIQ ships as a Docker Compose stack (dogfooding — DockIQ monitors itself):

```
docker compose up:
  dockiq-backend      (FastAPI)
  dockiq-ui           (static web)
  nats                (JetStream)
  victoriametrics
  loki
  postgres
  grafana             (optional, for embedded dashboards)   [optional]
```

Agents are distributed separately (one per host to monitor), typically as a
single container or binary with the control-plane URL + a join token.

- **v1:** single-node control plane. `[MVP]`
- **Later:** HA backend (stateless, scale horizontally), clustered NATS,
  VictoriaMetrics cluster mode, Postgres replication. `[FUTURE]`

---

## 7. Trust & security boundaries

```
[ Operator ] --OIDC/JWT--> [ Backend ] --mTLS--> [ Agent ] --socket--> [ Docker ]
```

- The **agent holds the keys to the host** (Docker socket access). It is the most
  sensitive component. It only executes commands that are signed/authorized by
  the control plane and permitted by policy.
- The **backend** enforces RBAC on every action.
- **Docker socket** is never exposed to the network — only the local agent
  touches it.

Full model in [Security](security.md).

---

## 8. Why this architecture

| Choice | Reason |
|---|---|
| Separate control plane vs agents | Central intelligence, thin trusted collectors, clean multi-host scaling |
| Python agent | Single-language stack with the backend, mature Docker SDK, simple I/O-bound concurrency |
| Python backend | Async API + rich ML ecosystem for anomaly/LLM engines |
| NATS event bus | Decouples producers/consumers, durable replay, simple ops |
| Purpose-built stores | Right tool per data shape (TS vs logs vs relational) |
| Engines as modules on one backend (v1) | Ship fast; extract to services later if needed |

See [Tech Stack](02-tech-stack.md) for the full rationale and alternatives
considered.
