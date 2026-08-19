# Engine 11: Diagnostic Query Agent

> **The natural-language front door to DockIQ.** A user types a plain-English
> prompt — *"check the response latency for the last 5 messages"* or *"why did
> latency suddenly increase?"* — and the agent translates it into safe,
> read-only queries against DockIQ's stores, fetches the data, and returns a
> report or a root-cause diagnosis. It's the **text-to-SQL pattern**, but over
> VictoriaMetrics (PromQL), Loki (LogQL), and PostgreSQL (SQL).

This is a *consumer* of the other engines, not a new data source. It reuses the
Metrics, Logging, LLM Observability, Anomaly, Topology, and Alert engines as
tools and turns their output into an answer a human asked for in one sentence.

---

## Purpose

- Let any operator ask DockIQ a question in natural language and get **data +
  an explanation** back, without writing PromQL/LogQL or knowing the schema.
- Two modes from one prompt:
  - **Report mode** — *"show me X"* → fetch, aggregate, and summarize.
  - **Diagnose mode** — *"why did X happen?"* → correlate signals across engines
    and return a ranked root-cause hypothesis with evidence.
- Ground every answer in real query results (no hallucinated numbers) and always
  show the underlying query + data so the answer is auditable.

---

## What it accepts (prompt → intent)

| Example prompt | Intent | Resolves to |
|---|---|---|
| "check the response latency for the last 5 messages" | report / metric lookup | `dockiq_llm_request_latency_seconds`, last 5 requests, service-scoped |
| "why did latency suddenly increase?" | diagnose / root-cause | latency series + change-point + correlated CPU/mem/deploys/logs |
| "show error logs for the checkout service in the last hour" | report / log search | LogQL over Loki, `service="checkout"`, `level=error` |
| "what's my LLM cost today vs yesterday?" | report / comparison | `dockiq_llm_cost_usd_total` windowed + delta |
| "which containers are unhealthy right now?" | report / state | PostgreSQL container/health tables |
| "is anything anomalous on host web-01?" | diagnose | Anomaly Engine baselines for that host's series |

The agent extracts **entity** (service/container/host/model), **signal**
(latency/cost/errors/cpu…), **time window** ("last 5 messages", "last hour",
"today vs yesterday"), and **mode** (report vs diagnose) from the prompt.

---

## How it works

The agent is an **LLM planner with tool-calling**, not a free-text SQL generator.
The LLM never talks to a database directly — it chooses from a fixed set of
**typed, sandboxed query tools**, and the tools enforce scope, safety, and
tenancy. This is what keeps a text-to-query agent trustworthy.

```
user prompt
    │
    ▼
┌──────────────────────────────┐
│  Planner (LLM, tool-calling)  │  system prompt = schema + label conventions
│  parse intent, entity, window │  + available tools + tenant/RBAC scope
└───────────────┬──────────────┘
                │ picks tool(s), fills typed args
                ▼
┌──────────────────────────────────────────────────────────┐
│  Query tools (read-only, scoped, validated)               │
│   • metrics_query(promql, range)   → VictoriaMetrics      │
│   • logs_query(logql, range)       → Loki                 │
│   • sql_query(named_query, params) → PostgreSQL (allow-list)│
│   • anomaly_check(series, window)  → Anomaly Engine       │
│   • topology_neighbors(entity)     → Topology Engine      │
│   • recent_deploys(entity, window) → Deployment records   │
└───────────────┬──────────────────────────────────────────┘
                │ raw results (numbers, rows, log lines)
                ▼
┌──────────────────────────────┐
│  Synthesizer (LLM)            │  grounds answer in results only;
│  report OR ranked diagnosis   │  cites the query + values used
└───────────────┬──────────────┘
                ▼
   answer + evidence + the exact queries run
```

### Report mode
Plan → run one or a few query tools → summarize the returned data (with the raw
numbers and a small table/sparkline). Example: *"last 5 messages"* → fetch the
5 most recent `dockiq_llm_request_latency_seconds` samples for the caller's
service → return them plus min/max/avg.

### Diagnose mode ("why did latency increase?")
A structured playbook the planner runs as tool calls, not a guess:

1. **Confirm & locate** — pull the metric, detect the change-point (when did it
   jump, by how much).
