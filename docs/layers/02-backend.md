# Layer: Backend (FastAPI Control Plane)

The backend is the brain of DockIQ. It exposes the API, hosts all engines,
orchestrates agents, enforces security, and serves the data the UI needs.

---

## 1. Responsibilities

- **API surface** — REST + WebSocket, auto-documented via OpenAPI (see [API Design](../api-design.md)).
- **Agent orchestration** — enrollment, heartbeat tracking, command dispatch.
- **Engine host** — runs the 10 engines as internal modules (v1) behind a common interface.
- **Event consumption** — subscribes to NATS subjects; routes to engines.
- **Persistence** — owns PostgreSQL (metadata) and mediates VictoriaMetrics/Loki queries.
- **AuthN/Z** — OIDC/SSO, local users, API keys, RBAC, tenant scoping.
- **Deployment orchestration** — the Deployment/Release layer logic.
- **WebSocket fan-out** — bridge relevant NATS events to UI sessions.

---

## 2. Why FastAPI (recap)

Async I/O, automatic OpenAPI/validation via Pydantic, plugin-friendly DI, and —
critically — it lives in the **Python ML ecosystem** the Anomaly and LLM
engines need. See [Tech Stack §3](../02-tech-stack.md).

---

## 3. Module structure

```
backend/
├── app/
│   ├── main.py                 # FastAPI app, lifespan, router mount
│   ├── api/                    # REST + WS routers (versioned: /api/v1)
│   │   ├── hosts.py
│   │   ├── containers.py
│   │   ├── topology.py
│   │   ├── metrics.py
│   │   ├── logs.py
│   │   ├── alerts.py
│   │   ├── deployments.py
│   │   ├── llm.py
│   │   ├── auth.py
│   │   └── ws.py               # WebSocket gateway
│   ├── engines/                # the 10 engines (see engines/ docs)
│   │   ├── base.py             # Engine interface / lifecycle
│   │   ├── discovery/
│   │   ├── classification/
│   │   ├── topology/
│   │   ├── metrics/
│   │   ├── logging/
│   │   ├── alert/
│   │   ├── anomaly/
│   │   ├── healing/
│   │   ├── dashboards/
│   │   └── llm/
│   ├── deployment/             # release management layer
│   ├── agents/                 # agent registry, command bus, control channel
│   ├── bus/                    # NATS client, subjects, consumers
│   ├── store/                  # PostgreSQL (models, repos), VM client, Loki client
│   ├── auth/                   # OIDC, RBAC, api keys, tenancy
│   ├── core/                   # config, logging, errors, DI
│   └── models/                 # Pydantic schemas + SQLAlchemy models
└── tests/
```

---

## 4. Engine model

All engines implement a common interface so they can be started, stopped, and
(later) extracted into separate services:

```python
class Engine(Protocol):
    name: str
    def subjects(self) -> list[str]: ...      # NATS subjects it consumes
    async def start(self, ctx: EngineContext) -> None: ...
    async def on_event(self, subject: str, msg: Event) -> None: ...
    async def stop(self) -> None: ...
```

`EngineContext` provides scoped access to stores, the command bus, the event
publisher, and config — no engine reaches for globals. This is what lets v1 run
all engines in-process while keeping a clean seam to split them out later.

**In-process now, services later:** v1 co-locates engines for velocity and simple
ops. Because they only communicate via the event bus + stores (never direct
calls), any engine can be lifted into its own deployment when a scaling need
appears (likely candidates first: Metrics ingest, Anomaly, LLM).

---

## 5. Agent orchestration

- **Registry** — tracks each agent: host facts, last heartbeat, health,
  capabilities, cert identity. Backed by PostgreSQL + in-memory cache.
- **Enrollment** — validates join tokens, issues client certs, records the host.
- **Command bus** — request/reply to agents (NATS req/rep or gRPC). Handles
  timeouts, retries, idempotency keys, and result capture.
