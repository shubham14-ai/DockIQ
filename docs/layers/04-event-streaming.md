# Layer: Event Streaming (NATS / JetStream)

NATS is the nervous system of DockIQ. It decouples agents (producers) from
engines (consumers) and gives the platform durable, replayable event streams.

```
Agent → Event Bus → Processors → Alert Engine
```

---

## 1. Why NATS/JetStream (recap)

Lightweight single binary, simple ops (no ZooKeeper/KRaft), **JetStream** for
durable + replayable streams, subject wildcards that map naturally to our
tenant/host routing, and easy self-hosting for an on-prem product. Kafka is the
documented future option for extreme volume. See [Tech Stack §7](../02-tech-stack.md).

---

## 2. Subject taxonomy

Structured, hierarchical subjects enable precise subscriptions:

```
dockiq.<tenant>.<host_id>.events        # container lifecycle, OOM, health transitions
dockiq.<tenant>.<host_id>.metrics       # sampled stats notifications
dockiq.<tenant>.<host_id>.logs          # log notifications / pointers
dockiq.<tenant>.<host_id>.health        # healthcheck/probe results
dockiq.<tenant>.<host_id>.topology      # observed connections / network membership
dockiq.<tenant>.<host_id>.heartbeat     # liveness + host facts

dockiq.<tenant>.commands.<host_id>      # control-plane → agent commands (req/rep)
dockiq.<tenant>.command_results.<host_id>

dockiq.<tenant>.alerts                  # alert lifecycle (fired/resolved/ack)
dockiq.<tenant>.deployments             # deploy progress events
dockiq.<tenant>.incidents               # incident lifecycle
```

Wildcards let a consumer subscribe broadly or narrowly:
- `dockiq.default.*.events` — all event streams for the default tenant.
- `dockiq.*.*.heartbeat` — all heartbeats (platform health).
- `dockiq.acme.host-7.>` — everything from one host.

---

## 3. Streams & consumers (JetStream)

### Streams
Durable streams persist messages so a down consumer misses nothing:

| Stream | Subjects captured | Retention | Purpose |
|---|---|---|---|
| `EVENTS` | `dockiq.*.*.events` | limits (time/size) | lifecycle + control signals |
| `HEALTH` | `dockiq.*.*.health` | short | health transitions |
| `TOPOLOGY` | `dockiq.*.*.topology` | short | connection observations |
| `COMMANDS` | `dockiq.*.commands.*` | work-queue | command delivery |
| `ALERTS` | `dockiq.*.alerts` | longer | alert lifecycle |
| `DEPLOY` | `dockiq.*.deployments` | longer | deploy progress/audit |

> High-volume **metrics** and **logs** primarily bypass JetStream persistence:
> the agent remote-writes metrics to VictoriaMetrics and pushes logs to Loki
> directly; only lightweight *notifications* travel on NATS. This keeps the bus
> responsive and avoids duplicating bulk storage. See [Data Flow §2](../03-data-flow.md).

### Consumers
- **Durable, named** consumers per engine group (Discovery, Classification,
  Topology, Alert, Anomaly, Healing…).
- **At-least-once** delivery; engines are **idempotent** (dedupe by event ID).
- **Ack + redelivery** with backoff; a max-deliver limit routes poison messages
  to a **DLQ** subject.

---

## 4. Delivery semantics

| Property | Choice | Why |
|---|---|---|
| Guarantee | at-least-once | simplest durable; engines dedupe |
| Ordering | per-subject (per host) | lifecycle order within a host preserved |
| Idempotency | required in consumers | tolerate replays after reconnect |
| Backpressure | JetStream flow control + consumer pull | protect slow engines |
| Dead-letter | max-deliver → DLQ subject | isolate poison messages |

---

## 5. Command channel (request/reply)

Commands use JetStream work-queue semantics (or NATS core req/rep for
low-latency):
1. Backend publishes to `dockiq.<tenant>.commands.<host_id>` with a **command ID**.
2. The target agent consumes, executes, and replies on
   `dockiq.<tenant>.command_results.<host_id>`.
3. Backend correlates by command ID; timeouts trigger retry (idempotent) or
   surface a failure.

This is the down-flow half of [Data Flow §4](../03-data-flow.md).

---

## 6. Security

- **mTLS** between agents/backend and NATS.
- **Per-tenant credentials** — NATS accounts/permissions restrict each agent to
  its own tenant + host subjects; an agent can neither read another tenant's
  streams nor publish outside its host prefix.
- **Backend** holds broader publish/subscribe rights, still tenant-aware in
  application logic.

NATS **accounts** provide hard multi-tenant isolation at the bus level — a strong
reason it fits DockIQ's tenancy model.

---

## 7. Broker abstraction (swap-ability)

The event layer sits behind an interface so the broker can change without
touching engines:

```python
class EventBus(Protocol):
    async def publish(self, subject: str, event: Event) -> None: ...
    async def subscribe(self, subject: str, durable: str,
                        handler: Callable[[Event], Awaitable[None]]) -> Subscription: ...
    async def request(self, subject: str, event: Event, timeout: float) -> Event: ...
```

A `NatsEventBus` implements it now; a `KafkaEventBus` could implement it later
if volume demands. Engines only see `EventBus`. This is the concrete
"document both, swap later" hedge from the tech-stack decision.

---

## 8. Reliability model

- **Producer down (agent):** on reconnect, the agent replays its bounded local
  buffer; JetStream accepts and consumers catch up.
- **Consumer down (engine):** durable consumer resumes from last ack; no loss.
- **Broker down:** agents buffer locally; backend pauses dispatch/live updates;
  everything resumes on reconnect.
- **Broker cluster:** `[FUTURE]` NATS cluster/supercluster for HA.

---

## 9. Observability of the bus

- Stream/consumer lag, redelivery counts, DLQ depth exported as metrics into
  VictoriaMetrics (DockIQ dogfoods itself).
- Alert on consumer lag / DLQ growth (a stuck engine is an incident).

---

## 10. Phase

- **`[MVP]`** Single NATS+JetStream node; core streams (EVENTS, HEALTH, COMMANDS,
  ALERTS); durable consumers for Discovery/Classification/Metrics-notify/Alert;
  mTLS + per-tenant creds; broker abstraction in place.
- **`[FUTURE]`** NATS clustering/HA, TOPOLOGY/DEPLOY/INCIDENTS streams at scale,
  Kafka adapter if needed.
