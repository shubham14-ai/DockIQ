"""``POST /diagnostics/ask`` — natural-language diagnostics (Engine 11)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
from app.engines.diagnostic.agent import agent

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


class AskRequest(BaseModel):
    question: str
    tenant_id: str | None = None
    context: str | None = None


class Step(BaseModel):
    tool: str
    input: dict


class AskResponse(BaseModel):
    answer: str | None = None
    error: str | None = None
    steps: list[Step] = []
    model: str


@router.get("/status")
async def status() -> dict:
    """Whether the diagnostic agent is configured (has an API key)."""
    return {"enabled": settings.diagnostic_enabled, "model": settings.diagnostic_model}


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    tenant_id = req.tenant_id or settings.default_tenant
    result = await agent.ask(req.question, tenant_id=tenant_id, context=req.context)
    return AskResponse(**result)