2. **Correlate in time** — check what else moved in the same window: CPU/mem of
   the container, upstream/downstream neighbors (Topology), a recent deploy
   (Deployment records), error-rate in logs (Loki), anomaly flags (Anomaly).
3. **Rank hypotheses** — score candidate causes (e.g. *"deploy at 14:02 raised
   p95 by 3×"*, *"Qdrant CPU-bound → RAG retrieval slow"*) by correlation
   strength + timing.
4. **Answer** — top hypothesis, supporting evidence, and the exact queries, so
   the operator can verify or drill in.

---

## Safety model (why it can't go wrong)

| Guardrail | How |
|---|---|
| **Read-only** | Tools only issue reads (PromQL/LogQL are read-only; SQL is a named allow-list of parameterized SELECTs — no free-form SQL). |
| **Tenant/RBAC scoped** | The caller's tenant + role are injected into every tool call; queries can't reach another tenant's data. |
| **Grounded answers** | The synthesizer may only state numbers that appear in tool results; the prompt forbids inventing values. |
| **Bounded** | Time ranges, series count, and result rows are capped to protect the TSDB from a runaway query. |
| **Auditable** | Every answer ships with the queries it ran and the values used; prompts + tool calls are logged. |
| **Prompt-injection aware** | Log/label content pulled into context is treated as data, never as instructions to the planner. |

---

## What it powers

| Consumer | Use |
|---|---|
| **UI — Ask bar** | A chat/command box on Overview, Container, and Host pages |
| **Alert enrichment** | Auto-run diagnose mode on a firing alert → attach a first-pass root cause |
| **Incident summaries** | "Explain this incident" → narrative from correlated signals |
| **Onboarding** | New users query the system in English instead of learning PromQL |

---

## Data

Stateless over the stores it queries. It **owns**:
- **Conversation/session history** (prompt, resolved intent, tool calls, answer)
  in PostgreSQL — for audit, follow-up questions, and feedback.
- **Named-query catalog** (the SQL allow-list) and the tool schema.

It reads VictoriaMetrics, Loki, PostgreSQL, and the other engines; it writes
nothing to the observability stores.

---

## Interfaces

- **Consumes:** Metrics, Logging, LLM Observability, Anomaly, Topology,
  Deployment records; the shared label convention (`service`, `tenant`, `host`).
- **Serves:** the UI Ask bar and Alert enrichment.
- **API:**
  - `POST /agent/ask` `{ prompt, scope? }` → `{ answer, mode, evidence[], queries[] }`
  - `POST /agent/ask/stream` — streaming tokens + tool-call trace (WebSocket/SSE)
  - `GET  /agent/sessions/{id}` — replay a past conversation
- **LLM provider:** Claude (Anthropic) via the backend's Python ML stack — same
  provider used by the LLM Observability and Anomaly work. Model + prompts are
  config; the agent degrades to a template-based query builder if the LLM is
  unavailable (see Failure modes).

---

## Failure modes

| Failure | Handling |
|---|---|
| Ambiguous prompt ("latency?" — which service?) | Ask one clarifying question, or default to the page's current scope and say so |
| LLM unavailable / rate-limited | Fall back to a deterministic intent parser + templated queries for common asks; report reduced capability |
| Query returns no data | Say "no data in range" explicitly; suggest a wider window — never fabricate |
| Runaway/expensive query | Caps on range/series/rows; reject + explain instead of hammering the TSDB |
| Wrong entity resolved | Show the resolved entity + query so the user can correct; one-tap re-scope |
| Prompt injection via logs/labels | Context from stores is quoted as data; planner instructions are fixed and separate |

---

## Phase

- **`[FUTURE]`** (Phase 5, pairs with Anomaly maturity and builds on LLM
  Observability from Phase 4). Ship in stages:
  1. **Report mode** over Metrics + Logs (NL → PromQL/LogQL, grounded summaries).
  2. **Named-query SQL tool** for container/health/alert state.
  3. **Diagnose mode** — the correlation playbook across Anomaly + Topology +
     Deployment records.
  4. **Alert enrichment + streaming UI** and session/follow-up memory.

A *lite* version can appear earlier as a NL→PromQL helper in the UI once Metrics
and Logging are solid; the root-cause intelligence deepens as Anomaly and
Topology mature.
