# DockIQ

**Docker Infrastructure Intelligence Platform**

DockIQ is not "another Docker monitoring dashboard." It is a platform that
**discovers, understands, monitors, and operates** containerized infrastructure
autonomously. It knows *what* is running (technology detection), *how it is
connected* (topology), *whether it is healthy* (metrics + anomaly detection),
and it can *act* on that knowledge (alerting, self-healing, deployment, and
rollback).

> Docker + Intelligence → **DockIQ**

---

## The one-line pitch

Most tools stop at **Monitoring**. DockIQ covers the full operational loop:

```
Discover → Classify → Monitor → Analyze → Alert → Deploy → Validate → Rollback → Self-Heal
```

This turns it from a *monitoring platform* into a **Docker Operations /
Infrastructure Intelligence Platform**.

---

## What makes it different

| Capability | Existing tools | DockIQ |
|---|---|---|
| Resource metrics (CPU/mem/net/disk) | ✅ cAdvisor, Netdata | ✅ (reused, not reinvented) |
| Live logs | ✅ Dozzle | ✅ |
| Multi-host agents, RBAC, alerts | ✅ DockMon | ✅ |
| **Technology detection** (FastAPI, Redis, Kafka, Qdrant…) | ❌ | ✅ **Unique** |
| **Automatic dashboard generation** | ❌ | ✅ **Unique** |
| **Service relationship discovery** | ❌ (partial) | ✅ **Unique** |
| **AI/LLM observability** (tokens, cost, RAG latency) | ❌ | ✅ **Unique** |
| **Intelligent (baseline) alerting** | ⚠️ threshold-only | ✅ |
| **Self-healing** beyond restart | ⚠️ restart-only | ✅ |
| **Deployment + smart rollback** | ❌ | ✅ |

---

## The 10 core engines

1. **Discovery Engine** — find every host, container, network, volume
2. **Classification Engine** — auto-label containers (API, DB, cache, queue, worker, vector DB, AI service…)
3. **Topology Engine** — build the service dependency & communication graph
4. **Metrics Engine** — collect and store time-series resource metrics
5. **Logging Engine** — stream, index, and search container logs
6. **Alert Engine** — threshold + baseline + anomaly-driven alerting
7. **AI Anomaly Engine** — baseline learning & forecasting
8. **Self-Healing Engine** — restart → rollback → scale → recover → incident
9. **Dashboard Generator** — auto-build dashboards from detected technologies
10. **LLM Observability Engine** — token usage, prompt latency, cost, vector DB perf

Plus a **Deployment & Release Management Layer** (rolling / blue-green / canary,
health validation, smart rollback, drift detection, dependency validation).

---

## Architecture at a glance

```
        ┌──────────────────────────────────────────────────────┐
        │                     Control Plane                     │
        │  FastAPI Backend · Engines · NATS Event Bus · Web UI  │
        └───────────────┬───────────────┬──────────────────────┘
                        │               │
        ┌───────────────┴───┐   ┌───────┴───────────┐
        │  Storage Layer    │   │  Docker Host A     │
        │  VictoriaMetrics  │   │  ┌──────────────┐  │
        │  Loki             │   │  │ DockIQ Agent │  │  (Python)
        │  PostgreSQL       │   │  └──────┬───────┘  │
        └───────────────────┘   │   Docker Engine    │
                                └────────────────────┘
                                (repeat per host: B, C, …)
```

- **Agent** (Python): runs on every Docker host — events, stats, discovery, health, logs, topology, heartbeat.
- **Backend** (FastAPI/Python): the brain — hosts all engines, exposes the API, serves the UI.
- **Storage**: VictoriaMetrics (metrics), Loki (logs), PostgreSQL (hosts/containers/rules/alerts/tenants).
- **Event bus**: NATS (JetStream) — `Agent → Event Bus → Processors → Alert Engine`.

---

## Agent design (Python)

The agent is the only component that touches the Docker socket. It is
**I/O-bound** — most of its work is *waiting* on long-lived Docker streams
(events, per-container stats, per-container logs) — so the design is built around
that shape rather than raw CPU throughput.

**Concurrency model — a thread per stream, plus one asyncio loop for NATS:**

