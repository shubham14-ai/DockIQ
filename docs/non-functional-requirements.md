# Non-Functional Requirements (SLOs & Scale)

Targets that constrain every store/engine decision. Numbers are **v1 targets**
to validate during Phase 1, not hard guarantees.

---

## 1. Scale targets (v1)

| Dimension | Target (single control-plane node) |
|---|---|
| Hosts (agents) | up to **100** |
| Containers total | up to **5,000** |
| Metric series | ≤ **~500k** active series |
| Ingest rate | ≤ **~50k** samples/sec |
| Log throughput | ≤ **~10k** lines/sec |
| Concurrent UI users | ≤ **50** |

Beyond this → scale-out (Phase 7): HA backend, NATS cluster, VM cluster.

## 2. Latency SLOs

| Path | Target |
|---|---|
| Metric sample → queryable in VM | < 10 s |
| Event (container start) → visible in UI | < 5 s |
| Threshold alert fire (breach → notify) | < 30 s |
| Baseline/anomaly alert | < 60 s |
| API read (inventory) p95 | < 300 ms |
| Metric/log query p95 | < 2 s |
| Agent command (restart) issued → acked | < 5 s |

## 3. Cardinality budget (hard rule)

Series = `containers × metrics × label-combos`. To protect VictoriaMetrics:
- **Allowed labels only:** `tenant, host_id, container_id, container, image, service, role, tech`.
- **Forbidden as labels:** request IDs, prompts, user IDs, timestamps, paths, any
  unbounded value.
- **Per-container series cap:** ~100. LLM per-request detail → traces, **never** TSDB labels.
- Guardrail: ingest drops offending labels with a logged warning (see
  [Metrics Engine](engines/04-metrics-engine.md)).

## 4. Availability & durability

| Concern | Target |
|---|---|
| Control-plane uptime (v1, single node) | best-effort; HA in Phase 7 |
| No telemetry loss on brief outage | agent disk buffer + JetStream replay |
| PostgreSQL (source of truth) | backed up; RPO ≤ 24 h (v1) |
| Metrics/logs | time-bounded, regenerable-in-part; snapshot backups |

## 5. Agent footprint (guest on customer hosts)

| Resource | Target |
|---|---|
| Memory | < 50 MB idle, < 150 MB loaded |
| CPU | < 2% of one core (≈30 containers) |
| Disk buffer | ≤ 256 MB (bounded) |

## 6. Security & compliance (non-functional)

- All external traffic TLS; agents/NATS mTLS.
- Every mutating action audited (append-only).
- Tenant isolation enforced at DB/NATS/TSDB/API layers.
- Secret-like env values redacted at ingest.

## 7. Control-plane sizing (rule of thumb)

For the **v1 scale targets** above, a single node with roughly:
- **8 vCPU / 16 GB RAM / 200 GB SSD** for the full stack (backend + NATS +
  VictoriaMetrics + Loki + PostgreSQL + Grafana).
- VictoriaMetrics dominates disk; Loki dominates object/blob storage over time.

Confirm empirically in Phase 1 load testing. See [Roadmap](roadmap.md).
