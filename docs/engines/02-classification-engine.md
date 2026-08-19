# Engine 2: Classification Engine

> **The foundation of everything.** When a container starts, DockIQ automatically
> answers two questions: *what technology is this?* (FastAPI, PostgreSQL, Redis,
> Qdrant…) and *what role does it play?* (API, DB, cache, queue, worker, frontend,
> vector DB, AI service). Every downstream engine keys off these answers.

This is one of DockIQ's core **differentiators** — no major Docker monitoring
project does automatic technology detection well.

---

## Purpose

- **Technology detection:** identify the software running in a container from the
  supported catalog.
- **Role classification:** assign a functional role used across dashboards,
  alerts, and topology.
- Do it **automatically, zero-config**, and expose confidence + evidence so
  humans can trust or override it.

---

## The two outputs

### Role (functional class)
```
api | worker | database | queue | cache | frontend | vectordb | ai | proxy | unknown
```

### Technology (specific software)
Catalog (initial, extensible):
```
Web/API:     fastapi, django, flask, express/node, nginx, traefik, caddy, gunicorn
Data:        postgres, mysql, mariadb, mongodb, redis, memcached, elasticsearch
Messaging:   kafka, rabbitmq, nats
Vector DB:   qdrant, chromadb, milvus, weaviate, pgvector
AI/Orchestration: langgraph, airflow, celery, ollama, vllm, triton
Observability: prometheus, grafana, loki, victoriametrics
```

---

## Detection sources (evidence)

Classification is **evidence-based**: it gathers signals, scores candidates, and
picks the best with a confidence. Sources, from the brief:

| Source | Example signal |
|---|---|
| **Image name/digest** | `postgres:16`, `qdrant/qdrant`, `redis:7` |
| **Docker labels** | `org.opencontainers…`, custom `com.dockiq.tech` overrides |
| **Exposed ports** | 5432→postgres, 6379→redis, 9092→kafka, 6333→qdrant |
| **OpenAPI endpoints** | `/openapi.json` + server header → FastAPI vs Flask |
| **Running processes** | `postgres`, `redis-server`, `celery`, `gunicorn` (via agent) |
| **Environment variables** | `POSTGRES_PASSWORD`, `REDIS_URL`, `CELERY_BROKER_URL` |

No single source is trusted alone — a container named `app` on port 8000 could be
FastAPI *or* Flask; the `/openapi.json` structure + process (`uvicorn`) decides.

---

## Internals

```
container discovered (Discovery)
        │  facts: image, labels, ports, env, processes, probes
        ▼
┌─────────────────────────────────────────────┐
│  Signal extractors (one per source)          │
│   image · labels · ports · openapi · procs · env
└───────────────┬─────────────────────────────┘
                ▼
        ┌───────────────┐   weighted rules + catalog
        │  Scorer        │──▶ candidate techs with scores
        └───────┬───────┘
                ▼
        ┌───────────────┐
        │  Resolver      │──▶ best tech + role + confidence + evidence
        └───────┬───────┘
                ▼   persist + inject labels (tech, role)
        classifications / detected_technologies (Postgres)
                │
                └──▶ Metrics/Loki labels · Dashboards · Alerts · Topology
```

- **Rule catalog:** declarative rules map signals → candidate (tech, role, weight).
  Editable/extensible without code changes (YAML/DB-driven).
- **Active probing** (optional, agent-assisted): fetch `/openapi.json`,
  `/-/healthy`, banner on a port — only for reachable, non-destructive endpoints.
- **Confidence:** aggregate weighted evidence; below a threshold → `unknown` with
  the top guesses recorded.
- **Override:** a `com.dockiq.tech` / `com.dockiq.role` label (or UI action)
  forces classification and is always authoritative.
- **Re-classification:** on image change (deploy) the container is re-evaluated.

---

## Why classification is upstream of everything

```
classify → role=database, tech=postgres
   ├─ Dashboards: generate the PostgreSQL dashboard
   ├─ Alerts: attach DB-appropriate baseline rules (connections, replication lag)
   ├─ Topology: render as a DB node; expect inbound from services
   ├─ Metrics: label series role=db tech=postgres for "all databases" queries
   └─ Deployment: dependency validation treats it as a stateful dependency
```

Without this, dashboards/alerts must be hand-built per container. With it, the
platform is zero-config.

---

## Data

`classifications`: `container_id, role, tech, confidence, evidence(jsonb),
source, overridden(bool), classified_at`.
`detected_technologies`: catalog + version where detectable.

---

## Interfaces

- Consumes: `discovery.container.added|updated`, agent probe results.
- Emits: `classification.updated` (role/tech) → Dashboards, Alerts, Topology,
  Metrics label injection.
- API: `GET /containers/{id}/classification`, `POST /containers/{id}/classification`
  (manual override), `GET /catalog/technologies`.

---

## Failure modes

| Failure | Handling |
|---|---|
| Ambiguous signals | Return top candidates + `unknown` role until more evidence; re-probe |
| Custom/obscure image | Falls to `unknown`; label override available; catalog extensible |
| Probe blocked (no network access) | Degrade to passive sources (image/ports/env) |
| Misclassification | User override wins and is remembered; feeds catalog tuning |

---

## Phase

- **`[MVP]`** Passive detection (image, labels, ports, env) + role assignment for
  the common catalog; label override.
- **`[FUTURE]`** Active probing (OpenAPI/banners), process-based detection via
  agent, version detection, learned/tunable weights, broader catalog.
