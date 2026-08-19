# Engine 5: Logging Engine

> **See what containers are saying.** The Logging Engine streams, stores, and
> serves container logs — live tailing, multi-container views, and search —
> reusing Dozzle-style UX and Loki storage.

---

## Purpose

- Collect stdout/stderr from every container reliably.
- Store cheaply in Loki, indexed by the shared labels.
- Provide **live streaming**, **multi-container views**, **search/filter**, and
  **tail** to the UI — and log signals to the Alert and LLM engines.

---

## Capabilities (from the brief)

- **Live log streaming** — real-time tail in the UI.
- **Multi-container log view** — interleave logs from several containers (e.g. all
  replicas of a service, or a service + its dependencies).
- **Searchable logs** — filter by text, level, label, time.
- **Tail logs** — last N lines instantly.

---

## Inputs

| Input | Source |
|---|---|
| Container stdout/stderr | Agent LogShipper (Docker logs API) |
| Labels (role/tech/service) | Classification (applied as Loki labels) |
| Log-based alert rules | Alert Engine |

---

## Outputs

- Log streams in **Loki**, labeled per the shared convention.
- Query results (LogQL) to the UI log viewer.
- Extracted signals (error bursts, patterns) to Alert Engine; LLM-related lines
  to LLM Observability.

---

## Internals

```
container logs ──(tail, checkpoint)──▶ Agent LogShipper ──batch push──▶ Loki
                                                                 │
                                            backend LogQL query ◀┘
                                                    │
                                    ┌───────────────┼───────────────┐
                                    ▼               ▼               ▼
                                 UI viewer    Alert (log rules)  LLM engine
```

- **Reliable tailing:** the agent tracks each container's read position
  (checkpoint) so restarts neither drop nor duplicate lines.
- **Batching:** lines batched by size/time before push to Loki (efficiency).
- **Labels, not full-text index:** Loki indexes labels only; content is stored
  and grep-scanned at query time — cheap storage, fast label-scoped search.
- **Structured logs:** JSON logs are parsed at query time (LogQL `json`),
  enabling level/field filters without pre-indexing.
- **Backpressure/sampling:** on a log flood the agent batches harder and, as a
  last resort, samples with a logged warning — never OOM the host.

---

## UI: the log viewer

- **Tail mode** (follow), **history mode** (time range), **search** (substring/
  regex), **level filter** (error/warn/info), **label filter** (service/role/tech).
- **Multi-container:** pick a service → interleave all replicas; or pick a topology
  node → view it plus its dependencies' logs around the same time (correlation).
- **Correlation link:** from a metric spike or alert, jump to the exact logs at
  that timestamp for that container (shared labels make this one click).

---

## Log-based alerting (feeds Alert Engine)

- Rules like "≥ N occurrences of `ERROR`/`panic`/`OOM` in 5m for service X" or
  "log rate dropped to zero (silent container)" produce alert signals.
- Pattern extraction (e.g. crash-loop stack traces) can trigger Self-Healing.

---

## Data

Logs in Loki; labels per shared convention. No log content in PostgreSQL (only
derived events/alerts). Retention 7–30 days, tenant-configurable.

---

## Interfaces

- Consumes: `*.logs` notifications; direct agent→Loki push for content.
- Serves: LogQL via backend proxy → UI; signals → Alert/LLM.
- API: `GET /logs/query` (LogQL, tenant-scoped), `GET /containers/{id}/logs`
  (tail/range), WS stream for live tail.

---

## Failure modes

| Failure | Handling |
|---|---|
| Loki down | Agent buffers batches (bounded); backfills on recovery; alert raised |
| Log flood | Harder batching → sampling with warning; host protected |
| Container restart | Checkpointed positions prevent gaps/dupes |
| Huge single lines | Truncated with marker to protect pipeline |

---

## Phase

- **`[MVP]`** Live streaming, tail, single- and multi-container view, text/label
  search via Loki; correlation from container view.
- **`[FUTURE]`** Log-based alert rules, structured-log field filters, pattern
  extraction → Self-Healing, cross-service correlated timelines, object-store
  retention tiering.
