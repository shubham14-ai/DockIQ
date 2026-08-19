# Engine 10: LLM Observability Engine

> **The market gap DockIQ owns.** No Docker monitoring platform does AI/LLM
> observability well. DockIQ monitors token usage, prompt latency, LLM cost,
> embedding requests, RAG retrieval latency, and vector DB performance —
> first-class, alongside infrastructure.

This pairs naturally with the Classification Engine's detection of AI stacks
(LangGraph, Celery, Qdrant, ChromaDB, Milvus, Ollama, vLLM…).

---

## Purpose

- Give teams running LLM/RAG workloads the observability generic tools lack:
  **cost, latency, tokens, and vector-DB performance** in one place.
- Correlate LLM behavior with the underlying container metrics/logs/topology.
- Feed cost and latency anomalies into Alerts and Deployment validation.

---

## What it observes (from the brief)

| Signal | Meaning |
|---|---|
| **Token usage** | prompt/completion/total tokens per request, model, service |
| **Prompt latency** | time-to-first-token + total generation latency |
| **LLM cost** | $ per request/model/service/tenant (from token × price table) |
| **Embedding requests** | count, latency, tokens for embedding calls |
| **RAG retrieval latency** | vector search + rerank time in a RAG pipeline |
| **Vector DB performance** | Qdrant/Chroma/Milvus query latency, recall, index size |

---

## How it gets the data

LLM internals aren't visible from container stats alone, so DockIQ ingests via
multiple, increasingly deep sources:

1. **App instrumentation (OpenTelemetry-style):** an SDK/decorator the app uses to
   emit LLM spans/metrics (tokens, model, latency, cost) to DockIQ. Highest
   fidelity. `[primary]`
2. **Proxy/sidecar:** an optional LLM proxy (in front of OpenAI/Anthropic/local
   model endpoints) that measures tokens/latency/cost transparently — no app
   changes. `[FUTURE]`
3. **Vector DB metrics:** scrape Qdrant/Chroma/Milvus native metrics endpoints
   (query latency, collection size) via the Metrics Engine.
4. **Log parsing:** extract token/latency fields from structured app logs where
   instrumentation isn't present. `[fallback]`

All of it is tagged with the shared labels (`service`, `tenant`) plus LLM
dimensions (`model`, `provider`, `operation`).

---

## Internals

```
app SDK / proxy / vector-db metrics / logs
        │  LLM spans + metrics (tokens, latency, cost, model)
        ▼
┌──────────────────────────┐   price table (per model/provider)
│  Ingest + cost calculator  │──▶ cost = tokens × price
└───────────┬──────────────┘
            ▼  store as time-series (VictoriaMetrics) + traces (optional)
      dockiq_llm_* series ──▶ LLM dashboards, Alerts, Deployment validation
```

- **Cost model:** a maintained price table (per model/provider, input vs output
  tokens) turns token counts into dollars; per-service/tenant cost rollups.
- **Latency breakdown:** distinguishes queueing, TTFT, generation, and (for RAG)
  retrieval vs generation, so you see *where* latency lives.
- **Vector DB panels:** query latency, throughput, index/collection size, recall
  (if reported) for Qdrant/Chroma/Milvus.
- **Correlation:** ties LLM latency to the container's CPU/mem and to topology
  (e.g. slow RAG because Qdrant is CPU-bound).

---

## Metrics (examples)

```
dockiq_llm_tokens_total{service,model,provider,type=prompt|completion}
dockiq_llm_request_latency_seconds{service,model,operation=chat|embed}
dockiq_llm_cost_usd_total{service,model,provider,tenant}
dockiq_rag_retrieval_latency_seconds{service,vectordb}
dockiq_vectordb_query_latency_seconds{tech=qdrant|chroma|milvus,service}
dockiq_vectordb_collection_size{service,collection}
```

---

## What it powers

| Consumer | Use |
|---|---|
| **LLM dashboards** | cost/latency/token trends per model/service/tenant |
| **Alert Engine** | cost spike, latency regression, token runaway |
| **Anomaly Engine** | baseline LLM cost/latency; flag abnormal spend |
| **Deployment validation** | did the new prompt/model version blow up cost/latency? |
| **Topology** | RAG call-flow: API → retriever → vector DB → LLM |

---

## Data

`dockiq_llm_*` series in VictoriaMetrics; optional trace store for span detail
`[FUTURE]`; price table + per-tenant cost rollups in PostgreSQL.

---

## Interfaces

- Consumes: app SDK ingest endpoint, proxy metrics, vector-DB scrapes, log
  extraction.
- Serves: LLM dashboards, cost/latency queries.
- API: `POST /llm/ingest` (SDK/OTel), `GET /llm/cost`, `GET /llm/latency`,
  `GET /llm/vectordb`.

---

## Failure modes

| Failure | Handling |
|---|---|
| No instrumentation | Degrade to log parsing / vector-DB metrics only; prompt user to add SDK |
| Price table stale | Versioned price table; flag unknown models; estimate + warn |
| High-cardinality (per-prompt) | Aggregate by model/service; avoid per-request labels in TSDB |
| Provider API opacity | Proxy measurement fills gaps where app can't |

---

## Phase

- **`[FUTURE]`** (Phase 4+, a flagship differentiator). Begin with the app SDK
  ingest + cost table + vector-DB metric scrape + LLM dashboards; add proxy,
  traces, and deep RAG breakdowns later.
