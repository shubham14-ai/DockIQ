# Engine 3: Topology Engine

> **Understand the system, not just the containers.** Most tools monitor
> containers individually. The Topology Engine builds the *service dependency and
> communication graph* — who depends on whom, and who is actually talking to whom
> at runtime.

A core **differentiator**: existing tools don't truly understand
`Frontend → FastAPI → Redis → PostgreSQL`.

---

## Purpose

Build and maintain a live graph of the infrastructure:
- **Service dependency graph** — logical "A depends on B".
- **Runtime communication map** — observed "A is connecting to B:port right now".
- **Call flow visualization** — the path a request takes across services.
- Provide this graph to the UI, Dashboards, Alerts (blast radius), and Deployment
  (dependency validation).

---

## Inputs

| Input | Source | Gives |
|---|---|---|
| Docker network membership | Agent inventory | who *can* talk (same network) |
| Published ports / links / depends_on | Agent, Compose labels | declared dependencies |
| Observed TCP connections | Agent TopologyProbe (`/proc/net`, conntrack) | actual runtime edges |
| DNS / service-name resolution | Agent, Compose | map names → containers |
| Env var references | Classification (`REDIS_URL`, `DATABASE_URL`) | intended dependencies |
| Classification (role/tech) | Classification Engine | node typing + edge sense |

---

## Outputs

- `topology_edges` (Postgres): `(src_service, dst_service, kind, proto, port, weight, first_seen, last_seen, confidence)`.
- Node set (from containers + classification).
- Live graph updates → UI; blast-radius queries → Alerts; dependency health →
  Deployment.

---

## Internals

```
signals (network, ports, env refs, observed conns, DNS)
        │
        ▼
┌──────────────────────────┐
│  Edge builder             │  merge multi-source evidence per (src,dst)
│   - static edges (decl.)  │
│   - dynamic edges (obs.)  │
└───────────┬──────────────┘
            ▼
┌──────────────────────────┐
│  Aggregator/decay          │  weight by frequency; decay stale edges
└───────────┬──────────────┘
            ▼
      graph store (Postgres) ──▶ UI / Alerts / Deployment
```

- **Static edges** come from declarations (Compose `depends_on`, env
  `DATABASE_URL=postgres`, shared networks, links). High trust, low freshness.
- **Dynamic edges** come from observed connections (TCP flows mapped to
  containers). High freshness, requires aggregation to filter noise.
- **Fusion:** the same A→B relationship confirmed by multiple sources gets high
  confidence; observation without declaration is still surfaced (shadow
  dependency), declaration without observation flagged (maybe dead).
- **Service vs container:** edges are aggregated to the **service** level (all
  replicas of `api` → `postgres`) for a readable graph, with drill-down to
  container edges.
- **Decay:** edges not re-observed within a window fade (lower weight) and
  eventually drop — the graph reflects *now*, not history.

---

## Communication observation (how, safely)

- The agent samples established connections per container (from `/proc/<pid>/net/tcp`
  or conntrack), reporting `(src_container, dst_ip:port, proto, count)`.
- The engine resolves `dst_ip:port` to a container/service (via the network/IP
  inventory) and creates/strengthens an edge.
- **Connection-level only** — no packet payloads, no DPI. Low overhead.
- `[FUTURE]` eBPF for richer, cheaper flow capture; L7 awareness (HTTP paths) for
  true call-flow visualization.

---

## What the graph powers

| Consumer | Use |
|---|---|
| **UI** | Interactive topology view (nodes by role/tech, edges by traffic/health) |
| **Alert Engine** | Blast radius: "PostgreSQL down → these 4 services affected" |
| **Deployment** | Dependency validation before release (is Redis healthy?) |
| **Self-Healing** | Order of recovery; avoid restarting a dependency mid-request |
| **Dashboards** | Group related services; show a service + its deps together |

---

## Data

`topology_edges` as above; nodes are `containers` joined with `classifications`.
Edge `kind ∈ {declared, observed, inferred}`; `confidence` from fused evidence.

---

## Interfaces

- Consumes: `*.topology`, inventory, `classification.updated`.
- Emits: `topology.updated` → UI, Alerts, Deployment.
- API: `GET /topology?tenant=&host=&service=` (graph), `GET /services/{id}/dependencies`,
  `GET /services/{id}/dependents` (blast radius).

---

## Failure modes

| Failure | Handling |
|---|---|
| Noisy short-lived connections | Aggregation + weight threshold filters transient edges |
| NAT/overlay obscures dst IP | Fall back to declared edges + network membership |
| Missing observation (probe off) | Graph from static sources; mark dynamic edges absent |
| Stale edges after topology change | Decay window drops dead edges |

---

## Phase

- **`[MVP-lite]`** Static graph from networks + Compose `depends_on` + env refs
  (cheap, high value, no probing).
- **`[FUTURE]`** Observed-connection dynamic edges, edge decay/fusion, service
  aggregation UI, eBPF/L7 call-flow, time-scrub replay.
