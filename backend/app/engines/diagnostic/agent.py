"""The Diagnostic Query Agent (Engine 11).

A natural-language front door to DockIQ. A question like *"why is carevora-api
slow?"* or *"which containers are using the most memory?"* is answered by letting
Claude call read-only tools (metrics, logs, topology, alerts, events) to gather
evidence, then synthesise a grounded, cited answer.

Powered by the Claude API (see docs; model configurable via DIAGNOSTIC_MODEL).
All tools are strictly read-only — the agent can observe but never act.
"""
from __future__ import annotations

import logging

from anthropic import AsyncAnthropic

from app.core.config import settings
from app.engines.diagnostic.tools import TOOL_DEFINITIONS, execute_tool

log = logging.getLogger("dockiq.diagnostic")

SYSTEM_PROMPT = """You are DockIQ's Diagnostic Agent — an expert SRE embedded in a \
Docker Infrastructure Intelligence Platform. You answer operators' natural-language \
questions about their running containers by calling read-only tools to gather \
evidence, then giving a clear, grounded answer.

How DockIQ models the world:
- Every container is classified with a ROLE (api/worker/database/cache/queue/frontend/\
vectordb/ai/proxy) and a TECH (fastapi/postgres/redis/qdrant/...).
- Metrics live in VictoriaMetrics as `dockiq_*` series labelled by container, \
container_id, host_id, tenant. Logs live in Loki (LogQL). The service dependency \
graph (topology) shows who depends on whom, so you can reason about blast radius \
and find a root cause upstream of the symptom.
- Baselines (median/MAD) tell you what's normal, so you can say "70% is abnormal \
because this container normally sits at 20%".

Method:
1. Break the question into what evidence you need.
2. Call tools to get it — prefer specific queries. Correlate metrics with logs, \
events (restarts/OOM), topology, and baselines.
3. When you have enough, STOP calling tools and answer.

Answer style: lead with the direct answer, then the evidence and reasoning. If you \
identify a root cause distinct from the symptom (e.g. an API is slow because its \
vector DB is CPU-bound), say so explicitly and name the affected/dependent services. \
Be concise. If the data is insufficient, say what's missing. You cannot take actions \
— only observe and recommend."""


class DiagnosticAgent:
    def __init__(self) -> None:
        self._client: AsyncAnthropic | None = None

    def _client_or_none(self) -> AsyncAnthropic | None:
        if not settings.diagnostic_enabled:
            return None
        if self._client is None:
            self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    async def ask(self, question: str, tenant_id: str, context: str | None = None) -> dict:
        """Answer a natural-language question. Returns {answer, steps, model}."""
        client = self._client_or_none()
        if client is None:
            return {
                "answer": None,
                "error": "Diagnostic agent is not configured. Set ANTHROPIC_API_KEY "
                "in the backend environment to enable natural-language diagnostics.",
                "steps": [],
                "model": settings.diagnostic_model,
            }

        user_content = question if not context else f"{question}\n\nContext: {context}"
        messages: list[dict] = [{"role": "user", "content": user_content}]
        steps: list[dict] = []

        for _ in range(settings.diagnostic_max_iterations):
            try:
                resp = await client.messages.create(
                    model=settings.diagnostic_model,
                    max_tokens=12000,
                    system=SYSTEM_PROMPT,
                    tools=TOOL_DEFINITIONS,
                    messages=messages,
                )
            except Exception as exc:  # noqa: BLE001 — surface API errors to the caller
                log.warning("diagnostic API call failed: %s", exc)
                return {
                    "answer": None,
                    "error": f"Claude API error: {type(exc).__name__}: {exc}",
                    "steps": steps,
                    "model": settings.diagnostic_model,
                }

            # Preserve full assistant content (incl. any thinking blocks) for the
            # next turn — required for tool-use continuation.
            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                answer = "".join(
                    b.text for b in resp.content if getattr(b, "type", None) == "text"
                )
                return {"answer": answer, "steps": steps, "model": settings.diagnostic_model}

            # Execute every requested tool, return all results in one user message.
            tool_results = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                result = await execute_tool(block.name, dict(block.input), tenant_id)
                steps.append({"tool": block.name, "input": block.input})
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        return {
            "answer": "I gathered evidence but reached the tool-call limit before "
            "finishing. Try narrowing the question.",
            "steps": steps,
            "model": settings.diagnostic_model,
        }


# Module singleton.
agent = DiagnosticAgent()
