# Layer: Agent (Python)

The agent is the data-plane component that runs on every monitored Docker host.
It is the *only* component that touches the Docker socket. It observes and
executes; it never decides.

> **Design mantra:** thin, trusted, stateless, single-purpose.

---

## 1. Responsibilities

From the vision brief, the agent owns:

| Responsibility | What it does |
|---|---|
| **Docker Events** | Subscribe to the Docker event stream (create/start/stop/die/kill/oom/health_status) |
| **Docker Stats** | Sample per-container CPU, memory, network, block I/O |
| **Container Discovery** | Enumerate containers, images, networks, volumes; report inventory |
| **Health Monitoring** | Report Docker healthcheck status; run optional active probes (HTTP/TCP) |
| **Log Collection** | Stream container stdout/stderr; ship to Loki |
| **Topology Discovery** | Report network membership + observed connections (see §6) |
| **Heartbeat** | Periodic liveness + host facts (Docker version, OS, resources) |
| **Command Execution** | Execute control-plane commands (restart/stop/recreate/scale/run script) |

---

## 2. Why Python (recap)

One language across the whole platform (backend + engines + agent), the mature
official **Docker SDK for Python** (docker-py), and a simple concurrency model
that fits an I/O-bound agent: a **thread per stream** (events/stats/logs
fan-out across containers) plus one dedicated asyncio loop for the NATS
publisher. Distributed as a slim container image that mounts the Docker socket.
See [Tech Stack §2](../02-tech-stack.md).

---

## 3. Internal structure

```
                    ┌───────────────────────────────────────────┐
                    │                DockIQ Agent                │
                    │                                            │
  Docker socket ───▶│  ┌────────────┐   ┌────────────────────┐  │
  /var/run/docker   │  │ Docker SDK  │──▶│  Collectors         │  │
        .sock       │  │ client      │   │  - EventWatcher     │  │
                    │  └────────────┘   │  - StatsSampler     │  │
                    │                    │  - LogShipper       │  │
                    │                    │  - HealthProber     │  │
                    │                    │  - Inventory        │  │
                    │                    │  - TopologyProbe    │  │
                    │                    └─────────┬──────────┘  │
                    │  ┌────────────┐   ┌──────────▼──────────┐  │
                    │  │ Local buffer│◀─▶│  Dispatcher / Queue │  │
                    │  │ (bbolt/disk)│   └──────────┬──────────┘  │
                    │  └────────────┘              │             │
                    │  ┌───────────────────────────▼──────────┐  │
                    │  │  Transport                            │  │
                    │  │   - NATS publisher (telemetry)        │  │
                    │  │   - Control channel (gRPC/WSS)        │  │
                    │  │   - Loki push / VM remote-write       │  │
                    │  └───────────────────────────────────────┘  │
                    │  ┌───────────────────────────────────────┐  │
                    │  │  Command Executor (restart/stop/...)   │  │
                    │  └───────────────────────────────────────┘  │
                    └───────────────────────────────────────────┘
```

### Collectors
Each collector is an independent thread (or thread group) with its own lifecycle:
- **EventWatcher** — one long-lived subscription to `docker events`; normalizes
  and forwards.
- **StatsSampler** — per-container stats streams; configurable interval
  (default 5s, capable of per-second for hot containers).
- **LogShipper** — per-container log tailing with position tracking; batches to
  Loki.
- **HealthProber** — reads Docker healthcheck status; optionally performs active
  HTTP/TCP probes for containers without a native healthcheck.
- **Inventory** — periodic full reconciliation (containers/images/networks/
  volumes) to catch anything missed by the event stream.
- **TopologyProbe** — network membership + connection observation (§6).

---

## 4. State model

The agent is **effectively stateless**:
- No database. Its only durable state is a **bounded local buffer** (e.g. bbolt
  or a WAL file) used purely for reliability when the control plane is
  unreachable.
- On restart, it re-runs full discovery and reconciles — the control plane is
  the source of truth.
- Log tail positions are checkpointed so a restart doesn't re-ship or drop lines.

---

## 5. Transport

Two channels (see [Data Flow](../03-data-flow.md)):

1. **Telemetry (data plane)** → NATS subjects, and/or direct
   remote-write/push to VictoriaMetrics & Loki for bulk streams.
2. **Control (control plane)** → long-lived **gRPC or WSS** `[DECISION PENDING D-1]`
   connection for registration, heartbeat, config, and commands.

**Recommendation:** gRPC for the control channel (typed, bidirectional
streaming, efficient) + NATS for telemetry. WSS is the fallback if customer
network/proxy constraints make gRPC hard.

### Security of transport
- **mTLS** on all channels; the agent presents a client certificate issued at
  enrollment.
- Enrollment via a **one-time join token** minted by the control plane
  (short-lived), exchanged for a long-lived client cert.
