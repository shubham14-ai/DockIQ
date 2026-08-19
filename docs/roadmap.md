# Roadmap

The build order. It follows the brief's recommended sequence, front-loaded with a
usable MVP so the product delivers value early while laying the foundation for the
full Docker Infrastructure Intelligence Platform.

> Guiding rule from the brief: *"That sequence gets you a usable product quickly
> while laying the foundation for a full platform."*

---

## Build order (from the brief)

```
1. Discovery Engine
2. Monitoring Engine (Metrics + Logging)
3. Alert Engine
4. Topology Engine
5. Dashboard Generator
6. Deployment Engine
7. Rollback Engine
8. Self-Healing Engine
9. AI Anomaly Detection
10. Multi-Tenant SaaS Platform
```

Mapped to phases below. Anomaly/self-healing appear *earlier in lite form*
(baseline z-score, restart-on-crash) and *mature later* — the intelligence
deepens over time rather than arriving all at once.

---

## Phase 0 — Foundations (enablement)  ✅ DONE (live-verified)

**Goal:** the skeleton everything plugs into.
- Repo + Compose stack: backend, NATS/JetStream, VictoriaMetrics, Loki, Postgres.
- Agent skeleton (Python): enrollment (mTLS), heartbeat, NATS connectivity.
- Backend skeleton (FastAPI): auth (OIDC + local), RBAC scaffold, tenant scoping,
  event-bus + store clients, engine interface.
- Shared label convention wired end-to-end.
- DockIQ dogfoods itself (monitors its own stack).

**Exit:** an agent enrolls and heartbeats; backend up with auth; stores reachable.

---

## Phase 1 — MVP: Discover → Monitor → Alert `[MVP]`  ✅ DONE (live-verified: 31 containers, metrics/logs/alerts flowing)

**Goal:** a genuinely useful monitoring product.
- **Discovery Engine** — full inventory (containers/images/networks/volumes),
  event fast-path + reconcile, host lifecycle.
- **Classification (passive)** — role + tech from image/labels/ports/env; label
  override. *(Foundation for everything.)*
- **Metrics Engine** — CPU/mem/net/disk + lifecycle counters → VictoriaMetrics,
  labeled; recording rules.
- **Logging Engine** — live tail, multi-container view, search via Loki.
- **Alert Engine** — threshold + health/event rules, default rules per role/tech,
  dedup/grouping, maintenance windows/suppression, basic routing.
- **UI** — Overview, Hosts, Containers (metrics+logs+classification+events),
  Alerts; WebSocket live event timeline; login.

**Exit:** connect a host → see classified containers, metrics, logs, and get
baseline alerts with **zero configuration**.

---

## Phase 2 — Topology & richer intelligence  ✅ DONE (live: 31-node graph / 177 edges, project-namespaced; 34 anomaly baselines)

> Delivered: Topology Engine (network + compose depends_on + env-ref edges,
> project-namespaced services), blast-radius endpoints, Topology UI (react-flow),
> Anomaly-lite (rolling robust-z baselines + expected bands). Remaining sub-item:
> alert blast-radius *grouping* (wiring topology into the Alert engine) — deferred
> to when Self-Healing lands in Phase 5.

**Goal:** understand the *system*.
- **Topology Engine** — static graph (networks + Compose `depends_on` + env refs),
  then observed connections; service aggregation.
- **Topology UI** — interactive dependency/communication graph.
- **Alert blast-radius** — group downstream alerts under root cause via topology.
- **Anomaly (lite)** — rolling robust-z baselines; expected bands in UI; optional
  baseline alerts.

**Exit:** the topology graph is live; alerts are correlated by dependency; charts
show "normal" bands.

---

## Phase 3 — Auto Dashboards & deeper monitoring

**Goal:** zero-config dashboards.
- **Dashboard Generator** — generic role templates + fleet overview, then
  per-technology deep templates; Grafana provisioning + embed.
- **Metrics depth** — adaptive hot sampling, cAdvisor integration, host metrics.
- **Logging depth** — log-based alert rules, structured-field filters.

**Exit:** detected technologies get dashboards automatically; no manual Grafana.

---

## Phase 4 — LLM Observability (flagship differentiator)

**Goal:** own the AI/LLM observability gap.
- **LLM Observability Engine** — app SDK/OTel ingest, cost table, vector-DB
  metric scrape (Qdrant/Chroma/Milvus), LLM dashboards (tokens/cost/latency).
