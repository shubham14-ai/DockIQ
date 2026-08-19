# Engine 4: Metrics Engine

> **Collect and store the numbers.** The Metrics Engine ingests per-container
> resource metrics into VictoriaMetrics and serves them to dashboards, alerts,
> anomaly detection, and deployment validation. It *reuses* proven metric sources
> (Docker stats / cAdvisor) rather than reinventing collection.

---

## Purpose

- Sample and store time-series for every container: CPU, memory, network, disk
  I/O, plus lifecycle counters (restarts, OOM).
- Apply the [shared label convention](../layers/03-storage.md#1-shared-label-convention-the-glue)
  so metrics correlate with logs and metadata.
- Expose a clean query path (PromQL) to everything downstream.

---

## Metrics collected (from the brief)

| Category | Series (examples) |
|---|---|
| **CPU** | `dockiq_cpu_usage_ratio`, per-core, throttling |
| **Memory** | `dockiq_mem_usage_bytes`, `dockiq_mem_limit_bytes`, cache/rss, `dockiq_mem_usage_ratio` |
| **Network** | `dockiq_net_rx_bytes`, `dockiq_net_tx_bytes`, packets, errors, drops |
| **Disk** | `dockiq_blkio_read_bytes`, `dockiq_blkio_write_bytes`, iops |
| **Lifecycle** | `dockiq_restarts_total`, `dockiq_oom_kills_total`, `dockiq_container_up` |
| **Host** | node CPU/mem/disk/net (Node-Exporter concepts) |

> **Do not reinvent low-level collection.** The agent reads the Docker stats API
> directly; cAdvisor remains the reference and can be scraped as an additional
> source. OOM detection comes from Docker events + cgroup counters.

---

## Inputs

| Input | Source |
|---|---|
| Per-container stats samples | Agent StatsSampler (Docker stats API) |
| Host metrics | Agent / Node Exporter concepts |
| cAdvisor scrape (optional) | cAdvisor sidecar |
| Labels (role/tech/service) | Classification Engine |

---

## Outputs

- Time-series in **VictoriaMetrics**, fully labeled.
- PromQL query API to: Dashboards, Alert Engine, Anomaly Engine, Deployment
  validation, UI panels.

---

## Internals

```
agent stats ──remote-write──▶ VictoriaMetrics
     │                              ▲
     │ notify (light)               │ query (PromQL)
     ▼                              │
   NATS ─▶ Metrics Engine ──────────┘
                │
                ├─ ensure labels (role/tech/service) applied
                ├─ derive rollups (rates, ratios) as recording rules
                └─ flag "hot" containers → agent raises sample rate
```

- **Ingestion path:** bulk samples go via **remote-write** straight to
  VictoriaMetrics (efficient, backpressure-aware); lightweight notifications on
  NATS let engines react without carrying bulk data on the bus (see
  [Data Flow §2](../03-data-flow.md)).
- **Label injection:** the engine ensures every series carries `role`/`tech`/
  `service` from Classification so "all Redis" / "all databases" queries work.
- **Recording rules:** common derived series (CPU ratio, mem ratio, network rate)
  precomputed for cheap dashboards/alerts.
- **Adaptive sampling:** default 5s; containers under investigation (alerting,
  deploying, anomalous) can be bumped toward per-second ("hot") — Netdata-style
  high-resolution when it matters.
- **Cardinality control:** labels are bounded and curated (no unbounded label
  values like request IDs) to keep VictoriaMetrics healthy.

---

## Query patterns it enables

```promql
# All databases with high memory
dockiq_mem_usage_ratio{role="db"} > 0.9

# Redis network throughput across the fleet
sum by (container) (rate(dockiq_net_tx_bytes{tech="redis"}[5m]))

# Error/latency per deployment version (deploy validation)
dockiq_http_error_ratio{service="api", version="2.4.1"}
```

---

## Data

Series in VictoriaMetrics; metric names namespaced `dockiq_*`; labels per the
shared convention. Metric metadata (units, help) documented in [Data Model](../data-model.md#metric-conventions).

---

## Interfaces

- Consumes: `*.metrics` notifications; remote-write ingest.
- Serves: PromQL via backend proxy → Dashboards/Alerts/Anomaly/Deployment/UI.
- API: `GET /metrics/query`, `GET /metrics/query_range` (proxied, tenant-scoped).

---

## Failure modes

| Failure | Handling |
|---|---|
| VictoriaMetrics down | Ingest buffers at agent; queries degrade; alert raised |
| Cardinality explosion | Label curation + guardrails; drop offending labels with warning |
| Sample gaps (host offline) | `container_up`/staleness handles; anomaly ignores gaps |
| Clock skew | Timestamps normalized at ingest |

---

## Phase

- **`[MVP]`** CPU/mem/net/disk + lifecycle counters via Docker stats, labeled,
  stored in VictoriaMetrics, queryable; default 5s sampling; recording rules for
  ratios/rates.
- **`[FUTURE]`** Adaptive hot sampling, cAdvisor scrape integration, host/Node
  metrics depth, downsampling/rollups, app-level metrics (HTTP error/latency) for
  deploy validation.
