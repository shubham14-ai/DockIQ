# Technology Stack

Every technology choice, with rationale and the alternatives considered. Choices
marked **locked** were decided during doc finalization; **`[DECISION PENDING]`**
items are open.

---

## 1. Summary table

| Concern | Choice | Status | Key alternative(s) |
|---|---|---|---|
| Agent language | **Python** | locked | Go, Rust |
| Backend language/framework | **Python + FastAPI** | locked | Go, Node.js/NestJS |
| Metrics store | **VictoriaMetrics** | locked | Prometheus, Thanos, Mimir |
| Log store | **Loki** | locked | Elasticsearch/OpenSearch, ClickHouse |
| Metadata DB | **PostgreSQL** | locked | MySQL, CockroachDB |
| Event bus | **NATS (JetStream)** | locked | Kafka, Redpanda, RabbitMQ |
| Metric source (concepts) | **cAdvisor / Docker stats** | locked | build custom (rejected) |
| Dashboards | **Grafana (provisioned) + native UI** | locked | fully custom charts only |
| Frontend | **React + TypeScript** | proposed | Vue, Svelte |
| Graph/topology viz | **Cytoscape.js / react-flow** | proposed | D3 custom, vis.js |
| Agent↔backend channel | **NATS (control+telemetry) + REST (enrollment)** | locked (D-1 resolved) | gRPC, WSS |
| Anomaly/ML | **Python (statsmodels/Prophet/river)** | proposed | dedicated ML service |
| Container runtime target (v1) | **Docker Engine + Compose** | locked | Swarm, K8s `[FUTURE]` |

---

## 2. Agent — Python **(locked)**

**Why Python:**
- **Single-language stack** — the backend and all engines are already Python; a
  Python agent means one language, one toolchain, and shared idioms end-to-end.
- **Mature Docker SDK** — the official `docker` Python SDK (docker-py) covers
  everything the agent needs: events, stats, logs, inspect, and command
  execution.
- **Concurrency that fits the workload** — the agent is I/O-bound (streaming from
  the Docker socket), so a thread-per-stream model with a dedicated asyncio loop
  for NATS is simple and more than fast enough; the GIL is a non-issue for
  blocking socket reads.
- **Easy distribution** — shipped as a slim container image that mounts the
  Docker socket (`python:3.12-slim`); no separate build toolchain on target hosts.

**Alternatives:**
- *Go* — lower memory and a single static binary, but splits the codebase across
  two languages and doubles the toolchain/skills surface for little gain on an
  I/O-bound agent. (This was the original choice; moved to Python for a unified
  stack.)
- *Rust* — even lower footprint, but slowest to build and heaviest to staff; not
  worth the velocity hit.

## 3. Backend — Python + FastAPI **(locked)**

**Why FastAPI:**
- **Async** — high-concurrency I/O to agents, stores, and the event bus.
- **Automatic OpenAPI** — the API surface documents and validates itself
  (Pydantic models); great DX and client generation.
- **Plugin-friendly** — engines register as modules; clean dependency injection.
- **ML ecosystem** — the AI Anomaly and LLM Observability engines live where
  numpy/pandas/statsmodels/torch already are.
- **Team familiarity** — matches the intended stack.

**Alternatives:**
- *Go backend* — great performance, but loses the Python ML ecosystem the
  intelligence engines depend on; would force a separate ML service.
- *Node/NestJS* — fine API layer, weaker data/ML story.

## 4. Metrics store — VictoriaMetrics **(locked)**

**Why VictoriaMetrics instead of Prometheus:**
- **Better compression** — dramatically lower disk for the same data.
- **Better long-term retention** — built for it; Prometheus is not.
- **Horizontal scaling** — cluster mode for growth.
- **Prometheus-compatible** — speaks PromQL + remote-write, so cAdvisor/agent
  exporters and Grafana work unchanged.

**Alternatives:** Prometheus (retention/scale limits), Thanos/Mimir (more moving
parts), TimescaleDB (SQL-TS, but PromQL/Grafana ecosystem weaker for this shape).

## 5. Log store — Loki **(locked)**

**Why Loki:**
- **Low storage cost** — indexes labels, not full text; cheap object storage.
- **Grafana-native** — seamless with the dashboard layer.
- **Label model** — aligns with our metric/label conventions (same
  container/host/tenant labels across metrics and logs → easy correlation).

**Alternatives:** Elasticsearch/OpenSearch (powerful full-text, heavy + costly),
ClickHouse (excellent, but more custom integration work).

