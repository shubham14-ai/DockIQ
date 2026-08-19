"""Logs query API: proxies LogQL to Loki.

Tenant scoping is a no-op stub in the MVP (see docs/phase1-agent-protocol.md);
this simply forwards the query and returns Loki's JSON response as-is.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.store.loki import loki

router = APIRouter(tags=["logs"])


@router.get("/logs/query")
async def query(
    query: str = Query(..., description="LogQL query"),
    start: str | None = Query(None, description="Range start (unix ts or RFC3339)"),
    end: str | None = Query(None, description="Range end (unix ts or RFC3339)"),
    limit: int = Query(100, description="Max entries to return"),
) -> dict:
    return await loki.query_range(query, start, end, limit)


@router.get("/containers/{container_id}/logs")
async def container_logs(
    container_id: str,
    limit: int = Query(100, description="Max entries to return"),
) -> dict:
    logql = f'{{container_id="{container_id}"}}'
    return await loki.query_range(logql, None, None, limit)
