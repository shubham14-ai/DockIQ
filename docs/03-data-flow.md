# Data Flow

How data moves through DockIQ end-to-end. Two directions matter:

- **Observation flow (up):** host → agent → event bus → engines/storage → UI.
- **Command flow (down):** UI/engine → backend → agent → Docker Engine.

---

## 1. Planes recap

- **Data plane:** high-volume telemetry (stats, logs, events) from agents.
- **Control plane:** decisions, commands, config, and API traffic.

Keeping these separate means a burst of logs never blocks a control command, and
vice versa.

---

## 2. Observation flow (the main loop)

```
┌─────────────┐   Docker Engine API   ┌──────────────┐
│Docker Engine│──────────────────────▶│  DockIQ Agent │
└─────────────┘  events/stats/logs    └──────┬───────┘
                                             │ publish (NATS, per subject)
              dockiq.<tenant>.<host>.events  │
              dockiq.<tenant>.<host>.metrics │
              dockiq.<tenant>.<host>.logs    │
              dockiq.<tenant>.<host>.health  ▼
                                       ┌──────────────┐
                                       │  NATS/JetStream│
                                       └──────┬───────┘
                          ┌──────────────────┼───────────────────┐
                          ▼                  ▼                   ▼
                  ┌──────────────┐   ┌──────────────┐    ┌──────────────┐
                  │ Metrics      │   │ Logging      │    │ Discovery /  │
                  │ Ingest       │   │ Ingest       │    │ Classify /   │
                  │              │   │              │    │ Topology     │
                  └──────┬───────┘   └──────┬───────┘    └──────┬───────┘
                         ▼                  ▼                   ▼
                 VictoriaMetrics          Loki            PostgreSQL
                         │                  │                   │
                         └──────────────────┴─────────┬─────────┘
                                                       ▼
                                              ┌─────────────────┐
                                              │ Alert / Anomaly  │
                                              │ engines (consume │
                                              │ streams + query) │
                                              └────────┬────────┘
                                                       ▼
                                               Alerts, incidents,
                                               dashboards → UI (WS)
```

### Subjects (NATS)
Telemetry is published on structured subjects so consumers subscribe to exactly
what they need:

```
dockiq.<tenant>.<host_id>.events     # container lifecycle, OOM, health transitions
dockiq.<tenant>.<host_id>.metrics    # sampled stats (CPU/mem/net/disk)
dockiq.<tenant>.<host_id>.logs       # log lines (or a pointer if pushed direct to Loki)
dockiq.<tenant>.<host_id>.health     # healthcheck/probe results
dockiq.<tenant>.<host_id>.topology   # observed connections / network membership
dockiq.<tenant>.<host_id>.heartbeat  # liveness + host facts
```

### Where each stream lands
| Stream | Primary store | Consumed by |
|---|---|---|
| metrics | VictoriaMetrics | Metrics, Alert, Anomaly, Dashboard, Deployment |
| logs | Loki | Logging, Alert (log-based), LLM Observability |
| events | PostgreSQL (event timeline) + engines | Discovery, Classification, Self-Healing, Alert |
| health | PostgreSQL + engines | Alert, Self-Healing, Deployment validation |
| topology | PostgreSQL (graph edges) | Topology, Dashboard, Deployment dependency checks |
| heartbeat | PostgreSQL (host state) | Discovery, UI, Alert (host down) |

> **Metrics/logs high-volume note:** to avoid double-hops, the agent may push
> logs directly to Loki and metrics via remote-write to VictoriaMetrics, while
> publishing *lightweight event notifications* to NATS for the engines. NATS
> carries control-relevant signals; bulk telemetry can bypass it. Final split
> decided in [Metrics](engines/04-metrics-engine.md) / [Logging](engines/05-logging-engine.md).

---

## 3. The intelligence chain (per container lifecycle)

When a container starts, a cascade runs:

