# DockIQ Documentation

This is the authoritative design documentation for **DockIQ — a Docker
Infrastructure Intelligence Platform**. It is written to be *finalized before
building*: every layer and engine is documented in depth so implementation can
proceed against a stable spec.

> **How to read this:** Start with Vision → Architecture → Tech Stack → Data
> Flow. Then read the Layers (how the system is physically built), then the
> Engines (the intelligence that runs on top). Deployment, Data Model, API,
> Security, and Roadmap are cross-cutting references.

---

## Reading order

### 1. Foundations
- [`00-vision-and-goals.md`](00-vision-and-goals.md) — the "why", non-goals, success criteria, personas
- [`01-architecture-overview.md`](01-architecture-overview.md) — components, boundaries, deployment topology
- [`02-tech-stack.md`](02-tech-stack.md) — every technology choice + rationale + alternatives
- [`03-data-flow.md`](03-data-flow.md) — end-to-end data movement, control vs data plane

### 2. Layers (the physical system)
- [`layers/01-agent.md`](layers/01-agent.md) — the Python agent on each Docker host
- [`layers/02-backend.md`](layers/02-backend.md) — the FastAPI control plane
- [`layers/03-storage.md`](layers/03-storage.md) — VictoriaMetrics, Loki, PostgreSQL
- [`layers/04-event-streaming.md`](layers/04-event-streaming.md) — NATS/JetStream event bus
- [`layers/05-frontend.md`](layers/05-frontend.md) — the web UI

### 3. Engines (the intelligence)
- [`engines/01-discovery-engine.md`](engines/01-discovery-engine.md)
- [`engines/02-classification-engine.md`](engines/02-classification-engine.md)
- [`engines/03-topology-engine.md`](engines/03-topology-engine.md)
- [`engines/04-metrics-engine.md`](engines/04-metrics-engine.md)
- [`engines/05-logging-engine.md`](engines/05-logging-engine.md)
- [`engines/06-alert-engine.md`](engines/06-alert-engine.md)
- [`engines/07-ai-anomaly-engine.md`](engines/07-ai-anomaly-engine.md)
- [`engines/08-self-healing-engine.md`](engines/08-self-healing-engine.md)
- [`engines/09-dashboard-generator.md`](engines/09-dashboard-generator.md)
- [`engines/10-llm-observability-engine.md`](engines/10-llm-observability-engine.md)
- [`engines/11-diagnostic-agent.md`](engines/11-diagnostic-agent.md) — natural-language query & root-cause agent

### 4. Deployment & Release Management
- [`deployment/01-deployment-layer.md`](deployment/01-deployment-layer.md) — overview, triggers, engine design
- [`deployment/02-strategies.md`](deployment/02-strategies.md) — rolling / blue-green / canary
- [`deployment/03-rollback-and-healing.md`](deployment/03-rollback-and-healing.md) — smart rollback, drift & dependency validation

### 5. Cross-cutting references
- [`data-model.md`](data-model.md) — entities, relationships, PostgreSQL schema, metric/label conventions
- [`api-design.md`](api-design.md) — REST + WebSocket surface, auth, versioning
- [`security.md`](security.md) — authn/z, RBAC, multi-tenancy, secrets, threat model
- [`non-functional-requirements.md`](non-functional-requirements.md) — SLOs, scale targets, cardinality budget, sizing
- [`roadmap.md`](roadmap.md) — phased build order and milestones
- [`glossary.md`](glossary.md) — terminology

### 6. Build
- [`quickstart.md`](quickstart.md) — **Phase 0**: run the stack + enroll your first agent

---

## Key decisions (locked)

These were decided during doc finalization and drive the whole design:

| Decision | Choice | Rationale |
|---|---|---|
| Scope | **Full vision, phased** | Document everything, but ship MVP (Discover→Monitor→Alert) first |
| Event bus | **NATS (JetStream)** | Lightweight, simple ops, persistence, easy self-host |
| Orchestration target (v1) | **Docker standalone + Compose** | Matches the agent model; simplest to ship; Swarm/K8s abstracted for later |
| Agent language | **Python** | Single-language stack with the backend, mature Docker SDK, simple I/O-bound concurrency |
| Backend language | **Python / FastAPI** | Async, OpenAPI, plugin-friendly, ML ecosystem for anomaly/LLM engines |
| Metrics store | **VictoriaMetrics** | Better compression/retention than Prometheus, horizontal scale |
| Logs store | **Loki** | Low storage cost, label-based, Grafana-native |
| Metadata store | **PostgreSQL** | Relational truth for hosts/containers/rules/alerts/tenants |
| Docs format | **Markdown in `/docs`** | Version-controlled, review-friendly, build-ready |

Anything marked **`[DECISION PENDING]`** in a doc is an open question to resolve
before or during the phase that needs it.

---

## Conventions used in these docs

- **`[MVP]`** — part of Phase 1 (the first buildable version).
- **`[FUTURE]`** — a later phase; documented now for completeness.
- **`[DECISION PENDING]`** — an open design question.
- Diagrams are ASCII where possible for diff-friendliness; Mermaid where it adds clarity.
- Every engine doc follows the same template: *Purpose → Inputs → Outputs →
  Internals → Data → Interfaces → Failure modes → Phase*.
