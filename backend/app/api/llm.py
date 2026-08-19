"""LLM Observability API (Phase 4 Engine 10).

Ingests LLM/RAG usage events (from an app SDK/OTel-style instrumentation),
turns them into Prometheus exposition lines, and writes them to
VictoriaMetrics via ``app.store.vm.vm``. Also exposes simple cost/latency
rollup queries.

Router is included by ``main.py`` (wiring left to the caller — see the
engine's build report). See docs/engines/10-llm-observability-engine.md for
the metric names and design.

MVP note: VictoriaMetrics import treats `_total` series as plain samples
(current value at ingest time) rather than proper monotonic counters — this
keeps the demo simple while preserving the metric names from the design doc.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.engines.llm.pricing import PRICE_TABLE, estimate_cost_usd

log = logging.getLogger("dockiq.api.llm")

router = APIRouter(prefix="/llm", tags=["llm"])


# ----------------------------------------------------------------------
# schemas
# ----------------------------------------------------------------------


class IngestIn(BaseModel):
    service: str
    model: str
    provider: str | None = None
    operation: str = Field(default="chat", description="chat|embed")
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: float | None = None
    cost_usd: float | None = None
    tenant_id: str | None = None
    vectordb: str | None = None
    retrieval_ms: float | None = None


class IngestOut(BaseModel):
    ok: bool
    lines_written: int
    cost_usd: float | None = None


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _escape_label_value(value: str) -> str:
    """Escape a label value for Prometheus exposition format."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def _labels(pairs: dict[str, str | None]) -> str:
    parts = []
    for key, value in pairs.items():
        if value is None or value == "":
            continue
        parts.append(f'{key}="{_escape_label_value(value)}"')
    return "{" + ",".join(parts) + "}"


# ----------------------------------------------------------------------
# routes
# ----------------------------------------------------------------------


@router.post("/ingest", response_model=IngestOut)
async def ingest(body: IngestIn) -> IngestOut:
    from app.store.vm import vm  # lazy import per task constraints

    ts_ms = int(time.time() * 1000)
    lines: list[str] = []

    base_labels = {
        "service": body.service,
        "model": body.model,
        "provider": body.provider,
        "tenant_id": body.tenant_id,
    }

    if body.prompt_tokens is not None:
        labels = _labels({**base_labels, "type": "prompt"})
        lines.append(f"dockiq_llm_tokens_total{labels} {body.prompt_tokens} {ts_ms}")

    if body.completion_tokens is not None:
        labels = _labels({**base_labels, "type": "completion"})
        lines.append(f"dockiq_llm_tokens_total{labels} {body.completion_tokens} {ts_ms}")

    if body.latency_ms is not None:
        labels = _labels(
            {
                "service": body.service,
                "model": body.model,
                "operation": body.operation,
                "tenant_id": body.tenant_id,
            }
        )
        lines.append(
            f"dockiq_llm_request_latency_seconds{labels} {body.latency_ms / 1000.0} {ts_ms}"
        )

    cost_usd = body.cost_usd
    if cost_usd is None and (body.prompt_tokens is not None or body.completion_tokens is not None):
        cost_usd = estimate_cost_usd(body.model, body.prompt_tokens, body.completion_tokens)

    if cost_usd is not None:
        labels = _labels(base_labels)
        lines.append(f"dockiq_llm_cost_usd_total{labels} {cost_usd} {ts_ms}")

    if body.retrieval_ms is not None:
        labels = _labels(
            {
                "service": body.service,
                "vectordb": body.vectordb,
                "tenant_id": body.tenant_id,
            }
        )
        lines.append(
            f"dockiq_rag_retrieval_latency_seconds{labels} {body.retrieval_ms / 1000.0} {ts_ms}"
        )

    if lines:
        try:
            await vm.import_prometheus(lines)
        except Exception:  # noqa: BLE001 — never fail the ingest call on store issues
            log.exception("failed to write %d llm metric line(s) to VM", len(lines))

    return IngestOut(ok=True, lines_written=len(lines), cost_usd=cost_usd)


@router.get("/cost")
async def cost(service: str | None = None) -> dict:
    from app.store.vm import vm  # lazy import

    metric = "dockiq_llm_cost_usd_total"
    selector = f'{{service="{_escape_label_value(service)}"}}' if service else ""
    # last_over_time so sparse LLM samples are still returned (VM instant
    # queries otherwise miss single/infrequent points).
    promql = f"sum(last_over_time({metric}{selector}[1h])) by (service, model)"
    return await vm.query(promql)


@router.get("/latency")
async def latency(service: str | None = None) -> dict:
    from app.store.vm import vm  # lazy import

    metric = "dockiq_llm_request_latency_seconds"
    selector = f'{{service="{_escape_label_value(service)}"}}' if service else ""
    promql = f"avg(last_over_time({metric}{selector}[1h])) by (service, model)"
    return await vm.query(promql)


@router.get("/status")
async def status() -> dict:
    return {"enabled": True, "price_table_models": sorted(PRICE_TABLE.keys())}