```
container start event
        │
        ▼
[Discovery]  register container, image, ports, labels, networks, env (redacted)
        │
        ▼
[Classification]  detect technology + role (API / DB / cache / queue / worker / vectorDB / AI)
        │
        ▼
[Topology]  place node in graph; infer/observe edges to other services
        │
        ├──▶ [Dashboard Generator]  create the right dashboard for the detected tech
        │
        ├──▶ [Metrics]  begin sampling; [Anomaly] begin baseline learning
        │
        └──▶ [Alert]  attach default + baseline rules for this class of service
```

This cascade is why **classification is the foundation** — every downstream
engine keys off the container's detected role and technology.

---

## 4. Command flow (control plane)

```
┌─────────┐   REST/WS   ┌──────────┐  RBAC check  ┌──────────┐
│  Web UI  │────────────▶│ FastAPI   │─────────────▶│  Engine   │
└─────────┘             │ Backend   │              │ (e.g.     │
                        └────┬──────┘              │ Self-Heal)│
                             │ issue command       └────┬─────┘
                             ▼                          │
                      ┌──────────────┐                  │
                      │  Command bus  │◀─────────────────┘
                      │ (NATS req/rep │
                      │  or gRPC)     │
                      └──────┬───────┘
                             ▼
                      ┌──────────────┐   Docker Engine API
                      │  DockIQ Agent │──────────────────────▶ restart / stop /
                      └──────────────┘                        recreate / scale /
                                                              run recovery script
```

**Every command is:**
1. **Authorized** — RBAC + tenant scope checked at the backend.
2. **Policy-gated** — destructive actions checked against self-healing/deploy policy.
3. **Audited** — written to the audit log with actor, target, before/after.
4. **Acknowledged** — the agent reports success/failure back up the observation
   flow, closing the loop (did the restart actually fix it?).

---

## 5. Deployment data flow

```
CI system / registry
   │  webhook: "new image pushed  app:2.4.1"
   ▼
[Backend webhook receiver] ──▶ [Deployment Engine]
   │
   ├─ analyze: resource impact, drift, dependency health, risk score
   ├─ choose strategy: rolling / blue-green / canary
   ▼
issue deploy commands ──▶ Agent(s) ──▶ Docker Engine (pull, recreate, route)
   │
   ▼
[Validation] health checks + smoke tests + metric watch (error rate, latency)
   │
   ├─ pass ──▶ promote release, record in PostgreSQL, notify UI
   └─ fail ──▶ [Smart Rollback] restore previous version, open incident
```

See [Deployment Layer](deployment/01-deployment-layer.md).

---

## 6. Query flow (UI reads)

```
Web UI
  ├─ GET /hosts, /containers, /topology, /alerts     → Backend → PostgreSQL
  ├─ metrics panels                                  → Backend → VictoriaMetrics (PromQL)
  ├─ log viewer                                      → Backend → Loki (LogQL)
  └─ live updates                                    → WebSocket ← Backend (fanned from NATS)
```

Live updates (new events, alert state changes, deploy progress) are pushed over
a WebSocket; the backend bridges relevant NATS subjects to per-session WS
channels, scoped by tenant + RBAC.

---

## 7. Reliability & backpressure

- **JetStream durability:** if an engine is down, events persist and are replayed
  on reconnect — no data loss for control-relevant streams.
- **Agent local buffer:** if the control plane is unreachable, the agent buffers
  a bounded window of events/metrics on disk and replays on reconnect.
- **Backpressure:** bulk telemetry (metrics/logs) uses direct remote-write/push
  with the store's own backpressure; NATS carries the lower-volume control
  signals, keeping the bus responsive.
- **Idempotency:** commands carry a command ID; agents dedupe so a replayed
  command isn't executed twice.

---

## 8. Data retention (defaults, tunable)

| Data | Store | Default retention |
|---|---|---|
| High-res metrics | VictoriaMetrics | 15 days, then downsampled `[FUTURE]` |
| Downsampled metrics | VictoriaMetrics | 13 months |
| Logs | Loki | 7–30 days (tenant-configurable) |
| Events timeline | PostgreSQL | 90 days (then archived) |
| Alerts / incidents | PostgreSQL | indefinite (audit) |
| Deployments / audit | PostgreSQL | indefinite |

Retention is per-tenant configurable; defaults chosen to balance value vs cost.