- All subjects/commands are **tenant-scoped**.

---

## 6. Topology discovery (how the agent sees connections)

The agent contributes raw signals; the [Topology Engine](../engines/03-topology-engine.md)
assembles the graph. Signal sources, cheapest-first:

1. **Docker network membership** — which containers share user-defined networks
   (a strong static hint of who *can* talk to whom).
2. **Published/exposed ports & links** — declared relationships.
3. **Observed connections** — established TCP connections per container, sampled
   from `/proc/<pid>/net/tcp` (+ `tcp6`) mapped to container PIDs, or via conntrack
   where available. This yields *actual* runtime edges (container A → container B:port).
4. **DNS/service names** — resolving Compose service names to containers.

The agent reports edges as `(src_container, dst_ip:port, proto, count)`; the
engine resolves destinations to containers/services and aggregates. Deep-packet
inspection is **not** used; this is connection-level, low-overhead.

> eBPF-based connection tracking is a `[FUTURE]` enhancement for richer, lower-
> overhead observation.

---

## 7. Command execution

The executor handles control-plane commands. Supported actions:

| Command | Docker action |
|---|---|
| `restart` | restart container |
| `stop` / `start` | stop / start container |
| `recreate` | pull new image + recreate with same config (deploy/rollback) |
| `scale` | adjust replica count (Compose/Swarm-aware) `[FUTURE for Swarm]` |
| `run_script` | execute a bounded recovery script/exec in a container |
| `pull_image` | pre-pull an image (deploy prep) |
| `clear_cache` | app-specific recovery hook (e.g. exec redis FLUSHDB) `[policy-gated]` |

**Safety:**
- Every command carries a **command ID**; the agent **dedupes** (idempotency) so
  replays don't double-execute.
- The agent verifies the command's **signature/authorization** from the control
  plane before acting.
- Results (success/failure, logs) flow back up so engines can confirm the action
  worked.
- `run_script`/`clear_cache` run under time and resource limits.

---

## 8. Configuration

Agent config (env/file), minimal by design:
```yaml
control_plane_url: https://dockiq.example.com
join_token: <one-time>            # first boot only; replaced by mTLS cert
tenant_id: default
host_id: <auto-derived, stable>   # machine-id based
sampling:
  stats_interval: 5s
  hot_stats_interval: 1s          # for flagged containers
  log_batch: 1s / 1MB
probes:
  active_health: true
buffer:
  max_disk: 256MB
```

---

## 9. Packaging & distribution

- **Slim container image** (`python:3.12-slim` + the agent package), multi-arch
  (amd64/arm64).
- Shipped as:
  - a container image that mounts the Docker socket (the standard path), **or**
  - the Python package + a virtualenv and a systemd unit for hosts that prefer no
    container.
- Requires read access to `/var/run/docker.sock`. Running as a container needs
  the socket mounted; document the security implications (see [Security](../security.md)).

Example (Compose) for adding a host to DockIQ:
```yaml
services:
  dockiq-agent:
    image: dockiq/agent:latest
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - CONTROL_PLANE_URL=https://dockiq.example.com
      - JOIN_TOKEN=${DOCKIQ_JOIN_TOKEN}
```

> Note: `:ro` on the socket limits some actions; command execution
> (restart/recreate) needs write access. The agent documents which mount mode is
> required for which feature tier (read-only monitoring vs full operations).

---

## 10. Failure modes & handling

| Failure | Handling |
|---|---|
| Control plane unreachable | Buffer telemetry to disk (bounded), keep collecting, replay on reconnect |
| Docker socket unavailable | Report degraded via heartbeat; retry with backoff |
| Container churn storm | Rate-limit event processing; inventory reconcile catches missed items |
| Log volume spike | Batch + drop-to-sample with a logged warning; never OOM the host |
| Duplicate command (replay) | Idempotent via command ID dedupe |
| Agent crash | systemd/Docker `restart: unless-stopped`; full re-discovery on boot |
| Clock skew | Timestamps normalized at ingest; agent includes monotonic + wall time |

---

## 11. Resource budget (targets)

The agent must be a good guest on customer hosts:
- **Memory:** target < 80 MB idle, < 200 MB under load (Python interpreter + SDK).
- **CPU:** target < 3% of one core at steady state for a typical host (~30 containers).
- **Disk:** buffer capped (default 256 MB).
- **Network:** batched/compressed telemetry.

These are targets to validate during Phase 1 build.

---

## 12. Phase

- **`[MVP]`** Events, stats, inventory/discovery, health (Docker healthchecks),
  log shipping, heartbeat, basic command execution (restart/stop/start),
  telemetry over NATS + Loki/VM.
- **`[FUTURE]`** Active probes, connection-level topology, recreate/scale for
  deploy/rollback, `run_script`/`clear_cache`, eBPF connection tracking, Swarm/K8s
  awareness.
