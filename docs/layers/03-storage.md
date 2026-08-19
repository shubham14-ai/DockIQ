# Layer: Storage

DockIQ uses three purpose-built stores. Each data shape goes to the store built
for it, and a **shared label convention** ties them together so metrics, logs,
and metadata correlate cleanly.

| Store | Data shape | Holds |
|---|---|---|
| **VictoriaMetrics** | time-series | CPU/mem/net/disk metrics, health, deploy KPIs, LLM metrics |
| **Loki** | log streams | container stdout/stderr, indexed by label |
| **PostgreSQL** | relational | hosts, containers, classifications, topology, rules, alerts, deployments, tenants, users, audit |

---

## 1. Shared label convention (the glue)

Every metric series and every log stream carries the same core labels so you can
pivot from a chart to the exact logs to the container record:

```
tenant       = <tenant_id>
host_id      = <stable host id>
container_id = <docker container id>
container    = <human name>
image        = <image ref>
service      = <compose/service name or detected service>
role         = api|db|cache|queue|worker|frontend|vectordb|ai|unknown
tech         = fastapi|postgres|redis|kafka|qdrant|...   (from Classification)
```

`role` and `tech` are injected from the [Classification Engine](../engines/02-classification-engine.md),
so dashboards and alerts can target "all databases" or "all Redis instances"
without hardcoding container names.

---

## 2. VictoriaMetrics (metrics)

### Why
Better compression and retention than Prometheus, horizontal scaling, and
Prometheus-compatible (PromQL + remote-write) so cAdvisor/agent exporters and
Grafana work unchanged. See [Tech Stack §4](../02-tech-stack.md).

### What lands here
- Container resource metrics: `dockiq_cpu_usage_ratio`, `dockiq_mem_usage_bytes`,
  `dockiq_mem_limit_bytes`, `dockiq_net_rx_bytes`, `dockiq_net_tx_bytes`,
  `dockiq_blkio_read_bytes`, `dockiq_blkio_write_bytes`, restart counts, OOM counts.
- Health/uptime: `dockiq_container_up`, `dockiq_health_status`.
- Deployment KPIs: error rate, latency, per-version series (labeled `version`).
- LLM metrics: tokens, prompt latency, cost, embedding/RAG latencies (see
  [LLM Observability](../engines/10-llm-observability-engine.md)).

### Ingestion
- Agents send via **remote-write** (efficient, batched) and/or NATS→ingest.
- Optionally scrape cAdvisor as an additional source.

### Retention (defaults, tunable)
- High-res (5s/1s): ~15 days.
- Downsampled rollups: ~13 months. `[FUTURE]` (downsampling)

### Deployment
- v1: single-node VictoriaMetrics. `[MVP]`
- Scale: VictoriaMetrics cluster (vminsert/vmselect/vmstorage). `[FUTURE]`

---

## 3. Loki (logs)

### Why
Low storage cost (indexes labels, not full text), Grafana-native, and its label
model matches our convention — same labels as metrics, so correlation is trivial.
See [Tech Stack §5](../02-tech-stack.md).

### What lands here
- Container stdout/stderr lines, streamed by the agent's LogShipper.
- Labels: the shared convention (§1). Log *content* is stored; only labels are
  indexed → cheap.

### Ingestion
- Agents push directly to Loki (`/loki/api/v1/push`) in batches, with tail
  checkpointing for reliability.

### Query
- Backend queries via **LogQL**; the UI log viewer supports tail, search, and
  multi-container views (Dozzle-style, see [Logging Engine](../engines/05-logging-engine.md)).

### Retention
- Default 7–30 days, per-tenant configurable. Object storage backend for cheap
  long retention. `[FUTURE for object-store tiering]`

---

## 4. PostgreSQL (source of truth)

### Why
Relational integrity for the entities that must be consistent, JSONB for flexible
per-entity metadata, mature async drivers. See [Tech Stack §6](../02-tech-stack.md).

### What lands here
The authoritative records (full schema in [Data Model](../data-model.md)):
- **Inventory:** `tenants`, `hosts`, `containers`, `images`, `networks`, `volumes`
- **Intelligence:** `classifications`, `detected_technologies`, `topology_edges`
- **Ops:** `alert_rules`, `alerts`, `incidents`, `maintenance_windows`,
  `deployments`, `releases`, `rollbacks`
- **Platform:** `users`, `roles`, `permissions`, `api_keys`, `audit_log`
- **Event timeline:** `events` (container lifecycle, health transitions) — recent
  window; older archived.

### Access
- Async SQLAlchemy 2.0 / asyncpg, repository pattern, all queries tenant-scoped.

### Retention
- Alerts/incidents/deployments/audit: indefinite.
- Events timeline: ~90 days then archive.

---

## 5. Why not one store for everything

- **Time-series in Postgres** doesn't scale for per-second, per-container metrics
  across many hosts (cardinality + retention cost) — hence VictoriaMetrics.
- **Full-text logs in Postgres/ES** is expensive; Loki's label-indexed model is
  far cheaper for the "tail + filter by container" access pattern we need.
- **Relational truth in a TSDB** loses joins/constraints — hence PostgreSQL for
  entities and relationships.

Right tool per shape, unified by the shared label convention.

---

## 6. Correlation example

From a CPU spike chart to root cause, all keyed by the same labels:

```
VictoriaMetrics:  dockiq_cpu_usage_ratio{container="api-1"} spikes at 14:03
        │  (same labels: host_id, container_id, service, role, tech)
        ▼
Loki:             {container="api-1"} |= "error"  around 14:03  → stack traces
        │
        ▼
PostgreSQL:       events where container_id=... → "image updated to app:2.4.1 at 14:01"
        ▼
Conclusion:       deploy at 14:01 caused CPU spike + errors → Deployment layer rolls back
```

---

## 7. Backup & DR

| Store | Backup approach |
|---|---|
| PostgreSQL | Regular logical/physical backups (pg_dump / WAL archiving); the critical store |
| VictoriaMetrics | `vmbackup`/snapshots to object storage |
| Loki | Object-storage backend is itself durable; snapshot config/index |

PostgreSQL is the crown jewel (irreplaceable truth); metrics/logs are large but
regenerable-in-part and time-bounded.

---

## 8. Phase

- **`[MVP]`** Single-node VictoriaMetrics, Loki, PostgreSQL; shared label
  convention; core inventory + metrics + logs + alerts tables.
- **`[FUTURE]`** Downsampling/rollups, object-storage tiering, cluster modes,
  cross-region DR.
