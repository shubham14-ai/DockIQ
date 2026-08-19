"""Metrics query API: proxies PromQL to VictoriaMetrics.

Tenant scoping is a no-op stub in the MVP (see docs/phase1-agent-protocol.md);
this simply forwards the query and returns VM's JSON response as-is.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.store.vm import vm

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/query")
async def query(query: str = Query(..., description="PromQL instant query")) -> dict:
    return await vm.query(query)


@router.get("/query_range")
async def query_range(
    query: str = Query(..., description="PromQL range query"),
    start: str = Query(..., description="Range start (unix ts or RFC3339)"),
    end: str = Query(..., description="Range end (unix ts or RFC3339)"),
    step: str = Query(..., description="Query resolution step, e.g. '15s'"),
) -> dict:
    return await vm.query_range(query, start, end, step)