- **Liveness** — missed heartbeats → mark host degraded/down → Alert Engine.

---

## 6. Event consumption

The backend runs durable **JetStream consumers** per engine group. Key
properties:
- **Durable + replayable** — an engine restart resumes from its last ack.
- **Tenant-scoped subscriptions** — subjects include `<tenant>`.
- **At-least-once** — engines are idempotent (dedupe by event ID).
- **Dead-letter** — poison messages routed to a DLQ subject + logged.

---

## 7. Persistence access

- **PostgreSQL** — via async SQLAlchemy 2.0 / asyncpg; repository pattern per
  aggregate (hosts, containers, alerts, deployments…). See [Data Model](../data-model.md).
- **VictoriaMetrics** — HTTP client speaking PromQL for queries and remote-write
  for any backend-side metric emission.
- **Loki** — HTTP client speaking LogQL for queries; agents push logs directly.

The API never exposes raw store access — all reads go through typed repository/
service methods that enforce tenant + RBAC scope.

---

## 8. AuthN / AuthZ

- **AuthN:** OIDC/SSO (primary) + local users (fallback) + API keys (agents,
  automation). Sessions via JWT.
- **AuthZ:** RBAC — roles map to permissions; every endpoint declares required
  permission(s); tenant scoping applied in the data layer.
- Details in [Security](../security.md).

---

## 9. WebSocket gateway

The UI opens one authenticated WS connection. The backend:
1. Authenticates the session (JWT) and resolves tenant + RBAC.
2. Subscribes the session to the NATS subjects it's allowed to see, filtered by
   what the current view needs (host, container, topology, alerts, deploy).
3. Fans out messages, applying RBAC/tenant filtering on the way out.

This gives the UI live event timelines, alert state changes, and deploy progress
without polling.

---

## 10. API design (pointer)

Full surface in [API Design](../api-design.md). Highlights:
- Versioned under `/api/v1`.
- OpenAPI auto-generated; typed client generated for the frontend.
- Consistent envelope, pagination, and error format.
- WebSocket namespace for live updates.

---

## 11. Configuration

```yaml
server:
  host: 0.0.0.0
  port: 8080
database:
  url: postgresql+asyncpg://...
metrics:
  victoriametrics_url: http://victoriametrics:8428
logs:
  loki_url: http://loki:3100
bus:
  nats_url: nats://nats:4222
  jetstream: true
auth:
  oidc_issuer: https://...
  jwt_secret: <from secret>
tenancy:
  default_tenant: default
```

---

## 12. Scaling & HA

- **Stateless** — the backend keeps no session state that can't be reconstructed;
  scale horizontally behind a load balancer. `[FUTURE]`
- **Sticky WS** — WebSocket connections pin to an instance; NATS delivers to
  whichever instance holds the session.
- **Engine sharding** — heavy engines (Metrics, Anomaly, LLM) can be split into
  dedicated deployments consuming their own subjects.
- v1 ships single-instance for simplicity. `[MVP]`

---

## 13. Failure modes

| Failure | Handling |
|---|---|
| PostgreSQL down | API returns 503 for writes; degraded read cache where safe |
| VictoriaMetrics/Loki down | Metric/log panels degrade; alerting on those pauses with a surfaced warning |
| NATS down | Command dispatch + live updates pause; agents buffer; auto-resume on reconnect |
| Engine crash | Supervised restart; JetStream replays missed events |
| Agent flood | Consumer rate limits + backpressure; DLQ for poison messages |

---

## 14. Phase

- **`[MVP]`** API (hosts/containers/metrics/logs/alerts), agent orchestration,
  Discovery/Classification/Metrics/Logging/Alert engines in-process, WS gateway,
  OIDC + RBAC basics, single instance.
- **`[FUTURE]`** Deployment orchestration, Anomaly/Healing/Dashboard/LLM engines,
  engine extraction to services, HA/scale-out.
