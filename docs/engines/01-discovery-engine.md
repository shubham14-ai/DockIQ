# Engine 1: Discovery Engine

> **Find everything.** The Discovery Engine builds and continuously maintains the
> authoritative inventory of every host, container, image, network, and volume.
> It is the entry point of the intelligence chain — nothing downstream exists
> until Discovery has registered it.

---

## Purpose

Answer, at all times and with zero configuration: *what is running, where?*

- Enumerate all containers, images, networks, volumes across all hosts.
- Keep the inventory current in near-real-time via events + periodic reconcile.
- Capture the raw facts (labels, ports, env, mounts, image) that
  [Classification](02-classification-engine.md) and [Topology](03-topology-engine.md)
  reason over.

---

## Inputs

| Input | Source |
|---|---|
| Container lifecycle events (create/start/stop/die/destroy) | Agent → `*.events` |
| Full inventory snapshots (reconcile) | Agent Inventory collector |
| Host facts + heartbeat | Agent → `*.heartbeat` |
| Image/network/volume metadata | Agent (Docker SDK) |

---

## Outputs

| Output | Consumer |
|---|---|
| `hosts`, `containers`, `images`, `networks`, `volumes` records | PostgreSQL / all engines |
| "container discovered" internal event | Classification, Topology, Metrics, Dashboards |
| "container removed" event | Topology, Alert (cleanup), Dashboards |
| Inventory deltas | UI (live) |

---

## Internals

```
events ─┐
        ├─▶ [Reconciler] ──▶ upsert inventory ──▶ emit deltas ──▶ Classification…
snapshot ┘        ▲
                  └── periodic full sync catches missed events
```

- **Event-driven fast path:** each lifecycle event updates one record immediately.
- **Reconcile slow path:** periodic full snapshot from the agent diffs against
  stored inventory to self-heal any missed/duplicated events (Docker event
  streams can drop under load).
- **Stable identity:** containers keyed by Docker ID; hosts by a stable
  machine-derived `host_id` so restarts don't create duplicates.
- **Redaction:** env vars are captured but **secret-like keys are redacted/hashed**
  before storage (see [Security](../security.md)); Classification still gets
  enough signal (key *names*, safe values).

---

## Data captured per container

```
id, host_id, name, image (ref + digest), created_at, state, status,
command, labels{}, env{ (redacted) }, exposed_ports[], published_ports[],
mounts[], networks[], restart_policy, health (native), compose_project,
compose_service, first_seen, last_seen
```

Stored in `containers` (see [Data Model](../data-model.md)); large/optional blobs
in JSONB.

---

## Interfaces

- Consumes: `dockiq.<tenant>.<host>.events`, `.heartbeat`, inventory snapshots.
- Emits (internal, via bus): `discovery.container.added|updated|removed`,
  `discovery.host.online|offline`.
- API: `GET /hosts`, `GET /hosts/{id}/containers`, `GET /containers/{id}`.

---

## Failure modes

| Failure | Handling |
|---|---|
| Dropped Docker events | Periodic reconcile repairs inventory |
| Host offline | Heartbeat gap → mark host offline; containers marked stale, not deleted |
| Duplicate identity after restart | Stable host_id + container ID keying |
| Event/snapshot race | Reconcile is authoritative; last-write by observed timestamp |

---

## Phase

**`[MVP]`** — Discovery is foundational and ships first: full inventory of
containers/images/networks/volumes, event fast-path + reconcile, host lifecycle.
