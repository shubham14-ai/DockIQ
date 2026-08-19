# Glossary

Terminology used across the DockIQ documentation.

---

### Platform terms

- **DockIQ** — Docker + Intelligence. The platform: a Docker Infrastructure
  Intelligence Platform (not just monitoring).
- **Control Plane** — the central brain: backend, engines, event bus, stores, UI.
  Usually one deployment.
- **Data Plane** — the agents running on monitored hosts; observe and act, never
  decide.
- **Agent** — the Python service on each Docker host: events, stats, discovery, health,
  logs, topology, heartbeat, command execution.
- **Backend** — the FastAPI control-plane service hosting the API and engines.
- **Engine** — one of the 10 intelligence modules (Discovery, Classification,
  Topology, Metrics, Logging, Alert, Anomaly, Self-Healing, Dashboard Generator,
  LLM Observability).
- **Deployment/Release Layer** — the operations layer on top of the engines
  (deploy, validate, rollback).

### Data & storage

- **VictoriaMetrics** — the time-series (metrics) store; Prometheus-compatible.
- **Loki** — the log store; indexes labels, not full text.
- **PostgreSQL** — the relational source of truth (inventory, rules, alerts,
  deployments, audit, tenants).
- **NATS / JetStream** — the event bus; JetStream adds durable, replayable
  streams.
- **Shared label convention** — the common labels (`tenant, host_id,
  container_id, container, image, service, role, tech`) applied to metrics, logs,
  and metadata so they correlate.
- **Cardinality** — the number of unique label-value combinations; must be bounded
  to keep the TSDB healthy.

### Intelligence concepts

- **Discovery** — building the live inventory of hosts/containers/networks/volumes.
- **Classification** — auto-assigning a container's **role** and **technology**.
- **Role** — functional class: `api | worker | database | queue | cache |
  frontend | vectordb | ai | proxy | unknown`.
- **Technology (tech)** — the specific software (fastapi, postgres, redis, kafka,
  qdrant, …).
- **Topology** — the service dependency + runtime communication graph.
- **Declared / Observed / Inferred edge** — a dependency known from config /
  seen at runtime / deduced.
- **Blast radius** — the set of services affected when one service fails
  (computed from topology).
- **Baseline** — the learned "normal" for a metric series (value + variation,
  incl. seasonality).
- **Anomaly** — a statistically significant deviation from baseline.
- **Forecast** — a short-horizon prediction (e.g. time-to-disk-full).

### Operations

- **Alert** — a fired condition (threshold, baseline, forecast, log-rate, event).
- **Incident** — a grouped set of alerts under a root cause; may page humans.
- **Maintenance window / Silence** — suppression of alerts for a scope/time.
- **Self-Healing ladder** — restart → rollback → scale → clear cache → run script
  → open incident.
- **Policy gate** — the safety check controlling whether an automatic action is
  allowed.
- **Deployment strategy** — Rolling / Blue-Green / Canary.
- **Smart Rollback** — automatic restoration of the previous known-good version on
  regression.
- **Known-good** — the last release verified healthy; the rollback target.
- **Drift** — a mismatch between environments (env vars, compose, network,
  volumes, secrets).
- **Dependency validation** — checking required dependencies are healthy before a
  deploy.
- **Risk score** — pre-flight `LOW/MEDIUM/HIGH` estimate of a release's danger.

### LLM observability

- **Token usage** — prompt/completion/total tokens per request.
- **TTFT** — time to first token (a latency component).
- **RAG** — Retrieval-Augmented Generation; retrieval latency is measured
  separately from generation.
- **Vector DB** — Qdrant / ChromaDB / Milvus / Weaviate / pgvector; performance
  (query latency, index size) is observed.
- **Cost model / price table** — maps tokens × model price → dollars.

### Security

- **Tenant** — an isolation boundary; every entity carries `tenant_id`.
- **RBAC** — role-based access control (roles → permissions).
- **mTLS** — mutual TLS; both sides present certificates.
- **Join token** — one-time, short-lived token to enroll an agent.
- **Audit log** — append-only record of every mutating action (manual + automatic).
- **Redaction** — masking/hashing secret-like values before storage.

### Doc conventions

- **`[MVP]`** — part of Phase 1 (first buildable version).
- **`[FUTURE]`** — a later phase; documented now for completeness.
- **`[DECISION PENDING]`** — an open design question (see
  [Tech Stack §13](02-tech-stack.md#13-open-decisions)).