## 6. Metadata DB — PostgreSQL **(locked)**

**Stores:** hosts, containers, classifications, detected technologies, topology
edges, alert rules, alert instances, deployments/releases, tenants, users, RBAC,
audit log.

**Why Postgres:** relational integrity for the "source of truth," JSONB for
flexible per-entity metadata, mature ecosystem, `LISTEN/NOTIFY` if needed,
strong async drivers (asyncpg/SQLAlchemy 2.0).

## 7. Event bus — NATS / JetStream **(locked)**

**Why NATS over Kafka:**
- **Lightweight & simple ops** — a single small binary; no ZooKeeper/KRaft
  complexity to babysit.
- **JetStream persistence** — durable, replayable streams and consumers, so a
  briefly-down engine misses nothing.
- **Subjects & wildcards** — natural fit for `dockiq.<tenant>.<host>.<kind>`
  routing.
- **Easy self-host** — critical for an on-prem/self-hosted product.

**When we'd revisit Kafka:** very high sustained event volume across many large
tenants, or a need for the broader Kafka connector ecosystem. Documented as a
future scaling option; the event layer is written behind an interface so the
broker can be swapped. See [Event Streaming](layers/04-event-streaming.md).

## 8. Metric source — cAdvisor / Docker stats **(locked)**

**Do not reinvent low-level metric collection.** The agent uses the Docker stats
API directly, and cAdvisor remains the reference for container CPU/memory/
network/disk/lifecycle metrics and OOM detection. We integrate its concepts and,
where useful, run it as a metrics source scraped into VictoriaMetrics.

## 9. Dashboards — Grafana + native UI **(locked)**

- **Grafana** for rich, provisioned dashboards (the Dashboard Generator writes
  Grafana dashboard JSON from detected technologies) and Loki log panels.
- **Native UI** for the DockIQ-specific views (topology graph, classification,
  deployment console, LLM observability) that Grafana can't express well.

## 10. Frontend — React + TypeScript **(proposed)**

- Mature ecosystem, strong typing against the OpenAPI schema (generated client).
- **Topology graph:** Cytoscape.js or react-flow for the service dependency /
  communication graph.
- **Charts:** embed Grafana panels where possible; use a lightweight chart lib
  (e.g. Recharts/visx) for native views.

> Frontend framework is *proposed*, not locked — confirm before Phase where the
> UI is built. See [Frontend layer](layers/05-frontend.md).

## 11. AI / anomaly stack — Python **(proposed)**

- **Baselines & forecasting:** statsmodels / Prophet / `river` (online learning)
  for streaming baselines.
- **Anomaly detection:** seasonal decomposition + robust z-score / STL, with
  room for ML models later.
- **LLM observability:** OpenTelemetry-style instrumentation ingested from apps,
  plus proxy/sidecar metrics.

Runs in-process on the backend in v1; extractable to a dedicated service later.

## 12. Cross-cutting

| Concern | Choice |
|---|---|
| Container packaging | Docker + Compose (self-deploy); agent as a slim Python container |
| Config | Env vars + mounted config; secrets via env/file, Vault integration `[FUTURE]` |
| Observability of DockIQ itself | DockIQ monitors DockIQ (dogfood) + standard logs/metrics |
| CI events ingestion | Webhooks: GitHub/GitLab/Bitbucket/Docker Hub/registry |
| AuthN | OIDC/SSO + local users; API keys for agents/automation |
| AuthZ | RBAC (roles → permissions), tenant scoping |

---

## 13. Open decisions

| ID | Decision | Recommendation | Resolve by |
|---|---|---|---|
| ~~D-1~~ | ~~Agent↔backend control channel~~ **RESOLVED** → NATS (control+telemetry) + REST (enrollment). Rationale: the agent already speaks NATS; adding gRPC/WSS is a second protocol with no Phase-0 payoff. Revisit gRPC only if a typed, high-throughput control channel is later needed. | — | done (Phase 0) |
| D-2 | Frontend framework | React + TS | UI build (Phase 1/2) |
| D-3 | Topology graph library | Cytoscape.js | Topology UI (Phase 2) |
| D-4 | Run cAdvisor as sidecar vs agent-native stats only | Agent-native + optional cAdvisor | Metrics build (Phase 1) |
| D-5 | Grafana embedded vs fully native dashboards | Hybrid (Grafana + native) | Dashboard Generator (Phase 3) |

See [Roadmap](roadmap.md) for when each phase happens.
