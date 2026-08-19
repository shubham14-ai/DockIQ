# Engine 6: Alert Engine

> **Tell humans (and the healer) when something is wrong — intelligently.** The
> Alert Engine evaluates thresholds *and* learned baselines *and* anomalies,
> deduplicates noise, respects maintenance windows, and routes notifications.

It combines proven alerting (Alertmanager concepts, DockMon-style suppression/
maintenance) with DockIQ's **intelligent** twist: baseline-aware, not just
static thresholds.

---

## Purpose

- Evaluate rules over metrics, health, logs, and events.
- Move beyond static thresholds to **baseline/anomaly-aware** alerting.
- **Deduplicate** and group related alerts to fight fatigue.
- Respect **maintenance windows** and **suppression**.
- Route notifications and feed [Self-Healing](08-self-healing-engine.md).

---

## Threshold vs intelligent alerting (the differentiator)

```
Static (most tools):        Intelligent (DockIQ):
   CPU > 90%  → alert          CPU normally 20%, now 70% → abnormal → alert
                               (even though 70% < 90%)
```

The Alert Engine consumes baselines/forecasts from the
[AI Anomaly Engine](07-ai-anomaly-engine.md): an alert can fire on *deviation from
normal*, not only fixed limits. Both modes coexist — hard thresholds for safety
ceilings, baselines for early/subtle detection.

---

## Alert sources

| Source | Example |
|---|---|
| **Metrics** | CPU/mem/disk thresholds; baseline deviation; disk-full forecast |
| **Health** | healthcheck failing; crash loop; `container_up == 0` |
| **Events** | OOM kill; repeated restarts; image change |
| **Logs** | error burst; panic/stack trace; silent container |
| **Anomaly** | forecasted breach; seasonal anomaly |
| **Topology** | dependency down → blast-radius alert |
| **Deployment** | error/latency regression after release |

---

## Rule model

Rules are **auto-attached by class** (from Classification) and **user-definable**:

```yaml
rule: db-connections-high
applies_to: { role: db, tech: postgres }        # auto-targets all Postgres
condition:
  type: baseline                                 # or: threshold | forecast | lograte
  metric: dockiq_pg_connections
  sensitivity: medium
for: 5m
severity: warning
actions:
  notify: [ "#ops" ]
  heal: null                                     # optionally trigger self-healing
```

- **Zero-config defaults:** each role/tech ships default rules (a Postgres gets
  connection/replication/disk rules; a Redis gets memory/eviction rules) so a
  freshly discovered container is *already alertable*.
- **User rules:** override/extend via UI/API.

---

## Internals

```
metrics/health/logs/events/anomaly
        │
        ▼
┌────────────────┐   baselines/forecasts from Anomaly Engine
│  Evaluator      │◀──────────────────────────────────
│  (rule engine)  │
└───────┬────────┘
        ▼ candidate alert
┌────────────────┐
│  Dedup + group  │  correlate by container/service/cause; suppress dupes
└───────┬────────┘
        ▼
┌────────────────┐
│  Suppression    │  maintenance windows, silences, dependency-aware muting
└───────┬────────┘
        ▼
┌────────────────┐
│  Router         │  notify (Slack/email/webhook/PagerDuty) + emit to bus
└───────┬────────┘
        ├──▶ Self-Healing (if rule requests)
        └──▶ UI (live), incidents
```

- **Deduplication:** identical/related conditions collapse into one alert with a
  count; flapping is damped (`for:` duration + hysteresis).
- **Grouping & blast radius:** when a dependency fails, dependent-service alerts
  are grouped under the root cause using the [topology graph](03-topology-engine.md)
  ("PostgreSQL down" instead of 12 separate downstream alerts).
- **Maintenance windows / suppression:** DockMon-style — mute by tag/service/host
  for a window; silence specific alerts; auto-suppress dependents of a known-down
  service.
- **Routing:** per-severity, per-team channels; escalation `[FUTURE]`.

---

## Alert lifecycle

```
pending → firing → (acknowledged) → resolved
                └─▶ optional: trigger self-healing → auto-resolve if fixed
```

State persisted in `alerts`/`incidents`; every transition emitted on
`dockiq.<tenant>.alerts` for the UI and history.

---

## Data

`alert_rules` (definition, target selector, condition), `alerts` (instances,
state, timestamps), `incidents` (grouped), `maintenance_windows`, `silences`.
See [Data Model](../data-model.md).

---

## Interfaces

- Consumes: metrics (query), `*.health`, `*.events`, log signals, anomaly
  outputs, `topology.updated`.
- Emits: `dockiq.<tenant>.alerts`, self-healing triggers, notifications.
- API: CRUD `/alert-rules`, `GET /alerts`, `POST /alerts/{id}/ack`,
  `/maintenance-windows`, `/silences`.

---

## Failure modes

| Failure | Handling |
|---|---|
| Metric store unavailable | Pause metric rules, surface "alerting degraded", keep health/event rules |
| Alert storm | Dedup + grouping + rate limits; blast-radius collapse |
| Baseline not ready (new container) | Fall back to thresholds until baseline learned |
| Notification channel down | Retry + queue; mark delivery failure in UI |

---

## Phase

- **`[MVP]`** Threshold + health/event alerting, default rules per role/tech,
  dedup/grouping, maintenance windows/suppression, basic routing (email/webhook/
  Slack), UI + history.
- **`[FUTURE]`** Baseline/forecast conditions (Anomaly integration), blast-radius
  grouping via topology, log-based rules, escalation policies, self-healing
  triggers.
