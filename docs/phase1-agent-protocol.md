# Phase 1 Agent ↔ Backend Protocol (MVP)

The single source of truth for the message contracts between the Python agent and the
Python engines. **All Phase 1 components MUST conform to this exactly.**

> **MVP simplification:** all telemetry travels as JSON over NATS. Each backend
> engine is the sole writer to its store (Metrics→VictoriaMetrics, Logging→Loki,
> Discovery/Classification/Alert→PostgreSQL). Direct agent→VM/Loki remote-write is
> a later optimization.

## Subjects

```
dockiq.<tenant_id>.<host_id>.heartbeat    # already implemented (Phase 0)
dockiq.<tenant_id>.<host_id>.discovery    # container inventory snapshots
dockiq.<tenant_id>.<host_id>.events       # container lifecycle events
dockiq.<tenant_id>.<host_id>.metrics      # resource stats samples
dockiq.<tenant_id>.<host_id>.logs         # container log lines
dockiq.<tenant_id>.<host_id>.health       # health status changes
```

`tenant_id` and `host_id` come from the enrollment response. Helper:
`app/bus/subjects.py` (Python). The agent builds subjects by string.

## Payloads (JSON, UTF-8)

### discovery  → consumed by Discovery + Classification
Full or partial inventory. Sent on connect and periodically (reconcile).
```json
{
  "tenant_id": "default",
  "host_id": "abc123",
  "containers": [
    {
      "id": "c9f...",
      "name": "orders-api",
      "image": "myrepo/orders:2.4.1",
      "image_digest": "sha256:...",
      "state": "running",
      "status": "Up 3 minutes (healthy)",
      "command": "uvicorn app:app",
      "labels": {"com.docker.compose.service": "api"},
      "env": {"REDIS_URL": "redis://redis:6379", "POSTGRES_PASSWORD": "***REDACTED***"},
      "ports": {"8000/tcp": 8000},
      "mounts": [{"source": "/data", "destination": "/data"}],
      "networks": ["appnet"],
      "compose_project": "shop",
      "compose_service": "api",
      "health": "healthy"
    }
  ]
}
```
**Env redaction:** the agent MUST replace values of keys matching
`*PASSWORD*`, `*SECRET*`, `*TOKEN*`, `*KEY*`, `*_DSN`, or creds-bearing URLs with
`***REDACTED***` before sending.

### events  → consumed by Discovery (timeline) + Alert
```json
{
  "tenant_id": "default", "host_id": "abc123",
  "container_id": "c9f...", "name": "orders-api",
  "type": "start",            // create|start|stop|die|kill|oom|health_status
  "exit_code": 0,             // for die
  "time": "2026-08-18T14:03:01Z",
  "attributes": {"image": "myrepo/orders:2.4.1"}
}
```

### metrics  → consumed by Metrics (→ VictoriaMetrics)
Sampled every ~5s.
```json
{
  "tenant_id": "default", "host_id": "abc123",
  "ts": "2026-08-18T14:03:05Z",
  "samples": [
    {
      "container_id": "c9f...", "name": "orders-api",
      "cpu_ratio": 0.23,          // 0..N (fraction of one core)
      "mem_bytes": 268435456,
      "mem_limit_bytes": 536870912,
      "net_rx_bytes": 10485760,
      "net_tx_bytes": 5242880,
      "blk_read_bytes": 0,
      "blk_write_bytes": 1048576
    }
  ]
}
```
Metrics engine emits series named `dockiq_cpu_usage_ratio`,
`dockiq_mem_usage_bytes`, `dockiq_mem_limit_bytes`, `dockiq_mem_usage_ratio`,
`dockiq_net_rx_bytes`, `dockiq_net_tx_bytes`, `dockiq_blk_read_bytes`,
`dockiq_blk_write_bytes`, `dockiq_container_up` with labels
`tenant, host_id, container_id, container` (+ `role`,`tech` when available).

### logs  → consumed by Logging (→ Loki)
```json
{
  "tenant_id": "default", "host_id": "abc123",
  "container_id": "c9f...", "name": "orders-api",
  "lines": [
    {"ts": "2026-08-18T14:03:05.123Z", "stream": "stdout", "message": "GET /health 200"}
  ]
}
```
Loki labels: `tenant, host_id, container_id, container, stream`.

### health  → consumed by Alert
```json
{
  "tenant_id": "default", "host_id": "abc123",
  "container_id": "c9f...", "name": "orders-api",
  "status": "unhealthy",     // healthy|unhealthy|none
  "at": "2026-08-18T14:03:05Z"
}
```

## Store endpoints (backend-side)
- VictoriaMetrics import (text exposition): `POST {VM}/api/v1/import/prometheus`
  body = lines `metric{labels} value timestamp_ms`.
- VictoriaMetrics query: `GET {VM}/api/v1/query`, `/api/v1/query_range`.
- Loki push: `POST {LOKI}/loki/api/v1/push` (JSON streams).
- Loki query: `GET {LOKI}/loki/api/v1/query_range`.

Config (already in `app/core/config.py` / env): `NATS_URL`, `DATABASE_URL`. Add
`VM_URL` (default `http://victoriametrics:8428`) and `LOKI_URL`
(default `http://loki:3100`) — the Metrics/Logging engines read these from env.