- Anomaly baselines for LLM cost/latency.

**Exit:** teams see token usage, cost, prompt/RAG latency, and vector-DB perf
alongside infra.

---

## Phase 5 — Anomaly & Self-Healing maturity

**Goal:** proactive + self-operating.
- **AI Anomaly Engine** — seasonal models, forecasting/time-to-full, online
  learning, deploy-aware relearn.
- **Self-Healing Engine** — restart ladder → (later) rollback/scale/clear-cache/
  scripts, verification loops, policies, circuit breakers, dependency-aware order.
- **Diagnostic Query Agent** — natural-language front door: a prompt like *"check
  response latency for the last 5 messages"* or *"why did latency spike?"* becomes
  safe, read-only queries (PromQL/LogQL/named-SQL) plus a correlated root-cause
  answer. Report mode first (NL→query), then diagnose mode across Anomaly +
  Topology + Deployment records, then alert enrichment. See
  [Engine 11](engines/11-diagnostic-agent.md).

**Exit:** forecasted-breach alerts; crash-loops auto-remediated safely with full
audit; operators can ask DockIQ questions in plain English and get grounded,
auditable answers.

---

## Phase 6 — Deployment & Release Management

**Goal:** monitoring → operations.
- **Deployment Engine** — webhooks (GitHub/GitLab/Bitbucket/registry) + manual
  trigger; rolling → blue-green → canary; health/smoke/metric validation.
- **Smart Rollback** — automatic rollback on regression; known-good capture.
- **Deployment intelligence** — dependency validation, drift detection, risk
  scoring; deployment dashboard; multi-host coordination.

**Exit:** a bad deploy is detected and rolled back automatically; deploys are
gated by dependency health and drift.

---

## Phase 7 — Multi-Tenant SaaS & Enterprise

**Goal:** productize.
- Full multi-tenant isolation (SaaS), org/billing.
- Enterprise: approval workflows, change management, cost impact, Vault, GitOps,
  AI risk assessment, incident integrations (Jira/ServiceNow), auto-scaling
  recommendations.
- Scale-out: HA backend, NATS cluster, VictoriaMetrics cluster, engine extraction
  to services.
- Orchestration expansion: Swarm, then Kubernetes.

**Exit:** DockIQ runs as a multi-tenant SaaS and/or hardened on-prem enterprise
platform.

---

## Phasing of the 10 engines (at a glance)

| Engine | First appears | Matures |
|---|---|---|
| Discovery | Phase 1 | Phase 1 |
| Classification | Phase 1 (passive) | Phase 3 (active probing) |
| Metrics | Phase 1 | Phase 3 |
| Logging | Phase 1 | Phase 3 |
| Alert | Phase 1 (threshold) | Phase 2 (baseline/blast-radius) |
| Topology | Phase 2 (static) | Phase 5+ (dynamic/eBPF) |
| Anomaly | Phase 2 (lite) | Phase 5 (seasonal/forecast) |
| Dashboard Generator | Phase 3 | Phase 4 (LLM/deploy dashboards) |
| LLM Observability | Phase 4 | Phase 6 (deploy-cost validation) |
| Diagnostic Agent | Phase 5 (report mode) | Phase 6+ (deep diagnose/incident summaries) |
| Self-Healing | Phase 1 (restart) | Phase 5 (full ladder) |
| Deployment layer | Phase 6 | Phase 7 (Swarm/K8s/enterprise) |

---

## Open decisions to resolve along the way

Tracked in [Tech Stack §13](02-tech-stack.md#13-open-decisions):
- **D-1** Agent↔backend control channel (gRPC vs WSS) — resolve in Phase 1.
- **D-2** Frontend framework — resolve in Phase 1.
- **D-3** Topology graph library — resolve in Phase 2.
- **D-4** cAdvisor sidecar vs agent-native stats — resolve in Phase 1/3.
- **D-5** Grafana embed vs native dashboards — resolve in Phase 3.

---

## Definition of "MVP done"

A new user can:
1. Deploy the DockIQ stack (Compose) and add a host (agent + join token).
2. Immediately see every container **classified** (role + tech).
3. View **metrics** and **live logs** per container.
4. Receive **baseline alerts** with no rules written.
5. Do all of the above through an authenticated, RBAC-scoped UI.

That is a usable product — and the foundation for Phases 2–7.
