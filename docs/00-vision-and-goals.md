# Vision & Goals

## 1. The problem

Running containerized infrastructure today means stitching together many tools:

- **cAdvisor / Netdata** for resource metrics
- **Dozzle** for logs
- **Prometheus + Grafana + Alertmanager** for dashboards and alerting
- **DockMon**-style tools for multi-host management, RBAC, alerts
- Ad-hoc scripts for deployment and rollback

Each tool sees only its slice. **None of them understands the system.** They
don't know that a container is a PostgreSQL database, that a FastAPI service
depends on it, that the current CPU of 70% is abnormal because this container
normally sits at 20%, or that a deploy 3 minutes ago is the reason the error
rate spiked.

Operators are left doing the intelligence work by hand: correlating, diagnosing,
deciding to roll back, building dashboards, wiring alerts.

## 2. The vision

> **DockIQ is a Docker Infrastructure Intelligence Platform** — it discovers,
> understands, monitors, and *operates* Docker infrastructure with minimal human
> configuration.

The guiding principle: **the platform should understand the infrastructure the
way a senior SRE does**, and then act on that understanding.

The full operational loop DockIQ owns:

```
Discover → Classify → Monitor → Analyze → Alert → Deploy → Validate → Rollback → Self-Heal
```

## 3. What DockIQ is (and is not)

**DockIQ IS:**
- A zero-config-first platform: point it at a Docker host and it *figures out*
  what's there.
- Opinionated intelligence: it classifies containers, detects technologies,
  maps dependencies, and learns baselines automatically.
- An operations platform: it can deploy, validate, roll back, and self-heal.
- Multi-host and (eventually) multi-tenant.

**DockIQ IS NOT:**
- A reinvention of low-level metric collection — it *reuses* proven sources
  (cAdvisor concepts, Docker stats) rather than rebuilding them.
- A generic APM for application code tracing (though LLM observability is a
  first-class exception).
- A Kubernetes-first platform in v1 — Docker standalone/Compose is the initial
  target, with the architecture kept orchestrator-agnostic for later.

## 4. Non-goals (explicit)

- **v1 does not target Kubernetes.** The agent and engines are designed with an
  orchestrator abstraction so K8s can be added, but it is out of scope for the
  first buildable version. `[FUTURE]`
- **DockIQ does not replace CI.** It *receives* build/release events from CI
  systems; it does not build images itself (initially).
- **DockIQ does not do application-level distributed tracing** in v1 (outside
  the LLM observability slice).
- **No agentless mode in v1.** An agent must run on each monitored host.

## 5. The unique differentiators

These are the capabilities no existing Docker monitoring project does well, and
they are DockIQ's reason to exist:

1. **Technology Detection Engine** — automatically identify FastAPI, Django,
   Flask, Node.js, Kafka, Redis, PostgreSQL, Qdrant, ChromaDB, Milvus,
   LangGraph, Airflow, Celery, and more, from image names, labels, ports,
   OpenAPI endpoints, processes, and env vars.
2. **Automatic Dashboard Generator** — detect a technology → generate the right
   dashboard. No manual Grafana setup.
3. **Service Relationship Discovery** — build the real dependency graph
   (Frontend → FastAPI → Redis → PostgreSQL), including runtime communication.
4. **AI/LLM Observability** — token usage, prompt latency, LLM cost, embedding
   requests, RAG retrieval latency, vector DB performance. A large, unserved
   market gap.
5. **Self-Healing Engine** — beyond restart: rollback, scale, clear cache, run
   recovery scripts, open incidents.
6. **Intelligent Alert Engine** — baseline learning, forecasting, anomaly
   detection, and alert deduplication instead of static thresholds.
7. **Auto Classification Engine** — every container is automatically classified
   (API, Worker, DB, Queue, Cache, Frontend, Vector DB, AI Service). This
   classification is the foundation everything else builds on.

## 6. Success criteria

The platform is succeeding if, for a newly connected Docker host:

- **Discovery:** 100% of running containers appear within one discovery cycle.
- **Classification:** ≥ 90% of common containers are correctly classified with
  no manual input.
- **Detection:** the technology behind each container is identified for the
  supported catalog (see [Classification Engine](engines/02-classification-engine.md)).
- **Zero-config value:** an operator gets useful dashboards and baseline alerts
  **without writing a single rule or dashboard**.
- **Operational trust:** a bad deploy is automatically detected and rolled back
  before a human would have noticed.

## 7. Personas

| Persona | Needs | DockIQ value |
|---|---|---|
| **Platform/SRE engineer** | Multi-host visibility, alerting, incident response | Unified topology, baseline alerts, self-healing |
| **Backend/ML developer** | Know if my service + its deps are healthy; LLM cost/latency | Auto dashboards, service graph, LLM observability |
| **DevOps/release engineer** | Safe deploys, rollback, drift detection | Deployment layer, smart rollback, config drift |
| **Engineering manager / owner** | Cost impact, reliability, audit | Cost analysis, audit logs, incident history |

## 8. Guiding design values

1. **Zero-config first, configurable second.** Sensible automatic behavior out
   of the box; every automatic decision is overridable.
2. **Understand before acting.** No self-healing or rollback without a model of
   normal.
3. **Reuse proven components.** Don't rebuild metric collection, log storage, or
   dashboards from scratch.
4. **Safe by default.** Destructive actions (rollback, scale-down, deletion)
   require policy and are auditable.
5. **Orchestrator-agnostic core.** Docker first, but abstractions ready for
   Swarm/K8s.

## 9. The name

**DockIQ = Docker + Intelligence.** Short, brandable, enterprise-friendly. If
the platform later grows beyond Docker (VMs, K8s, cloud), the "IQ" (intelligence)
remains the core promise. See [`raw_info/info.txt`](../raw_info/info.txt) for the
naming exploration that led here.