```
main thread ── enroll (REST) ─▶ heartbeat loop (every 5s)
    │
    ├─ collectors thread
    │     ├─ discovery      full inventory reconcile every 30s
    │     ├─ events         one Docker event subscription; on start/stop it
    │     │                 spins up/tears down the per-container threads below
    │     ├─ StatsManager   1 sampling thread per running container (5s)
    │     └─ LogsManager    2 threads per container (reader → queue → batcher)
    │
    └─ NatsPublisher ── a dedicated asyncio event loop on its own thread
```

- **Why threads, not async, for collection:** the `docker` SDK (docker-py) is
  blocking. A thread that sits in `for event in client.events()` is the simplest
  correct way to consume a blocking generator, and the GIL is irrelevant because
  every collector is parked in a socket read, not holding the interpreter.
- **Lifecycle by `threading.Event`:** each container's stats/logs threads are
  tracked in a manager dict and stopped via a per-container `Event` — the direct
  analogue of a cancellable context. The event stream drives start/stop as
  containers churn; `discovery` reconciles anything missed.
- **NATS on its own loop:** `nats-py` is async-only, so `NatsPublisher` runs one
  event loop on a background thread and exposes a thread-safe, fire-and-forget
  `publish()` (via `run_coroutine_threadsafe`). The same loop also serves
  request/reply **commands** (restart/stop/recreate), running the blocking Docker
  handler in an executor so it never stalls the loop.
- **Resilient by design:** any single collector failing (socket hiccup, a
  container vanishing mid-stream) is logged and isolated — it never takes down
  the others, the heartbeat, or the process.
- **Contract-stable:** every payload is JSON on `dockiq.<tenant>.<host>.<kind>`
  subjects, identical to the protocol in
  [`docs/phase1-agent-protocol.md`](docs/phase1-agent-protocol.md), so the agent
  is a drop-in for the control plane.

Entry point: [`agent/main.py`](agent/main.py) · collectors:
[`agent/collectors/`](agent/collectors/) · transport:
[`agent/nats_publisher.py`](agent/nats_publisher.py).

---

## Documentation

The full design lives in [`/docs`](docs/README.md). Start there.

| Doc | Purpose |
|---|---|
| [Vision & Goals](docs/00-vision-and-goals.md) | Why DockIQ exists, non-goals, success criteria |
| [Architecture Overview](docs/01-architecture-overview.md) | System shape, components, boundaries |
| [Tech Stack](docs/02-tech-stack.md) | Every technology choice, with rationale |
| [Data Flow](docs/03-data-flow.md) | How data moves end-to-end |
| [Layers](docs/layers/) | Agent, Backend, Storage, Event Bus, Frontend — in depth |
| [Engines](docs/engines/) | Each of the 10 engines — in depth |
| [Deployment Layer](docs/deployment/) | Release strategies, rollback, healing |
| [Data Model](docs/data-model.md) | Entities & schemas |
| [API Design](docs/api-design.md) | REST + WebSocket surface |
| [Security](docs/security.md) | AuthN/Z, RBAC, secrets, threat model |
| [Roadmap](docs/roadmap.md) | Phased build order (MVP → full platform) |
| [Glossary](docs/glossary.md) | Terminology |

---

## Status

🏗️ **Phase 1 (MVP) — code-complete, pending live verification.** The full
Discover → Classify → Monitor → Alert loop is implemented:

- **Python agent** collectors: Docker discovery, events, stats, logs, health → NATS.
- **Backend engines:** Discovery, Classification (24-tech catalog), Metrics
  (→ VictoriaMetrics), Logging (→ Loki), Alert (default rules + evaluator).
- **Web UI** (React): Overview, Hosts, Containers (classification + live metric
  charts + log tail), Alerts (with ack).

Verified without a running daemon: backend imports cleanly (21 routes, all 5
engines load), UI production build succeeds, `docker compose config` valid. The
**Python agent build and the live end-to-end run still need Docker Desktop running.**

### Run it
```bash
cp .env.example .env
docker compose up -d --build            # control plane + UI
docker compose --profile agent up -d    # local test agent (discovers this host's containers)
```
- Web UI: <http://localhost:5173>  ·  API docs: <http://localhost:8080/docs>
- Grafana: <http://localhost:3000>

Full walkthrough: [docs/quickstart.md](docs/quickstart.md).

## Source material

The original vision brief is preserved at [`raw_info/info.txt`](raw_info/info.txt).
This documentation set formalizes and extends it.
